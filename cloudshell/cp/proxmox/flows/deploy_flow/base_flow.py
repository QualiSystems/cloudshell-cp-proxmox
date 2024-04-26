import logging
from abc import abstractmethod

from cloudshell.api.cloudshell_api import CloudShellAPISession, ReservationInfo
from cloudshell.cp.core.cancellation_manager import CancellationContextManager
from cloudshell.cp.core.flows import AbstractDeployFlow
from cloudshell.cp.core.request_actions import DeployVMRequestActions
from cloudshell.cp.core.request_actions.models import (
    VmDetailsData,
    DeployAppResult,
    Attribute
)
from cloudshell.cp.core.rollback import RollbackCommandsManager
from cloudshell.cp.core.utils.name_generator import NameGenerator

from cloudshell.cp.proxmox.flows.deploy_flow.commands import CloneVMCommand

from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from cloudshell.cp.proxmox.models.deploy_app import BaseProxmoxDeployApp
from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig

logger = logging.getLogger(__name__)


class AbstractProxmoxDeployFlow(AbstractDeployFlow):
    def __init__(
            self,
            api: ProxmoxHandler,
            resource_config: ProxmoxResourceConfig,
            cs_api: CloudShellAPISession,
            reservation_info: ReservationInfo,
            cancellation_manager: CancellationContextManager,
    ):
        super().__init__(logger=logger)
        self._resource_config = resource_config
        self._reservation_info = reservation_info
        self._cs_api = cs_api
        self._cancellation_manager = cancellation_manager
        self._rollback_manager = RollbackCommandsManager(logger)
        self.proxmox_api = api
        self.generate_name = NameGenerator(max_length=80)

    @abstractmethod
    def _apply_cloud_init(
        self,
        deployed_vm_id: int,
        deploy_app: BaseProxmoxDeployApp
    ) -> None:
        """"""
        pass

    @abstractmethod
    def _prepare_vm_details_data(
            self,
            deployed_vm_id: int,
            deploy_app: BaseProxmoxDeployApp
    ) -> VmDetailsData:
        """Prepare CloudShell VM Details model."""
        pass

    @abstractmethod
    def _get_source_instance(self, deploy_app: BaseProxmoxDeployApp):
        """"""
        pass

    @abstractmethod
    def _get_instance_snapshot(self, deploy_app: BaseProxmoxDeployApp):
        """"""
        pass

    @abstractmethod
    def _is_full_disk_clone(self, deploy_app: BaseProxmoxDeployApp) -> bool:
        """Get disk clone mode.

        True  - Full disk clone
        False - Linked clone
        """
        pass

    def _get_target_storage(self, deploy_app: BaseProxmoxDeployApp) -> str:
        """Get target storage."""
        return deploy_app.target_storage

    def _get_target_node(self, deploy_app: BaseProxmoxDeployApp) -> str:
        """Get target node name."""
        return deploy_app.target_node

    def _prepare_app_attrs(
            self, deploy_app: BaseProxmoxDeployApp, vm_id: int
    ) -> list[Attribute]:
        attrs = []

        # link_attr = get_deploy_app_vm_console_link_attr(
        #     deploy_app, self._resource_config, vm, vm.si
        # )
        # if link_attr:
        #     attrs.append(link_attr)

        return attrs

    def _prepare_deploy_app_result(
            self,
            deployed_vm_id: int,
            deploy_app: BaseProxmoxDeployApp,
            instance_name: str,
    ) -> DeployAppResult:
        vm_details_data = self._prepare_vm_details_data(
            deployed_vm_id=deployed_vm_id,
            deploy_app=deploy_app,
        )

        logger.info(f"Prepared VM details: {vm_details_data}")

        return DeployAppResult(
            actionId=deploy_app.actionId,
            vmUuid=str(deployed_vm_id),
            vmName=instance_name,
            vmDetailsData=vm_details_data,
            deployedAppAdditionalData={
                "ip_regex": deploy_app.ip_regex,
                "refresh_ip_timeout": deploy_app.refresh_ip_timeout,
                "auto_power_off": deploy_app.auto_power_off,
                "auto_delete": deploy_app.auto_delete,
            },
            deployedAppAttributes=self._prepare_app_attrs(deploy_app, deployed_vm_id),
        )

    def _create_vm(
        self,
        deploy_app: BaseProxmoxDeployApp,
        instance_name: str,
    ) -> int:
        """"""
        with self._cancellation_manager:
            src_instance_id = self._get_source_instance(deploy_app)

        with self._cancellation_manager:
            snapshot = self._get_instance_snapshot(deploy_app)

        with self._cancellation_manager:
            target_storage = self._get_target_storage(deploy_app)

        with self._cancellation_manager:
            target_node = self._get_target_node(deploy_app)

        return CloneVMCommand(
            api=self.proxmox_api,
            rollback_manager=self._rollback_manager,
            cancellation_manager=self._cancellation_manager,
            instance_id=src_instance_id,
            instance_name=instance_name,
            instance_snapshot=snapshot,
            full=self._is_full_disk_clone(deploy_app=deploy_app),
            target_storage=target_storage,
            target_node=target_node,
        ).execute()

    def _deploy(self, request_actions: DeployVMRequestActions) -> DeployAppResult:
        """Deploy Proxmox Instance."""
        conf = self._resource_config
        # noinspection PyTypeChecker
        deploy_app: BaseProxmoxDeployApp = request_actions.deploy_app
        target_storage = deploy_app.target_storage or conf.shared_storage

        if deploy_app.autogenerated_name:
            instance_name = self.generate_name(deploy_app.app_name)
        else:
            instance_name = deploy_app.app_name

        logger.info(f"Generated name for the Instance: {instance_name}")

        with self._rollback_manager:
            logger.info(f"Creating VM {instance_name}")
            deployed_vm_id = self._create_vm(
                deploy_app=deploy_app,
                instance_name=instance_name,
            )
            # self._add_tags(deployed_vm)
            self._apply_cloud_init(deploy_app, deployed_vm_id)

        logger.info(f"Preparing Deploy App result for the {deployed_vm_id}")
        return self._prepare_deploy_app_result(
            deployed_vm_id=deployed_vm_id,
            deploy_app=deploy_app,
            instance_name=instance_name,
        )

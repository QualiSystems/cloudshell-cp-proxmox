import logging
from abc import abstractmethod
from contextlib import suppress
from typing import Dict

from cloudshell.api.cloudshell_api import CloudShellAPISession, ReservationInfo
from cloudshell.cp.core.cancellation_manager import CancellationContextManager
from cloudshell.cp.core.flows import AbstractDeployFlow
from cloudshell.cp.core.request_actions import DeployVMRequestActions
from cloudshell.cp.core.request_actions.models import VmDetailsData, DeployAppResult, \
    Attribute
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
    def _prepare_vm_details_data(
            self, deployed_vm_id: int, deploy_app: BaseProxmoxDeployApp
    ) -> VmDetailsData:
        """Prepare CloudShell VM Details model."""
        pass

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
            vm_name: str,
    ) -> DeployAppResult:
        vm_details_data = self._prepare_vm_details_data(
            deployed_vm_id=deployed_vm_id,
            deploy_app=deploy_app,
        )

        logger.info(f"Prepared VM details: {vm_details_data}")

        return DeployAppResult(
            actionId=deploy_app.actionId,
            vmUuid=str(deployed_vm_id),
            vmName=vm_name,
            vmDetailsData=vm_details_data,
            deployedAppAdditionalData={
                "ip_regex": deploy_app.ip_regex,
                "refresh_ip_timeout": deploy_app.refresh_ip_timeout,
                "auto_power_off": deploy_app.auto_power_off,
                "auto_delete": deploy_app.auto_delete,
            },
            deployedAppAttributes=self._prepare_app_attrs(deploy_app, deployed_vm_id),
        )


class AbstractProxmoxDeployVMFlow(AbstractProxmoxDeployFlow):
    @abstractmethod
    def _get_vm_template(
            self, deploy_app: BaseProxmoxDeployApp
    ):
        """Get VM template to clone VM from."""
        pass

    def _get_vm_snapshot(
            self, deploy_app: BaseProxmoxDeployApp, vm_template: str
    ) -> str:
        """Get VM Snapshot to clone from."""
        pass

    def _create_vm(
            self,
            deploy_app: BaseProxmoxDeployApp,
            vm_name: str,
            # vm_resource_pool: ResourcePoolHandler,
            vm_storage: str,
            # vm_folder: FolderHandler,
            # dc: DcHandler,
            # ) -> VmHandler:
    ) -> int:
        """Create VM on the vCenter."""
        with self._cancellation_manager:
            vm_template = self._get_vm_template(deploy_app)

        with self._cancellation_manager:
            snapshot = self._get_vm_snapshot(deploy_app, vm_template)

        # config_spec = ConfigSpecHandler.from_deploy_add(deploy_app)
        # if deploy_app.copy_source_uuid:
        #     config_spec.bios_uuid = vm_template.bios_uuid

        return CloneVMCommand(
            api=self.proxmox_api,
            rollback_manager=self._rollback_manager,
            cancellation_manager=self._cancellation_manager,
            vm_template=vm_template,
            vm_name=vm_name,
            vm_storage=vm_storage,
            vm_snapshot=snapshot,
        ).execute()

    def _apply_cloud_init(self, node: str, deploy_app: BaseProxmoxDeployApp,
                          deployed_vm_id: int):
        with self._cancellation_manager:
            node = self.proxmox_api.get_node_by_vmid(deployed_vm_id)
            # we create customization spec here and will set it on PowerOn command
            data = {"ciuser": deploy_app.user, "cipassword": deploy_app.password}
            self.proxmox_api.set_user_data(
                node=node,
                vm_id=deployed_vm_id,
                user_data=data
            )

    def _deploy(self, request_actions: DeployVMRequestActions) -> DeployAppResult:
        """Deploy VCenter VM."""
        conf = self._resource_config
        # noinspection PyTypeChecker
        deploy_app: BaseProxmoxDeployApp = request_actions.deploy_app
        storage = conf.shared_storage

        if deploy_app.autogenerated_name:
            vm_name = self.generate_name(deploy_app.app_name)
        else:
            vm_name = deploy_app.app_name

        logger.info(f"Generated name for the VM: {vm_name}")

        with self._cancellation_manager:
            logger.info(f"Getting VM storage")
            # storage = self.proxmox_api.get_vm_ifaces_info(100)

        with self._rollback_manager:
            logger.info(f"Creating VM {vm_name}")
            deployed_vm_id = self._create_vm(
                deploy_app=deploy_app,
                vm_name=vm_name,
                vm_storage=storage,
            )
            # self._add_tags(deployed_vm)
            self._apply_cloud_init(deploy_app, deployed_vm_id)

        logger.info(f"Preparing Deploy App result for the {deployed_vm_id}")
        return self._prepare_deploy_app_result(
            deployed_vm_id=deployed_vm_id,
            deploy_app=deploy_app,
            vm_name=vm_name,
        )

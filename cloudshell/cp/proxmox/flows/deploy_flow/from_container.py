from __future__ import annotations

from cloudshell.shell.core.driver_utils import GlobalLock

from cloudshell.cp.proxmox.flows.deploy_flow import AbstractProxmoxDeployFlow
from cloudshell.cp.proxmox.flows.deploy_flow.commands import CloneVMCommand
from cloudshell.cp.proxmox.models.deploy_app import (
    BaseProxmoxDeployApp,
    InstanceFromContainerDeployApp,
)
from cloudshell.cp.proxmox.utils.threading import LockHandler

containers_lock = LockHandler()


class ProxmoxDeployInstanceFromContainerFlow(AbstractProxmoxDeployFlow):
    def _get_instance_snapshot(self, deploy_app: InstanceFromContainerDeployApp) -> str | None:
        return deploy_app.snapshot

    def _is_full_disk_clone(self, deploy_app: InstanceFromContainerDeployApp) -> bool:
        return True

    def _apply_cloud_init(
        self, deployed_vm_id: int, deploy_app: InstanceFromContainerDeployApp
    ) -> None:
        pass

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

        with containers_lock.lock(src_instance_id):
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

    def _get_source_instance(self, deploy_app: InstanceFromContainerDeployApp) -> int:
        """Get Source VM ID."""
        return int(deploy_app.container_id)

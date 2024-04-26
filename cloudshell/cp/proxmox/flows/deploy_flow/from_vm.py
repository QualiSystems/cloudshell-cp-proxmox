from cloudshell.cp.core.request_actions.models import VmDetailsData

from cloudshell.cp.proxmox.actions.vm_details import VMDetailsActions
from cloudshell.cp.proxmox.flows.deploy_flow import AbstractProxmoxDeployFlow
from cloudshell.cp.proxmox.models.deploy_app import InstanceFromVMDeployApp


class ProxmoxDeployInstanceFromVMFlow(AbstractProxmoxDeployFlow):
    def _get_instance_snapshot(self, deploy_app: InstanceFromVMDeployApp) -> str:
        """Get snapshot name."""
        return deploy_app.sm_snapshot

    def _apply_cloud_init(
        self,
        deployed_vm_id: int,
        deploy_app: InstanceFromVMDeployApp
    ) -> None:
        """"""
        pass

    def _get_source_instance(self, deploy_app: InstanceFromVMDeployApp) -> int:
        """Get Source VM ID."""
        return int(deploy_app.vm_id)

    def _is_full_disk_clone(self, deploy_app: InstanceFromVMDeployApp) -> bool:
        """Full copy of all disks is always done when cloning a normal VM."""
        return True

    def _prepare_vm_details_data(
        self,
        deployed_vm_id: int,
        deploy_app: InstanceFromVMDeployApp
    ) -> VmDetailsData:
        """Prepare CloudShell VM Details model."""
        vm_details_actions = VMDetailsActions(
            self.proxmox_api,
            self._resource_config,
            self._cancellation_manager,
        )
        return vm_details_actions.create(deployed_vm_id, deploy_app)


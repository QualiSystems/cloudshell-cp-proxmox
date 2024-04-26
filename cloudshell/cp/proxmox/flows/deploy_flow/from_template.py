from cloudshell.cp.core.request_actions.models import VmDetailsData

from cloudshell.cp.proxmox.actions.vm_details import VMDetailsActions
from cloudshell.cp.proxmox.flows.deploy_flow import AbstractProxmoxDeployFlow
from cloudshell.cp.proxmox.models.deploy_app import InstanceFromTemplateDeployApp


class ProxmoxDeployInstanceFromTemplateFlow(AbstractProxmoxDeployFlow):

    def _get_instance_snapshot(self, deploy_app: InstanceFromTemplateDeployApp) -> None:
        """Get snapshot name."""
        return None

    def _apply_cloud_init(
        self,
        deployed_vm_id: int,
        deploy_app: InstanceFromTemplateDeployApp
    ) -> None:
        """"""
        pass

    def _get_source_instance(self, deploy_app: InstanceFromTemplateDeployApp) -> int:
        """Get Source VM ID."""
        return int(deploy_app.template_id)

    def _is_full_disk_clone(self, deploy_app: InstanceFromTemplateDeployApp) -> bool:
        """Determine is disk cloning full or not."""
        return deploy_app.clone_mode or False

    def _prepare_vm_details_data(
        self,
        deployed_vm_id: int,
        deploy_app: InstanceFromTemplateDeployApp
    ) -> VmDetailsData:
        """Prepare CloudShell VM Details model."""
        vm_details_actions = VMDetailsActions(
            self.proxmox_api,
            self._resource_config,
            self._cancellation_manager,
        )
        return vm_details_actions.create(deployed_vm_id, deploy_app)


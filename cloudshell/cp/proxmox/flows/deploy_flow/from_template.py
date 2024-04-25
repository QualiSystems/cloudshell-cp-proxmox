from cloudshell.cp.core.request_actions.models import VmDetailsData

from cloudshell.cp.proxmox.flows.deploy_flow import AbstractProxmoxDeployFlow
from cloudshell.cp.proxmox.models.deploy_app import InstanceFromTemplateDeployApp


class ProxmoxDeployInstanceFromTemplateFlow(AbstractProxmoxDeployFlow):

    def _get_instance_snapshot(self, deploy_app: InstanceFromTemplateDeployApp) -> None:
        """Get snapshot name."""
        return None

    def _apply_cloud_init(
        self,
        deploy_app: InstanceFromTemplateDeployApp,
        deployed_vm_id: int
    ) -> None:
        """"""
        pass

    def _get_source_instance(self, deploy_app: InstanceFromTemplateDeployApp) -> int:
        """Get Source VM ID."""
        return int(deploy_app.template_id)

    def _is_full_disk_clone(self, deploy_app: InstanceFromTemplateDeployApp) -> bool:
        """Determine is disk cloning full or not."""
        return False  # TODO

    def _prepare_vm_details_data(
        self,
        deployed_vm: object,
        deploy_app: InstanceFromTemplateDeployApp
    ) -> VmDetailsData:
        pass

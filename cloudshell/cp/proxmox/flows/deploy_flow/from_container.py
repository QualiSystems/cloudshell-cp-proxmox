from cloudshell.cp.core.request_actions.models import VmDetailsData
from cloudshell.cp.proxmox.flows.deploy_flow import AbstractProxmoxDeployFlow
from cloudshell.cp.proxmox.models.deploy_app import (
    BaseProxmoxDeployApp,
    InstanceFromContainerDeployApp,
)


class ProxmoxDeployContainerFromImageFlow(AbstractProxmoxDeployFlow):
    def _apply_cloud_init(
        self, deployed_vm_id: int, deploy_app: BaseProxmoxDeployApp
    ) -> None:
        pass

    def _get_source_instance(self, deploy_app: InstanceFromContainerDeployApp) -> int:
        """Get Source VM ID."""
        return int(deploy_app.container_id)

    def _get_instance_snapshot(self, deploy_app: BaseProxmoxDeployApp):
        pass

    def _is_full_disk_clone(self, deploy_app: BaseProxmoxDeployApp) -> bool:
        return True

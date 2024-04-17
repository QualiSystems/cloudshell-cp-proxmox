from cloudshell.cp.core.request_actions.models import VmDetailsData

from cloudshell.cp.proxmox.flows.deploy_flow import AbstractProxmoxDeployVMFlow
from cloudshell.cp.proxmox.models.deploy_app import BaseProxmoxDeployApp


class ProxmoxDeployVMFromTemplateFlow(AbstractProxmoxDeployVMFlow):

    def _get_vm_template(self, deploy_app: BaseProxmoxDeployApp):
        pass

    def _prepare_vm_details_data(self, deployed_vm: object,
                                 deploy_app: BaseProxmoxDeployApp) -> VmDetailsData:
        pass

    def _create_vm(self, deploy_app: BaseProxmoxDeployApp, vm_name: str):
        pass

from __future__ import annotations

from cloudshell.cp.proxmox.models import deploy_app
from cloudshell.cp.proxmox.utils.instance_type import InstanceType

from .base_flow import AbstractProxmoxDeployFlow
from .from_container import ProxmoxDeployContainerFromImageFlow
from .from_qemu import ProxmoxDeployVMFromQEMUImageFlow
from .from_template import ProxmoxDeployInstanceFromTemplateFlow
from .from_vm import ProxmoxDeployInstanceFromVMFlow

DEPLOY_APP_TO_FLOW_PARAMS = (
    (
        deploy_app.InstanceFromVMDeployApp,
        (ProxmoxDeployInstanceFromVMFlow, InstanceType.VM),
    ),
    (
        deploy_app.InstanceFromTemplateDeployApp,
        (ProxmoxDeployInstanceFromTemplateFlow, InstanceType.VM),
    ),
    (
        deploy_app.InstanceFromContainerImageDeployApp,
        (ProxmoxDeployContainerFromImageFlow, InstanceType.CONTAINER),
    ),
    (
        deploy_app.InstanceFromQEMUImageDeployApp,
        (ProxmoxDeployVMFromQEMUImageFlow, InstanceType.CONTAINER),
    ),
)


def get_deploy_params(request_action) -> type[AbstractProxmoxDeployFlow]:
    da = request_action.deploy_app
    for deploy_class, deploy_params in DEPLOY_APP_TO_FLOW_PARAMS:
        if isinstance(da, deploy_class):
            return deploy_params
    raise NotImplementedError(f"Not supported deployment type {type(da)}")


__all__ = (
    ProxmoxDeployInstanceFromVMFlow,
    ProxmoxDeployInstanceFromTemplateFlow,
    ProxmoxDeployContainerFromImageFlow,
    ProxmoxDeployVMFromQEMUImageFlow,
    get_deploy_params,
)

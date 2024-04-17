from __future__ import annotations

from .base_flow import AbstractProxmoxDeployVMFlow
from .from_qemu import ProxmoxDeployVMFromQEMUImageFlow
from .from_container_image import ProxmoxDeployContainerFromImageFlow
from .from_template import ProxmoxDeployVMFromTemplateFlow
from .from_vm import ProxmoxDeployVMFromVMFlow

from cloudshell.cp.proxmox.models import deploy_app

DEPLOY_APP_TO_FLOW = (
    (deploy_app.VMFromVMDeployApp, ProxmoxDeployVMFromVMFlow),
    (deploy_app.VMFromTemplateDeployApp, ProxmoxDeployVMFromTemplateFlow),
    (deploy_app.ContainerFromImageDeployApp, ProxmoxDeployContainerFromImageFlow),
    (deploy_app.VMFromQEMUImageDeployApp, ProxmoxDeployVMFromQEMUImageFlow),
)


def get_deploy_flow(request_action) -> type[AbstractProxmoxDeployVMFlow]:
    da = request_action.deploy_app
    for deploy_class, deploy_flow in DEPLOY_APP_TO_FLOW:
        if isinstance(da, deploy_class):
            return deploy_flow
    raise NotImplementedError(f"Not supported deployment type {type(da)}")


__all__ = (
    ProxmoxDeployVMFromVMFlow,
    ProxmoxDeployVMFromTemplateFlow,
    ProxmoxDeployContainerFromImageFlow,
    ProxmoxDeployVMFromQEMUImageFlow,
    get_deploy_flow,
)

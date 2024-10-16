from __future__ import annotations

from cloudshell.cp.proxmox.models import deploy_app

from .base_flow import AbstractProxmoxDeployVMFlow
from .from_image import (
    ProxmoxDeployContainerFromLocalImageFlow,
    ProxmoxDeployContainerFromRemoteImageFlow,
)
from .from_qemu import ProxmoxDeployVMFromQEMUImageFlow
from .from_template import ProxmoxDeployVMFromTemplateFlow
from .from_vm import ProxmoxDeployVMFromVMFlow

DEPLOY_APP_TO_FLOW = (
    (deploy_app.VMFromVMDeployApp, ProxmoxDeployVMFromVMFlow),
    (deploy_app.VMFromTemplateDeployApp, ProxmoxDeployVMFromTemplateFlow),
    (deploy_app.VMFromQEMUImageDeployApp, ProxmoxDeployVMFromQEMUImageFlow),
    (
        deploy_app.ContainerFromLocalImageDeployApp,
        ProxmoxDeployContainerFromLocalImageFlow,
    ),  # noqa: E501
    (
        deploy_app.ContainerFromRemoteImageDeployApp,
        ProxmoxDeployContainerFromRemoteImageFlow,
    ),  # noqa: E501
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
    ProxmoxDeployVMFromQEMUImageFlow,
    ProxmoxDeployContainerFromLocalImageFlow,
    ProxmoxDeployContainerFromRemoteImageFlow,
    get_deploy_flow,
)

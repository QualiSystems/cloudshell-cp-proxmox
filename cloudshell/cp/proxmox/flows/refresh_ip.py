from __future__ import annotations

from cloudshell.cp.core.cancellation_manager import CancellationContextManager

from cloudshell.cp.proxmox.actions.vm_network import VMNetworkActions
from cloudshell.cp.proxmox.exceptions import VmIsNotPowered
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from cloudshell.cp.proxmox.models.deployed_app import BaseProxmoxDeployedApp
from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig


def refresh_ip(
    deployed_app: BaseProxmoxDeployedApp,
    resource_conf: ProxmoxResourceConfig,
    cancellation_manager: CancellationContextManager,
) -> str:
    api = ProxmoxHandler.from_config(resource_conf)
    vm_id = int(deployed_app.vmdetails.uid)
    if api.get_vm_status(vm_id).lower() != "running":
        raise VmIsNotPowered(vm_id)

    actions = VMNetworkActions(resource_conf, cancellation_manager)
    ip = actions.get_vm_ip(
            api,
            vm_id,
            ip_regex=deployed_app.ip_regex,
            timeout=deployed_app.refresh_ip_timeout,
        )
    if ip != deployed_app.private_ip:
        deployed_app.update_private_ip(deployed_app.name, ip)
    return ip

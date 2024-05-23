from __future__ import annotations

from cloudshell.cp.core.cancellation_manager import CancellationContextManager

from cloudshell.cp.proxmox.actions.vm_network import VMNetworkActions
from cloudshell.cp.proxmox.exceptions import VmIsNotPowered
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from cloudshell.cp.proxmox.models.deployed_app import BaseProxmoxDeployedApp
from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig
from cloudshell.cp.proxmox.utils.power_state import PowerState


def refresh_ip(
    si: ProxmoxHandler,
    deployed_app: BaseProxmoxDeployedApp,
    resource_conf: ProxmoxResourceConfig,
    cancellation_manager: CancellationContextManager,
) -> str:
    instance_id = int(deployed_app.vmdetails.uid)
    if si.get_instance_status(instance_id) != PowerState.RUNNING:
        raise VmIsNotPowered(instance_id)

    actions = VMNetworkActions(resource_conf, cancellation_manager)
    instance_network_details = si.get_instance_ifaces_info(instance_id)
    ip = actions.get_vm_ip(
            instance_id,
            instance_network_details,
            ip_regex=deployed_app.ip_regex,
            timeout=deployed_app.refresh_ip_timeout,
        )
    if ip != deployed_app.private_ip:
        deployed_app.update_private_ip(deployed_app.name, ip)
    return ip

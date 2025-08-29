from __future__ import annotations

from contextlib import suppress

from cloudshell.cli.service.cli import CLI
from cloudshell.cp.core.cancellation_manager import CancellationContextManager
from cloudshell.cp.proxmox.actions.vm_network import VMNetworkActions
from cloudshell.cp.proxmox.exceptions import VmIsNotPowered, VmDoesNotExistException, \
    BaseProxmoxException
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from cloudshell.cp.proxmox.models.deployed_app import BaseProxmoxDeployedApp
from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig
from cloudshell.cp.proxmox.utils.instance_type import InstanceType
from cloudshell.cp.proxmox.utils.power_state import PowerState


def refresh_ip(
    cli: CLI,
    deployed_app: BaseProxmoxDeployedApp,
    resource_conf: ProxmoxResourceConfig,
    cancellation_manager: CancellationContextManager,
) -> str:
    ip = ""
    timeout = deployed_app.refresh_ip_timeout
    instance_id = int(deployed_app.vmdetails.uid)
    si = ProxmoxHandler.from_config(resource_conf)
    instance_conf = None
    with suppress(BaseProxmoxException):
        instance_conf = si.get_instance(instance_id)
    if not instance_conf:
        si = ProxmoxHandler.from_config(
            resource_conf,
            InstanceType.CONTAINER
        )
    if not deployed_app.wait_for_ip:
        timeout = 1
    try:

        if si.get_instance_status(instance_id) != PowerState.RUNNING:
            raise VmIsNotPowered(instance_id)

        actions = VMNetworkActions(resource_conf, cancellation_manager)
        ip = actions.get_vm_ip(
            si,
            instance_id,
            ip_regex=deployed_app.ip_regex,
            timeout=timeout,
            cli=cli
        )
        if ip != deployed_app.private_ip:
            deployed_app.update_private_ip(deployed_app.name, ip)
    except Exception:
        if deployed_app.wait_for_ip:
            raise
    return ip

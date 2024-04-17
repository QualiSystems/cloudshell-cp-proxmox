from __future__ import annotations

import logging
import re
import time
from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from cloudshell.cp.proxmox.exceptions import VMIPNotFoundException
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler

if TYPE_CHECKING:
    from cloudshell.cp.core.cancellation_manager import CancellationContextManager

    from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig


logger = logging.getLogger(__name__)


class VMNetworkActions:
    QUALI_NETWORK_PREFIX = "QS_"
    DEFAULT_IP_REGEX = ".*"
    DEFAULT_IP_DELAY = 5

    def __init__(
        self,
        resource_conf: ProxmoxResourceConfig,
        cancellation_manager: CancellationContextManager | nullcontext = nullcontext(),
    ):
        self._resource_conf = resource_conf
        self._cancellation_manager = cancellation_manager

    def is_quali_network(self, network_name: str) -> bool:
        return network_name.startswith(self.QUALI_NETWORK_PREFIX)

    def _find_vm_ip(
        self,
        api: ProxmoxHandler,
        vm: int,
        is_ip_pass_regex: callable[[str | None], bool],
    ) -> str | None:
        logger.debug(f"Searching for the IPv4 address of the {vm}")

        node = api.get_node_by_vmid(vm)
        for vnic in api.get_vm_ifaces_info(node, vm):
            ip = vnic.get("ipv4")
            name = vnic.get("name")
            logger.debug(f"Checking {name} with ip {ip}")
            if is_ip_pass_regex(ip):
                logger.debug(f"Found IP {ip} on {name}")
                return ip

    def get_vm_ip(
        self,
        api: ProxmoxHandler,
        vm_id: int,
        ip_regex: str | None = None,
        timeout: int = 0,
    ) -> str:
        logger.info(f"Getting IP address for the VM {vm_id} from the vCenter")
        timeout_time = datetime.now() + timedelta(seconds=timeout)
        is_ip_pass_regex = get_ip_regex_match_func(ip_regex)

        while True:
            with self._cancellation_manager:
                ip = self._find_vm_ip(api, vm_id, is_ip_pass_regex)
            if ip:
                break
            if datetime.now() > timeout_time:
                raise VMIPNotFoundException(ip_regex)
            time.sleep(self.DEFAULT_IP_DELAY)
        return ip


def get_ip_regex_match_func(ip_regex=None) -> callable[[str | None], bool]:
    """Get Regex Match function for the VM IP address."""
    pattern = re.compile(ip_regex) if ip_regex is not None else None

    def is_ip_pass_regex(ip: str | None) -> bool:
        if not ip:
            result = False
        elif not pattern:
            result = True
        else:
            result = bool(pattern.match(ip))
        return result

    return is_ip_pass_regex

from __future__ import annotations

import logging
import re
import time
from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from cloudshell.cli.service.cli import CLI
from cloudshell.cli.service.command_mode import CommandMode

from cloudshell.cp.proxmox.cli.websocket_session import WebSocketSession
from cloudshell.cp.proxmox.exceptions import VMIPNotFoundException
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from cloudshell.cp.proxmox.utils.instance_type import InstanceType

if TYPE_CHECKING:
    from cloudshell.cp.core.cancellation_manager import CancellationContextManager
    from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig


logger = logging.getLogger(__name__)


class VMNetworkActions:
    IP_REGEX = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
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
        logger.debug(f"Searching for the IPv4 address of the {vm} instance")

        for vnic in api.get_instance_ifaces_info(vm).values():
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
        cli: CLI | None = None,
        ip_regex: str | None = None,
        timeout: int = 0,
    ) -> str:
        logger.info(f"Getting IP address for the VM {vm_id} from the Proxmox")
        timeout_time = datetime.now() + timedelta(seconds=timeout)
        instance = api.get_instance(vm_id)
        is_ip_pass_regex = get_ip_regex_match_func(ip_regex)

        while True:
            with self._cancellation_manager:
                ip = self._find_vm_ip(api, vm_id, is_ip_pass_regex)
                if instance.instance_type == InstanceType.CONTAINER:
                    ip = self._find_ip_over_cli(cli, api, vm_id, is_ip_pass_regex)
            if ip:
                break

            if datetime.now() > timeout_time:
                raise VMIPNotFoundException(ip_regex)
            time.sleep(self.DEFAULT_IP_DELAY)
        return ip

    def _find_ip_over_cli(self, cli, api, instance_id, is_ip_pass_regex) -> str:
        node = api.get_node_by_vmid(instance_id)
        session_types = [
            WebSocketSession(
                host=self._resource_conf.address,
                username=self._resource_conf.user,
                password=self._resource_conf.password,
                proxmox_handler=api,
                node=node,
            )
        ]
        mode = CommandMode(r"#\s*$")

        with cli.get_session(session_types, mode) as cli_service:
            ips_data = cli_service.send_command(f'lxc-info -i {instance_id}',
                                             logger=logger,
                                           timeout=300)
            ips = list(self.IP_REGEX.findall(ips_data))
            for ip in ips:
                if is_ip_pass_regex(ip):
                    logger.debug(f"Found IP {ip} on {instance_id}")
                    return ip
            return ips[0]


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

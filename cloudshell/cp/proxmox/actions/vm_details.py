from __future__ import annotations

import ipaddress
import logging
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Union

from cloudshell.cp.core.request_actions.models import (
    VmDetailsData,
    VmDetailsNetworkInterface,
    VmDetailsProperty,
)

from cloudshell.cp.proxmox.actions.vm_network import VMNetworkActions
from cloudshell.cp.proxmox.exceptions import InstanceIsNotRunningException, \
    VMIPNotFoundException
from cloudshell.cp.proxmox.models.deploy_app import (
    BaseProxmoxDeployApp,
)
from cloudshell.cp.proxmox.models.deployed_app import (
    BaseProxmoxDeployedApp,
)
from cloudshell.cp.proxmox.utils.units_converter import format_bytes

if TYPE_CHECKING:
    from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
    from cloudshell.cp.core.cancellation_manager import CancellationContextManager
    from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig

logger = logging.getLogger(__name__)

APP_MODEL_TYPES = Union[
    BaseProxmoxDeployApp, BaseProxmoxDeployedApp
]


class VMDetailsActions:
    def __init__(
            self,
            ph: ProxmoxHandler,
            resource_conf: ProxmoxResourceConfig,
            cancellation_manager: CancellationContextManager,
    ):
        self._ph = ph
        self._resource_conf = resource_conf
        self._cancellation_manager = cancellation_manager

    def _prepare_common_vm_instance_data(
            self,
            instance_id: int,
            wait_for_results: bool = True
    ) -> list[VmDetailsProperty]:
        vm_info = {}
        if wait_for_results:
            vm_info = self._get_instance_info_with_retries(instance_id=instance_id)
        else:
            with suppress(InstanceIsNotRunningException):
                vm_info = self._ph.get_instance_info(instance_id=instance_id)
            # vm_info = self._get_instance_info(instance_id=instance_id)
        data = [
            VmDetailsProperty(key="CPU", value=f"{vm_info['CPU']} vCPU"),
            VmDetailsProperty(key="Memory", value=format_bytes(vm_info["Memory"])),
            VmDetailsProperty(key="Guest OS", value=vm_info["Guest OS"]),
            VmDetailsProperty(key="Disk Size", value=format_bytes(vm_info["Disk"]))

        ]
        return data

    def _get_instance_info_with_retries(self, instance_id: int, max_retries: int = 7,
                                        timeout: int = 7) \
            -> dict[str: str] | None:
        retry = -1
        while retry < max_retries:
            try:
                return self._ph.get_instance_info(instance_id=instance_id)
            except InstanceIsNotRunningException:
                logger.info(f"Instance {instance_id} is not running yet. "
                            f"Retry in {timeout} seconds")
                time.sleep(timeout)
                retry += 1

    def _prepare_vm_network_data(
            self,
            instance_id: int,
            app_model: APP_MODEL_TYPES,
            wait_for_results: bool = True
    ) -> list[VmDetailsNetworkInterface]:
        """Prepare VM Network data."""
        logger.info(f"Preparing VM Details network data for the {instance_id}")

        network_interfaces = []
        network_actions = VMNetworkActions(self._resource_conf,
                                           self._cancellation_manager)

        vnics_data: dict = self._get_instance_interfaces_with_retries(
            instance_id=instance_id)
        primary_ip = None
        if wait_for_results:
            with suppress(VMIPNotFoundException):
                primary_ip = network_actions.get_vm_ip(
                    self._ph,
                    instance_id,
                    ip_regex=app_model.ip_regex,
                    timeout=3,
                )

        for mac, iface in vnics_data.items():
            vlan_id = iface.get("tag", "")
            if not vlan_id:
                vlan_id = 0
            is_predefined = str(vlan_id) in self._resource_conf.reserved_networks
            network_data = [
                VmDetailsProperty(key="IP", value=iface.get("ipv4")),
                VmDetailsProperty(key="MAC Address", value=mac),
                VmDetailsProperty(key="vNIC Name", value=iface.get("name")),
                VmDetailsProperty(key="Guest Interface Name", value=iface[
                    "guest_name"]),
                VmDetailsProperty(key="Firewall Enabled", value=str(int(
                    iface.get("firewall", "0")) == 1)),
            ]

            ip = None
            with suppress(ValueError):
                ip = str(ipaddress.ip_address(iface["ipv4"]))

            is_primary = primary_ip == ip if primary_ip else False

            interface = VmDetailsNetworkInterface(
                interfaceId=mac,
                networkId=str(vlan_id),
                isPrimary=is_primary,
                isPredefined=is_predefined,
                networkData=network_data,
                privateIpAddress=ip,
            )

            network_interfaces.append(interface)

        return network_interfaces

    def _get_instance_interfaces_with_retries(
            self,
            instance_id: int,
            max_retries: int = 7,
            timeout: int = 5
    ) -> dict[str: dict] | None:
        retry = -1
        while retry < max_retries:
            try:
                return self._ph.get_instance_ifaces_info(instance_id=instance_id)
            except InstanceIsNotRunningException:
                logger.info(f"Instance {instance_id} is not running yet. "
                            f"Retry in {timeout} seconds")
                time.sleep(timeout)
                retry += 1

    def create(
            self,
            instance_id: int,
            app_model: APP_MODEL_TYPES,
            wait_for_results: bool = True
    ) -> VmDetailsData:
        try:
            app_name = app_model.app_name  # DeployApp
        except AttributeError:
            app_name = app_model.name  # DeployedApp

        try:
            # instance_id = int(app_model.vmdetails.uid)
            instance_details = self._prepare_common_vm_instance_data(
                instance_id=instance_id,
                wait_for_results=wait_for_results
            )
            network_details = self._prepare_vm_network_data(
                instance_id=instance_id,
                app_model=app_model,
                wait_for_results=wait_for_results
            )
        except Exception as e:
            logger.exception("Failed to created VM Details:")
            details = VmDetailsData(appName=app_name, errorMessage=str(e))
        else:
            details = VmDetailsData(
                appName=app_name,
                vmInstanceData=instance_details,
                vmNetworkData=network_details,
            )
        logger.info(f"VM Details: {details}")
        return details

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Union

from cloudshell.cp.core.request_actions.models import (
    VmDetailsData,
    VmDetailsNetworkInterface,
    VmDetailsProperty,
)

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
        si: ProxmoxHandler,
        resource_conf: ProxmoxResourceConfig,
        cancellation_manager: CancellationContextManager,
    ):
        self._si = si
        self._resource_conf = resource_conf
        self._cancellation_manager = cancellation_manager

    def _prepare_common_vm_instance_data(self, vm_id: int) -> list[VmDetailsProperty]:

        vm_info = self._si.get_vm_info(vm_id=vm_id)
        data = [
            VmDetailsProperty(key="CPU", value=f"{vm_info['CPU']} vCPU"),
            VmDetailsProperty(key="Memory", value=format_bytes(vm_info["Memory"])),
            VmDetailsProperty(key="Guest OS", value=vm_info["Guest OS"]),
            VmDetailsProperty(key="Disk Size", value=format_bytes(vm_info["Disk"]))

        ]
        return data

    def _prepare_vm_network_data(
            self,
            vm_id: int,
    ) -> list[VmDetailsNetworkInterface]:
        """Prepare VM Network data."""
        logger.info(f"Preparing VM Details network data for the {vm_id}")

        network_interfaces = []

        for iface in self._si.get_vm_ifaces_info(vm_id=vm_id):
            network_data = [
                VmDetailsProperty(key="IP", value=iface["ipv4"]),
                VmDetailsProperty(key="MAC Address", value=iface["mac"]),
                VmDetailsProperty(key="Network Adapter", value=iface["name"]),
            ]

            interface = VmDetailsNetworkInterface(
                interfaceId=iface["mac"],
                networkData=network_data,
                privateIpAddress=iface["ipv4"],
            )
            network_interfaces.append(interface)

        return network_interfaces

    def create(
        self,
        app_model: APP_MODEL_TYPES,
    ) -> VmDetailsData:
        try:
            app_name = app_model.app_name  # DeployApp
        except AttributeError:
            app_name = app_model.name  # DeployedApp

        try:
            vm_id = int(app_model.vmdetails.uid)
            instance_details = self._prepare_common_vm_instance_data(vm_id=vm_id)
            network_details = self._prepare_vm_network_data(vm_id=vm_id)
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

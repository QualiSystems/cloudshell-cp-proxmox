from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Any

from attrs import define

from cloudshell.shell.flows.connectivity.cloud_providers_flow import (
    AbcCloudProviderConnectivityFlow,
    VnicInfo,
)
from cloudshell.shell.flows.connectivity.models.connectivity_model import (
    is_set_action,
)

from cloudshell.cp.proxmox.exceptions import VmDoesNotExistException
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from cloudshell.cp.proxmox.models.connectivity_action_model import \
    ProxmoxConnectivityActionModel
from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig
from cloudshell.cp.proxmox.utils.connectivity_helpers import NetworkSettings
from cloudshell.cp.proxmox.utils.threading import LockHandler

if TYPE_CHECKING:
    from collections.abc import Collection
    from concurrent.futures import ThreadPoolExecutor

    from cloudshell.cp.core.reservation_info import ReservationInfo

VM_NOT_FOUND_MSG = "VM {} is not found. Skip disconnecting vNIC"
logger = logging.getLogger(__name__)
network_lock = LockHandler()
switch_lock = LockHandler()


@define(slots=False)
class ProxmoxConnectivityFlow(AbcCloudProviderConnectivityFlow):
    _resource_conf: ProxmoxResourceConfig
    _reservation_info: ReservationInfo

    def __attrs_post_init__(self):
        self._api = ProxmoxHandler.from_config(self._resource_conf)
        self._sandbox_id = self._reservation_info.reservation_id
        self._instance_interface_type_map = {}

    def validate_actions(
            self, actions: Collection[ProxmoxConnectivityActionModel]
    ) -> None:
        _ = [self._get_network_settings(action) for action in actions]

    def pre_connectivity(
            self,
            actions: Collection[ProxmoxConnectivityActionModel],
            executor: ThreadPoolExecutor,
    ) -> None:

        for action in filter(is_set_action, actions):
            vm = self.get_target(action)
            if vm not in self._instance_interface_type_map:
                self._instance_interface_type_map[vm] = (
                    self._api.get_instance_interface_type(vm)
                )

    def load_target(self, target_name: str) -> Any:
        self._api.get_node_by_vmid(int(target_name))
        return int(target_name)

    def get_vnics(self, vm_id: int) -> Collection[VnicInfo]:
        def get_vnic_info(vnic: dict) -> VnicInfo:
            return VnicInfo(
                vnic.get("name"),
                int(vnic.get("index")),
                True,
            )

        return tuple(map(get_vnic_info, self._api.get_instance_ifaces_info(
            vm_id
        ).values()
                         )
                     )

    def set_vlan(
            self, action: ProxmoxConnectivityActionModel, target: str = None
    ) -> str:

        vnic_name = int(action.custom_action_attrs.vnic)
        net_settings = self._get_network_settings(action)
        interface_type = self._instance_interface_type_map[target]

        logger.info(f"Connecting net{vnic_name} to the {target}.{vnic_name} iface")

        return self._api.attach_interface(
            network_bridge=net_settings.switch_name,
            instance_id=target,
            vlan_tag=net_settings.vlan_id,
            vnic_id=vnic_name,
            interface_type=interface_type,
            enable_firewall=net_settings.enable_firewall,
        )

    def remove_vlan(
            self, action: ProxmoxConnectivityActionModel, target: int | None
    ) -> str:
        if target is None:
            # skip disconnecting vNIC
            # CloudShell would call Connectivity one more time in teardown after VM was
            # deleted if disconnect for the first time failed
            logger.warning(VM_NOT_FOUND_MSG.format(action.custom_action_attrs.vm_uuid))
            return ""

        mac = self._api.detach_interface(target, action.connector_attrs.interface)

        return mac

    def clear(self, action: ProxmoxConnectivityActionModel, target: Any) -> str:
        """Executes before set VLAN actions or for rolling back failed.

        Returns updated interface if it's different from target name.
        """
        vnic_name = action.custom_action_attrs.vnic
        return self._api.detach_interface(target, int(vnic_name))

    # def post_connectivity(
    #         self,
    #         actions: Collection[ProxmoxConnectivityActionModel],
    #         executor: ThreadPoolExecutor,
    # ) -> None:
    #     pass

    def _get_network_settings(
            self, action: ProxmoxConnectivityActionModel
    ) -> NetworkSettings:
        return NetworkSettings.convert(action, self._resource_conf)

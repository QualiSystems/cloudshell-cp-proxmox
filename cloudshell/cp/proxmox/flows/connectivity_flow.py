from __future__ import annotations

import logging
from contextlib import suppress
from functools import cached_property
from itertools import chain
from typing import TYPE_CHECKING, Any

from attrs import define, field

from cloudshell.shell.flows.connectivity.cloud_providers_flow import (
    AbcCloudProviderConnectivityFlow,
    VnicInfo,
)
from cloudshell.shell.flows.connectivity.models.connectivity_model import (
    ConnectionModeEnum,
    is_remove_action,
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

    # _switches: dict[tuple[str, str], AbstractSwitchHandler] = field(
    #     init=False, factory=dict
    # )
    # _networks: dict[str, NetworkHandler] = field(
    #     init=False, factory=dict
    # )
    # _networks_watcher: NetworkWatcher = field(init=False)

    def __attrs_post_init__(self):
        self._api = ProxmoxHandler.from_config(self._resource_conf)
        # self._networks_watcher = NetworkWatcher(self._si, self._dc)
        # self._networks_watcher.populate_in_bg()
        self._sandbox_id = self._reservation_info.reservation_id
        self._instance_interface_type_map = {}

    def validate_actions(
            self, actions: Collection[ProxmoxConnectivityActionModel]
    ) -> None:
        # if switch name not specified in VLAN service or in resource config
        # converter would raise an exception
        _ = [self._get_network_settings(action) for action in actions]

    def pre_connectivity(
            self,
            actions: Collection[ProxmoxConnectivityActionModel],
            executor: ThreadPoolExecutor,
    ) -> None:

        for action in filter(is_set_action, actions):
            vm = self.get_target(action)
            if vm in self._instance_interface_type_map:
                self._instance_interface_type_map[vm] = (
                    self._api.get_instance_interface_type(
                        vm
                    ))

    def load_target(self, target_name: str) -> Any:
        try:
            node = self._api.get_node_by_vmid(int(target_name))
        except VmDoesNotExistException:
            node = None
        return node

    def get_vnics(self, vm_id: int) -> Collection[VnicInfo]:
        def get_vnic_info(vnic: dict) -> VnicInfo:
            return VnicInfo(
                vnic.get("name"),
                int(vnic.get("index")),
                True,
            )

        return tuple(map(get_vnic_info, self._api.get_instance_ifaces_info(vm_id)))

    def set_vlan(
            self, action: ProxmoxConnectivityActionModel, target: str = None
    ) -> str:
        # assert isinstance(target, VmHandler)

        vnic_name = action.custom_action_attrs.vnic
        net_settings = self._get_network_settings(action)
        interface_type = self._instance_interface_type_map[target]

        logger.info(f"Connecting net{vnic_name} to the {target}.{vnic_name} iface")

        return self._api.attach_interface(
            network_bridge=net_settings.network_bridge,
            instance_id=target,
            vlan_tag=net_settings.vlan_id,
            vnic_id=net_settings.name,
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
        vnic = target.get_vnic_by_mac(action.connector_attrs.interface)
        logger.info(f"Disconnecting {vnic.network} from the {vnic}")
        vnic.connect(self._holding_network)
        return vnic.mac_address

    def clear(self, action: ProxmoxConnectivityActionModel, target: Any) -> str:
        """Executes before set VLAN actions or for rolling back failed.

        Returns updated interface if it's different from target name.
        """
        assert isinstance(target, VmHandler)
        vnic_name = action.custom_action_attrs.vnic
        try:
            vnic = target.get_vnic(vnic_name)
        except VnicNotFound:
            logger.info(f"VNIC {vnic_name} is not created. Skip disconnecting")
            mac = ""
        else:
            logger.info(f"Disconnecting {vnic.network} from the {vnic}")
            vnic.connect(self._holding_network)
            mac = vnic.mac_address
        return mac

    def post_connectivity(
            self,
            actions: Collection[ProxmoxConnectivityActionModel],
            executor: ThreadPoolExecutor,
    ) -> None:
        net_to_remove = {}  # {(pg_name, host_name): action}

        for action in actions:
            if self._is_remove_vlan_or_failed(action):
                net_settings = self._get_network_settings(action)
                if not net_settings.existed:
                    vm = self.get_target(action)
                    # we need to remove network only once for every used host
                    host_name = getattr(vm, "host.name", None)
                    key = (net_settings.name, host_name)
                    net_to_remove[key] = net_settings

        # remove unused networks
        r = executor.map(self._remove_pg_with_checks, net_to_remove.values())

    def _get_network_settings(
            self, action: ProxmoxConnectivityActionModel
    ) -> NetworkSettings:
        return NetworkSettings.convert(action, self._resource_conf)

    def _is_remove_vlan_or_failed(self, action: ProxmoxConnectivityActionModel) -> bool:
        if is_remove_action(action):
            result = True
        else:
            results = self.results[action.action_id]
            success = results and all(result.success for result in results)
            result = not success
        return result

    def _clear_networks_for_exclusive(self, net_settings: NetworkSettings) -> None:
        """If network is exclusive only this one could use the VLAN ID."""

        def same_vlan(name: str) -> bool:
            switch = net_settings.switch_name
            vlan = net_settings.vlan_id
            _same_vlan = f"_{switch}_VLAN_{vlan}_" in name
            return _same_vlan and is_network_generated_name(name)

        logger.info(
            f"Network {net_settings.name} is exclusive, "
            f"removing other quali networks with the same VLAN ID"
        )
        for network in self._networks_watcher.find_networks(key=same_vlan):
            # all networks (except current ) should be disconnected from VMs and removed
            if net_settings.name == network.name:
                self._migrate_vms_from_another_sandbox(network)
            else:
                self._migrate_vms_to_holding_network(network)
                network.wait_network_become_free()
                self._delete_pg_from_every_host(network)

    def _clear_exclusive_networks(self, net_settings: NetworkSettings) -> None:
        """Remove exclusive networks.

        If we are using shared network no other exclusive networks with the same
        VLAN ID shouldn't exist.
        """

        def same_vlan_and_exclusive(name: str) -> bool:
            switch = net_settings.switch_name
            vlan = net_settings.vlan_id
            same_vlan = f"_{switch}_VLAN_{vlan}_" in name
            exclusive_access = f"{ConnectionModeEnum.ACCESS.value}_E" in name
            exclusive_trunk = f"{ConnectionModeEnum.TRUNK.value}_E" in name
            exclusive = exclusive_access or exclusive_trunk
            return same_vlan and exclusive and is_network_generated_name(name)

        for network in self._networks_watcher.find_networks(
                key=same_vlan_and_exclusive
        ):
            self._migrate_vms_to_holding_network(network)
            network.wait_network_become_free()
            self._delete_pg_from_every_host(network)

    def _migrate_vms_to_holding_network(self, source_net: AbstractNetwork):
        logger.info(f"Migrating all VMs from {source_net} to the holding network")
        for vm in source_net.vms:
            with suppress(ManagedEntityNotFound):  # VM has been deleted
                for vnic in vm.vnics:
                    if vnic.is_connected_to_network(source_net):
                        vnic.connect(self._holding_network)

    def _migrate_vms_from_another_sandbox(self, network: AbstractNetwork):
        for vm in network.vms:
            with suppress(ManagedEntityNotFound):  # VM has been deleted
                if vm.folder_name != self._sandbox_id:
                    for vnic in vm.vnics:
                        if vnic.is_connected_to_network(network):
                            vnic.connect(self._holding_network)

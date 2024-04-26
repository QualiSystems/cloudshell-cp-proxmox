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
        pass
        # existed_pg_names = set()
        # net_to_create = {}  # {(pg_name, host_name): action}
        #
        # for action in filter(is_set_action, actions):
        #     net_settings = self._get_network_settings(action)
        #     if net_settings.existed:
        #         existed_pg_names.add(net_settings.name)
        #     else:
        #         # for VSwitch creates a port group on every host that is used by VM
        #         vm = self.get_target(action)
        #         key = (net_settings.name, vm.host.name)
        #         net_to_create[key] = net_settings
        #
        # # check that existed networks exist
        # self._networks.update(
        #     {n: self._networks_watcher.get_network(n) for n in existed_pg_names}
        # )
        #
        # # create networks
        # tuple(executor.map(self._get_or_create_network, net_to_create.values()))

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
        network = self._networks[net_settings.name]

        logger.info(f"Connecting {network} to the {target}.{vnic_name} iface")
        # try:
        #     vnic = target.get_vnic(vnic_name)
        # except VnicNotFound:
        #     vnic = create_new_vnic(target, network, vnic_name)
        # else:
        #     vnic.connect(network)
        # mac = ""

        mac = self._api.attach_interface(
            network_bridge=network_bridge,
            instance_id=instance_id,
            vlan_tag=vlan_tag,
            vnic_id=vnic_id,
            interface_type=interface_type,
            enable_firewall=enable_firewall,
        ).get("mac")

        return vnic.mac_address

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
        tags = set(chain.from_iterable(r))

        # remove property collector
        self._networks_watcher.destroy()

        # remove tags
        self._remove_tags(tags)

    def _get_switch(self, net_settings: NetworkSettings) -> AbstractSwitchHandler:
        switch_name = net_settings.switch_name
        vm = self.get_target(net_settings.vm_uuid)
        host_name = vm.host.name
        key = (switch_name, host_name)

        switch = self._switches.get(key)
        if not switch:
            with switch_lock.lock(switch_name):
                if not (switch := self._switches.get(key)):
                    self._switches[key] = vm.get_v_switch(switch_name)
        return switch

    @staticmethod
    def _validate_network(
        network: NetworkHandler,
        switch: AbstractSwitchHandler,
        net_settings: NetworkSettings,
    ) -> None:
        if isinstance(network, NetworkHandler) and isinstance(switch, VSwitchHandler):
            if not switch.port_group_exists(network.name):
                # In vCenter the host's PG can be deleted but the network remains.
                # In this case we need to recreate the port group.
                # It's possible if the network is used in a VM's snapshot
                # but the VM is disconnected from the network.
                # Or Host PG might be created on one host and we need it on another
                switch.create_port_group(
                    network.name,
                    net_settings.vlan_id,
                    net_settings.port_mode,
                    net_settings.promiscuous_mode,
                    net_settings.forged_transmits,
                    net_settings.mac_changes,
                )

    def _get_or_create_network(self, net_settings: NetworkSettings) -> AbstractNetwork:
        switch = self._get_switch(net_settings)
        with network_lock.lock(net_settings.name):
            if net_settings.exclusive:
                # remove other networks with the same VLAN ID
                self._clear_networks_for_exclusive(net_settings)
            else:
                # remove exclusive networks with the same VLAN ID
                self._clear_exclusive_networks(net_settings)

            try:
                # getting earlier created network
                network = self._networks_watcher.get_network(net_settings.name)
            except NetworkNotFound:
                network = self._create_network(switch, net_settings)
            else:
                self._validate_network(network, switch, net_settings)
            self._networks[net_settings.name] = network
        return network

    def _create_network(
        self, switch: AbstractSwitchHandler, net_settings: NetworkSettings
    ) -> AbstractNetwork:
        try:
            # create Port Group - Host PG or DV PG
            switch.create_port_group(
                net_settings.name,
                net_settings.vlan_id,
                net_settings.port_mode,
                net_settings.promiscuous_mode,
                net_settings.forged_transmits,
                net_settings.mac_changes,
            )
        except PortGroupExists:
            pass
        network = self._networks_watcher.wait_appears(net_settings.name)
        self._add_tags(network)
        return network

    def _remove_pg_with_checks(self, net_settings: NetworkSettings) -> set[str]:
        def remove(name: str, existed: bool, vm_uuid: str) -> tuple[set[str], bool]:
            net_tags = set()
            net_not_found = False

            try:
                net_tags = self._remove_pg(name, existed, vm_uuid)
            except PgCanNotBeRemoved as e:
                logger.info(f"Port group {e.name} should not be removed")
            except NetworkNotFound as e:
                logger.info(f"Network {e.name} is already removed")
                net_not_found = True
            except ResourceInUse as e:
                logger.info(f"Network {e.name} is still in use, skip removing")
            return net_tags, net_not_found

        # remove network with new standard name
        tags, not_found = remove(
            net_settings.name, net_settings.existed, net_settings.vm_uuid
        )
        if not_found:
            # remove network with old standard name
            tags, _ = remove(
                net_settings.old_name, net_settings.existed, net_settings.vm_uuid
            )

        return tags

    def _network_can_be_replaced(self, net: AbstractNetwork) -> bool:
        reserved_networks = self._resource_conf.reserved_networks
        not_quali_name = not is_network_generated_name(net.name)
        if not net.name:
            result = True
        elif net.name == self._resource_conf.holding_network:
            result = True
        elif net.name not in reserved_networks and not_quali_name:
            result = True
        else:
            result = False
        return result

    def _get_network_settings(
        self, action: ProxmoxConnectivityActionModel
    ) -> NetworkSettings:
        return NetworkSettings.convert(action)

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

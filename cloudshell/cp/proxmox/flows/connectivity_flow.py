from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from attrs import define

from cloudshell.cp.proxmox.constants import BRIDGE_TEMPLATE, VLAN_TEMPLATE
from cloudshell.cp.proxmox.exceptions import VmDoesNotExistException, \
    BaseProxmoxException
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from cloudshell.cp.proxmox.handlers.switch_handler import SwitchHandler
from cloudshell.cp.proxmox.models.connectivity_action_model import (
    ProxmoxConnectivityActionModel,
)
from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig
from cloudshell.cp.proxmox.utils.connectivity_helpers import NetworkSettings
from cloudshell.cp.proxmox.utils.instance_type import InstanceType
from cloudshell.cp.proxmox.utils.threading import LockHandler
from cloudshell.shell.flows.connectivity.cloud_providers_flow import (
    AbcCloudProviderConnectivityFlow,
    VnicInfo,
)
from cloudshell.shell.flows.connectivity.models.connectivity_model import is_set_action

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
        # self._api = ProxmoxHandler.from_config(self._resource_conf)
        self._sandbox_id = self._reservation_info.reservation_id
        from collections import defaultdict
        self._instance_interface_type_map = defaultdict(list)
        self._api_map = {}

    def validate_actions(
            self, actions: Collection[ProxmoxConnectivityActionModel]
    ) -> None:
        _ = [self._get_network_settings(action) for action in actions]

    def pre_connectivity(
            self,
            actions: Collection[ProxmoxConnectivityActionModel],
            executor: ThreadPoolExecutor,
    ) -> None:
        nodes = set()
        api = ProxmoxHandler.from_config(self._resource_conf)
        container_api = ProxmoxHandler.from_config(self._resource_conf,
                                                   InstanceType.CONTAINER)

        for action in filter(is_set_action, actions):
            vlan_id = action.vlan_id
            vm = self.get_target(action)
            _api = api
            instance_conf = None
            with suppress(BaseProxmoxException):
                instance_conf = _api.get_instance(vm)
            if not instance_conf:
                _api = container_api
                instance_conf = _api.get_instance(vm)
            bridge = None
            node = api.get_node_by_vmid(vm)
            if self._resource_conf.default_sdn_zone:
                sdn_handler = self._resource_conf.default_sdn_zone
                bridge = api.create_vnet(
                    sdn_zone_name=sdn_handler,
                    vnet_name=BRIDGE_TEMPLATE.format(VLAN_TEMPLATE.format(
                        vlan_id=vlan_id)
                    ),
                    vlan_id=vlan_id,
                )
            elif self._resource_conf.default_bridge:
                nodes.add((api, node))
                root_br = self._resource_conf.default_bridge
                bridge_handler = SwitchHandler(api, logger)
                bridge = bridge_handler.prepare_network(
                    instance_config=instance_conf,
                    vlan_id=vlan_id,
                    br_name=root_br
                )

            if not bridge:
                self._api_map[vm] = (api, None)
            if vm not in self._instance_interface_type_map:
                self._instance_interface_type_map[vm].append(
                    (api.get_instance_interface_type(vm), bridge)
                )
        if not self._resource_conf.default_sdn_zone and self._resource_conf.default_bridge:
            # if no sdn zone or default bridge is set, we need to create a new one
            # for each node
            for node in nodes:
                api = ProxmoxHandler.from_config(self._resource_conf)
                with switch_lock:
                    api.apply_network_config(node)

    def load_target(self, target_name: str) -> Any:
        return int(target_name)

    def get_vnics(self, vm_id: int) -> Collection[VnicInfo]:
        def get_vnic_info(vnic: dict) -> VnicInfo:
            return VnicInfo(
                vnic.get("name"),
                int(vnic.get("index")),
                True,
            )

        return tuple(
            map(get_vnic_info, self._api_map.get(vm_id).get_instance_ifaces_info(
                vm_id).values())
        )

    def set_vlan(
            self, action: ProxmoxConnectivityActionModel, target: str = None
    ) -> str:
        vnic_name = int(action.custom_action_attrs.vnic)
        net_settings = self._get_network_settings(action)
        interface_type, br = self._instance_interface_type_map[target]

        logger.info(f"Connecting net{vnic_name} to the {target}.{vnic_name} iface")

        return self._api_map.get(target).attach_interface(
            network_bridge=br or net_settings.switch_name,
            instance_id=target,
            vlan_tag=net_settings.vlan_id,
            vnic_id=vnic_name,
            interface_type=interface_type,
            enable_firewall=net_settings.enable_firewall,
        )

    def remove_vlan(
            self, action: ProxmoxConnectivityActionModel, target: int | None
    ) -> str:
        mac = ""
        if target is None:
            # skip disconnecting vNIC
            # CloudShell would call Connectivity one more time in teardown after VM was
            # deleted if disconnect for the first time failed
            logger.warning(VM_NOT_FOUND_MSG.format(action.custom_action_attrs.vm_uuid))
            return ""
        api = self._api_map.get(target)
        if api:
            mac = api.detach_interface(target, action.connector_attrs.interface)

        return mac

    def clear(self, action: ProxmoxConnectivityActionModel, target: Any) -> str:
        """Executes before set VLAN actions or for rolling back failed.

        Returns updated interface if it's different from target name.
        """
        vnic_name = action.custom_action_attrs.vnic
        api = self._api_map.get(target)
        if api:
            return api.detach_interface(target, int(vnic_name))

    def _get_network_settings(
            self, action: ProxmoxConnectivityActionModel
    ) -> NetworkSettings:
        return NetworkSettings.convert(action, self._resource_conf)

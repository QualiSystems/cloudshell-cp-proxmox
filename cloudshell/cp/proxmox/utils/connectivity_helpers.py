from __future__ import annotations

import logging
import re

from attrs import define

from cloudshell.shell.flows.connectivity.models.connectivity_model import (
    ConnectionModeEnum,
)

from cloudshell.cp.proxmox.exceptions import BaseProxmoxException
from cloudshell.cp.proxmox.models.connectivity_action_model import \
    ProxmoxConnectivityActionModel
from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig

logger = logging.getLogger(__name__)


MAX_DVSWITCH_LENGTH = 60
MAX_DVSWITCH_LENGTH_V2 = 50
QS_NAME_PREFIX = "QS"
PORT_GROUP_NAME_PATTERN = re.compile(rf"{QS_NAME_PREFIX}_.+_VLAN")


class DvSwitchNameEmpty(BaseProxmoxException):
    def __init__(self):
        msg = (
            "For connectivity actions you have to specify default DvSwitch name in the "
            "resource or in every VLAN service"
        )
        super().__init__(msg)


@define
class PgCanNotBeRemoved(BaseProxmoxException):
    name: str

    def __str__(self):
        return f"Port group {self.name} can't be removed, it's not created by the Shell"


def generate_port_group_name(
    dv_switch_name: str, vlan_id: str, port_mode: ConnectionModeEnum
) -> str:
    dvs_name = dv_switch_name[:MAX_DVSWITCH_LENGTH]
    return f"{QS_NAME_PREFIX}_{dvs_name}_VLAN_{vlan_id}_{port_mode.value}"


def generate_port_group_name_v2(
    *,
    dv_switch_name: str,
    vlan_id: str,
    port_mode: ConnectionModeEnum,
) -> str:
    dvs_name = dv_switch_name[:MAX_DVSWITCH_LENGTH]

    return f"{QS_NAME_PREFIX}_{dvs_name}_VLAN_{vlan_id}_{port_mode.value}"


def is_network_generated_name(net_name: str):
    return bool(PORT_GROUP_NAME_PATTERN.search(net_name))


# def is_correct_vnic(expected_vnic: str, vnic: Vnic) -> bool:
#     """Check that expected vNIC name or number is equal to vNIC.
#
#     :param expected_vnic: vNIC name or number from the connectivity request
#     """
#     if expected_vnic.isdigit():
#         try:
#             is_correct = vnic.index == int(expected_vnic)
#         except ValueError:
#             is_correct = False
#     else:
#         is_correct = expected_vnic.lower() == vnic.name.lower()
#     return is_correct


# def get_available_vnic(
#     vm: int,
#     default_network: AbstractNetwork,
#     reserved_networks: list[str],
# ) -> Vnic | None:
#     for vnic in vm.vnics:
#         try:
#             network = vnic.network
#         except VnicWithoutNetwork:
#             # when cloning a VM to the host which is not connected to the same dvswitch
#             # a new VM's vNIC is created without network
#             logger.warning(f"You have a wrong network configuration for the {vm.host}")
#             break
#         else:
#             if is_vnic_network_can_be_replaced(
#                 network, default_network, reserved_networks
#             ):
#                 break
#     else:
#         vnic = None
#     return vnic


def create_new_vnic(
    vm: int, network: str, vnic_index: int
) -> str:
    if len(vm.vnics) >= 10:
        raise BaseProxmoxException("Limit of vNICs per VM is 10")

    try:
        last_vnic = vm.vnics[-1]
    except IndexError:
        pass  # no vNICs on the VM
    else:
        # connectivity flow should return new vNICs only if previous one exists
        assert last_vnic.index == int(vnic_index) - 1

    vnic = vm.vnic_class.create(network)

    return vnic


# def is_vnic_network_can_be_replaced(
#     network: AbstractNetwork,
#     default_network: AbstractNetwork,
#     reserved_network_names: list[str],
# ) -> bool:
#     return any(
#         (
#             not network.name,
#             network.name == default_network,
#             network.name not in reserved_network_names
#             and not (is_network_generated_name(network.name)),
#         )
#     )


def get_existed_port_group_name(action: ProxmoxConnectivityActionModel) -> str | None:
    pg_name = (
        action.connection_params.vlan_service_attrs.existing_network
        or action.connection_params.vlan_service_attrs.virtual_network  # deprecated
        or action.connection_params.vlan_service_attrs.port_group_name  # deprecated
    )
    return pg_name


@define
class NetworkSettings:
    switch_name: str
    vlan_id: int
    port_mode: ConnectionModeEnum
    enable_firewall: bool
    vm_uuid: str

    @classmethod
    def convert(
        cls,
        action: ProxmoxConnectivityActionModel,
        resource_config: ProxmoxResourceConfig,
    ):
        con_params = action.connection_params
        vlan_service = con_params.vlan_service_attrs

        vlan_id = int(con_params.vlan_id)
        port_mode = con_params.mode
        enable_firewall = vlan_service.enable_firewall
        switch = vlan_service.switch_name or resource_config.default_bridge

        return cls(
            switch_name=switch,
            vlan_id=vlan_id,
            port_mode=port_mode,
            vm_uuid=action.custom_action_attrs.vm_uuid,
            enable_firewall=enable_firewall,
        )

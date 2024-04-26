from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from attrs import define

from cloudshell.shell.flows.connectivity.models.connectivity_model import (
    ConnectionModeEnum,
    IsolationLevelEnum,
)

from cloudshell.cp.vcenter.exceptions import BaseVCenterException
from cloudshell.cp.vcenter.handlers.si_handler import CustomSpecNotFound

if TYPE_CHECKING:
    from typing_extensions import Self

    from cloudshell.cp.vcenter.handlers.network_handler import (
        AbstractNetwork,
        DVPortGroupHandler,
        NetworkHandler,
    )
    from cloudshell.cp.vcenter.handlers.vm_handler import VmHandler
    from cloudshell.cp.vcenter.handlers.vnic_handler import Vnic
    from cloudshell.cp.vcenter.models.connectivity_action_model import (
        VcenterConnectivityActionModel,
    )
    from cloudshell.cp.vcenter.resource_config import VCenterResourceConfig


logger = logging.getLogger(__name__)


MAX_DVSWITCH_LENGTH = 60
# uses for PG names v2
MAX_DVSWITCH_LENGTH_V2 = 50
QS_NAME_PREFIX = "QS"
PORT_GROUP_NAME_PATTERN = re.compile(rf"{QS_NAME_PREFIX}_.+_VLAN")


class DvSwitchNameEmpty(BaseVCenterException):
    def __init__(self):
        msg = (
            "For connectivity actions you have to specify default DvSwitch name in the "
            "resource or in every VLAN service"
        )
        super().__init__(msg)


@define
class PgCanNotBeRemoved(BaseVCenterException):
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
    forged_transmits: bool,
    mac_changes: bool,
    promiscuous_mode: bool,
    exclusive: bool,
) -> str:
    dvs_name = dv_switch_name[:MAX_DVSWITCH_LENGTH]
    flags = "E" if exclusive else "S"
    flags += "F" if forged_transmits else ""
    flags += "M" if mac_changes else ""
    flags += "P" if promiscuous_mode else ""
    return f"{QS_NAME_PREFIX}_{dvs_name}_VLAN_{vlan_id}_{port_mode.value}_{flags}"


def is_network_generated_name(net_name: str):
    return bool(PORT_GROUP_NAME_PATTERN.search(net_name))


def is_correct_vnic(expected_vnic: str, vnic: Vnic) -> bool:
    """Check that expected vNIC name or number is equal to vNIC.

    :param expected_vnic: vNIC name or number from the connectivity request
    """
    if expected_vnic.isdigit():
        try:
            is_correct = vnic.index == int(expected_vnic)
        except ValueError:
            is_correct = False
    else:
        is_correct = expected_vnic.lower() == vnic.name.lower()
    return is_correct


def get_available_vnic(
    vm: VmHandler,
    default_network: AbstractNetwork,
    reserved_networks: list[str],
) -> Vnic | None:
    from cloudshell.cp.vcenter.handlers.vnic_handler import VnicWithoutNetwork

    for vnic in vm.vnics:
        try:
            network = vnic.network
        except VnicWithoutNetwork:
            # when cloning a VM to the host which is not connected to the same dvswitch
            # a new VM's vNIC is created without network
            logger.warning(f"You have a wrong network configuration for the {vm.host}")
            break
        else:
            if is_vnic_network_can_be_replaced(
                network, default_network, reserved_networks
            ):
                break
    else:
        vnic = None
    return vnic


def create_new_vnic(
    vm: VmHandler, network: NetworkHandler | DVPortGroupHandler, vnic_index: str
) -> Vnic:
    if len(vm.vnics) >= 10:
        raise BaseVCenterException("Limit of vNICs per VM is 10")

    try:
        last_vnic = vm.vnics[-1]
    except IndexError:
        pass  # no vNICs on the VM
    else:
        # connectivity flow should return new vNICs only if previous one exists
        assert last_vnic.index == int(vnic_index) - 1

    vnic = vm.vnic_class.create(network)
    try:
        custom_spec = vm.si.get_customization_spec(vm.name)
    except CustomSpecNotFound:
        pass
    else:
        # we need to have the same number of interfaces on the VM and in the
        # customization spec
        logger.info(f"Adding a new vNIC to the customization spec for the {vm}")
        if custom_spec.number_of_vnics > 0:
            custom_spec.add_new_vnic()
            vm.si.overwrite_customization_spec(custom_spec)

    return vnic


def is_vnic_network_can_be_replaced(
    network: AbstractNetwork,
    default_network: AbstractNetwork,
    reserved_network_names: list[str],
) -> bool:
    return any(
        (
            not network.name,
            network.name == default_network,
            network.name not in reserved_network_names
            and not (is_network_generated_name(network.name)),
        )
    )


def get_existed_port_group_name(action: VcenterConnectivityActionModel) -> str | None:
    pg_name = (
        action.connection_params.vlan_service_attrs.existing_network
        or action.connection_params.vlan_service_attrs.virtual_network  # deprecated
        or action.connection_params.vlan_service_attrs.port_group_name  # deprecated
    )
    return pg_name


def should_remove_port_group(name: str, existed: bool) -> bool:
    """Check if we should remove the network.

    We don't remove the network if it was specified in action
    or doesn't create by the Shell
    """
    return not existed and is_network_generated_name(name)


def check_pg_can_be_removed(name: str, existed: bool) -> None:
    if not should_remove_port_group(name, existed):
        raise PgCanNotBeRemoved(name)


@define
class NetworkSettings:
    name: str
    old_name: str
    existed: bool
    exclusive: bool
    switch_name: str
    vlan_id: str
    port_mode: ConnectionModeEnum
    promiscuous_mode: bool
    forged_transmits: bool
    mac_changes: bool
    vm_uuid: str

    @classmethod
    def convert(
        cls,
        action: VcenterConnectivityActionModel,
        conf: VCenterResourceConfig,
    ) -> Self:
        con_params = action.connection_params
        vlan_service = con_params.vlan_service_attrs

        vlan_id = con_params.vlan_id
        port_mode = con_params.mode
        switch = vlan_service.switch_name or conf.default_dv_switch
        exclusive = vlan_service.isolation_level is IsolationLevelEnum.EXCLUSIVE
        if (promiscuous_mode := vlan_service.promiscuous_mode) is None:
            promiscuous_mode = conf.promiscuous_mode
        if (forged_transmits := vlan_service.forged_transmits) is None:
            forged_transmits = conf.forged_transmits
        if (mac_changes := vlan_service.mac_changes) is None:
            mac_changes = conf.mac_changes

        if name := (old_name := get_existed_port_group_name(action)):
            existed = True
        else:
            if not switch:
                raise DvSwitchNameEmpty
            existed = False
            old_name = generate_port_group_name(switch, vlan_id, port_mode)
            name = generate_port_group_name_v2(
                dv_switch_name=switch,
                vlan_id=vlan_id,
                port_mode=port_mode,
                forged_transmits=forged_transmits,
                mac_changes=mac_changes,
                promiscuous_mode=promiscuous_mode,
                exclusive=exclusive,
            )
        return cls(
            name=name,
            old_name=old_name,
            existed=existed,
            exclusive=exclusive,
            switch_name=switch,
            vlan_id=vlan_id,
            port_mode=port_mode,
            promiscuous_mode=promiscuous_mode,
            forged_transmits=forged_transmits,
            mac_changes=mac_changes,
            vm_uuid=action.custom_action_attrs.vm_uuid,
        )

from __future__ import annotations

import logging
import re
import time
from functools import cached_property, partial
from typing import TYPE_CHECKING, Any

from attrs import define

from cloudshell.cp.proxmox.exceptions import (
    VmDoesNotExistException,
    UnsuccessfulOperationException,
)
from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig
from cloudshell.cp.proxmox.handlers.rest_api_handler import ProxmoxAutomationAPI
from cloudshell.cp.proxmox.constants import (
    CPU,
    RAM,
    DISK_SIZE,
    ADDRESS_TYPE,
    IP_ADDRESS,
    IP_LIST,
    IFACE_NAME,
    MAC,
    CI_USER,
    CI_PASSWORD,
)
from cloudshell.cp.proxmox.utils.instance_type import InstanceType

if TYPE_CHECKING:
    from typing_extensions import Self

logger = logging.getLogger(__name__)

RETRIES = 6
TIMEOUT = 5


@define
class ProxmoxHandler:
    _obj: ProxmoxAutomationAPI

    def __enter__(self) -> Self:
        return self

    @classmethod
    def from_config(cls, conf: ProxmoxResourceConfig,
                    instance_type=InstanceType.VM) -> (
            ProxmoxHandler):
        return cls.connect(conf.address, conf.user, conf.password, instance_type)

    @classmethod
    def connect(cls, host: str, user: str, password: str,
                instance_type: InstanceType) -> ProxmoxHandler:
        logger.info("Initializing Proxmox API client.")
        api = ProxmoxAutomationAPI(
            address=host,
            username=user,
            password=password,
            instance_type=instance_type
        )
        api.connect()
        return cls(api)

    @cached_property
    def vmid_to_node(self):
        return {
            res["vmid"]: res["node"] for res in self._obj.get_resources(r_type="vm")
        }

    def version(self):
        """Get Proxmox version."""
        return self._obj.version().get("version", "Undefined")

    def get_node_by_vmid(self, instance_id: int) -> str:
        """Get Proxmox on which VM is located."""

        node = self.vmid_to_node.get(instance_id, None)
        if node:
            return node

        raise VmDoesNotExistException(f"There is no VM with vmid {instance_id}")

    def start_instance(self, instance_id: int, node: str = None) -> None:
        """Turn ON Virtual Machine by instance_id"""
        if not node:
            node = self.get_node_by_vmid(instance_id)
        self._obj.start_instance(node=node, instance_id=instance_id)

    def stop_instance(self, instance_id: int, soft: bool, node: str = None) -> None:
        """Turn ON Virtual Machine by instance_id"""
        if not node:
            node = self.get_node_by_vmid(instance_id)
        if soft:
            self._obj.shutdown_instance(node=node, instance_id=instance_id)
        else:
            self._obj.stop_instance(node=node, instance_id=instance_id)

    def delete_instance(self, instance_id: int) -> None:
        """Stop Virtual machine and delete it."""
        try:
            node = self.get_node_by_vmid(instance_id)
            self.stop_instance(instance_id=instance_id, soft=False, node=node)
            self._obj.delete_instance(node=node, instance_id=instance_id)
        except VmDoesNotExistException:
            logger.info(
                f"Virtual machine with instance_id {instance_id} doesn't exist. "
                f"Skip deleting."
            )

    def get_instance_status(self, instance_id: int) -> str:
        """Get Virtual Machine status."""
        try:
            node = self.get_node_by_vmid(instance_id)
            data = self._obj.get_instance_status(node=node, instance_id=instance_id)
            return data.get("status", "stopped")
        except VmDoesNotExistException as e:
            logger.error(
                f"Virtual machine with instance_id {instance_id} doesn't exist."
            )
            raise e

    def set_user_data(self, instance_id: int, username: str, password: str) -> None:
        """Set user data for Virtual Machine."""
        node = self.get_node_by_vmid(instance_id)
        user_data = {CI_USER: username, CI_PASSWORD: password}
        self._obj.set_user_data(node=node, instance_id=instance_id, user_data=user_data)

    def get_instance_info(self, instance_id: int) -> dict:
        """Get Virtual Machine details."""
        try:
            node = self.get_node_by_vmid(instance_id)
            data = self._obj.get_instance_status(node=node, instance_id=instance_id)

            info = {
                "CPU": data.get(CPU, 0),
                "Memory": data.get(RAM, 0),
                "Guest OS": self.get_instance_os(instance_id=instance_id, node=node),
                "Disk": data.get(DISK_SIZE, 0)
            }

            return info
        except VmDoesNotExistException as e:
            logger.error(
                f"Virtual machine with instance_id {instance_id} doesn't exist."
            )
            raise e

    def get_instance_ifaces_info(self, instance_id):
        data_regexp = re.compile(
            r"^(?P<type>\w+)=(?P<mac>([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})+),"
            r".*bridge=(?P<bridge>\w+),"
            r".*tag=(?P<vlan>\d+)(,.*)?$"
        )
        #  net0: virtio=02:00:00:00:00:01,bridge=vmbr0,tag=10
        #  [model=](e1000 | e1000-82540em | e1000-82544gc | e1000-82545em | e1000e
        #  | i82551 | i82557b | i82559er | ne2k_isa | ne2k_pci | pcnet | rtl8139
        #  | virtio | vmxnet3) [,bridge=<bridge>] [,firewall=<boolean>]
        #  [,link_down=<boolean>] [,macaddr=<XX:XX:XX:XX:XX:XX>] [,mtu=<integer>]
        #  [,queues=<integer>] [,rate=<number>] [,tag=<integer>]
        #  [,trunks=<vlanid[;vlanid...]>]
        result = {}
        try:
            node = self.get_node_by_vmid(instance_id)
            config = self._obj.get_instance_config(node=node, instance_id=instance_id)
            guest_data = self._obj.get_net_ifaces(node=node, instance_id=instance_id)
            guest_ifaces = {x.get(MAC): x for x in guest_data.get("result", [])}
            for k, v in config.items():
                if k.startswith("net"):
                    vnic_data = data_regexp.search(v).groupdict()
                    mac = vnic_data.pop("mac")
                    iface = guest_ifaces.get(mac)
                    iface_ipv4 = "Undefined"
                    iface_ipv6 = "Undefined"
                    if vnic_data:
                        for ip in iface.get(IP_LIST, []):
                            if ip.get(ADDRESS_TYPE) == "ipv4":
                                iface_ipv4 = ip.get(IP_ADDRESS)
                            elif ip.get(ADDRESS_TYPE) == "ipv6":
                                iface_ipv6 = ip.get(IP_ADDRESS)
                        result[mac] = vnic_data.update(
                            {"name": k,
                             "index": k.replace("net", ""),
                             "guest_name": iface.get(IFACE_NAME),
                             "mac": iface.get(MAC),
                             "ipv4": iface_ipv4,
                             "ipv6": iface_ipv6,
                             }
                        )

            return result
        except VmDoesNotExistException as e:
            logger.error(
                f"Virtual machine with instance_id {instance_id} doesn't exist."
            )
            raise e

    def get_instance_os(self, instance_id: int, node: str = None) -> str:
        """Get Virtual Machine Operation System details."""
        try:
            if not node:
                node = self.get_node_by_vmid(instance_id)
            data = self._obj.get_instance_osinfo(node=node, instance_id=instance_id)
            os_name = data.get("result", {}).get("name")
            os_version = data.get("result", {}).get("version")
            return f"{os_name} {os_version}"
        except VmDoesNotExistException as e:
            logger.error(
                f"Virtual machine with instance_id {instance_id} doesn't exist."
            )
            raise e

    def _task_waiter(
            self,
            node: str,
            upid: str,
            msg: str,
            retries: int = RETRIES,
            timeout: int = TIMEOUT
    ):
        """Check if the task finished and finished successfully."""
        status = "running"
        exit_status = ""
        attempt = 0
        while status == "running" and attempt < retries:
            data = self._obj.get_task_status(node=node, upid=upid)
            status = data.get("status", "running")
            exit_status = data.get("exitstatus", "Failed")
            attempt += 1
            time.sleep(timeout)

        if status == "running" or exit_status.upper() != "OK":
            raise UnsuccessfulOperationException(msg)

    def attach_interface(self, instance_id: int, vnic_id: int) -> None:
        """Attach interface to Virtual Machine."""
        node = self.get_node_by_vmid(instance_id)
        upid = self._obj.attach_interface(node=node, instance_id=instance_id,
                                          vnic_id=vnic_id)

        self._task_waiter(
            node=node,
            upid=upid,
            msg=f"Failed to attach interface {vnic_id} during {{attempt*timeout}} sec"
        )

    def get_snapshots_list(self, instance_id: int) -> list[int | bytes]:
        """Get list of existing snapshots."""
        node = self.get_node_by_vmid(instance_id)
        data = self._obj.get_snapshot_list(node=node, instance_id=instance_id)

        return [snap["name"] for snap in data]

    def create_snapshot(
            self,
            instance_id: int,
            name: str,
            dump_memory: bool = False,
    ) -> str:
        """Create Virtual Machine snapshot."""
        node = self.get_node_by_vmid(instance_id)

        data = self._obj.get_instance_status(node=node, instance_id=instance_id)
        vm_status = data.get("status", "stopped")

        upid = self._obj.create_snapshot(
            node=node,
            instance_id=instance_id,
            name=name,
            vm_state=int((vm_status == "running") and dump_memory)
        )

        self._task_waiter(
            node=node,
            upid=upid,
            msg=f"Failed to create snapshot {name} during {{attempt*timeout}} sec"
        )
        return name

    def restore_from_snapshot(self, instance_id: int, name: str):
        """Restore Virtual Machine from state from snapshot."""
        node = self.get_node_by_vmid(instance_id)

        upid = self._obj.restore_from_snapshot(node=node, instance_id=instance_id,
                                               name=name)

        self._task_waiter(
            node=node,
            upid=upid,
            msg=f"Failed to restore from snapshot {name} during {{attempt*timeout}} sec"
        )

    def clone_instance(
            self,
            instance_id: int,
            vm_name: str,
            node: str,
            snapshot: str = None,
            user_data: dict | None = None,
    ) -> str:
        """Clone Virtual Machine."""
        new_instance_id = self._obj.clone_instance(
            node=node,
            instance_id=instance_id,
            name=vm_name,
            snapshot=snapshot,
        )

        self._task_waiter(
            node=node,
            upid=str(new_instance_id),
            msg=f"Failed to clone VM {vm_name} during {{attempt*timeout}} sec"
        )
        return self.get_node_by_vmid(int(new_instance_id))

    def delete_snapshot(self, instance_id: int, name: str):
        """Delete Virtual Machine snapshot."""
        node = self.get_node_by_vmid(instance_id)

        upid = self._obj.delete_snapshot(node=node, instance_id=instance_id,
                                         name=name)

        self._task_waiter(
            node=node,
            upid=upid,
            msg=f"Failed to delete snapshot {name} during {{attempt*timeout}} sec"
        )

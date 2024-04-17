from __future__ import annotations

import logging
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
    MAC
)

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
    def from_config(cls, conf: ProxmoxResourceConfig) -> ProxmoxHandler:
        return cls.connect(conf.address, conf.user, conf.password)

    @classmethod
    def connect(cls, host: str, user: str, password: str) -> ProxmoxHandler:
        logger.info("Initializing Proxmox API client.")
        api = ProxmoxAutomationAPI(
            address=host,
            username=user,
            password=password
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

    def get_node_by_vmid(self, vm_id: int) -> str:
        """Get Proxmox on which VM is located."""

        node = self.vmid_to_node.get(vm_id, None)
        if node:
            return node

        raise VmDoesNotExistException(f"There is no VM with vmid {vm_id}")

    def start_vm(self, vm_id: int, node: str = None) -> None:
        """Turn ON Virtual Machine by vm_id"""
        if not node:
            node = self.get_node_by_vmid(vm_id)
        self._obj.start_vm(node=node, vm_id=vm_id)

    def stop_vm(self, vm_id: int, soft: bool, node: str = None) -> None:
        """Turn ON Virtual Machine by vm_id"""
        if not node:
            node = self.get_node_by_vmid(vm_id)
        if soft:
            self._obj.shutdown_vm(node=node, vm_id=vm_id)
        else:
            self._obj.stop_vm(node=node, vm_id=vm_id)

    def delete_vm(self, vm_id: int) -> None:
        """Stop Virtual machine and delete it."""
        try:
            node = self.get_node_by_vmid(vm_id)
            self.stop_vm(vm_id=vm_id, soft=False, node=node)
            self._obj.delete_vm(node=node, vm_id=vm_id)
        except VmDoesNotExistException:
            logger.info(
                f"Virtual machine with vm_id {vm_id} doesn't exist. Skip deleting."
            )

    def get_vm_status(self, vm_id: int) -> str:
        """Get Virtual Machine status."""
        try:
            node = self.get_node_by_vmid(vm_id)
            data = self._obj.get_vm_status(node=node, vm_id=vm_id)
            return data.get("status", "stopped")
        except VmDoesNotExistException as e:
            logger.error(
                f"Virtual machine with vm_id {vm_id} doesn't exist."
            )
            raise e

    def set_user_data(self, node, vm_id: int, user_data: dict) -> None:
        """Set user data for Virtual Machine."""
        self._obj.set_user_data(node=node, vm_id=vm_id, user_data=user_data)


    def get_vm_info(self, vm_id: int) -> dict:
        """Get Virtual Machine details."""
        try:
            node = self.get_node_by_vmid(vm_id)
            data = self._obj.get_vm_status(node=node, vm_id=vm_id)

            info = {
                "CPU": data.get(CPU, 0),
                "Memory": data.get(RAM, 0),
                "Guest OS": self.get_vm_os(vm_id=vm_id, node=node),
                "Disk": data.get(DISK_SIZE, 0)
            }

            return info
        except VmDoesNotExistException as e:
            logger.error(
                f"Virtual machine with vm_id {vm_id} doesn't exist."
            )
            raise e

    def get_vm_ifaces_info(self, vm_id: int) -> list[dict]:
        """Get Virtual Machine network interfaces details."""
        try:
            node = self.get_node_by_vmid(vm_id)
            data = self._obj.get_net_ifaces(node=node, vm_id=vm_id)

            ifaces = []
            for iface in data.get("result", []):
                iface_ipv4 = "Undefined"
                iface_ipv6 = "Undefined"
                for ip in iface.get(IP_LIST, []):
                    if ip.get(ADDRESS_TYPE) == "ipv4":
                        iface_ipv4 = ip.get(IP_ADDRESS)
                    elif ip.get(ADDRESS_TYPE) == "ipv6":
                        iface_ipv6 = ip.get(IP_ADDRESS)

                ifaces.append(
                    {
                        "name": iface.get(IFACE_NAME),
                        "mac": iface.get(MAC),
                        "ipv4": iface_ipv4,
                        "ipv6": iface_ipv6,
                    }
                )

            return ifaces
        except VmDoesNotExistException as e:
            logger.error(
                f"Virtual machine with vm_id {vm_id} doesn't exist."
            )
            raise e

    def get_vm_os(self, vm_id: int, node: str = None) -> str:
        """Get Virtual Machine Operation System details."""
        try:
            if not node:
                node = self.get_node_by_vmid(vm_id)
            data = self._obj.get_vm_osinfo(node=node, vm_id=vm_id)
            os_name = data.get("result", {}).get("name")
            os_version = data.get("result", {}).get("version")
            return f"{os_name} {os_version}"
        except VmDoesNotExistException as e:
            logger.error(
                f"Virtual machine with vm_id {vm_id} doesn't exist."
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

    def get_snapshots_list(self, vm_id: int) -> list[int | bytes]:
        """Get list of existing snapshots."""
        node = self.get_node_by_vmid(vm_id)
        data = self._obj.get_snapshot_list(node=node, vm_id=vm_id)

        return [snap["name"] for snap in data]

    def create_snapshot(
            self,
            vm_id: int,
            name: str,
            dump_memory: bool = False,
    ) -> str:
        """Create Virtual Machine snapshot."""
        node = self.get_node_by_vmid(vm_id)

        data = self._obj.get_vm_status(node=node, vm_id=vm_id)
        vm_status = data.get("status", "stopped")

        upid = self._obj.create_snapshot(
            node=node,
            vm_id=vm_id,
            name=name,
            vm_state=int((vm_status == "running") and dump_memory)
        )

        self._task_waiter(
            node=node,
            upid=upid,
            msg=f"Failed to create snapshot {name} during {{attempt*timeout}} sec"
        )
        return name

    def restore_from_snapshot(self, vm_id: int, name: str):
        """Restore Virtual Machine from state from snapshot."""
        node = self.get_node_by_vmid(vm_id)

        upid = self._obj.restore_from_snapshot(node=node, vm_id=vm_id, name=name)

        self._task_waiter(
            node=node,
            upid=upid,
            msg=f"Failed to restore from snapshot {name} during {{attempt*timeout}} sec"
        )

    def clone_vm(
            self,
            vm_id: int,
            vm_name: str,
            node: str,
            snapshot: str = None,
            user_data: dict | None = None,
    ) -> str:
        """Clone Virtual Machine."""
        new_vm_id = self._obj.clone_vm(
            node=node,
            vm_id=vm_id,
            name=vm_name,
            snapshot=snapshot,
        )

        self._task_waiter(
            node=node,
            upid=str(new_vm_id),
            msg=f"Failed to clone VM {vm_name} during {{attempt*timeout}} sec"
        )
        return self.get_node_by_vmid(int(new_vm_id))

    def delete_snapshot(self, vm_id: int, name: str):
        """Delete Virtual Machine snapshot."""
        node = self.get_node_by_vmid(vm_id)

        upid = self._obj.delete_snapshot(node=node, vm_id=vm_id, name=name)

        self._task_waiter(
            node=node,
            upid=upid,
            msg=f"Failed to delete snapshot {name} during {{attempt*timeout}} sec"
        )

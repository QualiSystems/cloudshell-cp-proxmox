from __future__ import annotations

import logging
import ssl
import time
from contextlib import suppress
from functools import cached_property
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import websocket
from attrs import define
from requests import Response

from cloudshell.cp.proxmox.constants import (
    ADDRESS_TYPE,
    CI_PASSWORD,
    CI_USER,
    CPU,
    DISK_SIZE,
    IFACE_NAME,
    IP_ADDRESS,
    IP_LIST,
    MAC,
    RAM,
)
from cloudshell.cp.proxmox.exceptions import (
    InstanceIsNotRunningException,
    UnsuccessfulOperationException,
    VmDoesNotExistException,
)
from cloudshell.cp.proxmox.handlers.rest_api_handler import ProxmoxAutomationAPI
from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig
from cloudshell.cp.proxmox.utils.instance_type import InstanceType
from cloudshell.cp.proxmox.utils.power_state import PowerState

if TYPE_CHECKING:
    from typing_extensions import Self

logger = logging.getLogger(__name__)

RETRIES = 6
TIMEOUT = 5


@define(slots=False)
class ProxmoxHandler:
    _obj: ProxmoxAutomationAPI

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    @classmethod
    def from_config(
        cls, conf: ProxmoxResourceConfig, instance_type: InstanceType = InstanceType.VM
    ) -> ProxmoxHandler:
        return cls.connect(conf.address, conf.user, conf.password, instance_type)

    @classmethod
    def connect(
        cls, host: str, user: str, password: str, instance_type: InstanceType
    ) -> ProxmoxHandler:
        logger.info("Initializing Proxmox API client.")
        api = ProxmoxAutomationAPI(
            address=host, username=user, password=password, instance_type=instance_type
        )
        api.connect()
        return cls(api)

    @property
    def auth_ticket(self):
        return self._obj.ticket

    # @cached_property
    @property
    def vmid_to_node(self):
        return {res["vmid"]: res["node"] for res in self._obj.get_resources()}

    def generate_new_vm_id(self) -> int:
        """Generate new Virtual Machine ID."""
        result = self._obj.get_next_id()
        return int(result)

    def version(self):
        """Get Proxmox version."""
        return self._obj.version().get("version", "Undefined")

    def get_node_by_vmid(self, instance_id: int) -> str:
        """Get Proxmox on which VM is located."""

        node = self.vmid_to_node.get(instance_id, None)
        if node:
            return node

        raise VmDoesNotExistException(f"There is no VM with vmid {instance_id}")

    def start_instance(
        self, instance_id: int, node: str = None, skip_check: bool = False
    ) -> None:
        """Turn ON Virtual Machine by instance_id"""
        if not node:
            node = self.get_node_by_vmid(instance_id)
        logger.info(f"Node for VM {instance_id} is {node}")
        if (
            skip_check
            or not self.get_instance_status(instance_id, node) == PowerState.RUNNING
        ):
            self._obj.start_instance(node=node, instance_id=instance_id)

    def stop_instance(
        self,
        instance_id: int,
        soft: bool,
        node: str = None,
        max_retries: int = 5,
        timeout: int = 5,
    ) -> None:
        """Turn OFF Instance by instance_id"""
        if not node:
            node = self.get_node_by_vmid(instance_id)
        while max_retries > 0:
            if soft:
                upid = self._obj.shutdown_instance(node=node, instance_id=instance_id)
            else:
                upid = self._obj.stop_instance(node=node, instance_id=instance_id)

            if upid:
                logger.info(f"upid for stopping instance {instance_id}: {upid}")
                self._task_waiter(
                    node=node,
                    upid=upid,
                    msg=f"Failed to stop instance {instance_id} "
                    f"during {{attempt*timeout}} sec",
                )

            status = self.get_instance_status(instance_id, node)
            if status == PowerState.STOPPED:
                return
            max_retries -= 1
            time.sleep(timeout)

    def delete_instance(self, instance_id: int) -> None:
        """Stop Virtual machine and delete it."""
        try:
            node = self.get_node_by_vmid(instance_id)
            logger.info(f"Stopping Instance {instance_id}")
            self.stop_instance(instance_id=instance_id, soft=False, node=node)
            logger.info(f"Deleting Instance {instance_id}")
            self._obj.delete_instance(node=node, instance_id=instance_id)
        except VmDoesNotExistException:
            logger.info(
                f"Virtual machine with instance_id {instance_id} doesn't exist. "
                f"Skip deleting."
            )

    def get_instance_status(self, instance_id: int, node: str = None) -> str:
        """Get Virtual Machine status."""
        try:
            if not node:
                node = self.get_node_by_vmid(instance_id)
            data = self._obj.get_instance_status(node=node, instance_id=instance_id)
            return PowerState.from_str(data.get("status", "stopped"))
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

    def set_disk_data(self, instance_id: int, disk_data: dict) -> None:
        """Set user data for Virtual Machine."""
        node = self.get_node_by_vmid(instance_id)
        self._obj.set_disk_data(node=node, instance_id=instance_id, disk_data=disk_data)

    def get_instance_storage(self, instance_id: int) -> dict:
        """Get Virtual Machine storage details."""
        disk_types = ["efidisk", "ide", "sata", "scsi", "virtio"]
        node = self.get_node_by_vmid(instance_id)
        # efidisk0, ide0, sata0, scsi0, virtio0
        response = self._obj.get_instance_config(node=node, instance_id=instance_id)
        return {
            k: v
            for k, v in response.items()
            if any([k.startswith(x) for x in disk_types])
        }

    def get_instance_info(self, instance_id: int) -> dict:
        """Get Virtual Machine details."""
        try:
            node = self.get_node_by_vmid(instance_id)
            data = self._obj.get_instance_status(node=node, instance_id=instance_id)

            info = {
                "CPU": data.get(CPU, 0),
                "Memory": data.get(RAM, 0),
                "Guest OS": self.get_instance_os(instance_id=instance_id, node=node),
                "Disk": data.get(DISK_SIZE, 0),
            }

            return info
        except VmDoesNotExistException as e:
            logger.error(
                f"Virtual machine with instance_id {instance_id} doesn't exist."
            )
            raise e

    def get_mac_address_by_interface_id(
        self, instance_id: int, interface_id: int, node: str = None
    ) -> str:
        """Get MAC address of Virtual Machine interface."""
        try:
            if not node:
                node = self.get_node_by_vmid(instance_id)
            data = self._obj.get_instance_config(node=node, instance_id=instance_id)
            return data.get(f"net{interface_id}", {}).get("mac")
        except VmDoesNotExistException as e:
            logger.error(
                f"Virtual machine with instance_id {instance_id} doesn't exist."
            )
            raise e

    def get_instance_interface_type(
        self, instance_id: int, interface_id: int = 0, node: str = None
    ) -> str:
        """Get MAC address of Virtual Machine interface."""
        try:
            if not node:
                node = self.get_node_by_vmid(instance_id)
            data = self._obj.get_instance_config(node=node, instance_id=instance_id)
            interface_type = data.get(f"net{interface_id}", {}).get("type")
            if interface_type:
                return interface_type
            for k, v in data.items():
                if k.startswith(f"net{interface_id}"):
                    return v.get("type")
        except VmDoesNotExistException as e:
            logger.error(
                f"Virtual machine with instance_id {instance_id} doesn't exist."
            )
            raise e

    def get_instance_ifaces_info(self, instance_id):
        result = {}
        try:
            node = self.get_node_by_vmid(instance_id)
            config: dict = self._obj.get_instance_config(
                node=node, instance_id=instance_id
            )
            guest_data = {}
            guest_ifaces = {}
            with suppress(InstanceIsNotRunningException):
                guest_data = self._obj.get_net_ifaces(
                    node=node, instance_id=instance_id
                )

            if self._obj.instance_type == InstanceType.VM:
                guest_ifaces = {
                    x.get(MAC, "").lower(): x for x in guest_data.get("result", [])
                }
                for k, v in config.items():
                    if k.startswith("net"):
                        # vnic_data = self.VM_REGEXP.search(v).groupdict()
                        mac = v.get("mac")
                        iface = guest_ifaces.get(mac.lower(), {})
                        iface_ipv4 = None
                        iface_ipv6 = None
                        if v:
                            for ip in iface.get(IP_LIST, []):
                                if ip.get(ADDRESS_TYPE) == "ipv4":
                                    iface_ipv4 = ip.get(IP_ADDRESS)
                                elif ip.get(ADDRESS_TYPE) == "ipv6":
                                    iface_ipv6 = ip.get(IP_ADDRESS)
                            result[mac] = v
                            result[mac] |= {
                                "name": k,
                                "index": k.replace("net", ""),
                                "guest_name": iface.get(IFACE_NAME),
                                "guest_mac": iface.get(MAC),
                                "ipv4": iface_ipv4,
                                "ipv6": iface_ipv6,
                            }

                return result
            else:
                guest_ifaces = {
                    x.get("hwaddr", "").lower(): x for x in guest_data.get("result", [])
                }
                for k, v in config.items():
                    mac = v.get("mac")
                    ip_data = guest_ifaces.get(mac.lower(), {})
                    if mac:
                        result[mac] = {
                            "name": k,
                            "firewall": v.get("firewall"),
                            "type": v.get("type"),
                            "tag": v.get("tag"),
                            "bridge": v.get("bridge"),
                            "index": k.replace("net"),
                            "guest_name": ip_data.get("name"),
                            "guest_mac": mac,
                            "ipv4": ip_data.get("inet", "Undefined"),
                            "ipv6": ip_data.get("inet6", "Undefined"),
                        }

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
        except InstanceIsNotRunningException:
            return ""
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
        timeout: int = TIMEOUT,
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

    def attach_interface(
        self,
        network_bridge: str,
        instance_id: int,
        vlan_tag: int,
        vnic_id: int,
        interface_type: str = "virtio",
        mac_address: str = None,
        enable_firewall: bool = False,
    ) -> str:
        """Attach interface to Virtual Machine."""
        node = self.get_node_by_vmid(instance_id)
        data = f"{interface_type}"
        if not mac_address:
            try:
                mac_address = self.get_mac_address_by_interface_id(
                    instance_id, vnic_id, node
                )
            except VmDoesNotExistException:
                mac_address = None
        if mac_address:
            data += f"={mac_address}"
        if enable_firewall is None:
            enable_firewall = False
        data += (
            f",bridge={network_bridge},tag={vlan_tag},firewall={int(enable_firewall)}"
        )
        if mac_address:
            self._obj.update_interface(
                node=node, instance_id=instance_id, interface_id=vnic_id, data=data
            )
        else:
            self._obj.attach_interface(
                node=node, instance_id=instance_id, interface_id=vnic_id, data=data
            )

        return self.get_mac_address_by_interface_id(
            instance_id=instance_id, interface_id=vnic_id, node=node
        )

    def detach_interface(
        self,
        instance_id: int,
        mac: int,
    ) -> str:
        """Attach interface to Virtual Machine."""
        interface_id = None
        interface_data = {}
        node = self.get_node_by_vmid(instance_id)
        instance_data = self._obj.get_instance_config(
            node=node, instance_id=instance_id
        )
        for k, v in instance_data.items():
            if k.startswith("net") and v.get("mac") == mac:
                interface_id = k.replace("net", "")
                interface_data = v
                break

        if interface_id and interface_data:
            logger.info(
                f"Disconnecting {interface_data.get('name', '')} from the "
                f"{interface_data.get('guest_name', '')}"
            )
            interface_type = interface_data.get("type")
            mac_address = interface_data.get("mac")
            data = f"{interface_type}={mac_address},link_down=1"
            upid = self._obj.update_interface(
                node=node, instance_id=instance_id, interface_id=interface_id, data=data
            )
            self._task_waiter(
                node=node,
                upid=upid,
                msg=f"Failed to attach interface {interface_id} during {{attempt*timeout}} sec",
            )
            return mac_address

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
            vm_state=int((vm_status == "running") and dump_memory),
        )

        self._task_waiter(
            node=node,
            upid=upid,
            msg=f"Failed to create snapshot {name} during {{attempt*timeout}} sec",
        )
        return name

    def restore_from_snapshot(self, instance_id: int, name: str):
        """Restore Virtual Machine from state from snapshot."""
        node = self.get_node_by_vmid(instance_id)

        upid = self._obj.restore_from_snapshot(
            node=node, instance_id=instance_id, name=name
        )

        self._task_waiter(
            node=node,
            upid=upid,
            msg=f"Failed to restore from snapshot {name} during {{attempt*timeout}} sec",
        )

    def clone_instance(
        self,
        instance_id: int,
        instance_node: str,
        instance_name: str,
        new_instance_id: int = None,
        snapshot: str = None,
        full: bool = None,
        target_storage: str = None,
        target_node: str = None,
    ) -> (int, str):
        """Clone Virtual Machine."""
        # ToDo review performance of this method
        if not new_instance_id:
            new_instance_id = self.generate_new_vm_id()

        upid = self._obj.clone_instance(
            node=instance_node,
            instance_id=instance_id,
            new_instance_id=new_instance_id,
            name=instance_name,
            snapshot=snapshot,
            full=full,
            target_storage=target_storage,
            target_node=target_node,
        )

        # self._task_waiter(
        #     node=instance_node,
        #     upid=upid,
        #     msg=f"Failed to clone Instance {instance_name} "
        #         f"during {{attempt*timeout}} seconds.",
        #     retries=60,
        #     timeout=10
        # )
        # self.get_node_by_vmid(int(new_instance_id))
        # self.get_instance_status(new_instance_id, node=target_node or node)

        return int(new_instance_id), upid

    def wait_for_deploy_to_complete(
        self, instance_node: str, upid: str, instance_name: str
    ):
        self._task_waiter(
            node=instance_node,
            upid=upid,
            msg=f"Failed to clone Instance {instance_name} "
            f"during {{attempt*timeout}} seconds.",
            retries=60,
            timeout=10,
        )
        # self.get_node_by_vmid(int(new_instance_id))

    def get_websocket(self, node):
        termproxy = self._obj.get_vnc_shell(node)

        ticket: str = termproxy.get("ticket")
        port: str = termproxy.get("port")

        headers = {
            "Authorization": f"PVEAPIToken={self._obj.token}",
            "Sec-WebSocket-Protocol": "bianry",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "Cookie": f"PVEAuthCookie={self._obj.ticket}",
        }

        ssl_defaults = ssl.get_default_verify_paths()
        ssl_context = ssl.create_default_context(cafile=ssl_defaults.cafile)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        opts = {"cert_reqs": ssl.CERT_NONE}

        websocket_url = (
            f"wss://{self._obj.address}:{self._obj.port}/api2/json/nodes"
            f"/{node}/vncwebsocket"
        )
        query_params = {"port": port, "vncticket": ticket}

        return websocket.create_connection(
            url=f"{websocket_url}?{urlencode(query_params)}",
            sslopt=opts,
            header=headers,
            timeout=2,
            close_timeout=10,
        )

    def delete_snapshot(self, instance_id: int, name: str):
        """Delete Virtual Machine snapshot."""
        node = self.get_node_by_vmid(instance_id)

        upid = self._obj.delete_snapshot(node=node, instance_id=instance_id, name=name)

        self._task_waiter(
            node=node,
            upid=upid,
            msg=f"Failed to delete snapshot {name} during {{attempt*timeout}} sec",
        )

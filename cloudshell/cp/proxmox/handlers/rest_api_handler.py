from __future__ import annotations

import logging
import ssl
import time
from abc import abstractmethod
from collections.abc import Callable
from urllib.parse import quote

import requests
import urllib3
from attrs import define, field
from attrs.setters import frozen

from cloudshell.cp.proxmox.constants import COOKIES, TOKEN
from cloudshell.cp.proxmox.exceptions import (
    AuthAPIException,
    BaseProxmoxException,
    InstanceIsNotRunningException,
    ParamsException,
    UnsuccessfulOperationException,
)
from cloudshell.cp.proxmox.utils.instance_config_helper import convert_instance_config
from cloudshell.cp.proxmox.utils.instance_type import InstanceType

logger = logging.getLogger(__name__)


@define
class BaseAPIClient:
    address: str = field(on_setattr=frozen)
    username: str = field(on_setattr=frozen)
    password: str = field(on_setattr=frozen)
    session: requests.Session = field(on_setattr=frozen, default=requests.Session())
    scheme: str = field(on_setattr=frozen, default="https")
    port: int = field(on_setattr=frozen, default=8006)
    verify_ssl: bool = field(on_setattr=frozen, default=ssl.CERT_NONE)

    def __attrs_post_init__(self):
        self.session.verify = self.verify_ssl
        self.session.headers.update({"Content-Type": "application/json"})
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    @abstractmethod
    def _base_url(self):
        pass

    def _do_request(
        self,
        method: Callable,
        path: str,
        raise_for_status: bool = True,
        http_error_map: dict[int, Exception | type[Exception]] | None = None,
        **kwargs: dict,
    ) -> requests.Response:
        if http_error_map is None:
            http_error_map = {}

        url = f"{self._base_url()}/{path}"
        res = method(url=url, **kwargs)
        try:
            raise_for_status and res.raise_for_status()
        except requests.exceptions.HTTPError as caught_err:
            if res is not None and res.content:
                logger.error(f"HTTP Request {url} Error: {res.content}")
            else:
                logger.exception(f"HTTP Request {url} Error: {caught_err}")
            http_code = caught_err.response.status_code
            err = http_error_map.get(http_code, BaseProxmoxException)
            raise err from caught_err
        return res

    def _do_get(
        self,
        path: str,
        raise_for_status: bool = True,
        http_error_map: dict[int, Exception | type[Exception]] | None = None,
        **kwargs: dict,
    ) -> requests.Response:
        """Basic GET request client method."""
        return self._do_request(
            self.session.get, path, raise_for_status, http_error_map, **kwargs
        )

    def _do_post(
        self,
        path: str,
        raise_for_status: bool = True,
        http_error_map: dict[int, Exception | type[Exception]] | None = None,
        **kwargs: dict,
    ) -> requests.Response:
        """Basic POST request client method."""
        return self._do_request(
            self.session.post, path, raise_for_status, http_error_map, **kwargs
        )

    def _do_put(
        self,
        path: str,
        raise_for_status: bool = True,
        http_error_map: dict[int, Exception] | None = None,
        **kwargs: dict,
    ) -> requests.Response:
        """Basic PUT request client method."""
        return self._do_request(
            self.session.put, path, raise_for_status, http_error_map, **kwargs
        )

    def _do_delete(
        self,
        path: str,
        raise_for_status: bool = True,
        http_error_map: dict[int, Exception | type[Exception]] | None = None,
        **kwargs: dict,
    ) -> requests.Response:
        """Basic DELETE request client method."""
        return self._do_request(
            self.session.delete, path, raise_for_status, http_error_map, **kwargs
        )


@define
class ProxmoxAutomationAPI(BaseAPIClient):
    ticket: str | None = None
    token: str | None = None
    instance_type: InstanceType = field(on_setattr=frozen, default=InstanceType.VM)

    class Decorators:
        @classmethod
        def get_data(
            cls, retries: int = 6, timeout: int = 5, raise_on_timeout: bool = True
        ):
            def wrapper(decorated):
                def inner(*args, **kwargs):
                    exception = None
                    attempt = 0
                    while attempt < retries:
                        try:
                            return decorated(*args, **kwargs).json()["data"]
                        except Exception as e:
                            exception = e
                            time.sleep(timeout)
                            attempt += 1

                    if raise_on_timeout:
                        if exception:
                            raise exception
                        else:
                            raise BaseProxmoxException(
                                f"Cannot get data for {retries*timeout} sec."
                            )

                return inner

            return wrapper

        @classmethod
        def get_instance_data(
            cls, retries: int = 6, timeout: int = 5, raise_on_timeout: bool = True
        ):
            def wrapper(decorated):
                def inner(*args, **kwargs):
                    exception = None
                    attempt = 0
                    while attempt < retries:
                        try:
                            response = decorated(*args, **kwargs).json()["data"]
                            return convert_instance_config(response)
                        except Exception as e:
                            exception = e
                            time.sleep(timeout)
                            attempt += 1

                    if raise_on_timeout:
                        if exception:
                            raise exception
                        else:
                            raise BaseProxmoxException(
                                f"Cannot get data for {retries*timeout} sec."
                            )

                return inner

            return wrapper

        @classmethod
        def is_success(cls, decorated):
            def inner(*args, **kwargs):
                x = decorated(*args, **kwargs)
                flag = x.json().get("success", None)
                if flag is None or int(flag) != 1:
                    raise UnsuccessfulOperationException("")

                return decorated(*args, **kwargs).json()

            return inner

        @classmethod
        def is_instance_locked(
            cls, retries: int = 60, timeout: int = 5, raise_on_timeout: bool = True
        ):
            def wrapper(decorated):
                def inner(*args, **kwargs):
                    attempt = 0
                    while attempt < retries:
                        try:
                            resp = decorated(*args, **kwargs)
                            data = resp.json().get("data", None)
                            if data and data.get("lock", None) is None:
                                return data
                        except Exception as e:
                            pass
                        finally:
                            time.sleep(timeout)
                            attempt += 1

                    if raise_on_timeout:
                        raise Exception(
                            f"VM is still locked after {retries*timeout} sec"
                        )

                return inner

            return wrapper

    def _base_url(self):
        return f"{self.scheme}://{self.address}:{self.port}/api2/json"

    def connect(self):
        """"""
        ticket_info = self._get_ticket_info()

        self.ticket = ticket_info.get("ticket", None)
        self.token = ticket_info.get("CSRFPreventionToken", None)

        if self.ticket and self.token:
            self.session.headers.update({TOKEN: self.token})
        else:
            raise

    @Decorators.get_data()
    def _get_ticket_info(self) -> requests.Response:
        """Get Rest API session ticket."""
        error_map = {
            401: AuthAPIException,
        }
        return self._do_post(
            path="access/ticket",
            http_error_map=error_map,
            json={"username": self.username, "password": self.password},
        )

    @Decorators.get_data()
    def get_task_status(self, node: str, upid: str) -> requests.Response:
        """"""
        error_map = {
            401: AuthAPIException,
        }
        # self.session.headers.update({})
        return self._do_get(
            path=f"nodes/{node}/tasks/{quote(upid)}/status",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def version(self) -> requests.Response:
        """Get Proxmox server version info."""
        error_map = {
            401: AuthAPIException,
        }
        # self.session.headers.update({})
        return self._do_get(
            path="version", http_error_map=error_map, cookies={COOKIES: self.ticket}
        )

    @Decorators.get_data()
    def get_resources(self, r_type: str = None) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        if not r_type:
            if self.instance_type == InstanceType.VM:
                r_type = "vm"
            else:
                r_type = "lxc"
        # self.session.headers.update({})

        return self._do_get(
            path=f"cluster/resources?type={r_type}" if r_type else "cluster/resources",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def get_network_bridges(self, r_type: str = None) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return self._do_get(
            path=f"cluster/resources?type={r_type}" if r_type else "any_bridge",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def set_disk_data(
        self, node: str, instance_id: int, disk_data: dict
    ) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }

        return self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/config",
            json=disk_data,
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def set_user_data(
        self, node: str, instance_id: int, user_data: dict
    ) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }

        return self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/config",
            json=user_data,
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def assign_vlan(
        self,
        node: str,
        network_bridge: str,
        interface_id: str,
        instance_id: int,
        vlan_tag: str,
        interface_type: str = "virtio",
        mac_address: str = "",
        enable_firewall: bool = True,
    ) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        data = f"{interface_type}"
        if mac_address:
            data += f":{network_bridge}"
        data += f",bridge={vlan_tag},tag={vlan_tag},firewall={int(enable_firewall)}"
        return self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/config",
            json={f"net{interface_id}": data},
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def attach_interface(
        self,
        node: str,
        interface_id: int,
        instance_id: int,
        data: str,
    ) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }

        response = self._do_put(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/config",
            http_error_map=error_map,
            json={f"net{interface_id}": data},
            cookies={COOKIES: self.ticket},
        )
        return response

    @Decorators.get_data()
    def update_interface(
        self,
        node: str,
        interface_id: int,
        instance_id: int,
        data: str,
    ) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        return self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/config",
            http_error_map=error_map,
            json={f"net{interface_id}": data},
            cookies={COOKIES: self.ticket},
        )

    # @Decorators.get_data()
    # def detach_interface(
    #         self,
    #         node: str,
    #         interface_id: int,
    #         instance_id: int,
    # ) -> requests.Response:
    #     """"""
    #     error_map = {
    #         400: ParamsException,
    #         401: AuthAPIException,
    #     }
    #     return self._do_put(
    #         path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/config",
    #         http_error_map=error_map,
    #         json={f"net{interface_id}": "link_down=True"},
    #         cookies={COOKIES: self.ticket}
    #     )

    @Decorators.get_data()
    def get_next_id(self) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return self._do_get(
            path=f"cluster/nextid?_dc={int(time.time())}",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.is_instance_locked()
    def get_instance_status(self, node: str, instance_id: int) -> requests.Response:
        """Get Virtual Machine Status."""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
            500: InstanceIsNotRunningException,
        }

        return self._do_get(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}"
            f"/status/current",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data(retries=60)
    def get_instance_ifaces(self, node: str, instance_id: int) -> requests.Response:
        """Get Virtual Machine Status."""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return self._do_get(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/agent/network-get-interfaces",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def start_instance(self, node: str, instance_id: int) -> requests.Response:
        """Start Virtual Machine."""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        return self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/status/start",
            http_error_map=error_map,
            json={"node": node, "vmid": instance_id},
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def stop_instance(self, node: str, instance_id: int) -> requests.Response:
        """Stop virtual machine.

        The qemu process will exit immediately.
        This is akin to pulling the power plug of a running computer
        and may damage the VM data.
        """
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        return self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/status/stop",
            http_error_map=error_map,
            json={"node": node, "vmid": instance_id},
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def shutdown_instance(self, node: str, instance_id: int) -> requests.Response:
        """Shutdown virtual machine.

        This is similar to pressing the power button on a physical machine.
        This will send an ACPI event for the guest OS,
        which should then proceed to a clean shutdown.
        """
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        return self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/status/shutdown",
            http_error_map=error_map,
            json={"node": node, "vmid": instance_id},
            cookies={COOKIES: self.ticket},
        )

    # @Decorators.is_success
    @Decorators.get_data()
    def clone_instance(
        self,
        node: str,
        instance_id: int,
        new_instance_id: int,
        name: str = None,
        snapshot: str = None,
        full: bool = None,
        target_storage: str = None,
        target_node: str = None,
    ) -> requests.Response:
        """Create VM."""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }

        # new_instance_id = self.get_next_id()
        data = {"newid": new_instance_id, "node": node, "vmid": instance_id}

        if name:
            data["name"] = name.replace("_", "-")

        if snapshot:
            data["snapname"] = snapshot

        # Create a full copy of all disks.
        # This is always done when you clone a normal VM.
        # For VM templates, we try to create a linked clone by default.
        if full:
            data["full"] = True

            # Target storage for full clone.
            if target_storage:
                data["storage"] = target_storage

        # Target node. Only allowed if the original VM is on shared storage.
        if target_node:
            data["target"] = target_node

        upid = self._do_post(
            path=f"nodes/{node}/{self.instance_type.value.lower()}/{instance_id}/clone",
            json=data,
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

        return upid

    # @Decorators.is_success
    def delete_instance(
        self,
        node: str,
        instance_id: int,
        destroy_unref_disk: bool = True,
        purge: bool = True,
        skip_lock: bool = False,
    ) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
            500: UnsuccessfulOperationException,
        }

        return self._do_delete(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}?node="
            f"{node}&vmid={int(instance_id)}&"
            f"purge={int(purge)}&destroy-unreferenced-disks={int(destroy_unref_disk)}",
            http_error_map=error_map,
            # json={"node": node, "vmid": instance_id, "purge": f"{int(purge)}",
            #       "destroy-unreferenced-disks": f"{int(destroy_unref_disk)}"},
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def get_snapshot_list(self, node: str, instance_id: int) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return self._do_get(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/snapshot",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def create_snapshot(
        self, node: str, instance_id: int, snapshot_name: str, instance_state: int = 0
    ) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/snapshot",
            json={"snapname": snapshot_name, "vmstate": instance_state},
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def restore_from_snapshot(
        self,
        node: str,
        instance_id: int,
        snapshot_name: str,
    ) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/snapshot/{snapshot_name}/rollback",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def delete_snapshot(
        self,
        node: str,
        instance_id: int,
        snapshot_name: str,
    ) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return self._do_delete(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/snapshot/{snapshot_name}",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    @Decorators.get_data()
    def get_node_report(self, node: str) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return self._do_get(
            path=f"/nodes/{node}/status",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    def get_net_ifaces(self, node: str, instance_id: int) -> dict:
        """"""
        if self.instance_type == InstanceType.VM:
            return self.get_vm_net_ifaces(node, instance_id)
        else:
            return self.get_lxc_net_ifaces(node, instance_id)

    def get_lxc_net_ifaces(self, node: str, instance_id: int) -> dict:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
            500: InstanceIsNotRunningException,
        }
        response = self._do_get(
            path=f"/nodes/{node}/lxc/{instance_id}/interfaces",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )
        return response.json()["data"]

    def get_vm_net_ifaces(self, node: str, instance_id: int) -> dict:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
            500: InstanceIsNotRunningException,
        }
        # self.session.headers.update({})

        response = self._do_get(
            path=f"/nodes/{node}/{self.instance_type.value}/{instance_id}"
            f"/agent/network-get-interfaces",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )
        return response.json()["data"]

    @Decorators.get_data()
    def get_vnc_shell(self, node):
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        return self._do_post(
            path=f"nodes/{node}/termproxy",
            json={
                "node": node,
                # "websocket": True
            },
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

    # @Decorators.get_data()
    def get_instance_osinfo(self, node: str, instance_id: int) -> dict:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
            500: InstanceIsNotRunningException,
        }

        return self._do_get(
            path=f"/nodes/{node}/{self.instance_type.value}/"
            f"{instance_id}/agent/get-osinfo",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        ).json()["data"]

    @Decorators.get_instance_data()
    def get_instance_config(
        self, node: str, instance_id: int
    ) -> requests.Response | dict:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }

        return self._do_get(
            path=f"/nodes/{node}/{self.instance_type.value}/{instance_id}/config",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket},
        )

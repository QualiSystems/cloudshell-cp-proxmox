from __future__ import annotations

import ssl
import time
from abc import abstractmethod
from collections.abc import Callable

from attrs import define, field
from attrs.setters import frozen
from urllib.parse import quote

import requests
import urllib3


from cloudshell.cp.proxmox.exceptions import (
    BaseProxmoxException,
    AuthAPIException,
    ParamsException, UnsuccessfulOperationException,
)

from cloudshell.cp.proxmox.constants import COOKIES, TOKEN
from cloudshell.cp.proxmox.utils.instance_type import InstanceType


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
            cls,
            retries: int = 6,
            timeout: int = 5,
            raise_on_timeout: bool = True
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
            cls,
            retries: int = 60,
            timeout: int = 5,
            raise_on_timeout: bool = True
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
                        raise Exception(f"VM is still locked after {retries*timeout} sec")
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
            json={"username": self.username, "password": self.password}
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
            cookies={COOKIES: self.ticket}
        )

    @Decorators.get_data()
    def version(self) -> requests.Response:
        """Get Proxmox server version info."""
        error_map = {
            401: AuthAPIException,
        }
        # self.session.headers.update({})
        return self._do_get(
            path="version",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket}
        )

    @Decorators.get_data()
    def get_resources(self, r_type: str = None) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return (self._do_get(
            path=f"cluster/resources?type={r_type}" if r_type else "cluster/resources",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket}
        ))

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
            cookies={COOKIES: self.ticket}
        )

    @Decorators.get_data()
    def set_user_data(
            self,
            node: str,
            instance_id: int,
            user_data: dict
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
            cookies={COOKIES: self.ticket}
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
            cookies={COOKIES: self.ticket}
        )

    @Decorators.get_data()
    def attach_interface(
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
            data += f":{mac_address}"
        data += f",bridge={network_bridge},tag={vlan_tag},firewall={int(enable_firewall)}"
        return self._do_put(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/config",
            http_error_map=error_map,
            json={f"net{interface_id}": f"{data}"},
            cookies={COOKIES: self.ticket}
        )

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
            cookies={COOKIES: self.ticket}
        )

    @Decorators.is_instance_locked()
    def get_instance_status(self, node: str, instance_id: int) -> requests.Response:
        """Get Virtual Machine Status."""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return self._do_get(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/status/current",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket}
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
            cookies={COOKIES: self.ticket}
        )

    def start_instance(self, node: str, instance_id: int) -> None:
        """Start Virtual Machine."""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/status/start",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket}
        )

    def stop_instance(self, node: str, instance_id: int) -> None:
        """Stop virtual machine.

        The qemu process will exit immediately.
        This is akin to pulling the power plug of a running computer
        and may damage the VM data.
        """
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/status/stop",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket}
        )

    def shutdown_instance(self, node: str, instance_id: int) -> None:
        """Shutdown virtual machine.

        This is similar to pressing the power button on a physical machine.
        This will send an ACPI event for the guest OS,
        which should then proceed to a clean shutdown.
        """
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/status/shutdown",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket}
        )

    # @Decorators.is_success
    def clone_instance(
            self,
            node: str,
            instance_id: int,
            name: str = None,
            snapshot: str = None
    ) -> requests.Response:
        """Create VM."""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }

        new_instance_id = self.get_next_id()
        data = {
            "newid": new_instance_id,
            "node": node,
            "vmid": instance_id
        }

        if name:
            data["name"] = name

        if snapshot:
            data["snapname"] = snapshot

        # {
        #     "full": "",
        #     "name": "",
        #     "snapname": "",
        #     "format": "",
        #     "storage": "",
        #     "target": "",
        # }

        self._do_post(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}/clone",
            json=data,
            http_error_map=error_map,
            cookies={COOKIES: self.ticket}
        )

        return new_instance_id

    # @Decorators.is_success
    def delete_instance(
            self,
            node: str,
            instance_id: int,
            destroy_unref_disk: bool = False,
            purge: bool = False,
            skip_lock: bool = False
    ) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
            500: UnsuccessfulOperationException,
        }

        return self._do_delete(
            path=f"nodes/{node}/{self.instance_type.value}/{instance_id}?purge={int(purge)}&destroy-unreferenced-disks={int(destroy_unref_disk)}",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket}
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
            cookies={COOKIES: self.ticket}
        )

    @Decorators.get_data()
    def create_snapshot(
            self,
            node: str,
            instance_id: int,
            snapshot_name: str,
            instance_state: int = 0
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
            cookies={COOKIES: self.ticket}
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
            cookies={COOKIES: self.ticket}
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
            cookies={COOKIES: self.ticket}
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
            cookies={COOKIES: self.ticket}
        )

    @Decorators.get_data()
    def get_net_ifaces(self, node: str, instance_id: int) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        response = self._do_get(
            path=f"/nodes/{node}/{self.instance_type.value}/{instance_id}/config",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket}
        )
        return response

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
            cookies={COOKIES: self.ticket}
        )

    @Decorators.get_data()
    def get_instance_osinfo(self, node: str, instance_id: int) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return self._do_get(
            path=f"/nodes/{node}/{self.instance_type.value}/{instance_id}/agent/network-get-interfaces",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket}
        )

    @Decorators.get_data()
    def get_instance_config(self, node: str, instance_id: int) -> requests.Response:
        """"""
        error_map = {
            400: ParamsException,
            401: AuthAPIException,
        }
        # self.session.headers.update({})

        return self._do_get(
            path=f"/nodes/{node}/{self.instance_type.value}/{instance_id}/config",
            http_error_map=error_map,
            cookies={COOKIES: self.ticket}
        )


if __name__ == "__main__":
    # session = requests.Session()
    # session.verify = ssl.CERT_NONE
    # session.headers.update({"Content-Type": "application/json"})
    # urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    #
    # url = "https://192.168.26.120:8006/api2/json/access/ticket"
    # cred = {"username": "root@pam", "password": "Password1"}
    #
    # res = session.post(url, json=cred)
    # print(res.json())

    api = ProxmoxAutomationAPI(
        address="192.168.105.21",
        # address="192.168.26.120",
        username="root@pam",
        password="Password1",
        # instance_type=InstanceType.VM
    )
    api.connect()
    res = api.attach_interface(node="proxmox1", instance_id=101, network_bridge="vmbr1",
                               interface_id="3", vlan_tag="65")
    res1 = api.get_instance_ifaces(node="proxmox1", instance_id=101)
    res = api.get_task_status(node="proxmox1", upid="UPID:proxmox1:0034308A:11F8AFA1:660C23DC:qmsnapshot:100:root@pam:")

    # print(get_node_by_vmid(instance_id=102))
    # print(api.version())
    # for i in api.get_resources(r_type="vm"):
    #     print(i)
    #
    # print(api.get_next_id())
    # for snap in api.get_snapshot_list(node="proxmox1", instance_id=100):
    #     print(snap)

    # api.create_snapshot(node="proxmox1", instance_id=100, name="working")
    # api.clone_vm(node="pve", instance_id=100)

    # for k,v in api.get_node_report(node="proxmox8").items():
    #     print(f"{k} : {v}")
    # print(api.get_node_report(node="proxmox1"))
    # print(api.get_instance_ifaces(node="pve", instance_id=102))
    # print(api.get_instance_status(node="pve", instance_id=103))
    # for instance_id in [102, 103, 104]:
    #     api.delete_vm(node="pve", instance_id=instance_id)
    # print(api.delete_vm(node="proxmox1", instance_id=120))

    # print(api.ticket)
    # print(api.token)
    print(1)

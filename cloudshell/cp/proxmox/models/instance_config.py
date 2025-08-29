from __future__ import annotations

import logging
from contextlib import suppress

from attr import define
from typing_extensions import TYPE_CHECKING, Self

from cloudshell.cp.proxmox.constants import MAC, IFACE_NAME, IP_ADDRESS, ADDRESS_TYPE, \
    IP_LIST
from cloudshell.cp.proxmox.exceptions import BaseProxmoxException, \
    VmDoesNotExistException, InstanceIsNotRunningException
from cloudshell.cp.proxmox.utils.instance_type import InstanceType

if TYPE_CHECKING:
    from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler

logger = logging.getLogger(__name__)

@define
class InstanceConfig:
    name: str
    cpu: int
    memory: str
    architecture: str
    bios_uuid: str
    os: str
    os_disk_name: str
    os_disk_size: str
    interfaces: list[dict]
    data_disks: list[dict]
    instance_type: InstanceType

    @classmethod
    def from_proxmox_instance(cls, api: ProxmoxHandler, instance_id: int) -> Self:
        config = api.get_instance_config(instance_id)
        interfaces = [v | {"name": k} for k,v in config.items() if k.startswith(
            "net")]
        if config.get("hostname"):
            return cls(
                name=config.get("hostname"),
                cpu=config.get("cores"),
                memory=config.get("memory"),
                architecture=config.get("arch"),
                bios_uuid="",
                os=config.pop("ostype"),
                os_disk_size=config.get("rootfs", {}).pop("size"),
                data_disks=[
                    v | {"name": k} for k,v in config.items() if k.startswith("mp")
                ],
                os_disk_name=list(config.pop("rootfs", {}).values())[0],
                interfaces=interfaces,
                instance_type=InstanceType.CONTAINER
            )
        else:
            guest_info = {}
            with suppress(BaseProxmoxException):
                guest_info = api.get_instance_os(instance_id)
            os_disk = next((config.pop(x) for x in config.get("boot", {}).get(
                "order", "").split(";") if x in config and config[x].get("size")), None)
            return cls(
                name=config.get("name"),
                cpu=config.get("cores"),
                memory=config.get("memory"),
                architecture=config.get("cpu"),
                bios_uuid=config.get("smbios1", {}).get("uuid"),
                os=guest_info,
                os_disk_size=os_disk.pop("size"),
                os_disk_name=list(os_disk.values())[0],
                interfaces=interfaces,
                data_disks=[
                    v for k,v in config.items() if ((k.startswith("scsi") and not k.startswith("scsihw"))
                    or k.startswith("ide") or k.startswith("sata")
                    or k.startswith("virtio")) and v.get("media") != "cdrom"
                ],
                instance_type=InstanceType.VM
            )
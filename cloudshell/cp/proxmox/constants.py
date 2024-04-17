from __future__ import annotations


SHELL_NAME = "Proxmox Cloud Provider 2G"
STATIC_SHELL_NAME = "Generic Static Proxmox VM 2G"

VM_FROM_VM_DEPLOYMENT_PATH = f"{SHELL_NAME}.Proxmox VM From VM 2G"
VM_FROM_TEMPLATE_DEPLOYMENT_PATH = f"{SHELL_NAME}.Proxmox VM From Template 2G"
CONTAINER_FROM_IMAGE_DEPLOYMENT_PATH = (f"{SHELL_NAME}.Proxmox Container From "
                                            f"Image 2G")
VM_FROM_QEMU_DEPLOYMENT_PATH = f"{SHELL_NAME}.Proxmox VM From QEMU Image 2G"


COOKIES = "PVEAuthCookie"
TOKEN = "CSRFPreventionToken"

CPU = "cpus"
RAM = "maxmem"
DISK_SIZE = "maxdisk"

ADDRESS_TYPE = "ip-address-type"
IP_LIST = "ip-addresses"
IP_ADDRESS = "ip-address"
MAC = "hardware-address"
IFACE_NAME = "name"

SNAPSHOT_TYPE = "proxmox_snapshot"

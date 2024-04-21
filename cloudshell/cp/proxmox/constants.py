from __future__ import annotations

SHELL_NAME = "Proxmox Cloud Provider 2G"
STATIC_SHELL_NAME = "Generic Static Proxmox VM 2G"

VM_FROM_VM_DEPLOYMENT_PATH = f"{SHELL_NAME}.Proxmox Instance From VM 2G"
VM_FROM_TEMPLATE_DEPLOYMENT_PATH = f"{SHELL_NAME}.Proxmox Instance From Template 2G"
CONTAINER_FROM_IMAGE_DEPLOYMENT_PATH = (f"{SHELL_NAME}.Proxmox Instance From "
                                        f"Container Image 2G")
VM_FROM_QEMU_DEPLOYMENT_PATH = f"{SHELL_NAME}.Proxmox Instance From QEMU Image 2G"
CONTAINER_FROM_CONTAINER_DEPLOYMENT_PATH = (f"{SHELL_NAME}.Proxmox Instance From "
                                            f"Container 2G")

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

CI_USER = "ciuser"
CI_PASSWORD = "cipassword"
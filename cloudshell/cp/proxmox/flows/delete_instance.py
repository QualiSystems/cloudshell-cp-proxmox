from __future__ import annotations

import logging

from attrs import define
from typing import TYPE_CHECKING

from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler

if TYPE_CHECKING:
    from cloudshell.cp.proxmox.models.deployed_app import BaseProxmoxDeployedApp
    from cloudshell.cp.proxmox.resource_config import (
        ProxmoxResourceConfig,
    )

logger = logging.getLogger(__name__)


@define
class ProxmoxDeleteFlow:
    _si: ProxmoxHandler
    _deployed_app: BaseProxmoxDeployedApp
    _resource_config: ProxmoxResourceConfig

    def delete(self) -> None:
        """Power ON Virtual Machine."""
        logger.info(f"Powering On the {self._deployed_app.vmdetails.uid}")
        self._si.delete_vm(vm_id=int(self._deployed_app.vmdetails.uid))

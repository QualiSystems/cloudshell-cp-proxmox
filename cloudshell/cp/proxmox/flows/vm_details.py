from __future__ import annotations

from attrs import define
from typing import TYPE_CHECKING

from cloudshell.cp.core.cancellation_manager import CancellationContextManager
from cloudshell.cp.core.flows import AbstractVMDetailsFlow
from cloudshell.cp.core.request_actions.models import VmDetailsData
from cloudshell.cp.proxmox.actions.vm_details import VMDetailsActions

if TYPE_CHECKING:
    from cloudshell.cp.proxmox.models.deployed_app import BaseProxmoxDeployedApp
    from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
    from cloudshell.cp.proxmox.resource_config import (
        ProxmoxResourceConfig,
    )


@define
class ProxmoxGetVMDetailsFlow(AbstractVMDetailsFlow):
    _si: ProxmoxHandler
    _resource_config: ProxmoxResourceConfig
    _cancellation_manager: CancellationContextManager

    def _get_vm_details(self, deployed_app: BaseProxmoxDeployedApp) -> VmDetailsData:
        return VMDetailsActions(
            self._si,
            self._resource_config,
            self._cancellation_manager,
        ).create(deployed_app)

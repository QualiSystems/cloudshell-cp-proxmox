from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from attrs import define

from cloudshell.cp.proxmox.actions.validation import ValidationActions
from cloudshell.shell.core.driver_context import AutoLoadDetails

if TYPE_CHECKING:
    from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
    from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig

logger = logging.getLogger(__name__)


@define
class ProxmoxAutoloadFlow:
    _si: ProxmoxHandler
    _resource_config: ProxmoxResourceConfig

    def discover(self) -> AutoLoadDetails:
        validation_actions = ValidationActions(self._si, self._resource_config)
        validation_actions.validate_resource_conf()

        version = self._si.version()
        logger.debug(f"Proxmox version:  {version}")

        return AutoLoadDetails([], [])

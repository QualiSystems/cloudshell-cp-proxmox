from __future__ import annotations

import logging

from attrs import define
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
    from cloudshell.cp.proxmox.models.deployed_app import BaseProxmoxDeployedApp
    from cloudshell.cp.proxmox.resource_config import (
        ShutdownMethod,
        ProxmoxResourceConfig,
    )

logger = logging.getLogger(__name__)


@define
class ProxmoxPowerFlow:
    _si: ProxmoxHandler
    _deployed_app: BaseProxmoxDeployedApp
    _resource_config: ProxmoxResourceConfig

    def power_on(self):
        """Power ON Virtual Machine."""
        logger.info(f"Powering On the {self._deployed_app.vmdetails.uid}")
        self._si.start_instance(instance_id=int(self._deployed_app.vmdetails.uid))

    def power_off(self):
        """Power OFF Virtual Machine."""
        logger.info(f"Powering Off {self._deployed_app.vmdetails.uid}")
        soft = self._resource_config.shutdown_method is ShutdownMethod.SOFT
        self._si.stop_instance(
            instance_id=int(self._deployed_app.vmdetails.uid),
            soft=soft
        )

from __future__ import annotations

import logging
from contextlib import suppress
from http.client import RemoteDisconnected
from typing import TYPE_CHECKING

from attrs import define

from cloudshell.cp.proxmox.exceptions import VmDoesNotExistException, \
    BaseProxmoxException
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from cloudshell.cp.proxmox.utils.instance_type import InstanceType

if TYPE_CHECKING:
    from cloudshell.cp.proxmox.models.deployed_app import BaseProxmoxDeployedApp
    from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig

logger = logging.getLogger(__name__)


@define
class ProxmoxDeleteFlow:
    _deployed_app: BaseProxmoxDeployedApp
    _resource_config: ProxmoxResourceConfig

    def delete(self) -> None:
        """Power ON Virtual Machine."""
        si = ProxmoxHandler.from_config(self._resource_config)
        instance_conf = None
        with suppress(BaseProxmoxException):
            instance_conf = si.get_instance(int(self._deployed_app.vmdetails.uid))
        if not instance_conf:
            si = ProxmoxHandler.from_config(
                self._resource_config,
                InstanceType.CONTAINER
            )

        logger.info(f"Powering Off and Deleting the {self._deployed_app.vmdetails.uid}")
        try:
            si.delete_instance(instance_id=int(self._deployed_app.vmdetails.uid))
        except RemoteDisconnected:
            if not instance_conf:
                si = ProxmoxHandler.from_config(
                    self._resource_config,
                    InstanceType.CONTAINER
                )
            else:
                si = ProxmoxHandler.from_config(
                    self._resource_config,
                    InstanceType.VM
                )
                si.delete_instance(instance_id=int(self._deployed_app.vmdetails.uid))

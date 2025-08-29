from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from attrs import define

from cloudshell.cp.core.cancellation_manager import CancellationContextManager
from cloudshell.cp.core.flows import AbstractVMDetailsFlow
from cloudshell.cp.core.request_actions.models import VmDetailsData
from cloudshell.cp.proxmox.actions.vm_details import VMDetailsActions
from cloudshell.cp.proxmox.constants import CONTAINER_FROM_CONTAINER_DEPLOYMENT_PATH
from cloudshell.cp.proxmox.exceptions import BaseProxmoxException
from cloudshell.cp.proxmox.utils.instance_type import InstanceType
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler

if TYPE_CHECKING:
    from cloudshell.cp.proxmox.models.deployed_app import BaseProxmoxDeployedApp
    from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig


logger = logging.getLogger(__name__)


@define
class ProxmoxGetVMDetailsFlow(AbstractVMDetailsFlow):
    _resource_config: ProxmoxResourceConfig
    _cancellation_manager: CancellationContextManager

    def __attrs_post_init__(self):
        super().__init__(logger)

    def _get_vm_details(self, deployed_app: BaseProxmoxDeployedApp) -> VmDetailsData:
        instance_id = int(deployed_app.vmdetails.uid)
        si = ProxmoxHandler.from_config(self._resource_config)
        instance = None
        with suppress(BaseProxmoxException):
            instance = si.get_instance(instance_id)
        if not instance:
            si = ProxmoxHandler.from_config(self._resource_config, InstanceType.CONTAINER)

        return VMDetailsActions(
            si,
            self._resource_config,
            self._cancellation_manager,
        ).create(instance_id, deployed_app)

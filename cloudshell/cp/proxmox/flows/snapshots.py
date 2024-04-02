from __future__ import annotations

import datetime
import logging

from attrs import define
from typing import TYPE_CHECKING

from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from cloudshell.cp.proxmox.constants import SNAPSHOT_TYPE
from cloudshell.cp.proxmox.exceptions import (
    InvalidOrchestrationType,
    InvalidCommandParam
)
from cloudshell.shell.core.orchestration_save_restore import OrchestrationSaveRestore


if TYPE_CHECKING:
    from cloudshell.api.cloudshell_api import CloudShellAPISession
    from cloudshell.cp.proxmox.models.deployed_app import BaseProxmoxDeployedApp
    from cloudshell.cp.proxmox.resource_config import (
        ProxmoxResourceConfig,
    )

logger = logging.getLogger(__name__)


def _validate_dump_memory_param(dump_memory: str):
    expected_values = ("Yes", "No")
    if dump_memory not in ("Yes", "No"):
        raise InvalidCommandParam(
            param_name="save_memory",
            param_value=dump_memory,
            expected_values=expected_values,
        )


@define
class ProxmoxSnapshotFlow:
    _si: ProxmoxHandler
    _deployed_app: BaseProxmoxDeployedApp
    _resource_config: ProxmoxResourceConfig

    def save_snapshot(self, snapshot_name: str, dump_memory: str) -> str:
        _validate_dump_memory_param(dump_memory)
        dump_memory = dump_memory == "Yes"
        snapshot_path = self._si.create_snapshot(
            vm_id=int(self._deployed_app.vmdetails.uid),
            name=snapshot_name,
            dump_memory=dump_memory
        )
        return snapshot_path

    def restore_from_snapshot(
        self,
        cs_api: CloudShellAPISession,
        snapshot_path: str,
    ):
        self._si.restore_from_snapshot(
            vm_id=int(self._deployed_app.vmdetails.uid),
            name=snapshot_path,
        )
        cs_api.SetResourceLiveStatus(self._deployed_app.name, "Offline", "Powered Off")

    def orchestration_save(self) -> str:
        snapshot_name = datetime.now().strftime("%y_%m_%d %H_%M_%S_%f")
        snapshot_path = self.save_snapshot(snapshot_name, dump_memory="No")
        path = f"{SNAPSHOT_TYPE}:{snapshot_path}"

        result = OrchestrationSaveRestore(
            self._resource_config.name
        ).prepare_orchestration_save_result(path)
        return result

    def orchestration_restore(self, artifacts_info: str, cs_api: CloudShellAPISession):
        result = OrchestrationSaveRestore(
            self._resource_config.name
        ).parse_orchestration_save_result(artifacts_info)
        type_, snapshot_path = result["path"].split(":", 1)
        if not type_ == SNAPSHOT_TYPE:
            raise InvalidOrchestrationType(type_)

        self.restore_from_snapshot(cs_api, snapshot_path)

    def remove_snapshot(self, snapshot_name: str) -> None:
        self._si.delete_snapshot(
            vm_id=int(self._deployed_app.vmdetails.uid),
            name=snapshot_name,
        )

from __future__ import annotations

import logging
import time

from cloudshell.cp.core.cancellation_manager import CancellationContextManager
from cloudshell.cp.core.rollback import RollbackCommand, RollbackCommandsManager

from cloudshell.cp.proxmox.exceptions import UnsuccessfulOperationException
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from cloudshell.shell.core.driver_utils import GlobalLock

logger = logging.getLogger(__name__)


class CloneVMCommand(RollbackCommand, GlobalLock):
    def __init__(
        self,
        api: ProxmoxHandler,
        instance_id: int,
        rollback_manager: RollbackCommandsManager,
        cancellation_manager: CancellationContextManager,
        full: bool,
        instance_name: str,
        target_storage: str,
        target_node: str,
        instance_snapshot: str | None = None,
    ):
        super().__init__(
            rollback_manager=rollback_manager, cancellation_manager=cancellation_manager
        )
        self._api = api
        self._src_instance_id = instance_id
        self._instance_name = instance_name
        self._full = full
        self._target_storage = target_storage
        self._target_node = target_node
        self._vm_snapshot = instance_snapshot
        self._cloned_vm_id: int | None = None

    def _execute(self) -> int:
        src_node = self._api.get_node_by_vmid(self._src_instance_id)

        retry = 0
        while retry <= 5:
            # with suppress(UnsuccessfulOperationException):
            try:
                new_vm_id, up_id = self._execute_deploy(src_node)
                self._api.wait_for_deploy_to_complete(
                    instance_node=src_node,
                    upid=up_id,
                    instance_name=self._instance_name
                )
                self._api.get_node_by_vmid(new_vm_id)
                return new_vm_id
            except UnsuccessfulOperationException as e:
                logger.warning(f"Deploy request for {self._instance_name} failed with:"
                               f" {e}\n Retrying...", exc_info=True)
                retry += 1

        raise UnsuccessfulOperationException(f"Failed to deploy {self._instance_name}")

    @GlobalLock.lock
    def _execute_deploy(self, node) -> tuple[str, str]:
        result = self._api.clone_instance(
            instance_id=self._src_instance_id,
            instance_name=self._instance_name,
            instance_node=node,
            snapshot=self._vm_snapshot,
            full=self._full,
            target_storage=self._target_storage,
            target_node=self._target_node,
        )
        time.sleep(5)
        return result

    def rollback(self):
        if self._cloned_vm_id:
            self._api.delete_instance(self._cloned_vm_id)

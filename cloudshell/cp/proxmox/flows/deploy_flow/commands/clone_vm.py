from __future__ import annotations

from contextlib import suppress
from typing import Dict

from cloudshell.cp.core.cancellation_manager import CancellationContextManager
from cloudshell.cp.core.rollback import RollbackCommand, RollbackCommandsManager

from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler


class CloneVMCommand(RollbackCommand):
    def __init__(
        self,
        api: ProxmoxHandler,
        vm_template: str,
        rollback_manager: RollbackCommandsManager,
        cancellation_manager: CancellationContextManager,
        vm_name: str,
        vm_storage: str,
        vm_snapshot: str | None = None,
        user_data: dict | None = None,
    ):
        super().__init__(
            rollback_manager=rollback_manager, cancellation_manager=cancellation_manager
        )
        self._api = api
        self._vm_template = vm_template
        self._vm_name = vm_name
        self._vm_storage = vm_storage
        self._vm_snapshot = vm_snapshot
        self._user_data = user_data
        self._cloned_vm: str | None = None

    def _execute(self) -> str:
        try:
            vm_id = int(self._vm_template)
        except ValueError:
            vm_id = self._api.get_vm_id(self._vm_template)

        try:
            vm = self._api.clone_vm(
                vm_id=vm_id,
                vm_name=self._vm_name,
                node=self._vm_storage,
                snapshot=self._vm_snapshot,
            )
        except Exception:
            # with suppress(FolderIsNotEmpty):
            #     self._vm_folder.destroy()
            raise
        else:
            self._cloned_vm = vm
            return vm

    def rollback(self):
        if self._cloned_vm:
            self._cloned_vm.delete()
        # with suppress(FolderIsNotEmpty):
        #     self._vm_folder.destroy()

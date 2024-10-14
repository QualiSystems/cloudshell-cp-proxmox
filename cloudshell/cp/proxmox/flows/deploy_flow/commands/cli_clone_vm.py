from __future__ import annotations

from cloudshell.cp.core.cancellation_manager import CancellationContextManager
from cloudshell.cp.core.rollback import RollbackCommand, RollbackCommandsManager
from cloudshell.shell.core.driver_utils import GlobalLock

from cloudshell.cp.proxmox.flows.deploy_flow.commands import CloneVMCommand
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler


class CLICloneVMCommand(CloneVMCommand):

    def _execute(self) -> int:
        try:
            self._cloned_vm_id = self._api.clone_instance(
                instance_id=self._src_instance_id,
                instance_name=self._instance_name,
                snapshot=self._vm_snapshot,
                full=self._full,
                target_storage=self._target_storage,
                target_node=self._target_node,
            )
        except Exception as e:
            raise

        return self._cloned_vm_id



    def rollback(self):
        if self._cloned_vm_id:
            self._api.delete_instance(self._cloned_vm_id)

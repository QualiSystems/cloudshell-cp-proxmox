from __future__ import annotations

from cloudshell.cp.core.cancellation_manager import CancellationContextManager
from cloudshell.cp.core.rollback import RollbackCommand, RollbackCommandsManager

from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig


class DeployVMFromImageCommand(RollbackCommand):
    def __init__(
        self,
        rollback_manager: RollbackCommandsManager,
        cancellation_manager: CancellationContextManager,
        resource_conf: ProxmoxResourceConfig,
        vcenter_image: str,
        vcenter_image_arguments: list[str],
        vm_name: str,
        vm_storage: DatastoreHandler,
    ):
        super().__init__(
            rollback_manager=rollback_manager, cancellation_manager=cancellation_manager
        )
        self._resource_conf = resource_conf
        self._vcenter_image = vcenter_image
        self._vcenter_image_arguments = vcenter_image_arguments
        self._vm_name = vm_name
        self._vm_storage = vm_storage
        self._deployed_vm: str | None = None

    def _execute(self) -> str:
        ovf_tool_script = OVFToolScript(
            ovf_tool_path=self._resource_conf.ovf_tool_path,
            datacenter=self._resource_conf.default_datacenter,
            vm_cluster=self._resource_conf.vm_cluster,
            vm_storage=self._vm_storage.name,
            vm_folder=str(self._vm_folder_path),
            vm_resource_pool=self._resource_conf.vm_resource_pool,
            vm_name=self._vm_name,
            vcenter_image=self._vcenter_image,
            custom_args=self._vcenter_image_arguments,
            vcenter_user=self._resource_conf.user,
            vcenter_password=self._resource_conf.password,
            vcenter_host=self._resource_conf.address,
        )
        ovf_tool_script.run()

        path = self._vm_folder_path + self._vm_name
        vm = self._dc.get_vm_by_path(path)
        self._deployed_vm = vm
        return vm

    def rollback(self):
        if self._deployed_vm:
            self._deployed_vm.delete()

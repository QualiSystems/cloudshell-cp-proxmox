from __future__ import annotations

from .autoload import ProxmoxAutoloadFlow
from .delete_instance import ProxmoxDeleteFlow
from .power_flow import ProxmoxPowerFlow
from .snapshots import ProxmoxSnapshotFlow
from .vm_details import ProxmoxGetVMDetailsFlow

__all__ = (
    ProxmoxAutoloadFlow,
    ProxmoxPowerFlow,
    ProxmoxDeleteFlow,
    ProxmoxSnapshotFlow,
    ProxmoxGetVMDetailsFlow,
)

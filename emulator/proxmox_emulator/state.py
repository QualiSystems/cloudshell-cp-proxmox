"""In-memory, thread-safe state store for the emulator.

Everything the emulator knows about (nodes, VMs, in-flight tasks) lives in a
plain dict, scoped to the process's lifetime -- no disk persistence. Restart
the emulator and every VM (including ones you explicitly created) is gone,
which keeps repeated test runs clean and avoids Windows file-locking issues
that come with writing state to disk.

Vmids 100-500 are a standing mock range: any operation on an id in that range
succeeds, whether or not a VM was ever explicitly created there. Reads for an
uncreated id in that range synthesize a default VM on the fly (not stored);
mutations (start/stop/create/clone) store the result, so subsequent reads see
consistent state for the rest of the session. Ids above 500 behave like real
Proxmox: they only exist if explicitly created/cloned, and there is no ceiling
on what id create/clone can target.
"""

import copy
import re
import threading
import time

from .errors import ProxmoxApiError
from .upid import generate_upid

_MAC_RE = re.compile(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")

VMID_MIN = 100
VMID_MAX = 999999999

# Standing mock range: any operation on a vmid <= this value succeeds, even if
# it was never explicitly created. Lets a caller control success vs. failure
# purely by choosing an id, without a create/clone call first. Ids above this
# value behave like real Proxmox -- they only exist if explicitly created.
VMID_AUTOVIVIFY_MAX = 500

# Real Proxmox VM lifecycle knows more states (paused, suspended, ...); the
# driver only needs to tell "stopped" apart from "running" for now.
STATUS_STOPPED = "stopped"
STATUS_RUNNING = "running"


class ProxmoxState:
    def __init__(self, state_path, node_name="pve", action_delay=0.0):
        self._path = state_path  # unused; kept for API compat
        self._node = node_name
        self._delay = max(0.0, action_delay)
        self._lock = threading.RLock()
        self._data = {"nodes": {node_name: {"status": "online"}}, "vms": {}, "tasks": {}}

    def reset(self):
        """Clear all in-memory VMs and tasks. Starts empty, same as __init__."""
        with self._lock:
            self._data = {"nodes": {self._node: {"status": "online"}}, "vms": {}, "tasks": {}}

    def dump(self):
        """Debug-only snapshot of the full state dict -- never used as a source of truth."""
        with self._lock:
            return copy.deepcopy(self._data)

    def _default_vm(self, vmid_int, node):
        return {
            "vmid": vmid_int,
            "node": node,
            "name": "vm{}".format(vmid_int),
            "cores": 1,
            "sockets": 1,
            "memory": 512,
            "ostype": "l26",
            "template": 0,
            "status": STATUS_STOPPED,
            "start_time": None,
            "created_at": time.time(),
            "config_extra": {},
        }

    # -- helpers -----------------------------------------------------------

    def _touch_node(self, node):
        """Mock cluster: any node name is a valid member, registered on first mention.

        Real Proxmox would reject a node that never joined the cluster. This emulator
        deliberately doesn't model cluster membership/join semantics -- it auto-registers
        whatever node a caller addresses, so multi-node scenarios (e.g. a clone's `target`
        naming a different node) succeed without any setup step, matching the 100-500
        vmid auto-vivification philosophy elsewhere in this file.
        """
        with self._lock:
            self._data["nodes"].setdefault(node, {"status": "online"})

    @staticmethod
    def _validate_vmid(vmid):
        try:
            vmid_int = int(vmid)
        except (TypeError, ValueError):
            raise ProxmoxApiError(400, errors={"vmid": "value does not look like a valid VM ID"})
        if not (VMID_MIN <= vmid_int <= VMID_MAX):
            raise ProxmoxApiError(400, errors={"vmid": "value does not look like a valid VM ID"})
        return vmid_int

    def _get_vm_or_404(self, node, vmid):
        """Read-path lookup: synthesizes (without storing) for the mock range."""
        self._touch_node(node)
        vmid_int = self._validate_vmid(vmid)
        key = str(vmid_int)
        vm = self._data["vms"].get(key)
        if vm is None:
            if vmid_int <= VMID_AUTOVIVIFY_MAX:
                return self._default_vm(vmid_int, node)
            raise ProxmoxApiError(
                500, message="Configuration file 'nodes/{}/qemu/{}.conf' does not exist".format(node, key)
            )
        return vm

    def _get_vm_for_mutation(self, node, vmid):
        """Mutation-path lookup: same success rule, but persists mock-range VMs on first touch."""
        vm = self._get_vm_or_404(node, vmid)
        key = str(vm["vmid"])
        if key not in self._data["vms"]:
            self._data["vms"][key] = vm
        return vm

    def _create_task(self, node, task_type, task_id, user):
        upid = generate_upid(node, task_type, task_id=task_id, user=user)
        now = time.time()
        self._data["tasks"][upid] = {
            "node": node,
            "type": task_type,
            "vmid": str(task_id),
            "user": user,
            "starttime": now,
            "finish_at": now + self._delay,
            "exitstatus": "OK",
        }
        return upid

    # -- nodes ---------------------------------------------------------

    def node_summary(self):
        """Mirrors GET /nodes: one entry per node any caller has addressed so far."""
        return [
            {
                "node": name,
                "status": "online",
                "type": "node",
                "cpu": 0.05,
                "maxcpu": 8,
                "mem": 4294967296,
                "maxmem": 34359738368,
                "uptime": 864000,
                "level": "",
            }
            for name in sorted(self._data["nodes"])
        ]

    def node_status(self, node):
        self._touch_node(node)
        return {
            "cpu": 0.05,
            "memory": {"free": 30064771072, "total": 34359738368, "used": 4294967296},
            "uptime": 864000,
            "pveversion": "pve-manager/8.2.4/emulated",
            "kversion": "Linux 6.8.0-emulated",
        }

    # -- cluster ---------------------------------------------------------

    def cluster_resources(self, r_type=None):
        """Mirrors GET /cluster/resources.

        The real driver resolves "which node is vmid X on" purely from this
        endpoint, so every vmid in the 100-500 mock range must appear here even
        if never explicitly created -- synthesized on the fly, not stored.
        """
        if r_type not in (None, "", "vm", "qemu"):
            return []

        vms_by_id = dict(self._data["vms"])
        for vmid in range(VMID_MIN, VMID_AUTOVIVIFY_MAX + 1):
            key = str(vmid)
            if key not in vms_by_id:
                vms_by_id[key] = self._default_vm(vmid, self._node)

        resources = []
        for vm in vms_by_id.values():
            status = self._vm_status(vm)
            resources.append(
                {
                    "id": "qemu/{}".format(vm["vmid"]),
                    "type": "qemu",
                    "vmid": vm["vmid"],
                    "node": vm["node"],
                    "name": vm["name"],
                    "status": vm["status"],
                    "template": vm["template"],
                    "cpu": status["cpu"],
                    "maxcpu": status["cpus"],
                    "mem": status["mem"],
                    "maxmem": status["maxmem"],
                    "disk": status["disk"],
                    "maxdisk": status["maxdisk"],
                    "uptime": status["uptime"],
                    "pool": "",
                }
            )
        return sorted(resources, key=lambda r: r["vmid"])

    def get_next_free_vmid(self):
        """Mirrors GET /cluster/nextid: lowest unused vmid >= VMID_MIN."""
        candidate = VMID_MIN
        used = set(int(v) for v in self._data["vms"])
        while candidate in used:
            candidate += 1
        return candidate

    # -- qemu: read ------------------------------------------------------

    def list_vms(self, node):
        """Mirrors GET /nodes/{node}/qemu: only VMs actually stored on this node."""
        self._touch_node(node)
        summaries = []
        for vm in self._data["vms"].values():
            if vm["node"] == node:
                summaries.append(self._vm_summary(vm))
        return sorted(summaries, key=lambda v: v["vmid"])

    def get_config(self, node, vmid):
        vm = self._get_vm_or_404(node, vmid)
        config = {
            "vmid": vm["vmid"],
            "name": vm["name"],
            "cores": vm["cores"],
            "sockets": vm["sockets"],
            "memory": vm["memory"],
            "ostype": vm["ostype"],
            "template": vm["template"],
            "net0": "virtio={},bridge=vmbr0".format(self._default_mac(vm["vmid"])),
            "digest": "emulated{:040d}".format(vm["vmid"]),
        }
        config.update(vm.get("config_extra", {}))
        return config

    @staticmethod
    def _default_mac(vmid_int):
        """Deterministic per-vmid MAC (52:54:00 is the real QEMU/KVM OUI prefix).

        Used both as the default net0 config and to derive the matching guest-agent
        interface below, so a fresh VM has a self-consistent config <-> IP pairing
        without any caller having to set one up first.
        """
        return "52:54:00:{:02X}:{:02X}:{:02X}".format(
            (vmid_int >> 16) & 0xFF, (vmid_int >> 8) & 0xFF, vmid_int & 0xFF
        )

    @staticmethod
    def _default_ip(vmid_int):
        return "10.0.{}.{}".format((vmid_int >> 8) & 0xFF, vmid_int & 0xFF)

    def get_status(self, node, vmid):
        vm = self._get_vm_or_404(node, vmid)
        return self._vm_status(vm)

    def _vm_summary(self, vm):
        status = self._vm_status(vm)
        return {
            "vmid": vm["vmid"],
            "name": vm["name"],
            "status": vm["status"],
            "template": vm["template"],
            "cpus": vm["cores"] * vm["sockets"],
            "maxmem": status["maxmem"],
            "mem": status["mem"],
            "maxdisk": status["maxdisk"],
            "disk": status["disk"],
            "uptime": status["uptime"],
        }

    def _vm_status(self, vm):
        running = vm["status"] == STATUS_RUNNING
        now = time.time()
        uptime = int(now - vm["start_time"]) if running and vm.get("start_time") else 0
        maxmem = vm["memory"] * 1024 * 1024
        maxdisk = vm.get("disk_size", 32) * 1024 * 1024 * 1024
        status = {
            "vmid": vm["vmid"],
            "name": vm["name"],
            "status": vm["status"],
            "qmpstatus": vm["status"],
            "template": vm["template"],
            "cpus": vm["cores"] * vm["sockets"],
            "cpu": round(0.02 + 0.01 * (vm["vmid"] % 5), 4) if running else 0,
            "maxmem": maxmem,
            "mem": int(maxmem * 0.35) if running else 0,
            "maxdisk": maxdisk,
            "disk": 0,
            "uptime": uptime,
            "pid": (200000 + vm["vmid"]) if running else None,
        }
        # Real Proxmox only includes "lock" while an operation (clone, backup,
        # migrate, ...) actually holds the VM locked, and omits the key
        # otherwise. The driver's status poller
        # (ProxmoxAutomationAPI.Decorators.is_instance_locked) treats *any*
        # present "lock" value -- including "" -- as still-locked and will
        # retry for up to 5 minutes before giving up, so never add this key
        # for an unlocked VM.
        if vm.get("lock"):
            status["lock"] = vm["lock"]
        return status

    # -- qemu: create / clone / delete -----------------------------------

    def create_vm(self, node, vmid, params, user):
        self._touch_node(node)
        vmid_int = self._validate_vmid(vmid)
        key = str(vmid_int)
        with self._lock:
            if key in self._data["vms"]:
                raise ProxmoxApiError(400, errors={"vmid": "VM {} already exists".format(vmid_int)})
            known = {"vmid", "node", "name", "cores", "sockets", "memory", "ostype"}
            vm = {
                "vmid": vmid_int,
                "node": node,
                "name": params.get("name") or "vm{}".format(vmid_int),
                "cores": int(params.get("cores", 1)),
                "sockets": int(params.get("sockets", 1)),
                "memory": int(params.get("memory", 512)),
                "ostype": params.get("ostype", "l26"),
                "template": 0,
                "status": STATUS_STOPPED,
                "start_time": None,
                "created_at": time.time(),
                "config_extra": {k: v for k, v in params.items() if k not in known},
            }
            self._data["vms"][key] = vm
        return self._create_task(node, "qmcreate", key, user)

    def clone_vm(self, node, source_vmid, newid, params, user):
        """Clone within `node`, or onto `target` if the caller asked for a different node.

        Mirrors real Proxmox's clone-with-migration `target` param
        (`ProxmoxAutomationAPI.clone_instance` sends it as `data["target"]`). Any node name
        is accepted -- see `_touch_node` -- so the new VM ends up genuinely stored under
        whichever node was requested, keeping later `cluster/resources` lookups (and thus
        the driver's `get_node_by_vmid`) consistent with where the clone actually landed.
        """
        source = self._get_vm_or_404(node, source_vmid)
        vmid_int = self._validate_vmid(newid)
        key = str(vmid_int)
        target_node = params.get("target") or node
        self._touch_node(target_node)
        with self._lock:
            if key in self._data["vms"]:
                raise ProxmoxApiError(400, errors={"newid": "VM {} already exists".format(vmid_int)})
            vm = {
                "vmid": vmid_int,
                "node": target_node,
                "name": params.get("name") or "vm{}".format(vmid_int),
                "cores": source["cores"],
                "sockets": source["sockets"],
                "memory": source["memory"],
                "ostype": source["ostype"],
                "template": 0,
                "status": STATUS_STOPPED,
                "start_time": None,
                "created_at": time.time(),
                "cloned_from": source["vmid"],
                "config_extra": dict(source.get("config_extra", {})),
            }
            self._data["vms"][key] = vm
        return self._create_task(node, "qmclone", key, user)

    def delete_vm(self, node, vmid, user):
        vm = self._get_vm_or_404(node, vmid)
        key = str(vm["vmid"])
        with self._lock:
            if vm["status"] == STATUS_RUNNING:
                raise ProxmoxApiError(
                    500, message="VM {} is running - stop it first".format(vm["vmid"])
                )
            # Only try to delete from memory if it was explicitly created (not logical).
            if key in self._data["vms"]:
                del self._data["vms"][key]
        return self._create_task(node, "qmdestroy", key, user)

    # -- qemu: power state -------------------------------------------------

    def start_vm(self, node, vmid, user):
        with self._lock:
            vm = self._get_vm_for_mutation(node, vmid)
            key = str(vm["vmid"])
            if vm["status"] != STATUS_RUNNING:
                vm["status"] = STATUS_RUNNING
                vm["start_time"] = time.time()
        return self._create_task(node, "qmstart", key, user)

    def stop_vm(self, node, vmid, user):
        with self._lock:
            vm = self._get_vm_for_mutation(node, vmid)
            key = str(vm["vmid"])
            vm["status"] = STATUS_STOPPED
            vm["start_time"] = None
        return self._create_task(node, "qmstop", key, user)

    def shutdown_vm(self, node, vmid, user):
        """Graceful ACPI shutdown -- same end state as stop_vm, distinct task type."""
        with self._lock:
            vm = self._get_vm_for_mutation(node, vmid)
            key = str(vm["vmid"])
            vm["status"] = STATUS_STOPPED
            vm["start_time"] = None
        return self._create_task(node, "qmshutdown", key, user)

    # -- qemu: snapshots ---------------------------------------------------
    #
    # Real Proxmox always lists a synthetic "current" entry (the live-state
    # pointer) alongside actual snapshots; it can't be rolled back to or
    # deleted. Mirrored here for GET fidelity, but rejected as a target for
    # the mutating ops below, same as real Proxmox.

    def list_snapshots(self, node, vmid):
        vm = self._get_vm_or_404(node, vmid)
        names = sorted(vm.get("snapshots", {}))
        return [{"name": n} for n in names] + [{"name": "current"}]

    def create_snapshot(self, node, vmid, name, vmstate, user):
        if name == "current":
            raise ProxmoxApiError(400, message="snapshot name 'current' is reserved")
        with self._lock:
            vm = self._get_vm_for_mutation(node, vmid)
            key = str(vm["vmid"])
            snapshots = vm.setdefault("snapshots", {})
            if name in snapshots:
                raise ProxmoxApiError(400, message="snapshot '{}' already exists".format(name))
            snapshots[name] = {
                "name": name,
                "vmstate": 1 if int(vmstate) else 0,
                "created_at": time.time(),
            }
        return self._create_task(node, "qmsnapshot", key, user)

    def restore_snapshot(self, node, vmid, name, user):
        """Rollback also restores the snapshot's saved power state, matching real Proxmox --

        a 'with memory' snapshot rolls back running, a disk-only one rolls back stopped.
        """
        with self._lock:
            vm = self._get_vm_for_mutation(node, vmid)
            key = str(vm["vmid"])
            snapshots = vm.get("snapshots", {})
            if name == "current" or name not in snapshots:
                raise ProxmoxApiError(400, message="no such snapshot '{}'".format(name))
            if snapshots[name]["vmstate"]:
                vm["status"] = STATUS_RUNNING
                vm["start_time"] = time.time()
            else:
                vm["status"] = STATUS_STOPPED
                vm["start_time"] = None
        return self._create_task(node, "qmrollback", key, user)

    def delete_snapshot(self, node, vmid, name, user):
        with self._lock:
            vm = self._get_vm_for_mutation(node, vmid)
            key = str(vm["vmid"])
            snapshots = vm.get("snapshots", {})
            if name == "current" or name not in snapshots:
                raise ProxmoxApiError(400, message="no such snapshot '{}'".format(name))
            del snapshots[name]
        return self._create_task(node, "qmdelsnapshot", key, user)

    # -- qemu: guest agent (backs Refresh IP) -------------------------------

    def get_agent_network_ifaces(self, node, vmid):
        """Mirrors GET .../agent/network-get-interfaces.

        Real Proxmox 500s when the QEMU guest agent isn't reachable (stopped VM, no
        agent installed) -- the driver treats that as "no data" rather than a hard
        failure, so mirror the stopped case as a 500 rather than synthesizing an
        always-present interface. Returns an IP derived from the same vmid-based MAC
        `get_config` already reports on net0, so config and agent data agree without
        any setup step.
        """
        vm = self._get_vm_or_404(node, vmid)
        if vm["status"] != STATUS_RUNNING:
            raise ProxmoxApiError(
                500, message="VM {} qmp command 'guest-network-get-interfaces' failed - got timeout".format(vm["vmid"])
            )
        config = self.get_config(node, vmid)
        mac = self._primary_mac(config) or self._default_mac(vm["vmid"])
        return {
            "result": [
                {
                    "name": "eth0",
                    "hardware-address": mac.lower(),
                    "ip-addresses": [
                        {"ip-address": self._default_ip(vm["vmid"]), "ip-address-type": "ipv4", "prefix": 24},
                    ],
                }
            ]
        }

    @staticmethod
    def _primary_mac(config):
        for key in sorted(k for k in config if k.startswith("net")):
            match = _MAC_RE.search(str(config[key]))
            if match:
                return match.group(0)
        return None

    def get_agent_osinfo(self, node, vmid):
        """Mirrors GET .../agent/get-osinfo.

        Same "500 while unreachable, else a fixed self-consistent payload" shape as
        `get_agent_network_ifaces` -- the driver's `get_instance_os` only catches a
        500 (`InstanceIsNotRunningException`) here, not a 404, so an unimplemented
        route previously surfaced as an unhandled exception instead of the "no OS
        info yet" case the driver already knows how to tolerate.
        """
        vm = self._get_vm_or_404(node, vmid)
        if vm["status"] != STATUS_RUNNING:
            raise ProxmoxApiError(
                500, message="VM {} qmp command 'guest-get-osinfo' failed - got timeout".format(vm["vmid"])
            )
        return {
            "result": {
                "id": "debian",
                "name": "Debian GNU/Linux",
                "pretty-name": "Debian GNU/Linux 11 (bullseye)",
                "version": "11",
                "version-id": "11",
                "kernel-release": "5.10.0-9-amd64",
                "machine": "x86_64",
            }
        }

    # -- tasks -----------------------------------------------------------

    def get_task_status(self, upid):
        task = self._data["tasks"].get(upid)
        if task is None:
            raise ProxmoxApiError(500, message="no such task")
        now = time.time()
        finished = now >= task["finish_at"]
        result = {
            "upid": upid,
            "node": task["node"],
            "pid": 0,
            "type": task["type"],
            "id": task["vmid"],
            "user": task["user"],
            "starttime": int(task["starttime"]),
            "status": "stopped" if finished else "running",
        }
        if finished:
            result["exitstatus"] = task.get("exitstatus", "OK")
        return result

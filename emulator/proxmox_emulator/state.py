"""Persistent, thread-safe state store for the emulator.

Everything the emulator knows about (nodes, VMs, in-flight tasks) lives in a
single JSON document on disk. Every mutation is written through immediately
(read-modify-write under a lock, atomic replace on disk) so state survives
process restarts -- create a VM, kill the emulator, start it again, and the
VM is still there.
"""

import json
import os
import tempfile
import threading
import time

from .errors import ProxmoxApiError
from .upid import generate_upid

VMID_MIN = 100
VMID_MAX = 999999999

# Real Proxmox VM lifecycle knows more states (paused, suspended, ...); the
# driver only needs to tell "stopped" apart from "running" for now.
STATUS_STOPPED = "stopped"
STATUS_RUNNING = "running"


class ProxmoxState:
    def __init__(self, state_path, node_name="pve", action_delay=0.0):
        self._path = state_path
        self._node = node_name
        self._delay = max(0.0, action_delay)
        self._lock = threading.RLock()
        self._data = self._load()

    # -- persistence -----------------------------------------------------

    def _load(self):
        if os.path.exists(self._path):
            with open(self._path, "r") as fh:
                data = json.load(fh)
            data.setdefault("vms", {})
            data.setdefault("tasks", {})
            data.setdefault("next_vmid", VMID_MIN)
            return data
        return {"vms": {}, "tasks": {}, "next_vmid": VMID_MIN}

    def _save(self):
        directory = os.path.dirname(os.path.abspath(self._path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def reset(self):
        with self._lock:
            self._data = {"vms": {}, "tasks": {}, "next_vmid": VMID_MIN}
            self._save()

    # -- helpers -----------------------------------------------------------

    def _check_node(self, node):
        if node != self._node:
            raise ProxmoxApiError(
                500, message="node '{}' not found in this emulated cluster (only '{}' exists)".format(node, self._node)
            )

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
        self._check_node(node)
        key = str(self._validate_vmid(vmid))
        vm = self._data["vms"].get(key)
        if vm is None:
            raise ProxmoxApiError(
                500, message="Configuration file 'nodes/{}/qemu/{}.conf' does not exist".format(node, key)
            )
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
        self._save()
        return upid

    # -- nodes ---------------------------------------------------------

    def node_summary(self):
        return {
            "node": self._node,
            "status": "online",
            "type": "node",
            "cpu": 0.05,
            "maxcpu": 8,
            "mem": 4294967296,
            "maxmem": 34359738368,
            "uptime": 864000,
            "level": "",
        }

    def node_status(self, node):
        self._check_node(node)
        return {
            "cpu": 0.05,
            "memory": {"free": 30064771072, "total": 34359738368, "used": 4294967296},
            "uptime": 864000,
            "pveversion": "pve-manager/8.2.4/emulated",
            "kversion": "Linux 6.8.0-emulated",
        }

    # -- qemu: read ------------------------------------------------------

    def list_vms(self, node):
        self._check_node(node)
        summaries = []
        for vm in self._data["vms"].values():
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
            "digest": "emulated{:040d}".format(vm["vmid"]),
        }
        config.update(vm.get("config_extra", {}))
        return config

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
        return {
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
            "lock": vm.get("lock", ""),
        }

    # -- qemu: create / clone / delete -----------------------------------

    def create_vm(self, node, vmid, params, user):
        self._check_node(node)
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
            if vmid_int >= self._data["next_vmid"]:
                self._data["next_vmid"] = vmid_int + 1
            self._save()
        return self._create_task(node, "qmcreate", key, user)

    def clone_vm(self, node, source_vmid, newid, params, user):
        source = self._get_vm_or_404(node, source_vmid)
        vmid_int = self._validate_vmid(newid)
        key = str(vmid_int)
        with self._lock:
            if key in self._data["vms"]:
                raise ProxmoxApiError(400, errors={"newid": "VM {} already exists".format(vmid_int)})
            vm = {
                "vmid": vmid_int,
                "node": node,
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
            if vmid_int >= self._data["next_vmid"]:
                self._data["next_vmid"] = vmid_int + 1
            self._save()
        return self._create_task(node, "qmclone", key, user)

    def delete_vm(self, node, vmid, user):
        vm = self._get_vm_or_404(node, vmid)
        key = str(vm["vmid"])
        with self._lock:
            if vm["status"] == STATUS_RUNNING:
                raise ProxmoxApiError(
                    500, message="VM {} is running - stop it first".format(vm["vmid"])
                )
            del self._data["vms"][key]
            self._save()
        return self._create_task(node, "qmdestroy", key, user)

    # -- qemu: power state -------------------------------------------------

    def start_vm(self, node, vmid, user):
        vm = self._get_vm_or_404(node, vmid)
        key = str(vm["vmid"])
        with self._lock:
            if vm["status"] != STATUS_RUNNING:
                vm["status"] = STATUS_RUNNING
                vm["start_time"] = time.time()
                self._data["vms"][key] = vm
                self._save()
        return self._create_task(node, "qmstart", key, user)

    def stop_vm(self, node, vmid, user):
        vm = self._get_vm_or_404(node, vmid)
        key = str(vm["vmid"])
        with self._lock:
            vm["status"] = STATUS_STOPPED
            vm["start_time"] = None
            self._data["vms"][key] = vm
            self._save()
        return self._create_task(node, "qmstop", key, user)

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

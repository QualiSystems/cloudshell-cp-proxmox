#!/usr/bin/env python
"""Manual walkthrough of the Proxmox emulator's API using `requests` -- the exact
same HTTP library cloudshell-cp-proxmox's ProxmoxAutomationAPI uses. Mirrors
examples.sh/examples.ps1 step-for-step, so behavior can be compared across
curl, PowerShell, and the real driver's own client library.

Usage:
    python examples.py [host] [port] [http|https]
    python examples.py                        # defaults to http://127.0.0.1:8006
    python examples.py 127.0.0.1 18006 http   # against `server.py --no-tls --port 18006`
"""
from __future__ import annotations

import json
import sys

import requests
import urllib3


def step(msg: str) -> None:
    print(f"\n\033[1;36m==> {msg}\033[0m")


def show(obj) -> None:
    print(json.dumps(obj, indent=2))


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = sys.argv[2] if len(sys.argv) > 2 else "8006"
    scheme = sys.argv[3] if len(sys.argv) > 3 else "http"
    base = f"{scheme}://{host}:{port}/api2/json"

    session = requests.Session()
    if scheme == "https":
        session.verify = False  # self-signed cert, exactly like a fresh real Proxmox node
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    step("Version (no auth required)")
    try:
        resp = session.get(f"{base}/version", timeout=5)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Could not reach {base}/version -- is the emulator running?", file=sys.stderr)
        print(f"({e})", file=sys.stderr)
        if str(port) == "8006":
            print(
                "\nNote: if the server's console shows it's listening but every\n"
                "request still resets/times out immediately, and you're running\n"
                "this inside a sandboxed or restrictively-networked shell (some CI\n"
                "runners and coding-agent sandboxes do this), that sandbox may be\n"
                "blocking Proxmox's well-known port 8006 specifically, regardless\n"
                "of client. A normal terminal session shouldn't hit this. Either\n"
                "way, running the server on a different port (e.g. --port 18006,\n"
                "passed as the 2nd arg here) sidesteps it.",
                file=sys.stderr,
            )
        return 1
    show(resp.json())

    step("Log in (POST /access/ticket with a JSON body, like the real driver)")
    resp = session.post(f"{base}/access/ticket", json={"username": "root@pam", "password": "anything"}, timeout=5)
    resp.raise_for_status()
    show(resp.json())
    ticket = resp.json()["data"]["ticket"]
    csrf = resp.json()["data"]["CSRFPreventionToken"]
    session.headers.update({"CSRFPreventionToken": csrf})
    auth_cookies = {"PVEAuthCookie": ticket}

    step("List VMs (should be empty on a fresh state file)")
    resp = session.get(f"{base}/nodes/pve/qemu", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step("Ask for the next free VM ID")
    resp = session.get(f"{base}/cluster/nextid", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())
    vmid = int(resp.json()["data"])

    step(f"Create VM {vmid} (this is what a bare 'create' looks like; the real driver always clones instead - see below)")
    resp = session.post(
        f"{base}/nodes/pve/qemu",
        json={"vmid": vmid, "name": "demo-vm", "cores": 2, "memory": 2048},
        cookies=auth_cookies,
    )
    resp.raise_for_status()
    show(resp.json())
    upid = resp.json()["data"]

    step(f"Poll the task until it's done (real UPID: {upid})")
    resp = session.get(f"{base}/nodes/pve/tasks/{upid}/status", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step(f"cluster/resources now resolves vmid {vmid} -> node (this is how the driver finds which node a VM lives on)")
    resp = session.get(f"{base}/cluster/resources", params={"type": "vm"}, cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step(f"Get VM {vmid} config")
    resp = session.get(f"{base}/nodes/pve/qemu/{vmid}/config", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step("Status before starting: should be 'stopped', and must NOT contain a 'lock' key")
    resp = session.get(f"{base}/nodes/pve/qemu/{vmid}/status/current", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step(f"Start VM {vmid}")
    resp = session.post(f"{base}/nodes/pve/qemu/{vmid}/status/start", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step("Status after starting: 'running' with mock cpu/mem/uptime data")
    resp = session.get(f"{base}/nodes/pve/qemu/{vmid}/status/current", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step("Get Snapshots (empty except the synthetic 'current' pointer)")
    resp = session.get(f"{base}/nodes/pve/qemu/{vmid}/snapshot", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step("Save Snapshot 'before-clone' (vmstate=1 -- 'with memory', VM is running)")
    resp = session.post(
        f"{base}/nodes/pve/qemu/{vmid}/snapshot",
        json={"snapname": "before-clone", "vmstate": 1},
        cookies=auth_cookies,
    )
    resp.raise_for_status()
    show(resp.json())

    step(f"Refresh IP: VM {vmid} config reports a net0 MAC")
    resp = session.get(f"{base}/nodes/pve/qemu/{vmid}/config", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step("Refresh IP: guest agent reports a matching IPv4 address (VM is running)")
    resp = session.get(f"{base}/nodes/pve/qemu/{vmid}/agent/network-get-interfaces", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step("Restore Snapshot 'before-clone' (a 'with memory' snapshot -- VM stays running)")
    resp = session.post(f"{base}/nodes/pve/qemu/{vmid}/snapshot/before-clone/rollback", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step("Remove Snapshot 'before-clone'")
    resp = session.delete(f"{base}/nodes/pve/qemu/{vmid}/snapshot/before-clone", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step(f"Clone VM {vmid} (this is the path the real driver actually uses to 'create' a VM)")
    resp = session.get(f"{base}/cluster/nextid", cookies=auth_cookies)
    resp.raise_for_status()
    new_id = int(resp.json()["data"])
    resp = session.post(
        f"{base}/nodes/pve/qemu/{vmid}/clone",
        json={"newid": new_id, "name": "demo-vm-clone"},
        cookies=auth_cookies,
    )
    resp.raise_for_status()
    show(resp.json())

    step("Both VMs now listed")
    resp = session.get(f"{base}/nodes/pve/qemu", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step("Deleting a running VM is rejected (matches real Proxmox) - expect an HTTP error here")
    resp = session.delete(f"{base}/nodes/pve/qemu/{vmid}", cookies=auth_cookies)
    print(f"HTTP {resp.status_code}: {resp.text}")

    step(f"Stop, then delete VM {vmid}")
    resp = session.post(f"{base}/nodes/pve/qemu/{vmid}/status/stop", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())
    resp = session.delete(f"{base}/nodes/pve/qemu/{vmid}", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step("Stop and delete the clone too")
    session.post(f"{base}/nodes/pve/qemu/{new_id}/status/stop", cookies=auth_cookies).raise_for_status()
    session.delete(f"{base}/nodes/pve/qemu/{new_id}", cookies=auth_cookies).raise_for_status()

    step("Final list: back to empty")
    resp = session.get(f"{base}/nodes/pve/qemu", cookies=auth_cookies)
    resp.raise_for_status()
    show(resp.json())

    step("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

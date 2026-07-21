#!/usr/bin/env bash
# Manual walkthrough of the Proxmox emulator's API using curl, mirroring exactly
# what cloudshell-cp-proxmox's ProxmoxAutomationAPI does (JSON bodies, ticket
# cookie + CSRFPreventionToken header, task-UPID polling, cluster/resources for
# vmid->node lookup). Run this against a running emulator to sanity-check that
# requests/responses look the way they should.
#
# Usage:
#   ./examples.sh [host] [port] [scheme]
#   ./examples.sh                       # defaults to https://127.0.0.1:8006
#   ./examples.sh 127.0.0.1 18006 http  # against `server.py --no-tls --port 18006`
#
# Requires: curl, python3 (only used to pretty-print/parse JSON; any python3 works)

set -euo pipefail

HOST="${1:-127.0.0.1}"
PORT="${2:-8006}"
SCHEME="${3:-https}"
BASE="${SCHEME}://${HOST}:${PORT}/api2/json"

CURL_OPTS=(-s)
if [[ "$SCHEME" == "https" ]]; then
  CURL_OPTS+=(-k) # self-signed cert, exactly like a fresh real Proxmox node
fi

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
show() { python3 -m json.tool <<<"$1" 2>/dev/null || printf '%s\n' "$1"; }
jget() { python3 -c "import sys, json; d=json.loads(sys.argv[1]); print(sys.argv[2].split('.') and __import__('functools').reduce(lambda o,k: o[k], sys.argv[2].split('.'), d))" "$1" "$2"; }

step "Version (no auth required)"
if ! resp=$(curl "${CURL_OPTS[@]}" --fail "$BASE/version"); then
  echo "Could not reach $BASE/version -- is the emulator running?" >&2
  if [[ "$PORT" == "8006" ]]; then
    echo "" >&2
    echo "Note: if the server's log shows it's listening but every request" >&2
    echo "still resets/times out immediately, and you're running this inside" >&2
    echo "a sandboxed or restrictively-networked shell (some CI runners and" >&2
    echo "coding-agent sandboxes do this), that sandbox may be blocking" >&2
    echo "Proxmox's well-known port 8006 specifically, regardless of client." >&2
    echo "A normal terminal session shouldn't hit this. Either way, running" >&2
    echo "the server on a different port (e.g. --port 18006, passed as the" >&2
    echo "2nd arg here) sidesteps it." >&2
  fi
  exit 1
fi
show "$resp"

step "Log in (POST /access/ticket with a JSON body, like the real driver)"
resp=$(curl "${CURL_OPTS[@]}" -X POST "$BASE/access/ticket" \
  -H "Content-Type: application/json" \
  -d '{"username":"root@pam","password":"anything"}')
show "$resp"
TICKET=$(jget "$resp" "data.ticket")
CSRF=$(jget "$resp" "data.CSRFPreventionToken")
AUTH_HDR=(-b "PVEAuthCookie=${TICKET}" -H "CSRFPreventionToken: ${CSRF}")

step "List VMs (should be empty on a fresh state file)"
show "$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu")"

step "Ask for the next free VM ID"
resp=$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/cluster/nextid")
show "$resp"
VMID=$(jget "$resp" "data")

step "Create VM $VMID (this is what a bare 'create' looks like; the real driver always clones instead - see below)"
resp=$(curl "${CURL_OPTS[@]}" -X POST "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu" \
  -H "Content-Type: application/json" \
  -d "{\"vmid\":${VMID},\"name\":\"demo-vm\",\"cores\":2,\"memory\":2048}")
show "$resp"
UPID=$(jget "$resp" "data")

step "Poll the task until it's done (real UPID: $UPID)"
show "$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/nodes/pve/tasks/${UPID}/status")"

step "cluster/resources now resolves vmid $VMID -> node (this is how the driver finds which node a VM lives on)"
show "$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/cluster/resources?type=vm")"

step "Get VM $VMID config"
show "$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/config")"

step "Status before starting: should be 'stopped', and must NOT contain a 'lock' key"
show "$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/status/current")"

step "Start VM $VMID"
show "$(curl "${CURL_OPTS[@]}" -X POST "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/status/start")"

step "Status after starting: 'running' with mock cpu/mem/uptime data"
show "$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/status/current")"

step "Get Snapshots (empty except the synthetic 'current' pointer)"
show "$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/snapshot")"

step "Save Snapshot 'before-clone' (vmstate=1 -- 'with memory', VM is running)"
show "$(curl "${CURL_OPTS[@]}" -X POST "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/snapshot" \
  -H "Content-Type: application/json" \
  -d '{"snapname":"before-clone","vmstate":1}')"

step "Refresh IP: VM $VMID config reports a net0 MAC"
show "$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/config")"

step "Refresh IP: guest agent reports a matching IPv4 address (VM is running)"
show "$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/agent/network-get-interfaces")"

step "Restore Snapshot 'before-clone' (a 'with memory' snapshot -- VM stays running)"
show "$(curl "${CURL_OPTS[@]}" -X POST "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/snapshot/before-clone/rollback")"

step "Remove Snapshot 'before-clone'"
show "$(curl "${CURL_OPTS[@]}" -X DELETE "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/snapshot/before-clone")"

step "Clone VM $VMID (this is the path the real driver actually uses to 'create' a VM)"
resp=$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/cluster/nextid")
NEWID=$(jget "$resp" "data")
resp=$(curl "${CURL_OPTS[@]}" -X POST "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/clone" \
  -H "Content-Type: application/json" \
  -d "{\"newid\":${NEWID},\"name\":\"demo-vm-clone\"}")
show "$resp"

step "Both VMs now listed"
show "$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu")"

step "Deleting a running VM is rejected (matches real Proxmox) - expect an HTTP error here"
set +e
curl "${CURL_OPTS[@]}" -X DELETE "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}" -w '\nHTTP %{http_code}\n'
set -e

step "Stop, then delete VM $VMID"
show "$(curl "${CURL_OPTS[@]}" -X POST "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}/status/stop")"
show "$(curl "${CURL_OPTS[@]}" -X DELETE "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${VMID}")"

step "Stop and delete the clone too"
curl "${CURL_OPTS[@]}" -X POST "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${NEWID}/status/stop" >/dev/null
curl "${CURL_OPTS[@]}" -X DELETE "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu/${NEWID}" >/dev/null

step "Final list: back to empty"
show "$(curl "${CURL_OPTS[@]}" "${AUTH_HDR[@]}" "$BASE/nodes/pve/qemu")"

step "Done."

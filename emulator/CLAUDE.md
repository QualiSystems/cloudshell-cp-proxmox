# emulator/ — Proxmox VE API emulator

Context for working in this directory. User-facing setup/usage docs live in `README.md` — read that for
"how to run it." This file is about what's non-obvious, what to check before changing anything, and lessons
already paid for during development so they don't get re-learned the hard way.

## Permission boundary

Work in this repo is scoped to the `emulator/` directory only. `cloudshell/cp/proxmox/` (the actual
driver) is read-only reference material for "what does the real driver actually call" — never a target
for edits from here, even when a bug traces back to driver code. If behavior needs to differ, the fix
belongs in the emulator's handling of that behavior, not in the driver.

## What this is and why

A Flask app that speaks the subset of the real Proxmox VE REST API that `cloudshell-cp-proxmox` needs, so the
driver can be developed/tested without a real Proxmox cluster. Scope is deliberately narrow: VM create/clone/
list/config/status/start/stop/shutdown/delete, snapshot save/restore/remove/list, the guest-agent endpoint
backing Refresh IP, plus the cluster-level lookups the driver needs to make those work. Explicitly not
implemented: real networking (bridges/SDN/firewall — net0's MAC is synthesized, not configurable topology),
real storage, backups, cloud-init, migration, HA, LXC containers, multi-node clusters, ACL enforcement.

**State model**: Everything lives in a plain in-memory dict (`ProxmoxState._data`) for the life of the process —
no disk persistence, no repo pollution. Starts empty on every launch; a restart discards all VMs, including
explicitly created ones. See "Auto-vivification" below for the 100-500 mock range that succeeds without needing
anything explicitly created first.

**Inspecting state while debugging**: `GET /debug/state` (`routes/debug.py`) dumps the live `_data` dict as
pretty-printed JSON — unauthenticated (listed in `access.OPEN_PATHS`) and not versioned under `/api2/json`,
since it isn't part of the emulated Proxmox API. Chosen over dumping state to a file on every mutation because
disk-backed state was already removed once for Windows file-lock issues (see above) — an endpoint stays live
and correct with zero extra write-hooks, at the cost of needing the server to be responsive to inspect it.

## Ground truth is the real driver, not generic Proxmox docs

This repo's `master` branch is an unmodified `cloudshell-package-repo-template` skeleton with no driver code —
easy to be misled by. The actual driver lives on **`feature_base_driver`** (and
`feature_base_driver_with_sdn`), under `cloudshell/cp/proxmox/`. The emulator was built and then corrected
by reading that code directly, not by assuming standard Proxmox behavior — several things it does are
specific to how *this* driver calls the API, not just "what Proxmox does":

- `cloudshell/cp/proxmox/handlers/rest_api_handler.py` (`ProxmoxAutomationAPI`) — the actual HTTP client:
  every endpoint, param, and body shape the driver sends. Start here for "what does the driver send on
  the wire" questions.
- `cloudshell/cp/proxmox/handlers/proxmox_handler.py` (`ProxmoxHandler`) — the orchestration layer: what
  order things get called in, what gets retried, what gets polled. `vmid_to_node`/`get_node_by_vmid`
  (backed by `cluster/resources`) and `start_instance`/`stop_instance`/`get_instance_status` live here.
- `cloudshell/cp/proxmox/flows/power_flow.py` (`ProxmoxPowerFlow`) — Power On/Off resource commands.
  `power_off()` reads the resource-level "Shutdown Method" attribute to decide soft (ACPI shutdown) vs
  hard stop.
- `cloudshell/cp/proxmox/flows/snapshots.py` (`ProxmoxSnapshotFlow`) — Save/Restore/Remove/Get Snapshots
  resource commands, plus orchestration save/restore. All four mutate through `ProxmoxHandler`'s snapshot
  methods, each of which POSTs/DELETEs to `nodes/{node}/qemu/{vmid}/snapshot[...]` and then polls the
  returned UPID via `_task_waiter` (`proxmox_handler.py`) — the same `GET nodes/{node}/tasks/{upid}/status`
  endpoint the power flow already relies on. `create_snapshot` first reads `status/current` to decide
  `vmstate` (1 only if the VM is running *and* the caller asked for memory dump).
- `cloudshell/cp/proxmox/flows/refresh_ip.py` (`refresh_ip`) — reads VM status (must be running, else
  `VmIsNotPowered`), then `VMNetworkActions.get_vm_ip` (`actions/vm_network.py`) polls
  `ProxmoxHandler.get_instance_ifaces_info`, which combines `GET .../config` (parses `netN` strings for a
  MAC) with `GET .../agent/network-get-interfaces` (QEMU guest-agent lookup, keyed by MAC) to find an IP
  matching a regex. No task/UPID polling here — it's plain synchronous GETs with a client-side sleep loop.
- `cloudshell/cp/proxmox/flows/deploy_flow/base_flow.py` (`AbstractProxmoxDeployFlow._deploy`) — the
  deploy orchestration: calls `_create_vm` (clone) then, if `deploy_app.auto_power_on`, an immediate
  start. `_get_target_node`/`_get_target_storage` read the deploy app's "Target Node"/"Target Storage"
  attributes.
- `cloudshell/cp/proxmox/flows/deploy_flow/commands/clone_vm.py` (`CloneVMCommand`) — resolves the
  *source* node via `get_node_by_vmid` before cloning, then calls `ProxmoxHandler.clone_instance` with
  both that source node and the deploy app's requested `target_node`.
- `cloudshell/cp/proxmox/resource_config.py` — `ShutdownMethod` enum + `ProxmoxAttributeNames` (the
  CloudShell attribute name strings: "User", "Password", "Shared Storage", "Shutdown Method", "Default
  Bridge", "Reserved Networks"). `ProxmoxResourceConfig` is the resource-level (not per-app) config.
- `cloudshell/cp/proxmox/models/deploy_app.py` / `models/deployed_app.py` — per-deploy-app attributes,
  including `target_node` ("Target Node") and `target_storage` ("Target Storage"). These are set per
  app instance, distinct from the resource-level `ProxmoxResourceConfig` attributes above.

**Before adding any new endpoint or field, read the corresponding method in `rest_api_handler.py` first.**
Guessing from Proxmox's public docs alone is what caused the bugs described below.

## Known driver bugs (reference only — out of scope to fix from here)

- **`ProxmoxPowerFlow.power_off()` raises `NameError: name 'ShutdownMethod' is not defined`, always.**
  `power_flow.py` imports `ShutdownMethod` only inside `if TYPE_CHECKING:` (alongside `ProxmoxResourceConfig`
  and `ProxmoxHandler`, which *are* correctly TYPE_CHECKING-only since the file has
  `from __future__ import annotations` and only uses them as annotations). But `power_off()` evaluates
  `ShutdownMethod.SOFT` as a live expression at runtime — the name was never actually imported, so this
  fails unconditionally, on every Power Off call, regardless of Proxmox/cluster/node state. **This crash
  happens before any HTTP request is built** — `self._si.stop_instance(...)` (the line that would call
  the emulator) is never reached, so nothing shows up in the emulator's request log for a failed Power
  Off. No emulator-side change can affect this; the fix is a real top-level import of `ShutdownMethod` in
  `power_flow.py`, which is outside the permission boundary for this directory.

## Non-obvious behaviors (each one cost real debugging time)

- **The driver always creates VMs by cloning — never a bare create.** There is no code path in
  `rest_api_handler.py` that calls `POST /nodes/{node}/qemu` directly; `CloneVMCommand` /
  `ProxmoxHandler.clone_instance` is the only real "create" path. The bare create endpoint
  (`ProxmoxState.create_vm`) still exists here — it's valid real-Proxmox behavior and useful for seeding a
  clone-source VM in tests/scripts — but don't expect the driver to call it.
- **`GET /cluster/resources?type=vm` is the *only* way the driver resolves vmid → node**
  (`ProxmoxHandler.vmid_to_node` / `get_node_by_vmid`). Every operation that takes just a vmid (start, stop,
  delete, status, ...) goes through this first; if a vmid isn't in that list, the driver raises
  `VmDoesNotExistException` locally without ever hitting the per-VM endpoint. This is why `cluster/resources`
  exists here even though the initial ask was "just" create/delete.
- **`status/current` must never include a `lock` key unless the VM is genuinely locked.** The driver wraps
  `get_instance_status` in `Decorators.is_instance_locked`, which polls up to 60 times (5s apart — up to
  5 minutes) until the response has no `lock` key, treating *any* present value (including `""`) as
  still-locked. An early version of this emulator always sent `"lock": ""`, which would have hung every
  single status check. Fixed in `ProxmoxState._vm_status` — only add the key when a VM actually has a lock
  reason set (nothing in current scope ever sets one). **Do not reintroduce an always-present `lock` key.**
- **Requests are JSON bodies, not form-encoded**, and `CSRFPreventionToken` is set once, as a session-wide
  header, in `ProxmoxAutomationAPI.connect()` — present on every request, not just mutating ones. The
  emulator accepts both JSON and form bodies and only *requires* the CSRF header on POST/PUT/DELETE, so both
  styles work, but treat JSON-body-only as the real contract when in doubt.
- **`GET /cluster/nextid`** backs `ProxmoxHandler.generate_new_vm_id()`. It returns the lowest unused vmid
  ≥ 100 (matching real Proxmox — not a monotonic counter), so deleting a VM makes its id reusable.
- **`DELETE .../qemu/{vmid}`'s response body is ignored by the driver** — it only cares whether the call
  raised. It also always stops the VM first (`ProxmoxHandler.delete_instance`), so the emulator's "reject
  delete of a running VM" behavior mostly matters when testing the emulator directly (curl/example scripts),
  not for the driver's actual call sequence.
- **Auto-vivification: IDs 100–500 auto-succeed, 501+ auto-fail, and nothing is pre-populated**
  (`VMID_AUTOVIVIFY_MAX` in `state.py`). The dict starts empty — there is no eager materialization of the
  100-500 range at startup. Instead:
  - **Reads** (`get_config`, `get_status`, `cluster_resources`) for an id ≤ 500 that was never created
    synthesize a default VM (`ProxmoxState._default_vm`: 1 core, 512MB RAM, stopped, name=`vm{id}`) on the fly
    and return it *without* writing it to the dict.
  - **Mutations** (`start_vm`, `stop_vm`, `shutdown_vm`, via `_get_vm_for_mutation`) do the same synthesis but
    then store the result, so the change (e.g. "now running") is visible to later reads in the same session.
  - **Ids above 500** behave like real Proxmox: they don't exist unless explicitly created/cloned, and
    `create_vm`/`clone_vm` have no ceiling — they can target any id, including >500, and always succeed. This
    is what lets the driver's real create flow (nextid → clone into that id, almost always landing above 500
    once the mock range is otherwise occupied by real usage) keep working.
  - `cluster_resources()` (the *only* endpoint the driver uses to resolve vmid → node) merges stored VMs with
    synthesized entries for every unstored id in 100-500, so the whole mock range always resolves — this was
    the fix for CloudShell's `VmDoesNotExistException: no VM with vmid 444` when nothing had explicitly
    created VM 444.
  - `get_next_free_vmid` (`cluster/nextid`) only looks at the dict's actual keys, so on a fresh instance it
    returns 100, same as real Proxmox — the mock range is not "occupied" until something is actually stored
    there.

## Multi-node emulation (nodes are a registry, not a single fixed string)

- **`ProxmoxState._data["nodes"]` is a dict of known node names**, not a single hardcoded node. Any
  node name any caller addresses gets auto-registered on first mention (`ProxmoxState._touch_node`) --
  there is no cluster join/membership step, and no rejection of unknown node names. This mirrors the
  100-500 vmid auto-vivification philosophy: prioritize zero-setup success over strict topology fidelity.
- **Clone honors the real Proxmox `target` param** (`ProxmoxAutomationAPI.clone_instance` sends it as
  `data["target"]`, sourced from the deploy app's "Target Node" CloudShell attribute). If `target` is
  present in the clone body, the new VM is stored under that node instead of the source node, so
  `cluster/resources` (and therefore the driver's `get_node_by_vmid`) correctly reports it there and a
  later start/stop addressed to that node succeeds.
- **Trade-off, stated explicitly so it isn't rediscovered as a "regression":** because any node name is
  accepted, a genuinely misspelled node against a 100-500 autoviv-range vmid now silently synthesizes a
  default VM and succeeds, where it used to 500 with "node not found." This was a deliberate choice
  (ease of mocking over fail-fast validation) -- ids above 500 that were never explicitly created still
  correctly 500 regardless of node, since that check doesn't depend on node membership.
- **`list_vms` (`GET /nodes/{node}/qemu`) is node-scoped** -- only returns VMs actually stored under that
  node. `GET /nodes` (`node_summary`) returns one entry per registered node, not a single fixed entry.
- `_touch_node` acquires `self._lock` internally (it's an `RLock`, so it's safe to call from inside an
  already-locked mutation block too) -- don't bypass it with a raw dict write when registering a node.

## Snapshots & Refresh IP (added July 2026)

- **Snapshots live per-VM as `vm["snapshots"]`, a name -> `{"name", "vmstate", "created_at"}` dict** --
  same "plain dict on the VM" pattern as everything else. `list_snapshots`/`create_snapshot`/
  `restore_snapshot`/`delete_snapshot` in `state.py` back `GET/POST/POST-rollback/DELETE
  nodes/{node}/qemu/{vmid}/snapshot[...]`; all three mutating ops go through the same `_create_task` UPID
  path as start/stop/shutdown, with task types `qmsnapshot`/`qmrollback`/`qmdelsnapshot`.
- **A synthetic `"current"` entry is always appended to `list_snapshots`'s output**, matching real
  Proxmox's live-state pointer, but `restore_snapshot`/`delete_snapshot` explicitly reject `name ==
  "current"` with a 400 -- it was a deliberate choice to mirror real Proxmox's *listing* behavior while
  still failing fast if CloudShell ever tried to restore/remove it as if it were a real snapshot.
- **Restoring a snapshot actually changes the VM's power status** to the state the snapshot captured:
  `vmstate: 1` ("with memory," only possible if the VM was running when saved) rolls back running;
  `vmstate: 0` rolls back stopped. This was a deliberate fidelity choice (over "snapshot restore is a
  no-op state-wise") so that `ProxmoxSnapshotFlow.restore_from_snapshot`'s follow-up
  `SetResourceLiveStatus("Offline")` call and any subsequent status poll see something meaningful.
- **`get_config` now always synthesizes a `net0` entry** -- `"virtio={mac},bridge=vmbr0"` with a MAC
  deterministically derived from the vmid (`ProxmoxState._default_mac`, using the real QEMU/KVM `52:54:00`
  OUI prefix) -- unless a caller's `config_extra` already has one, in which case that value wins
  (`config_extra` is applied *after* the synthesized default, matching how explicit create/clone params
  already override synthesized fields elsewhere in this file). This exists purely so Refresh IP has a MAC
  to correlate against without requiring any setup step, consistent with the emulator's zero-setup
  philosophy (see "Auto-vivification" above).
- **`GET .../agent/network-get-interfaces` (the QEMU guest-agent endpoint backing IP discovery) 500s
  whenever the VM isn't running**, mirroring real Proxmox's behavior when the guest agent is unreachable.
  The driver already treats that 500 as "no data yet" (`suppress(InstanceIsNotRunningException)` in
  `ProxmoxHandler.get_instance_ifaces_info`) rather than a hard failure, so this is safe to model exactly
  rather than always returning a fake interface. When running, it returns one interface (`"eth0"`) whose
  `"hardware-address"` matches the MAC from `get_config`'s `net0` and whose `ip-addresses` entry is a
  vmid-derived IPv4 (`ProxmoxState._default_ip`, `10.0.{high byte}.{low byte}`) -- config and agent data
  are always self-consistent without needing to explicitly set up networking first.
- **Response field names for the guest-agent payload matter exactly**: `"hardware-address"`, `"name"`,
  `"ip-addresses"` (each `{"ip-address", "ip-address-type", "prefix"}`) -- these are the literal Proxmox
  wire keys the driver's `constants.py` (`MAC`, `IFACE_NAME`, `IP_LIST`, `IP_ADDRESS`, `ADDRESS_TYPE`) maps
  onto, not arbitrary choices; get them from `constants.py` directly rather than guessing, same "read the
  driver first" rule as everywhere else in this file.

## Guest OS info (`agent/get-osinfo`, added July 2026)

- **This route didn't exist at all until traced from a live log showing a 404 on
  `GET .../agent/get-osinfo`, with "Guest OS" not showing up in CloudShell's VM details.**
  `ProxmoxHandler.get_instance_os` (backs the "Guest OS" details field) calls
  `ProxmoxAutomationAPI.get_instance_osinfo`, whose `http_error_map` only maps `400`/`401`/`500` -- a 404
  falls through to the generic `BaseProxmoxException`, which `get_instance_os` doesn't catch (it only
  catches `InstanceIsNotRunningException` and `VmDoesNotExistException`). An unimplemented route 404s
  and that exception propagates uncaught, unlike the already-implemented
  `agent/network-get-interfaces`, which the driver already tolerates failing via a 500.
- **Fix was to add the route and mirror `get_agent_network_ifaces`'s exact shape**: 500
  (`guest-get-osinfo ... got timeout`) while the VM isn't running -- lands on the 500 branch the driver
  already maps to `InstanceIsNotRunningException` and suppresses -- and a fixed, always-consistent OS
  payload once running (`ProxmoxState.get_agent_osinfo` in `state.py`). The payload is static rather than
  vmid-derived (unlike the MAC/IP pairing) since nothing downstream correlates it against another
  endpoint's value -- there was nothing to keep "self-consistent" with.
- **Driver parses the payload as `data["result"]["name"]` / `["version"]`** (a dict, not a list like
  `network-get-interfaces`'s `result`) -- don't reuse the list-of-interfaces shape here.

## Development workflow

When working on new ideas or features:

1. **Clarify logic first** — Before writing code or running tests, align on the execution and implementation
   approach: what should happen, why, and how the state/behavior should work. Sketch the design (in prose or
   pseudocode) and discuss edge cases.
2. **Ask permission before testing** — Once logic is clear, explicitly ask the user (via `AskUserQuestion`)
   whether to start testing the implementation, rather than assuming the approach is correct and running
   tests against untested code. This prevents discovering halfway through that the design was misunderstood.
3. **Update CLAUDE.md as you learn** — New behaviors, constraints, or design decisions discovered during
   implementation should be captured here so future changes don't re-learn the same lessons. Use `AskUserQuestion`
   to check whether new learnings should go into CLAUDE.md and with what detail level before writing.

This discipline prevents the "wrong idea tested thoroughly" antipattern: clear design → explicit permission
to test → minimal rework.

## Windows-specific things learned the hard way

- **A "connection reset" on port 8006 during dev/testing was an artifact of a sandboxed shell tool, not the
  emulator, not real Proxmox behavior, and not something a normal terminal session hits.** Confirmed by a
  full matrix: server launched via a sandboxed agent shell + any client (curl, PowerShell, Python `requests`)
  all got reset on port 8006 specifically; the same server launched as a plain process worked instantly for
  all three. If this resurfaces, it's environment/sandbox, not a code regression — don't "fix" the emulator
  for it.
- **Windows PowerShell 5.1's `Invoke-RestMethod` over HTTPS is genuinely, independently flaky** against
  Werkzeug's ad-hoc self-signed cert (confirmed outside any sandbox) — random "underlying connection was
  closed" even when the exact same request over plain HTTP is 100% reliable. curl and Python `requests`
  (what the real driver uses) are unaffected. This is why `examples.ps1` defaults to `-Scheme http`.
- **git-bash's `kill $!` does not reliably terminate Windows-native `python.exe` processes** spawned via `&`
  backgrounding — the reported PID can outlive the "killed" job, leaving an orphaned server still holding a
  port. Verify cleanup with `Get-Process` / `Get-NetTCPConnection` (PowerShell) rather than trusting `kill`'s
  exit status; use `taskkill //F //PID <pid>` or PowerShell's `Stop-Process -Id <pid> -Force` for cleanup.

## Testing & example scripts

- `tests/test_lifecycle.py` — pytest, run from `emulator/` (`pip install -r requirements.txt -r
  test_requirements.txt && pytest`). Covers full lifecycle (create/clone/start/stop/delete), the lock-key
  regression, cluster/resources + nextid semantics, the auto-vivify range (100-500 succeed without being
  created, mutations on them persist, 501+ fail unless explicitly created), that state does not survive
  across separate `ProxmoxState`/app instances, the full snapshot lifecycle (save/list/restore/remove,
  duplicate-name rejection, `"current"` being listed but not restorable/deletable, restore actually
  flipping power status per `vmstate`), and Refresh IP's guest-agent endpoint (500 while stopped, matching
  MAC/IP once running). `list_vms` (`GET /nodes/pve/qemu`) starts empty and only shows what's actually
  stored — it does *not* show the synthesized 100-500 range; only `cluster_resources` does.
- `examples.sh` / `examples.ps1` / `examples.py` — three walkthroughs of the same request sequence (login →
  create → poll task → cluster/resources lookup → start → get/save/refresh-ip/restore/remove snapshot →
  clone → rejected delete-while-running → stop → delete), one per client (curl, PowerShell, Python
  `requests`), kept step-for-step identical so behavior can be diffed across platforms. Update all three
  together when adding a new step.

## Recent discoveries (from active development)

**In-memory-only state, nothing pre-populated (July 2026):** The emulator was refactored off disk persistence
(a JSON file, `os.replace()`, Windows file-lock retries — all removed) to a plain in-memory dict scoped to the
process. An intermediate version of this eagerly materialized all 401 VMs (100-500) into memory at startup;
that was wrong and got corrected — it made `cluster/nextid` return 501 on a fresh instance instead of 100, and
conflated "the mock range should succeed" with "the mock range should be pre-existing storage," which isn't
the same thing. The corrected design (documented under "Auto-vivification" above) synthesizes 100-500 on read
without storing, and only persists a mock-range VM once something actually mutates it. Nothing is pre-occupied,
so `nextid` behaves exactly like a fresh real cluster.

**Process learning:** Clarifying design before implementation saves rework — this exact mistake (eager
materialization) was implemented, tested as passing, and then had to be unwound once the nextid/create
contradiction surfaced. Sketch the logic, get explicit agreement on it, *then* write code and tests. This is
now part of the development workflow (see "Development workflow" section).

**Deploy-with-auto-power-on can target a node the clone never actually used (July 2026):** Traced from a
real log: clone succeeded (`POST /nodes/pve/qemu/444/clone` -> vmid 501), but the immediately-following
auto-power-on start call (`POST /nodes/aaa/qemu/501/status/start`) 500'd five times in a row. Root cause,
read directly out of the driver: `AbstractProxmoxDeployFlow._deploy` (`base_flow.py`) starts the newly
cloned VM using `node=self._get_target_node(deploy_app)` -- i.e. the deploy app's raw "Target Node"
attribute value -- rather than the node the VM actually resolves to via `get_node_by_vmid`. That same
attribute is also sent to Proxmox as the clone's `target` param (see rest_api_handler.clone_instance),
but the emulator used to ignore `target` entirely and always kept the clone on the source node, so any
mismatch between "requested target" and "where the VM actually landed" surfaced late, confusingly, on the
unrelated-looking start call. Since driver changes are out of scope here (see "Permission boundary"),
the fix lives entirely in the emulator: honor `target` for real (clone lands on the requested node) and
accept any node name (see "Multi-node emulation" above) -- this makes the emulator match what the driver
actually asks of it, instead of masking a Target-Node misconfiguration until a much later, harder-to-read
failure.

## Current status

Work in progress on the `emulator` branch — check `git status` for uncommitted changes and `git log` for commit history.

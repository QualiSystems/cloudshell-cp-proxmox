# Proxmox VE API Emulator

A small, self-contained emulator of the [Proxmox VE REST API](https://pve.proxmox.com/pve-docs/api-viewer/) so
`cloudshell-cp-proxmox` can be developed and exercised without a real Proxmox cluster available.

It speaks the same URL scheme, JSON envelope, authentication headers, and async-task (UPID) polling pattern as
real Proxmox, and persists VM state to a local JSON file, so the driver can't tell the difference for the
operations it covers. It has been checked directly against this repo's actual driver code
(`cloudshell/cp/proxmox/handlers/rest_api_handler.py` and `proxmox_handler.py`, on the `feature_base_driver`
branch) rather than against generic Proxmox docs alone — see [Matching the real driver](#matching-the-real-driver)
for what that caught.

## Scope

Implemented now — enough to create, list, inspect, power, and delete QEMU VMs:

| Real Proxmox operation           | Method & path                                              |
|-----------------------------------|--------------------------------------------------------------|
| Get API version                   | `GET /api2/json/version`                                     |
| Log in / get a ticket             | `POST /api2/json/access/ticket`                               |
| List nodes                        | `GET /api2/json/nodes`                                        |
| Node status                       | `GET /api2/json/nodes/{node}/status`                           |
| Cluster resources (vmid -> node)  | `GET /api2/json/cluster/resources`                             |
| Next free VM ID                   | `GET /api2/json/cluster/nextid`                                |
| List VMs                          | `GET /api2/json/nodes/{node}/qemu`                             |
| Create VM                         | `POST /api2/json/nodes/{node}/qemu`                            |
| Clone VM                          | `POST /api2/json/nodes/{node}/qemu/{vmid}/clone`                |
| Get VM config                     | `GET /api2/json/nodes/{node}/qemu/{vmid}/config`                |
| Get VM current status             | `GET /api2/json/nodes/{node}/qemu/{vmid}/status/current`        |
| Start VM                          | `POST /api2/json/nodes/{node}/qemu/{vmid}/status/start`          |
| Stop VM (hard)                    | `POST /api2/json/nodes/{node}/qemu/{vmid}/status/stop`           |
| Shutdown VM (soft/ACPI)           | `POST /api2/json/nodes/{node}/qemu/{vmid}/status/shutdown`       |
| Delete VM                         | `DELETE /api2/json/nodes/{node}/qemu/{vmid}`                    |
| Poll an async task                | `GET /api2/json/nodes/{node}/tasks/{upid}/status`                |

**Deliberately out of scope for now** (per the initial ask — creation/deletion of VMs first): networking
(NICs, bridges, `vmbr*`, SDN, firewall), storage realism (disks are recorded but not simulated), snapshots,
backups, cloud-init, migration, HA, LXC containers, multi-node clusters, and ACL/permission enforcement. The
structure below is meant to make adding any of these straightforward later.

## Install

```bash
cd emulator
pip install -r requirements.txt
# optional, for running tests:
pip install -r test_requirements.txt
```

Requires Python 3.8+.

## Run it

```bash
# from the emulator/ directory
python server.py
# or, equivalently:
python -m proxmox_emulator
```

By default this binds `0.0.0.0:8006` (Proxmox's default API port) and serves HTTPS with an ad-hoc,
self-signed certificate — just like a real Proxmox node does out of the box. State is persisted to
`emulator/data/state.json`.

> **If every request times out / resets on port 8006, see [Troubleshooting](#troubleshooting) below** —
> it's a known sandboxed-shell gotcha, not an emulator bug, and unlikely to affect a normal terminal session.

Useful flags:

```bash
python server.py --host 0.0.0.0 --port 8006 --node pve \
                  --state-file ./data/state.json \
                  --action-delay 0 \
                  --no-tls \
                  --reset
```

| Flag              | Meaning                                                                                     |
|--------------------|-----------------------------------------------------------------------------------------------|
| `--host`           | Interface to bind (default `0.0.0.0`)                                                        |
| `--port`           | Listening port (default `8006`, matching real Proxmox)                                       |
| `--node`           | Name of the single emulated node (default `pve`) — must match what the driver is configured with |
| `--state-file`     | Path to the JSON state file (default `emulator/data/state.json`)                              |
| `--action-delay`   | Seconds a create/clone/start/stop/delete task takes before it reports as finished (default `0`, i.e. instant). Bump this if you want to exercise the driver's async task-polling/retry logic realistically. |
| `--no-tls`         | Serve plain HTTP instead of HTTPS (real Proxmox is HTTPS-only, but this is handy for quick local testing) |
| `--reset`          | Wipe any existing state file before starting                                                  |

The server keeps running and logging requests until you stop it (Ctrl+C).

## Persistence

All cluster state — VMs and their config/power state, plus in-flight task records — lives in the single
JSON file passed via `--state-file`. Every create/clone/start/stop/delete call is written straight through
to disk (atomic replace), so:

* Stopping and restarting the emulator does not lose VMs.
* Creating VM `100`, restarting the emulator, then listing VMs will still show `100`.
* Deleting the state file (or passing `--reset`) gives you a clean cluster.

There is exactly one emulated node (name configurable via `--node`, default `pve`). All VM/task state lives
under that node.

## Pointing the driver at it

1. Start the emulator on a machine reachable from wherever the driver runs, e.g.:
   ```bash
   python server.py --host 0.0.0.0 --port 8006
   ```
2. In the CloudShell Proxmox cloud provider resource, set:
   * **Address / host** → the emulator machine's IP or hostname
   * **Port** → `8006` (or whatever you passed to `--port`)
   * **User** → anything, e.g. `root@pam` (any username/password is accepted — see [Known simplifications](#known-simplifications))
   * **Password** / **API token** → anything non-empty
   * **SSL verification** → disabled (the emulator's certificate is self-signed, exactly like a fresh real Proxmox node)
3. Before you can deploy anything, **create at least one VM to act as a clone source/template** (the real
   driver's deploy flow always clones an existing VM — see below — it never creates one from scratch). Use
   the bare create endpoint or any of the three walkthrough scripts below to seed one, and set its vmid as
   the resource's template ID.
4. Deploy/teardown flows that call clone, status, power on/off, and delete should now work end-to-end
   against the emulator.

### Manual checks with curl / PowerShell / Python

Three ready-to-run walkthrough scripts exercise the full request/response contract step by step (login,
create, poll task, `cluster/resources` lookup, start, clone, delete-while-running rejection, stop, delete)
and print every response so you can eyeball that it looks right:

```bash
# macOS/Linux
./examples.sh [host] [port] [http|https]     # e.g. ./examples.sh 127.0.0.1 18006 http
```

```powershell
# Windows
.\examples.ps1 [-HostName <ip>] [-Port <port>] [-Scheme http|https]
```

```bash
# Any platform -- uses `requests`, the same HTTP library the real driver uses
python examples.py [host] [port] [http|https]
```

All three mirror each other step-for-step, so the same walkthrough can be diffed across platforms/clients.
They default to plain HTTP against `127.0.0.1:8006` — start the server with `--no-tls` to match, or pass
`-Scheme https` / `https` as the 3rd arg to exercise the self-signed-cert path instead.

## Matching the real driver

This emulator was cross-checked against `cloudshell-cp-proxmox`'s actual `ProxmoxAutomationAPI` client
(`cloudshell/cp/proxmox/handlers/rest_api_handler.py`) and `ProxmoxHandler`
(`cloudshell/cp/proxmox/handlers/proxmox_handler.py`), not just the general Proxmox API docs. A few things
that fell out of that, worth knowing if you extend either side:

* **The driver always creates VMs by cloning, never via a bare create.** `ProxmoxHandler.clone_instance` /
  `CloneVMCommand` is the only "create a VM" path actually exercised — there is no code path that calls
  `POST /nodes/{node}/qemu` directly. The bare create endpoint still exists here (handy for seeding a
  clone-source VM, and it's still valid real-Proxmox behavior), but don't expect the driver itself to call it.
* **The driver resolves "which node is this VM on" purely from `GET /cluster/resources?type=vm`**
  (`ProxmoxHandler.vmid_to_node` / `get_node_by_vmid`) — every operation that takes just a `vmid` (start,
  stop, delete, status, ...) goes through this lookup first. If a VM isn't in that list, the driver raises
  `VmDoesNotExistException` locally without ever calling the per-VM endpoint. That's why `cluster/resources`
  is implemented here even though the initial ask was scoped to "just" create/delete.
* **Requests are JSON bodies, not form-encoded**, and the CSRF header is set once (in
  `ProxmoxAutomationAPI.connect()`) as a session-wide header — present on every request, not just
  mutating ones. The emulator accepts both JSON and form-encoded bodies, and only *requires* the CSRF header
  on POST/PUT/DELETE, so both styles work.
* **`status/current` must never include a `lock` key unless the VM is genuinely locked.** The driver's
  `get_instance_status` is wrapped in a decorator (`Decorators.is_instance_locked`) that polls up to 60 times,
  5 seconds apart, until the response has no `lock` key — it treats *any* present value, including `""`, as
  still-locked. An earlier draft of this emulator always included `"lock": ""` in the status response, which
  would have made every single status check block for up to 5 minutes before giving up. Fixed in
  `ProxmoxState._vm_status` — the key is only added when a VM actually has a lock reason set (nothing in the
  current create/delete scope ever sets one).
* **`GET /cluster/nextid`** backs `ProxmoxHandler.generate_new_vm_id()`, used whenever the deploy flow clones
  without an explicit target ID. It returns the lowest unused vmid ≥ 100, matching real Proxmox (not just an
  ever-incrementing counter), so deleting a VM makes its ID reusable again.
* **`DELETE .../qemu/{vmid}`'s response is ignored by the driver** — `ProxmoxHandler.delete_instance` fires
  the request and only cares whether it raised (non-2xx). It also always stops the VM first, so the
  "reject delete of a running VM" behavior here mostly matters for testing the emulator directly (via curl/the
  example scripts), not for the driver's own call sequence.

## Behavior notes (matching real Proxmox)

* Every response is wrapped as `{"data": ...}`; errors come back as `{"data": null, "message": "..."}` or
  `{"data": null, "errors": {"field": "..."}}` with a non-2xx status, the same shapes Proxmox uses.
* Create/clone/start/stop/shutdown/delete return a task ID (a `UPID:...` string), not the finished result —
  poll `GET /api2/json/nodes/{node}/tasks/{upid}/status` until `status == "stopped"`, then check `exitstatus`.
* Creating a VM does **not** start it — same as real Proxmox. Call `status/start` to bring it up.
* Deleting a running VM is rejected (HTTP 500, matching Proxmox's real behavior) — stop it first.
* Duplicate `vmid` on create, and unknown `vmid` on delete/config/status, return Proxmox-style 400/500 errors.
* `vmid` must be in Proxmox's real valid range (100–999999999).

## Known simplifications

* **Auth is not cryptographically enforced.** Any username/password given to `/access/ticket` is accepted,
  and any `PVEAPIToken=...` header is accepted without validating the secret. The emulator does still require
  *some* auth (ticket cookie + CSRF header, or an API token header) on every endpoint except `/version` and
  `/access/ticket`, so 401 handling in the driver can still be exercised.
* **Single node only.** There's no multi-node cluster simulation; the node name is whatever you pass via
  `--node`.
* **No real hypervisor.** "Running" VMs don't consume real CPU/RAM — `status/current` reports plausible mock
  numbers (fixed-ish CPU%, memory as a fraction of configured max, uptime computed from when `start` was
  called).
* **No storage/network simulation.** Disk and NIC parameters passed on create/clone are stored verbatim in
  the VM's config (so round-tripping config values works) but aren't otherwise interpreted. Cloud-init
  (`set_user_data`), interface attach/detach, and snapshots aren't implemented at all yet.

## Troubleshooting

**"Connection was reset" / "underlying connection was closed" on port 8006, from every client.** If you hit
this in a sandboxed or restrictively-networked shell (some CI runners and coding-agent sandboxes apply exactly
this kind of policy — this was in fact first found and root-caused inside one during development, not on a
real deployment), it's the sandbox resetting connections on Proxmox's well-known port 8006 specifically,
independent of which client connects to it. It's not something a normal terminal session hits: running the
same server the normal way (a regular shell, no sandbox) and browsing to it, or curling it, works immediately
— an auth-required endpoint correctly returns `{"data": null, "message": "authentication failure"}` rather
than timing out, confirming the server is reachable and behaving correctly. If you do land in an environment
where this reproduces, running the server on a different port (`--port 18006` or similar) sidesteps it —
nothing else about the emulator or the driver changes.

**Windows PowerShell 5.1's `Invoke-RestMethod` over HTTPS** has a separate, genuine (confirmed outside any
sandbox) quirk: it's intermittently incompatible with Werkzeug's ad-hoc self-signed HTTPS certificate
specifically (random "underlying connection was closed" even on a port that works fine over HTTP). curl and
Python's `requests`/urllib3 (what the real driver uses) are both unaffected over HTTPS. That's why
`examples.ps1` defaults to `-Scheme http`; pass `-Scheme https` if you want to exercise that path anyway.

## Extending it

The code is organized so new endpoints are additive:

```
emulator/
  server.py                    convenience launcher (python server.py)
  examples.sh                  curl walkthrough of the full API (macOS/Linux)
  examples.ps1                 Invoke-RestMethod walkthrough of the full API (Windows)
  examples.py                  requests-based walkthrough of the full API (any platform)
  proxmox_emulator/
    cli.py                     argument parsing, ties everything together
    app.py                     Flask app factory + auth middleware + error handler
    state.py                   ProxmoxState — the persisted VM/task model, all mutations go through here
    upid.py                    UPID (task ID) generation/parsing
    errors.py                  ProxmoxApiError -> Proxmox-shaped error responses
    context.py                 get_state() helper for route handlers
    routes/
      access.py                /version, /access/ticket
      nodes.py                 /nodes, /nodes/{node}/status
      cluster.py               /cluster/resources, /cluster/nextid
      qemu.py                  VM create/clone/list/config/status/start/stop/shutdown/delete
      tasks.py                 /nodes/{node}/tasks/{upid}/status
  tests/
    test_lifecycle.py          integration tests against a live Flask test client
```

To add a new area (e.g. networking, snapshots, LXC containers, cloud-init):

1. Read the corresponding method(s) in `cloudshell/cp/proxmox/handlers/rest_api_handler.py` first — that's
   the actual contract to match, not just the general Proxmox docs (see
   [Matching the real driver](#matching-the-real-driver) for why that matters).
2. Add the new fields/methods to `ProxmoxState` in `state.py` (this is the single source of truth, and is
   what gets persisted).
3. Add a route module under `routes/` (or extend an existing one) that calls into `ProxmoxState` and returns
   the same `{"data": ...}` / task-UPID shapes as the rest of the API.
4. Register the blueprint in `routes/__init__.py` if it's a new file.
5. Add coverage in `tests/`, and add the new steps to all three example scripts.

## Testing

```bash
cd emulator
pip install -r requirements.txt -r test_requirements.txt
pytest
```

The test suite spins up the Flask app in-process (no network involved) and drives full VM lifecycles,
including a restart-and-reload check that proves persistence works.

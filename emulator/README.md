# Proxmox VE API Emulator

A small, self-contained emulator of the [Proxmox VE REST API](https://pve.proxmox.com/pve-docs/api-viewer/) so
`cloudshell-cp-proxmox` can be developed and exercised without a real Proxmox cluster available.

It speaks the same URL scheme, JSON envelope, authentication headers, and async-task (UPID) polling pattern as
real Proxmox, and persists VM state to a local JSON file, so the driver can't tell the difference for the
operations it covers.

## Scope

Implemented now — enough to create, list, inspect, and delete QEMU VMs:

| Real Proxmox operation      | Method & path                                          |
|------------------------------|---------------------------------------------------------|
| Get API version              | `GET /api2/json/version`                                |
| Log in / get a ticket        | `POST /api2/json/access/ticket`                          |
| List nodes                   | `GET /api2/json/nodes`                                   |
| Node status                  | `GET /api2/json/nodes/{node}/status`                      |
| List VMs                     | `GET /api2/json/nodes/{node}/qemu`                        |
| Create VM                    | `POST /api2/json/nodes/{node}/qemu`                       |
| Clone VM                     | `POST /api2/json/nodes/{node}/qemu/{vmid}/clone`           |
| Get VM config                | `GET /api2/json/nodes/{node}/qemu/{vmid}/config`           |
| Get VM current status        | `GET /api2/json/nodes/{node}/qemu/{vmid}/status/current`   |
| Start VM                     | `POST /api2/json/nodes/{node}/qemu/{vmid}/status/start`     |
| Stop VM                      | `POST /api2/json/nodes/{node}/qemu/{vmid}/status/stop`      |
| Delete VM                    | `DELETE /api2/json/nodes/{node}/qemu/{vmid}`               |
| Poll an async task           | `GET /api2/json/nodes/{node}/tasks/{upid}/status`           |

**Deliberately out of scope for now** (per the initial ask — creation/deletion of VMs first): networking
(NICs, bridges, `vmbr*`, SDN, firewall), storage realism (disks are recorded but not simulated), snapshots,
backups, migration, HA, LXC containers, multi-node clusters, and ACL/permission enforcement. The structure
below is meant to make adding any of these straightforward later.

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
3. Deploy/teardown flows that call VM create, status, and delete should now work end-to-end against the emulator.

### Quick manual check with curl

```bash
# get a ticket
curl -sk -X POST https://<emulator-ip>:8006/api2/json/access/ticket \
     -d username=root@pam -d password=anything

# create VM 100 (swap in the ticket/CSRF token from the response above)
curl -sk -X POST https://<emulator-ip>:8006/api2/json/nodes/pve/qemu \
     -b "PVEAuthCookie=<ticket>" -H "CSRFPreventionToken: <csrf>" \
     -d vmid=100 -d name=my-vm -d cores=2 -d memory=2048

# list VMs - VM 100 shows up, status "stopped"
curl -sk https://<emulator-ip>:8006/api2/json/nodes/pve/qemu -b "PVEAuthCookie=<ticket>"

# start it
curl -sk -X POST https://<emulator-ip>:8006/api2/json/nodes/pve/qemu/100/status/start \
     -b "PVEAuthCookie=<ticket>" -H "CSRFPreventionToken: <csrf>"

# query it - now "running" with mock cpu/mem/uptime data
curl -sk https://<emulator-ip>:8006/api2/json/nodes/pve/qemu/100/status/current -b "PVEAuthCookie=<ticket>"
```

Or skip ticket auth entirely with an API-token-style header, which the emulator also accepts without checking
the secret:

```bash
curl -sk https://<emulator-ip>:8006/api2/json/nodes/pve/qemu \
     -H "Authorization: PVEAPIToken=root@pam!emulator=anything"
```

## Behavior notes (matching real Proxmox)

* Every response is wrapped as `{"data": ...}`; errors come back as `{"data": null, "message": "..."}` or
  `{"data": null, "errors": {"field": "..."}}` with a non-2xx status, the same shapes Proxmox uses.
* Create/clone/start/stop/delete return a task ID (a `UPID:...` string), not the finished result — poll
  `GET /api2/json/nodes/{node}/tasks/{upid}/status` until `status == "stopped"`, then check `exitstatus`.
  This mirrors Proxmox's real async task model, which the driver has to handle regardless of which backend
  it's talking to.
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
  the VM's config (so round-tripping config values works) but aren't otherwise interpreted.

## Extending it

The code is organized so new endpoints are additive:

```
emulator/
  server.py                    convenience launcher (python server.py)
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
      qemu.py                  VM create/clone/list/config/status/start/stop/delete
      tasks.py                 /nodes/{node}/tasks/{upid}/status
  tests/
    test_lifecycle.py          integration tests against a live Flask test client
```

To add a new area (e.g. networking, snapshots, LXC containers):

1. Add the new fields/methods to `ProxmoxState` in `state.py` (this is the single source of truth, and is
   what gets persisted).
2. Add a route module under `routes/` (or extend an existing one) that calls into `ProxmoxState` and returns
   the same `{"data": ...}` / task-UPID shapes as the rest of the API.
3. Register the blueprint in `routes/__init__.py` if it's a new file.
4. Add coverage in `tests/`.

## Testing

```bash
cd emulator
pip install -r requirements.txt -r test_requirements.txt
pytest
```

The test suite spins up the Flask app in-process (no network involved) and drives full VM lifecycles,
including a restart-and-reload check that proves persistence works.

import pytest

from proxmox_emulator.app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(str(tmp_path / "state.json"), node_name="pve", action_delay=0.0)
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def _login(client):
    # The real driver (ProxmoxAutomationAPI._get_ticket_info) POSTs a JSON body,
    # not form data -- match that exactly rather than the more lenient form path.
    resp = client.post("/api2/json/access/ticket", json={"username": "root@pam", "password": "anything"})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["ticket"].startswith("PVE:")
    return {"CSRFPreventionToken": data["CSRFPreventionToken"]}


def test_authentication_required(client):
    resp = client.get("/api2/json/nodes/pve/qemu")
    assert resp.status_code == 401


def test_version_and_ticket_are_open(client):
    assert client.get("/api2/json/version").status_code == 200
    assert client.post("/api2/json/access/ticket", json={"username": "root@pam"}).status_code == 200


def test_debug_state_dump_is_open_and_reflects_live_state(client):
    resp = client.get("/debug/state")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert resp.get_json()["vms"] == {}

    headers = _login(client)
    client.post("/api2/json/nodes/pve/qemu", json={"vmid": "100", "name": "debug-vm"}, headers=headers)

    dumped = client.get("/debug/state").get_json()
    assert dumped["vms"]["100"]["name"] == "debug-vm"


def test_full_vm_lifecycle(client):
    headers = _login(client)

    # Starts empty -- nothing is pre-materialized.
    assert client.get("/api2/json/nodes/pve/qemu").get_json()["data"] == []

    resp = client.post(
        "/api2/json/nodes/pve/qemu",
        json={"vmid": "100", "name": "test-vm", "cores": "2", "memory": "2048"},
        headers=headers,
    )
    assert resp.status_code == 200
    upid = resp.get_json()["data"]
    assert upid.startswith("UPID:pve:")
    assert ":qmcreate:100:" in upid

    task = client.get("/api2/json/nodes/pve/tasks/{}/status".format(upid)).get_json()["data"]
    assert task["status"] == "stopped"
    assert task["exitstatus"] == "OK"

    vms = client.get("/api2/json/nodes/pve/qemu").get_json()["data"]
    assert vms == [{**vms[0], "vmid": 100}]
    assert vms[0]["status"] == "stopped"  # created VMs are not auto-started, matching real Proxmox

    config = client.get("/api2/json/nodes/pve/qemu/100/config").get_json()["data"]
    assert config["name"] == "test-vm"
    assert config["cores"] == 2
    assert config["memory"] == 2048

    # regression test for a bug where an always-present "lock": "" field made
    # the driver's is_instance_locked poller retry every status check for 5 min
    status = client.get("/api2/json/nodes/pve/qemu/100/status/current").get_json()["data"]
    assert "lock" not in status

    assert client.post("/api2/json/nodes/pve/qemu/100/status/start", headers=headers).status_code == 200

    status = client.get("/api2/json/nodes/pve/qemu/100/status/current").get_json()["data"]
    assert status["status"] == "running"
    assert status["mem"] > 0
    assert status["uptime"] >= 0
    assert "lock" not in status

    # real Proxmox refuses to destroy a running VM
    resp = client.delete("/api2/json/nodes/pve/qemu/100", headers=headers)
    assert resp.status_code == 500

    assert client.post("/api2/json/nodes/pve/qemu/100/status/stop", headers=headers).status_code == 200
    assert client.delete("/api2/json/nodes/pve/qemu/100", headers=headers).status_code == 200

    assert client.get("/api2/json/nodes/pve/qemu").get_json()["data"] == []


def test_shutdown_is_a_distinct_task_type_but_same_effect_as_stop(client):
    headers = _login(client)
    client.post("/api2/json/nodes/pve/qemu", json={"vmid": "100"}, headers=headers)
    client.post("/api2/json/nodes/pve/qemu/100/status/start", headers=headers)

    resp = client.post("/api2/json/nodes/pve/qemu/100/status/shutdown", headers=headers)
    assert resp.status_code == 200
    assert ":qmshutdown:100:" in resp.get_json()["data"]

    status = client.get("/api2/json/nodes/pve/qemu/100/status/current").get_json()["data"]
    assert status["status"] == "stopped"


def test_duplicate_vmid_rejected(client):
    headers = _login(client)
    client.post("/api2/json/nodes/pve/qemu", json={"vmid": "100"}, headers=headers)
    resp = client.post("/api2/json/nodes/pve/qemu", json={"vmid": "100"}, headers=headers)
    assert resp.status_code == 400
    assert "vmid" in resp.get_json()["errors"]


def test_delete_unknown_vm_above_mock_range_errors(client):
    headers = _login(client)
    resp = client.delete("/api2/json/nodes/pve/qemu/999", headers=headers)
    assert resp.status_code == 500


def test_clone_vm(client):
    headers = _login(client)
    client.post(
        "/api2/json/nodes/pve/qemu", json={"vmid": "100", "name": "template-vm", "cores": "4"}, headers=headers
    )

    resp = client.post(
        "/api2/json/nodes/pve/qemu/100/clone",
        json={"newid": "200", "name": "clone-of-template", "node": "pve", "vmid": "100"},
        headers=headers,
    )
    assert resp.status_code == 200
    upid = resp.get_json()["data"]
    assert ":qmclone:200:" in upid

    config = client.get("/api2/json/nodes/pve/qemu/200/config").get_json()["data"]
    assert config["name"] == "clone-of-template"
    assert config["cores"] == 4  # inherited from source


def test_cluster_resources_used_for_vmid_to_node_lookup(client):
    """The driver's get_node_by_vmid() resolves purely from GET /cluster/resources?type=vm."""
    headers = _login(client)
    client.post("/api2/json/nodes/pve/qemu", json={"vmid": "600", "name": "vm-a"}, headers=headers)
    client.post("/api2/json/nodes/pve/qemu", json={"vmid": "601", "name": "vm-b"}, headers=headers)

    resp = client.get("/api2/json/cluster/resources?type=vm", headers=headers)
    assert resp.status_code == 200
    resources = resp.get_json()["data"]
    vmid_to_node = {r["vmid"]: r["node"] for r in resources}

    # Explicitly created VMs (above the mock range) resolve normally.
    assert vmid_to_node[600] == "pve"
    assert vmid_to_node[601] == "pve"

    # The 100-500 mock range resolves too, even though nothing was created there.
    assert vmid_to_node[100] == "pve"
    assert vmid_to_node[444] == "pve"
    assert vmid_to_node[500] == "pve"

    # Ids above the mock range that were never created do not resolve.
    assert 999 not in vmid_to_node

    # unknown resource types (containers, storage, ...) are out of scope for now
    assert client.get("/api2/json/cluster/resources?type=lxc", headers=headers).get_json()["data"] == []


def test_mock_range_succeeds_without_explicit_create(client):
    """Ids 100-500 work on any operation without a prior create/clone call."""
    headers = _login(client)

    # A never-created vmid in the mock range resolves.
    config = client.get("/api2/json/nodes/pve/qemu/444/config", headers=headers).get_json()["data"]
    assert config["vmid"] == 444

    status = client.get("/api2/json/nodes/pve/qemu/444/status/current", headers=headers).get_json()["data"]
    assert status["status"] == "stopped"

    # Starting it persists the running state for the rest of the session.
    assert client.post("/api2/json/nodes/pve/qemu/444/status/start", headers=headers).status_code == 200
    status = client.get("/api2/json/nodes/pve/qemu/444/status/current", headers=headers).get_json()["data"]
    assert status["status"] == "running"

    assert client.post("/api2/json/nodes/pve/qemu/444/status/stop", headers=headers).status_code == 200
    assert client.delete("/api2/json/nodes/pve/qemu/444", headers=headers).status_code == 200


def test_ids_above_mock_range_fail_unless_explicitly_created(client):
    headers = _login(client)

    # 501 was never created -- every operation on it fails.
    assert client.get("/api2/json/nodes/pve/qemu/501/config", headers=headers).status_code == 500
    assert client.get("/api2/json/nodes/pve/qemu/501/status/current", headers=headers).status_code == 500
    assert client.post("/api2/json/nodes/pve/qemu/501/status/start", headers=headers).status_code == 500
    assert client.delete("/api2/json/nodes/pve/qemu/501", headers=headers).status_code == 500

    # But create/clone can still explicitly target it -- matches real Proxmox,
    # and is how the driver's clone-based create flow (get nextid -> clone) works.
    resp = client.post("/api2/json/nodes/pve/qemu", json={"vmid": "501", "name": "explicit"}, headers=headers)
    assert resp.status_code == 200
    config = client.get("/api2/json/nodes/pve/qemu/501/config", headers=headers).get_json()["data"]
    assert config["name"] == "explicit"


def test_cluster_nextid_returns_lowest_free_id(client):
    headers = _login(client)
    # Nothing is pre-occupied -- matches real Proxmox's fresh-cluster behavior.
    assert client.get("/api2/json/cluster/nextid", headers=headers).get_json()["data"] == "100"

    client.post("/api2/json/nodes/pve/qemu", json={"vmid": "100"}, headers=headers)
    client.post("/api2/json/nodes/pve/qemu", json={"vmid": "101"}, headers=headers)
    assert client.get("/api2/json/cluster/nextid", headers=headers).get_json()["data"] == "102"

    client.delete("/api2/json/nodes/pve/qemu/100", headers=headers)
    assert client.get("/api2/json/cluster/nextid", headers=headers).get_json()["data"] == "100"


def test_clone_with_target_lands_on_that_node(client):
    """Regression test: driver clones from the source node but can ask, via the

    `target` clone param, for the new VM to live on a different node (deploy_app's
    "Target Node" attribute -- see rest_api_handler.clone_instance). The new VM must
    actually be recorded under `target`, not the source node, so that a later
    start/stop addressed to `target` succeeds and cluster/resources reports it there.
    """
    headers = _login(client)
    client.post(
        "/api2/json/nodes/pve/qemu", json={"vmid": "100", "name": "template-vm"}, headers=headers
    )

    resp = client.post(
        "/api2/json/nodes/pve/qemu/100/clone",
        json={"newid": "501", "name": "aaa", "node": "pve", "vmid": "100", "target": "aaa"},
        headers=headers,
    )
    assert resp.status_code == 200

    resources = client.get("/api2/json/cluster/resources?type=vm", headers=headers).get_json()["data"]
    vmid_to_node = {r["vmid"]: r["node"] for r in resources}
    assert vmid_to_node[501] == "aaa"

    # Starting it must be addressed to the node it actually landed on.
    assert client.post("/api2/json/nodes/aaa/qemu/501/status/start", headers=headers).status_code == 200
    status = client.get("/api2/json/nodes/aaa/qemu/501/status/current", headers=headers).get_json()["data"]
    assert status["status"] == "running"

    # The new node shows up in the node list once addressed.
    nodes = {n["node"] for n in client.get("/api2/json/nodes", headers=headers).get_json()["data"]}
    assert nodes == {"pve", "aaa"}

    # list_vms is node-scoped: the clone shows up under its target node, not the source.
    vms_on_pve = client.get("/api2/json/nodes/pve/qemu", headers=headers).get_json()["data"]
    assert all(vm["vmid"] != 501 for vm in vms_on_pve)
    vms_on_aaa = client.get("/api2/json/nodes/aaa/qemu", headers=headers).get_json()["data"]
    assert any(vm["vmid"] == 501 for vm in vms_on_aaa)


def test_snapshot_lifecycle(client):
    """Save/Get/Restore/Remove Snapshot -- mirrors ProxmoxSnapshotFlow's call sequence."""
    headers = _login(client)
    client.post("/api2/json/nodes/pve/qemu", json={"vmid": "100", "name": "snap-vm"}, headers=headers)

    # A fresh VM's snapshot list is just the synthetic "current" pointer.
    snaps = client.get("/api2/json/nodes/pve/qemu/100/snapshot", headers=headers).get_json()["data"]
    assert [s["name"] for s in snaps] == ["current"]

    resp = client.post(
        "/api2/json/nodes/pve/qemu/100/snapshot",
        json={"snapname": "before-change", "vmstate": "0"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert ":qmsnapshot:100:" in resp.get_json()["data"]

    snaps = client.get("/api2/json/nodes/pve/qemu/100/snapshot", headers=headers).get_json()["data"]
    assert {s["name"] for s in snaps} == {"current", "before-change"}

    # Duplicate snapshot names are rejected, matching real Proxmox.
    resp = client.post(
        "/api2/json/nodes/pve/qemu/100/snapshot", json={"snapname": "before-change"}, headers=headers
    )
    assert resp.status_code == 400

    # Start the VM, then take a "with memory" snapshot.
    client.post("/api2/json/nodes/pve/qemu/100/status/start", headers=headers)
    resp = client.post(
        "/api2/json/nodes/pve/qemu/100/snapshot",
        json={"snapname": "running-snap", "vmstate": "1"},
        headers=headers,
    )
    assert resp.status_code == 200

    # Rolling back to the disk-only snapshot restores it stopped.
    resp = client.post("/api2/json/nodes/pve/qemu/100/snapshot/before-change/rollback", headers=headers)
    assert resp.status_code == 200
    assert ":qmrollback:100:" in resp.get_json()["data"]
    status = client.get("/api2/json/nodes/pve/qemu/100/status/current", headers=headers).get_json()["data"]
    assert status["status"] == "stopped"

    # Rolling back to the memory snapshot restores it running.
    resp = client.post("/api2/json/nodes/pve/qemu/100/snapshot/running-snap/rollback", headers=headers)
    assert resp.status_code == 200
    status = client.get("/api2/json/nodes/pve/qemu/100/status/current", headers=headers).get_json()["data"]
    assert status["status"] == "running"

    # "current" can't be rolled back to or deleted -- it's a marker, not a real snapshot.
    assert (
        client.post("/api2/json/nodes/pve/qemu/100/snapshot/current/rollback", headers=headers).status_code == 400
    )
    assert client.delete("/api2/json/nodes/pve/qemu/100/snapshot/current", headers=headers).status_code == 400

    resp = client.delete("/api2/json/nodes/pve/qemu/100/snapshot/before-change", headers=headers)
    assert resp.status_code == 200
    assert ":qmdelsnapshot:100:" in resp.get_json()["data"]

    snaps = client.get("/api2/json/nodes/pve/qemu/100/snapshot", headers=headers).get_json()["data"]
    assert {s["name"] for s in snaps} == {"current", "running-snap"}

    # Deleting/restoring an unknown snapshot name errors.
    assert client.delete("/api2/json/nodes/pve/qemu/100/snapshot/nope", headers=headers).status_code == 400
    assert (
        client.post("/api2/json/nodes/pve/qemu/100/snapshot/nope/rollback", headers=headers).status_code == 400
    )


def test_refresh_ip_via_guest_agent(client):
    """Backs the Refresh IP flow: config net0 -> MAC, agent endpoint -> matching IP."""
    headers = _login(client)
    client.post("/api2/json/nodes/pve/qemu", json={"vmid": "200", "name": "ip-vm"}, headers=headers)

    config = client.get("/api2/json/nodes/pve/qemu/200/config", headers=headers).get_json()["data"]
    assert config["net0"].startswith("virtio=52:54:00:")

    # Guest agent isn't reachable on a stopped VM -- driver treats this as "no data", not fatal.
    resp = client.get("/api2/json/nodes/pve/qemu/200/agent/network-get-interfaces", headers=headers)
    assert resp.status_code == 500

    client.post("/api2/json/nodes/pve/qemu/200/status/start", headers=headers)

    resp = client.get("/api2/json/nodes/pve/qemu/200/agent/network-get-interfaces", headers=headers)
    assert resp.status_code == 200
    iface = resp.get_json()["data"]["result"][0]
    assert iface["hardware-address"] in config["net0"].lower()
    assert iface["ip-addresses"][0]["ip-address-type"] == "ipv4"
    assert iface["ip-addresses"][0]["ip-address"] == "10.0.0.200"


def test_get_osinfo_via_guest_agent(client):
    """Backs get_instance_os (shown as VM "Guest OS" details) -- 500 while stopped,
    matching data once running, mirroring the network-get-interfaces guest-agent shape."""
    headers = _login(client)
    client.post("/api2/json/nodes/pve/qemu", json={"vmid": "201", "name": "os-vm"}, headers=headers)

    resp = client.get("/api2/json/nodes/pve/qemu/201/agent/get-osinfo", headers=headers)
    assert resp.status_code == 500

    client.post("/api2/json/nodes/pve/qemu/201/status/start", headers=headers)

    resp = client.get("/api2/json/nodes/pve/qemu/201/agent/get-osinfo", headers=headers)
    assert resp.status_code == 200
    result = resp.get_json()["data"]["result"]
    assert result["name"] == "Debian GNU/Linux"
    assert result["version"] == "11"


def test_state_is_not_shared_across_app_instances(tmp_path):
    """State is in-memory per-process; a fresh app instance starts empty."""
    state_file = tmp_path / "state.json"

    app1 = create_app(str(state_file), node_name="pve")
    with app1.test_client() as client1:
        headers = _login(client1)
        client1.post(
            "/api2/json/nodes/pve/qemu",
            json={"vmid": "101", "name": "session-vm"},
            headers=headers,
        )
        vms = client1.get("/api2/json/nodes/pve/qemu", headers=headers).get_json()["data"]
        assert any(vm["vmid"] == 101 and vm["name"] == "session-vm" for vm in vms)

    # A second instance (simulating a restart) does not see the first one's VM.
    app2 = create_app(str(state_file), node_name="pve")
    with app2.test_client() as client2:
        headers = _login(client2)
        vms = client2.get("/api2/json/nodes/pve/qemu", headers=headers).get_json()["data"]
        assert vms == []

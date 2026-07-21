import pytest

from proxmox_emulator.app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(str(tmp_path / "state.json"), node_name="pve", action_delay=0.0)
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def _login(client):
    resp = client.post("/api2/json/access/ticket", data={"username": "root@pam", "password": "anything"})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["ticket"].startswith("PVE:")
    return {"CSRFPreventionToken": data["CSRFPreventionToken"]}


def test_authentication_required(client):
    resp = client.get("/api2/json/nodes/pve/qemu")
    assert resp.status_code == 401


def test_version_and_ticket_are_open(client):
    assert client.get("/api2/json/version").status_code == 200
    assert client.post("/api2/json/access/ticket", data={"username": "root@pam"}).status_code == 200


def test_full_vm_lifecycle(client):
    headers = _login(client)

    assert client.get("/api2/json/nodes/pve/qemu").get_json()["data"] == []

    resp = client.post(
        "/api2/json/nodes/pve/qemu",
        data={"vmid": "100", "name": "test-vm", "cores": "2", "memory": "2048"},
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

    assert client.post("/api2/json/nodes/pve/qemu/100/status/start", headers=headers).status_code == 200

    status = client.get("/api2/json/nodes/pve/qemu/100/status/current").get_json()["data"]
    assert status["status"] == "running"
    assert status["mem"] > 0
    assert status["uptime"] >= 0

    # real Proxmox refuses to destroy a running VM
    resp = client.delete("/api2/json/nodes/pve/qemu/100", headers=headers)
    assert resp.status_code == 500

    assert client.post("/api2/json/nodes/pve/qemu/100/status/stop", headers=headers).status_code == 200
    assert client.delete("/api2/json/nodes/pve/qemu/100", headers=headers).status_code == 200

    assert client.get("/api2/json/nodes/pve/qemu").get_json()["data"] == []


def test_duplicate_vmid_rejected(client):
    headers = _login(client)
    client.post("/api2/json/nodes/pve/qemu", data={"vmid": "100"}, headers=headers)
    resp = client.post("/api2/json/nodes/pve/qemu", data={"vmid": "100"}, headers=headers)
    assert resp.status_code == 400
    assert "vmid" in resp.get_json()["errors"]


def test_delete_unknown_vm_errors(client):
    headers = _login(client)
    resp = client.delete("/api2/json/nodes/pve/qemu/999", headers=headers)
    assert resp.status_code == 500


def test_clone_vm(client):
    headers = _login(client)
    client.post("/api2/json/nodes/pve/qemu", data={"vmid": "100", "name": "template-vm", "cores": "4"}, headers=headers)

    resp = client.post(
        "/api2/json/nodes/pve/qemu/100/clone",
        data={"newid": "200", "name": "clone-of-template"},
        headers=headers,
    )
    assert resp.status_code == 200
    upid = resp.get_json()["data"]
    assert ":qmclone:200:" in upid

    config = client.get("/api2/json/nodes/pve/qemu/200/config").get_json()["data"]
    assert config["name"] == "clone-of-template"
    assert config["cores"] == 4  # inherited from source


def test_state_persists_across_restarts(tmp_path):
    state_file = tmp_path / "state.json"

    app1 = create_app(str(state_file), node_name="pve")
    with app1.test_client() as client1:
        headers = _login(client1)
        client1.post(
            "/api2/json/nodes/pve/qemu",
            data={"vmid": "101", "name": "persisted-vm"},
            headers=headers,
        )

    assert state_file.exists()

    app2 = create_app(str(state_file), node_name="pve")
    with app2.test_client() as client2:
        resp = client2.get(
            "/api2/json/nodes/pve/qemu",
            headers={"Authorization": "PVEAPIToken=root@pam!emulator=fake-secret"},
        )
        vms = resp.get_json()["data"]
        assert any(vm["vmid"] == 101 and vm["name"] == "persisted-vm" for vm in vms)

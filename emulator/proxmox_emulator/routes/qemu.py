from flask import Blueprint, g, jsonify, request

from ..context import get_state
from ..errors import ProxmoxApiError

bp = Blueprint("qemu", __name__)


def _params():
    if request.form:
        return request.form.to_dict()
    return request.get_json(silent=True) or {}


@bp.route("/nodes/<node>/qemu", methods=["GET"])
def list_qemu(node):
    return jsonify({"data": get_state().list_vms(node)})


@bp.route("/nodes/<node>/qemu", methods=["POST"])
def create_qemu(node):
    params = _params()
    vmid = params.get("vmid")
    if not vmid:
        raise ProxmoxApiError(400, errors={"vmid": "parameter is required"})
    upid = get_state().create_vm(node, vmid, params, user=g.username)
    return jsonify({"data": upid})


@bp.route("/nodes/<node>/qemu/<int:vmid>", methods=["DELETE"])
def delete_qemu(node, vmid):
    upid = get_state().delete_vm(node, vmid, user=g.username)
    return jsonify({"data": upid})


@bp.route("/nodes/<node>/qemu/<int:vmid>/clone", methods=["POST"])
def clone_qemu(node, vmid):
    params = _params()
    newid = params.get("newid")
    if not newid:
        raise ProxmoxApiError(400, errors={"newid": "parameter is required"})
    upid = get_state().clone_vm(node, vmid, newid, params, user=g.username)
    return jsonify({"data": upid})


@bp.route("/nodes/<node>/qemu/<int:vmid>/config", methods=["GET"])
def get_config(node, vmid):
    return jsonify({"data": get_state().get_config(node, vmid)})


@bp.route("/nodes/<node>/qemu/<int:vmid>/status/current", methods=["GET"])
def status_current(node, vmid):
    return jsonify({"data": get_state().get_status(node, vmid)})


@bp.route("/nodes/<node>/qemu/<int:vmid>/status/start", methods=["POST"])
def start_qemu(node, vmid):
    upid = get_state().start_vm(node, vmid, user=g.username)
    return jsonify({"data": upid})


@bp.route("/nodes/<node>/qemu/<int:vmid>/status/stop", methods=["POST"])
def stop_qemu(node, vmid):
    upid = get_state().stop_vm(node, vmid, user=g.username)
    return jsonify({"data": upid})


@bp.route("/nodes/<node>/qemu/<int:vmid>/status/shutdown", methods=["POST"])
def shutdown_qemu(node, vmid):
    upid = get_state().shutdown_vm(node, vmid, user=g.username)
    return jsonify({"data": upid})


@bp.route("/nodes/<node>/qemu/<int:vmid>/snapshot", methods=["GET"])
def list_snapshots(node, vmid):
    return jsonify({"data": get_state().list_snapshots(node, vmid)})


@bp.route("/nodes/<node>/qemu/<int:vmid>/snapshot", methods=["POST"])
def create_snapshot(node, vmid):
    params = _params()
    name = params.get("snapname")
    if not name:
        raise ProxmoxApiError(400, errors={"snapname": "parameter is required"})
    upid = get_state().create_snapshot(node, vmid, name, params.get("vmstate", 0), user=g.username)
    return jsonify({"data": upid})


@bp.route("/nodes/<node>/qemu/<int:vmid>/snapshot/<name>/rollback", methods=["POST"])
def rollback_snapshot(node, vmid, name):
    upid = get_state().restore_snapshot(node, vmid, name, user=g.username)
    return jsonify({"data": upid})


@bp.route("/nodes/<node>/qemu/<int:vmid>/snapshot/<name>", methods=["DELETE"])
def delete_snapshot(node, vmid, name):
    upid = get_state().delete_snapshot(node, vmid, name, user=g.username)
    return jsonify({"data": upid})


@bp.route("/nodes/<node>/qemu/<int:vmid>/agent/network-get-interfaces", methods=["GET"])
def agent_network_ifaces(node, vmid):
    return jsonify({"data": get_state().get_agent_network_ifaces(node, vmid)})


@bp.route("/nodes/<node>/qemu/<int:vmid>/agent/get-osinfo", methods=["GET"])
def agent_osinfo(node, vmid):
    return jsonify({"data": get_state().get_agent_osinfo(node, vmid)})

from flask import Blueprint, jsonify, request

from ..context import get_state

bp = Blueprint("cluster", __name__)


@bp.route("/cluster/resources", methods=["GET"])
def cluster_resources():
    r_type = request.args.get("type")
    return jsonify({"data": get_state().cluster_resources(r_type)})


@bp.route("/cluster/nextid", methods=["GET"])
def cluster_nextid():
    return jsonify({"data": str(get_state().get_next_free_vmid())})

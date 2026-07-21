from flask import Blueprint, jsonify

from ..context import get_state

bp = Blueprint("nodes", __name__)


@bp.route("/nodes", methods=["GET"])
def list_nodes():
    return jsonify({"data": [get_state().node_summary()]})


@bp.route("/nodes/<node>/status", methods=["GET"])
def node_status(node):
    return jsonify({"data": get_state().node_status(node)})

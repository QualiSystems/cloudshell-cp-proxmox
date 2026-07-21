from flask import Blueprint, jsonify

from ..context import get_state

bp = Blueprint("tasks", __name__)


@bp.route("/nodes/<node>/tasks/<path:upid>/status", methods=["GET"])
def task_status(node, upid):
    return jsonify({"data": get_state().get_task_status(upid)})

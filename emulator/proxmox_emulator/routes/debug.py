import json

from flask import Blueprint, Response

from ..context import get_state

bp = Blueprint("debug", __name__)

# Not versioned under /api2/json -- this isn't part of the emulated Proxmox API,
# just a debugging window into the live state dict.
STATE_PATH = "/debug/state"


@bp.route(STATE_PATH, methods=["GET"])
def dump_state():
    body = json.dumps(get_state().dump(), indent=2, sort_keys=True)
    return Response(body, mimetype="application/json")

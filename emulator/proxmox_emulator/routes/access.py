import time

from flask import Blueprint, jsonify, make_response, request

from ..errors import ProxmoxApiError

bp = Blueprint("access", __name__)

# Endpoints reachable with no prior authentication, matching the real API.
OPEN_PATHS = {"/api2/json/access/ticket", "/api2/json/version"}


@bp.route("/version", methods=["GET"])
def version():
    return jsonify({"data": {"version": "8.2.4", "release": "8.2", "repoid": "emulated"}})


@bp.route("/access/ticket", methods=["POST"])
def ticket():
    payload = request.form.to_dict() or (request.get_json(silent=True) or {})
    username = payload.get("username")
    if not username:
        raise ProxmoxApiError(400, errors={"username": "parameter is required"})
    # The emulator does not check the password: any credentials are accepted so
    # the driver can be pointed at it without needing real cluster secrets.
    ticket_value = "PVE:{user}:{ts:08X}::emulated".format(user=username, ts=int(time.time()))
    csrf_token = "emulated-csrf-token"
    response = make_response(
        jsonify(
            {
                "data": {
                    "ticket": ticket_value,
                    "CSRFPreventionToken": csrf_token,
                    "username": username,
                }
            }
        )
    )
    response.set_cookie("PVEAuthCookie", ticket_value)
    return response

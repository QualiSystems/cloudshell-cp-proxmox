from flask import Flask, g, jsonify, request

from .errors import ProxmoxApiError
from .routes import register_routes
from .routes.access import OPEN_PATHS
from .state import ProxmoxState


def create_app(state_path, node_name="pve", action_delay=0.0):
    app = Flask(__name__)
    app.config["PROXMOX_STATE"] = ProxmoxState(state_path, node_name=node_name, action_delay=action_delay)
    app.url_map.strict_slashes = False

    @app.before_request
    def _authenticate():
        if request.path in OPEN_PATHS:
            return None

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("PVEAPIToken="):
            # Format: PVEAPIToken=USER@REALM!TOKENID=<secret>
            g.username = auth_header[len("PVEAPIToken="):].split("!", 1)[0]
            return None

        cookie = request.cookies.get("PVEAuthCookie")
        if cookie and cookie.startswith("PVE:"):
            g.username = cookie.split(":")[1]
            if request.method in ("POST", "PUT", "DELETE") and not request.headers.get("CSRFPreventionToken"):
                raise ProxmoxApiError(401, message="CSRFPreventionToken missing")
            return None

        raise ProxmoxApiError(401, message="authentication failure")

    @app.errorhandler(ProxmoxApiError)
    def _handle_api_error(err):
        return jsonify(err.to_body()), err.status_code

    @app.errorhandler(404)
    def _handle_not_found(err):
        return jsonify({"data": None, "message": "no such resource"}), 404

    register_routes(app)
    return app

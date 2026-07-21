from flask import current_app


def get_state():
    return current_app.config["PROXMOX_STATE"]

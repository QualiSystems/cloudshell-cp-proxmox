class ProxmoxApiError(Exception):
    """Mirrors the shape of an error response from the real Proxmox VE API."""

    def __init__(self, status_code, message=None, errors=None):
        super().__init__(message or (errors and repr(errors)) or "Proxmox API error")
        self.status_code = status_code
        self.message = message
        self.errors = errors

    def to_body(self):
        body = {"data": None}
        if self.errors:
            body["errors"] = self.errors
        if self.message:
            body["message"] = self.message
        return body

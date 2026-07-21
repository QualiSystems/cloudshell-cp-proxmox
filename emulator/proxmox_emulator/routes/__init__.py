from . import access, nodes, qemu, tasks


def register_routes(app):
    app.register_blueprint(access.bp, url_prefix="/api2/json")
    app.register_blueprint(nodes.bp, url_prefix="/api2/json")
    app.register_blueprint(qemu.bp, url_prefix="/api2/json")
    app.register_blueprint(tasks.bp, url_prefix="/api2/json")

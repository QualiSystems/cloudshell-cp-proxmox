import argparse
import os

from .app import create_app

DEFAULT_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "state.json")


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Proxmox VE API emulator (VM create/list/status/start/stop/delete)")
    parser.add_argument("--host", default="0.0.0.0", help="interface to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8006, help="port to listen on (default: 8006, Proxmox's default)")
    parser.add_argument("--node", default="pve", help="name of the single emulated node (default: pve)")
    parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_FILE,
        help="path to the JSON file used to persist VM/task state (default: emulator/data/state.json)",
    )
    parser.add_argument(
        "--action-delay",
        type=float,
        default=0.0,
        help="seconds a create/clone/start/stop/delete task takes before it reports as finished (default: 0, i.e. instant)",
    )
    parser.add_argument("--no-tls", action="store_true", help="serve plain HTTP instead of Proxmox's default self-signed HTTPS")
    parser.add_argument("--reset", action="store_true", help="wipe any existing state file before starting")
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    app = create_app(args.state_file, node_name=args.node, action_delay=args.action_delay)
    if args.reset:
        app.config["PROXMOX_STATE"].reset()

    ssl_context = None if args.no_tls else "adhoc"
    scheme = "http" if args.no_tls else "https"
    print(
        "Proxmox emulator listening on {scheme}://{host}:{port} "
        "(node={node}, state-file={state_file})".format(
            scheme=scheme, host=args.host, port=args.port, node=args.node, state_file=args.state_file
        )
    )
    app.run(host=args.host, port=args.port, ssl_context=ssl_context, threaded=True)


if __name__ == "__main__":
    main()

import json
from urllib.parse import urlencode

import ssl
import warnings
import websocket
from cloudshell.cli.session.helper.normalize_buffer import normalize_buffer

from cloudshell.cp.proxmox.handlers.rest_api_handler import ProxmoxAutomationAPI

websocket.enableTrace(True)

host = "192.168.105.21"
user = "root@pam"
api = ProxmoxAutomationAPI(
    address="192.168.105.21",
    # address="192.168.26.120",
    username="root@pam",
    password="Password1",
)
api.connect()

warnings.filterwarnings(action="ignore")
node_name: str = "proxmox1"
proxmox_host: str = host
proxmox_user: str = user

termproxy = api.get_vnc_shell(node_name)
# termproxy = proxmox.nodes(node_name).termproxy.post(node=node_name)

ticket: str = termproxy.get('ticket')
port: str = termproxy.get('port')

cookie = api.token
headers = {
    'Authorization': f'PVEAPIToken={api.token}',
    'Sec-WebSocket-Protocol': 'bianry',
    'Pragma': 'no-cache',
    'Cache-Control': 'no-cache',
    'Cookie': f'PVEAuthCookie={api.ticket}'
}

ssl_defaults = ssl.get_default_verify_paths()
ssl_context = ssl.create_default_context(cafile=ssl_defaults.cafile)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
opts = {"cert_reqs": ssl.CERT_NONE}

websocket_url = f'wss://{proxmox_host}:8006/api2/json/nodes/{node_name}/vncwebsocket'
query_params = {'port': port, 'vncticket': ticket}

ws = websocket.create_connection(url=f"{websocket_url}?{urlencode(query_params)}", sslopt=opts, header=headers)

handshake = f"{proxmox_user}!{api.token}:{ticket}\n"
# handshake = f"{proxmox_user}:{ticket}\n"

ws.send(handshake)
print(ws.getstatus())
print(ws.recv_data())
# ws.send('1:86:24:')
# print(ws.getstatus())
# print(ws.recv_data())
# ws.ping()
# ws.send_text('lxc-info -n 108 -i\n')
# ws.send_bytes(bytearray('lxc-info -n 108 -i\n', 'utf-8'))
# ws.send('1:86:24:')
# print(ws.getstatus())
# ws.ping()
# print(ws.recv_data())
# print(ws.recv_data())
# print(ws.recv_data())
# print(ws.recv_data())
# print(ws.recv_data())

# ws.ping()
# print(ws.recv_data())
# print(ws.recv_data())
# print(ws.recv_data())
# ws.send('1:86:24:')
# print(ws.recv_data())
# print(ws.recv())
# print(ws.recv())
# print(ws.recv())
# print(ws.recv())
print(ws.recv())
# print(ws.recv())
# print(ws.recv_data())
# print(ws.recv_data())
# print(ws.recv_data())
# print(ws.recv_data())
ws.close()
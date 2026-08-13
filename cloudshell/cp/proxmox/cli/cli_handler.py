from cloudshell.cli.service.cli import CLI
from cloudshell.cli.service.command_mode import CommandMode
from cloudshell.logging.qs_logger import get_qs_logger

from cloudshell.cp.proxmox.cli.websocket_session import WebSocketSession
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from cloudshell.cp.proxmox.utils.instance_type import InstanceType


def execute_commands(cli, source_vmid, target_vmid, logger):
    for step in commands_data['steps']:
        # Replace placeholders with actual VM IDs
        command = step['command'].replace('<vmid>', str(source_vmid)).replace('105',
                                                                              str(target_vmid))

        # Send command using the CLI object's send_command method
        print(f"Executing: {step['description']}")
        result = cli.send_command(command, logger=logger)

        # Print result or handle it as needed
        print(f"Result: {result}")


cli = CLI()
mode = CommandMode(r'#\s*$')
proxmox_handler = ProxmoxHandler.connect(host, username, password, InstanceType.VM)

session_types = [WebSocketSession(host=host, username=username,password=password,
                                  proxmox_handler=proxmox_handler, node=node)]

with cli.get_session(session_types, mode) as cli_service:
    import json
    logger = get_qs_logger()

    # Example JSON structure containing the commands
    commands_json = '''
    {
      "steps": [
        {
          "description": "Shutdown the source VM to ensure data consistency.",
          "command": "qm shutdown <vmid>"
        },
        {
          "description": "Locate the VM's disk files.",
          "command": "ls /var/lib/vz/images/<vmid>/"
        },
        {
          "description": "Create a new directory for the cloned VM.",
          "command": "mkdir /var/lib/vz/images/105/"
        },
        {
          "description": "Copy the VM's disk files to the new directory.",
          "command": "cp /var/lib/vz/images/<vmid>/* /var/lib/vz/images/105/"
        },
        {
          "description": "Copy and rename the VM configuration file.",
          "command": "cp /etc/pve/qemu-server/<vmid>.conf /etc/pve/qemu-server/105.conf"
        },
        {
          "description": "Verify that Proxmox recognizes the new VM.",
          "command": "qm list"
        }
      ]
    }
    '''
    # {
    #   "description": "Edit the new configuration file to update disk paths and other necessary fields.",
    #   "command": "nano /etc/pve/qemu-server/105.conf"
    # },
    #         {
    #           "description": "Start the cloned VM.",
    #           "command": "qm start 105"
    #         }
    # Parse the JSON data
    commands_data = json.loads(commands_json)

    source_vmid = 101  # Replace with actual source VM ID
    target_vmid = proxmox_handler.generate_new_vm_id()
    proxmox_handler.clone_instance(source_vmid, f"testvm{target_vmid}")
    source_vmid = target_vmid
    target_vmid = proxmox_handler.generate_new_vm_id()
    execute_commands(cli_service, source_vmid, target_vmid, logger)
    proxmox_handler.get_instance_storage(target_vmid)
    proxmox_handler.set_disk_data(target_vmid, {""})
    # config = cli_service.send_command(f'qm config {target_vmid}', logger=logger)
    # out = cli_service.send_command(f'qm start {target_vmid}', logger=logger, timeout=300)

    print(out)

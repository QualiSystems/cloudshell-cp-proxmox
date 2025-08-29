from cloudshell.cp.proxmox.constants import VLAN_TEMPLATE, BRIDGE_TEMPLATE
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler
from logging import Logger


class SwitchHandler:
    """
    This class handles the switch operations for the Proxmox environment.
    """

    def __init__(self, api: ProxmoxHandler, logger: Logger):
        """
        Initializes the SwitchHandler with the given sandbox.
        """
        self.api = api
        self.logger = logger

    def prepare_network(self, instance_config, vlan_id, br_name):
        """
        Executes the switch operations.
        :return:
        """
        self.logger.info("Preparing network")
        node = instance_config.get("node")
        vlan = self.create_vlan(node, vlan_id, br_name)
        return self.create_br(node, vlan)

    def create_vlan(self, node, vlan_id, br_name):
        """
        Creates a VLAN in the proxmox.
        :param node:
        :param br_name:
        :param vlan_id: The VLAN ID to be created.
        """
        self.logger.info(f"Creating VLAN {vlan_id}")
        # Add your logic to create VLAN here
        vlan = VLAN_TEMPLATE.format(
            vlan_id=vlan_id
        )
        return self.api.create_vlan(
            node=node,
            vlan_id=vlan_id,
            br_name=br_name,
            vlan_name=vlan
        )

    def create_br(self, node, interface_name):
        """
        Creates a bridge based on the VLAN.
        :param interface_name:
        :param node:
        """
        br = BRIDGE_TEMPLATE.format(vlan_name=interface_name)
        self.logger.info(f"Creating BR {br}")
        # Add your logic to create BR here
        return self.api.create_bridge(
            node=node,
            bridge_name=br,
            interface=interface_name
        )

import warnings
from typing import Optional

from pydantic import Field

from cloudshell.shell.flows.connectivity.models.connectivity_model import (
    ConnectionParamsModel,
    ConnectivityActionModel,
    VlanServiceModel,
)


class ProxmoxVlanServiceModel(VlanServiceModel):
    enable_firewall: Optional[bool] = Field(None, alias="Enable Firewall")


class ProxmoxConnectionParamsModel(ConnectionParamsModel):
    vlan_service_attrs: ProxmoxVlanServiceModel = Field(
        ..., alias="vlanServiceAttributes"
    )


class ProxmoxConnectivityActionModel(ConnectivityActionModel):
    connection_params: ProxmoxConnectionParamsModel = Field(
        ..., alias="connectionParams"
    )

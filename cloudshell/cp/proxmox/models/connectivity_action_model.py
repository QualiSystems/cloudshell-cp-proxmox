import warnings
from typing import Optional

from pydantic import Field

from cloudshell.shell.flows.connectivity.models.connectivity_model import (
    ConnectionParamsModel,
    ConnectivityActionModel,
    VlanServiceModel,
)


class ProxmoxVlanServiceModel(VlanServiceModel):
    port_group_name: Optional[str] = Field(None, alias="Port Group Name")

    def __getattribute__(self, item):
        if item in ("port_group_name", "virtual_network"):
            msg = (
                "'Port Group Name' and 'Virtual Network' attributes are deprecated, "
                "use 'Existing Network' instead"
            )
            warnings.warn(msg, DeprecationWarning, stacklevel=2)
        return super().__getattribute__(item)


class ProxmoxConnectionParamsModel(ConnectionParamsModel):
    vlan_service_attrs: ProxmoxVlanServiceModel = Field(
        ..., alias="vlanServiceAttributes"
    )


class ProxmoxConnectivityActionModel(ConnectivityActionModel):
    connection_params: ProxmoxConnectionParamsModel = Field(
        ..., alias="connectionParams"
    )

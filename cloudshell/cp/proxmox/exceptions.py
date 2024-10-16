from __future__ import annotations

from collections.abc import Iterable

from attrs import define

from cloudshell.cp.proxmox.constants import SNAPSHOT_TYPE


class BaseProxmoxException(Exception):
    pass


class InvalidCommandParam(BaseProxmoxException):
    def __init__(
        self, param_name: str, param_value: str, expected_values: Iterable[str]
    ):
        self.param_name = param_name
        self.param_value = param_value
        self.expected_values = expected_values
        super().__init__(
            f"Param '{param_name}' is invalid. It should be one of the "
            f"'{expected_values}' but the value is '{param_value}'"
        )


class AuthAPIException(BaseProxmoxException):
    """Wrong ticket Exception."""


class InstanceIsNotRunningException(BaseProxmoxException):
    """Instance is not running."""


class ParamsException(BaseProxmoxException):
    """Parameter verification failed."""


class UnsuccessfulOperationException(BaseProxmoxException):
    """Operation finished unsuccessfully."""


class InvalidAttributeException(BaseProxmoxException):
    """Attribute is not valid."""


class VmDoesNotExistException(BaseProxmoxException):
    """Virtual Machine does not exist."""


class VmIsNotPowered(BaseProxmoxException):
    """Virtual Machine is not powered."""


@define
class VMIPNotFoundException(BaseProxmoxException):
    ip_regex: str | None = None

    def __str__(self):
        msg = "IP address not found"
        if self.ip_regex:
            msg = f"{msg} by regex: {self.ip_regex}"
        return msg


class InvalidOrchestrationType(BaseProxmoxException):
    def __init__(self, type_: str):
        msg = f"Invalid orchestration type '{type_}', expect {SNAPSHOT_TYPE}"
        super().__init__(msg)

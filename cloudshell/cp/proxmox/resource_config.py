from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from attr import Attribute
from attrs import define

from cloudshell.api.cloudshell_api import CloudShellAPISession, ResourceInfo
from cloudshell.cp.proxmox.constants import STATIC_SHELL_NAME
from cloudshell.shell.standards.core.namespace_type import NameSpaceType
from cloudshell.shell.standards.core.resource_conf import BaseConfig, attr
from cloudshell.shell.standards.core.resource_conf.attrs_getter import (
    MODEL,
    AbsAttrsGetter,
)
from cloudshell.shell.standards.core.resource_conf.base_conf import password_decryptor
from cloudshell.shell.standards.core.resource_conf.resource_attr import AttrMeta


class ShutdownMethod(Enum):
    SOFT = "soft"
    HARD = "hard"


class ProxmoxAttributeNames:
    user = "User"
    password = "Password"
    shared_storage = "Shared Storage"
    shutdown_method = "Shutdown Method"
    default_bridge = "Default Bridge"
    reserved_networks = "Reserved Networks"


@define(slots=False, str=False)
class ProxmoxResourceConfig(BaseConfig):
    ATTR_NAMES = ProxmoxAttributeNames

    user: str = attr(ATTR_NAMES.user)
    password: str = attr(ATTR_NAMES.password, is_password=True)
    shared_storage: str = attr(ATTR_NAMES.shared_storage)
    default_bridge: str = attr(ATTR_NAMES.default_bridge)
    reserved_networks: str = attr(ATTR_NAMES.reserved_networks)
    shutdown_method: ShutdownMethod = attr(ATTR_NAMES.shutdown_method)

    @classmethod
    def from_cs_resource_details(
        cls,
        details: ResourceInfo,
        api: CloudShellAPISession,
    ) -> ProxmoxResourceConfig:
        attrs = ResourceInfoAttrGetter(
            cls, password_decryptor(api), details
        ).get_attrs()
        converter = cls._CONVERTER(cls, attrs)
        return cls(
            name=details.Name,
            shell_name=details.ResourceModelName,
            family_name=details.ResourceFamilyName,
            address=details.Address,
            api=api,
            **converter.convert(),
        )

    @property
    def is_static(self) -> bool:
        return self.shell_name == STATIC_SHELL_NAME


class ResourceInfoAttrGetter(AbsAttrsGetter):
    def __init__(
        self,
        model_cls: type[MODEL],
        decrypt_password: Callable[[str], str],
        details: ResourceInfo,
    ):
        super().__init__(model_cls, decrypt_password)
        self.details = details
        self._attrs = {a.Name: a.Value for a in details.ResourceAttributes}
        self.shell_name = details.ResourceModelName
        self.family_name = details.ResourceFamilyName

    def _extract_attr_val(self, f: Attribute, meta: AttrMeta) -> str:
        key = self._get_key(meta)
        return self._attrs[key]

    def _get_key(self, meta: AttrMeta) -> str:
        namespace = self._get_namespace(meta.namespace_type)
        return f"{namespace}.{meta.name}"

    def _get_namespace(self, namespace_type: NameSpaceType) -> str:
        if namespace_type is NameSpaceType.SHELL_NAME:
            namespace = self.shell_name
        elif namespace_type is NameSpaceType.FAMILY_NAME:
            namespace = self.family_name
        else:
            raise ValueError(f"Unknown namespace: {namespace_type}")
        return namespace

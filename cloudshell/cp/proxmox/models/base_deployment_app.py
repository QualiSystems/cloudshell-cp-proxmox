from __future__ import annotations

from typing import Any

from attrs import define


class ProxmoxDeploymentAppAttributeNames:
    target_node = "Target Node"
    target_storage = "Target Storage"
    behavior_during_save = "Behavior during save"
    auto_power_on = "Auto Power On"
    auto_power_off = "Auto Power Off"
    wait_for_ip = "Wait for IP"
    ip_regex = "IP Regex"
    auto_delete = "Auto Delete"
    autoload = "Autoload"
    refresh_ip_timeout = "Refresh IP Timeout"
    autogenerated_name = "Autogenerated Name"


class ProxmoxInstanceFromQEMUImageDeploymentAppAttributeNames(
    ProxmoxDeploymentAppAttributeNames
):
    image_url = "Image URL"


class ProxmoxInstanceFromContainerImageDeploymentAppAttributeNames(
    ProxmoxDeploymentAppAttributeNames
):
    container_image = "Container Image"


class ProxmoxInstanceFromVMDeploymentAppAttributeNames(
    ProxmoxDeploymentAppAttributeNames
):
    vm_id = "VM ID"
    snapshot = "Snapshot"


class ProxmoxInstanceFromContainerDeploymentAppAttributeNames(
    ProxmoxDeploymentAppAttributeNames
):
    container_id = "Container ID"
    snapshot = "Snapshot"


class ProxmoxInstanceFromTemplateDeploymentAppAttributeNames(
    ProxmoxDeploymentAppAttributeNames
):
    template_id = "Template ID"
    clone_mode = "Clone Mode"


@define
class ResourceAttrRODeploymentPath:
    name: str
    default: Any = None

    def get_key(self, instance) -> str:
        dp = instance.DEPLOYMENT_PATH
        return f"{dp}.{self.name}"

    def __get__(self, instance, owner):
        if instance is None:
            return self

        return instance.attributes.get(self.get_key(instance), self.default)


class ResourceBoolAttrRODeploymentPath(ResourceAttrRODeploymentPath):
    TRUE_VALUES = {"true", "yes", "y"}
    FALSE_VALUES = {"false", "no", "n"}

    def __get__(self, instance, owner):
        val = super().__get__(instance, owner)
        if val is self or val is self.default or not isinstance(val, str):
            return val
        if val.lower() in self.TRUE_VALUES:
            return True
        if val.lower() in self.FALSE_VALUES:
            return False
        raise ValueError(f"{self.name} is boolean attr, but value is {val}")


class ResourceListAttrRODeploymentPath(ResourceAttrRODeploymentPath):
    def __init__(self, name, sep=";", default=None):
        if default is None:
            default = []
        super().__init__(name, default)
        self._sep = sep

    def __get__(self, instance, owner):
        val = super().__get__(instance, owner)
        if val is self or val is self.default or not isinstance(val, str):
            return val
        return list(filter(bool, map(str.strip, val.split(self._sep))))


class ResourceIntAttrRODeploymentPath(ResourceAttrRODeploymentPath):
    def __get__(self, instance, owner) -> int:
        val = super().__get__(instance, owner)
        if val is self or val is self.default:
            return val
        return int(val) if val else None


class ResourceFloatAttrRODeploymentPath(ResourceAttrRODeploymentPath):
    def __get__(self, instance, owner) -> float:
        val = super().__get__(instance, owner)
        if val is self or val is self.default:
            return val
        return float(val) if val else None

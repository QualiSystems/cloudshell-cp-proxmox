from enum import Enum


class InstanceType(Enum):
    VM = "qemu"
    CONTAINER = "lxc"

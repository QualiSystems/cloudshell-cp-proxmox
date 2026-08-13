from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from attrs import define

from cloudshell.cp.proxmox.exceptions import InvalidAttributeException
from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler

if TYPE_CHECKING:
    from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig


logger = logging.getLogger(__name__)


# todo move this validation to the model
BEHAVIOURS_DURING_SAVE = ("Remain Powered On", "Power Off")


@define
class ValidationActions:
    _si: ProxmoxHandler
    _resource_conf: ProxmoxResourceConfig

    def validate_resource_conf(self):
        logger.info("Validating resource config")
        conf = self._resource_conf
        _is_not_empty(conf.address, "address")
        _is_not_empty(conf.user, conf.ATTR_NAMES.user)
        _is_not_empty(conf.password, conf.ATTR_NAMES.password)
        # _is_value_in(
        #     conf.behavior_during_save,
        #     BEHAVIOURS_DURING_SAVE,
        #     conf.ATTR_NAMES.behavior_during_save,
        # )


def _is_not_empty(value: str, attr_name: str):
    if not value:
        raise InvalidAttributeException(f"{attr_name} cannot be empty")


def _is_value_in(value: str, expected_values: Iterable[str], attr_name: str):
    if value not in expected_values:
        raise InvalidAttributeException(
            f"{attr_name} should be one of the {list(expected_values)}"
        )

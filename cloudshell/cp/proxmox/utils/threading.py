from __future__ import annotations

import logging
from contextlib import contextmanager
from threading import Lock

from attrs import define, field

logger = logging.getLogger(__name__)


@define
class LockHandler:
    _lock_creation_lock: Lock = field(init=False, factory=Lock)
    _locks: dict[str, Lock] = field(init=False, factory=dict)

    @contextmanager
    def lock(self, net_name: str) -> None:
        lock = self._get_lock(net_name)
        with lock:
            yield

    def _get_lock(self, net_name: str) -> Lock:
        lock = self._locks.get(net_name)
        if not lock:
            with self._lock_creation_lock:
                if not (lock := self._locks.get(net_name)):
                    lock = Lock()
                    self._locks[net_name] = lock
        return lock

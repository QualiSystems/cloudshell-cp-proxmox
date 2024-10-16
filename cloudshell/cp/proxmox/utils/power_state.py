from enum import Enum


class PowerState(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    PAUSED = "paused"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"
    ERROR = "error"

    @staticmethod
    def from_str(label):
        return next(
            (state for state in PowerState if state.value == label), PowerState.UNKNOWN
        )

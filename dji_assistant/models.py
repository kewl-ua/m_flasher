from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from functools import total_ordering
import re


class FirmwareAction(str, Enum):
    REFRESH = "refresh"
    DOWNGRADE = "downgrade"
    UPGRADE = "upgrade"
    UPDATE = "update"
    UNKNOWN = "unknown"


@total_ordering
@dataclass(frozen=True)
class FirmwareVersion:
    parts: tuple[int, ...]

    def __post_init__(self):
        if len(self.parts) < 3 or any(type(part) is not int or part < 0 for part in self.parts):
            raise ValueError("Firmware version requires at least three non-negative integers.")

    @classmethod
    def parse(cls, value: str) -> "FirmwareVersion":
        value = value.strip()
        match = re.fullmatch(r"[Vv]?(\d+(?:\.\d+){2,})", value)
        if not match:
            raise ValueError(f"Invalid firmware version: {value!r}")
        return cls(tuple(int(part) for part in match.group(1).split(".")))

    def __str__(self) -> str:
        return ".".join(f"{part:04d}" if i == len(self.parts) - 1 else f"{part:02d}"
                        for i, part in enumerate(self.parts))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, FirmwareVersion):
            return NotImplemented
        return self.parts < other.parts


@dataclass(frozen=True)
class FirmwareEntry:
    version: FirmwareVersion
    action: FirmwareAction
    date: date | None = None
    official: bool | None = None
    current: bool = False


class FirmwareStage(str, Enum):
    IDLE = "idle"
    CONFIRMATION = "confirmation"
    DOWNLOADING = "downloading"
    TRANSMITTING = "transmitting"
    UPDATING = "updating"
    COMPLETE = "complete"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FirmwareStatus:
    stage: FirmwareStage
    version: FirmwareVersion | None = None
    percent: int | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class FirmwareResult:
    action: str
    previous: FirmwareVersion
    installed: FirmwareVersion

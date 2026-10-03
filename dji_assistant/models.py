from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from functools import total_ordering


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

    @classmethod
    def parse(cls, value: str) -> "FirmwareVersion":
        value = value.strip()
        if value[:1].lower() == "v":
            value = value[1:]
        return cls(tuple(int(part) for part in value.split(".")))

    def __str__(self) -> str:
        return ".".join(f"{part:02d}" if i < 3 else f"{part:04d}"
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

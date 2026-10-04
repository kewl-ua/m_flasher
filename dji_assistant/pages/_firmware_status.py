from __future__ import annotations

import re

from ._firmware_tree import FirmwareNode, _walk
from ..exceptions import UnexpectedAssistantState
from ..models import FirmwareStage, FirmwareStatus, FirmwareVersion

CONFIRMATION_TEXT = "During the whole upgrade process, the following items are required:"
CONFIRMATION_ITEMS = {
    "Computer is connected to the internet.",
    "Device powered on with sufficient battery",
    "USB Connection",
}
_STAGES = {
    "Downloading": FirmwareStage.DOWNLOADING,
    "Transmitting": FirmwareStage.TRANSMITTING,
    "Updating": FirmwareStage.UPDATING,
    "Update Complete!": FirmwareStage.COMPLETE,
    "Update failed.": FirmwareStage.FAILED,
    CONFIRMATION_TEXT: FirmwareStage.CONFIRMATION,
}


def parse_status(root: FirmwareNode) -> FirmwareStatus:
    nodes = list(_walk(root))
    texts = [node.name for node in nodes if node.control_type == "Text"]
    stages = {_STAGES[name] for name in texts if name in _STAGES}
    if len(stages) > 1:
        raise UnexpectedAssistantState("Multiple firmware stages visible.")
    if not stages:
        stage = FirmwareStage.IDLE if "Current" in texts or "Current:" in texts else FirmwareStage.UNKNOWN
        return FirmwareStatus(stage)
    stage = stages.pop()
    versions: set[FirmwareVersion] = set()
    if stage != FirmwareStage.CONFIRMATION:
        for name in texts:
            if re.fullmatch(r"[Vv]?\d+(?:\.\d+){2,}", name):
                versions.add(FirmwareVersion.parse(name))
            match = re.fullmatch(r"The DJI device has been updated to: ([Vv]?\d+(?:\.\d+){2,})", name)
            if match:
                versions.add(FirmwareVersion.parse(match.group(1)))
    if len(versions) > 1:
        raise UnexpectedAssistantState("Ambiguous firmware progress target.")
    percents: set[int] = set()
    for index, name in enumerate(texts):
        if name == "%" and index and texts[index - 1].isdigit():
            percents.add(int(texts[index - 1]))
        elif re.fullmatch(r"\d+%", name):
            percents.add(int(name[:-1]))
    if len(percents) > 1 or any(value > 100 for value in percents):
        raise UnexpectedAssistantState("Invalid or ambiguous firmware progress.")
    codes = {name for name in texts if re.fullmatch(r"\d+(?:-\d+){2,}", name)} if stage == FirmwareStage.FAILED else set()
    if len(codes) > 1:
        raise UnexpectedAssistantState("Ambiguous firmware error code.")
    return FirmwareStatus(
        stage, next(iter(versions), None), next(iter(percents), None),
        next(iter(codes), None) if stage == FirmwareStage.FAILED else None,
    )

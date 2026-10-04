from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ..exceptions import UnexpectedAssistantState
from ..models import FirmwareAction, FirmwareEntry, FirmwareVersion

_VERSION = re.compile(r"[Vv]?(\d+(?:\.\d+){2,})")
_DATE = re.compile(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}")
_ACTIONS = {action.value.capitalize(): action for action in FirmwareAction
            if action is not FirmwareAction.UNKNOWN}


@dataclass(frozen=True)
class FirmwareNode:
    control_type: str
    name: str
    children: tuple[FirmwareNode, ...] = ()


def _walk(node: FirmwareNode):
    yield node
    for child in node.children:
        yield from _walk(child)


def installed_version(root: FirmwareNode) -> FirmwareVersion:
    labels: list[FirmwareVersion] = []

    def inspect(node: FirmwareNode):
        if node.control_type == "Table":
            return
        children = node.children
        for index, child in enumerate(children):
            if child.control_type == "Text" and child.name in {"Current", "Current:"}:
                following = index + 1
                if following < len(children) and children[following].name == ":":
                    following += 1
                if following >= len(children):
                    raise UnexpectedAssistantState("Current label has no version.")
                match = _VERSION.fullmatch(children[following].name)
                if not match:
                    raise UnexpectedAssistantState("Current label has invalid version.")
                labels.append(FirmwareVersion.parse(match.group(1)))
            inspect(child)

    inspect(root)
    if len(labels) != 1:
        raise UnexpectedAssistantState(
            f"Expected one standalone Current label, found {len(labels)}."
        )
    return labels[0]


def parse_firmware_tree(
    root: FirmwareNode,
    row_nodes: dict[FirmwareVersion, FirmwareNode] | None = None,
) -> list[FirmwareEntry]:
    tables = [node for node in _walk(root) if node.control_type == "Table"]
    if len(tables) != 1:
        raise UnexpectedAssistantState(
            f"Expected one firmware table, found {len(tables)}."
        )

    entries: list[FirmwareEntry] = []
    table_versions: set[FirmwareVersion] = set()

    def visit(node: FirmwareNode):
        versions: set[FirmwareVersion] = set()
        actions: list[FirmwareAction] = []
        names: list[str] = []
        contains_row = False
        if node.control_type == "Text":
            names.append(node.name)
            match = _VERSION.fullmatch(node.name)
            if match and not _DATE.fullmatch(node.name):
                version = FirmwareVersion.parse(match.group(1))
                versions.add(version)
                table_versions.add(version)
        if node.control_type == "Button":
            actions.append(_ACTIONS.get(node.name, FirmwareAction.UNKNOWN))
        elif node.control_type == "Hyperlink" and node.name in _ACTIONS:
            actions.append(_ACTIONS[node.name])
        for child in node.children:
            child_versions, child_actions, child_names, child_row = visit(child)
            versions.update(child_versions)
            actions.extend(child_actions)
            names.extend(child_names)
            contains_row = contains_row or child_row
        if not contains_row and len(versions) == 1 and actions:
            if len(actions) != 1:
                raise UnexpectedAssistantState("Firmware row has multiple actions.")
            if actions[0] is FirmwareAction.UNKNOWN:
                raise UnexpectedAssistantState("Firmware row has an unknown action.")
            dates = {name for name in names if _DATE.fullmatch(name)}
            if len(dates) > 1:
                raise UnexpectedAssistantState("Firmware row has multiple dates.")
            parsed_date = None
            if dates:
                value = dates.pop()
                try:
                    parsed_date = date.fromisoformat(
                        "-".join(f"{int(part):02d}" for part in re.split(r"[-/.]", value))
                    )
                except ValueError as exc:
                    raise UnexpectedAssistantState(
                        f"Invalid firmware date: {value!r}."
                    ) from exc
            entries.append(FirmwareEntry(
                version=next(iter(versions)),
                action=actions[0],
                date=parsed_date,
                official=True if "OFFICIAL" in names else None,
                current="CURRENT" in names,
            ))
            if row_nodes is not None:
                row_nodes[entries[-1].version] = node
            contains_row = True
        return versions, actions, names, contains_row

    visit(tables[0])
    versions = [entry.version for entry in entries]
    if not entries:
        raise UnexpectedAssistantState("No firmware rows with known actions found.")
    if len(set(versions)) != len(versions):
        raise UnexpectedAssistantState("Duplicate firmware versions in table.")
    if set(versions) != table_versions:
        raise UnexpectedAssistantState("Some firmware versions have no isolated row.")
    current = [entry for entry in entries if entry.current]
    installed = installed_version(root)
    if len(current) > 1:
        raise UnexpectedAssistantState(
            f"Expected one CURRENT firmware row, found {len(current)}."
        )

    if (current and current[0].version != installed) or (
        not current and installed in table_versions
    ):
        raise UnexpectedAssistantState("Current label and firmware table disagree.")
    return entries

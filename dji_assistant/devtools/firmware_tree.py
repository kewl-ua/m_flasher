from __future__ import annotations

import re
from collections import Counter

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dji_assistant import DJIAssistant
from dji_assistant.backend.uia.helpers import (
    compact_control,
    info_of,
    safe_descendants,
    safe_parent,
)
from dji_assistant.constants import FIRMWARE_ACTION_NAMES

console = Console()

VERSION_RE = re.compile(r"\b[Vv]?(\d+(?:\.\d+){2,})\b")
DATE_RE = re.compile(r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b")


def version_strings(root) -> set[str]:
    out = set()

    controls = [root] + safe_descendants(root)
    for ctrl in controls:
        try:
            name = info_of(ctrl)["name"]
        except Exception:
            continue

        for m in VERSION_RE.finditer(name):
            out.add(m.group(1))

    return out


def action_controls(root):
    found = []

    for ctrl in [root] + safe_descendants(root):
        try:
            i = info_of(ctrl)
        except Exception:
            continue

        if (
            i["type"] in {"Button", "Hyperlink"}
            and i["name"] in FIRMWARE_ACTION_NAMES
        ):
            found.append(ctrl)

    return found


def dates_in(root) -> set[str]:
    dates = set()

    for ctrl in [root] + safe_descendants(root):
        try:
            name = info_of(ctrl)["name"]
        except Exception:
            continue

        dates.update(DATE_RE.findall(name))

    return dates


def find_smallest_row_candidate(version: str, ctrl, max_depth: int = 8):
    """
    A firmware row should be the smallest ancestor which:
      * contains the requested version;
      * contains exactly one unique firmware version;
      * contains at least one firmware action (Refresh/Downgrade/etc).

    This deliberately excludes the page/document ancestor, which contains
    both current-version text and all firmware rows.
    """
    current = ctrl

    for depth in range(max_depth + 1):
        versions = version_strings(current)
        actions = action_controls(current)

        if version in versions and len(versions) == 1 and actions:
            return depth, current

        current = safe_parent(current)
        if current is None:
            break

    return None, None


def print_ancestor_chain(ctrl, max_depth: int = 7):
    current = ctrl

    for depth in range(max_depth + 1):
        if current is None:
            break

        versions = sorted(version_strings(current))
        actions = [info_of(x)["name"] for x in action_controls(current)]
        dates = sorted(dates_in(current))

        console.print(
            f"  [dim]L{depth}[/dim] {compact_control(current)} "
            f"[cyan]versions={versions}[/cyan] "
            f"[magenta]actions={actions}[/magenta] "
            f"[green]dates={dates}[/green]"
        )

        current = safe_parent(current)


def print_row(row, version: str):
    console.print(Panel.fit(
        f"[bold]Firmware row candidate[/bold]\nversion={version}\n"
        f"{compact_control(row)}",
        border_style="green",
    ))

    table = Table("Type", "Name", "AutomationId", "Class")
    controls = [row] + safe_descendants(row)

    for ctrl in controls:
        i = info_of(ctrl)
        if not any((i["name"], i["automation_id"], i["class_name"])):
            continue
        table.add_row(
            i["type"],
            i["name"],
            i["automation_id"],
            i["class_name"],
        )

    console.print(table)


def main():
    console.print("[bold]Connecting to DJI Assistant...[/bold]")

    with DJIAssistant.connect() as dji:
        console.print("[green]OK[/green] UIA window connected")

        dji.firmware.open()
        console.print("[green]OK[/green] Firmware Update opened\n")

        occurrences = dji.firmware.version_controls()

        if not occurrences:
            console.print("[red]No firmware-version strings found.[/red]")
            raise SystemExit(2)

        console.print("[bold]Version occurrences:[/bold]")
        for idx, (version, ctrl) in enumerate(occurrences):
            console.print(
                f"  [{idx}] {version:16} {compact_control(ctrl)}"
            )

        console.print(
            "\n[bold]Ancestor analysis[/bold] "
            "(this is what we need for FirmwarePage.available()):"
        )

        rows = {}
        unresolved = []

        for idx, (version, ctrl) in enumerate(occurrences):
            console.print(
                f"\n[yellow]Occurrence #{idx}: {version}[/yellow]"
            )
            print_ancestor_chain(ctrl)

            depth, row = find_smallest_row_candidate(version, ctrl)

            if row is None:
                unresolved.append((version, ctrl))
                console.print(
                    "  [dim]No isolated firmware-row candidate found. "
                    "This occurrence is likely Current version or another "
                    "non-row label.[/dim]"
                )
                continue

            key = id(row.element_info)
            rows[key] = (version, row, depth)
            console.print(
                f"  [green]ROW FOUND[/green] at ancestor level {depth}"
            )

        console.print("\n[bold]Isolated firmware rows:[/bold]")

        if not rows:
            console.print("[red]None found.[/red]")
        else:
            for version, row, depth in rows.values():
                print_row(row, version)

        console.print("\n[bold]Summary[/bold]")
        console.print(f"  version occurrences : {len(occurrences)}")
        console.print(f"  isolated rows       : {len(rows)}")
        console.print(f"  unresolved labels   : {len(unresolved)}")

        if rows:
            console.print(
                "\n[green]Good sign:[/green] if the isolated rows correspond "
                "to V01.00.0900/Refresh and V01.00.0800/Downgrade, "
                "we have enough structure to implement the real parser."
            )


if __name__ == "__main__":
    main()

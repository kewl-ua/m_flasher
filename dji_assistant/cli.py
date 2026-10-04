from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from .client import DJIAssistant
from .backend.uia.helpers import info_of
from .constants import WINDOW_TITLE
from .devtools.firmware_tree import main as firmware_probe_main

console = Console()


def cmd_diagnose(window_title: str = WINDOW_TITLE):
    with DJIAssistant.connect(title=window_title) as dji:
        win = dji._session.window
        info = info_of(win)

        table = Table("Check", "Result")
        table.add_row("DJI Assistant", "[green]connected[/green]")
        table.add_row("Backend", "UIA")
        table.add_row("Window", info["name"])
        table.add_row("Class", info["class_name"])

        console.print(table)


def main():
    parser = argparse.ArgumentParser(prog="dji-assistant")
    parser.add_argument("--window-title", default=WINDOW_TITLE)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("diagnose")
    sub.add_parser("firmware-probe")

    args = parser.parse_args()

    if args.command == "diagnose":
        cmd_diagnose(window_title=args.window_title)
    elif args.command == "firmware-probe":
        firmware_probe_main(window_title=args.window_title)


if __name__ == "__main__":
    main()

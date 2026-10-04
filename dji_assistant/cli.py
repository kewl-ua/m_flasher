from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from .client import DJIAssistant
from .backend.uia.helpers import info_of
from .constants import WINDOW_TITLE
from .devtools.firmware_tree import main as firmware_probe_main
from .exceptions import DJIAssistantError

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
    parser.add_argument(
        "--no-physical-input", action="store_true",
        help="Disallow SDK mouse clicks, focus requests and physical-input fallbacks",
    )
    parser.add_argument(
        "--addressed-input", action="store_true",
        help="Experimental renderer messages for card/picker; native dialogs can take focus",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("diagnose")
    sub.add_parser("firmware-probe")
    sub.add_parser("list")
    sub.add_parser("current")
    sub.add_parser("status")
    select = sub.add_parser("offline-select", help="Select a ZIP without starting a write")
    select.add_argument("package")
    for name in ("downgrade", "upgrade", "refresh", "offline-upgrade"):
        command = sub.add_parser(name)
        if name != "refresh":
            command.add_argument("target")
        if name == "offline-upgrade":
            command.add_argument("package")
        command.add_argument("--expected-device", required=True)
        command.add_argument("--expected-current", required=True)
        command.add_argument("--yes", action="store_true",
                             help="Authorize firmware write; hardware must be prepared")
        command.add_argument("--timeout", type=float, default=1200)

    args = parser.parse_args()
    if (args.no_physical_input or args.addressed_input) and args.command == "firmware-probe":
        parser.error("firmware-probe does not support input mode options.")

    if args.command in {"downgrade", "upgrade", "refresh", "offline-upgrade"} and not args.yes:
        parser.error("Firmware write requires --yes. No device action was performed.")
    try:
        if args.command == "diagnose":
            cmd_diagnose(window_title=args.window_title)
        elif args.command == "firmware-probe":
            firmware_probe_main(window_title=args.window_title)
        else:
            with DJIAssistant.connect(
                title=args.window_title, allow_physical_input=not args.no_physical_input,
                addressed_input=args.addressed_input,
            ) as dji:
                if args.command == "status":
                    console.print(dji.firmware.status())
                elif args.command == "offline-select":
                    console.print(dji.offline.select_package(args.package))
                else:
                    dji.firmware.open()
                    if args.command == "current":
                        console.print(str(dji.firmware.current()))
                    elif args.command == "list":
                        for entry in dji.firmware.available():
                            console.print(entry)
                    else:
                        options = dict(
                            expected_device=args.expected_device,
                            expected_current=args.expected_current,
                            confirm=args.yes, timeout=args.timeout,
                            on_status=console.print,
                        )
                        if args.command == "offline-upgrade":
                            result = dji.offline.upgrade(args.package, args.target, **options)
                        elif args.command == "refresh":
                            result = dji.firmware.refresh(**options)
                        elif args.command == "upgrade":
                            result = dji.firmware.upgrade(args.target, **options)
                        else:
                            result = dji.firmware.downgrade(args.target, **options)
                        console.print(result)
    except (DJIAssistantError, ValueError, OSError) as exc:
        console.print(f"Error: {exc}", style="red", markup=False)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

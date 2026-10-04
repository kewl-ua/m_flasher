from __future__ import annotations

import argparse
import math

from rich.console import Console
from rich.table import Table

from .client import DJIAssistant
from .isolated import IsolatedAssistant, _DESKTOP_NAME
from .backend.uia.helpers import info_of
from .constants import WINDOW_TITLE
from .devtools.firmware_tree import main as firmware_probe_main
from .exceptions import DJIAssistantError

console = Console()


def _timeout(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and positive.")
    return result


def _add_isolated_commands(sub) -> None:
    isolated = sub.add_parser(
        "isolated", help="Experimental separate-desktop commands; no firmware writes",
    )
    commands = isolated.add_subparsers(dest="isolated_command", required=True)
    for name in (
        "launch", "attach", "open-device", "current", "status",
        "ignore-flysafe", "offline-select", "quit",
    ):
        command = commands.add_parser(name)
        command.add_argument(
            "--timeout", type=_timeout,
            default={"launch": 60, "offline-select": 120, "quit": 20}.get(name, 30),
        )
        if name == "launch":
            command.add_argument("executable", help="Installed DJI Assistant executable")
        else:
            command.add_argument("--desktop", default=_DESKTOP_NAME)
        if name == "open-device":
            command.add_argument("name")
        if name == "offline-select":
            command.add_argument("package")


def _cmd_isolated(args) -> int:
    dji = None
    result = 0
    try:
        if args.isolated_command == "launch":
            dji = IsolatedAssistant.launch(
                args.executable, title=args.window_title, timeout=args.timeout,
            )
        else:
            dji = IsolatedAssistant.attach(
                args.desktop, title=args.window_title, timeout=args.timeout,
            )
        command = args.isolated_command
        if command in {"launch", "attach"}:
            console.print(f"Connected desktop: {dji.desktop_name}", markup=False)
            console.print("Assistant remains running. Use isolated quit for normal exit.")
        elif command == "open-device":
            dji.open_device(args.name, timeout=args.timeout)
            console.print(f"Opened device: {args.name}", markup=False)
        elif command == "current":
            console.print(str(dji.current()))
        elif command == "status":
            console.print(dji.status())
        elif command == "ignore-flysafe":
            dji.ignore_flysafe()
            console.print("FlySafe Ignore completed (or no known prompt was present).")
        elif command == "offline-select":
            console.print(str(dji.select_package(args.package, timeout=args.timeout)), markup=False)
            console.print("Package selected only; no firmware write started.")
        elif command == "quit":
            dji.quit_application(timeout=args.timeout)
            console.print("Assistant normal exit confirmed.")
    except (DJIAssistantError, ValueError, OSError) as exc:
        console.print(f"Error: {exc}", style="red", markup=False)
        result = 1
    finally:
        if dji is not None:
            try:
                dji.close()
            except (DJIAssistantError, OSError) as exc:
                console.print(
                    f"Disconnect error: {exc}. Recovery desktop: {dji.desktop_name}",
                    style="red", markup=False,
                )
                result = 1
    return result


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
    _add_isolated_commands(sub)
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
    if args.command == "isolated":
        if args.no_physical_input or args.addressed_input:
            parser.error("isolated commands always prohibit physical input and use addressed input.")
        return _cmd_isolated(args)
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

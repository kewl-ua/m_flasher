from __future__ import annotations

import time
import math
import re
from collections.abc import Callable
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import win32con
import win32gui
from pywinauto import Desktop

from .base import BasePage
from ._firmware_operations import WRITE_LOCK, FirmwareOperations, validate_options, version_value
from .firmware import FirmwarePage
from ._firmware_tree import _walk
from ..exceptions import FirmwareOperationFailed, FirmwareOutcomeUnknown, UnexpectedAssistantState
from ..models import FirmwareResult, FirmwareStatus, FirmwareVersion

PACKAGE_FIELD = "Click here to select firmware zip package..."


def validate_package(path: str | Path) -> Path:
    package = Path(path).expanduser().resolve(strict=True)
    if not package.is_file() or package.suffix.lower() != ".zip":
        raise ValueError("Offline Upgrade requires an original DJI ZIP package.")
    try:
        with ZipFile(package) as archive:
            entries = archive.infolist()
            if not entries or any(entry.flag_bits & 1 for entry in entries):
                raise ValueError("Empty or encrypted firmware ZIP is unsupported.")
            if not any(entry.filename.endswith(".cfg.sig") for entry in entries):
                raise ValueError("Expected DJI configuration signature file is missing.")
            if len({entry.filename for entry in entries}) != len(entries):
                raise ValueError("Firmware ZIP has duplicate entry names.")
            if any(Path(entry.filename).is_absolute() or ".." in Path(entry.filename).parts
                   or "\\" in entry.filename or ":" in entry.filename for entry in entries):
                raise ValueError("Firmware ZIP contains unsafe paths.")
            bad = archive.testzip()
            if bad is not None:
                raise ValueError(f"Firmware ZIP CRC failed: {bad}")
    except BadZipFile as exc:
        raise ValueError("Invalid firmware ZIP.") from exc
    return package


def package_target(package: Path, expected_device: str) -> FirmwareVersion:
    if expected_device != "Matrice 4T":
        raise ValueError("Offline package model validation currently supports Matrice 4T only.")
    with ZipFile(package) as archive:
        configs = [entry.filename for entry in archive.infolist()
                   if entry.filename.endswith(".cfg.sig")]
    if len(configs) != 1:
        raise ValueError("Expected one offline package configuration.")
    match = re.fullmatch(r"wa345t_0000_v(\d+(?:\.\d+){2,})_[^/]+\.cfg\.sig", configs[0])
    if not match:
        raise ValueError("Offline configuration filename is not for the observed M4T package format.")
    return FirmwareVersion.parse(match.group(1))


class OfflinePage(BasePage):
    def open(self) -> "OfflinePage":
        from ._firmware_status import parse_status
        from ..models import FirmwareStage
        root, _ = FirmwarePage(self.session)._capture()
        if parse_status(root).stage not in {FirmwareStage.IDLE, FirmwareStage.UNKNOWN}:
            raise UnexpectedAssistantState("Cannot navigate during firmware operation or confirmation.")
        link = self.session.window_spec.child_window(
            title="Offline Upgrade", control_type="Hyperlink"
        )
        link.wait("exists visible enabled", timeout=10)
        link.wrapper_object().invoke()
        self._field().wait("exists visible enabled", timeout=10)
        return self

    def _field(self):
        return self.session.window_spec.child_window(
            title=PACKAGE_FIELD, control_type="Edit"
        )

    def selected_package(self) -> Path | None:
        value = self._field().wrapper_object().get_value().strip()
        return Path(value).resolve() if value else None

    def _owned_file_dialogs(self):
        candidates = [
            *Desktop(backend="uia").windows(class_name="#32770"),
            *self.window.descendants(control_type="Window", class_name="#32770"),
        ]
        dialogs = {}
        for window in candidates:
            owner = win32gui.GetWindow(window.handle, win32con.GW_OWNER)
            seen = set()
            while owner and owner not in seen:
                if owner == self.window.handle:
                    dialogs[window.handle] = window
                    break
                seen.add(owner)
                owner = win32gui.GetWindow(owner, win32con.GW_OWNER)
        return list(dialogs.values())

    def select_package(self, path: str | Path, *, timeout: float = 10) -> Path:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive.")
        package = validate_package(path)
        self.open()
        if self.selected_package() == package:
            return package
        self.window.set_focus()
        field = self._field().wrapper_object()
        rectangle = field.rectangle()
        point = (int((rectangle.left + rectangle.right) / 2),
                 int((rectangle.top + rectangle.bottom) / 2))
        hit = win32gui.WindowFromPoint(point)
        if win32gui.GetAncestor(hit, win32con.GA_ROOT) != self.window.handle:
            raise UnexpectedAssistantState(
                "File field is covered by another window. Uncover DJI Assistant and try selection again."
            )
        field.click_input()
        deadline = time.monotonic() + timeout
        dialog = None
        while time.monotonic() < deadline:
            dialogs = self._owned_file_dialogs()
            if len(dialogs) > 1:
                raise UnexpectedAssistantState("Multiple owned file dialogs; no file submitted.")
            if dialogs:
                dialog = dialogs[0]
                break
            time.sleep(0.2)
        if dialog is None:
            raise UnexpectedAssistantState(
                "Owned file dialog not found. Select the ZIP manually; do not press Start Upgrade."
            )
        return self._submit_package(dialog, package, deadline)

    def _submit_package(self, dialog, package: Path, deadline: float) -> Path:
        # Standard Windows file dialogs expose language-independent IDs.
        combos = [ctrl for ctrl in dialog.descendants(control_type="ComboBox")
                  if ctrl.element_info.automation_id == "1148"]
        if len(combos) != 1:
            raise UnexpectedAssistantState("File-name control is not unique; no file submitted.")
        edits = combos[0].descendants(control_type="Edit")
        buttons = [ctrl for ctrl in dialog.descendants(control_type="Button")
                   if ctrl.element_info.automation_id == "1"]
        if len(edits) != 1 or len(buttons) != 1:
            raise UnexpectedAssistantState("File dialog layout unsupported; no file submitted.")
        edits[0].set_edit_text(str(package))
        FirmwareOperations.invoke(buttons[0])
        while time.monotonic() < deadline:
            if self.selected_package() == package:
                return package
            time.sleep(0.2)
        raise UnexpectedAssistantState("File selection was not confirmed in DJI Assistant.")

    def upgrade(
        self, path: str | Path, target: str | FirmwareVersion, *,
        expected_device: str, expected_current: str | FirmwareVersion,
        confirm: bool = False, timeout: float = 1200, poll_interval: float = 2,
        on_status: Callable[[FirmwareStatus], None] | None = None,
    ) -> FirmwareResult:
        if not WRITE_LOCK.acquire(blocking=False):
            raise UnexpectedAssistantState("Another SDK firmware operation is in progress.")
        try:
            return self._upgrade(
                path, target, expected_device=expected_device,
                expected_current=expected_current, confirm=confirm, timeout=timeout,
                poll_interval=poll_interval, on_status=on_status,
            )
        finally:
            WRITE_LOCK.release()

    def _upgrade(
        self, path: str | Path, target: str | FirmwareVersion, *,
        expected_device: str, expected_current: str | FirmwareVersion,
        confirm: bool = False, timeout: float = 1200, poll_interval: float = 2,
        on_status: Callable[[FirmwareStatus], None] | None = None,
    ) -> FirmwareResult:
        validate_options(confirm, timeout, poll_interval)
        package = validate_package(path)
        fingerprint = package.stat()
        target_version = version_value(target)
        if package_target(package, expected_device) != target_version:
            raise ValueError("Requested target does not match offline configuration filename.")
        firmware = FirmwarePage(self.session)
        from ._firmware_status import parse_status
        from ..models import FirmwareStage
        state_root, _ = firmware._capture()
        state = parse_status(state_root)
        if state.stage not in {FirmwareStage.IDLE, FirmwareStage.UNKNOWN}:
            raise UnexpectedAssistantState("An operation or confirmation is already visible.")
        if state.stage is FirmwareStage.UNKNOWN:
            names = {node.name for node in _walk(state_root)}
            if "Local version:" not in names:
                raise UnexpectedAssistantState("Expected idle firmware or offline page.")
        firmware.open()
        operations = FirmwareOperations(firmware)
        operations.offline_package = package
        root, _ = firmware._capture()
        previous = operations.guard(root, expected_device, expected_current)
        self.open()
        if self.selected_package() != package:
            self.select_package(package)
        if self.selected_package() != package:
            raise UnexpectedAssistantState("Exact ZIP selection was not verified.")
        root, controls = firmware._capture()
        operations._require_device(root, expected_device)
        buttons = [node for node in _walk(root)
                   if node.control_type == "Button" and node.name == "Start Upgrade"]
        if len(buttons) != 1:
            raise UnexpectedAssistantState("Start Upgrade is not unique.")
        now = package.stat()
        if (now.st_size, now.st_mtime_ns) != (fingerprint.st_size, fingerprint.st_mtime_ns):
            raise UnexpectedAssistantState("Firmware ZIP changed after validation.")
        button = controls[id(buttons[0])]
        if not button.is_enabled() or not button.is_visible():
            raise UnexpectedAssistantState("Start Upgrade is disabled or invisible.")
        deadline = time.monotonic() + timeout
        try:
            button.invoke()
            return operations.wait(target_version, previous, "offline", expected_device,
                                   deadline, poll_interval, on_status)
        except (FirmwareOutcomeUnknown, FirmwareOperationFailed):
            raise
        except Exception as exc:
            raise FirmwareOutcomeUnknown(
                "Offline write may have started. Do not retry; inspect DJI Assistant."
            ) from exc

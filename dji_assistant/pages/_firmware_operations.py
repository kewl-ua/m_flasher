from __future__ import annotations

import math
import time
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING
from pathlib import Path

from ._firmware_status import CONFIRMATION_ITEMS, parse_status
from ._firmware_tree import FirmwareNode, _walk, installed_version, parse_firmware_tree
from ..exceptions import (
    FirmwareOperationFailed, FirmwareOutcomeUnknown, UIElementNotFound,
    UnexpectedAssistantState,
)
from ..models import (
    FirmwareAction, FirmwareResult, FirmwareStage, FirmwareStatus, FirmwareVersion,
)

WRITE_LOCK = threading.Lock()

if TYPE_CHECKING:
    from .firmware import FirmwarePage


def version_value(value: str | FirmwareVersion) -> FirmwareVersion:
    return FirmwareVersion.parse(value) if isinstance(value, str) else value


def validate_options(confirm: bool, timeout: float, poll_interval: float):
    if confirm is not True:
        raise ValueError("Firmware writes require confirm=True and prepared hardware.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive.")
    if not math.isfinite(poll_interval) or poll_interval <= 0:
        raise ValueError("poll_interval must be finite and positive.")


class FirmwareOperations:
    def __init__(self, page: FirmwarePage):
        self.page = page
        self.offline_package: Path | None = None

    def guard(self, root: FirmwareNode, expected_device: str,
              expected_current: str | FirmwareVersion) -> FirmwareVersion:
        if not expected_device.strip():
            raise ValueError("expected_device must not be empty.")
        names = [node.name for node in _walk(root)]
        if any(name in names for name in ("Confirm", "Ignore", "Start Update")):
            raise UnexpectedAssistantState("An unexpected confirmation is already open.")
        device_nodes = [node for node in _walk(root)
                        if node.control_type == "Hyperlink" and node.name == expected_device]
        if len(device_nodes) != 1:
            raise UnexpectedAssistantState("Expected device page is not uniquely identified.")
        current = installed_version(root)
        if current != version_value(expected_current):
            raise UnexpectedAssistantState(
                f"Current version changed: expected {expected_current}, got {current}."
            )
        return current

    @staticmethod
    def invoke(button):
        if not button.is_enabled() or not button.is_visible():
            raise UnexpectedAssistantState("Action button is disabled or invisible.")
        button.invoke()

    def online(
        self, action: FirmwareAction, version: str | FirmwareVersion, *,
        expected_device: str, expected_current: str | FirmwareVersion,
        confirm: bool = False, timeout: float = 1200, poll_interval: float = 2,
        on_status: Callable[[FirmwareStatus], None] | None = None,
    ) -> FirmwareResult:
        if not WRITE_LOCK.acquire(blocking=False):
            raise UnexpectedAssistantState("Another SDK firmware operation is in progress.")
        try:
            return self._online(
                action, version, expected_device=expected_device,
                expected_current=expected_current, confirm=confirm, timeout=timeout,
                poll_interval=poll_interval, on_status=on_status,
            )
        finally:
            WRITE_LOCK.release()

    def _online(
        self, action: FirmwareAction, version: str | FirmwareVersion, *,
        expected_device: str, expected_current: str | FirmwareVersion,
        confirm: bool = False, timeout: float = 1200, poll_interval: float = 2,
        on_status: Callable[[FirmwareStatus], None] | None = None,
    ) -> FirmwareResult:
        validate_options(confirm, timeout, poll_interval)
        target = version_value(version)
        if action is FirmwareAction.REFRESH and target != version_value(expected_current):
            raise ValueError("Refresh target must equal expected_current.")
        root, controls = self.page._capture()
        previous = self.guard(root, expected_device, expected_current)
        if action is FirmwareAction.DOWNGRADE and target >= previous:
            raise ValueError("Downgrade target must be older than current.")
        if action is FirmwareAction.UPGRADE and target <= previous:
            raise ValueError("Upgrade target must be newer than current.")
        rows: dict[FirmwareVersion, FirmwareNode] = {}
        entries = parse_firmware_tree(root, rows)
        matches = [entry for entry in entries if entry.version == target]
        if len(matches) != 1:
            raise UIElementNotFound(f"Target firmware {target} is not uniquely available.")
        if matches[0].action is not action:
            raise UnexpectedAssistantState(
                f"Target row offers {matches[0].action.value}, not {action.value}."
            )
        buttons = [node for node in _walk(rows[target])
                   if node.control_type in {"Button", "Hyperlink"}
                   and node.name == action.value.capitalize()]
        if len(buttons) != 1:
            raise UnexpectedAssistantState("Firmware action is not unique.")
        button = controls[id(buttons[0])]
        if not button.is_enabled() or not button.is_visible():
            raise UnexpectedAssistantState("Firmware action is disabled or invisible.")
        deadline = time.monotonic() + timeout
        try:
            # Invoke may have reached the application even if it raises.
            button.invoke()
            return self.wait(target, previous, action.value, expected_device,
                             deadline, poll_interval, on_status)
        except (FirmwareOperationFailed, FirmwareOutcomeUnknown):
            raise
        except Exception as exc:
            raise FirmwareOutcomeUnknown(
                "Firmware action may have started. Do not retry; inspect DJI Assistant."
            ) from exc

    def wait(self, target: FirmwareVersion, previous: FirmwareVersion, action: str,
             expected_device: str, deadline: float, poll_interval: float,
             on_status: Callable[[FirmwareStatus], None] | None) -> FirmwareResult:
        confirmation_sent = False
        active_seen = False
        last_status = None
        stage_rank = -1
        ranks = {FirmwareStage.DOWNLOADING: 0, FirmwareStage.TRANSMITTING: 1,
                 FirmwareStage.UPDATING: 2}
        while time.monotonic() < deadline:
            root, controls = self.page._capture()
            status = parse_status(root)
            names = {node.name for node in _walk(root)}
            if any(name in names for name in ("Confirm", "Ignore")):
                raise FirmwareOutcomeUnknown("Unexpected dialog; no further buttons pressed.")
            if status != last_status and on_status is not None:
                on_status(status)
            last_status = status
            if status.version is not None and status.version != target:
                raise FirmwareOutcomeUnknown("Progress shows an unexpected target; do not retry.")
            if status.stage is FirmwareStage.FAILED:
                raise FirmwareOperationFailed(status.error_code)
            if status.stage is FirmwareStage.CONFIRMATION:
                if confirmation_sent or active_seen:
                    raise FirmwareOutcomeUnknown("Confirmation reappeared; no repeated Start Update.")
                nodes = list(_walk(root))
                names = {node.name for node in nodes}
                required = CONFIRMATION_ITEMS if action != "offline" else {
                    "Device powered on with sufficient battery", "USB Connection",
                }
                if not required.issubset(names):
                    raise FirmwareOutcomeUnknown("Unexpected firmware requirements dialog.")
                if action != "offline":
                    if installed_version(root) != previous:
                        raise FirmwareOutcomeUnknown("Current changed before confirmation.")
                self._require_device(root, expected_device)
                if action == "offline":
                    fields = [node for node in nodes if node.control_type == "Edit"
                              and node.name == "Click here to select firmware zip package..."]
                    if len(fields) != 1 or self.offline_package is None:
                        raise FirmwareOutcomeUnknown("Offline package field is missing.")
                    if Path(controls[id(fields[0])].get_value()).resolve() != self.offline_package:
                        raise FirmwareOutcomeUnknown("Offline package changed before confirmation.")
                buttons = [node for node in nodes if node.control_type == "Button"
                           and node.name == "Start Update"]
                if len(buttons) != 1:
                    raise FirmwareOutcomeUnknown("Start Update is not unique.")
                confirmation_sent = True
                self.invoke(controls[id(buttons[0])])
            elif status.stage in ranks:
                active_seen = True
                rank = ranks[status.stage]
                if rank < stage_rank:
                    raise FirmwareOutcomeUnknown("Firmware stage regressed; inspect application.")
                stage_rank = rank
            elif status.stage is FirmwareStage.COMPLETE:
                if status.version != target or status.percent != 100:
                    raise FirmwareOutcomeUnknown("Completion target or 100% is not confirmed.")
                buttons = [node for node in _walk(root)
                           if node.control_type == "Button" and node.name == "Back"]
                if len(buttons) != 1:
                    raise FirmwareOutcomeUnknown("Completion Back button is not unique.")
                self.invoke(controls[id(buttons[0])])
                while time.monotonic() < deadline:
                    next_root, _ = self.page._capture()
                    if parse_status(next_root).stage in {FirmwareStage.IDLE, FirmwareStage.UNKNOWN}:
                        break
                    time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
                else:
                    raise FirmwareOutcomeUnknown("Back navigation was not confirmed.")
                self.page.open()
                return self._verify(target, previous, action, expected_device,
                                    deadline, poll_interval)
            elif status.stage is FirmwareStage.IDLE and active_seen:
                raise FirmwareOutcomeUnknown(
                    "Completion was not observed; inspect Current and device manually."
                )
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        raise FirmwareOutcomeUnknown("Firmware wait timed out. Do not retry or interrupt the device.")

    @staticmethod
    def _require_device(root: FirmwareNode, expected_device: str):
        matches = [node for node in _walk(root)
                   if node.control_type == "Hyperlink" and node.name == expected_device]
        if len(matches) != 1:
            raise FirmwareOutcomeUnknown("Device page changed; outcome requires manual verification.")

    def _verify(
        self, target: FirmwareVersion, previous: FirmwareVersion, action: str,
        expected_device: str, deadline: float, poll_interval: float,
    ) -> FirmwareResult:
        last_read_error = None
        while time.monotonic() < deadline:
            root, _ = self.page._capture()
            names = {node.name for node in _walk(root)}
            if "Current" in names or "Current:" in names:
                self._require_device(root, expected_device)
                try:
                    installed = installed_version(root)
                except UnexpectedAssistantState as exc:
                    last_read_error = exc
                    time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
                    continue
                if installed != target:
                    raise FirmwareOutcomeUnknown(
                        f"Completion reported success but Current is {installed}, not {target}."
                    )
                return FirmwareResult(action, previous, installed)
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        raise FirmwareOutcomeUnknown(
            "Completion observed but Current verification timed out."
        ) from last_read_error

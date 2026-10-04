from __future__ import annotations

import re
import time
from collections.abc import Callable
from pywinauto.controls.uiawrapper import UIAWrapper

from .base import BasePage
from ._firmware_tree import FirmwareNode, installed_version, parse_firmware_tree
from ..constants import FIRMWARE_LINK_NAME
from ..exceptions import UIElementNotFound
from ..models import (
    FirmwareAction, FirmwareEntry, FirmwareResult, FirmwareStatus, FirmwareVersion,
)

VERSION_RE = re.compile(r"\b[Vv]?(\d+(?:\.\d+){2,})\b")


class FirmwarePage(BasePage):
    def _capture(self) -> tuple[FirmwareNode, dict[int, UIAWrapper]]:
        controls: dict[int, UIAWrapper] = {}

        def capture(ctrl: UIAWrapper) -> FirmwareNode:
            info = ctrl.element_info
            node = FirmwareNode(
                control_type=info.control_type,
                name=(info.name or "").strip(),
                children=tuple(capture(child) for child in ctrl.children()),
            )
            controls[id(node)] = ctrl
            return node

        return capture(self.window), controls

    def available(self) -> list[FirmwareEntry]:
        root, _ = self._capture()
        return parse_firmware_tree(root)

    def current(self) -> FirmwareVersion:
        root, _ = self._capture()
        return installed_version(root)

    def status(self) -> FirmwareStatus:
        from ._firmware_status import parse_status
        root, _ = self._capture()
        return parse_status(root)

    def run(
        self, action: FirmwareAction, version: str | FirmwareVersion, *,
        expected_device: str, expected_current: str | FirmwareVersion,
        confirm: bool = False, timeout: float = 1200, poll_interval: float = 2,
        on_status: Callable[[FirmwareStatus], None] | None = None,
    ) -> FirmwareResult:
        from ._firmware_operations import FirmwareOperations
        if action not in {FirmwareAction.DOWNGRADE, FirmwareAction.UPGRADE, FirmwareAction.REFRESH}:
            raise ValueError("Unsupported firmware operation.")
        return FirmwareOperations(self).online(
            action, version, expected_device=expected_device,
            expected_current=expected_current, confirm=confirm, timeout=timeout,
            poll_interval=poll_interval, on_status=on_status,
        )

    def downgrade(
        self, version: str | FirmwareVersion, *, expected_device: str,
        expected_current: str | FirmwareVersion, confirm: bool = False,
        timeout: float = 1200, poll_interval: float = 2,
        on_status: Callable[[FirmwareStatus], None] | None = None,
    ) -> FirmwareResult:
        return self.run(
            FirmwareAction.DOWNGRADE, version, expected_device=expected_device,
            expected_current=expected_current, confirm=confirm, timeout=timeout,
            poll_interval=poll_interval, on_status=on_status,
        )

    def upgrade(
        self, version: str | FirmwareVersion, *, expected_device: str,
        expected_current: str | FirmwareVersion, confirm: bool = False,
        timeout: float = 1200, poll_interval: float = 2,
        on_status: Callable[[FirmwareStatus], None] | None = None,
    ) -> FirmwareResult:
        return self.run(
            FirmwareAction.UPGRADE, version, expected_device=expected_device,
            expected_current=expected_current, confirm=confirm, timeout=timeout,
            poll_interval=poll_interval, on_status=on_status,
        )

    def refresh(
        self, *, expected_device: str, expected_current: str | FirmwareVersion,
        confirm: bool = False, timeout: float = 1200, poll_interval: float = 2,
        on_status: Callable[[FirmwareStatus], None] | None = None,
    ) -> FirmwareResult:
        return self.run(
            FirmwareAction.REFRESH, expected_current, expected_device=expected_device,
            expected_current=expected_current, confirm=confirm, timeout=timeout,
            poll_interval=poll_interval, on_status=on_status,
        )

    def select(self, version: str | FirmwareVersion) -> FirmwareEntry:
        target = FirmwareVersion.parse(version) if isinstance(version, str) else version
        for entry in self.available():
            if entry.version == target:
                return entry
        raise UIElementNotFound(f"Firmware version {target} is not in the table.")

    def open(self) -> "FirmwarePage":
        from ._firmware_status import parse_status
        from ..models import FirmwareStage
        from ..exceptions import UnexpectedAssistantState
        root, _ = self._capture()
        if parse_status(root).stage not in {FirmwareStage.IDLE, FirmwareStage.UNKNOWN}:
            raise UnexpectedAssistantState("Cannot navigate during firmware operation or confirmation.")
        link = self.session.window_spec.child_window(
            title=FIRMWARE_LINK_NAME,
            control_type="Hyperlink",
        )

        try:
            link.wait("exists visible enabled", timeout=10)
            obj = link.wrapper_object()
        except Exception as exc:
            raise UIElementNotFound(
                "Firmware Update hyperlink was not found"
            ) from exc

        try:
            obj.invoke()
        except Exception:
            obj.click_input()

        # Temporary synchronization for milestone 0.
        # We replace it with state-based waits once the page model is known.
        time.sleep(1.5)
        return self

    def version_controls(self):
        matches = []

        for ctrl in self.window.descendants():
            try:
                info = ctrl.element_info
                name = (getattr(info, "name", "") or "").strip()
                if not name:
                    continue

                m = VERSION_RE.search(name)
                if not m:
                    continue

                matches.append((m.group(1), ctrl))
            except Exception:
                continue

        return matches

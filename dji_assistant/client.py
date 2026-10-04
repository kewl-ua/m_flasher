from __future__ import annotations

import math
import os
import time
from pathlib import Path

from pywinauto import Desktop
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.uia_defines import IUIA
from pywinauto.uia_element_info import UIAElementInfo
import win32con
import win32gui

from .backend.uia.session import UIASession
from .constants import WINDOW_TITLE
from .pages.firmware import FirmwarePage
from .pages.offline import OfflinePage
from .exceptions import DJIAssistantNotRunning, UnexpectedAssistantState


class DJIAssistant:
    def __init__(self, session: UIASession):
        self._session = session
        self.firmware = FirmwarePage(session)
        self.offline = OfflinePage(session)

    @classmethod
    def connect(cls, title: str = WINDOW_TITLE) -> "DJIAssistant":
        return cls(UIASession(title=title).connect())

    @classmethod
    def launch(
        cls, executable: str | Path, *, title: str = WINDOW_TITLE,
        timeout: float = 30,
    ) -> "DJIAssistant":
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive.")
        path = Path(executable).resolve(strict=True)
        if not path.is_file() or path.suffix.lower() != ".exe":
            raise ValueError("Expected installed DJI Assistant executable.")
        desktop = Desktop(backend="uia")
        windows = desktop.windows(title=title)
        if len(windows) > 1:
            raise UnexpectedAssistantState("Multiple Assistant windows; not launching.")
        if not windows:
            os.startfile(str(path), cwd=str(path.parent))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            windows = desktop.windows(title=title)
            if len(windows) > 1:
                raise UnexpectedAssistantState("Multiple Assistant windows appeared.")
            if windows and windows[0].is_visible() and windows[0].is_enabled():
                return cls.connect(title=title)
            time.sleep(0.2)
        raise DJIAssistantNotRunning("Assistant launch timed out; application is not terminated.")

    def _raw_device_cards(self, name: str) -> list[UIAWrapper]:
        walker = IUIA().iuia.RawViewWalker
        pending = [(self._session.window.element_info.element, 0)]
        names = set()
        cards = []
        count = 0
        while pending:
            element, depth = pending.pop()
            count += 1
            if count > 500 or depth > 20:
                raise UnexpectedAssistantState("Device-list Raw View exceeds search limits.")
            label = (element.CurrentName or "").strip()
            names.add(label)
            if label == name:
                cards.append(UIAWrapper(UIAElementInfo(element)))
            child = walker.GetFirstChildElement(element)
            while child:
                pending.append((child, depth + 1))
                child = walker.GetNextSiblingElement(child)
                if len(pending) + count > 500:
                    raise UnexpectedAssistantState("Device-list Raw View exceeds search limits.")
        return cards if "CONNECTED DEVICES" in names else []

    def _click_device_card(self, card: UIAWrapper) -> None:
        window = self._session.window
        window.set_focus()
        bounds = card.rectangle()
        outer = window.rectangle()
        if (bounds.width() <= 0 or bounds.height() <= 0
                or bounds.left < outer.left or bounds.right > outer.right
                or bounds.top < outer.top or bounds.bottom > outer.bottom):
            raise UnexpectedAssistantState("Device card bounds are outside the Assistant window.")
        center = bounds.mid_point()
        hit = win32gui.WindowFromPoint((center.x, center.y))
        if win32gui.GetAncestor(hit, win32con.GA_ROOT) != window.handle:
            raise UnexpectedAssistantState("Device card is covered by another window.")
        card.click_input()

    def open_device(self, name: str, *, timeout: float = 30):
        if not name.strip() or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Device name and positive finite timeout are required.")
        deadline = time.monotonic() + timeout
        invoked = False
        firmware_navigation_sent = False
        readiness_error = None
        backend_pending = False
        while time.monotonic() < deadline:
            controls = self._session.window.descendants()
            names = {(c.element_info.name or "").strip() for c in controls}
            if "DJI ASSISTANT 2" in names:
                agreements = [
                    c for c in controls if (c.element_info.name or "").strip() == "Agree"
                    and c.element_info.control_type == "Button" and c.is_visible()
                ]
                if agreements:
                    raise UnexpectedAssistantState(
                        "DJI Assistant Terms of Use require user acceptance. "
                        "SDK did not press Agree."
                    )
            backend_pending = "Waiting for Backend to boot up ..." in names
            if backend_pending:
                time.sleep(0.2)
                continue
            if name in names and ("Current" in names or "Local version:" in names):
                if "Current" not in names:
                    if not firmware_navigation_sent:
                        firmware_navigation_sent = True
                        self.firmware.open()
                    time.sleep(0.2)
                    continue
                try:
                    self.firmware.current()
                except UnexpectedAssistantState as exc:
                    readiness_error = exc
                    time.sleep(0.2)
                    continue
                return self
            targets = [c for c in controls if (c.element_info.name or "").strip() == name]
            raw_card = False
            if not targets and not invoked and "DJI ASSISTANT 2" in names:
                targets = self._raw_device_cards(name)
                raw_card = True
            if len(targets) > 1:
                raise UnexpectedAssistantState("Device card is ambiguous; no selection.")
            if targets and not invoked:
                target = targets[0]
                if not target.is_enabled() or not target.is_visible():
                    raise UnexpectedAssistantState("Device card is not enabled and visible.")
                invoked = True
                if raw_card:
                    self._click_device_card(target)
                else:
                    target.invoke()
            time.sleep(0.2)
        if backend_pending:
            raise UnexpectedAssistantState(
                "DJI Assistant backend did not become ready before timeout. "
                "No device card was invoked and no firmware action was started."
            )
        raise UnexpectedAssistantState(
            "Device card/page was not exposed through UIA before timeout. "
            "A visually present card may be missing from Accessibility; "
            "no repeated card invocation was performed."
        ) from readiness_error

    def flysafe_prompt(self) -> bool:
        names = {(c.element_info.name or "").strip()
                 for c in self._session.window.descendants()}
        return "Updating No-fly Zone Database is required. Update now?" in names

    def confirm_flysafe(self, *, confirm: bool = False):
        if confirm is not True:
            raise ValueError("FlySafe update requires separate confirm=True.")
        if not self.flysafe_prompt():
            raise UnexpectedAssistantState("Expected FlySafe prompt is not present.")
        button = self._session.window_spec.child_window(title="Confirm", control_type="Button")
        button.wait("exists visible enabled", timeout=10)
        button.wrapper_object().invoke()

    def quit_application(self, *, timeout: float = 15) -> None:
        from .models import FirmwareStage

        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive.")
        if self.firmware.status().stage is not FirmwareStage.IDLE:
            raise UnexpectedAssistantState(
                "Application exit requires a verified idle firmware page."
            )
        deadline = time.monotonic() + timeout
        controls = self._session.window.descendants()
        if not any((ctrl.element_info.name or "").strip() == "Quit Now?"
                   for ctrl in controls):
            self._session.window.close()
        while time.monotonic() < deadline:
            windows = Desktop(backend="uia").windows(
                title=self._session.title, enabled_only=False
            )
            if not windows:
                self.close()
                return
            controls = self._session.window.descendants()
            prompts = [ctrl for ctrl in controls
                       if (ctrl.element_info.name or "").strip() == "Quit Now?"]
            if prompts:
                if len(prompts) != 1:
                    raise UnexpectedAssistantState("Quit confirmation is ambiguous.")
                dialog = prompts[0].parent()
                buttons = [ctrl for ctrl in dialog.descendants(control_type="Button")
                           if (ctrl.element_info.name or "").strip() == "Yes"]
                if len(buttons) != 1:
                    raise UnexpectedAssistantState("Quit dialog Yes button is not unique.")
                button = buttons[0]
                if not button.is_enabled() or not button.is_visible():
                    raise UnexpectedAssistantState("Quit confirmation is not available.")
                button.invoke()
                break
            time.sleep(0.2)
        else:
            raise UnexpectedAssistantState("Quit confirmation did not appear; no forced termination.")
        while time.monotonic() < deadline:
            if not Desktop(backend="uia").windows(
                title=self._session.title, enabled_only=False
            ):
                self.close()
                return
            time.sleep(0.2)
        raise UnexpectedAssistantState("Application exit was not confirmed; Yes was not repeated.")

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

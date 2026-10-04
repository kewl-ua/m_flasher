from __future__ import annotations

from pywinauto import Desktop
from pywinauto.application import WindowSpecification
from pywinauto.controls.uiawrapper import UIAWrapper

from ...constants import WINDOW_TITLE
from ...exceptions import DJIAssistantNotRunning


class UIASession:
    def __init__(self, title: str = WINDOW_TITLE):
        self.title = title
        self._window: UIAWrapper | None = None
        self._window_spec: WindowSpecification | None = None

    def connect(self) -> "UIASession":
        spec = Desktop(backend="uia").window(title=self.title)

        try:
            spec.wait("exists visible ready", timeout=10)
            self._window = spec.wrapper_object()
            self._window_spec = spec
        except Exception as exc:
            raise DJIAssistantNotRunning(
                f"DJI Assistant window not found: {self.title!r}"
            ) from exc

        return self

    @property
    def window(self) -> UIAWrapper:
        if self._window is None:
            raise DJIAssistantNotRunning(
                "UIA session is not connected. Call connect() first."
            )
        return self._window

    @property
    def window_spec(self) -> WindowSpecification:
        if self._window_spec is None:
            raise DJIAssistantNotRunning(
                "UIA session is not connected. Call connect() first."
            )
        return self._window_spec

    def close(self):
        # We do not close DJI Assistant itself; we only release our reference.
        self._window = None
        self._window_spec = None

from __future__ import annotations

from pywinauto import Desktop

from ...constants import WINDOW_TITLE
from ...exceptions import DJIAssistantNotRunning


class UIASession:
    def __init__(self, title: str = WINDOW_TITLE):
        self.title = title
        self._window = None

    def connect(self):
        spec = Desktop(backend="uia").window(title=self.title)

        try:
            spec.wait("exists visible ready", timeout=10)
            self._window = spec.wrapper_object()
        except Exception as exc:
            raise DJIAssistantNotRunning(
                f"DJI Assistant window not found: {self.title!r}"
            ) from exc

        return self

    @property
    def window(self):
        if self._window is None:
            raise DJIAssistantNotRunning(
                "UIA session is not connected. Call connect() first."
            )
        return self._window

    def close(self):
        # We do not close DJI Assistant itself; we only release our reference.
        self._window = None

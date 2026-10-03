from __future__ import annotations

from .backend.uia.session import UIASession
from .pages.firmware import FirmwarePage


class DJIAssistant:
    def __init__(self, session: UIASession):
        self._session = session
        self.firmware = FirmwarePage(session)

    @classmethod
    def connect(cls) -> "DJIAssistant":
        return cls(UIASession().connect())

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

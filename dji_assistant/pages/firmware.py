from __future__ import annotations

import re
import time

from .base import BasePage
from ..constants import FIRMWARE_LINK_NAME
from ..exceptions import UIElementNotFound

VERSION_RE = re.compile(r"\b[Vv]?(\d+(?:\.\d+){2,})\b")


class FirmwarePage(BasePage):
    def open(self) -> "FirmwarePage":
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

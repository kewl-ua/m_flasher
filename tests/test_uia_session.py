import unittest
from unittest.mock import Mock, patch

from dji_assistant.backend.uia.session import UIASession
from dji_assistant.client import DJIAssistant
from dji_assistant.constants import FIRMWARE_LINK_NAME, WINDOW_TITLE
from dji_assistant.exceptions import DJIAssistantNotRunning
from dji_assistant.pages.firmware import FirmwarePage


class UIASessionTests(unittest.TestCase):
    def test_spec_and_wrapper_have_separate_roles(self):
        wrapper = Mock(spec=["descendants", "children", "element_info"])
        wrapper.children.return_value = []
        wrapper.element_info.control_type = "Window"
        wrapper.element_info.name = ""
        spec = Mock()
        spec.wrapper_object.return_value = wrapper
        with patch("dji_assistant.backend.uia.session.Desktop") as desktop:
            desktop.return_value.window.return_value = spec
            session = UIASession().connect()

        desktop.assert_called_once_with(backend="uia")
        desktop.return_value.window.assert_called_once_with(title=WINDOW_TITLE)
        self.assertIs(session.window, wrapper)
        self.assertIs(session.window_spec, spec)
        page = FirmwarePage(session)
        with patch("dji_assistant.pages.firmware.time.sleep"):
            self.assertIs(page.open(), page)
        spec.child_window.assert_called_once_with(
            title=FIRMWARE_LINK_NAME, control_type="Hyperlink"
        )
        link = spec.child_window.return_value
        link.wait.assert_called_once_with("exists visible enabled", timeout=10)
        link.wrapper_object.return_value.invoke.assert_called_once_with()
        link.wrapper_object.return_value.click_input.assert_not_called()
        wrapper.descendants.return_value = []
        self.assertEqual(page.version_controls(), [])
        wrapper.descendants.assert_called_once_with()

        session.close()
        for name in ("window", "window_spec"):
            with self.assertRaises(DJIAssistantNotRunning):
                getattr(session, name)

    def test_unconnected_session_rejects_both_window_forms(self):
        session = UIASession()
        for name in ("window", "window_spec"):
            with self.assertRaises(DJIAssistantNotRunning):
                getattr(session, name)

    def test_client_passes_explicit_title(self):
        title = "DJI Assistant 2 (Enterprise Series)"
        with patch("dji_assistant.client.UIASession") as session:
            client = DJIAssistant.connect(title=title)
        session.assert_called_once_with(title=title)
        self.assertIs(client._session, session.return_value.connect.return_value)


if __name__ == "__main__":
    unittest.main()

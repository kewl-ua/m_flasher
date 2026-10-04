import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dji_assistant.client import DJIAssistant
from dji_assistant.exceptions import UnexpectedAssistantState
from dji_assistant.models import FirmwareStage, FirmwareStatus


def control(name, kind="Text"):
    item = Mock()
    item.element_info.name = name
    item.element_info.control_type = kind
    item.is_enabled.return_value = True
    item.is_visible.return_value = True
    return item


class StartupTests(unittest.TestCase):
    def test_launch_uses_official_executable_via_windows_shell(self):
        path = Path(r"C:\DJI\DJI Assistant 2.exe")
        desktop = Mock()
        desktop.windows.side_effect = [[], [control("Assistant")]]
        with patch("dji_assistant.client.Path.resolve", return_value=path), patch(
            "dji_assistant.client.Path.is_file", return_value=True
        ), patch("dji_assistant.client.Desktop", return_value=desktop), patch(
            "dji_assistant.client.os.startfile"
        ) as start, patch.object(DJIAssistant, "connect") as connect:
            self.assertIs(DJIAssistant.launch(path), connect.return_value)
        start.assert_called_once_with(str(path), cwd=str(path.parent))

    def test_existing_window_is_reused(self):
        with patch("dji_assistant.client.Path.resolve", return_value=Path("DJI.exe")), patch(
            "dji_assistant.client.Path.is_file", return_value=True
        ), patch("dji_assistant.client.Desktop") as desktop, patch(
            "dji_assistant.client.os.startfile"
        ) as start, patch.object(DJIAssistant, "connect"):
            desktop.return_value.windows.return_value = [control("Assistant")]
            DJIAssistant.launch("DJI.exe")
        start.assert_not_called()

    def test_card_invoked_once(self):
        session = Mock()
        card = control("Matrice 4T", "Hyperlink")
        session.window.descendants.side_effect = [
            [card], [card, control("Current"), control("V17.02.0501")],
        ]
        client = DJIAssistant(session)
        with patch("dji_assistant.client.time.sleep"), patch.object(
            client.firmware, "current", return_value="17.02.0501"
        ):
            client.open_device("Matrice 4T")
        card.invoke.assert_called_once_with()

    def test_ambiguous_card_denied(self):
        session = Mock()
        cards = [control("Matrice 4T"), control("Matrice 4T")]
        session.window.descendants.return_value = cards
        with self.assertRaises(UnexpectedAssistantState):
            DJIAssistant(session).open_device("Matrice 4T")
        for card in cards:
            card.invoke.assert_not_called()

    def test_missing_uia_card_reports_accessibility_not_disconnection(self):
        session = Mock()
        session.window.descendants.return_value = [control("DJI ASSISTANT 2", "Image")]
        with patch("dji_assistant.client.time.monotonic", side_effect=[0, 0, 31]), patch(
            "dji_assistant.client.time.sleep"
        ), patch.object(DJIAssistant, "_raw_device_cards", return_value=[]):
            with self.assertRaisesRegex(UnexpectedAssistantState, "exposed through UIA"):
                DJIAssistant(session).open_device("Matrice 4T")

    def test_raw_card_clicked_once_and_current_readiness_waited(self):
        session = Mock()
        card = control("Matrice 4T")
        home = [control("DJI ASSISTANT 2", "Image")]
        page = [control("Matrice 4T", "Hyperlink"), control("Current")]
        session.window.descendants.side_effect = [home, page, page]
        client = DJIAssistant(session)
        with patch.object(client, "_raw_device_cards", return_value=[card]), patch.object(
            client, "_click_device_card"
        ) as click, patch.object(client.firmware, "current", side_effect=[
            UnexpectedAssistantState("Current label has invalid version."), "17.02.0501"
        ]), patch("dji_assistant.client.time.sleep"):
            self.assertIs(client.open_device("Matrice 4T"), client)
        click.assert_called_once_with(card)
        card.invoke.assert_not_called()

    def test_flysafe_requires_separate_authorization(self):
        client = DJIAssistant(Mock())
        with self.assertRaises(ValueError):
            client.confirm_flysafe()
        client._session.window_spec.child_window.assert_not_called()

    def test_startup_terms_require_user_acceptance(self):
        session = Mock()
        agree = control("Agree", "Button")
        session.window.descendants.return_value = [
            control("DJI ASSISTANT 2", "Image"), agree,
            control("Waiting for Backend to boot up ..."),
        ]
        with self.assertRaisesRegex(UnexpectedAssistantState, "Terms of Use"):
            DJIAssistant(session).open_device("Matrice 4T")
        agree.invoke.assert_not_called()

    def test_backend_timeout_has_specific_reason(self):
        session = Mock()
        session.window.descendants.return_value = [
            control("DJI ASSISTANT 2", "Image"),
            control("Waiting for Backend to boot up ..."),
        ]
        with patch("dji_assistant.client.time.monotonic", side_effect=[0, 0, 31]), patch(
            "dji_assistant.client.time.sleep"
        ), patch.object(DJIAssistant, "_raw_device_cards") as raw:
            with self.assertRaisesRegex(UnexpectedAssistantState, "backend"):
                DJIAssistant(session).open_device("Matrice 4T")
        raw.assert_not_called()

    def test_restored_offline_page_navigates_to_firmware_once(self):
        session = Mock()
        offline = [control("Matrice 4T", "Hyperlink"), control("Local version:")]
        firmware = [control("Matrice 4T", "Hyperlink"), control("Current")]
        session.window.descendants.side_effect = [offline, offline, firmware]
        client = DJIAssistant(session)
        with patch.object(client.firmware, "open") as navigate, patch.object(
            client.firmware, "current", return_value="17.00.0001"
        ), patch("dji_assistant.client.time.sleep"):
            self.assertIs(client.open_device("Matrice 4T"), client)
        navigate.assert_called_once_with()

    def test_raw_card_covered_by_another_window_is_not_clicked(self):
        session = Mock()
        card = control("Matrice 4T")
        from pywinauto.win32structures import RECT
        card.rectangle.return_value = RECT(20, 20, 120, 40)
        session.window.rectangle.return_value = RECT(0, 0, 500, 500)
        session.window.handle = 1
        with patch("dji_assistant.client.win32gui.WindowFromPoint", return_value=2), patch(
            "dji_assistant.client.win32gui.GetAncestor", return_value=2
        ):
            with self.assertRaisesRegex(UnexpectedAssistantState, "covered"):
                DJIAssistant(session)._click_device_card(card)
        card.click_input.assert_not_called()

    def test_quit_existing_prompt_confirms_scoped_yes_once(self):
        session = Mock()
        prompt = control("Quit Now?")
        yes = control(" Yes ", "Button")
        prompt.parent.return_value.descendants.return_value = [yes]
        session.window.descendants.return_value = [prompt]
        client = DJIAssistant(session)
        with patch.object(client.firmware, "status", return_value=FirmwareStatus(
            FirmwareStage.IDLE
        )), patch("dji_assistant.client.Desktop") as desktop:
            desktop.return_value.windows.side_effect = [[session.window], []]
            client.quit_application()
        yes.invoke.assert_called_once_with()
        session.window.close.assert_not_called()
        session.close.assert_called_once_with()

    def test_quit_denied_during_firmware_write(self):
        session = Mock()
        client = DJIAssistant(session)
        with patch.object(client.firmware, "status", return_value=FirmwareStatus(
            FirmwareStage.UPDATING
        )):
            with self.assertRaises(UnexpectedAssistantState):
                client.quit_application()
        session.window.close.assert_not_called()
        session.window.descendants.assert_not_called()


if __name__ == "__main__":
    unittest.main()

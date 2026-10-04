import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import win32con
from pywinauto.win32structures import RECT

from dji_assistant.backend.uia.input import addressed_click
from dji_assistant.exceptions import UnexpectedAssistantState


class AddressedInputTests(unittest.TestCase):
    def exercise(self, *, handles=(20,), owner=10, process=100, bounds=None, error=None):
        window = Mock(handle=10)
        target = Mock()
        target.rectangle.return_value = bounds or RECT(30, 40, 130, 60)
        target.is_enabled.return_value = True
        target.is_visible.return_value = True
        with ExitStack() as stack:
            prefix = "dji_assistant.backend.uia.input."
            stack.enter_context(patch(
                prefix + "win32gui.EnumChildWindows",
                side_effect=lambda handle, callback, param: [
                    callback(child, param) for child in handles
                ],
            ))
            stack.enter_context(patch(prefix + "win32gui.GetClassName", return_value="Chrome_RenderWidgetHostHWND"))
            stack.enter_context(patch(prefix + "win32gui.IsWindowVisible", return_value=True))
            stack.enter_context(patch(prefix + "win32gui.GetAncestor", return_value=owner))
            stack.enter_context(patch(
                prefix + "win32process.GetWindowThreadProcessId",
                side_effect=lambda handle: (1, 100 if handle == 10 else process),
            ))
            stack.enter_context(patch(prefix + "win32gui.GetWindowRect", return_value=(0, 0, 500, 500)))
            stack.enter_context(patch(prefix + "win32gui.ScreenToClient", return_value=(80, 50)))
            send = stack.enter_context(patch(prefix + "win32gui.SendMessageTimeout", side_effect=error))
            try:
                addressed_click(window, target)
            finally:
                target.click_input.assert_not_called()
                window.set_focus.assert_not_called()
            return send

    def test_sends_one_pair_to_renderer_without_global_input(self):
        send = self.exercise()
        self.assertEqual(send.call_count, 3)
        self.assertEqual(
            [call.args[1] for call in send.call_args_list],
            [win32con.WM_MOUSEMOVE, win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP],
        )
        self.assertTrue(all(call.args[0] == 20 for call in send.call_args_list))

    def test_ambiguous_foreign_and_outside_targets_are_rejected(self):
        for options in (
            {"handles": (20, 21)}, {"owner": 99}, {"process": 999},
            {"bounds": RECT(30, 40, 600, 60)},
        ):
            with self.subTest(options=options), self.assertRaises(UnexpectedAssistantState):
                self.exercise(**options)

    def test_send_error_never_retries(self):
        import win32gui
        error = win32gui.error(5, "SendMessageTimeout", "denied")
        with self.assertRaisesRegex(UnexpectedAssistantState, "No retry"):
            self.exercise(error=error)

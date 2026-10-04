import json
import socket
import struct
import unittest
from unittest.mock import Mock, patch

from dji_assistant import IsolatedAssistant
from dji_assistant._isolated_worker import (
    _dispatch, _initialize, _IsolatedOfflinePage, _assert_reusable_desktop,
)
from dji_assistant.exceptions import UnexpectedAssistantState
from dji_assistant.isolated import _receive, _send
from dji_assistant.models import FirmwareStage, FirmwareStatus, FirmwareVersion


class ProtocolTests(unittest.TestCase):
    def test_outbound_oversize_and_nonfinite_payload_never_sent(self):
        for message in ({"text": "x" * 65536}, {"timeout": float("nan")}):
            with self.subTest(message_type=next(iter(message))):
                connection = Mock()
                with self.assertRaises(ValueError):
                    _send(connection, message)
                connection.sendall.assert_not_called()

    def test_roundtrip_and_fragmented_reads(self):
        first, second = socket.socketpair()
        try:
            _send(first, {"command": "current", "arguments": {}})
            self.assertEqual(_receive(second)["command"], "current")
        finally:
            first.close()
            second.close()
        payload = json.dumps({"ok": True}).encode()
        message = struct.pack("!I", len(payload)) + payload
        connection = Mock()
        connection.recv.side_effect = [bytes([byte]) for byte in message]
        self.assertTrue(_receive(connection)["ok"])

    def test_bad_size_disconnect_and_shape(self):
        for payload in (struct.pack("!I", 65537), struct.pack("!I", 0), b""):
            with self.subTest(payload=payload), self.assertRaises((ValueError, ConnectionError)):
                connection = Mock()
                connection.recv.return_value = payload
                _receive(connection)
        with self.assertRaises(ValueError):
            connection = Mock()
            connection.recv.side_effect = [struct.pack("!I", 2), b"[]"]
            _receive(connection)


class ControllerTests(unittest.TestCase):
    def controller(self):
        return IsolatedAssistant(123, "DjiSdk_abc", Mock(), Mock())

    def test_launch_reuses_same_desktop_name(self):
        with patch("dji_assistant.isolated.Path") as path, patch(
            "dji_assistant.isolated._USER32",
        ) as user32, patch.object(IsolatedAssistant, "_start") as start:
            path.return_value.resolve.return_value.suffix = ".exe"
            IsolatedAssistant.launch("DJI.exe")
            IsolatedAssistant.launch("DJI.exe")
        self.assertEqual(
            [call.args[0] for call in user32.CreateDesktopW.call_args_list],
            ["DjiSdk_IsolatedAssistant", "DjiSdk_IsolatedAssistant"],
        )
        self.assertEqual(start.call_count, 2)

    def test_wrong_handshake_token_releases_resources_without_initialization(self):
        process, thread, connection = Mock(), Mock(), Mock()
        with patch("dji_assistant.isolated.socket.socket") as socket_factory, patch(
            "dji_assistant.isolated._spawn", return_value=(process, thread, 1, 2),
        ), patch("dji_assistant.isolated._receive", return_value={
            "desktop": "DjiSdk_abc", "token": "not-the-secret",
        }), patch("dji_assistant.isolated._USER32") as user32, patch.object(
            IsolatedAssistant, "_call",
        ) as call:
            socket_factory.return_value.__enter__.return_value.accept.return_value = (connection, None)
            with self.assertRaisesRegex(UnexpectedAssistantState, "authentication failed"):
                IsolatedAssistant._start(123, "DjiSdk_abc", "Assistant", 10, "DJI.exe")
        call.assert_not_called()
        connection.close.assert_called_once()
        process.Close.assert_called_once()
        thread.Close.assert_called_once()
        user32.CloseDesktop.assert_called_once_with(123)

    def test_malformed_envelope_poisons_channel(self):
        controller = self.controller()
        with patch("dji_assistant.isolated._send") as send, patch(
            "dji_assistant.isolated._receive", return_value={"ok": "yes"},
        ):
            with self.assertRaisesRegex(UnexpectedAssistantState, "outcome unknown"):
                controller.current()
            with self.assertRaisesRegex(UnexpectedAssistantState, "No retry"):
                controller.current()
        send.assert_called_once()

    def test_current_rejects_nonstring_readback(self):
        controller = self.controller()
        with patch.object(controller, "_call", return_value=None):
            with self.assertRaisesRegex(UnexpectedAssistantState, "Invalid"):
                controller.current()

    def test_nonzero_worker_exit_reported_after_handle_cleanup(self):
        controller = self.controller()
        with patch("dji_assistant.isolated._USER32") as user32, patch(
            "dji_assistant.isolated.win32event.WaitForSingleObject", return_value=0,
        ), patch(
            "dji_assistant.isolated.win32process.GetExitCodeProcess", return_value=1,
        ):
            with self.assertRaisesRegex(UnexpectedAssistantState, "exited with code 1"):
                controller.close()
        controller._process.Close.assert_called_once()
        user32.CloseDesktop.assert_called_once_with(123)

    def test_unknown_transport_outcome_poisoned_without_retry(self):
        controller = self.controller()
        with patch("dji_assistant.isolated._send") as send, patch(
            "dji_assistant.isolated._receive", side_effect=TimeoutError("late"),
        ):
            with self.assertRaisesRegex(UnexpectedAssistantState, "outcome unknown"):
                controller.current()
            with self.assertRaisesRegex(UnexpectedAssistantState, "No retry"):
                controller.current()
        send.assert_called_once()

    def test_remote_error_does_not_poison_channel(self):
        controller = self.controller()
        with patch("dji_assistant.isolated._send"), patch(
            "dji_assistant.isolated._receive",
            side_effect=[{"ok": False, "error": "not ready"},
                         {"ok": True, "result": "17.02.0501"}],
        ):
            with self.assertRaisesRegex(UnexpectedAssistantState, "not ready"):
                controller.current()
            self.assertEqual(controller.current(), FirmwareVersion.parse("17.02.0501"))

    def test_status_uses_typed_model(self):
        controller = self.controller()
        with patch.object(controller, "_call", return_value={
            "stage": "idle", "version": None, "percent": None, "error_code": None,
        }):
            self.assertEqual(controller.status(), FirmwareStatus(FirmwareStage.IDLE))

    def test_close_is_idempotent_and_never_quits_application(self):
        controller = self.controller()
        with patch("dji_assistant.isolated._USER32") as user32, patch(
            "dji_assistant.isolated.win32event.WaitForSingleObject", return_value=0,
        ), patch(
            "dji_assistant.isolated.win32process.GetExitCodeProcess", return_value=0,
        ):
            controller.close()
            controller.close()
        controller._connection.close.assert_called_once()
        controller._process.Close.assert_called_once()
        user32.CloseDesktop.assert_called_once_with(123)

    def test_close_timeout_releases_handles_but_reports_unfinished_worker(self):
        controller = self.controller()
        with patch("dji_assistant.isolated._USER32"), patch(
            "dji_assistant.isolated.win32event.WaitForSingleObject", return_value=258,
        ):
            with self.assertRaisesRegex(UnexpectedAssistantState, "still finishing"):
                controller.close()
        controller._process.Close.assert_called_once()

    def test_invalid_response_shape_is_not_success(self):
        controller = self.controller()
        with patch.object(controller, "_call", return_value={"stage": "idle"}):
            with self.assertRaisesRegex(UnexpectedAssistantState, "Invalid"):
                controller.status()

    def test_invalid_timeout_and_recovery_name_rejected_before_win32(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                IsolatedAssistant.launch("missing.exe", timeout=timeout)
        for name in ("Default", "DjiSdk_abc\\Default", "DjiSdk_"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                IsolatedAssistant.attach(name)


class WorkerTests(unittest.TestCase):
    def test_reuse_reports_window_lookup_failure_outside_native_callback(self):
        import win32process

        error = win32process.error(5, "GetWindowThreadProcessId", "denied")
        with patch("dji_assistant._isolated_worker._USER32") as user32, patch(
            "dji_assistant._isolated_worker._desktop_name", return_value="DjiSdk_IsolatedAssistant",
        ), patch(
            "dji_assistant._isolated_worker.win32process.GetWindowThreadProcessId",
            side_effect=error,
        ):
            user32.EnumDesktopWindows.side_effect = lambda desktop, callback, data: callback(42, data)
            with self.assertRaisesRegex(UnexpectedAssistantState, "Could not verify") as raised:
                _assert_reusable_desktop("DjiSdk_IsolatedAssistant")
        self.assertIs(raised.exception.__cause__, error)

    def test_reuse_checks_foreign_windows_before_spawning(self):
        with patch("dji_assistant._isolated_worker._dji_processes", return_value=[]), patch(
            "dji_assistant._isolated_worker._assert_reusable_desktop",
            side_effect=UnexpectedAssistantState("other processes"),
        ), patch("dji_assistant._isolated_worker._spawn") as spawn:
            with self.assertRaisesRegex(UnexpectedAssistantState, "other processes"):
                _initialize("DjiSdk_IsolatedAssistant", "Assistant", "DJI.exe", 1)
        spawn.assert_not_called()

    def test_reuse_rejects_foreign_hidden_window(self):
        with patch("dji_assistant._isolated_worker._USER32") as user32, patch(
            "dji_assistant._isolated_worker._desktop_name", return_value="DjiSdk_IsolatedAssistant",
        ), patch(
            "dji_assistant._isolated_worker.win32process.GetWindowThreadProcessId",
            return_value=(1, 987654),
        ), patch("dji_assistant._isolated_worker.os.getpid", return_value=123):
            user32.EnumDesktopWindows.side_effect = lambda desktop, callback, data: callback(42, data)
            with self.assertRaisesRegex(UnexpectedAssistantState, "other processes"):
                _assert_reusable_desktop("DjiSdk_IsolatedAssistant")

    def test_reuse_rejects_wrong_worker_desktop(self):
        with patch("dji_assistant._isolated_worker._USER32") as user32, patch(
            "dji_assistant._isolated_worker._desktop_name", return_value="Default",
        ):
            with self.assertRaisesRegex(UnexpectedAssistantState, "not on"):
                _assert_reusable_desktop("DjiSdk_IsolatedAssistant")
        user32.EnumDesktopWindows.assert_not_called()

    def test_flysafe_dismissal_requires_idle(self):
        dji = Mock()
        dji.firmware.status.return_value = FirmwareStatus(FirmwareStage.UPDATING)
        with patch("dji_assistant._isolated_worker._window_desktop", return_value="DjiSdk_abc"):
            with self.assertRaisesRegex(UnexpectedAssistantState, "requires idle"):
                _dispatch(dji, "DjiSdk_abc", "ignore_flysafe", {})
        dji.flysafe_prompt.assert_not_called()
        dji._session.window_spec.child_window.assert_not_called()

    def test_selection_waits_for_current_without_repeating_file_action(self):
        dji = Mock()
        version = FirmwareVersion.parse("17.02.0501")
        dji.firmware.current.side_effect = [
            version, UnexpectedAssistantState("Current not rendered"), version,
        ]
        dji.offline.select_package.return_value = "package.zip"
        with patch("dji_assistant._isolated_worker._window_desktop", return_value="DjiSdk_abc"), patch(
            "dji_assistant._isolated_worker.time.sleep",
        ):
            self.assertEqual(
                _dispatch(dji, "DjiSdk_abc", "select_package", {"path": "package.zip"}),
                "package.zip",
            )
        dji.offline.select_package.assert_called_once_with(path="package.zip")
        dji.firmware.open.assert_called_once_with()

    def test_changed_current_is_rejected_without_retry(self):
        dji = Mock()
        dji.firmware.current.side_effect = [
            FirmwareVersion.parse("17.02.0501"), FirmwareVersion.parse("17.00.0001"),
        ]
        with patch("dji_assistant._isolated_worker._window_desktop", return_value="DjiSdk_abc"):
            with self.assertRaisesRegex(UnexpectedAssistantState, "Current changed"):
                _dispatch(dji, "DjiSdk_abc", "select_package", {"path": "package.zip"})
        dji.offline.select_package.assert_called_once()

    def test_current_readiness_timeout_preserves_cause_and_no_retry(self):
        dji = Mock()
        cause = UnexpectedAssistantState("missing Current")
        dji.firmware.current.side_effect = [FirmwareVersion.parse("17.02.0501"), cause]
        with patch("dji_assistant._isolated_worker._window_desktop", return_value="DjiSdk_abc"), patch(
            "dji_assistant._isolated_worker.time.monotonic", side_effect=[0, 1, 11],
        ), patch("dji_assistant._isolated_worker.time.sleep"):
            with self.assertRaisesRegex(UnexpectedAssistantState, "Do not repeat") as error:
                _dispatch(dji, "DjiSdk_abc", "select_package", {"path": "package.zip"})
        self.assertIs(error.exception.__cause__, cause)
        dji.offline.select_package.assert_called_once()

    def test_existing_dji_processes_prevent_launch(self):
        with patch("dji_assistant._isolated_worker._dji_processes", return_value=[42]), patch(
            "dji_assistant._isolated_worker._spawn",
        ) as spawn:
            with self.assertRaisesRegex(UnexpectedAssistantState, "already running"):
                _initialize("DjiSdk_abc", "Assistant", "DJI.exe", 1)
        spawn.assert_not_called()

    def test_write_commands_are_not_exposed(self):
        dji = Mock()
        with patch("dji_assistant._isolated_worker._window_desktop", return_value="DjiSdk_abc"):
            for command in ("upgrade", "downgrade", "refresh", "offline-upgrade", "eval"):
                with self.subTest(command=command), self.assertRaises(ValueError):
                    _dispatch(dji, "DjiSdk_abc", command, {})
        self.assertEqual(dji.firmware.method_calls, [])
        self.assertEqual(dji.offline.method_calls, [])

    def test_desktop_escape_rejected_before_navigation(self):
        dji = Mock()
        with patch("dji_assistant._isolated_worker._window_desktop", return_value="Default"):
            with self.assertRaisesRegex(UnexpectedAssistantState, "escaped"):
                _dispatch(dji, "DjiSdk_abc", "open_device", {"name": "Matrice 4T"})
        dji.open_device.assert_not_called()

    def test_picker_escape_rejected_before_submission(self):
        page = _IsolatedOfflinePage(Mock())
        with patch("dji_assistant._isolated_worker._window_desktop",
                   side_effect=["Default", "DjiSdk_abc"]), patch(
            "dji_assistant.pages.offline.OfflinePage._submit_package",
        ) as submit:
            with self.assertRaisesRegex(UnexpectedAssistantState, "picker escaped"):
                page._submit_package(Mock(), Mock(), 100)
        submit.assert_not_called()

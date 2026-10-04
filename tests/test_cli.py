import unittest
from unittest.mock import patch

from dji_assistant.cli import main
from dji_assistant.exceptions import FirmwareOutcomeUnknown, UnexpectedAssistantState
from dji_assistant.models import FirmwareVersion


class CliTests(unittest.TestCase):
    def test_no_physical_input_option_propagates_to_session(self):
        with patch("sys.argv", ["dji-assistant", "--no-physical-input", "current"]), patch(
            "dji_assistant.cli.DJIAssistant"
        ) as assistant, patch("dji_assistant.cli.console"):
            self.assertEqual(main(), 0)
        self.assertFalse(assistant.connect.call_args.kwargs["allow_physical_input"])

    def test_missing_authorization_never_connects(self):
        for command in (
            ["refresh"], ["upgrade", "17.01.0516"],
            ["downgrade", "17.00.0001"],
            ["offline-upgrade", "17.02.0501", "package.zip"],
        ):
            argv = ["dji-assistant", *command, "--expected-device", "Matrice 4T",
                    "--expected-current", "17.01.0516"]
            with self.subTest(command=command), patch("sys.argv", argv), patch(
                "dji_assistant.cli.DJIAssistant"
            ) as assistant, patch("argparse.ArgumentParser.error", side_effect=SystemExit(2)):
                with self.assertRaises(SystemExit):
                    main()
                assistant.connect.assert_not_called()

    def test_current_command(self):
        with patch("sys.argv", ["dji-assistant", "current"]), patch(
            "dji_assistant.cli.DJIAssistant"
        ) as assistant, patch("dji_assistant.cli.console") as console:
            client = assistant.connect.return_value.__enter__.return_value
            client.firmware.current.return_value = FirmwareVersion.parse("17.02.0501")
            self.assertEqual(main(), 0)
            console.print.assert_called_once_with("17.02.0501")

    def test_unknown_outcome_returns_failure_without_retry(self):
        argv = ["dji-assistant", "refresh", "--expected-device", "Matrice 4T",
                "--expected-current", "17.01.0516", "--yes"]
        with patch("sys.argv", argv), patch(
            "dji_assistant.cli.DJIAssistant"
        ) as assistant, patch("dji_assistant.cli.console"):
            client = assistant.connect.return_value.__enter__.return_value
            client.firmware.refresh.side_effect = FirmwareOutcomeUnknown("Do not retry")
            self.assertEqual(main(), 1)
            client.firmware.refresh.assert_called_once()


class IsolatedCliTests(unittest.TestCase):
    def execute(self, arguments, configure=None):
        with patch("sys.argv", [
            "dji-assistant", "--window-title", "Enterprise", "isolated", *arguments,
        ]), patch("dji_assistant.cli.IsolatedAssistant") as factory, patch(
            "dji_assistant.cli.DJIAssistant",
        ) as ordinary, patch("dji_assistant.cli.console") as console:
            if configure:
                configure(factory)
            result = main()
        ordinary.connect.assert_not_called()
        ordinary.launch.assert_not_called()
        return result, factory, console

    def test_launch_prints_recovery_desktop_and_disconnects_without_quit(self):
        result, factory, console = self.execute(["launch", "DJI.exe", "--timeout", "45"])
        self.assertEqual(result, 0)
        factory.launch.assert_called_once_with("DJI.exe", title="Enterprise", timeout=45)
        factory.attach.assert_not_called()
        client = factory.launch.return_value
        client.close.assert_called_once()
        client.quit_application.assert_not_called()
        self.assertIn("Connected desktop:", console.print.call_args_list[0].args[0])

    def test_commands_attach_and_route_to_only_requested_action(self):
        cases = (
            (["attach"], None, (), {}),
            (["current"], "current", (), {}),
            (["status"], "status", (), {}),
            (["ignore-flysafe"], "ignore_flysafe", (), {}),
            (["open-device", "Matrice 4T"], "open_device", ("Matrice 4T",), {"timeout": 30}),
            (["offline-select", "package.zip"], "select_package", ("package.zip",), {"timeout": 120}),
            (["quit"], "quit_application", (), {"timeout": 20}),
        )
        for arguments, method, positional, keywords in cases:
            with self.subTest(command=arguments[0]):
                result, factory, _ = self.execute(arguments)
                self.assertEqual(result, 0)
                factory.launch.assert_not_called()
                factory.attach.assert_called_once_with(
                    "DjiSdk_IsolatedAssistant", title="Enterprise",
                    timeout={"offline-select": 120, "quit": 20}.get(arguments[0], 30),
                )
                client = factory.attach.return_value
                if method:
                    getattr(client, method).assert_called_once_with(*positional, **keywords)
                client.close.assert_called_once()
                client.firmware.assert_not_called()
                if method != "quit_application":
                    client.quit_application.assert_not_called()

    def test_custom_recovery_desktop_and_timeout(self):
        result, factory, _ = self.execute([
            "current", "--desktop", "DjiSdk_old", "--timeout", "12",
        ])
        self.assertEqual(result, 0)
        factory.attach.assert_called_once_with("DjiSdk_old", title="Enterprise", timeout=12)

    def test_action_error_closes_worker_without_retry_or_quit(self):
        def configure(factory):
            factory.attach.return_value.select_package.side_effect = UnexpectedAssistantState("unknown")

        result, factory, console = self.execute(["offline-select", "package.zip"], configure)
        self.assertEqual(result, 1)
        client = factory.attach.return_value
        client.select_package.assert_called_once()
        client.close.assert_called_once()
        client.quit_application.assert_not_called()
        self.assertIn("unknown", console.print.call_args.args[0])

    def test_cleanup_error_preserves_original_error_in_output(self):
        def configure(factory):
            client = factory.attach.return_value
            client.current.side_effect = UnexpectedAssistantState("original failure")
            client.close.side_effect = UnexpectedAssistantState("worker still finishing")

        result, _, console = self.execute(["current"], configure)
        self.assertEqual(result, 1)
        messages = [call.args[0] for call in console.print.call_args_list]
        self.assertIn("original failure", messages[0])
        self.assertIn("worker still finishing", messages[1])

    def test_attach_failure_does_not_launch_or_retry(self):
        def configure(factory):
            factory.attach.side_effect = UnexpectedAssistantState("no application")

        result, factory, _ = self.execute(["attach"], configure)
        self.assertEqual(result, 1)
        factory.attach.assert_called_once()
        factory.launch.assert_not_called()

    def test_invalid_options_and_write_commands_never_start_worker(self):
        arguments = (
            ["isolated", "refresh"],
            ["isolated", "upgrade", "17.02.0501"],
            ["isolated", "current", "--timeout", "0"],
            ["isolated", "launch", "DJI.exe", "--timeout", "nan"],
            ["isolated", "status", "--timeout", "inf"],
            ["--addressed-input", "isolated", "current"],
            ["--no-physical-input", "isolated", "current"],
        )
        for command in arguments:
            with self.subTest(command=command), patch("sys.argv", ["dji-assistant", *command]), patch(
                "dji_assistant.cli.IsolatedAssistant",
            ) as factory, patch("argparse.ArgumentParser.error", side_effect=SystemExit(2)):
                with self.assertRaises(SystemExit):
                    main()
                factory.launch.assert_not_called()
                factory.attach.assert_not_called()


if __name__ == "__main__":
    unittest.main()

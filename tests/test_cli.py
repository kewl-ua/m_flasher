import unittest
from unittest.mock import patch

from dji_assistant.cli import main
from dji_assistant.exceptions import FirmwareOutcomeUnknown
from dji_assistant.models import FirmwareVersion


class CliTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

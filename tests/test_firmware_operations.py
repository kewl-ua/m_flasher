import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

from dji_assistant.exceptions import (
    FirmwareOperationFailed, FirmwareOutcomeUnknown, UIElementNotFound,
    UnexpectedAssistantState,
)
from dji_assistant.models import FirmwareAction, FirmwareStage, FirmwareVersion
from dji_assistant.pages._firmware_operations import WRITE_LOCK, FirmwareOperations
from dji_assistant.pages._firmware_status import (
    CONFIRMATION_ITEMS, CONFIRMATION_TEXT, parse_status,
)
from dji_assistant.pages._firmware_tree import FirmwareNode, _walk
from dji_assistant.pages.offline import OfflinePage, package_target, validate_package
from test_firmware import text, tree

CURRENT = "17.01.0516"
TARGET = "17.00.0001"


def device_tree(current=CURRENT):
    base = tree(label="V" + current)
    return FirmwareNode("Window", "", (
        FirmwareNode("Hyperlink", "Matrice 4T"), *base.children,
    ))


def stage(name, version=TARGET, percent="100", extra=()):
    children = [text(name)]
    if version:
        children.append(text("V" + version))
    if percent:
        children.extend((text(percent), text("%")))
    children.extend(extra)
    if name == "Update Complete!":
        children.append(FirmwareNode("Button", "Back"))
    return FirmwareNode("Window", "", tuple(children))


def snapshot(root, buttons):
    controls = {}
    for node in _walk(root):
        if node.control_type == "Button":
            button = buttons.setdefault(node.name, Mock())
            button.is_enabled.return_value = True
            button.is_visible.return_value = True
            controls[id(node)] = button
    return root, controls


def page_for(roots):
    buttons = {}
    page = Mock()
    snapshots = [snapshot(root, buttons) for root in roots]
    page._capture.side_effect = snapshots
    return page, buttons


def completed_tree(version=TARGET):
    return FirmwareNode("Window", "", (
        FirmwareNode("Hyperlink", "Matrice 4T"),
        text("Current"), text(":"), text("V" + version),
    ))


class OperationTests(unittest.TestCase):
    def test_completion_waits_for_rendered_current_without_new_write(self):
        incomplete = FirmwareNode("Window", "", (
            FirmwareNode("Hyperlink", "Matrice 4T"), text("Current"), text(":"),
            text("V"),
        ))
        page, buttons = page_for([incomplete, completed_tree()])
        with patch("dji_assistant.pages._firmware_operations.time.sleep"):
            result = FirmwareOperations(page)._verify(
                FirmwareVersion.parse(TARGET), FirmwareVersion.parse(CURRENT),
                "offline", "Matrice 4T", float("inf"), 0.001,
            )
        self.assertEqual(str(result.installed), TARGET)
        self.assertEqual(buttons, {})

    def test_confirmation_dates_are_not_error_codes(self):
        root = FirmwareNode("Window", "", (
            text(CONFIRMATION_TEXT), text("2026-04-29"), text("2026-02-13"),
        ))
        status = parse_status(root)
        self.assertIs(status.stage, FirmwareStage.CONFIRMATION)
        self.assertIsNone(status.error_code)

    def run_operation(self, page, **options):
        defaults = dict(expected_device="Matrice 4T", expected_current=CURRENT,
                        confirm=True, timeout=10, poll_interval=0.001)
        defaults.update(options)
        return FirmwareOperations(page).online(FirmwareAction.DOWNGRADE, TARGET, **defaults)

    def test_full_sequence_confirms_once_and_verifies_current(self):
        initial = device_tree()
        confirmation = FirmwareNode("Window", "", (
            *initial.children, text(CONFIRMATION_TEXT),
            *(text(item) for item in CONFIRMATION_ITEMS),
            FirmwareNode("Button", "Start Update"),
        ))
        page, buttons = page_for([
            initial, confirmation, stage("Downloading", percent="10"),
            stage("Transmitting", version="", percent="0"),
            stage("Updating", percent="50"), stage("Update Complete!"),
            completed_tree(), completed_tree(),
        ])
        with patch("dji_assistant.pages._firmware_operations.time.sleep"):
            result = self.run_operation(page)
        self.assertEqual(str(result.installed), TARGET)
        buttons["Downgrade"].invoke.assert_called_once_with()
        buttons["Start Update"].invoke.assert_called_once_with()
        buttons["Back"].invoke.assert_called_once_with()

    def test_already_started_does_not_repeat_confirmation(self):
        page, buttons = page_for([
            device_tree(), stage("Transmitting", version="", percent="10"),
            stage("Updating", percent="99"), stage("Update Complete!"),
            completed_tree(), completed_tree(),
        ])
        with patch("dji_assistant.pages._firmware_operations.time.sleep"):
            self.run_operation(page)
        self.assertNotIn("Start Update", buttons)
        buttons["Downgrade"].invoke.assert_called_once_with()

    def test_failure_has_code_and_never_retries(self):
        page, buttons = page_for([
            device_tree(), stage("Update failed.", version="", percent="0",
                                 extra=(text("2-251-1"),)),
        ])
        with self.assertRaises(FirmwareOperationFailed) as raised:
            self.run_operation(page)
        self.assertEqual(raised.exception.code, "2-251-1")
        buttons["Downgrade"].invoke.assert_called_once_with()

    def test_wrong_target_read_error_and_invoke_error_are_unknown(self):
        for error in ("target", "read", "invoke"):
            page, buttons = page_for([device_tree(), stage("Updating", version="99.00.0000")])
            if error == "read":
                first = snapshot(device_tree(), buttons)
                page._capture.side_effect = [first, RuntimeError("UIA disconnected")]
            if error == "invoke":
                buttons["Downgrade"].invoke.side_effect = RuntimeError("Invoke failed")
            with self.subTest(error=error), self.assertRaises(FirmwareOutcomeUnknown):
                self.run_operation(page)
            buttons["Downgrade"].invoke.assert_called_once_with()

    def test_confirmation_and_stage_regression_are_not_retried(self):
        for roots in (
            [stage("Updating", percent="50"), stage("Downloading", percent="2")],
            [stage("Updating", percent="50"),
             stage(CONFIRMATION_TEXT, version="", percent="")],
        ):
            page, buttons = page_for([device_tree(), *roots])
            with patch("dji_assistant.pages._firmware_operations.time.sleep"):
                with self.assertRaises(FirmwareOutcomeUnknown):
                    self.run_operation(page)
            buttons["Downgrade"].invoke.assert_called_once_with()

    def test_preconditions_do_not_invoke(self):
        for options in (
            dict(confirm=False), dict(expected_device="Wrong model"),
            dict(expected_current="16.01.0006"), dict(timeout=0),
            dict(poll_interval=float("nan")),
        ):
            page, buttons = page_for([device_tree()])
            with self.subTest(options=options), self.assertRaises(
                (ValueError, UnexpectedAssistantState)
            ):
                self.run_operation(page, **options)
            buttons["Downgrade"].invoke.assert_not_called()

    def test_concurrent_operation_denied(self):
        page, buttons = page_for([device_tree()])
        WRITE_LOCK.acquire()
        try:
            with self.assertRaises(UnexpectedAssistantState):
                self.run_operation(page)
        finally:
            WRITE_LOCK.release()
        buttons["Downgrade"].invoke.assert_not_called()

    def test_unknown_dialog_blocks_confirmation_before_start(self):
        initial = device_tree()
        confirmation = FirmwareNode("Window", "", (
            *initial.children, text(CONFIRMATION_TEXT),
            *(text(item) for item in CONFIRMATION_ITEMS),
            FirmwareNode("Button", "Start Update"), FirmwareNode("Button", "Confirm"),
        ))
        page, buttons = page_for([initial, confirmation])
        with self.assertRaises(FirmwareOutcomeUnknown):
            self.run_operation(page)
        buttons["Start Update"].invoke.assert_not_called()

    def test_disabled_wrong_action_and_missing_target(self):
        page, buttons = page_for([device_tree()])
        buttons["Downgrade"].is_enabled.return_value = False
        with self.assertRaises(UnexpectedAssistantState):
            self.run_operation(page)
        buttons["Downgrade"].invoke.assert_not_called()
        for target, action in ((TARGET, FirmwareAction.UPGRADE), ("99.00.0000", FirmwareAction.DOWNGRADE)):
            page, buttons = page_for([device_tree()])
            with self.assertRaises((UnexpectedAssistantState, UIElementNotFound, ValueError)):
                FirmwareOperations(page).online(
                    action, target, expected_device="Matrice 4T",
                    expected_current=CURRENT, confirm=True,
                )
            buttons["Downgrade"].invoke.assert_not_called()

    def test_timeout_never_retries(self):
        page, buttons = page_for([device_tree(), FirmwareNode("Window", "")])
        with patch("dji_assistant.pages._firmware_operations.time.monotonic",
                   side_effect=[0, 0, 0, 11, 11]), patch(
                       "dji_assistant.pages._firmware_operations.time.sleep"):
            with self.assertRaises(FirmwareOutcomeUnknown):
                self.run_operation(page)
        buttons["Downgrade"].invoke.assert_called_once_with()

    def test_completion_target_or_percent_mismatch(self):
        for root in (stage("Update Complete!", version=CURRENT),
                     stage("Update Complete!", percent="99")):
            page, buttons = page_for([device_tree(), root])
            with self.assertRaises(FirmwareOutcomeUnknown):
                self.run_operation(page)
            buttons["Back"].invoke.assert_not_called()

    def test_verification_reads_standalone_offline_current(self):
        target = FirmwareVersion.parse("17.02.0501")
        page, _ = page_for([completed_tree(str(target))])
        result = FirmwareOperations(page)._verify(
            target, FirmwareVersion.parse(CURRENT), "offline", "Matrice 4T", float("inf"), 1,
        )
        self.assertEqual(result.installed, target)

    def test_refresh_cannot_succeed_from_unchanged_current_alone(self):
        page, _ = page_for([stage("Updating", version=CURRENT), completed_tree(CURRENT)])
        with patch("dji_assistant.pages._firmware_operations.time.sleep"):
            with self.assertRaises(FirmwareOutcomeUnknown):
                FirmwareOperations(page).wait(
                    FirmwareVersion.parse(CURRENT), FirmwareVersion.parse(CURRENT),
                    "refresh", "Matrice 4T", float("inf"), 1, None,
                )

    def test_offline_confirmation_has_no_internet_or_current_label(self):
        field = FirmwareNode("Edit", "Click here to select firmware zip package...")
        start = FirmwareNode("Button", "Start Update")
        confirmation = FirmwareNode("Window", "", (
            FirmwareNode("Hyperlink", "Matrice 4T"), text(CONFIRMATION_TEXT),
            text("Device powered on with sufficient battery"), text("USB Connection"),
            field, start,
        ))
        page, buttons = page_for([
            confirmation, stage("Transmitting", version="", percent="5"),
            stage("Update Complete!", version="17.02.0501"),
            completed_tree("17.02.0501"), completed_tree("17.02.0501"),
        ])
        snapshots = page._capture.side_effect
        snapshots = list(snapshots)
        edit = Mock()
        edit.get_value.return_value = r"C:\firmware\package.zip"
        snapshots[0][1][id(field)] = edit
        page._capture.side_effect = snapshots
        operation = FirmwareOperations(page)
        operation.offline_package = Path(r"C:\firmware\package.zip")
        with patch("dji_assistant.pages._firmware_operations.time.sleep"):
            result = operation.wait(
                FirmwareVersion.parse("17.02.0501"), FirmwareVersion.parse(CURRENT),
                "offline", "Matrice 4T", float("inf"), 1, None,
            )
        self.assertEqual(str(result.installed), "17.02.0501")
        buttons["Start Update"].invoke.assert_called_once_with()

    def test_repeated_confirmation_never_invokes_start_twice(self):
        initial = device_tree()
        confirmation = FirmwareNode("Window", "", (
            *initial.children, text(CONFIRMATION_TEXT),
            *(text(item) for item in CONFIRMATION_ITEMS),
            FirmwareNode("Button", "Start Update"),
        ))
        page, buttons = page_for([initial, confirmation, confirmation])
        with patch("dji_assistant.pages._firmware_operations.time.sleep"):
            with self.assertRaises(FirmwareOutcomeUnknown):
                self.run_operation(page)
        buttons["Start Update"].invoke.assert_called_once_with()

    def test_callback_failure_after_invoke_is_unknown(self):
        page, buttons = page_for([device_tree(), stage("Updating")])
        callback = Mock(side_effect=RuntimeError("consumer callback failed"))
        with self.assertRaises(FirmwareOutcomeUnknown):
            self.run_operation(page, on_status=callback)
        buttons["Downgrade"].invoke.assert_called_once_with()

    def test_expected_current_mismatch_after_completion_is_unknown(self):
        page, buttons = page_for([
            device_tree(), stage("Update Complete!"),
            completed_tree(CURRENT), completed_tree(CURRENT),
        ])
        with self.assertRaises(FirmwareOutcomeUnknown):
            self.run_operation(page)
        buttons["Back"].invoke.assert_called_once_with()

    def test_offline_confirmation_changed_path_never_starts(self):
        field = FirmwareNode("Edit", "Click here to select firmware zip package...")
        confirmation = FirmwareNode("Window", "", (
            FirmwareNode("Hyperlink", "Matrice 4T"), text(CONFIRMATION_TEXT),
            text("Device powered on with sufficient battery"), text("USB Connection"),
            field, FirmwareNode("Button", "Start Update"),
        ))
        page, buttons = page_for([confirmation])
        first = snapshot(confirmation, buttons)
        edit = Mock()
        edit.get_value.return_value = r"C:\firmware\other.zip"
        first[1][id(field)] = edit
        page._capture.side_effect = [first]
        operation = FirmwareOperations(page)
        operation.offline_package = Path(r"C:\firmware\expected.zip")
        with self.assertRaises(FirmwareOutcomeUnknown):
            operation.wait(FirmwareVersion.parse("17.02.0501"), FirmwareVersion.parse(CURRENT),
                           "offline", "Matrice 4T", float("inf"), 1, None)
        buttons["Start Update"].invoke.assert_not_called()


class StatusTests(unittest.TestCase):
    def test_split_percent_and_transmitting_without_version(self):
        value = parse_status(stage("Transmitting", version="", percent="84"))
        self.assertEqual(value.stage, FirmwareStage.TRANSMITTING)
        self.assertEqual(value.percent, 84)
        self.assertIsNone(value.version)

    def test_blank_unknown(self):
        self.assertEqual(parse_status(FirmwareNode("Window", "")).stage, FirmwareStage.UNKNOWN)

    def test_ambiguous_stages_versions_and_invalid_percentage(self):
        for root in (
            stage("Updating", extra=(text("Downloading"),)),
            stage("Updating", extra=(text("V99.00.0000"),)),
            stage("Updating", percent="101"),
        ):
            with self.subTest(root=root), self.assertRaises(UnexpectedAssistantState):
                parse_status(root)


class PackageTests(unittest.TestCase):
    def test_official_zip_shape_and_target_without_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "package.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("wa345t_0000_v17.02.0501_20260529.pro.cfg.sig", b"test")
            self.assertEqual(validate_package(path), path)
            self.assertEqual(str(package_target(path, "Matrice 4T")), "17.02.0501")
            with self.assertRaises(ValueError):
                package_target(path, "Matrice 4E")

    def test_invalid_missing_bin_empty_and_unsafe_zip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "package.zip"
            with self.assertRaises(FileNotFoundError):
                validate_package(path)
            path.write_bytes(b"not zip")
            with self.assertRaises(ValueError):
                validate_package(path)
            bin_path = Path(folder) / "package.bin"
            bin_path.write_bytes(b"test")
            with self.assertRaises(ValueError):
                validate_package(bin_path)
            for names in ((), ("component.sig",), ("../bad.cfg.sig",)):
                with ZipFile(path, "w") as archive:
                    for name in names:
                        archive.writestr(name, b"test")
                with self.assertRaises(ValueError):
                    validate_package(path)

    def test_offline_denies_unconfirmed_before_any_ui(self):
        session = Mock()
        with self.assertRaises(ValueError):
            OfflinePage(session).upgrade("missing.zip", TARGET,
                                         expected_device="Matrice 4T",
                                         expected_current=CURRENT)
        self.assertEqual(session.mock_calls, [])

    def test_target_mismatch_denied_before_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "package.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("wa345t_0000_v17.02.0501_20260529.pro.cfg.sig", b"test")
            session = Mock()
            with self.assertRaises(ValueError):
                OfflinePage(session).upgrade(path, TARGET, expected_device="Matrice 4T",
                                             expected_current=CURRENT, confirm=True)
            self.assertEqual(session.mock_calls, [])

    def test_zip_crc_failure_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "package.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("wa345t_0000_v17.02.0501_test.cfg.sig", b"payload")
            data = path.read_bytes().replace(b"payload", b"PAYLOAD", 1)
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                validate_package(path)

    def test_native_picker_uses_owned_dialog_and_numeric_ids(self):
        package = Path(r"C:\firmware\package.zip")
        session = Mock()
        session.window.handle = 10
        session.window.descendants.return_value = []
        offline = OfflinePage(session)
        unrelated = Mock(handle=20)
        owned = Mock(handle=30)
        combo = Mock()
        combo.element_info.automation_id = "1148"
        edit = Mock()
        combo.descendants.return_value = [edit]
        button = Mock()
        button.element_info.automation_id = "1"
        button.is_enabled.return_value = True
        button.is_visible.return_value = True
        owned.descendants.side_effect = lambda control_type: (
            [combo] if control_type == "ComboBox" else [button]
        )
        field = session.window_spec.child_window.return_value.wrapper_object.return_value
        field.rectangle.return_value = Mock(left=0, right=10, top=0, bottom=10)
        with patch("dji_assistant.pages.offline.validate_package", return_value=package), patch.object(
            offline, "open"
        ), patch.object(offline, "selected_package", side_effect=[None, package]), patch(
            "dji_assistant.pages.offline.Desktop"
        ) as desktop, patch(
            "dji_assistant.pages.offline.win32gui.GetWindow",
            side_effect=lambda handle, _: {20: 99, 99: 0, 30: 10}[handle],
        ), patch(
            "dji_assistant.pages.offline.win32gui.WindowFromPoint", return_value=10
        ), patch(
            "dji_assistant.pages.offline.win32gui.GetAncestor", return_value=10
        ):
            desktop.return_value.windows.return_value = [unrelated, owned]
            self.assertEqual(offline.select_package(package), package)
        edit.set_edit_text.assert_called_once_with(str(package))
        button.invoke.assert_called_once_with()
        unrelated.descendants.assert_not_called()

    def test_unowned_picker_is_never_used(self):
        session = Mock()
        session.window.handle = 10
        session.window.descendants.return_value = []
        offline = OfflinePage(session)
        unrelated = Mock(handle=20)
        field = session.window_spec.child_window.return_value.wrapper_object.return_value
        field.rectangle.return_value = Mock(left=0, right=10, top=0, bottom=10)
        with patch("dji_assistant.pages.offline.validate_package", return_value=Path("test.zip")), patch.object(
            offline, "open"
        ), patch.object(offline, "selected_package", return_value=None
        ), patch("dji_assistant.pages.offline.Desktop") as desktop, patch(
            "dji_assistant.pages.offline.win32gui.GetWindow", return_value=0
        ), patch("dji_assistant.pages.offline.time.monotonic", side_effect=[0, 0, 11]), patch(
            "dji_assistant.pages.offline.time.sleep"
        ), patch(
            "dji_assistant.pages.offline.win32gui.WindowFromPoint", return_value=10
        ), patch(
            "dji_assistant.pages.offline.win32gui.GetAncestor", return_value=10
        ):
            desktop.return_value.windows.return_value = [unrelated]
            with self.assertRaises(UnexpectedAssistantState):
                offline.select_package("test.zip")
        unrelated.descendants.assert_not_called()

    def test_nested_owned_picker_is_found_and_deduplicated(self):
        session = Mock()
        session.window.handle = 10
        dialog = Mock(handle=30)
        session.window.descendants.return_value = [dialog]
        offline = OfflinePage(session)
        with patch("dji_assistant.pages.offline.Desktop") as desktop, patch(
            "dji_assistant.pages.offline.win32gui.GetWindow", return_value=10
        ):
            desktop.return_value.windows.return_value = []
            self.assertEqual(offline._owned_file_dialogs(), [dialog])
            desktop.return_value.windows.return_value = [dialog]
            self.assertEqual(offline._owned_file_dialogs(), [dialog])

    def test_already_selected_package_never_clicks_field(self):
        offline = OfflinePage(Mock())
        path = Path(r"C:\firmware\package.zip")
        with patch("dji_assistant.pages.offline.validate_package", return_value=path), patch.object(
            offline, "open"
        ), patch.object(offline, "selected_package", return_value=path):
            self.assertEqual(offline.select_package(path), path)
        offline.session.window.set_focus.assert_not_called()

    def test_covered_field_never_clicked(self):
        offline = OfflinePage(Mock())
        field = offline.session.window_spec.child_window.return_value.wrapper_object.return_value
        field.rectangle.return_value = Mock(left=0, right=10, top=0, bottom=10)
        with patch("dji_assistant.pages.offline.validate_package", return_value=Path("test.zip")), patch.object(
            offline, "open"
        ), patch.object(offline, "selected_package", return_value=None), patch(
            "dji_assistant.pages.offline.win32gui.WindowFromPoint", return_value=100
        ), patch("dji_assistant.pages.offline.win32gui.GetAncestor", return_value=200):
            with self.assertRaises(UnexpectedAssistantState):
                offline.select_package("test.zip")
        field.click_input.assert_not_called()

    def test_offline_validated_start_and_failure_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "package.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("wa345t_0000_v17.02.0501_test.cfg.sig", b"test")
            offline = OfflinePage(Mock())
            offline_root = FirmwareNode("Window", "", (
                FirmwareNode("Hyperlink", "Matrice 4T"), text("Local version:"),
                FirmwareNode("Button", "Start Upgrade"),
            ))
            page, buttons = page_for([
                device_tree(), device_tree(), offline_root,
                stage("Update failed.", version="", percent="0", extra=(text("2-251-1"),)),
            ])
            with patch("dji_assistant.pages.offline.FirmwarePage", return_value=page), patch.object(
                offline, "open"
            ), patch.object(offline, "selected_package", return_value=path):
                with self.assertRaises(FirmwareOperationFailed):
                    offline.upgrade(path, "17.02.0501", expected_device="Matrice 4T",
                                    expected_current=CURRENT, confirm=True)
            buttons["Start Upgrade"].invoke.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import Mock

from dji_assistant.exceptions import UIElementNotFound, UnexpectedAssistantState
from dji_assistant.models import FirmwareAction, FirmwareVersion
from dji_assistant.pages._firmware_tree import FirmwareNode, parse_firmware_tree
from dji_assistant.pages.firmware import FirmwarePage


def text(name):
    return FirmwareNode("Text", name)


def row(version, action="Downgrade", current=False, date="2026-02-13",
        official=True, extra=()):
    labels = [text("V"), text(version)]
    if current:
        labels.append(text("CURRENT"))
    return FirmwareNode("Custom", "", (
        FirmwareNode("DataItem", "", tuple(labels)),
        FirmwareNode("DataItem", "", (text(date),)),
        FirmwareNode("DataItem", "", (text("OFFICIAL"),) if official else ()),
        FirmwareNode("DataItem", "", (
            FirmwareNode("Button", action),
            FirmwareNode("Hyperlink", "Release Note"),
        )),
        *extra,
    ))


def tree(rows=None, label="V17.01.0516"):
    if rows is None:
        rows = (row("17.01.0516", "Refresh", True),
                row("17.00.0001"))
    return FirmwareNode("Window", "", (
        FirmwareNode("Document", "", (
            text("Current"), text(":"), text(label),
            FirmwareNode("Table", "", tuple(rows)),
        )),
    ))


def wrapper(node):
    ctrl = Mock(spec=["element_info", "children"])
    ctrl.element_info.control_type = node.control_type
    ctrl.element_info.name = node.name
    ctrl.children.return_value = [wrapper(child) for child in node.children]
    return ctrl


class FirmwareTreeTests(unittest.TestCase):
    def test_rows_and_current_label_are_separate(self):
        entries = parse_firmware_tree(tree())
        self.assertEqual(len(entries), 2)
        self.assertEqual(str(entries[0].version), "17.01.0516")
        self.assertTrue(entries[0].current)
        self.assertEqual(entries[0].action, FirmwareAction.REFRESH)
        self.assertEqual(entries[1].date.isoformat(), "2026-02-13")
        self.assertEqual(entries[1].action, FirmwareAction.DOWNGRADE)

    def test_variable_depth(self):
        nested = FirmwareNode("Custom", "", (row("17.01.0516", "Refresh", True),))
        entries = parse_firmware_tree(tree((nested, row("17.00.0001"))))
        self.assertEqual(len(entries), 2)

    def test_absent_official_is_unknown_not_false(self):
        entries = parse_firmware_tree(tree((
            row("17.01.0516", "Refresh", True, official=False),
        )))
        self.assertIsNone(entries[0].official)

    def test_missing_date_is_unknown(self):
        entries = parse_firmware_tree(tree((
            row("17.01.0516", "Refresh", True, date=""),
        )))
        self.assertIsNone(entries[0].date)

    def test_date_separators(self):
        for value in ("2026/2/13", "2026.02.13"):
            with self.subTest(value=value):
                entries = parse_firmware_tree(tree((
                    row("17.01.0516", "Refresh", True, date=value),
                )))
                self.assertEqual(entries[0].date.isoformat(), "2026-02-13")

    def test_invalid_date(self):
        with self.assertRaises(UnexpectedAssistantState):
            parse_firmware_tree(tree((
                row("17.01.0516", "Refresh", True, date="2026-02-30"),
            )))

    def test_multiple_dates(self):
        with self.assertRaises(UnexpectedAssistantState):
            parse_firmware_tree(tree((
                row("17.01.0516", "Refresh", True, extra=(text("2025-01-01"),)),
            )))

    def test_multiple_actions(self):
        with self.assertRaises(UnexpectedAssistantState):
            parse_firmware_tree(tree((
                row("17.01.0516", "Refresh", True,
                    extra=(FirmwareNode("Button", "Upgrade"),)),
            )))

    def test_duplicate_versions(self):
        with self.assertRaises(UnexpectedAssistantState):
            parse_firmware_tree(tree((
                row("17.01.0516", "Refresh", True),
                row("17.01.0516", "Upgrade"),
            )))

    def test_missing_or_multiple_current(self):
        for rows in (
            (row("17.01.0516"),),
            (row("17.01.0516", "Refresh", True),
             row("17.00.0001", "Refresh", True)),
        ):
            with self.subTest(rows=rows), self.assertRaises(UnexpectedAssistantState):
                parse_firmware_tree(tree(rows))

    def test_conflicting_current_label(self):
        with self.assertRaises(UnexpectedAssistantState):
            parse_firmware_tree(tree(label="V17.00.0001"))

    def test_unknown_action_does_not_silently_drop_row(self):
        with self.assertRaises(UnexpectedAssistantState):
            parse_firmware_tree(tree((
                row("17.01.0516", "Refresh", True),
                row("17.00.0001", "Install"),
            )))

    def test_unknown_extra_button_is_ambiguous(self):
        with self.assertRaises(UnexpectedAssistantState):
            parse_firmware_tree(tree((
                row("17.01.0516", "Refresh", True,
                    extra=(FirmwareNode("Button", "Install"),)),
            )))

    def test_duplicate_current_labels(self):
        root = tree()
        document = root.children[0]
        duplicate = FirmwareNode("Document", "", (
            *document.children, text("Current"), text("V17.01.0516"),
        ))
        with self.assertRaises(UnexpectedAssistantState):
            parse_firmware_tree(FirmwareNode("Window", "", (duplicate,)))

    def test_unmarked_row_version_is_not_silently_skipped(self):
        with self.assertRaises(UnexpectedAssistantState):
            parse_firmware_tree(tree((
                row("17.01.0516", "Refresh", True),
                FirmwareNode("Custom", "", (text("17.00.0001"),)),
            )))

    def test_wrong_page_empty_and_multiple_tables(self):
        for root in (
            FirmwareNode("Document", "Offline Upgrade"),
            tree(()),
            FirmwareNode("Window", "", (
                FirmwareNode("Table", ""), FirmwareNode("Table", ""),
            )),
        ):
            with self.subTest(root=root), self.assertRaises(UnexpectedAssistantState):
                parse_firmware_tree(root)

    def test_operations_are_read_only_and_each_node_captured_once(self):
        win = wrapper(tree())
        page = FirmwarePage(Mock(window=win))
        entries = page.available()
        self.assertEqual(len(entries), 2)

        def check(ctrl):
            ctrl.children.assert_called_once_with()
            for child in ctrl.children.return_value:
                check(child)
        check(win)
        self.assertEqual(page.current(), FirmwareVersion.parse("17.01.0516"))
        self.assertEqual(page.select("v17.00.0001").action, FirmwareAction.DOWNGRADE)
        with self.assertRaises(UIElementNotFound):
            page.select("99.00.0000")
        with self.assertRaises(ValueError):
            page.select("not a version")

    def test_tree_read_failure_propagates(self):
        win = Mock()
        win.children.side_effect = RuntimeError("UIA connection lost")
        page = FirmwarePage(Mock(window=win))
        with self.assertRaisesRegex(RuntimeError, "UIA connection lost"):
            page.available()

    def test_version_validation_and_normalization(self):
        self.assertEqual(str(FirmwareVersion.parse("17.01.0516")), "17.01.0516")
        self.assertEqual(str(FirmwareVersion.parse("01.00.00.0900")), "01.00.00.0900")
        self.assertEqual(FirmwareVersion.parse(" V17.01.0516 "),
                         FirmwareVersion.parse("17.1.516"))
        for value in ("", "17", "17.01", "17..01", "-17.01.0516",
                      "17.01.0516 trailing", "17.01.1e2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FirmwareVersion.parse(value)

    def test_offline_installed_version_absent_from_online_table(self):
        from dji_assistant.pages._firmware_tree import installed_version
        root = tree((row("17.01.0516"), row("17.00.0001")), label="V17.02.0501")
        self.assertEqual(str(installed_version(root)), "17.02.0501")
        self.assertTrue(all(not entry.current for entry in parse_firmware_tree(root)))

    def test_current_reads_without_online_table(self):
        page = FirmwarePage(Mock(window=wrapper(FirmwareNode("Document", "", (
            text("Current"), text(":"), text("V17.02.0501"),
        )))))
        self.assertEqual(str(page.current()), "17.02.0501")


if __name__ == "__main__":
    unittest.main()

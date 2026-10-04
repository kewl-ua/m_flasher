from __future__ import annotations

import win32con
import win32gui
import win32process
from pywinauto.controls.uiawrapper import UIAWrapper

from ...exceptions import UnexpectedAssistantState


def addressed_click(window: UIAWrapper, target: UIAWrapper) -> None:
    if not target.is_enabled() or not target.is_visible():
        raise UnexpectedAssistantState("Addressed input target is not enabled and visible.")
    rectangle = target.rectangle()
    if rectangle.width() <= 0 or rectangle.height() <= 0:
        raise UnexpectedAssistantState("Addressed input target has empty bounds.")
    point = rectangle.mid_point()
    children = []
    win32gui.EnumChildWindows(window.handle, lambda handle, _: children.append(handle), None)
    renderers = [
        handle for handle in children
        if win32gui.GetClassName(handle) == "Chrome_RenderWidgetHostHWND"
        and win32gui.IsWindowVisible(handle)
    ]
    if len(renderers) != 1:
        raise UnexpectedAssistantState("Addressed input requires one visible Chromium renderer.")
    renderer = renderers[0]
    if (win32gui.GetAncestor(renderer, win32con.GA_ROOT) != window.handle
            or win32process.GetWindowThreadProcessId(renderer)[1]
            != win32process.GetWindowThreadProcessId(window.handle)[1]):
        raise UnexpectedAssistantState("Chromium renderer does not belong to Assistant.")
    left, top, right, bottom = win32gui.GetWindowRect(renderer)
    if (rectangle.left < left or rectangle.top < top
            or rectangle.right > right or rectangle.bottom > bottom):
        raise UnexpectedAssistantState("Addressed input target is outside the renderer.")
    x, y = win32gui.ScreenToClient(renderer, (point.x, point.y))
    if not (0 <= x < 32768 and 0 <= y < 32768):
        raise UnexpectedAssistantState("Addressed input coordinates exceed the supported range.")
    coordinates = (y << 16) | x
    try:
        for message, keys in (
            (win32con.WM_MOUSEMOVE, 0),
            (win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON),
            (win32con.WM_LBUTTONUP, 0),
        ):
            win32gui.SendMessageTimeout(
                renderer, message, keys, coordinates, win32con.SMTO_ABORTIFHUNG, 2000,
            )
    except win32gui.error as exc:
        raise UnexpectedAssistantState(
            "Addressed input may have reached Assistant. No retry or physical fallback; "
            "inspect the application."
        ) from exc

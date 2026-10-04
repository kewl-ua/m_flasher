from __future__ import annotations

import ctypes
import os
import socket
import sys
import time
from ctypes import wintypes

import win32event
import win32api
import win32process
from pywinauto import Desktop

from .client import DJIAssistant
from .exceptions import UnexpectedAssistantState
from .isolated import _receive, _send, _spawn, _window_desktop, _USER32, _desktop_name
from .models import FirmwareStage
from .pages.offline import OfflinePage


class _IsolatedOfflinePage(OfflinePage):
    def _submit_package(self, dialog, package, deadline):
        if _window_desktop(dialog.handle) != _window_desktop(self.window.handle):
            raise UnexpectedAssistantState("File picker escaped isolated desktop.")
        return super()._submit_package(dialog, package, deadline)


def _assert_reusable_desktop(name: str) -> None:
    desktop = _USER32.GetThreadDesktop(win32api.GetCurrentThreadId())
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    if _desktop_name(desktop) != name:
        raise UnexpectedAssistantState("Worker is not on the requested desktop.")
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _USER32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, callback_type, wintypes.LPARAM]
    _USER32.EnumDesktopWindows.restype = wintypes.BOOL
    foreign_pids = set()
    lookup_errors = []

    @callback_type
    def collect(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except win32process.error as exc:
            lookup_errors.append(exc)
            return False
        if pid != os.getpid():
            foreign_pids.add(pid)
        return True

    ctypes.set_last_error(0)
    ok = _USER32.EnumDesktopWindows(desktop, collect, 0)
    error = ctypes.get_last_error()
    if lookup_errors:
        raise UnexpectedAssistantState(
            "Could not verify ownership of reusable desktop windows; not launching."
        ) from lookup_errors[0]
    if not ok and error:
        raise ctypes.WinError(error)
    if foreign_pids:
        raise UnexpectedAssistantState(
            f"Reusable desktop contains windows from other processes "
            f"({sorted(foreign_pids)}); inspect it through attach, not launch."
        )


def _dji_processes() -> list[int]:
    class Entry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD), ("usage", wintypes.DWORD),
            ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
            ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
            ("flags", wintypes.DWORD), ("exe", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        found = []
        if not kernel.Process32FirstW(handle, ctypes.byref(entry)):
            raise ctypes.WinError(ctypes.get_last_error())
        while True:
            if entry.exe.lower() in {
                "dji assistant 2.exe", "djiservice.exe",
                "djiservicecore.exe", "djibrowser.exe",
            }:
                found.append(entry.pid)
            if not kernel.Process32NextW(handle, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:
                    raise ctypes.WinError(ctypes.get_last_error())
                break
        return found
    finally:
        kernel.CloseHandle(handle)


def _initialize(desktop: str, title: str, executable: str | None, timeout: float):
    if executable is not None:
        existing = _dji_processes()
        if existing:
            raise UnexpectedAssistantState(
                f"DJI processes already running ({existing}); close them normally first."
            )
        _assert_reusable_desktop(desktop)
        process, thread, _, _ = _spawn(executable, [], desktop)
        process.Close()
        thread.Close()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        windows = Desktop(backend="uia").windows(title=title, enabled_only=False)
        if len(windows) > 1:
            raise UnexpectedAssistantState("Multiple isolated Assistant windows.")
        if windows and windows[0].is_enabled():
            if _window_desktop(windows[0].handle) != desktop:
                raise UnexpectedAssistantState("Assistant escaped the isolated desktop.")
            dji = DJIAssistant.connect(
                title=title, allow_physical_input=False, addressed_input=True,
            )
            dji.offline = _IsolatedOfflinePage(dji._session)
            return dji
        time.sleep(0.2)
    raise UnexpectedAssistantState("Isolated main window did not become ready.")


def _dispatch(dji: DJIAssistant, desktop: str, command: str, arguments: dict):
    if _window_desktop(dji._session.window.handle) != desktop:
        raise UnexpectedAssistantState("Assistant escaped the isolated desktop.")
    if command == "open_device":
        dji.open_device(**arguments)
        return None
    if command == "current":
        return str(dji.firmware.current())
    if command == "status":
        status = dji.firmware.status()
        return {
            "stage": status.stage.value,
            "version": str(status.version) if status.version else None,
            "percent": status.percent, "error_code": status.error_code,
        }
    if command == "ignore_flysafe":
        if dji.firmware.status().stage is not FirmwareStage.IDLE:
            raise UnexpectedAssistantState("FlySafe dismissal requires idle firmware page.")
        if dji.flysafe_prompt():
            dji._session.window_spec.child_window(
                title="Ignore", control_type="Button",
            ).wrapper_object().invoke()
        return None
    if command == "select_package":
        previous = dji.firmware.current()
        selected = dji.offline.select_package(**arguments)
        dji.firmware.open()
        deadline = time.monotonic() + 10
        readiness_error = None
        while time.monotonic() < deadline:
            try:
                current = dji.firmware.current()
            except UnexpectedAssistantState as exc:
                readiness_error = exc
                time.sleep(0.2)
                continue
            if current != previous:
                raise UnexpectedAssistantState(
                    "Current changed during package selection; no firmware write was requested."
                )
            return str(selected)
        raise UnexpectedAssistantState(
            "Package selected, but Firmware Update Current did not become readable. "
            "Do not repeat selection automatically."
        ) from readiness_error
    if command == "quit":
        dji.quit_application(**arguments)
        return None
    raise ValueError(f"Unsupported isolated command: {command!r}; no action performed.")


def main() -> None:
    desktop, port = sys.argv[1:]
    token = os.environ.pop("DJI_SDK_WORKER_TOKEN")
    mutex = win32event.CreateMutex(None, False, "Local\\DjiSdkIsolatedAssistant_worker")
    acquired = win32event.WaitForSingleObject(mutex, 0) in (0, 0x80)
    dji = None
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=10) as connection:
            connection.settimeout(None)
            _send(connection, {"desktop": desktop, "token": token})
            while True:
                try:
                    request = _receive(connection)
                except ConnectionError:
                    break
                command = request.get("command")
                quit_done = False
                try:
                    if not acquired:
                        raise UnexpectedAssistantState("Another worker controls this desktop.")
                    arguments = request["arguments"]
                    if not isinstance(arguments, dict):
                        raise ValueError("Command arguments must be an object.")
                    if command == "initialize":
                        if dji is not None:
                            raise UnexpectedAssistantState("Worker already initialized.")
                        dji = _initialize(desktop, **arguments)
                        result = None
                    else:
                        if dji is None:
                            raise UnexpectedAssistantState("Worker not initialized.")
                        result = _dispatch(dji, desktop, command, arguments)
                        quit_done = command == "quit"
                    response = {"ok": True, "result": result}
                except Exception as exc:
                    response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                _send(connection, response)
                if quit_done:
                    break
    finally:
        if dji is not None:
            dji.close()
        if acquired:
            win32event.ReleaseMutex(mutex)
        mutex.Close()


if __name__ == "__main__":
    main()

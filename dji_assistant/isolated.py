"""Experimental, non-writing Assistant controller on a separate Windows desktop."""
from __future__ import annotations

import ctypes
import json
import math
import os
import secrets
import socket
import struct
import subprocess
import sys
import threading
from ctypes import wintypes
from pathlib import Path

import win32event
import win32process

from .constants import WINDOW_TITLE
from .exceptions import UnexpectedAssistantState
from .models import FirmwareStage, FirmwareStatus, FirmwareVersion

_LIMIT = 65536
_DESKTOP_NAME = "DjiSdk_IsolatedAssistant"
_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_USER32.CreateDesktopW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
]
_USER32.CreateDesktopW.restype = wintypes.HANDLE
_USER32.OpenDesktopW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
]
_USER32.OpenDesktopW.restype = wintypes.HANDLE
_USER32.CloseDesktop.argtypes = [wintypes.HANDLE]
_USER32.CloseDesktop.restype = wintypes.BOOL
_USER32.GetThreadDesktop.argtypes = [wintypes.DWORD]
_USER32.GetThreadDesktop.restype = wintypes.HANDLE
_USER32.GetUserObjectInformationW.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
_USER32.GetUserObjectInformationW.restype = wintypes.BOOL


def _positive_timeout(timeout: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive.")


def _desktop_name(handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    needed = wintypes.DWORD()
    if not _USER32.GetUserObjectInformationW(
        handle, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(needed),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def _window_desktop(handle: int) -> str:
    thread, _ = win32process.GetWindowThreadProcessId(handle)
    desktop = _USER32.GetThreadDesktop(thread)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    return _desktop_name(desktop)


def _receive_exact(connection: socket.socket, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        chunk = connection.recv(count - len(chunks))
        if not chunk:
            raise ConnectionError("Isolated worker disconnected.")
        chunks.extend(chunk)
    return bytes(chunks)


def _receive(connection: socket.socket) -> dict:
    size = struct.unpack("!I", _receive_exact(connection, 4))[0]
    if not 0 < size <= _LIMIT:
        raise ValueError("Invalid isolated IPC frame size.")
    message = json.loads(_receive_exact(connection, size))
    if not isinstance(message, dict):
        raise ValueError("Isolated IPC message must be an object.")
    return message


def _send(connection: socket.socket, message: dict) -> None:
    payload = json.dumps(message, ensure_ascii=True, allow_nan=False).encode("utf-8")
    if not 0 < len(payload) <= _LIMIT:
        raise ValueError("Isolated IPC message exceeds size limit.")
    connection.sendall(struct.pack("!I", len(payload)) + payload)


def _spawn(executable: str, args: list[str], desktop: str, env=None):
    startup = win32process.STARTUPINFO()
    startup.lpDesktop = "WinSta0\\" + desktop
    return win32process.CreateProcess(
        executable, subprocess.list2cmdline([executable, *args]),
        None, None, False, 0, env, str(Path(executable).parent), startup,
    )


class IsolatedAssistant:
    """Read/navigation/package-selection only; no firmware write commands.

    Explicit quit is required. On a lost IPC channel, do not retry actions:
    use attach(desktop_name) to inspect the existing application.
    """

    def __init__(self, desktop: int, name: str, connection: socket.socket, process):
        self.desktop_name = name
        self._desktop = desktop
        self._connection = connection
        self._process = process
        self._lock = threading.Lock()
        self._broken = False
        self._closed = False

    @classmethod
    def launch(
        cls, executable: str | Path, *, title: str = WINDOW_TITLE, timeout: float = 60,
    ) -> "IsolatedAssistant":
        _positive_timeout(timeout)
        path = Path(executable).resolve(strict=True)
        if not path.is_file() or path.suffix.lower() != ".exe":
            raise ValueError("Expected installed DJI Assistant executable.")
        name = _DESKTOP_NAME
        desktop = _USER32.CreateDesktopW(name, None, None, 0, 0x01FF, None)
        if not desktop:
            raise ctypes.WinError(ctypes.get_last_error())
        return cls._start(desktop, name, title, timeout, str(path))

    @classmethod
    def attach(
        cls, desktop_name: str, *, title: str = WINDOW_TITLE, timeout: float = 30,
    ) -> "IsolatedAssistant":
        _positive_timeout(timeout)
        if not desktop_name.startswith("DjiSdk_") or not desktop_name[7:].isalnum():
            raise ValueError("Expected SDK-created desktop name.")
        desktop = _USER32.OpenDesktopW(desktop_name, 0, False, 0x01FF)
        if not desktop:
            raise ctypes.WinError(ctypes.get_last_error())
        return cls._start(desktop, desktop_name, title, timeout, None)

    @classmethod
    def _start(cls, desktop, name, title, timeout, executable):
        process = None
        connection = None
        controller = None
        try:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                listener.settimeout(timeout)
                token = secrets.token_hex(32)
                env = dict(os.environ)
                env["DJI_SDK_WORKER_TOKEN"] = token
                process, thread, _, _ = _spawn(
                    sys.executable,
                    ["-m", "dji_assistant._isolated_worker", name,
                     str(listener.getsockname()[1])], name, env,
                )
                thread.Close()
                connection, _ = listener.accept()
                connection.settimeout(timeout)
                hello = _receive(connection)
                if (hello.get("desktop") != name
                        or not isinstance(hello.get("token"), str)
                        or not secrets.compare_digest(hello["token"], token)):
                    raise UnexpectedAssistantState("Isolated worker authentication failed.")
            controller = cls(desktop, name, connection, process)
            controller._call(
                "initialize", rpc_timeout=timeout + 5,
                title=title, executable=executable, timeout=timeout,
            )
            return controller
        except Exception as exc:
            if controller is not None:
                controller.close()
            else:
                if connection is not None:
                    connection.close()
                if process is not None:
                    process.Close()
                if not _USER32.CloseDesktop(desktop):
                    raise ctypes.WinError(ctypes.get_last_error()) from exc
            raise UnexpectedAssistantState(
                f"Isolated startup failed: {type(exc).__name__}: {exc}. "
                f"Application is NOT forcibly terminated. "
                f"If already launched, recover with IsolatedAssistant.attach({name!r})."
            ) from exc

    def _call(self, command: str, *, rpc_timeout: float = 30, **arguments):
        _positive_timeout(rpc_timeout)
        with self._lock:
            if self._closed or self._broken:
                raise UnexpectedAssistantState(
                    f"Isolated channel unavailable; attach to {self.desktop_name!r}. No retry."
                )
            self._connection.settimeout(rpc_timeout)
            try:
                _send(self._connection, {"command": command, "arguments": arguments})
                response = _receive(self._connection)
                if type(response.get("ok")) is not bool:
                    raise ValueError("Invalid isolated worker response.")
            except (OSError, ValueError, ConnectionError) as exc:
                self._broken = True
                raise UnexpectedAssistantState(
                    f"Isolated command {command!r} outcome unknown; no retry. "
                    f"Application may remain on {self.desktop_name!r}; attach to inspect."
                ) from exc
            if not response["ok"]:
                raise UnexpectedAssistantState(
                    f"Isolated {command}: {response.get('error')}. No automatic retry."
                )
            return response.get("result")

    def open_device(self, name: str, *, timeout: float = 30) -> None:
        _positive_timeout(timeout)
        self._call("open_device", rpc_timeout=timeout + 5, name=name, timeout=timeout)

    def current(self) -> FirmwareVersion:
        result = self._call("current")
        if not isinstance(result, str):
            raise UnexpectedAssistantState("Invalid isolated current-version response.")
        return FirmwareVersion.parse(result)

    def status(self) -> FirmwareStatus:
        result = self._call("status")
        if (not isinstance(result, dict)
                or set(result) != {"stage", "version", "percent", "error_code"}
                or not isinstance(result["stage"], str)
                or (result["version"] is not None and not isinstance(result["version"], str))
                or (result["error_code"] is not None and not isinstance(result["error_code"], str))
                or (result["percent"] is not None and (
                    type(result["percent"]) is not int or not 0 <= result["percent"] <= 100
                ))):
            raise UnexpectedAssistantState("Invalid isolated firmware-status response.")
        return FirmwareStatus(
            FirmwareStage(result["stage"]),
            FirmwareVersion.parse(result["version"]) if result["version"] else None,
            result["percent"], result["error_code"],
        )

    def ignore_flysafe(self) -> None:
        self._call("ignore_flysafe")

    def select_package(self, path: str | Path, *, timeout: float = 120) -> Path:
        _positive_timeout(timeout)
        package = Path(path).resolve(strict=True)
        result = self._call("select_package", rpc_timeout=timeout, path=str(package))
        if not isinstance(result, str) or Path(result) != package:
            raise UnexpectedAssistantState("Isolated package selection readback mismatch.")
        return package

    def quit_application(self, *, timeout: float = 20) -> None:
        _positive_timeout(timeout)
        self._call("quit", rpc_timeout=timeout + 5, timeout=timeout)
        self.close()

    def close(self) -> None:
        """Disconnect only; never kills Assistant. Use attach to recover it."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._connection.close()
            try:
                exited = win32event.WaitForSingleObject(self._process, 5000) == 0
                exit_code = win32process.GetExitCodeProcess(self._process) if exited else None
            finally:
                self._process.Close()
                if not _USER32.CloseDesktop(self._desktop):
                    raise ctypes.WinError(ctypes.get_last_error())
            if not exited:
                raise UnexpectedAssistantState(
                    f"Worker still finishing a command on {self.desktop_name!r}. "
                    "Nothing was forcibly terminated; attach after it exits."
                )
            if exit_code != 0:
                raise UnexpectedAssistantState(
                    f"Worker exited with code {exit_code}; Assistant may remain on "
                    f"{self.desktop_name!r}. Attach to inspect; no retry."
                )

"""Windows-only primitives for driving A.I.VOICE2 Editor."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from pathlib import Path

VK_RETURN = 0x0D
VK_DELETE = 0x2E
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_A = 0x41
VK_E = 0x45
VK_V = 0x56
VK_Y = 0x59
VK_N = 0x4E
VK_D = 0x44

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
_UI_POLL_SECONDS = 0.05


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def voice_virtual_key(index: int) -> int:
    return 0x30 if index == 10 else 0x30 + index


def title_matches(title: str, prefix: str) -> bool:
    return bool(title) and title.casefold().startswith(prefix.casefold())


def _error(reason: str) -> Exception:
    from . import AIV2Error

    return AIV2Error(reason)


class WindowsBackend:
    """Win32 + UI Automation backend."""

    _MAX_TREE_DEPTH = 8

    def __init__(self, title_prefix: str) -> None:
        self.title_prefix = title_prefix
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._editor_pid: int | None = None
        self._declare_signatures()

    def _declare_signatures(self) -> None:
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        self._kernel32.GlobalLock.restype = wintypes.LPVOID
        self._kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        self._kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        self._kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        self._user32.SetClipboardData.restype = wintypes.HANDLE
        self._user32.GetForegroundWindow.restype = wintypes.HWND

    def _find_editor(self) -> int:
        matches: list[int] = []
        buffer = ctypes.create_unicode_buffer(512)

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def collect(hwnd, _lparam):
            if self._user32.IsWindowVisible(hwnd):
                self._user32.GetWindowTextW(hwnd, buffer, len(buffer))
                if title_matches(buffer.value, self.title_prefix):
                    matches.append(hwnd)
            return True

        self._user32.EnumWindows(collect, 0)
        if not matches:
            raise _error(
                f"no visible window titled {self.title_prefix!r}; "
                "is A.I.VOICE2 Editor running?"
            )
        return matches[0]

    def _pid_of(self, hwnd: int) -> int:
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def _foreground(self) -> int:
        return self._user32.GetForegroundWindow()

    def _class_of(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        self._user32.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value

    def _title_of(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(512)
        self._user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def _is_owned_dialog(self, hwnd: int) -> bool:
        return bool(
            hwnd
            and self._class_of(hwnd) == "#32770"
            and self._editor_pid is not None
            and self._pid_of(hwnd) == self._editor_pid
        )

    def focus_editor(self) -> int:
        hwnd = self._find_editor()
        self._editor_pid = self._pid_of(hwnd)
        if self._user32.IsIconic(hwnd):
            self._user32.ShowWindow(hwnd, 9)
        self._user32.SetForegroundWindow(hwnd)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self._foreground() == hwnd:
                return hwnd
            time.sleep(_UI_POLL_SECONDS)
        raise _error(
            "could not bring A.I.VOICE2 Editor to the foreground; "
            "another window is holding focus"
        )

    def assert_editor_foreground(self) -> None:
        title = self._title_of(self._foreground())
        if not title_matches(title, self.title_prefix):
            raise _error(f"focus left the Editor; foreground window is {title!r}")

    def wait_editor_foreground(self, deadline: float) -> None:
        while time.monotonic() < deadline:
            foreground = self._foreground()
            title = self._title_of(foreground)
            if title_matches(title, self.title_prefix):
                return
            if not self._is_owned_dialog(foreground):
                raise _error(f"unexpected window took focus during export: {title!r}")
            time.sleep(_UI_POLL_SECONDS)
        raise _error("Editor did not regain focus after export")

    def focus_text_input(self, hwnd: int) -> None:
        import uiautomation as auto

        try:
            window = auto.ControlFromHandle(hwnd)
        except Exception as exc:
            raise _error(f"UI Automation could not attach to the Editor: {exc}") from exc
        if window is None:
            raise _error("UI Automation could not attach to the Editor window")

        candidates = self._text_candidates(window)
        if not candidates:
            raise _error(
                "no editable text control found in the Editor; is a text block open?"
            )
        focused = [control for control in candidates if control.HasKeyboardFocus]
        if focused:
            target = focused[0]
        elif len(candidates) == 1:
            target = candidates[0]
        else:
            raise _error(
                f"{len(candidates)} editable text controls found and none has "
                "focus; click the intended text block once, then retry"
            )
        try:
            target.SetFocus()
        except Exception as exc:
            raise _error(f"could not focus the text block: {exc}") from exc

    def _text_candidates(self, window) -> list:
        found: list = []
        frontier = [(window, 0)]
        while frontier:
            control, depth = frontier.pop(0)
            if depth >= self._MAX_TREE_DEPTH:
                continue
            try:
                children = control.GetChildren() or []
            except Exception:
                continue
            for child in children:
                if self._is_text_candidate(child):
                    found.append(child)
                else:
                    frontier.append((child, depth + 1))
        return found

    @staticmethod
    def _is_text_candidate(control) -> bool:
        import uiautomation as auto

        try:
            return bool(
                control.IsEnabled
                and control.IsKeyboardFocusable
                and control.ControlType
                in (auto.ControlType.DocumentControl, auto.ControlType.EditControl)
            )
        except Exception:
            return False

    def _send(self, *keys: int) -> None:
        events = [self._key_event(key, True) for key in keys]
        events += [self._key_event(key, False) for key in reversed(keys)]
        array = (INPUT * len(events))(*events)
        sent = self._user32.SendInput(
            len(events), ctypes.byref(array), ctypes.sizeof(INPUT)
        )
        if sent != len(events):
            raise _error(
                f"SendInput delivered {sent} of {len(events)} key events "
                f"(error {ctypes.get_last_error()})"
            )

    @staticmethod
    def _key_event(key: int, down: bool) -> INPUT:
        event = INPUT()
        event.type = INPUT_KEYBOARD
        event.union.ki = KEYBDINPUT(
            wVk=key,
            wScan=0,
            dwFlags=0 if down else KEYEVENTF_KEYUP,
            time=0,
            dwExtraInfo=None,
        )
        return event

    def clear_text(self) -> None:
        self._send(VK_CONTROL, VK_A)
        self._send(VK_DELETE)

    def assign_voice(self, index: int) -> None:
        self._send(VK_CONTROL, voice_virtual_key(index))

    def split_block(self) -> None:
        self._send(VK_CONTROL, VK_RETURN)

    def export_current(self) -> None:
        self._send(VK_CONTROL, VK_E)

    def export_all(self) -> None:
        self._send(VK_CONTROL, VK_SHIFT, VK_E)

    def _set_clipboard(self, text: str) -> None:
        if not self._user32.OpenClipboard(None):
            raise _error("could not open the clipboard")
        try:
            self._user32.EmptyClipboard()
            encoded = text.encode("utf-16-le") + b"\x00\x00"
            handle = self._kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
            if not handle:
                raise _error("could not allocate clipboard memory")
            locked = self._kernel32.GlobalLock(handle)
            if not locked:
                self._kernel32.GlobalFree(handle)
                raise _error("could not lock clipboard memory")
            try:
                ctypes.memmove(locked, encoded, len(encoded))
            finally:
                self._kernel32.GlobalUnlock(handle)
            if not self._user32.SetClipboardData(CF_UNICODETEXT, handle):
                self._kernel32.GlobalFree(handle)
                raise _error("could not set clipboard data")
        finally:
            self._user32.CloseClipboard()

    def paste_text(self, text: str) -> None:
        self._set_clipboard(text)
        self._send(VK_CONTROL, VK_V)

    def _wait_for_dialog(self, deadline: float, what: str) -> int:
        editor_seen = self._find_editor()
        while time.monotonic() < deadline:
            foreground = self._foreground()
            if self._is_owned_dialog(foreground):
                return foreground
            if foreground != editor_seen:
                raise _error(
                    f"unexpected window took focus while waiting for {what}: "
                    f"{self._title_of(foreground)!r}"
                )
            time.sleep(_UI_POLL_SECONDS)
        raise _error(f"{what} did not appear")

    def _confirm_overwrite_if_present(self, save_dialog: int) -> None:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            foreground = self._foreground()
            if foreground and foreground != save_dialog:
                if self._is_owned_dialog(foreground):
                    self._send(VK_MENU, VK_Y)
                elif not title_matches(self._title_of(foreground), self.title_prefix):
                    raise _error(
                        "unexpected window took focus during overwrite confirmation: "
                        f"{self._title_of(foreground)!r}"
                    )
                return
            time.sleep(_UI_POLL_SECONDS)

    def fill_save_dialog(self, path: Path, deadline: float) -> None:
        dialog = self._wait_for_dialog(deadline, "the export save dialog")
        self._set_clipboard(str(path))
        self._send(VK_MENU, VK_N)
        self._send(VK_CONTROL, VK_A)
        self._send(VK_CONTROL, VK_V)
        self._send(VK_RETURN)
        self._confirm_overwrite_if_present(dialog)

    def fill_folder_dialog(self, directory: Path, deadline: float) -> None:
        self._wait_for_dialog(deadline, "the batch export folder dialog")
        self._set_clipboard(str(directory))
        self._send(VK_MENU, VK_D)
        self._send(VK_CONTROL, VK_A)
        self._send(VK_CONTROL, VK_V)
        self._send(VK_RETURN)
        time.sleep(_UI_POLL_SECONDS * 4)
        self._send(VK_RETURN)

    def is_writer_done(self, path: Path) -> bool:
        handle = self._kernel32.CreateFileW(
            str(path),
            wintypes.DWORD(GENERIC_READ),
            wintypes.DWORD(0),
            None,
            wintypes.DWORD(OPEN_EXISTING),
            wintypes.DWORD(0),
            None,
        )
        invalid_handle_value = ctypes.c_void_p(-1).value
        handle_value = ctypes.cast(handle, ctypes.c_void_p).value
        if handle_value in (None, invalid_handle_value):
            return False
        self._kernel32.CloseHandle(handle)
        return True

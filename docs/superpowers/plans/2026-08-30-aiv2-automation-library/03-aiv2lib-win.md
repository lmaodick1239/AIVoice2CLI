# 03 — `aiv2lib/_win.py`

Read [`00-overview.md`](00-overview.md) and the backend contract in [`02-aiv2lib-init.md`](02-aiv2lib-init.md#backend-interface-contract) first. This file overwrites the stub created there. It holds every Windows-specific operation; nothing else in the package imports `ctypes` or `uiautomation`.

**Files:**
- Modify: [`aiv2lib/_win.py`](../../../../aiv2lib/_win.py) (replace the stub entirely)

**Interfaces:**
- Consumes: `AIV2Error` from [`aiv2lib/__init__.py`](../../../../aiv2lib/__init__.py). Import it inside methods, not at module top level, to avoid a circular import.
- Produces: `WindowsBackend(title_prefix)` implementing every method in the contract below.

---

## Backend interface contract (duplicated from file 02 — keep in sync)

```python
focus_editor() -> int
focus_text_input(hwnd: int) -> None
clear_text() -> None
paste_text(text: str) -> None
assign_voice(index: int) -> None
split_block() -> None
export_current() -> None
export_all() -> None
fill_save_dialog(path: Path, deadline: float) -> None
fill_folder_dialog(directory: Path, deadline: float) -> None
wait_editor_foreground(deadline: float) -> None
assert_editor_foreground() -> None
is_writer_done(path: Path) -> bool
```

`deadline` is an absolute `time.monotonic()` value supplied by the controller.

---

- [ ] **Step 1: Write the failing unit tests for the pure helpers**

Only three things in this file are testable off-Windows: the virtual-key table for `assign_voice`, the title matcher, and the dialog-class matcher. Add to [`tests/test_aiv2lib.py`](../../../../tests/test_aiv2lib.py):

```python
def test_voice_index_maps_to_virtual_keys():
    from aiv2lib._win import voice_virtual_key

    assert voice_virtual_key(1) == 0x31
    assert voice_virtual_key(9) == 0x39
    assert voice_virtual_key(10) == 0x30


def test_title_matches_prefix_case_insensitively():
    from aiv2lib._win import title_matches

    assert title_matches("A.I.VOICE2 Editor - untitled", "A.I.VOICE2 Editor")
    assert title_matches("a.i.voice2 editor", "A.I.VOICE2 Editor")
    assert not title_matches("A.I.VOICE Editor", "A.I.VOICE2 Editor")
    assert not title_matches("", "A.I.VOICE2 Editor")
```

These import `aiv2lib._win` directly. That module must therefore not touch `ctypes.windll` at import time — only inside functions. If you write `user32 = ctypes.windll.user32` at module scope, these tests fail on Linux and CI.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_aiv2lib.py -k "virtual_key or title_matches" -v`

Expected: `ImportError: cannot import name 'voice_virtual_key'`.

- [ ] **Step 3: Write the module**

Replace [`aiv2lib/_win.py`](../../../../aiv2lib/_win.py) entirely:

```python
"""Windows-only primitives for driving A.I.VOICE2 Editor.

Everything that touches Win32 or UI Automation lives here. The controller in
__init__.py stays platform-agnostic and testable with a fake backend.

Deliberate choices:

* SendInput, not keybd_event: keybd_event is superseded and does not carry the
  extended-key flag correctly for the keys used here.
* Clipboard paste, not synthesized characters: one event regardless of text
  length, and immune to whatever IME state the Editor is in.
* Full path typed into the save dialog's filename field: Windows treats an
  absolute path there as navigate-then-name, so this sets both fields at once.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from pathlib import Path

# --- virtual key codes ----------------------------------------------------

VK_RETURN = 0x0D
VK_DELETE = 0x2E
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12  # Alt
VK_A = 0x41
VK_E = 0x45
VK_V = 0x56
VK_Y = 0x59
VK_N = 0x4E
VK_D = 0x44

# --- SendInput plumbing ---------------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# GENERIC_READ with no sharing: succeeds only when no writer holds the file.
GENERIC_READ = 0x80000000
OPEN_EXISTING = 3

# Poll granularity for waiting on windows, independent of the controller's
# file-poll interval. Short enough that a dialog is caught promptly.
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


# --- pure helpers (unit-tested off-Windows) -------------------------------


def voice_virtual_key(index: int) -> int:
    """Map character slot 1-10 to a digit virtual key. Slot 10 is Ctrl+0."""
    if index == 10:
        return 0x30
    return 0x30 + index


def title_matches(title: str, prefix: str) -> bool:
    """True if a window title starts with prefix, ignoring case.

    The Editor appends the project name, so this is a prefix test rather than
    equality.
    """
    if not title:
        return False
    return title.casefold().startswith(prefix.casefold())


def _error(reason: str) -> Exception:
    """Build an AIV2Error. Imported late to dodge the circular import."""
    from . import AIV2Error

    return AIV2Error(reason)


class WindowsBackend:
    """Win32 + UI Automation implementation of the backend contract."""

    def __init__(self, title_prefix: str) -> None:
        self.title_prefix = title_prefix
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._editor_pid: int | None = None
        self._declare_signatures()

    def _declare_signatures(self) -> None:
        """Pin restypes for anything returning a handle or a pointer.

        ctypes defaults every restype to C ``int``. On 64-bit Windows that
        silently truncates HANDLE and LPVOID returns: CreateFileW's failure
        value comes back as -1 instead of the full-width sentinel, and
        GlobalLock returns a chopped address that memmove would write to.
        Both are real corruption, not cosmetics.
        """
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        self._kernel32.GlobalLock.restype = wintypes.LPVOID
        self._kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        self._kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        self._kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        self._user32.SetClipboardData.restype = wintypes.HANDLE
        self._user32.GetForegroundWindow.restype = wintypes.HWND

    # --- window discovery ------------------------------------------------

    def _find_editor(self) -> int:
        """Return the handle of the first visible window matching the prefix."""
        matches: list[int] = []
        buffer = ctypes.create_unicode_buffer(512)

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def collect(hwnd, _lparam):
            if not self._user32.IsWindowVisible(hwnd):
                return True
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

    # --- focus -----------------------------------------------------------

    def focus_editor(self) -> int:
        """Raise the Editor and wait for it to actually become foreground."""
        hwnd = self._find_editor()
        self._editor_pid = self._pid_of(hwnd)

        if self._user32.IsIconic(hwnd):
            self._user32.ShowWindow(hwnd, 9)  # SW_RESTORE
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
        """Fail fast if focus has been stolen since the last check."""
        foreground = self._foreground()
        buffer = ctypes.create_unicode_buffer(512)
        self._user32.GetWindowTextW(foreground, buffer, len(buffer))
        if not title_matches(buffer.value, self.title_prefix):
            raise _error(
                f"focus left the Editor; foreground window is {buffer.value!r}"
            )

    def wait_editor_foreground(self, deadline: float) -> None:
        """Wait for the Editor to be foreground with no owned dialog left open."""
        while time.monotonic() < deadline:
            foreground = self._foreground()
            buffer = ctypes.create_unicode_buffer(512)
            self._user32.GetWindowTextW(foreground, buffer, len(buffer))
            if title_matches(buffer.value, self.title_prefix):
                return
            if self._class_of(foreground) != "#32770":
                raise _error(
                    f"unexpected window took focus during export: {buffer.value!r}"
                )
            time.sleep(_UI_POLL_SECONDS)
        raise _error("Editor did not regain focus after export")

    # --- UI Automation text targeting ------------------------------------

    _MAX_TREE_DEPTH = 8

    def focus_text_input(self, hwnd: int) -> None:
        """Focus the active text block's control.

        Hotkeys alone cannot do this: raising the top-level window says nothing
        about which child control has the caret. UI Automation is the only
        supported way to reach it without clicking fixed coordinates.
        """
        import uiautomation as auto

        try:
            window = auto.ControlFromHandle(hwnd)
        except Exception as exc:  # uiautomation surfaces bare COM errors
            raise _error(f"UI Automation could not attach to the Editor: {exc}") from exc
        if window is None:
            raise _error("UI Automation could not attach to the Editor window")

        candidates = self._text_candidates(window)
        if not candidates:
            raise _error(
                "no editable text control found in the Editor; "
                "is a text block open?"
            )

        # Prefer whatever already holds the caret. The Editor shows one text
        # control per block, so on a multi-block project every block is a
        # candidate and only the focused one is the intended target.
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
        """Breadth-first walk for editable text controls, depth-capped.

        Only GetChildren() is used. uiautomation's deeper traversal helpers vary
        across releases, and the Editor's tree is shallow enough that a manual
        walk is both shorter and version-proof. The cap keeps a pathological
        tree from turning this into a scan of the whole desktop.
        """
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
        """True for an enabled, focusable Document or Edit control.

        IsKeyboardFocusable is the discriminator rather than any multiline
        property: UI Automation exposes no portable "is multiline" flag, and a
        control that cannot take keyboard focus cannot be the text block
        regardless of its type.
        """
        import uiautomation as auto

        try:
            if not control.IsEnabled or not control.IsKeyboardFocusable:
                return False
            return control.ControlType in (
                auto.ControlType.DocumentControl,
                auto.ControlType.EditControl,
            )
        except Exception:
            # A control can vanish mid-walk; treat that as "not a candidate".
            return False

    # --- keyboard --------------------------------------------------------

    def _send(self, *keys: int) -> None:
        """Press keys in order, release in reverse. One SendInput call."""
        events: list[INPUT] = []
        for key in keys:
            events.append(self._key_event(key, down=True))
        for key in reversed(keys):
            events.append(self._key_event(key, down=False))

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

    # --- clipboard -------------------------------------------------------

    def _set_clipboard(self, text: str) -> None:
        """Put text on the clipboard as CF_UNICODETEXT.

        The previous clipboard contents are not restored. Restoring means
        enumerating and duplicating every format the owner published, which is
        far more code than this library should carry.

        ponytail: clipboard is clobbered; restore only if a user reports it.
        """
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
            # Ownership transferred to the clipboard; do not free handle.
        finally:
            self._user32.CloseClipboard()

    def paste_text(self, text: str) -> None:
        self._set_clipboard(text)
        self._send(VK_CONTROL, VK_V)

    # --- dialogs ---------------------------------------------------------

    def _wait_for_dialog(self, deadline: float, what: str) -> int:
        """Wait for a #32770 dialog owned by the Editor process to be foreground."""
        while time.monotonic() < deadline:
            foreground = self._foreground()
            if (
                self._class_of(foreground) == "#32770"
                and self._pid_of(foreground) == self._editor_pid
            ):
                return foreground
            time.sleep(_UI_POLL_SECONDS)
        raise _error(f"{what} did not appear")

    def _confirm_overwrite_if_present(self, save_dialog: int) -> None:
        """Answer the overwrite prompt if one appeared, otherwise do nothing.

        ``save_dialog`` is the handle of the dialog we just confirmed. It must be
        excluded: for a short moment after Enter the save dialog is still
        foreground, and a naive "is a #32770 in front?" check would fire Alt+Y
        into the filename field instead of the prompt. The overwrite prompt is a
        *different* #32770 owned by the same process.

        A short fixed window is acceptable here because this waits for a UI
        transition, not for synthesis to finish.
        """
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            foreground = self._foreground()
            if foreground and foreground != save_dialog:
                if (
                    self._class_of(foreground) == "#32770"
                    and self._pid_of(foreground) == self._editor_pid
                ):
                    self._send(VK_MENU, VK_Y)
                return  # save dialog closed with no prompt, or focus moved on
            time.sleep(_UI_POLL_SECONDS)

    def fill_save_dialog(self, path: Path, deadline: float) -> None:
        """Type an absolute path into the save dialog and confirm.

        Windows resolves an absolute path in the filename field by navigating to
        the directory and using the leaf as the name, so this needs one paste
        rather than driving the address bar separately.
        """
        dialog = self._wait_for_dialog(deadline, "the export save dialog")
        self._set_clipboard(str(path))
        self._send(VK_MENU, VK_N)  # focus the File name field
        self._send(VK_CONTROL, VK_A)
        self._send(VK_CONTROL, VK_V)
        self._send(VK_RETURN)
        self._confirm_overwrite_if_present(dialog)

    def fill_folder_dialog(self, directory: Path, deadline: float) -> None:
        """Point the folder picker at directory and confirm.

        The folder picker has no File name field in the same sense, so this uses
        the address bar (Alt+D) to navigate, then confirms the selection.
        """
        self._wait_for_dialog(deadline, "the batch export folder dialog")
        self._set_clipboard(str(directory))
        self._send(VK_MENU, VK_D)  # focus the address bar
        self._send(VK_CONTROL, VK_A)
        self._send(VK_CONTROL, VK_V)
        self._send(VK_RETURN)  # navigate into the directory
        time.sleep(_UI_POLL_SECONDS * 4)  # let the listing repaint
        self._send(VK_RETURN)  # accept "select this folder"

    # --- file completion -------------------------------------------------

    def is_writer_done(self, path: Path) -> bool:
        """True if the file opens for read with no sharing.

        Size stability alone is not proof: the Editor writes a WAV header, then
        the sample data, so a header-only file can look stable for one poll. An
        exclusive open fails while any writer still holds the handle.
        """
        handle = self._kernel32.CreateFileW(
            str(path),
            wintypes.DWORD(GENERIC_READ),
            wintypes.DWORD(0),  # no sharing
            None,
            wintypes.DWORD(OPEN_EXISTING),
            wintypes.DWORD(0),
            None,
        )
        # With restype pinned to HANDLE this is None on failure, because ctypes
        # renders a NULL/-1 handle as None rather than an integer sentinel.
        if not handle:
            return False
        self._kernel32.CloseHandle(handle)
        return True
```

- [ ] **Step 4: Run the helper tests**

Run: `python -m pytest tests/test_aiv2lib.py -k "virtual_key or title_matches" -v`

Expected: both pass, on any platform. If they fail with `OSError` or `AttributeError: windll`, something in the module is touching Win32 at import time — move it into a method.

- [ ] **Step 5: Run the whole off-Windows suite**

Run: `python -m pytest -q`

Expected: everything passes. No test in this file's scope requires Windows; the real dialog behaviour is covered by [`04-tests.md`](04-tests.md)'s opt-in smoke tests.

- [ ] **Step 6: Commit**

```bash
git add aiv2lib/_win.py tests/test_aiv2lib.py
git commit -m "feat: implement Win32 and UI Automation backend"
```

---

## Notes for whoever debugs this on real hardware

`fill_folder_dialog` sends `Enter` twice: once to navigate the address bar into the directory, once to accept the folder. If the picker variant in your Windows build accepts the folder on the first `Enter`, the second one lands on the already-closed dialog and is harmless — but if it instead lands in the Editor, you will see a stray block split. Check this on first run and drop the second `Enter` if so.

`_confirm_overwrite_if_present` sends `Alt+Y`. On a Japanese-locale Windows the overwrite prompt's affirmative button is 「はい(Y)」, so the `Y` accelerator holds. Verify rather than assume; if it differs, `VK_RETURN` targets the default button instead.

The one-second window in `_confirm_overwrite_if_present` is a UI-transition wait, not an export wait. Do not grow it into a substitute for `wait_for_audio`.

UUID filenames mean the overwrite prompt should never appear in practice. The handler exists because a collision would otherwise hang forever behind a modal dialog.

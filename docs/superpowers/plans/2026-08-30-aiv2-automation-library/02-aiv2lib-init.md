# 02 — `aiv2lib/__init__.py`

Read [`00-overview.md`](00-overview.md) first. This file produces the entire public API plus the filesystem completion logic. It contains no Win32 code.

**Files:**
- Create: [`aiv2lib/__init__.py`](../../../../aiv2lib/__init__.py)
- Create: [`aiv2lib/_win.py`](../../../../aiv2lib/_win.py) (stub only; [`03-aiv2lib-win.md`](03-aiv2lib-win.md) replaces it)

**Interfaces:**
- Consumes: [`pyproject.toml`](../../../../pyproject.toml) from [`01-pyproject.md`](01-pyproject.md).
- Produces: `AIV2Error`, `AIV2Controller`, and the frozen backend contract below.

---

## Backend interface contract

Both this file and [`03-aiv2lib-win.md`](03-aiv2lib-win.md) are written against this. It is duplicated verbatim in `03` because the two files may be implemented by different people in either order. **If you change a signature here, change it there too.**

```python
class Backend(Protocol):
    def focus_editor(self) -> int:
        """Bring the A.I.VOICE2 Editor main window to the foreground.

        Returns the window handle. Raises AIV2Error if the window is not
        found, cannot be raised, or does not become foreground in time.
        """

    def focus_text_input(self, hwnd: int) -> None:
        """Focus the active text block's edit control inside hwnd via UI Automation.

        Raises AIV2Error if zero or more than one viable control is found.
        """

    def clear_text(self) -> None:
        """Select all and delete in the already-focused text control."""

    def paste_text(self, text: str) -> None:
        """Place text on the clipboard and paste it into the focused control."""

    def assign_voice(self, index: int) -> None:
        """Send Ctrl+<index>, where index 10 maps to Ctrl+0."""

    def split_block(self) -> None:
        """Send Ctrl+Enter."""

    def export_current(self) -> None:
        """Send Ctrl+E. Does not wait for the resulting dialog."""

    def export_all(self) -> None:
        """Send Ctrl+Shift+E. Does not wait for the resulting dialog."""

    def fill_save_dialog(self, path: Path, deadline: float) -> None:
        """Wait for the owned save dialog, enter the full path, confirm.

        Also confirms an overwrite prompt if one appears. Raises AIV2Error on
        timeout or if the foreground window is not the expected dialog.
        """

    def fill_folder_dialog(self, directory: Path, deadline: float) -> None:
        """Wait for the owned folder-picker dialog, enter the directory, confirm."""

    def wait_editor_foreground(self, deadline: float) -> None:
        """Block until the editor is foreground again with no owned dialog."""

    def assert_editor_foreground(self) -> None:
        """Raise AIV2Error immediately if the foreground window is not the editor."""

    def is_writer_done(self, path: Path) -> bool:
        """True if path can be opened for exclusive read (no writer holds it)."""
```

`deadline` is always an absolute `time.monotonic()` value. The controller owns the clock; the backend never invents its own timeout.

---

- [ ] **Step 1: Write the failing constructor tests**

These live in [`tests/test_aiv2lib.py`](../../../../tests/test_aiv2lib.py), which [`04-tests.md`](04-tests.md) owns in full. Create just this much now so this file has a red bar to work against:

```python
from pathlib import Path

import pytest

import aiv2lib


class FakeBackend:
    def __init__(self):
        self.events = []


def test_constructor_normalizes_and_creates_export_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(aiv2lib.sys, "platform", "win32")
    monkeypatch.setattr(aiv2lib, "_make_backend", lambda title: FakeBackend())

    controller = aiv2lib.AIV2Controller(tmp_path / "audio")

    assert controller.export_dir == (tmp_path / "audio").resolve()
    assert controller.export_dir.is_dir()
    assert controller.app_title_prefix == "A.I.VOICE2 Editor"
    assert controller.timeout == 300.0
    assert controller.poll_interval == 0.25
    assert controller.stable_polls == 3


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timeout": 0}, "timeout must be greater than zero"),
        ({"poll_interval": 0}, "poll_interval must be greater than zero"),
        ({"stable_polls": 1}, "stable_polls must be at least 2"),
        ({"app_title_prefix": ""}, "app_title_prefix must not be empty"),
    ],
)
def test_constructor_rejects_invalid_configuration(tmp_path, monkeypatch, kwargs, message):
    monkeypatch.setattr(aiv2lib.sys, "platform", "win32")
    monkeypatch.setattr(aiv2lib, "_make_backend", lambda title: FakeBackend())

    with pytest.raises(aiv2lib.AIV2Error, match=message):
        aiv2lib.AIV2Controller(tmp_path, **kwargs)


def test_constructor_rejects_non_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(aiv2lib.sys, "platform", "linux")

    with pytest.raises(aiv2lib.AIV2Error, match="requires Windows"):
        aiv2lib.AIV2Controller(tmp_path)
```

- [ ] **Step 2: Run and confirm it fails**

Run: `python -m pytest tests/test_aiv2lib.py -v`

Expected: collection error, `ModuleNotFoundError: No module named 'aiv2lib'`.

- [ ] **Step 3: Create the backend stub so imports resolve**

Create [`aiv2lib/_win.py`](../../../../aiv2lib/_win.py) with exactly this. [`03-aiv2lib-win.md`](03-aiv2lib-win.md) overwrites the whole file later.

```python
from __future__ import annotations


class WindowsBackend:
    """Placeholder. Replaced by the real implementation in plan file 03."""

    def __init__(self, title_prefix: str) -> None:
        self.title_prefix = title_prefix
```

- [ ] **Step 4: Write the controller**

Create [`aiv2lib/__init__.py`](../../../../aiv2lib/__init__.py):

```python
"""Minimal Windows automation for A.I.VOICE2 Editor.

Preconditions the library cannot enforce, and that the operator must satisfy:

* A.I.VOICE2 Editor is running, with a window title starting with the
  configured prefix.
* The right-hand tab is 音声効果, not アクセント. On アクセント the Editor
  rebuilds one UI element per character, which turns a 300-character clear
  into ~15 seconds instead of ~1.
* Nobody is using the keyboard or mouse while a call is in flight. Every
  operation is synthesized input against the foreground window.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

__all__ = ["AIV2Controller", "AIV2Error"]


class AIV2Error(RuntimeError):
    """The only exception this library raises.

    The message is a short reason. There are deliberately no subclasses: v1
    callers either retry the whole operation or surface the message.
    """


def _make_backend(title_prefix: str) -> Any:
    """Seam for tests. Imported lazily so non-Windows test hosts can patch it."""
    from ._win import WindowsBackend

    return WindowsBackend(title_prefix)


class AIV2Controller:
    """Drives A.I.VOICE2 Editor through hotkeys, dialogs, and the filesystem."""

    def __init__(
        self,
        export_dir: str | os.PathLike[str],
        app_title_prefix: str = "A.I.VOICE2 Editor",
        timeout: float = 300.0,
        poll_interval: float = 0.25,
        stable_polls: int = 3,
    ) -> None:
        if sys.platform != "win32":
            raise AIV2Error("A.I.VOICE2 automation requires Windows")
        if not app_title_prefix:
            raise AIV2Error("app_title_prefix must not be empty")
        if timeout <= 0:
            raise AIV2Error("timeout must be greater than zero")
        if poll_interval <= 0:
            raise AIV2Error("poll_interval must be greater than zero")
        if stable_polls < 2:
            raise AIV2Error("stable_polls must be at least 2")

        self.export_dir = self._prepare_export_dir(export_dir)
        self.app_title_prefix = app_title_prefix
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self.stable_polls = int(stable_polls)
        self._backend = _make_backend(app_title_prefix)

    # ---- setup helpers -------------------------------------------------

    @staticmethod
    def _prepare_export_dir(export_dir: str | os.PathLike[str]) -> Path:
        path = Path(export_dir).expanduser().resolve()
        probe = path / ".aiv2lib-write-test"
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe.touch()
            probe.unlink()
        except OSError as exc:
            raise AIV2Error(f"export directory is not writable: {path}") from exc
        return path

    def _deadline(self) -> float:
        return time.monotonic() + self.timeout

    def _focused_text_input(self) -> None:
        """Focus the editor window, then the active text block inside it."""
        hwnd = self._backend.focus_editor()
        self._backend.focus_text_input(hwnd)

    # ---- primitives ----------------------------------------------------

    def focus(self) -> None:
        """Bring the Editor main window to the foreground."""
        self._backend.focus_editor()

    def clear_block(self) -> None:
        """Empty the active text block."""
        self._focused_text_input()
        self._backend.clear_text()

    def paste_text(self, text: str) -> None:
        """Replace nothing; paste text at the caret of the active text block.

        Pasting beats synthesizing keystrokes: it is one input event regardless
        of length, and it does not depend on the active IME.
        """
        if not isinstance(text, str):
            raise AIV2Error("text must be a string")
        self._focused_text_input()
        self._backend.paste_text(text)

    def assign_voice(self, voice_index: int) -> None:
        """Assign character 1-10 to the active block (Ctrl+1 .. Ctrl+0)."""
        if isinstance(voice_index, bool) or not isinstance(voice_index, int):
            raise AIV2Error("voice_index must be an integer from 1 to 10")
        if not 1 <= voice_index <= 10:
            raise AIV2Error("voice_index must be an integer from 1 to 10")
        self._focused_text_input()
        self._backend.assign_voice(voice_index)

    def split_block(self) -> None:
        """Split the active block at the caret (Ctrl+Enter)."""
        self._focused_text_input()
        self._backend.split_block()

    # ---- exports -------------------------------------------------------

    def generate_audio(self, text: str, voice_index: int | None = None) -> Path:
        """Replace the active block with text, export it, return the WAV path.

        The filename is a UUID chosen by this library and typed into the save
        dialog, because the Editor's own naming rules truncate long text and
        would collide across calls.
        """
        if not isinstance(text, str):
            raise AIV2Error("text must be a string")
        if not text.strip():
            raise AIV2Error("text must not be blank")

        deadline = self._deadline()
        destination = self.export_dir / f"{uuid.uuid4().hex}.wav"

        self.clear_block()
        self.paste_text(text)
        if voice_index is not None:
            self.assign_voice(voice_index)

        self._backend.assert_editor_foreground()
        self._backend.export_current()
        self._backend.fill_save_dialog(destination, deadline)
        self._backend.wait_editor_foreground(deadline)

        return self.wait_for_audio(destination, deadline=deadline)

    def batch_export_all(self) -> list[Path]:
        """Export every text block into a fresh per-call directory.

        Ctrl+Shift+E writes one file per block using the Editor's naming rules,
        so this cannot name files itself. It isolates them in a new directory
        instead and returns whatever landed there.
        """
        deadline = self._deadline()
        directory = self.export_dir / uuid.uuid4().hex
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise AIV2Error(f"could not create batch directory: {directory}") from exc

        self._backend.focus_editor()
        self._backend.export_all()
        self._backend.fill_folder_dialog(directory, deadline)
        self._backend.wait_editor_foreground(deadline)

        return self._wait_for_directory(directory, deadline)

    # ---- completion detection -----------------------------------------

    def wait_for_audio(self, path: Path, deadline: float | None = None) -> Path:
        """Block until path is a complete WAV, then return it.

        Complete means: exists, nonzero, size unchanged across stable_polls
        consecutive polls, and openable for exclusive read. Size alone is not
        enough because the Editor writes the header before the samples.
        """
        target = Path(path)
        limit = self._deadline() if deadline is None else deadline
        stable = 0
        last_size = -1

        while True:
            size = self._size_or_none(target)
            if size is not None and size > 0:
                if size == last_size:
                    stable += 1
                else:
                    stable = 1
                    last_size = size
                if stable >= self.stable_polls and self._backend.is_writer_done(target):
                    return target
            else:
                stable = 0
                last_size = -1

            self._sleep_until(limit, f"timed out waiting for {target.name}")

    def _wait_for_directory(self, directory: Path, deadline: float) -> list[Path]:
        """Block until every WAV in directory is complete and none are appearing."""
        stable = 0
        previous: dict[str, int] | None = None

        while True:
            snapshot = {
                item.name: self._size_or_none(item) or 0
                for item in directory.glob("*.wav")
            }
            if snapshot and all(size > 0 for size in snapshot.values()):
                if snapshot == previous:
                    stable += 1
                else:
                    stable = 1
                    previous = snapshot
                if stable >= self.stable_polls:
                    files = sorted(directory.glob("*.wav"))
                    if all(self._backend.is_writer_done(item) for item in files):
                        return files
            else:
                stable = 0
                previous = None

            self._sleep_until(
                deadline, f"timed out waiting for batch output in {directory.name}"
            )

    def _sleep_until(self, deadline: float, message: str) -> None:
        """Sleep one poll interval, or raise if that would pass the deadline."""
        if time.monotonic() + self.poll_interval > deadline:
            raise AIV2Error(message)
        time.sleep(self.poll_interval)

    @staticmethod
    def _size_or_none(path: Path) -> int | None:
        try:
            return path.stat().st_size
        except OSError:
            return None
```

- [ ] **Step 5: Run the constructor tests**

Run: `python -m pytest tests/test_aiv2lib.py -v`

Expected: all three tests pass.

- [ ] **Step 6: Confirm the non-Windows guard holds on this machine**

Run: `python -c "import aiv2lib; aiv2lib.AIV2Controller('/tmp/x')"`

Expected on Linux/macOS: `AIV2Error: A.I.VOICE2 automation requires Windows`. This is the guard working, not a failure. On Windows this instead fails inside `_make_backend` while file 03 is still a stub, which is also expected.

- [ ] **Step 7: Commit**

```bash
git add aiv2lib/__init__.py aiv2lib/_win.py tests/test_aiv2lib.py
git commit -m "feat: add AIV2Controller public API and completion detection"
```

---

## Design notes

Why the deadline is a parameter, not a per-call timeout: `generate_audio()` spends its budget across four waits (save dialog, overwrite prompt, editor refocus, file stability). Passing one absolute deadline through means a slow dialog eats into the file wait rather than granting each stage a fresh 300 seconds.

Why `wait_for_audio()` is public: it is the one internal step a caller may legitimately need alone, for instance after driving the Editor by hand.

Why `_wait_for_directory()` compares a name-to-size map rather than a count: a batch export both creates files and grows them. Requiring the whole map to repeat catches "file 3 of 5 just appeared" and "file 2 is still growing" with one check.

`ponytail: polling with stat() beats a filesystem watcher here; swap in watchdog only if a real workload shows the poll interval dominating.`

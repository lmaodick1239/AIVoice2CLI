"""Minimal Windows automation for A.I.VOICE2 Editor.

Operator preconditions:

* A.I.VOICE2 Editor is running, with a matching window title.
* Right-hand tab is 音声効果, not アクセント.
* Nobody uses keyboard or mouse while a call is in flight.
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
    """Automation failure with a concise reason."""


def _make_backend(title_prefix: str) -> Any:
    from ._win import WindowsBackend

    return WindowsBackend(title_prefix)


class AIV2Controller:
    """Drive A.I.VOICE2 Editor and return completed WAV paths."""

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
        hwnd = self._backend.focus_editor()
        self._backend.focus_text_input(hwnd)

    def focus(self) -> None:
        self._backend.focus_editor()

    def clear_block(self) -> None:
        self._focused_text_input()
        self._backend.clear_text()

    def paste_text(self, text: str) -> None:
        if not isinstance(text, str):
            raise AIV2Error("text must be a string")
        self._focused_text_input()
        self._backend.paste_text(text)

    def assign_voice(self, voice_index: int) -> None:
        if isinstance(voice_index, bool) or not isinstance(voice_index, int):
            raise AIV2Error("voice_index must be an integer from 1 to 10")
        if not 1 <= voice_index <= 10:
            raise AIV2Error("voice_index must be an integer from 1 to 10")
        self._focused_text_input()
        self._backend.assign_voice(voice_index)

    def split_block(self) -> None:
        self._focused_text_input()
        self._backend.split_block()

    def generate_audio(self, text: str, voice_index: int | None = None) -> Path:
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

    def wait_for_audio(self, path: Path, deadline: float | None = None) -> Path:
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
        if time.monotonic() + self.poll_interval > deadline:
            raise AIV2Error(message)
        time.sleep(self.poll_interval)

    @staticmethod
    def _size_or_none(path: Path) -> int | None:
        try:
            return path.stat().st_size
        except OSError:
            return None

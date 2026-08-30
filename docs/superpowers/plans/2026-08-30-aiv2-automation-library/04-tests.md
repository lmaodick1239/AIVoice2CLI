# 04 — `tests/test_aiv2lib.py` and `tests/test_windows_smoke.py`

Read [`00-overview.md`](00-overview.md) first. Files [`02-aiv2lib-init.md`](02-aiv2lib-init.md) and [`03-aiv2lib-win.md`](03-aiv2lib-win.md) each seeded a few tests to work against a red bar. This file states the finished suite. Where a test already exists from an earlier file, keep it and add the rest around it.

**Files:**
- Modify: [`tests/test_aiv2lib.py`](../../../../tests/test_aiv2lib.py) (final content below, replacing the partial version)
- Create: [`tests/test_windows_smoke.py`](../../../../tests/test_windows_smoke.py)

**Interfaces:**
- Consumes: `AIV2Error`, `AIV2Controller`, `_make_backend` from [`aiv2lib/__init__.py`](../../../../aiv2lib/__init__.py); `voice_virtual_key`, `title_matches` from [`aiv2lib/_win.py`](../../../../aiv2lib/_win.py).
- Produces: no library code.

---

## What is and is not tested

Testable off-Windows, and therefore tested here: constructor validation, method call ordering, voice-index validation, the UUID naming scheme, deadline propagation, size-stability logic, the exclusive-open gate, batch directory isolation, batch completion, and timeout behaviour.

Not testable without the real application: whether `Alt+N` reaches the save dialog's filename field, whether the folder picker needs one `Enter` or two, whether UI Automation finds exactly one editable control, and whether the overwrite prompt answers to `Alt+Y`. These are covered by the opt-in smoke file, which a human runs on a machine with the Editor open.

The fake backend records calls and drives the filesystem itself. That is the point: `generate_audio()` is mostly sequencing, and sequencing is what breaks.

---

- [ ] **Step 1: Write the full fake-backend suite**

Replace [`tests/test_aiv2lib.py`](../../../../tests/test_aiv2lib.py) with:

```python
"""Off-Windows tests for aiv2lib.

The Win32 backend is replaced by a fake that records calls and writes files on
cue. Nothing here needs A.I.VOICE2 Editor or even Windows.
"""

from pathlib import Path

import pytest

import aiv2lib


class FakeBackend:
    """Records every backend call; optionally writes files when asked to export.

    write_plan controls what happens when an export hotkey is sent:
      None                 -> write nothing (used for timeout tests)
      {"name": bytes}      -> write those files into the export target
    Files are written in one shot, so they are stable from the first poll.
    """

    def __init__(self, write_plan=None):
        self.events = []
        self.write_plan = write_plan
        self.save_target = None
        self.folder_target = None
        self.locked = set()

    # focus / text

    def focus_editor(self):
        self.events.append(("focus_editor",))
        return 101

    def focus_text_input(self, hwnd):
        self.events.append(("focus_text_input", hwnd))

    def clear_text(self):
        self.events.append(("clear_text",))

    def paste_text(self, text):
        self.events.append(("paste_text", text))

    def assign_voice(self, index):
        self.events.append(("assign_voice", index))

    def split_block(self):
        self.events.append(("split_block",))

    # exports

    def export_current(self):
        self.events.append(("export_current",))

    def export_all(self):
        self.events.append(("export_all",))

    # dialogs

    def fill_save_dialog(self, path, deadline):
        self.events.append(("fill_save_dialog", Path(path), deadline))
        self.save_target = Path(path)
        if self.write_plan is not None:
            self.save_target.write_bytes(self.write_plan)

    def fill_folder_dialog(self, directory, deadline):
        self.events.append(("fill_folder_dialog", Path(directory), deadline))
        self.folder_target = Path(directory)
        for name, payload in (self.write_plan or {}).items():
            (self.folder_target / name).write_bytes(payload)

    def wait_editor_foreground(self, deadline):
        self.events.append(("wait_editor_foreground", deadline))

    def assert_editor_foreground(self):
        self.events.append(("assert_editor_foreground",))

    # completion

    def is_writer_done(self, path):
        return Path(path) not in self.locked


def make_controller(tmp_path, monkeypatch, backend=None, **kwargs):
    backend = backend or FakeBackend()
    monkeypatch.setattr(aiv2lib.sys, "platform", "win32")
    monkeypatch.setattr(aiv2lib, "_make_backend", lambda title: backend)
    settings = {"poll_interval": 0.01, "timeout": 2.0}
    settings.update(kwargs)
    return aiv2lib.AIV2Controller(tmp_path, **settings), backend


def names(backend):
    """Just the call names, for order assertions that ignore arguments."""
    return [event[0] for event in backend.events]


# --- constructor ----------------------------------------------------------


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
        ({"timeout": -1}, "timeout must be greater than zero"),
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


def test_constructor_reports_unwritable_export_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(aiv2lib.sys, "platform", "win32")
    monkeypatch.setattr(aiv2lib, "_make_backend", lambda title: FakeBackend())
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")

    with pytest.raises(aiv2lib.AIV2Error, match="not writable"):
        aiv2lib.AIV2Controller(blocker / "under-a-file")


# --- primitives -----------------------------------------------------------


def test_text_methods_focus_window_then_text_control(tmp_path, monkeypatch):
    controller, backend = make_controller(tmp_path, monkeypatch)

    controller.clear_block()
    controller.paste_text("この れっしゃは ふつう れっしゃです。")

    assert backend.events == [
        ("focus_editor",),
        ("focus_text_input", 101),
        ("clear_text",),
        ("focus_editor",),
        ("focus_text_input", 101),
        ("paste_text", "この れっしゃは ふつう れっしゃです。"),
    ]


def test_focus_does_not_touch_the_text_control(tmp_path, monkeypatch):
    controller, backend = make_controller(tmp_path, monkeypatch)

    controller.focus()

    assert backend.events == [("focus_editor",)]


def test_assign_voice_accepts_one_through_ten(tmp_path, monkeypatch):
    controller, backend = make_controller(tmp_path, monkeypatch)

    controller.assign_voice(1)
    controller.assign_voice(10)

    assert backend.events[-1] == ("assign_voice", 10)
    assert ("assign_voice", 1) in backend.events


@pytest.mark.parametrize("index", [0, 11, -1, True, 1.5, "1", None])
def test_assign_voice_rejects_invalid_index(tmp_path, monkeypatch, index):
    controller, backend = make_controller(tmp_path, monkeypatch)

    with pytest.raises(aiv2lib.AIV2Error, match="voice_index must be an integer from 1 to 10"):
        controller.assign_voice(index)

    assert backend.events == []  # rejected before touching the Editor


def test_split_block_focuses_text_input(tmp_path, monkeypatch):
    controller, backend = make_controller(tmp_path, monkeypatch)

    controller.split_block()

    assert backend.events == [
        ("focus_editor",),
        ("focus_text_input", 101),
        ("split_block",),
    ]


@pytest.mark.parametrize("text", [b"bytes", 5, None])
def test_paste_text_rejects_non_strings(tmp_path, monkeypatch, text):
    controller, backend = make_controller(tmp_path, monkeypatch)

    with pytest.raises(aiv2lib.AIV2Error, match="text must be a string"):
        controller.paste_text(text)

    assert backend.events == []


# --- generate_audio -------------------------------------------------------


def test_generate_audio_returns_uuid_named_wav(tmp_path, monkeypatch):
    controller, backend = make_controller(
        tmp_path, monkeypatch, FakeBackend(write_plan=b"RIFF....WAVEdata")
    )

    result = controller.generate_audio("こんにちは")

    assert result == backend.save_target
    assert result.parent == controller.export_dir
    assert result.suffix == ".wav"
    assert len(result.stem) == 32  # uuid4().hex
    assert result.read_bytes() == b"RIFF....WAVEdata"


def test_generate_audio_call_order(tmp_path, monkeypatch):
    controller, backend = make_controller(
        tmp_path, monkeypatch, FakeBackend(write_plan=b"RIFF")
    )

    controller.generate_audio("こんにちは", voice_index=3)

    assert names(backend) == [
        "focus_editor",
        "focus_text_input",
        "clear_text",
        "focus_editor",
        "focus_text_input",
        "paste_text",
        "focus_editor",
        "focus_text_input",
        "assign_voice",
        "assert_editor_foreground",
        "export_current",
        "fill_save_dialog",
        "wait_editor_foreground",
    ]


def test_generate_audio_skips_voice_assignment_when_not_requested(tmp_path, monkeypatch):
    controller, backend = make_controller(
        tmp_path, monkeypatch, FakeBackend(write_plan=b"RIFF")
    )

    controller.generate_audio("こんにちは")

    assert "assign_voice" not in names(backend)


def test_generate_audio_produces_a_fresh_name_each_call(tmp_path, monkeypatch):
    controller, backend = make_controller(
        tmp_path, monkeypatch, FakeBackend(write_plan=b"RIFF")
    )

    first = controller.generate_audio("いちばん")
    second = controller.generate_audio("にばん")

    assert first != second


def test_generate_audio_shares_one_deadline_across_stages(tmp_path, monkeypatch):
    controller, backend = make_controller(
        tmp_path, monkeypatch, FakeBackend(write_plan=b"RIFF")
    )

    controller.generate_audio("こんにちは")

    save = next(e for e in backend.events if e[0] == "fill_save_dialog")
    wait = next(e for e in backend.events if e[0] == "wait_editor_foreground")
    assert save[2] == wait[1]


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_generate_audio_rejects_blank_text(tmp_path, monkeypatch, text):
    controller, backend = make_controller(tmp_path, monkeypatch)

    with pytest.raises(aiv2lib.AIV2Error, match="text must not be blank"):
        controller.generate_audio(text)

    assert backend.events == []


def test_generate_audio_times_out_when_no_file_appears(tmp_path, monkeypatch):
    controller, _ = make_controller(
        tmp_path, monkeypatch, FakeBackend(write_plan=None), timeout=0.2
    )

    with pytest.raises(aiv2lib.AIV2Error, match="timed out waiting for"):
        controller.generate_audio("こんにちは")


def test_generate_audio_waits_for_the_writer_to_release(tmp_path, monkeypatch):
    backend = FakeBackend(write_plan=b"RIFF")
    controller, backend = make_controller(tmp_path, monkeypatch, backend, timeout=0.3)

    original = backend.is_writer_done
    calls = {"n": 0}

    def release_on_third_call(path):
        calls["n"] += 1
        return calls["n"] >= 3 and original(path)

    backend.is_writer_done = release_on_third_call

    result = controller.generate_audio("こんにちは")

    assert result.exists()
    assert calls["n"] >= 3


def test_generate_audio_rejects_a_permanently_locked_file(tmp_path, monkeypatch):
    backend = FakeBackend(write_plan=b"RIFF")
    backend.is_writer_done = lambda path: False
    controller, _ = make_controller(tmp_path, monkeypatch, backend, timeout=0.2)

    with pytest.raises(aiv2lib.AIV2Error, match="timed out waiting for"):
        controller.generate_audio("こんにちは")


# --- wait_for_audio -------------------------------------------------------


def test_wait_for_audio_ignores_a_zero_byte_file(tmp_path, monkeypatch):
    controller, _ = make_controller(tmp_path, monkeypatch, timeout=0.2)
    empty = controller.export_dir / "empty.wav"
    empty.write_bytes(b"")

    with pytest.raises(aiv2lib.AIV2Error, match="timed out waiting for empty.wav"):
        controller.wait_for_audio(empty)


def test_wait_for_audio_requires_size_to_settle(tmp_path, monkeypatch):
    controller, _ = make_controller(tmp_path, monkeypatch, timeout=1.0, stable_polls=3)
    growing = controller.export_dir / "growing.wav"
    growing.write_bytes(b"RIFF")

    real_stat = aiv2lib.AIV2Controller._size_or_none
    sizes = iter([4, 8, 16, 32, 32, 32, 32])

    def fake_size(path):
        if Path(path) == growing:
            try:
                return next(sizes)
            except StopIteration:
                return 32
        return real_stat(path)

    monkeypatch.setattr(aiv2lib.AIV2Controller, "_size_or_none", staticmethod(fake_size))

    assert controller.wait_for_audio(growing) == growing


def test_wait_for_audio_accepts_an_explicit_deadline(tmp_path, monkeypatch):
    import time

    controller, _ = make_controller(tmp_path, monkeypatch, timeout=100.0)
    missing = controller.export_dir / "missing.wav"

    with pytest.raises(aiv2lib.AIV2Error, match="timed out"):
        controller.wait_for_audio(missing, deadline=time.monotonic() + 0.1)


# --- batch_export_all -----------------------------------------------------


def test_batch_export_isolates_output_in_a_uuid_directory(tmp_path, monkeypatch):
    plan = {"0_first.wav": b"RIFF-a", "1_second.wav": b"RIFF-bb"}
    controller, backend = make_controller(tmp_path, monkeypatch, FakeBackend(write_plan=plan))

    results = controller.batch_export_all()

    assert [item.name for item in results] == ["0_first.wav", "1_second.wav"]
    assert results[0].parent == backend.folder_target
    assert backend.folder_target.parent == controller.export_dir
    assert len(backend.folder_target.name) == 32


def test_batch_export_ignores_a_pre_existing_sibling_directory(tmp_path, monkeypatch):
    controller, backend = make_controller(
        tmp_path, monkeypatch, FakeBackend(write_plan={"0_only.wav": b"RIFF"})
    )
    stale = controller.export_dir / "stale.wav"
    stale.write_bytes(b"RIFF-old")

    results = controller.batch_export_all()

    assert stale not in results
    assert [item.name for item in results] == ["0_only.wav"]


def test_batch_export_call_order(tmp_path, monkeypatch):
    controller, backend = make_controller(
        tmp_path, monkeypatch, FakeBackend(write_plan={"0_a.wav": b"RIFF"})
    )

    controller.batch_export_all()

    assert names(backend) == [
        "focus_editor",
        "export_all",
        "fill_folder_dialog",
        "wait_editor_foreground",
    ]


def test_batch_export_times_out_on_an_empty_directory(tmp_path, monkeypatch):
    controller, _ = make_controller(
        tmp_path, monkeypatch, FakeBackend(write_plan={}), timeout=0.2
    )

    with pytest.raises(aiv2lib.AIV2Error, match="timed out waiting for batch output"):
        controller.batch_export_all()


def test_batch_export_waits_for_a_late_arriving_file(tmp_path, monkeypatch):
    """A second file appearing mid-poll must reset stability, not be missed."""
    backend = FakeBackend(write_plan={"0_first.wav": b"RIFF-a"})
    controller, backend = make_controller(tmp_path, monkeypatch, backend, timeout=2.0)

    real_glob = Path.glob
    state = {"polls": 0}

    def glob_then_add(self, pattern):
        results = list(real_glob(self, pattern))
        if self == backend.folder_target:
            state["polls"] += 1
            if state["polls"] == 2:
                (self / "1_late.wav").write_bytes(b"RIFF-bb")
        return iter(results)

    monkeypatch.setattr(Path, "glob", glob_then_add)

    results = controller.batch_export_all()

    assert [item.name for item in results] == ["0_first.wav", "1_late.wav"]


def test_batch_export_rejects_partially_locked_output(tmp_path, monkeypatch):
    backend = FakeBackend(write_plan={"0_a.wav": b"RIFF", "1_b.wav": b"RIFF"})
    controller, backend = make_controller(tmp_path, monkeypatch, backend, timeout=0.2)
    backend.is_writer_done = lambda path: Path(path).name == "0_a.wav"

    with pytest.raises(aiv2lib.AIV2Error, match="timed out waiting for batch output"):
        controller.batch_export_all()


# --- pure helpers from the Win32 module ----------------------------------


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


def test_win_module_imports_without_windows():
    """The Win32 module must not touch windll at import time."""
    import importlib

    import aiv2lib._win as win

    importlib.reload(win)
```

- [ ] **Step 2: Run the suite**

Run: `python -m pytest tests/test_aiv2lib.py -v`

Expected: every test passes. Runtime should be a couple of seconds; the timeout tests use `timeout=0.2` and `poll_interval=0.01` deliberately, so if the suite takes minutes, a test is using production defaults by mistake.

- [ ] **Step 3: Commit the unit suite**

```bash
git add tests/test_aiv2lib.py
git commit -m "test: cover controller sequencing and completion detection"
```

- [ ] **Step 4: Write the opt-in smoke tests**

Create [`tests/test_windows_smoke.py`](../../../../tests/test_windows_smoke.py):

```python
"""Opt-in tests against a real A.I.VOICE2 Editor. Skipped by default.

To run:

    set AIV2_SMOKE_EXPORT_DIR=C:\\temp\\aiv2-smoke
    python -m pytest tests/test_windows_smoke.py -v -s

Preconditions, none of which the library can check for you:

* A.I.VOICE2 Editor is running with at least one text block.
* The right-hand tab is 音声効果, not アクセント.
* You are not touching the keyboard or mouse while these run. They synthesize
  input against the foreground window; interference will fail them, and that
  is the intended behaviour rather than a flaky test.
"""

import os
import sys

import pytest

import aiv2lib

EXPORT_DIR = os.environ.get("AIV2_SMOKE_EXPORT_DIR")

pytestmark = [
    pytest.mark.skipif(sys.platform != "win32", reason="requires Windows"),
    pytest.mark.skipif(not EXPORT_DIR, reason="set AIV2_SMOKE_EXPORT_DIR to run"),
]

SAMPLE = (
    "この れっしゃは ふつう れっしゃ ななお いき わんまんかーです。"
    "しゅうてん ななお まで かくえきに ていしゃします。"
)


@pytest.fixture
def controller():
    return aiv2lib.AIV2Controller(EXPORT_DIR, timeout=120.0)


def test_focus_finds_the_editor(controller):
    controller.focus()


def test_generate_audio_writes_a_playable_wav(controller):
    result = controller.generate_audio(SAMPLE)

    assert result.exists()
    assert result.stat().st_size > 1024
    assert result.read_bytes()[:4] == b"RIFF"
    print(f"\nwrote {result} ({result.stat().st_size} bytes)")


def test_generate_audio_honours_a_voice_index(controller):
    result = controller.generate_audio("こんにちは。", voice_index=1)

    assert result.exists()
    assert result.read_bytes()[:4] == b"RIFF"


def test_generate_audio_handles_a_long_script(controller):
    result = controller.generate_audio(SAMPLE * 4)

    assert result.stat().st_size > 4096


def test_batch_export_all_returns_every_block(controller):
    """Requires at least two text blocks in the open project.

    This is the test most likely to expose the double-Enter question in
    fill_folder_dialog. If it hangs on the picker, that is the bug to chase.
    """
    results = controller.batch_export_all()

    assert results
    for item in results:
        assert item.read_bytes()[:4] == b"RIFF"
    print(f"\nwrote {len(results)} files to {results[0].parent}")


def test_focus_loss_is_reported(controller):
    """Manual test. Click another window while this runs; expect AIV2Error."""
    pytest.skip("manual: drop the skip and steal focus during the call")
    with pytest.raises(aiv2lib.AIV2Error, match="focus left the Editor"):
        controller.generate_audio(SAMPLE)
```

- [ ] **Step 5: Confirm the smoke tests skip cleanly**

Run: `python -m pytest tests/test_windows_smoke.py -v`

Expected: all skipped, with the reason shown. They must never fail merely because the environment variable is unset.

- [ ] **Step 6: Run everything**

Run: `python -m pytest -q`

Expected: the unit suite passes, the smoke suite skips, exit status 0.

- [ ] **Step 7: Commit**

```bash
git add tests/test_windows_smoke.py
git commit -m "test: add opt-in smoke tests against a live Editor"
```

---

## Reading a smoke failure

`no visible window titled 'A.I.VOICE2 Editor'` — the Editor is closed, or its title differs. Pass `app_title_prefix` to match what the title bar actually shows.

`N editable text controls found and none has focus` — UI Automation sees several candidates. Click into the intended text block once and retry. If this recurs, the candidate filter in [`aiv2lib/_win.py`](../../../../aiv2lib/_win.py) needs narrowing against the real tree.

`the export save dialog did not appear` — `Ctrl+E` did not open a dialog. Most likely a dialog was already open, which makes hotkeys inert.

`timed out waiting for <uuid>.wav` — the dialog was driven but the file never settled at that path. Check whether the filename field actually received the absolute path; that is the assumption behind the single-paste approach.

Batch export hanging on the picker — the second `Enter` in `fill_folder_dialog` is the suspect. See the notes at the end of [`03-aiv2lib-win.md`](03-aiv2lib-win.md).

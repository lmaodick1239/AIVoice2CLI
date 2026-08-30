# A.I.VOICE2 Automation Library Implementation Plan — Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan file-by-file. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight Windows-only Python library that focuses A.I.VOICE2 Editor, targets its active text block through Windows UI Automation, drives the current-block and batch WAV export dialogs, and returns only fully written output paths.

**Architecture:** [`aiv2lib/__init__.py`](../../../../aiv2lib/__init__.py) owns the public controller, validation, orchestration, and filesystem completion checks. [`aiv2lib/_win.py`](../../../../aiv2lib/_win.py) contains every Windows-specific operation: window lookup, focus, `SendInput`, clipboard, `#32770` dialog handling, UI Automation text targeting, and the exclusive-open probe. The controller obtains its backend through the private module function `_make_backend()`, which is the only seam tests replace.

**Tech Stack:** Python 3.10+, standard library (`ctypes`, `pathlib`, `time`, `uuid`, `sys`, `os`), `uiautomation`, `pytest` as a development dependency.

## Global Constraints

- Windows only. Constructing the controller elsewhere raises `AIV2Error("A.I.VOICE2 automation requires Windows")`.
- `ctypes`/Win32 for window focus, `SendInput`, clipboard, dialog control, and exclusive file-open checks.
- `uiautomation` only to discover and focus an enabled A.I.VOICE2 `DocumentControl` or multiline `EditControl`.
- No `pynput`, `watchdog`, `pyperclip`, AutoHotkey, coordinate clicks, fixed export-completion sleeps, callbacks, dry-run mode, or consumer wrappers.
- Exactly two package modules: [`aiv2lib/__init__.py`](../../../../aiv2lib/__init__.py) and [`aiv2lib/_win.py`](../../../../aiv2lib/_win.py).
- One exception type, `AIV2Error`, carrying a concise reason string.
- `generate_audio()` exports the current block with `Ctrl+E` to `export_dir/{uuid4().hex}.wav` and returns `pathlib.Path`.
- `batch_export_all()` exports with `Ctrl+Shift+E` into a unique `export_dir/{uuid4().hex}/` directory and returns `list[pathlib.Path]` sorted by filename.
- Legal foreground windows during export: the editor, or the specific owned `#32770` save/folder/overwrite dialog expected by the current state. Anything else is a hard failure.
- Output completion requires nonzero sizes stable across `stable_polls` polls, no directory membership changes during those polls for batch output, and a successful exclusive read-open.
- Defaults: `timeout=300.0`, `poll_interval=0.25`, `stable_polls=3`. All configurable.
- Public methods: `focus()`, `clear_block()`, `paste_text()`, `assign_voice()`, `split_block()`, `generate_audio()`, `batch_export_all()`, `wait_for_audio()`.
- No `render()` method and no `AudioResult`. Callers use `Path.open()`, `Path.read_bytes()`, or `Path.stat()`.

## Verified Product Facts

From the official manual (A.I.VOICE2 Editor 2.14.1):

| Operation | Hotkey |
|---|---|
| Export current セリフ | `Ctrl+E` |
| Batch export (all blocks) | `Ctrl+Shift+E` |
| Batch export (selected blocks) | `Ctrl+Shift+W` |
| Assign character 1–10 | `Ctrl+1` … `Ctrl+0` |
| Split block at cursor | `Ctrl+Enter` |
| Continuous play/stop | `Shift+F5` |

- Hotkeys are inert while a dialog or popup is open.
- `Ctrl+E` opens a Windows **save** dialog; batch export opens a **folder** dialog.
- Window title begins with `A.I.VOICE2 Editor`; the binary is `aivoice.exe`.
- Batch export with naming rules produced `0_この れっしゃは ふ… .wav`: block index plus truncated spoken text. A trailing UUID in long text is truncated away, so filename uniqueness must come from the dialog, not from the spoken text.
- The アクセント tab makes clear/paste pathologically slow (~15 s for 300 characters); the 音声効果 tab is ~1 s. Document this as an operator precondition.

## Plan Files, In Execution Order

| Order | Plan file | Produces |
|---|---|---|
| 1 | [`01-pyproject.md`](01-pyproject.md) | [`pyproject.toml`](../../../../pyproject.toml) |
| 2 | [`02-aiv2lib-init.md`](02-aiv2lib-init.md) | [`aiv2lib/__init__.py`](../../../../aiv2lib/__init__.py) |
| 3 | [`03-aiv2lib-win.md`](03-aiv2lib-win.md) | [`aiv2lib/_win.py`](../../../../aiv2lib/_win.py) |
| 4 | [`04-tests.md`](04-tests.md) | [`tests/test_aiv2lib.py`](../../../../tests/test_aiv2lib.py), [`tests/test_windows_smoke.py`](../../../../tests/test_windows_smoke.py) |
| 5 | [`05-readme.md`](05-readme.md) | [`README.md`](../../../../README.md) |

Files 2 and 3 are written against the backend interface frozen in [`02-aiv2lib-init.md`](02-aiv2lib-init.md#backend-interface-contract). Read that contract before implementing either.

Development order note: [`02-aiv2lib-init.md`](02-aiv2lib-init.md) creates a stub [`aiv2lib/_win.py`](../../../../aiv2lib/_win.py) so imports resolve, and [`03-aiv2lib-win.md`](03-aiv2lib-win.md) replaces it wholesale. Tests for the controller use a fake backend and never import the real one.

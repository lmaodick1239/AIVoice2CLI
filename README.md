# aiv2lib

Automate A.I.VOICE2 Editor from Python. Text in, WAV path out.

```python
from aiv2lib import AIV2Controller

controller = AIV2Controller(r"C:\audio\out")
wav = controller.generate_audio("こんにちは。", voice_index=1)
print(wav, wav.stat().st_size)
```

`generate_audio` returns a `pathlib.Path` that is fully written. Use
`wav.read_bytes()`, `wav.open("rb")`, or `shutil.copy` from there.

## Requirements

- Windows. The Editor also runs on macOS, but this library does not.
- Python 3.10+
- A.I.VOICE2 Editor, running, with a project open.
- One dependency: `uiautomation`.

```bash
pip install .
```

## Preconditions this library cannot check

These are not optional. Each one produces a confusing failure if ignored.

**The Editor must be running with at least one text block.** The library finds
the window by title prefix; it does not launch the application.

**Set the right-hand tab to 音声効果, not アクセント.** On アクセント the Editor
builds one UI element per character. Clearing a 300-character block takes
roughly 15 seconds instead of 1, and long scripts can fail outright.

**Do not use the keyboard or mouse while a call is in flight.** Every operation
is synthesized input against the foreground window. The library treats stolen
focus as a hard error rather than typing into whatever happens to be in front.

**The clipboard gets overwritten.** Text is pasted rather than typed, and the
previous clipboard contents are not restored.

## API

### `AIV2Controller(export_dir, app_title_prefix="A.I.VOICE2 Editor", timeout=300.0, poll_interval=0.25, stable_polls=3)`

`export_dir` is created if missing and checked for writability. The remaining
arguments are timing and targeting knobs; the defaults suit a normal desktop.
Raise `timeout` for very long scripts, or `poll_interval` if polling shows up in
a profile.

### `generate_audio(text, voice_index=None) -> Path`

Clears the active text block, pastes `text`, optionally assigns a character
(1–10), exports with `Ctrl+E`, and drives the save dialog to
`export_dir/<uuid>.wav`.

The UUID filename is deliberate. The Editor's own naming rules derive filenames
from the spoken text and truncate them — a 60-character line becomes
`[num]_この れっしゃは ふ….wav` — so consecutive calls may collide. Typing an
absolute path into the save dialog is the only way to get a name the caller can
rely on.

### `batch_export_all() -> list[Path]`

Exports every text block with `Ctrl+Shift+E` into a fresh
`export_dir/<uuid>/` directory, and returns the WAV files sorted by name.

Filenames come from the Editor's naming rules here, because batch export offers
a folder picker rather than a save dialog. The per-call directory is what keeps
runs from mixing.

### `wait_for_audio(path, deadline=None) -> Path`

Blocks until `path` is complete. Useful when you have driven the Editor by hand
and only need the completion check.

### Primitives

`focus()`, `clear_block()`, `paste_text(text)`, `assign_voice(index)`,
`split_block()`. Thin wrappers over the documented hotkeys, for callers that
need to compose their own flow.

There is no `render()`. The Editor has playback and export, not a separate
render step; export *is* the render.

## How completion is detected

A file existing does not mean it is finished. The library requires all of:

1. The file exists and is nonzero.
2. Its size is unchanged across `stable_polls` consecutive polls.
3. It opens for exclusive read, meaning no writer holds the handle.

Point 3 matters because the Editor writes the WAV header before the sample
data. A header-only file can look size-stable for one poll.

Batch export additionally requires the set of files in the directory to stop
changing, so a file appearing late is not missed.

There is no `sleep()`-based "export probably finished by now" anywhere in this
library.

## Errors

One exception type, `AIV2Error`, with a short reason. Common messages:

| Message | Cause |
|---|---|
| `requires Windows` | Constructed on another platform. |
| `no visible window titled ...` | Editor not running, or title prefix differs. |
| `no editable text control found` | No text block open. |
| `N editable text controls found and none has focus` | Ambiguous UI tree; click the intended block once. |
| `focus left the Editor` | Another window took focus mid-operation. |
| `the export save dialog did not appear` | `Ctrl+E` was inert, usually because a dialog was already open. |
| `timed out waiting for <name>.wav` | The dialog was driven but no complete file arrived. |

There are no subclasses. Callers either retry the whole operation or surface the
message.

## Hotkeys used

From the [official manual](https://aivoice.jp/manual/editor2/keyboard_shortcuts.html):

| Operation | Hotkey |
|---|---|
| Export current セリフ | `Ctrl+E` |
| Batch export, all blocks | `Ctrl+Shift+E` |
| Assign character 1–10 | `Ctrl+1` … `Ctrl+0` |
| Split block at cursor | `Ctrl+Enter` |

Hotkeys do nothing while a dialog is open, which is why every export waits for
its dialog and for the Editor to regain focus afterwards.

## Not included

Sequential batching (write a `for` loop), selected-block export
(`Ctrl+Shift+W`), dry-run mode, event callbacks, macOS support. Each is a small
addition if a real workload needs it; none is here speculatively.

## Testing

```bash
python -m pytest
```

The unit suite replaces the Win32 backend with a fake and runs anywhere. The
smoke tests need a live Editor:

```bash
set AIV2_SMOKE_EXPORT_DIR=C:\temp\aiv2-smoke
python -m pytest tests/test_windows_smoke.py -v -s
```

They skip unless that variable is set.

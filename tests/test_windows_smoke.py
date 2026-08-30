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

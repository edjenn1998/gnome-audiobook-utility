import array
import subprocess
import threading

from audiobook_utility.diagnostics import record_exception
from audiobook_utility.media import merge, private_options, probe


def test_merge_audio_order_and_continuity(audio, tmp_path):
    inputs = [audio("second.flac", duration=0.6, frequency=800),
              audio("first.wav", duration=0.6, frequency=300),
              audio("third.mp3", duration=0.6, frequency=1200)]
    result = tmp_path / "ordered.m4b"
    merge(inputs, result, threading.Event())
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(result),
                                   "-ac", "1", "-ar", "48000", "-f", "s16le", "-"])
    samples = array.array("h", raw)
    for index, expected in enumerate([800, 300, 1200]):
        section = samples[round((index * 0.6 + 0.15) * 48000):round((index * 0.6 + 0.45) * 48000)]
        crossings = sum(a < 0 <= b for a, b in zip(section, section[1:]))
        assert abs(crossings / 0.3 - expected) < 10
    for boundary in (0.6, 1.2):
        section = samples[round((boundary - 0.005) * 48000):round((boundary + 0.005) * 48000)]
        assert sum(abs(x) for x in section) / len(section) > 500


def test_container_detection_ignores_extension(audio, tmp_path):
    source = audio("actual.flac")
    renamed = tmp_path / "misleading.mp3"
    source.rename(renamed)
    assert probe(renamed).codec == "flac"


def test_license_values_never_appear_in_process_arguments():
    from pathlib import Path
    fixture = "0123456789abcdef0123456789abcdef"
    with private_options(["-audible_key", fixture, "-i", "/tmp/input"]) as args:
        assert fixture not in args
        assert args[0] == "-/audible_key"
        # Anonymous RAM file is accessible only while the operation owns its descriptor.
        assert Path(args[1]).read_text() == fixture
        handle = Path(args[1])
    assert not handle.exists()


def test_ffprobe_can_read_anonymous_option_files(audio):
    source = audio("plain.m4a")
    # This unprotected file needs no key, but exercises FFprobe's real file-option parser.
    assert probe(source, ["-audible_key", "0123456789abcdef0123456789abcdef"]).codec == "aac"


def test_diagnostics_redact_exception_values_and_locals(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    try:
        raise ValueError("sensitive-fixture-do-not-log")
    except ValueError as exc:
        record_exception(exc)
    path = tmp_path / "audiobook-utility/diagnostics.log"
    assert "sensitive-fixture" not in path.read_text()
    assert "ValueError" in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600

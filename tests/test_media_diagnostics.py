import json
import subprocess
import sys
import threading

import pytest

from audiobook_utility.audible_service import AudibleService
from audiobook_utility.diagnostics import record_exception
from audiobook_utility.media import probe
from audiobook_utility.media import inherited_fds, memory_file
from audiobook_utility.media_diagnostics import MediaFailure
from audiobook_utility.protected_diagnostics import protected_report
from audiobook_utility.receipts import Receipts


def test_protected_conversion_in_nondumpable_parent(encrypted_aaxc, tmp_path):
    source, reference, voucher = encrypted_aaxc
    output = tmp_path / "restricted.m4b"
    # Change only this disposable process's dumpability, never host ptrace policy.
    program = """
import ctypes, json, sys, threading
from pathlib import Path
from audiobook_utility.media import convert, probe
data = json.load(sys.stdin)
assert ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) == 0
options = ['-audible_key', data['key'], '-audible_iv', data['iv']]
info = probe(Path(data['source']), options)
convert(Path(data['source']), Path(data['output']), threading.Event(), input_options=options)
assert len(probe(Path(data['output'])).chapters) == len(info.chapters)
"""
    result = subprocess.run([sys.executable, "-c", program],
        input=json.dumps({**voucher, "source": str(source), "output": str(output)}),
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    from test_protected_media import decoded_audio
    assert decoded_audio(output) == decoded_audio(reference)


def test_descriptor_permission_evidence_in_restricted_parent():
    program = """
import ctypes, json
from audiobook_utility.protected_diagnostics import descriptor_checks
assert ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) == 0
print(json.dumps(descriptor_checks()))
"""
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=True)
    evidence = json.loads(result.stdout)
    assert evidence["parent_dumpable"] == 0
    assert evidence["legacy_parent_proc"] == {"readable": False, "errno": 13}
    assert evidence["inherited_child_local"] == {"readable": True}


def test_actual_ffprobe_reports_permission_denied_for_legacy_transport(encrypted_aaxc):
    source, _, voucher = encrypted_aaxc
    program = """
import ctypes, json, os, subprocess, sys
from pathlib import Path
from audiobook_utility.media import memory_file, probe, process_environment
from audiobook_utility.media_diagnostics import MediaFailure
data = json.load(sys.stdin)
assert ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) == 0
with memory_file(data['key']) as key, memory_file(data['iv']) as iv:
    result = subprocess.run(['ffprobe', '-v', 'error',
        '-/audible_key', f'/proc/{os.getpid()}/fd/{key.fd}',
        '-/audible_iv', f'/proc/{os.getpid()}/fd/{iv.fd}',
        '-show_format', '-of', 'json', data['source']],
        capture_output=True, text=True, env=process_environment())
    error = MediaFailure('ffprobe.inspect', returncode=result.returncode, stderr=result.stderr,
        paths=[data['source']], options=['-audible_key', data['key'], '-audible_iv', data['iv']])
    original_failure = error.details
info = probe(Path(data['source']), ['-audible_key', data['key'], '-audible_iv', data['iv']])
print(json.dumps({'legacy': original_failure, 'inherited_probe_codec': info.codec}))
"""
    result = subprocess.run([sys.executable, "-c", program],
        input=json.dumps({**voucher, "source": str(source)}), capture_output=True, text=True, check=True)
    evidence = json.loads(result.stdout)
    assert evidence["legacy"]["exit_status"] == 1
    assert evidence["legacy"]["cause"] == "private-file-open"
    assert "Error opening file" in evidence["legacy"]["stderr"]
    assert evidence["inherited_probe_codec"] == "aac"
    assert all(value not in result.stdout for value in voucher.values())


def test_private_descriptors_are_inherited_only_explicitly():
    import fcntl
    import os
    from pathlib import Path

    program = """
import pathlib, sys
try:
    print(pathlib.Path(sys.argv[1]).read_text())
except OSError:
    print('not-inherited')
"""
    with memory_file("public-fd-marker") as handle:
        assert str(handle).startswith("/proc/self/fd/")
        assert fcntl.fcntl(handle.fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
        allowed = subprocess.run([sys.executable, "-c", program, handle],
            pass_fds=inherited_fds([handle]), capture_output=True, text=True, check=True)
        unrelated = subprocess.run([sys.executable, "-c", program, handle],
            capture_output=True, text=True, check=True)
        assert allowed.stdout.strip() == "public-fd-marker"
        assert unrelated.stdout.strip() == "not-inherited"
        descriptor = handle.fd
    assert not Path(handle).exists()
    with pytest.raises(OSError):
        os.fstat(descriptor)


@pytest.mark.parametrize("bitrate", ["N/A", None, "", "not-numeric", 0])
def test_unknown_bitrate_does_not_reject_usable_audio(tmp_path, monkeypatch, bitrate):
    path = tmp_path / "input.aaxc"
    path.write_bytes(b"parser-fixture")
    document = {"streams": [{"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000",
                             "channels": 2, "bit_rate": bitrate, "duration": "1.25"}],
                "format": {"duration": "N/A", "bit_rate": "64000"}}
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        [], 0, json.dumps(document), ""))
    info = probe(path, ["-audible_key", "11" * 16, "-audible_iv", "22" * 16])
    assert info.duration == 1.25 and info.bitrate == 64000


def test_probe_preserves_operation_exit_and_redacted_stderr(tmp_path, monkeypatch):
    source = tmp_path / "Private Book Title.aaxc"
    source.write_bytes(b"fixture")
    key, iv = "1234567890abcdef" * 2, "abcdef1234567890" * 2
    stderr = (f"Error opening file /proc/42/fd/5: Permission denied\n"
              f"Failed to set value '{key}' for option '/audible_key'\n"
              f"Error opening input file {source}\n"
              f"Error opening https://example.invalid/?token={iv}\n")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], 1, "", stderr))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    with pytest.raises(MediaFailure) as captured:
        probe(source, ["-audible_key", key, "-audible_iv", iv])
    failure = captured.value
    assert failure.details["operation"] == "ffprobe.inspect"
    assert failure.details["exit_status"] == 1
    assert failure.details["cause"] == "private-file-permission"
    assert "Permission denied" in failure.details["stderr"]
    assert "'/audible_key'" in failure.details["stderr"]
    record_exception(failure)
    text = str(failure) + (tmp_path / "state/audiobook-utility/diagnostics.log").read_text()
    for secret in (key, iv, str(source), source.name, "https://example.invalid"):
        assert secret not in text


def test_zero_exit_invalid_audio_properties_are_identified(tmp_path, monkeypatch):
    source = tmp_path / "fixture.aaxc"
    source.touch()
    body = {"streams": [{"codec_type": "audio", "codec_name": "aac", "channels": 0,
                         "sample_rate": "0", "bit_rate": "N/A"}], "format": {"duration": "2.5"}}
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        [], 0, json.dumps(body), "[aac] channel element 0.0 is not allocated"))
    with pytest.raises(MediaFailure) as captured:
        probe(source)
    assert captured.value.details["operation"] == "ffprobe.audio_properties"
    assert captured.value.details["exit_status"] == 0
    assert captured.value.details["audio_properties"]["stream_bitrate"] == "N/A"
    assert "channel element" in captured.value.details["stderr"]


def test_redacted_on_device_report(encrypted_aaxc, tmp_path):
    from test_audible import MemoryStore

    source, _, voucher = encrypted_aaxc
    receipts = Receipts(tmp_path / "receipts.json")
    receipts.record("B000000001", source, threading.Event())
    store = MemoryStore()
    store.put("media:B000000001", voucher)
    report = protected_report(source, service=AudibleService(store, receipts=receipts))
    assert report["descriptors"]["inherited_child_local"]["readable"]
    assert report["option_transport_tests"]["ffprobe_private_option_loading"]["status"] == "passed"
    assert report["option_transport_tests"]["ffmpeg_private_option_loading"]["status"] == "passed"
    assert report["license_resolution"]["receipt_fingerprint_match"]
    assert report["license_resolution"]["key_valid_16_byte_hex"]
    assert report["protected_inspection"]["status"] == "passed"
    assert report["protected_sample_decode"]["status"] == "passed"
    text = json.dumps(report)
    for secret in (voucher["key"], voucher["iv"], "B000000001", source.name,
                   "Synthetic audiobook", "Test author", "Test voice"):
        assert secret not in text


def test_report_identifies_missing_voucher(encrypted_aaxc, tmp_path):
    from test_audible import MemoryStore

    source, _, _ = encrypted_aaxc
    receipts = Receipts(tmp_path / "missing-receipts.json")
    report = protected_report(source, service=AudibleService(MemoryStore(), receipts=receipts))
    license_status = report["license_resolution"]
    assert license_status["receipt_store"] == "missing"
    assert license_status["association_method"] == "legacy-filename"
    assert license_status["keyring_lookup"] == "missing"
    assert license_status["status"] == "failed"
    assert "protected_inspection" not in report


def test_diagnostic_cli_collects_without_creating_m4b(tmp_path):
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "tools/verify-protected.py"
    missing_source = tmp_path / "Private Missing Title.aaxc"
    destination = tmp_path / "report.json"
    result = subprocess.run([sys.executable, str(script), str(missing_source),
                             "--diagnose-only", "--report", str(destination)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(destination.read_text())
    assert report["diagnostic_revision"] == 2
    assert report["source"]["operation"] == "source.open"
    assert report["source"]["errno"] == 2
    assert missing_source.name not in destination.read_text()
    assert destination.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("*.m4b"))

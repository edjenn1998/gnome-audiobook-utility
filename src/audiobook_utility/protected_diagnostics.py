"""On-device evidence collection; no login, license request or M4B creation."""
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from . import __version__
from .audible_service import AudibleService
from .files import UtilityError
from .media import inherited_fds, memory_file, probe, process_environment, run_ffmpeg
from .media_diagnostics import MediaFailure


def tool_info(name: str) -> dict:
    executable = shutil.which(name)
    if not executable:
        return {"available": False}
    path = Path(executable).resolve()
    info = {"available": True, "executable": str(path).replace(str(Path.home()), "~"),
            "project_bundle": ".deps" in path.parts}
    try:
        result = subprocess.run([executable, "-version"], capture_output=True, text=True,
                                timeout=10, env=process_environment())
        match = re.search(rf"^{name} version ([a-zA-Z0-9.+_~-]{{1,80}})", result.stdout)
        info.update(version=match[1] if match else "unavailable", exit_status=result.returncode)
        if result.returncode:
            info["failure"] = MediaFailure(f"{name}.version", returncode=result.returncode,
                                           stderr=result.stderr, paths=[path]).details
    except (OSError, subprocess.TimeoutExpired) as exc:
        info["failure"] = type(exc).__name__
    return info


def descriptor_checks() -> dict:
    checks = {}
    try:
        checks["parent_dumpable"] = ctypes.CDLL(None).prctl(3, 0, 0, 0, 0)
    except (AttributeError, OSError):
        checks["parent_dumpable"] = "unavailable"
    try:
        value = Path("/proc/sys/kernel/yama/ptrace_scope").read_text().strip()
        checks["ptrace_scope"] = int(value) if value.isdecimal() else "unavailable"
    except OSError:
        checks["ptrace_scope"] = "unavailable"
    child = """
import json, pathlib, sys
try:
    ok = pathlib.Path(sys.argv[1]).read_text() == 'audiobook-private-fd-check'
    print(json.dumps({'readable': ok}))
except OSError as error:
    print(json.dumps({'readable': False, 'errno': error.errno}))
"""
    with memory_file("audiobook-private-fd-check") as private:
        for name, path, fds in [
            ("inherited_child_local", private, inherited_fds([private])),
            ("legacy_parent_proc", f"/proc/{os.getpid()}/fd/{private.fd}", ()),
        ]:
            try:
                result = subprocess.run([sys.executable, "-c", child, path],
                    capture_output=True, text=True, timeout=10, pass_fds=fds,
                    env=process_environment())
                checks[name] = json.loads(result.stdout)
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                checks[name] = {"failure": type(exc).__name__}
    return checks


def failure_details(error: Exception, operation: str) -> dict:
    if isinstance(error, MediaFailure):
        return {"status": "failed", **error.details}
    # No arbitrary exception strings: they may contain paths or third-party data.
    result = {"status": "failed", "operation": operation, "error_type": type(error).__name__}
    if isinstance(error, OSError):
        result["errno"] = error.errno
    return result


def transport_checks(cancel: threading.Event) -> dict:
    # Public test values, not an account voucher. This checks transport/parser
    # compatibility on ordinary media, not correctness of the purchased license.
    options = ["-audible_key", "00" * 16, "-audible_iv", "11" * 16]
    result = {}
    with tempfile.TemporaryDirectory(prefix="audiobook-diagnostic-") as directory:
        sample = Path(directory) / "public-test-tone.m4a"
        try:
            run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=0.1", str(sample)],
                       0.1, cancel, operation="self_test.generate_audio")
            result["generate_audio"] = {"status": "passed"}
        except (UtilityError, OSError) as exc:
            result["generate_audio"] = failure_details(exc, "self_test.generate_audio")
            return result
        try:
            probe(sample, options)
            result["ffprobe_private_option_loading"] = {"status": "passed"}
        except (UtilityError, OSError) as exc:
            result["ffprobe_private_option_loading"] = failure_details(exc, "self_test.ffprobe_options")
        try:
            run_ffmpeg([*options, "-i", str(sample), "-map", "0:a:0", "-f", "null", "-"],
                       0.1, cancel, operation="self_test.ffmpeg_options")
            result["ffmpeg_private_option_loading"] = {"status": "passed"}
        except (UtilityError, OSError) as exc:
            result["ffmpeg_private_option_loading"] = failure_details(exc, "self_test.ffmpeg_options")
    return result


def protected_report(source: Path, cancel: threading.Event | None = None,
                     service: AudibleService | None = None) -> dict:
    cancel = cancel or threading.Event()
    report = {"diagnostic_revision": 2, "application_version": __version__,
              "private_transport": "pass_fds:/proc/self/fd", "python_version": sys.version.split()[0],
              "tools": {name: tool_info(name) for name in ("ffprobe", "ffmpeg")},
              "descriptors": descriptor_checks(), "option_transport_tests": transport_checks(cancel)}
    try:
        source = source.expanduser().resolve(strict=True)
        with source.open("rb") as stream:
            header = stream.read(32)
        brand = header[8:12].decode("ascii", errors="replace") if header[4:8] == b"ftyp" else "unknown"
        report["source"] = {"size_bytes": source.stat().st_size,
                            "brand": brand if brand in {"aaxc", "aax ", "isom", "M4A ", "M4B "} else "other"}
    except OSError as exc:
        report["source"] = failure_details(exc, "source.open")
        return report
    license_details = {}
    report["license_resolution"] = license_details
    try:
        options = (service or AudibleService()).input_options(source, cancel, license_details)
        if not options:
            license_details["status"] = "not-a-supported-protected-extension"
            return report
        license_details["status"] = "resolved-not-yet-proven-by-decoding"
    except (UtilityError, OSError) as exc:
        license_details.update(failure_details(exc, "license.resolve"))
        return report
    try:
        evidence = {}
        info = probe(source, options, evidence)
        report["protected_inspection"] = {"status": "passed", **evidence, "codec": info.codec,
            "duration": info.duration, "sample_rate": info.sample_rate, "channels": info.channels,
            "bitrate": info.bitrate, "chapter_count": len(info.chapters)}
    except (UtilityError, OSError) as exc:
        report["protected_inspection"] = failure_details(exc, "ffprobe.inspect")
        return report
    try:
        run_ffmpeg([*options, "-i", str(source), "-map", "0:a:0", "-t", "3", "-f", "null", "-"],
                   min(info.duration, 3), cancel, operation="ffmpeg.protected_sample_decode")
        report["protected_sample_decode"] = {"status": "passed", "scope": "first-3-seconds-only"}
    except (UtilityError, OSError) as exc:
        report["protected_sample_decode"] = failure_details(exc, "ffmpeg.protected_sample_decode")
    report["full_book_playback"] = "not-verified-by-this-diagnostic"
    return report

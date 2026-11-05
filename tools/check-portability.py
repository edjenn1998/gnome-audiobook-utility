"""Measure a supplied release candidate on this machine; never build or install."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New JSON report; never overwrite evidence")
    parser.add_argument("--network", action="store_true", help="Load public Amazon form only, never log in")
    args = parser.parse_args()
    image = args.image.expanduser().resolve(strict=True)
    if args.output.exists():
        parser.error("Choose a new output report")
    root = Path(__file__).resolve().parents[1]
    work_base = root / "dist/portability"
    work_base.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="check-", dir=work_base) as temporary:
        work = Path(temporary)
        runtime_base = Path(os.environ.get("AUDIOBOOK_TEST_RUNTIME_BASE", root.parent))
        with tempfile.TemporaryDirectory(prefix=".au-rt-", dir=runtime_base) as runtime:
            env = os.environ.copy()
            env.update(PYTHONDONTWRITEBYTECODE="1", XDG_RUNTIME_DIR=runtime)
            wayland = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
            previous_runtime = os.environ.get("XDG_RUNTIME_DIR")
            if previous_runtime and Path(wayland).name == wayland:
                socket = Path(previous_runtime) / wayland
                if socket.is_socket():
                    (Path(runtime) / wayland).symlink_to(socket)
            for key, name in (("TMPDIR", "tmp"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                              ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state")):
                directory = work / name
                directory.mkdir()
                env[key] = str(directory)
            for name, flags in (("runtime-diagnostics", ["--diagnose-runtime"]),
                                ("normal", ["--self-test"]),
                                ("extract-and-run", ["--appimage-extract-and-run", "--self-test"])):
                if args.network and name != "runtime-diagnostics":
                    flags.append("--network")
                try:
                    with subprocess.Popen([str(image), *flags], env=env, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True, start_new_session=True) as process:
                        try:
                            stdout, stderr = process.communicate(timeout=180)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGTERM)
                            try:
                                process.communicate(timeout=5)
                            except subprocess.TimeoutExpired:
                                os.killpg(process.pid, signal.SIGKILL)
                                process.communicate()
                            raise
                        results.append({"check": name, "exit_status": process.returncode,
                                        "stdout": stdout, "stderr": stderr})
                except subprocess.TimeoutExpired:
                    results.append({"check": name, "exit_status": None, "error": "timeout"})
    report = {"image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
              "platform": platform.platform(), "architecture": platform.machine(),
              "display_backend": os.environ.get("GDK_BACKEND", "automatic"), "checks": results,
              "passed": all(item["exit_status"] == 0 for item in results),
              "scope": "This machine only; no cross-distribution compatibility inferred."}
    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("Portability report:", args.output, "passed:", report["passed"])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

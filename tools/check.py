"""Run credential-free tests with fresh project-local state on every invocation."""
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile


def main(arguments=None):
    root = Path(__file__).resolve().parents[1]
    parent = root / "dist"
    parent.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="check-", dir=parent))
    (work / "tmp").mkdir(mode=0o700)
    # WebKit's Unix socket path must fit sockaddr_un even in a deep checkout.
    runtime = Path(tempfile.mkdtemp(prefix=".au-rt-", dir=root.parent))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONPATH=str(root / "src"), TMPDIR=str(work / "tmp"),
               XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=str(work / "config"),
               XDG_DATA_HOME=str(work / "data"), XDG_CACHE_HOME=str(work / "cache"),
               XDG_STATE_HOME=str(work / "state"))
    print("Test state:", work, flush=True)
    try:
        return subprocess.run([sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q",
                               "--basetemp=" + str(work / "pytest"),
                               "--junitxml=" + str(work / "junit.xml"),
                               *(sys.argv[1:] if arguments is None else arguments)],
                              cwd=root, env=env).returncode
    finally:
        shutil.rmtree(runtime)


if __name__ == "__main__":
    raise SystemExit(main())

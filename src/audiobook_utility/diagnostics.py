import os
import json
import traceback
from datetime import UTC, datetime
from pathlib import Path


def record_exception(error: Exception):
    """Record stack locations, never exception values, source lines, arguments or locals."""
    try:
        directory = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "audiobook-utility"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / "diagnostics.log"
        if path.exists() and path.stat().st_size > 512 * 1024:
            path.replace(directory / "diagnostics.previous.log")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(f"{datetime.now(UTC).isoformat()} {type(error).__name__}\n")
            for frame in traceback.extract_tb(error.__traceback__):
                stream.write(f"  {Path(frame.filename).name}:{frame.lineno} {frame.name}\n")
            if error.__cause__:
                stream.write(f"  caused by {type(error.__cause__).__name__}\n")
            from .media_diagnostics import MediaFailure
            if isinstance(error, MediaFailure):
                stream.write(json.dumps(error.details, ensure_ascii=True) + "\n")
    except OSError:
        pass

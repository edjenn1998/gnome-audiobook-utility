import hashlib
import json
import os
import threading
from pathlib import Path

from .files import Cancelled, staging


def digest(path: Path, cancel: threading.Event) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancel.is_set():
                raise Cancelled("File verification canceled.")
            result.update(chunk)
    return result.hexdigest()


class Receipts:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "audiobook-utility/downloads.json"

    def load(self):
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def record(self, asin: str, file: Path, cancel: threading.Event):
        data = self.load()
        data[asin] = {"path": str(file.resolve()), "size": file.stat().st_size,
                      "sha256": digest(file, cancel)}
        with staging(self.path, replace=True) as temporary:
            temporary.write_text(json.dumps(data, indent=2) + "\n")

    def verified(self, asin: str, cancel: threading.Event):
        record = self.load().get(asin)
        if not isinstance(record, dict):
            return None
        try:
            file = Path(record["path"])
            if file.is_file() and file.stat().st_size == record["size"] and digest(file, cancel) == record["sha256"]:
                return file
        except (KeyError, OSError, TypeError):
            pass
        return None

import hashlib
import json
import os
import threading
from pathlib import Path

from .files import Cancelled, UtilityError, staging


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

    def load(self, diagnostics: dict | None = None):
        try:
            data = json.loads(self.path.read_text())
            if diagnostics is not None:
                diagnostics["receipt_store"] = "readable" if isinstance(data, dict) else "invalid-structure"
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError) as exc:
            if diagnostics is not None:
                diagnostics["receipt_store"] = ("missing" if isinstance(exc, FileNotFoundError)
                                                else "invalid-json" if isinstance(exc, ValueError)
                                                else "unreadable")
            return {}

    def record(self, asin: str, file: Path, cancel: threading.Event,
               license_key: str | None = None):
        data = self.load()
        record = {"path": str(file.resolve()), "size": file.stat().st_size,
                  "sha256": digest(file, cancel)}
        if license_key:
            record["license_key"] = license_key
        old = data.get(asin)
        if isinstance(old, dict):
            previous = [{k: v for k, v in old.items() if k != "previous"}]
            previous.extend(r for r in old.get("previous", []) if isinstance(r, dict))
            record["previous"] = [r for r in previous if r.get("sha256") != record["sha256"]
                                   or r.get("license_key") != record.get("license_key")]
        data[asin] = record
        with staging(self.path, replace=True) as temporary:
            temporary.write_text(json.dumps(data, indent=2) + "\n")

    def association(self, file: Path, cancel: threading.Event,
                    diagnostics: dict | None = None) -> tuple[str, str] | None:
        """Resolve existing and moved downloads by verified bytes, not a title or path."""
        file = file.expanduser().resolve(strict=True)
        size = file.stat().st_size
        candidates = []
        known_path = False
        for asin, latest in self.load(diagnostics).items():
            if not isinstance(latest, dict):
                continue
            records = [latest, *(r for r in latest.get("previous", []) if isinstance(r, dict))]
            for record in records:
                known_path |= record.get("path") == str(file)
                if record.get("size") == size and isinstance(record.get("sha256"), str):
                    candidates.append((asin, record))
        if candidates:
            fingerprint = digest(file, cancel)
            for asin, record in candidates:
                if record["sha256"] == fingerprint:
                    if diagnostics is not None:
                        diagnostics.update(receipt_fingerprint_match=True,
                                           receipt_path_match=record.get("path") == str(file),
                                           license_scope="per-download" if record.get("license_key") else "legacy-ASIN")
                    return asin, record.get("license_key") or "media:" + asin
        if diagnostics is not None:
            diagnostics.update(receipt_fingerprint_match=False, receipt_path_match=known_path,
                               receipt_size_candidate=bool(candidates))
        if known_path:
            raise UtilityError("This AAXC file no longer matches its download record. Restore the original downloaded file before converting it.")
        return None

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

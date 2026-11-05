"""Locked download history and recoverable, non-secret publication journals."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading

from .files import Cancelled, UtilityError, staging


def digest(path: Path, cancel: threading.Event) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancel.is_set():
                raise Cancelled("File verification canceled.")
            result.update(chunk)
    return result.hexdigest()


@contextmanager
def file_lock(path: Path, blocking=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield
    finally:
        os.close(fd)


class Receipts:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "audiobook-utility/downloads.json"
        self.journal = self.path.with_name(self.path.stem + ".pending.json")
        self.lock = self.path.with_name(self.path.name + ".lock")

    def _read_json(self, path):
        try:
            value = json.loads(path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise UtilityError("Download records are unreadable or corrupt. Preserve the records/backup and restore them before retrying.") from exc
        if not isinstance(value, dict):
            raise UtilityError("Download records have an invalid structure. Restore the records or their backup.")
        return value

    @staticmethod
    def _validate_record(asin, record):
        if not isinstance(asin, str) or not re.fullmatch(r"[A-Z0-9]{10}", asin) or not isinstance(record, dict):
            raise UtilityError("Download record identity is invalid.")
        if (not isinstance(record.get("path"), str) or not Path(record["path"]).is_absolute()
                or type(record.get("size")) is not int or record["size"] < 0
                or not isinstance(record.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"])):
            raise UtilityError("Download record properties are invalid.")
        key = record.get("license_key")
        if key is not None and (not isinstance(key, str) or len(key) > 256
                                or not (key == "media:" + asin or key.startswith("media:" + asin + ":"))
                                or any(ord(c) < 32 for c in key)):
            raise UtilityError("Download license reference is invalid.")

    def _read_records(self):
        records = self._read_json(self.path)
        for asin, record in records.items():
            self._validate_record(asin, record)
            previous = record.get("previous", [])
            if not isinstance(previous, list):
                raise UtilityError("Download history is invalid; restore a valid backup.")
            for old in previous:
                self._validate_record(asin, old)
                if "previous" in old:
                    raise UtilityError("Nested download history is invalid.")
        return records

    def _read_pending(self):
        transactions = self._read_json(self.journal)
        self._validate_pending(transactions)
        return transactions

    def _validate_pending(self, transactions):
        for tx, item in transactions.items():
            if (not re.fullmatch(r"[a-f0-9]{32}", tx) or not isinstance(item, dict)
                    or item.get("state") not in {"started", "ready"}
                    or not isinstance(item.get("asin"), str) or not re.fullmatch(r"[A-Z0-9]{10}", item["asin"])
                    or not isinstance(item.get("path"), str) or not Path(item["path"]).is_absolute()):
                raise UtilityError("Pending download records are invalid; preserve them for recovery.")
            key = item.get("license_key")
            if key is not None and (not isinstance(key, str) or not re.fullmatch(
                    "media:" + item["asin"] + r":[a-f0-9]{32}", key)):
                raise UtilityError("Pending download license ownership is invalid.")
            if item["state"] == "ready":
                self._validate_record(item["asin"], item)

    def load(self, diagnostics: dict | None = None):
        try:
            with file_lock(self.lock):
                records = self._read_records()
            if diagnostics is not None:
                diagnostics["receipt_store"] = "readable" if self.path.exists() else "missing"
            return records
        except UtilityError:
            if diagnostics is not None:
                diagnostics["receipt_store"] = "invalid-or-unreadable"
            raise

    def pending(self):
        with file_lock(self.lock):
            return self._read_pending()

    def _write_json(self, path, value):
        with staging(path, replace=True) as temporary:
            temporary.write_text(json.dumps(value, indent=2) + "\n")

    def _write_records(self, records):
        old = self._read_records()
        if old:
            self._write_json(self.path.with_suffix(self.path.suffix + ".backup"), old)
        self._write_json(self.path, records)

    def _merge(self, records, asin, record):
        old = records.get(asin)
        if old:
            history = [{k: v for k, v in old.items() if k != "previous"}, *old.get("previous", [])]
            history = [item for item in history if (item["sha256"], item.get("license_key")) !=
                       (record["sha256"], record.get("license_key"))]
            if history:
                record["previous"] = history
        records[asin] = record

    def record(self, asin, file, cancel, license_key=None):
        record = {"path": str(file.expanduser().resolve()), "size": file.stat().st_size, "sha256": digest(file, cancel)}
        if license_key:
            record["license_key"] = license_key
        self._validate_record(asin, record)
        with file_lock(self.lock):
            records = self._read_records()
            self._merge(records, asin, record)
            self._write_records(records)

    def begin(self, asin, target, license_key, tx=None):
        tx = tx or secrets.token_hex(16)
        with file_lock(self.lock):
            self._read_records()  # Never silently replace a corrupt store.
            pending = self._read_pending()
            pending[tx] = {"state": "started", "asin": asin, "path": str(target.resolve()), "license_key": license_key}
            self._validate_pending(pending)
            self._write_json(self.journal, pending)
        return tx

    @contextmanager
    def claim(self, tx, blocking=True):
        with file_lock(self.path.with_name(".download-" + tx + ".lock"), blocking):
            yield

    @contextmanager
    def transaction(self, asin, target, license_key):
        tx = secrets.token_hex(16)
        with self.claim(tx):
            self.begin(asin, target, license_key, tx)
            yield tx

    def ready(self, tx, temporary, cancel):
        size, fingerprint = temporary.stat().st_size, digest(temporary, cancel)
        with file_lock(self.lock):
            pending = self._read_pending()
            pending[tx].update(state="ready", size=size, sha256=fingerprint)
            self._write_json(self.journal, pending)

    def abort(self, tx):
        with file_lock(self.lock):
            pending = self._read_pending()
            if tx in pending:
                del pending[tx]
                self._write_json(self.journal, pending)

    def commit(self, tx):
        with file_lock(self.lock):
            pending = self._read_pending()
            item = pending.get(tx)
            if not item:
                return
            if item["state"] != "ready":
                raise UtilityError("The download is not ready for publication recovery.")
            records = self._read_records()
            self._merge(records, item["asin"], {k: v for k, v in item.items() if k not in {"state", "asin"}})
            self._write_records(records)
            del pending[tx]
            self._write_json(self.journal, pending)

    @staticmethod
    def matches(item, cancel):
        path = Path(item["path"])
        try:
            return (item["state"] == "ready" and path.is_file() and path.stat().st_size == item["size"]
                    and digest(path, cancel) == item["sha256"])
        except OSError:
            return False

    def published(self, tx):
        item = self.pending().get(tx)
        return bool(item and self.matches(item, threading.Event()))

    def recover(self, delete_license, cancel):
        for tx in self.pending():
            if cancel.is_set():
                raise Cancelled("Download recovery canceled.")
            try:
                with self.claim(tx, blocking=False):
                    item = self.pending().get(tx)
                    if not item:
                        continue
                    if self.matches(item, cancel):
                        self.commit(tx)
                    else:
                        if item.get("license_key"):
                            delete_license(item["license_key"])
                        self.abort(tx)
            except BlockingIOError:
                continue  # Another process is still performing this transaction.

    def _entries(self, diagnostics=None):
        try:
            with file_lock(self.lock):
                records, pending = self._read_records(), self._read_pending()
                if diagnostics is not None:
                    diagnostics["receipt_store"] = "readable" if self.path.exists() else "missing"
        except UtilityError:
            if diagnostics is not None:
                diagnostics["receipt_store"] = "invalid-or-unreadable"
            raise
        entries = [(item["asin"], item) for item in reversed(list(pending.values())) if item["state"] == "ready"]
        for asin, latest in records.items():
            entries.extend((asin, item) for item in [latest, *latest.get("previous", [])])
        return entries

    def association(self, file, cancel, diagnostics=None):
        file = file.expanduser().resolve(strict=True)
        size, known_path, candidates = file.stat().st_size, False, []
        for asin, record in self._entries(diagnostics):
            known_path |= record["path"] == str(file)
            if record["size"] == size:
                candidates.append((asin, record))
        if candidates:
            fingerprint = digest(file, cancel)
            for asin, record in candidates:
                if record["sha256"] == fingerprint:
                    if diagnostics is not None:
                        diagnostics.update(receipt_fingerprint_match=True, receipt_path_match=record["path"] == str(file),
                                           license_scope="per-download" if record.get("license_key") else "legacy-ASIN")
                    return asin, record.get("license_key") or "media:" + asin
        if diagnostics is not None:
            diagnostics.update(receipt_fingerprint_match=False, receipt_path_match=known_path, receipt_size_candidate=bool(candidates))
        if known_path:
            raise UtilityError("This AAXC file no longer matches its download record. Restore the original downloaded file before converting it.")
        return None

    def verified(self, asin, cancel):
        for entry_asin, item in self._entries():
            if entry_asin == asin:
                try:
                    file = Path(item["path"])
                    if file.is_file() and file.stat().st_size == item["size"] and digest(file, cancel) == item["sha256"]:
                        return file
                except OSError:
                    continue
        return None

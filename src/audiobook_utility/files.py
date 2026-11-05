import os
import re
import tempfile
import unicodedata
from contextlib import contextmanager
from pathlib import Path


class UtilityError(Exception):
    """An actionable operation failure safe to display locally."""


class Cancelled(UtilityError):
    pass


def safe_name(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    value = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', "_", value).strip(" .")
    return value.encode()[:180].decode(errors="ignore") or "Audiobook"


def natural_key(path: Path):
    return [int(p) if p.isdigit() else p.casefold() for p in re.split(r"(\d+)", path.name)]


def destination(folder: Path, title: str, suffix: str, conflict: str = "rename") -> Path:
    folder = folder.expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / (safe_name(title) + suffix)
    if conflict == "fail" and candidate.exists():
        raise UtilityError("Output already exists. Choose another title or destination.")
    number = 2
    while candidate.exists():
        candidate = folder / f"{safe_name(title)} ({number}){suffix}"
        number += 1
    return candidate


def sync_directory(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def staging(target: Path, replace: bool = False):
    """Publish only verified complete files; hard links implement atomic no-clobber."""
    target = target.expanduser().absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".audiobook-", suffix=target.suffix, dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        yield temporary
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
        sync_directory(target.parent)

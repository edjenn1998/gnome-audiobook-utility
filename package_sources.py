"""One explicit, tracked public-file policy for all distributable source copies."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

PRIVATE_SUFFIXES = {".pem", ".key", ".aax", ".aaxc", ".voucher", ".mp3", ".m4b", ".m4a",
                    ".wav", ".aac", ".flac", ".ogg", ".opus", ".part", ".log", ".appimage"}
PRIVATE_PARTS = {".git", ".venv", ".deps", "dist", "build", "__pycache__", ".pytest_cache", ".ruff_cache"}


def source_files(root):
    root = Path(root).resolve()
    manifest = root / "PACKAGING_FILES.txt"
    if not manifest.resolve().is_relative_to(root):
        raise ValueError("Source manifest symlink escapes the approved root")
    names = [line.strip() for line in manifest.read_text().splitlines() if line.strip() and not line.startswith("#")]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate public source manifest entries")
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    tracked = None
    if result.returncode == 0 and Path(result.stdout.strip()).resolve() == root:
        tracked = set(subprocess.check_output(["git", "-C", str(root), "ls-files", "--cached", "-z"]).decode().split("\0"))
    for name in names:
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts or set(relative.parts) & PRIVATE_PARTS
                or relative.suffix.lower() in PRIVATE_SUFFIXES or any(p == ".env" or p.startswith(".env.") for p in relative.parts)):
            raise ValueError(f"Private/unsafe source manifest entry: {name}")
        if tracked is not None and name not in tracked:
            raise ValueError(f"Untracked source was not approved for packaging: {name}")
        path = root / relative
        if not path.is_file():
            raise ValueError(f"Missing approved source: {name}")
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or resolved.relative_to(root).as_posix() not in names:
            raise ValueError(f"Symlink escapes approved sources: {name}")
    return sorted(names)


def copy_sources(root, destination, prefix=None):
    root, destination = Path(root).resolve(), Path(destination)
    hashes = {}
    for name in source_files(root):
        if prefix is not None and not Path(name).is_relative_to(prefix):
            continue
        relative = Path(name).relative_to(prefix) if prefix else Path(name)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    return hashes


def inventory(root):
    return {name: hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() for name in source_files(root)}


def write_inventory(root, destination):
    Path(destination).write_text(json.dumps(inventory(root), indent=2) + "\n")

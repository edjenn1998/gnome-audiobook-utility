"""Package the current source and local Git state, then verify a restored checkout."""
import hashlib
import io
import json
import os
import stat
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "gnome-audiobook-utility"
ROOT_FILES = {
    ".gitignore", "CHANGELOG.md", "LICENSE", "MANIFEST.in", "README.md", "THIRD_PARTY.md",
    "MIGRATION.md", "OPENCODE_HANDOFF.md", "meson.build", "meson.options", "pyproject.toml",
    "requirements.lock", "AGENTS.md", "setup.py", "package_sources.py", "PACKAGING_FILES.txt",
    "CODE_REVIEW.md", "REMEDIATION_REPORT.md",
}
SOURCE_DIRS = {"src", "tests", "docs", "data", "tools"}
EXCLUDED_PARTS = {".venv", ".deps", "__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist"}
PRIVATE_SUFFIXES = {".pem", ".key", ".aax", ".aaxc", ".voucher", ".part", ".log", ".mp3",
                    ".m4a", ".m4b", ".aac", ".flac", ".wav", ".ogg", ".opus", ".aiff"}


def git(*arguments: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", *arguments], cwd=cwd).decode("utf-8", errors="surrogateescape")


def source_files() -> list[str]:
    paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    selected = set()
    for name in paths:
        if not name:
            continue
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Invalid repository path: {name}")
        if path.parts[0] not in SOURCE_DIRS and name not in ROOT_FILES:
            raise ValueError(f"Review unexpected file before packaging: {name}")
        if (set(path.parts) & EXCLUDED_PARTS or any(p.endswith(".egg-info") for p in path.parts)
                or path.suffix.lower() in PRIVATE_SUFFIXES or path.suffix in {".pyc", ".pyo"}
                or any(p == ".env" or p.startswith(".env.") for p in path.parts)):
            raise ValueError(f"Runtime, private or generated file selected unexpectedly: {name}")
        # Keep tracked deletions deleted; the copied Git index preserves their status.
        if (ROOT / path).exists() or (ROOT / path).is_symlink():
            selected.add(name)
    repository = ROOT / ".git"
    if not repository.is_dir() or repository.is_symlink():
        raise ValueError("Migration requires a self-contained local .git directory.")
    if (repository / "objects/info/alternates").exists():
        raise ValueError("The Git object store uses alternates and is not self-contained.")
    for path in repository.rglob("*"):
        if path.is_symlink():
            raise ValueError("Git metadata contains a non-portable symlink.")
        if path.is_file():
            if path.name.endswith(".lock"):
                raise ValueError("A Git lock is present; finish Git operations before packaging.")
            selected.add(path.relative_to(ROOT).as_posix())
    return sorted(selected)


def add_bytes(archive: tarfile.TarFile, name: str, content: bytes, mode: int, mtime: int):
    entry = tarfile.TarInfo(f"{PREFIX}/{name}")
    entry.size = len(content)
    entry.mode = mode
    entry.mtime = mtime
    archive.addfile(entry, io.BytesIO(content))


def verify(archive_path: Path, manifest: dict):
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    expected = {entry["path"]: entry for entry in manifest["files"]}
    require(len(expected) == len(manifest["files"]), "Duplicate manifest entries")
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        require(len({m.name for m in members}) == len(members), "Duplicate archive entries")
        found = set()
        for member in members:
            name = Path(member.name)
            require(not name.is_absolute() and ".." not in name.parts, "Unsafe archive path")
            require(bool(name.parts) and name.parts[0] == PREFIX and member.isfile(), "Non-portable archive member")
            relative = name.relative_to(PREFIX).as_posix()
            content = archive.extractfile(member).read()
            if relative == "MIGRATION_MANIFEST.json":
                require(json.loads(content) == manifest, "Embedded manifest mismatch")
            else:
                require(relative in expected, f"Unexpected member: {relative}")
                entry = expected[relative]
                require(len(content) == entry["size"], f"Size mismatch: {relative}")
                require(hashlib.sha256(content).hexdigest() == entry["sha256"], f"Hash mismatch: {relative}")
                require(member.mode == entry["mode"], f"Mode mismatch: {relative}")
                found.add(relative)
        require(found == set(expected), "Missing migration files")
        with tempfile.TemporaryDirectory(prefix="verify-", dir=archive_path.parent) as temporary:
            archive.extractall(temporary, filter="data")
            restored = Path(temporary) / PREFIX
            require(git("rev-parse", "HEAD", cwd=restored).strip() == manifest["git_head"], "Restored Git HEAD mismatch")
            require(git("status", "--porcelain=v1", "--untracked-files=all", cwd=restored).splitlines() == manifest["git_status"], "Restored Git status mismatch")
            git("fsck", "--full", cwd=restored)


def main():
    git("fsck", "--full")
    if git("rev-parse", "--is-shallow-repository").strip() != "false":
        raise ValueError("Fetch complete history before creating a full-history migration.")
    manifest = {
        "format_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "git_head": git("rev-parse", "HEAD").strip(),
        "git_branch": git("branch", "--show-current").strip(),
        "git_status": git("status", "--porcelain=v1", "--untracked-files=all").splitlines(),
        "excluded": ["virtual environments", "Evo native runtimes", "builds/old archives", "caches",
                     "audio downloads", "vouchers", "XDG runtime state", "desktop keyring"],
        "files": [],
    }
    output = ROOT / "dist/migration"
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"{PREFIX}-migration.tar.gz"
    temporary = output / f".{PREFIX}-migration.tar.gz.part"
    try:
        with tarfile.open(temporary, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for name in source_files():
                path = ROOT / name
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError(f"Only ordinary files are portable: {name}")
                content = path.read_bytes()
                mode = stat.S_IMODE(metadata.st_mode) & 0o777
                manifest["files"].append({"path": name, "size": len(content), "mode": mode,
                                          "sha256": hashlib.sha256(content).hexdigest()})
                add_bytes(archive, name, content, mode, int(metadata.st_mtime))
            add_bytes(archive, "MIGRATION_MANIFEST.json",
                      (json.dumps(manifest, indent=2, ensure_ascii=True) + "\n").encode(),
                      0o644, int(datetime.now(UTC).timestamp()))
        if git("rev-parse", "HEAD").strip() != manifest["git_head"]:
            raise ValueError("Git HEAD changed during packaging")
        if git("status", "--porcelain=v1", "--untracked-files=all").splitlines() != manifest["git_status"]:
            raise ValueError("Git status changed during packaging")
        verify(temporary, manifest)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    with destination.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(
        f"{checksum}  {destination.name}\n", encoding="utf-8")
    print(f"Archive: {destination}")
    print(f"SHA-256: {checksum}")
    print(f"Verified {len(manifest['files'])} files, restored Git HEAD/status, and full object store.")
    print("Git history and uncommitted changes preserved; runtime/credential/media files excluded.")


if __name__ == "__main__":
    main()

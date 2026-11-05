import io
import fcntl
import shutil
import threading
from pathlib import Path

from mutagen import File, MutagenError
from mutagen.id3 import APIC, COMM, TALB, TCON, TCOP, TDRC, TIT2, TLAN, TPE1, TPE2, TPUB, TXXX
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from PIL import Image, UnidentifiedImageError

from .files import Cancelled, UtilityError, staging

FIELDS = ("title", "artist", "narrator", "series", "series_number", "album", "genre",
          "publisher", "date", "description", "copyright", "language")
MP4_KEYS = {
    "title": "\xa9nam", "artist": "\xa9ART", "narrator": "\xa9nrt", "album": "\xa9alb",
    "genre": "\xa9gen", "date": "\xa9day", "description": "desc", "copyright": "cprt",
    "series": "----:com.apple.iTunes:SERIES", "series_number": "----:com.apple.iTunes:SERIES-PART",
    "publisher": "----:com.apple.iTunes:Publisher", "language": "----:com.apple.iTunes:LANGUAGE",
}
MP4_ALIASES = {"description": ("ldes", "\xa9des"), "publisher": ("\xa9pub",)}
ID3_KEYS = {
    "title": TIT2, "artist": TPE1, "narrator": TPE2, "album": TALB, "genre": TCON,
    "publisher": TPUB, "date": TDRC, "copyright": TCOP, "language": TLAN,
}
CUSTOM = {"series": "SERIES", "series_number": "SERIES-PART"}


def validate_artwork(data: bytes) -> tuple[bytes, str]:
    if len(data) > 20 * 1024 * 1024:
        raise UtilityError("Cover images must be no larger than 20 MiB.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise UtilityError("Choose a JPEG or PNG cover image.")
            if max(image.size) > 12000 or min(image.size) < 1 or image.width * image.height > 40_000_000:
                raise UtilityError("Cover dimensions exceed 12,000 pixels or 40 megapixels.")
            image.verify()
            mime = "image/jpeg" if image.format == "JPEG" else "image/png"
        return data, mime
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UtilityError("The cover image is invalid or too large.") from exc


def prepare_preview(data, size=(320, 400)):
    """Return bounded preview bytes; original artwork is kept separately."""
    validate_artwork(data)
    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail(size, Image.Resampling.LANCZOS)
        preview = image.convert("RGBA")
        output = io.BytesIO()
        preview.save(output, format="PNG")
        return output.getvalue()


def load(path: Path):
    try:
        audio = File(path)
        if not isinstance(audio, (MP3, MP4)):
            raise UtilityError("Tag editing supports MP3, M4A and M4B containers. Convert other formats first.")
        return audio
    except (MutagenError, ValueError) as exc:
        raise UtilityError("Cannot read audiobook tags.") from exc


def read_tags(path: Path) -> tuple[dict[str, str], bytes | None]:
    audio = load(path)
    values = dict.fromkeys(FIELDS, "")
    tags = audio.tags or {}
    if isinstance(audio, MP4):
        for field, key in MP4_KEYS.items():
            keys = ("ldes", key, "\xa9des") if field == "description" else (key, *MP4_ALIASES.get(field, ()))
            raw = next((tags[k][0] for k in keys if tags.get(k)), "")
            values[field] = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        art = tags.get("covr", [None])[0]
        return values, bytes(art) if art else None
    for field, frame in ID3_KEYS.items():
        item = tags.get(frame.__name__)
        values[field] = str(item) if item else ""
    for field, desc in CUSTOM.items():
        item = tags.get(f"TXXX:{desc}")
        values[field] = str(item) if item else ""
    if audio.tags:
        comments = audio.tags.getall("COMM")
        preferred = next((c for c in comments if c.desc == "description"), None)
        standard = next((c for c in comments if c.desc == ""), None)
        values["description"] = str(preferred or standard) if preferred or standard else ""
        covers = audio.tags.getall("APIC")
        return values, covers[0].data if covers else None
    return values, None


def write_tags(path: Path, values: dict[str, str], artwork: bytes | None):
    """Update only supplied fields, preserving unknown tags. None removes all artwork."""
    unknown = set(values) - set(FIELDS)
    if unknown:
        raise UtilityError(f"Unsupported metadata fields: {', '.join(sorted(unknown))}")
    if any(not isinstance(v, str) or len(v) > 1_000_000 or "\x00" in v for v in values.values()):
        raise UtilityError("Metadata must be text without NUL characters (at most 1 MB per field).")
    mime = validate_artwork(artwork)[1] if artwork else None
    audio = load(path)
    if audio.tags is None:
        audio.add_tags()
    try:
        if isinstance(audio, MP4):
            for field, value in values.items():
                key = MP4_KEYS[field]
                audio.tags.pop(key, None)
                for alias in MP4_ALIASES.get(field, ()):
                    audio.tags.pop(alias, None)
                if value:
                    audio.tags[key] = [MP4FreeForm(value.encode()) if key.startswith("----") else value]
                    if field == "description":
                        # Players commonly use ldes for full-length summaries.
                        audio.tags["ldes"] = [value]
                    elif field == "publisher":
                        audio.tags["\xa9pub"] = [value]
            audio.tags.pop("covr", None)
            if artwork:
                audio.tags["covr"] = [MP4Cover(artwork, imageformat=MP4Cover.FORMAT_JPEG if mime == "image/jpeg" else MP4Cover.FORMAT_PNG)]
        else:
            for field, value in values.items():
                if field in ID3_KEYS:
                    frame = ID3_KEYS[field]
                    audio.tags.delall(frame.__name__)
                    if value:
                        audio.tags.add(frame(encoding=3, text=[value]))
                elif field in CUSTOM:
                    desc = CUSTOM[field]
                    audio.tags.delall(f"TXXX:{desc}")
                    if value:
                        audio.tags.add(TXXX(encoding=3, desc=desc, text=[value]))
                elif field == "description":
                    for comment in audio.tags.getall("COMM"):
                        if comment.desc in {"", "description"}:
                            del audio.tags[comment.HashKey]
                    if value:
                        audio.tags.add(COMM(encoding=3, lang="eng", desc="description", text=[value]))
            audio.tags.delall("APIC")
            if artwork:
                audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=artwork))
        audio.save()
    except (MutagenError, ValueError, TypeError) as exc:
        raise UtilityError("Could not write tags. No source file was replaced.") from exc


def edit(path: Path, values: dict[str, str], artwork: bytes | None,
         cancel: threading.Event | None = None):
    path = path.resolve(strict=True)
    with path.open("rb") as source:
        try:
            fcntl.flock(source.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UtilityError("Another operation is editing this file. Try again after it finishes.") from exc
        return _edit_locked(path, values, artwork, cancel)


def _edit_locked(path: Path, values: dict[str, str], artwork: bytes | None,
                 cancel: threading.Event | None):
    from .media import probe, verify
    before = path.stat()
    info = probe(path)
    with staging(path, replace=True) as temporary:
        with path.open("rb") as source, temporary.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                if cancel and cancel.is_set():
                    raise Cancelled("Metadata edit canceled; the original is unchanged.")
                output.write(chunk)
        shutil.copystat(path, temporary)
        write_tags(temporary, values, artwork)
        verify(temporary, info.duration)
        readback, actual_art = read_tags(temporary)
        if any(readback[k] != v for k, v in values.items()) or actual_art != artwork:
            raise UtilityError("Tag verification failed; the original was preserved.")
        now = path.stat()
        if (now.st_ino, now.st_mtime_ns, now.st_size) != (before.st_ino, before.st_mtime_ns, before.st_size):
            raise UtilityError("The source changed during editing. Reload before saving.")
        if cancel and cancel.is_set():
            raise Cancelled("Metadata edit canceled; the original is unchanged.")
    return path

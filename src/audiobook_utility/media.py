import json
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .files import Cancelled, UtilityError, staging

Progress = Callable[[float, str], None]


@dataclass
class MediaInfo:
    path: Path
    codec: str
    duration: float
    bitrate: int
    sample_rate: int
    channels: int
    size: int
    chapters: list[dict]
    tags: dict


def dependencies() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise UtilityError(f"Install the FFmpeg package (missing {', '.join(missing)}).")


def probe(path: Path, input_options: list[str] | None = None) -> MediaInfo:
    dependencies()
    path = path.expanduser().resolve(strict=True)
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", *(input_options or []), "-show_format", "-show_streams",
             "-show_chapters", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, check=True,
        )
        data = json.loads(result.stdout)
        audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
        fmt = data["format"]
        duration = float(fmt.get("duration", audio.get("duration", 0)))
        if duration <= 0:
            raise ValueError("No duration")
        return MediaInfo(path, audio["codec_name"], duration,
                         int(audio.get("bit_rate", fmt.get("bit_rate", 0))),
                         int(audio.get("sample_rate", 0)), int(audio.get("channels", 0)),
                         path.stat().st_size, data.get("chapters", []), fmt.get("tags", {}))
    except (subprocess.SubprocessError, ValueError, KeyError, StopIteration) as exc:
        raise UtilityError("Cannot inspect audio. The file may be corrupt, unsupported or protected.") from exc


def run_ffmpeg(args: list[str], duration: float, cancel: threading.Event,
               progress: Progress = lambda *_: None):
    dependencies()
    if cancel.is_set():
        raise Cancelled("Operation canceled.")
    # stderr goes to a bounded-lifetime file, avoiding pipe deadlock and unbounded memory.
    with tempfile.TemporaryFile(mode="w+b") as errors:
        process = subprocess.Popen(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-progress", "pipe:1", *args], stdout=subprocess.PIPE, stderr=errors,
            text=True,
        )
        def watch():
            while process.poll() is None:
                if cancel.wait(0.1):
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    return
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            for line in process.stdout:
                if line.startswith("out_time_us="):
                    try:
                        progress(min(0.99, int(line.split("=", 1)[1]) / 1e6 / duration), "Processing audio")
                    except ValueError:
                        pass
            status = process.wait()
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
            watcher.join(timeout=4)
        if cancel.is_set():
            raise Cancelled("Operation canceled; originals are unchanged.")
        if status:
            # Never include command arguments: protected-input options can contain secrets.
            errors.seek(0)
            detail = errors.read(4096).decode(errors="replace")
            if any(k in args for k in ("-activation_bytes", "-audible_key", "-audible_iv")):
                detail = "Protected audio could not be decoded by this FFmpeg build."
            raise UtilityError(f"FFmpeg failed. Check format support and available disk space.\n{detail}")


def verify(path: Path, duration: float, chapters: list[tuple[str, float, float]] | None = None):
    info = probe(path)
    if abs(info.duration - duration) > max(0.3, duration * 0.002):
        raise UtilityError("Output duration did not match the input. Output was discarded.")
    if chapters is not None:
        if len(info.chapters) != len(chapters):
            raise UtilityError("Chapter verification failed.")
        for actual, (_, start, end) in zip(info.chapters, chapters):
            if abs(float(actual["start_time"]) - start) > 0.02 or abs(float(actual["end_time"]) - end) > 0.03:
                raise UtilityError("Chapter timestamps did not match the audio timeline.")
    return info


def convert(source: Path, target: Path, cancel: threading.Event,
            progress: Progress = lambda *_: None, bitrate: int = 96,
            input_options: list[str] | None = None):
    info = probe(source, input_options)
    if target.suffix.lower() not in {".mp3", ".m4b"}:
        raise UtilityError("Select an M4B or MP3 output.")
    codec = "libmp3lame" if target.suffix.lower() == ".mp3" else "aac"
    copying = codec == "aac" and info.codec == "aac"
    with staging(target) as temporary:
        args = [*(input_options or []), "-i", str(info.path), "-map", "0:a:0",
                "-map", "0:v?", "-map_metadata", "0", "-map_chapters", "0",
                "-c:a", "copy" if copying else codec, "-c:v", "copy"]
        if not copying:
            args += ["-b:a", f"{bitrate}k"]
        if codec == "aac":
            args += ["-movflags", "+faststart", "-f", "mp4"]
        else:
            args += ["-id3v2_version", "3"]
        run_ffmpeg([*args, str(temporary)], info.duration, cancel, progress)
        verify(temporary, info.duration)
        # Mutagen maps audiobook-specific tags not understood consistently by FFmpeg.
        from .metadata import read_tags, write_tags
        try:
            tags, artwork = read_tags(source)
        except UtilityError:
            tags, artwork = {}, None
        write_tags(temporary, tags, artwork)
        verify(temporary, info.duration)
        if cancel.is_set():
            raise Cancelled("Conversion canceled.")
    progress(1, "Conversion complete")
    return target


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", " ").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")


def merge(sources: list[Path], target: Path, cancel: threading.Event,
          progress: Progress = lambda *_: None, titles: list[str] | None = None,
          bitrate: int = 96, chapters: bool = True, tags: dict | None = None,
          artwork: bytes | None = None, temporary_dir: Path | None = None):
    if not sources:
        raise UtilityError("Import at least one track.")
    if target.suffix.lower() not in {".m4b", ".mp3"}:
        raise UtilityError("Select an M4B or MP3 output.")
    infos = [probe(p) for p in sources]
    total = sum(i.duration for i in infos)
    if titles is not None and len(titles) != len(infos):
        raise UtilityError("Each track needs a chapter title.")
    if temporary_dir:
        temporary_dir.mkdir(parents=True, exist_ok=True)
    required = int(total * 48000 * 2 * 2 * 1.1)
    if shutil.disk_usage(temporary_dir or tempfile.gettempdir()).free < required:
        raise UtilityError("Insufficient temporary disk space; merging needs about 192 KB per second of audio.")
    with tempfile.TemporaryDirectory(prefix="audiobook-", dir=temporary_dir) as workspace:
        work = Path(workspace)
        timeline = []
        elapsed = 0.0
        combined = work / "combined.pcm"
        with combined.open("wb") as output:
            for index, info in enumerate(infos):
                pcm = work / "track.pcm"
                run_ffmpeg(["-i", str(info.path), "-map", "0:a:0", "-vn", "-ar", "48000",
                            "-ac", "2", "-c:a", "pcm_s16le", "-f", "s16le", str(pcm)],
                           info.duration, cancel,
                           lambda p, s, i=index: progress((i + p) / (len(infos) + 1), s))
                seconds = pcm.stat().st_size / (48000 * 2 * 2)
                if seconds <= 0:
                    raise UtilityError("An input track decoded to empty audio.")
                title = titles[index] if titles else info.tags.get("title", info.path.stem)
                timeline.append((title, elapsed, elapsed + seconds))
                elapsed += seconds
                with pcm.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        if cancel.is_set():
                            raise Cancelled("Merge canceled.")
                        output.write(chunk)
                pcm.unlink()
        metadata = work / "chapters.txt"
        text = ";FFMETADATA1\n"
        for title, start, end in timeline if chapters else []:
            text += f"[CHAPTER]\nTIMEBASE=1/1000000\nSTART={round(start * 1e6)}\nEND={round(end * 1e6)}\ntitle={_escape(title)}\n"
        metadata.write_text(text)
        with staging(target) as temporary:
            is_m4b = target.suffix.lower() == ".m4b"
            run_ffmpeg(["-f", "s16le", "-ar", "48000", "-ac", "2", "-i", str(combined),
                        "-i", str(metadata), "-map", "0:a", "-map_metadata", "1",
                        "-map_chapters", "1" if is_m4b and chapters else "-1",
                        "-c:a", "aac" if is_m4b else "libmp3lame", "-b:a", f"{bitrate}k",
                        *( ["-movflags", "+faststart", "-f", "mp4"] if is_m4b else ["-id3v2_version", "3"] ),
                        str(temporary)], elapsed, cancel,
                       lambda p, s: progress((len(infos) + p) / (len(infos) + 1), s))
            from .metadata import read_tags, write_tags
            original_tags, original_art = read_tags(sources[0]) if infos[0].codec in {"aac", "mp3"} else ({}, None)
            write_tags(temporary, tags if tags is not None else original_tags,
                       artwork if artwork is not None else original_art)
            verify(temporary, elapsed, timeline if is_m4b and chapters else None)
            if cancel.is_set():
                raise Cancelled("Merge canceled.")
    progress(1, "Merge complete")
    return target

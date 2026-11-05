import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .files import Cancelled, UtilityError, staging
from .media_diagnostics import MediaFailure, positive_number, probe_properties, redact_stderr

Progress = Callable[[float, str], None]


PROTECTED_OPTIONS = {"-activation_bytes": 8, "-audible_key": 32, "-audible_iv": 32}


def protected_format(path: Path) -> str | None:
    """Identify Audible ISO-BMFF brands before trusting a filename's suffix."""
    path = path.expanduser().resolve(strict=True)
    with path.open("rb") as stream:
        header = stream.read(4096)
    offset = 0
    while offset + 8 <= len(header):
        size = int.from_bytes(header[offset:offset + 4], "big")
        kind = header[offset + 4:offset + 8]
        if size < 8 or size > len(header) - offset:
            break
        if kind == b"ftyp" and size >= 16:
            brands = [header[offset + 8:offset + 12]]
            brands += [header[i:i + 4] for i in range(offset + 16, offset + size, 4)]
            if b"aaxc" in brands:
                return "aaxc"
            if b"aax " in brands:
                return "aax"
        offset += size
    # Legacy/corrupt named Audible inputs still require an explicit license.
    return path.suffix.lower()[1:] if path.suffix.lower() in {".aax", ".aaxc"} else None


class PrivatePath(str):
    """A child-local memfd path retaining the descriptor to inherit at exec."""

    def __new__(cls, fd: int):
        instance = super().__new__(cls, f"/proc/self/fd/{fd}")
        instance.fd = fd
        return instance


def inherited_fds(arguments: list[str]) -> tuple[int, ...]:
    return tuple(sorted({arg.fd for arg in arguments if isinstance(arg, PrivatePath)}))


@contextmanager
def memory_file(content: str):
    fd = os.memfd_create("audio-input", flags=os.MFD_CLOEXEC)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(os.dup(fd), "wb") as stream:
            stream.write(content.encode("utf-8"))
        os.lseek(fd, 0, os.SEEK_SET)
        yield PrivatePath(fd)
    finally:
        os.close(fd)


def process_environment():
    # FFREPORT can raise the log level and record decrypted demuxer option values.
    return {key: value for key, value in os.environ.items() if key != "FFREPORT"}


@contextmanager
def private_options(arguments: list[str], *, tool: str = "ffprobe"):
    """Keep demuxer credentials in RAM, never in subprocess arguments.

    FFprobe accepts file-valued AVOptions. FFmpeg 8's separate argument parser
    does not, so its concat demuxer loads per-file options from a one-file script.
    """
    from contextlib import ExitStack

    result = []
    pending = {}
    with ExitStack() as stack:
        iterator = iter(arguments)
        for arg in iterator:
            if arg in PROTECTED_OPTIONS:
                value = next(iterator, None)
                if not isinstance(value, str) or not re.fullmatch(
                        rf"[0-9a-fA-F]{{{PROTECTED_OPTIONS[arg]}}}", value):
                    raise UtilityError("The saved Audible media license has an invalid key or IV. Download the title again to obtain a valid license.")
                if tool == "ffprobe":
                    handle = stack.enter_context(memory_file(value))
                    result.extend(["-/" + arg[1:], handle])
                else:
                    pending[arg[1:]] = value
            elif tool == "ffmpeg" and arg == "-i" and pending:
                source = next(iterator, None)
                if not source or "\n" in source or "\r" in source:
                    raise UtilityError("Rename the protected input to remove line breaks before converting it.")
                escaped = str(Path(source).resolve()).replace("'", "'\\''")
                script = f"ffconcat version 1.0\nfile '{escaped}'\n"
                script += "".join(f"option {key} {value}\n" for key, value in pending.items())
                handle = stack.enter_context(memory_file(script))
                result.extend(["-f", "concat", "-safe", "0", "-i", handle])
                pending.clear()
            else:
                result.append(arg)
        if pending:
            raise UtilityError("Protected media options must belong to an input file.")
        yield result


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


def probe(path: Path, input_options: list[str] | None = None,
          diagnostics: dict | None = None) -> MediaInfo:
    dependencies()
    path = path.expanduser().resolve(strict=True)
    try:
        with private_options(input_options or []) as options:
            result = subprocess.run(
                ["ffprobe", "-v", "error", *options, "-show_format", "-show_streams",
                 "-show_chapters", "-of", "json", str(path)],
                capture_output=True, text=True, timeout=60, check=False,
                env=process_environment(),
                pass_fds=inherited_fds(options),
            )
    except subprocess.TimeoutExpired as exc:
        raise MediaFailure("ffprobe.inspect", reason="timeout", stderr=exc.stderr,
                           paths=[path], options=input_options or []) from None
    except OSError as exc:
        raise MediaFailure("ffprobe.start", reason=f"executable-os-error-{exc.errno}") from None
    if diagnostics is not None:
        diagnostics.update(operation="ffprobe.inspect", exit_status=result.returncode)
        if result.stderr:
            diagnostics["stderr"] = redact_stderr(result.stderr, paths=[path], options=input_options or [])
    if result.returncode:
        raise MediaFailure("ffprobe.inspect", returncode=result.returncode, stderr=result.stderr,
                           paths=[path], options=input_options or [])
    try:
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError("Invalid document")
        audio = next(s for s in data.get("streams", []) if s.get("codec_type") == "audio")
        fmt = data.get("format", {})
        if not isinstance(fmt, dict):
            raise ValueError("Invalid format document")
    except (ValueError, TypeError, AttributeError, StopIteration):
        raise MediaFailure("ffprobe.parse_json", reason="invalid-json", returncode=0,
                           stderr=result.stderr, paths=[path], options=input_options or []) from None
    duration = positive_number(fmt.get("duration")) or positive_number(audio.get("duration"))
    sample_rate = positive_number(audio.get("sample_rate"))
    channels = positive_number(audio.get("channels"))
    codec = audio.get("codec_name")
    if duration is None or sample_rate is None or channels is None or not isinstance(codec, str):
        raise MediaFailure("ffprobe.audio_properties", reason="invalid-audio-properties", returncode=0,
                           stderr=result.stderr, paths=[path], options=input_options or [],
                           properties=probe_properties(data))
    # Bitrate is optional. FFprobe may emit N/A even for otherwise valid audio.
    bitrate = positive_number(audio.get("bit_rate")) or positive_number(fmt.get("bit_rate")) or 0
    if diagnostics is not None:
        diagnostics["audio_properties"] = probe_properties(data)
    return MediaInfo(path, codec, duration, int(bitrate), int(sample_rate), int(channels),
                     path.stat().st_size, data.get("chapters", []), fmt.get("tags", {}))


def run_ffmpeg(args: list[str], duration: float, cancel: threading.Event,
               progress: Progress = lambda *_: None, *, operation: str = "ffmpeg.process"):
    dependencies()
    if cancel.is_set():
        raise Cancelled("Operation canceled.")
    # stderr goes to a bounded-lifetime file, avoiding pipe deadlock and unbounded memory.
    with tempfile.TemporaryFile(mode="w+b") as errors, private_options(args, tool="ffmpeg") as private_args:
        try:
            process = subprocess.Popen(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror", "-y",
                 "-progress", "pipe:1", *private_args], stdout=subprocess.PIPE, stderr=errors,
                text=True, env=process_environment(), pass_fds=inherited_fds(private_args),
            )
        except OSError as exc:
            raise MediaFailure(f"{operation}.start", reason=f"executable-os-error-{exc.errno}") from None
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
            errors.seek(0)
            detail = errors.read(16384).decode(errors="replace")
            paths = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "-i"]
            raise MediaFailure(operation, returncode=status, stderr=detail,
                               paths=[*paths, args[-1]], options=args)


def verify(path: Path, duration: float, chapters: list[tuple[str, float, float]] | None = None):
    info = probe(path)
    if abs(info.duration - duration) > max(0.3, duration * 0.002):
        raise UtilityError("Output duration did not match the input. Output was discarded.")
    if chapters is not None:
        if len(info.chapters) != len(chapters):
            raise UtilityError("Chapter verification failed.")
        for actual, (title, start, end) in zip(info.chapters, chapters):
            if abs(float(actual["start_time"]) - start) > 0.02 or abs(float(actual["end_time"]) - end) > 0.03:
                raise UtilityError("Chapter timestamps did not match the audio timeline.")
            if title and actual.get("tags", {}).get("title") != title:
                raise UtilityError("Chapter titles did not match the source.")
    return info


def convert(source: Path, target: Path, cancel: threading.Event,
            progress: Progress = lambda *_: None, bitrate: int = 96,
            input_options: list[str] | None = None):
    if protected_format(source) and not any(option in (input_options or []) for option in PROTECTED_OPTIONS):
        raise UtilityError("Protected Audible input requires its saved account media license before conversion.")
    info = probe(source, input_options)
    if target.suffix.lower() not in {".mp3", ".m4b"}:
        raise UtilityError("Select an M4B or MP3 output.")
    codec = "libmp3lame" if target.suffix.lower() == ".mp3" else "aac"
    copying = codec == "aac" and info.codec == "aac"
    protected = any(option in (input_options or []) for option in PROTECTED_OPTIONS)
    expected_chapters = [(c.get("tags", {}).get("title", ""), float(c["start_time"]),
                          float(c["end_time"])) for c in info.chapters] if codec == "aac" else None
    # A single-file concat input preserves packets, but not the child format's
    # chapters/global tags. Carry the source probe's metadata in a separate input.
    from contextlib import ExitStack
    with staging(target) as temporary, ExitStack() as stack:
        args = [*(input_options or []), "-i", str(info.path), "-map", "0:a:0",
                "-map", "0:v?"]
        if protected:
            text = ";FFMETADATA1\n"
            text += "".join(f"{_escape(key)}={_escape(value)}\n" for key, value in info.tags.items())
            for chapter in info.chapters:
                text += ("[CHAPTER]\nTIMEBASE=1/1000000\n"
                         f"START={round(float(chapter['start_time']) * 1e6)}\n"
                         f"END={round(float(chapter['end_time']) * 1e6)}\n"
                         f"title={_escape(chapter.get('tags', {}).get('title', ''))}\n")
            metadata_file = stack.enter_context(memory_file(text))
            # Preserve negative AAC priming timestamps. Concat's reported start
            # time would otherwise shift copied packets and introduce leading audio.
            # Cover artwork is copied with Mutagen, not concat's video stream.
            args = ["-copyts", *(input_options or []), "-i", str(info.path), "-f", "ffmetadata",
                    "-i", metadata_file, "-map", "0:a:0",
                    "-map_metadata", "1", "-map_chapters", "1"]
        else:
            args += ["-map_metadata", "0", "-map_chapters", "0"]
        args += ["-c:a", "copy" if copying else codec, "-c:v", "copy"]
        if not copying:
            args += ["-b:a", f"{bitrate}k"]
        if codec == "aac":
            args += ["-movflags", "+faststart", "-f", "mp4"]
        else:
            args += ["-id3v2_version", "3"]
        def encode_progress(p, text):
            progress(p * 0.8, text)
        run_ffmpeg([*args, str(temporary)], info.duration, cancel, encode_progress,
                   operation="ffmpeg.convert")
        verify(temporary, info.duration, expected_chapters)
        # Mutagen maps audiobook-specific tags not understood consistently by FFmpeg.
        from .metadata import read_tags, write_tags
        try:
            tags, artwork = read_tags(source)
        except UtilityError:
            tags, artwork = {}, None
        write_tags(temporary, tags, artwork)
        verify(temporary, info.duration, expected_chapters)
        run_ffmpeg(["-i", str(temporary), "-map", "0:a:0", "-f", "null", "-"],
                   info.duration, cancel,
                   lambda p, _: progress(0.8 + p * 0.19, "Verifying decoded audiobook"),
                   operation="ffmpeg.verify_audio")
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
    infos = []
    for path in sources:
        if cancel.is_set():
            raise Cancelled("Merge canceled.")
        infos.append(probe(path))
    total = sum(i.duration for i in infos)
    if titles is not None and len(titles) != len(infos):
        raise UtilityError("Each track needs a chapter title.")
    if temporary_dir:
        temporary_dir.mkdir(parents=True, exist_ok=True)
    required = int(((total + max(i.duration for i in infos)) * 48000 * 2 * 2
                    + total * bitrate * 1000 / 8) * 1.1)
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
                if abs(seconds - info.duration) > max(0.3, info.duration * 0.002):
                    raise UtilityError("A decoded track was shorter or longer than expected. Check the source for corruption.")
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

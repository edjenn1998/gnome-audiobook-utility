import hashlib
import subprocess
import threading

import pytest

from audiobook_utility.files import Cancelled, UtilityError, natural_key
from audiobook_utility.media import convert, merge, probe, run_ffmpeg
from audiobook_utility.metadata import edit, read_tags


def packets(path):
    return subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path),
                                    "-map", "0:a:0", "-c:a", "copy", "-f", "data", "-"])


def test_mp3_m4b_mp3_and_metadata(audio, tmp_path, artwork):
    source = audio()
    cover = artwork()
    edit(source, {"title": "Test title", "artist": "Test author", "narrator": "Voice",
                  "series": "Test series", "description": "Summary"}, cover)
    output = tmp_path / "out.m4b"
    updates = []
    convert(source, output, threading.Event(), lambda p, s: updates.append(p))
    assert probe(output).codec == "aac"
    tags, art = read_tags(output)
    assert tags["narrator"] == "Voice" and tags["title"] == "Test title"
    assert art == cover
    assert updates[-1] == 1
    mp3 = tmp_path / "back.mp3"
    convert(output, mp3, threading.Event(), bitrate=128)
    assert probe(mp3).codec == "mp3"
    assert read_tags(mp3)[0]["series"] == "Test series"
    assert read_tags(mp3)[1] == cover
    assert source.exists()


def test_aac_stream_copy(audio, tmp_path):
    source = audio("input.m4a")
    output = tmp_path / "out.m4b"
    convert(source, output, threading.Event())
    assert hashlib.sha256(packets(source)).digest() == hashlib.sha256(packets(output)).digest()


def test_cancel_and_failure_preserve_original(audio, tmp_path):
    source = audio()
    original = source.read_bytes()
    cancel = threading.Event()
    cancel.set()
    output = tmp_path / "out.m4b"
    with pytest.raises(Cancelled):
        convert(source, output, cancel)
    with pytest.raises(UtilityError):
        convert(source, output, threading.Event(), input_options=["-not-a-real-option"])
    assert not output.exists()
    assert not list(tmp_path.glob(".audiobook-*"))
    assert source.read_bytes() == original


def test_active_cancellation(tmp_path):
    cancel = threading.Event()
    output = tmp_path / "unfinished.wav"
    timer = threading.Timer(0.25, cancel.set)
    timer.start()
    with pytest.raises(Cancelled):
        run_ffmpeg(["-re", "-f", "lavfi", "-i", "sine=duration=20", str(output)],
                   20, cancel)
    timer.join()


def test_mixed_merge_chapters_and_artwork(audio, tmp_path, artwork):
    paths = [audio("track 10.flac", duration=0.7, rate=32000),
             audio("track 2.mp3", duration=0.5), audio("track 1.wav", duration=0.4, rate=22050)]
    paths.sort(key=natural_key)
    assert [p.name for p in paths] == ["track 1.wav", "track 2.mp3", "track 10.flac"]
    # Explicit reordered sequence must determine both audio and chapters.
    paths = [paths[2], paths[0], paths[1]]
    output = tmp_path / "merged.m4b"
    merge(paths, output, threading.Event(), titles=["Ten", "One", "Two"],
          tags={"title": "Merged", "artist": "Author"}, artwork=artwork())
    info = probe(output)
    assert abs(info.duration - 1.6) < 0.1
    assert [c["tags"]["title"] for c in info.chapters] == ["Ten", "One", "Two"]
    assert abs(float(info.chapters[1]["start_time"]) - 0.7) < 0.01
    assert read_tags(output)[1] == artwork()
    assert all(p.exists() for p in paths)


@pytest.mark.parametrize("format", ["mp3", "m4b"])
def test_single_merge(audio, tmp_path, format):
    source = audio("track.wav")
    output = tmp_path / f"merged.{format}"
    merge([source], output, threading.Event())
    assert abs(probe(output).duration - 0.5) < 0.1
    assert len(probe(output).chapters) == (1 if format == "m4b" else 0)


def test_many_tracks(audio, tmp_path):
    source = audio("tiny.wav", duration=0.015)
    output = tmp_path / "many.m4b"
    merge([source] * 100, output, threading.Event())
    assert len(probe(output).chapters) == 100


def test_corrupt_merge_input(audio, tmp_path):
    source = audio()
    corrupt = tmp_path / "broken.mp3"
    corrupt.write_text("not audio")
    with pytest.raises(UtilityError):
        merge([source, corrupt], tmp_path / "bad.m4b", threading.Event())
    assert not (tmp_path / "bad.m4b").exists()

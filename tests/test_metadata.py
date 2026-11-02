import hashlib

import pytest
from mutagen.id3 import TXXX
from mutagen.mp3 import MP3

from audiobook_utility.files import UtilityError
from audiobook_utility.metadata import FIELDS, edit, read_tags, validate_artwork
from test_media import packets


@pytest.mark.parametrize("suffix", ["mp3", "m4a"])
def test_metadata_artwork_and_audio_integrity(audio, artwork, suffix):
    path = audio(f"book.{suffix}")
    original = hashlib.sha256(packets(path)).digest()
    fields = dict.fromkeys(FIELDS, "Value")
    fields["date"] = "2026"
    fields["language"] = "eng"
    fields["series_number"] = "2"
    edit(path, fields, artwork())
    assert read_tags(path) == (fields, artwork())
    edit(path, {"title": "Changed"}, artwork("blue", "JPEG"))
    assert read_tags(path)[1] == artwork("blue", "JPEG")
    edit(path, {"title": ""}, None)
    assert read_tags(path)[0]["title"] == ""
    assert read_tags(path)[1] is None
    assert hashlib.sha256(packets(path)).digest() == original


def test_unknown_tags_survive(audio):
    source = audio()
    audio_file = MP3(source)
    audio_file.tags.add(TXXX(encoding=3, desc="Unrelated", text=["keep me"]))
    audio_file.save()
    edit(source, {"title": "Updated"}, None)
    assert str(MP3(source).tags["TXXX:Unrelated"]) == "keep me"


def test_invalid_art_preserves_source(audio):
    source = audio()
    original = source.read_bytes()
    with pytest.raises(UtilityError):
        edit(source, {"title": "Changed"}, b"not an image")
    assert source.read_bytes() == original
    with pytest.raises(UtilityError):
        validate_artwork(b"x" * (21 * 1024 * 1024))


def test_concurrent_metadata_edit_is_rejected(audio):
    import fcntl
    source = audio()
    with source.open("rb") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        with pytest.raises(UtilityError, match="Another operation"):
            edit(source, {"title": "Must not change"}, None)


def test_remove_standard_id3_comment(audio):
    from mutagen.id3 import COMM
    source = audio()
    audio_file = MP3(source)
    audio_file.tags.add(COMM(encoding=3, desc="", lang="eng", text=["Old summary"]))
    audio_file.save()
    assert read_tags(source)[0]["description"] == "Old summary"
    edit(source, {"description": ""}, None)
    assert read_tags(source)[0]["description"] == ""


def test_metadata_cancel_preserves_source(audio):
    import threading
    from audiobook_utility.files import Cancelled
    source = audio()
    original = source.read_bytes()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        edit(source, {"title": "Must not change"}, None, cancel)
    assert source.read_bytes() == original


@pytest.mark.parametrize("suffix", ["mp3", "m4b"])
def test_audible_summary_and_publisher_transfer(audio, artwork, tmp_path, suffix):
    import threading

    from mutagen.mp4 import MP4

    from audiobook_utility.media import convert
    from audiobook_utility.metadata import write_tags

    source = audio("audible-tags.m4a")
    write_tags(source, {"narrator": "Test narrator"}, artwork())
    original = MP4(source)
    summary = "A long audiobook summary.\n" * 400
    original.tags["\xa9des"] = [summary]
    original.tags["\xa9pub"] = ["Test publisher"]
    original.save()
    before = source.read_bytes()
    target = tmp_path / f"converted.{suffix}"
    convert(source, target, threading.Event())
    values, art = read_tags(target)
    assert values["description"] == summary
    assert values["publisher"] == "Test publisher"
    assert values["narrator"] == "Test narrator"
    assert art == artwork()
    assert source.read_bytes() == before
    edit(target, {"description": "", "publisher": ""}, art)
    assert read_tags(target)[0]["description"] == ""
    assert read_tags(target)[0]["publisher"] == ""
    if suffix == "m4b":
        assert all(key not in MP4(target).tags for key in ("desc", "ldes", "\xa9des", "\xa9pub"))

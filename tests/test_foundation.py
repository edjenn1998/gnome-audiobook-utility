from pathlib import Path

import pytest

from audiobook_utility.files import UtilityError, destination, safe_name, staging
from audiobook_utility.settings import Settings


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "config/settings.json"
    settings = Settings(output=str(tmp_path / "chosen output"), mp3_bitrate=192)
    settings.save(path)
    assert Settings.load(path) == settings
    assert Settings.load(tmp_path / "missing") == Settings()


def test_settings_validation(tmp_path):
    with pytest.raises(UtilityError):
        Settings(output="relative").save(tmp_path / "settings.json")


def test_names_and_collisions(tmp_path):
    assert safe_name("../../a\x00/b") == "_.._a__b"
    assert safe_name("...") == "Audiobook"
    assert len(safe_name("音" * 200).encode()) <= 180
    path = destination(tmp_path, "Title", ".m4b")
    path.touch()
    assert destination(tmp_path, "Title", ".m4b").name == "Title (2).m4b"
    with pytest.raises(UtilityError):
        destination(tmp_path, "Title", ".m4b", "fail")


def test_atomic_no_clobber_and_cleanup(tmp_path):
    target = tmp_path / "file.mp3"
    target.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        with staging(target) as temporary:
            temporary.write_bytes(b"other")
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_dependency_error(monkeypatch):
    from audiobook_utility.media import dependencies
    monkeypatch.setenv("PATH", "")
    with pytest.raises(UtilityError, match="Install"):
        dependencies()


def test_native_window():
    pytest.importorskip("gi")
    from audiobook_utility.ui import Application
    app = Application()
    assert app.register()
    app.activate()
    assert app.get_active_window().get_title() == "Audiobook Utility"
    app.get_active_window().destroy()

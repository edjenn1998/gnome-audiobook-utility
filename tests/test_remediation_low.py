import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import io
import time
from unittest.mock import patch

import httpx
import pytest

from audiobook_utility.files import staging
from audiobook_utility.metadata import read_tags
from audiobook_utility.thumbnails import thumbnail


def test_publication_syncs_file_and_directory(tmp_path):
    from audiobook_utility import files
    seen = []
    original = os.fsync
    def observe(fd):
        seen.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        original(fd)
    with patch.object(files.os, "fsync", observe):
        with staging(tmp_path / "published.bin") as temporary:
            temporary.write_bytes(b"synthetic data")
    assert seen == ["file", "directory"]


def test_directory_sync_failure_is_reported_without_deleting_committed_file(tmp_path):
    from audiobook_utility import files
    original = os.fsync
    def fail(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic directory sync failure")
        original(fd)
    target = tmp_path / "published.bin"
    with patch.object(files.os, "fsync", fail):
        with pytest.raises(OSError):
            with staging(target) as temporary:
                temporary.write_bytes(b"committed")
    assert target.read_bytes() == b"committed"


def test_corrupt_thumbnail_is_refetched(artwork, tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cache = tmp_path / "audiobook-utility/covers"
    cache.mkdir(parents=True)
    url = "https://images.example/cover"
    path = cache / hashlib.sha256(url.encode()).hexdigest()
    path.write_bytes(b"corrupt cache")
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: (calls.append(request) or httpx.Response(200, content=artwork())))) as client:
        assert thumbnail(url, client=client) is not None
    assert len(calls) == 1 and path.read_bytes() != b"corrupt cache"


def test_thumbnail_cache_quota_preserves_foreign_files(tmp_path):
    from audiobook_utility.thumbnails import prune_cache
    now = time.time()
    for index in range(5):
        path = tmp_path / f"{index:064x}"
        path.write_bytes(b"x" * 20)
        os.utime(path, (now + index, now))
    foreign = tmp_path / "keep.txt"
    foreign.write_text("not owned cache data")
    outside = tmp_path / "outside"
    outside.write_text("do not modify")
    (tmp_path / ("f" * 64)).symlink_to(outside)
    prune_cache(tmp_path, max_bytes=40, max_entries=2, now=now)
    retained = [p for p in tmp_path.iterdir() if len(p.name) == 64 and not p.is_symlink()]
    assert len(retained) == 2 and sum(p.stat().st_size for p in retained) <= 40
    assert foreign.read_text() == "not owned cache data" and outside.read_text() == "do not modify"


def test_thumbnail_cache_expires_only_owned_regular_files(tmp_path):
    from audiobook_utility.thumbnails import prune_cache
    expired = tmp_path / ("a" * 64)
    expired.write_bytes(b"old")
    os.utime(expired, (0, 0))
    fresh = tmp_path / ("b" * 64)
    fresh.write_bytes(b"fresh")
    prune_cache(tmp_path)
    assert not expired.exists() and fresh.read_bytes() == b"fresh"


def test_metadata_open_cancel_discard_and_save_keep_correct_state(audio, tmp_path, monkeypatch, native_app):
    from test_ui_workflows import wait
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    native_app.activate()
    window = native_app.get_active_window()
    first, second = audio("first.m4a"), audio("second.m4a")
    try:
        window.open_metadata(first)
        wait(window)
        window.tag_form.entries["title"].set_text("Unsaved title")
        assert window.tag_form.dirty
        window.open_metadata(second)
        assert window.metadata_path == first and not window.busy
        window.metadata_guard.emit("response", "cancel")
        assert window.metadata_path == first and window.tag_form.dirty
        window.open_metadata(second)
        window.metadata_guard.emit("response", "discard")
        wait(window)
        assert window.metadata_path == second and not window.tag_form.dirty
        assert read_tags(first)[0]["title"] != "Unsaved title"
        window.tag_form.entries["title"].set_text("Saved title")
        window.open_metadata(first)
        window.metadata_guard.emit("response", "save")
        wait(window)
        assert window.metadata_path == first and not window.tag_form.dirty
        assert read_tags(second)[0]["title"] == "Saved title"
    finally:
        window.destroy()


def test_failed_metadata_save_stays_dirty_and_close_can_cancel(audio, tmp_path, monkeypatch, native_app):
    from audiobook_utility import ui
    from test_ui_workflows import wait
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    native_app.activate()
    window = native_app.get_active_window()
    path = audio("book.m4a")
    original = path.read_bytes()
    failures = []
    window.error = failures.append
    try:
        window.open_metadata(path)
        wait(window)
        window.tag_form.entries["title"].set_text("Changed")
        with patch.object(ui, "edit", side_effect=OSError("synthetic disk full")):
            window.save_metadata()
            wait(window)
        assert failures and window.tag_form.dirty and path.read_bytes() == original
        assert window.close_requested() is True
        window.metadata_guard.emit("response", "cancel")
        assert window.get_visible() and window.tag_form.dirty
    finally:
        window.destroy()


def test_migration_hash_verification_survives_optimization(tmp_path):
    root = Path(__file__).parents[1]
    archive = tmp_path / "fixture.tar.gz"
    content = b"tampered"
    with tarfile.open(archive, "w:gz") as tar:
        item = tarfile.TarInfo("gnome-audiobook-utility/approved.txt")
        item.size, item.mode = len(content), 0o644
        tar.addfile(item, io.BytesIO(content))
    manifest = {"files": [{"path": "approved.txt", "size": len(content), "mode": 0o644,
                           "sha256": hashlib.sha256(b"original").hexdigest()}],
                "git_head": "fixture", "git_status": []}
    script = '''
import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('migration',sys.argv[1]); module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.git=lambda *args,**kwargs: 'fixture' if args[:1]==('rev-parse',) else ''
module.verify(__import__('pathlib').Path(sys.argv[2]),json.loads(sys.argv[3]))
'''
    result = subprocess.run([sys.executable, "-O", "-c", script, str(root / "tools/package-migration.py"), str(archive), json.dumps(manifest)],
                            capture_output=True, text=True)
    assert result.returncode != 0 and "hash" in result.stderr.lower()


def test_appimage_validation_is_explicit_under_optimization():
    path = Path(__file__).parents[1] / "tools/appimage/self_test.py"
    code = '''import importlib.util,sys
s=importlib.util.spec_from_file_location('selftest',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.require(False,'synthetic validation failed')'''
    result = subprocess.run([sys.executable, "-O", "-c", code, str(path)], capture_output=True, text=True)
    assert result.returncode != 0 and "synthetic validation failed" in result.stderr


def test_capture_refuses_missing_application_node_without_desktop_fallback():
    path = Path(__file__).parents[1] / "tools/capture.py"
    spec = importlib.util.spec_from_file_location("capture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.object(module.Gtk.WidgetPaintable, "new"), patch.object(module.Gtk.Snapshot, "new") as snapshot:
        snapshot.return_value.to_node.return_value = None
        with pytest.raises(RuntimeError, match="render|node"):
            module.application_png(object(), object(), 100, 100)


def test_capture_renders_only_application(native_app):
    from test_library_layout import settle
    path = Path(__file__).parents[1] / "tools/capture.py"
    spec = importlib.util.spec_from_file_location("capture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    native_app.activate()
    window = native_app.get_active_window()
    try:
        settle()
        data = module.application_png(window, window.get_renderer(), window.get_width(), window.get_height())
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        window.destroy()


def test_native_launcher_allocation_failure_is_useful(tmp_path):
    source = Path(__file__).parents[1] / "tools/appimage/AppRun.c"
    wrapper = tmp_path / "fail_strdup.c"
    wrapper.write_text('#include <stddef.h>\n#include <errno.h>\nchar *__wrap_strdup(const char *s){(void)s;errno=ENOMEM;return NULL;}\n')
    binary = tmp_path / "native-fixture"
    subprocess.run(["gcc", str(source), str(wrapper), "-Wl,--wrap=strdup", "-o", str(binary)], check=True, capture_output=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode != 0 and "memory" in result.stderr

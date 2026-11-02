import time

from audiobook_utility.media import probe
from audiobook_utility.metadata import read_tags
from audiobook_utility.settings import Settings


def wait(window):
    from gi.repository import GLib
    context = GLib.MainContext.default()
    deadline = time.monotonic() + 30
    while window.busy:
        while context.pending():
            context.iteration(False)
        assert time.monotonic() < deadline, "Background operation stalled"
        time.sleep(0.005)


def test_native_local_workflows(audio, artwork, tmp_path, monkeypatch, native_app):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = native_app
    app.activate()
    window = app.get_active_window()
    failures = []
    window.error = failures.append
    window.settings = Settings(output=str(tmp_path / "outputs"))
    try:
        paths = [audio("chapter 2.mp3"), audio("chapter 1.wav")]
        window.import_convert([paths[0]])
        wait(window)
        window.start_convert()
        wait(window)
        assert probe(window.last_output).codec == "aac"
        window.import_merge(paths)
        wait(window)
        assert window.tracks[0]["path"] == paths[1]
        window.move_track(0, 1)
        assert window.tracks[0]["path"] == paths[0]
        window.merge_tags.entries["title"].set_text("UI merged book")
        summary = "First paragraph.\n\nSecond paragraph with an audiobook summary." * 20
        window.merge_tags.entries["description"].set_text(summary)
        window.merge_tags.set_art(artwork())
        window.start_merge()
        wait(window)
        merged = window.last_output
        assert len(probe(merged).chapters) == 2
        window.open_metadata(merged)
        wait(window)
        assert window.tag_form.entries["title"].get_text() == "UI merged book"
        assert window.tag_form.entries["description"].get_text() == summary
        window.tag_form.entries["title"].set_text("Edited through UI")
        window.save_metadata()
        wait(window)
        assert read_tags(merged)[0]["title"] == "Edited through UI"
        assert read_tags(merged)[0]["description"] == summary
        assert read_tags(merged)[1] == artwork()
        assert not failures
        window.preferences()
        window.about()
    finally:
        window.destroy()


def test_open_shortcut_targets_current_workflow(tmp_path, monkeypatch, native_app):
    from audiobook_utility.ui import Gdk

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    native_app.activate()
    window = native_app.get_active_window()
    chosen = []
    window.choose = lambda callback, **options: chosen.append((callback, options))
    opened = []
    window.open_metadata = opened.append
    try:
        window.stack.set_visible_child_name("metadata")
        assert window.key_pressed(None, Gdk.KEY_o, 0, Gdk.ModifierType.CONTROL_MASK)
        chosen[-1][0]([tmp_path / "book.m4b"])
        assert opened == [tmp_path / "book.m4b"]
        assert not chosen[-1][1]
        window.stack.set_visible_child_name("merge")
        window.key_pressed(None, Gdk.KEY_o, 0, Gdk.ModifierType.CONTROL_MASK)
        assert chosen[-1] == (window.import_merge, {"multiple": True})
    finally:
        window.destroy()


def test_download_queue_keeps_success_and_logs_individual_failure(audio, tmp_path, monkeypatch, native_app):
    from types import SimpleNamespace

    from audiobook_utility.audible_service import Book
    from audiobook_utility.files import UtilityError

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    downloaded = audio("completed.mp3")
    books = [Book("B000000001", "Private failed title", "Author", 1, None, True),
             Book("B000000002", "Private completed title", "Author", 1, None, True)]
    calls = []
    def transfer(book, folder, cancel, progress):
        calls.append(book.asin)
        if book.asin == books[0].asin:
            raise UtilityError("Test license failure")
        return downloaded
    native_app.activate()
    window = native_app.get_active_window()
    failures = []
    window.error = failures.append
    window.service = SimpleNamespace(download_book=transfer)
    window.library_loaded(books)
    window.book_checks = {book.asin: True for book in books}
    try:
        window.download_selected()
        wait(window)
        assert calls == [book.asin for book in books]
        assert window.last_download == downloaded and books[1].local_path == downloaded
        assert window.book_checks == {books[0].asin: True, books[1].asin: False}
        assert len(failures) == 1 and "Test license failure" in failures[0]
        log = (tmp_path / "state/audiobook-utility/diagnostics.log").read_text()
        assert "transfer" in log
        assert "Private failed title" not in log and "Test license failure" not in log
    finally:
        window.destroy()

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
        window.merge_tags.set_art(artwork())
        window.start_merge()
        wait(window)
        merged = window.last_output
        assert len(probe(merged).chapters) == 2
        window.open_metadata(merged)
        wait(window)
        assert window.tag_form.entries["title"].get_text() == "UI merged book"
        window.tag_form.entries["title"].set_text("Edited through UI")
        window.save_metadata()
        wait(window)
        assert read_tags(merged)[0]["title"] == "Edited through UI"
        assert read_tags(merged)[1] == artwork()
        assert not failures
        window.set_default_size(400, 780)
        from gi.repository import GLib
        for _ in range(100):
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            time.sleep(0.002)
        assert window.get_width() <= 420
        window.preferences()
        window.about()
    finally:
        window.destroy()

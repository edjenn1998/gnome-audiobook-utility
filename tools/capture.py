"""Capture only the application's merge view using synthetic test tones."""
import subprocess
import tempfile
import time
from pathlib import Path

from audiobook_utility.ui import Application, Gio, GLib, Gtk


def application_png(window, renderer, width, height):
    paintable = Gtk.WidgetPaintable.new(window)
    snapshot = Gtk.Snapshot.new()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        raise RuntimeError("Application render node is unavailable; capture aborted")
    return renderer.render_texture(node, None).save_to_png_bytes().get_data()


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "docs/screenshots"
    output.mkdir(exist_ok=True)
    workspace_root = root / "dist/capture"
    workspace_root.mkdir(parents=True, exist_ok=True)
    app = Application()
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    app.register()
    app.activate()
    window = app.get_active_window()
    context = GLib.MainContext.default()
    try:
        with tempfile.TemporaryDirectory(dir=workspace_root) as workspace:
            tracks = []
            for index in range(1, 4):
                path = Path(workspace) / f"Chapter {index:02}.mp3"
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                                f"sine=duration=1:frequency={300 * index}", str(path)], check=True)
                tracks.append(path)
            window.stack.set_visible_child_name("merge")
            window.import_merge(tracks)
            started = time.monotonic()
            while window.busy or time.monotonic() - started < 2:
                while context.pending():
                    context.iteration(False)
                if time.monotonic() - started > 20:
                    raise RuntimeError("Import did not finish")
                time.sleep(0.01)
            data = application_png(window, window.get_renderer(), window.get_width(), window.get_height())
            (output / "merge.png").write_bytes(data)
    finally:
        window.destroy()
        app.quit()


if __name__ == "__main__":
    main()

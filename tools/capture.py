"""Capture the real merge view under Xvfb, using generated public-domain test tones."""
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import ImageGrab

from audiobook_utility.ui import Application
from gi.repository import GLib

root = Path(__file__).resolve().parents[1]
output = root / "docs/screenshots"
output.mkdir(exist_ok=True)
app = Application()
app.register()
app.activate()
window = app.get_active_window()
context = GLib.MainContext.default()
with tempfile.TemporaryDirectory(dir=root / ".deps") as workspace:
    tracks = []
    for index in range(1, 4):
        path = Path(workspace) / f"Chapter {index:02}.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        f"sine=duration=1:frequency={300 * index}", str(path)], check=True)
        tracks.append(path)
    window.stack.set_visible_child_name("merge")
    window.import_merge(tracks)
    deadline = time.monotonic() + 20
    while window.busy or time.monotonic() < deadline - 18:
        while context.pending():
            context.iteration(False)
        if time.monotonic() > deadline:
            raise RuntimeError("Import did not finish")
        time.sleep(0.01)
    ImageGrab.grab().crop((0, 0, window.get_width(), window.get_height())).save(output / "merge.png")
window.destroy()
app.quit()

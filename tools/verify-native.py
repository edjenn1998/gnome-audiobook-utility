"""Exercise both native conversion actions with an existing desktop license."""
import argparse
import threading
import time
from pathlib import Path

from audiobook_utility.files import UtilityError
from audiobook_utility.media import probe
from audiobook_utility.metadata import read_tags
from audiobook_utility.receipts import digest
from audiobook_utility.settings import Settings
from audiobook_utility.ui import Application, Gio, GLib


def wait(window, failures):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + 1800
    while window.busy:
        while context.pending():
            context.iteration(False)
        if time.monotonic() > deadline:
            window.cancel.set()
            raise UtilityError("Native operation exceeded the verification deadline.")
        time.sleep(0.01)
    if failures:
        raise UtilityError(failures[-1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.expanduser().resolve(strict=True)
    before = digest(source, threading.Event())
    app = Application()
    # Keep an existing application window and its in-memory state independent.
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    app.register()
    app.activate()
    window = app.get_active_window()
    failures = []
    window.error = failures.append
    window.settings = Settings(output=str(args.output_directory.expanduser().resolve()))
    try:
        for action in ("imported", "last-download"):
            window.convert_paths.clear()
            if action == "imported":
                window.import_convert([source])
            else:
                # Use the existing file; verification never requests another download.
                window.last_download = source
                window.convert_download()
            wait(window, failures)
            if window.convert_paths != [source]:
                raise UtilityError("The native action did not import the selected input.")
            window.start_convert()
            wait(window, failures)
            info = probe(window.last_output)
            tags, artwork = read_tags(window.last_output)
            print(f"Native {action}: {info.codec}, {info.duration:.2f} seconds, "
                  f"{len(info.chapters)} chapters, {len(tags)} metadata fields, "
                  f"cover {'present' if artwork else 'absent'}", flush=True)
        if digest(source, threading.Event()) != before:
            raise UtilityError("Source bytes changed during native verification.")
        print("Both native conversion actions completed; source unchanged.")
    finally:
        window.cancel.set()
        while window.busy:
            GLib.MainContext.default().iteration(True)
        window.destroy()
        app.quit()


if __name__ == "__main__":
    main()

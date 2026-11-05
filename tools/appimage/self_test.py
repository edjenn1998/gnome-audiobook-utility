"""Exercise the bundled runtime without touching saved account credentials."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", action="store_true", help="Also load Amazon's public login page without logging in")
    args = parser.parse_args(arguments)
    require(os.environ.get("AUDIOBOOK_APPIMAGE") == "1", "Self-test requires the AppImage runtime")
    manifest = Path("/usr/share/audiobook-utility/appimage-build.json")
    require(manifest.is_file(), "Build manifest missing")
    import audiobook_utility
    import audible
    import gi
    require(sys.prefix == "/usr", "Unexpected Python prefix")
    for module in (audiobook_utility, audible, gi):
        require(Path(module.__file__).is_relative_to("/usr/lib"), "A host Python package leaked into the runtime")
    from audiobook_utility.media import convert, merge, probe
    from audiobook_utility.metadata import edit, read_tags

    print("Bundled runtime:", json.loads(manifest.read_text())["python"], flush=True)
    with tempfile.TemporaryDirectory(prefix="audiobook-appimage-test-") as temporary:
        work = Path(temporary)
        source = work / "synthetic.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=duration=0.4", str(source)], check=True)
        target = work / "synthetic.m4b"
        convert(source, target, threading.Event())
        edit(target, {"title": "AppImage synthetic test", "description": "Paragraph one.\n\nParagraph two."}, None)
        require(read_tags(target)[0]["title"] == "AppImage synthetic test", "Metadata round-trip failed")
        require(probe(target).codec == "aac", "Conversion codec mismatch")
        merged = work / "merged.m4b"
        merge([source, source], merged, threading.Event(), titles=["One", "Two"])
        require(len(probe(merged).chapters) == 2, "Merged chapter count mismatch")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(merged), "-f", "null", "-"], check=True)
        print("Bundled FFmpeg conversion, merge, chapters, metadata and decoding: passed", flush=True)

    from audiobook_utility.login_flow import LoginRequest
    from audiobook_utility.login_window import LoginWindow, webkit_modules
    from audiobook_utility.ui import Application, Gio, GLib
    app = Application()
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    app.register()
    app.activate()
    parent = app.get_active_window()
    import io
    from PIL import Image
    image = io.BytesIO()
    Image.new("RGB", (32, 48), "blue").save(image, format="PNG")
    parent.tag_form.set_art(image.getvalue())
    deadline = time.monotonic() + 5
    while parent.tag_form.picture.get_paintable() is None:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        if time.monotonic() > deadline:
            raise RuntimeError("Bundled artwork preview timed out")
        time.sleep(0.01)
    require(parent.tag_form.picture.get_paintable() is not None, "Artwork preview missing")
    WebKit, _ = webkit_modules()
    target = "https://www.amazon.com/ap/maplanding"
    callback = target + "?openid.oa2.authorization_code=appimage-synthetic-test"
    uri = "https://www.amazon.com/ap/signin?" + urlencode({"openid.return_to": target})
    request = LoginRequest(uri, threading.Event())
    original_load = WebKit.WebView.load_uri
    def fixture(view, _):
        view.load_html(f'<html><meta http-equiv="refresh" content="0;url={callback}"></html>', "https://www.amazon.com/")
    WebKit.WebView.load_uri = fixture
    login = LoginWindow(parent, request)
    login.present()
    deadline = time.monotonic() + 30
    try:
        while not request.ready.is_set():
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            if time.monotonic() > deadline:
                raise RuntimeError("Bundled WebKit callback timed out")
            time.sleep(0.01)
        require(request.wait() == callback, "Automatic callback mismatch")
        print("Bundled GTK/Adwaita, ephemeral WebKit and automatic callback: passed", flush=True)
    finally:
        login.finish()
        WebKit.WebView.load_uri = original_load

    if args.network:
        from audible.localization import Locale
        from audible.login import build_oauth_url, create_code_verifier
        import httpx
        require(httpx.get("https://www.amazon.com/", follow_redirects=True, timeout=30).status_code < 500, "Public HTTPS request failed")
        locale = Locale("us")
        uri, _ = build_oauth_url(locale.country_code, locale.domain, locale.market_place_id, create_code_verifier())
        request = LoginRequest(uri, threading.Event())
        class NetworkLogin(LoginWindow):
            def process_terminated(self, view, reason):
                print("WebKit process termination:", reason.value_nick, flush=True)
                return super().process_terminated(view, reason)

            def load_failed(self, view, event, uri, error):
                print("WebKit network error:", error.domain, error.code, flush=True)
                return super().load_failed(view, event, uri, error)

            def tls_failed(self, view, uri, certificate, errors):
                print("WebKit TLS error flags:", int(errors), flush=True)
                return super().tls_failed(view, uri, certificate, errors)
        login = NetworkLogin(parent, request)
        result = []
        def evaluated(view, task):
            try:
                result.append(view.evaluate_javascript_finish(task).to_boolean())
            except GLib.Error:
                result.append(False)
        def loaded(view, event):
            if event == WebKit.LoadEvent.FINISHED and not request.ready.is_set():
                view.evaluate_javascript("!!document.querySelector('input[name=\"email\"],input[type=\"email\"]')", -1, None, None, None, evaluated)
        login.view.connect("load-changed", loaded)
        login.present()
        deadline = time.monotonic() + 45
        try:
            while not result:
                while GLib.MainContext.default().pending():
                    GLib.MainContext.default().iteration(False)
                if request.ready.is_set():
                    request.wait()  # Fixed, secret-safe browser errors retain their cause.
                if time.monotonic() > deadline:
                    raise RuntimeError("Bundled public Amazon login page could not load")
                time.sleep(0.01)
            require(result == [True], "Public sign-in page did not render")
            print("Bundled HTTPS/DNS/certificates and real Amazon sign-in page: passed (no account login)", flush=True)
        finally:
            login.finish()
    parent.destroy()
    app.quit()
    print("AppImage self-test completed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

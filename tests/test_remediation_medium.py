from contextlib import contextmanager
import errno
import importlib.util
import io
from pathlib import Path
import threading
from unittest.mock import patch

import httpx
import pytest

from audiobook_utility.audible_service import AudibleService, Book
from audiobook_utility.download import download
from audiobook_utility.files import Cancelled, UtilityError
from audiobook_utility.media import merge
from audiobook_utility.metadata import read_tags
from audiobook_utility.receipts import Receipts
from audiobook_utility.settings import Settings
from audiobook_utility.thumbnails import thumbnail
from test_audible import MemoryStore, item


@pytest.mark.parametrize("last_https", [False, True])
def test_redirect_downgrade_is_rejected_before_request(tmp_path, last_https):
    requests = []
    def respond(request):
        requests.append(str(request.url))
        if request.url.scheme == "https" and request.url.host == "start.example":
            return httpx.Response(302, headers={"location": "http://middle.example/book"})
        if last_https and request.url.host == "middle.example":
            return httpx.Response(302, headers={"location": "https://end.example/book"})
        return httpx.Response(200, content=b"ID3fixture", headers={"content-length": "10", "content-type": "audio/mpeg"})
    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        with pytest.raises(UtilityError, match="HTTPS|insecure"):
            download("https://start.example/book", tmp_path / "unsafe.mp3", threading.Event(), client=client)
    assert requests == ["https://start.example/book"]


def test_adts_first_track_merges_with_explicit_metadata(audio, tmp_path):
    first, second = audio("first.aac"), audio("second.wav")
    target = tmp_path / "merged.m4b"
    merge([first, second], target, threading.Event(), tags={"title": "ADTS works"})
    assert read_tags(target)[0]["title"] == "ADTS works"


def test_merge_explicit_cover_removal(audio, artwork, tmp_path):
    from audiobook_utility.metadata import edit
    from audiobook_utility.media import INHERIT_ARTWORK
    source = audio("covered.m4a")
    edit(source, {"title": "Source"}, artwork())
    kept, removed = tmp_path / "keep.m4b", tmp_path / "remove.m4b"
    merge([source], kept, threading.Event(), artwork=INHERIT_ARTWORK)
    merge([source], removed, threading.Event(), artwork=None)
    assert read_tags(kept)[1] == artwork()
    assert read_tags(removed)[1] is None


def test_corrupt_receipts_are_not_replaced(tmp_path):
    path = tmp_path / "receipts.json"
    original = '{"broken": NOT_JSON'
    path.write_text(original)
    audio = tmp_path / "synthetic.aaxc"
    audio.write_bytes(b"public fixture")
    with pytest.raises(UtilityError, match="corrupt|invalid"):
        Receipts(path).record("B000000001", audio, threading.Event())
    assert path.read_text() == original


def test_receipt_update_lock_preserves_both_writers(tmp_path):
    receipts = Receipts(tmp_path / "receipts.json")
    source = tmp_path / "synthetic.aaxc"
    source.write_bytes(b"public fixture")
    failures = []
    def record(asin):
        try:
            receipts.record(asin, source, threading.Event())
        except Exception as error:
            failures.append(error)
    threads = [threading.Thread(target=record, args=(f"B{i:09}",)) for i in range(1, 9)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not failures and len(receipts.load()) == 8


def test_local_io_error_is_not_replaced_by_network_message():
    store = MemoryStore()
    store.put("auth", {"fixture": True})
    class Auth:
        def to_dict(self):
            return {"fixture": True}
    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
    with patch("audible.Authenticator.from_dict", return_value=Auth()):
        with pytest.raises(OSError) as error:
            with AudibleService(store=store, client_factory=lambda **k: Client()).client():
                raise OSError(errno.ENOSPC, "fixture disk full")
    assert error.value.errno == errno.ENOSPC


def test_progress_dispatch_is_bounded_and_close_discards_stale_updates():
    from audiobook_utility.progress import ProgressDispatch
    callbacks, applied = [], []
    progress = ProgressDispatch(lambda value, text: applied.append((value, text)), callbacks.append)
    for i in range(10000):
        progress(i / 10000, "working")
    assert len(callbacks) == 1
    callbacks.pop()()
    assert applied == [(9999 / 10000, "working")]
    progress(1, "done")
    progress.close()
    callbacks.pop()()
    assert len(applied) == 1


def test_malformed_thumbnail_url_is_best_effort():
    with patch("httpx.Client") as client:
        assert thumbnail("https://example.invalid:not-a-port/") is None
        client.assert_not_called()


def test_thumbnail_stream_observes_cancel_without_waiting_for_large_chunk(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cancel = threading.Event()
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"small"
            cancel.set()
            yield b"next"
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Stream())))
    try:
        with pytest.raises(Cancelled):
            thumbnail("https://images.example/test", cancel=cancel, client=client)
    finally:
        client.close()


def test_temporary_directory_is_normalized_before_use():
    settings = Settings(temporary="~/AudiobookTemporary")
    settings.validate()
    assert Path(settings.temporary).is_absolute()
    assert "~" not in Path(settings.temporary).parts


def test_tolerant_library_rows_keep_unknown_rights_separate():
    missing = Book.parse({"asin": "B000000001", "title": "Unknown", "authors": None, "runtime_length_min": "N/A"})
    denied = Book.parse({"asin": "B000000002", "customer_rights": {"is_consumable_offline": False}})
    assert missing.downloadable is None and denied.downloadable is False
    assert missing.author == "" and missing.minutes is None


def test_invalid_library_row_does_not_hide_valid_rows(monkeypatch):
    service = AudibleService(store=MemoryStore())
    class Client:
        def get(self, *a, **kw):
            return {"items": [{"title": "Missing essential id"}, item(1), {"asin": "B000000002", "authors": None}]}
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    books = service.library(threading.Event())
    assert [b.asin for b in books] == ["B000000001", "B000000002"]
    assert service.library_skipped == 1


def test_prepared_cover_keeps_original_quality(artwork):
    from audiobook_utility.metadata import prepare_preview
    from PIL import Image
    data = artwork()
    preview = prepare_preview(data, (16, 16))
    assert max(Image.open(io.BytesIO(preview)).size) <= 16
    assert data == artwork()


def test_packaging_checks_versions_and_editable_records(tmp_path):
    spec = importlib.util.spec_from_file_location("appimage_builder", Path(__file__).parents[1] / "tools/build-appimage.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class Distribution:
        version = "9.9"
        metadata = {"Name": "fixture"}
        files = []
        def read_text(self, name):
            return '{"dir_info":{"editable":true}}'
    with pytest.raises(ValueError, match="version|locked"):
        module.validate_distribution(Distribution(), "1.0")
    with pytest.raises(ValueError, match="editable"):
        module.validate_distribution(Distribution(), "9.9")


def test_gtk_external_titles_are_literal(native_app, tmp_path, monkeypatch):
    from test_library_layout import settle
    from audiobook_utility.ui import Gtk
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    native_app.activate()
    window = native_app.get_active_window()
    window.stack.set_visible_child_name("audible")
    window.library_loaded([Book("B000000001", "A & <b>literal</b>", "Author & Co", 1, None, True)])
    try:
        settle()
        def rows(widget):
            from gi.repository import Adw
            if isinstance(widget, Adw.PreferencesRow):
                yield widget
            child = widget.get_first_child()
            while child:
                yield from rows(child)
                child = child.get_next_sibling()
        visible = list(rows(window.book_list))
        assert visible and all(not row.get_use_markup() for row in visible)
        assert isinstance(window.book_list, Gtk.ListView)
    finally:
        window.destroy()


def test_large_library_recycles_row_widgets(native_app, tmp_path, monkeypatch):
    from test_library_layout import settle
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    native_app.activate()
    window = native_app.get_active_window()
    window.stack.set_visible_child_name("audible")
    window.library_loaded([Book(f"B{i:09}", f"Title {i}", "Author", 1, None, True) for i in range(5000)])
    try:
        settle()
        assert window.library_model.get_n_items() == 5000
        assert window._library_widgets_created < 1000
        adjustment = window.library_scroll.get_vadjustment()
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        settle()
        assert window._library_widgets_created < 1000
    finally:
        window.destroy()


def test_cover_preparation_runs_off_main_thread_and_stale_result_is_ignored(native_app, artwork, tmp_path, monkeypatch):
    import time
    from audiobook_utility import ui
    main_thread = threading.get_ident()
    threads = []
    original = ui.prepare_preview
    def prepare(data):
        threads.append(threading.get_ident())
        return original(data)
    monkeypatch.setattr(ui, "prepare_preview", prepare)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    native_app.activate()
    window = native_app.get_active_window()
    try:
        data = artwork()
        window.tag_form.set_art(data)
        deadline = time.monotonic() + 5
        while window.tag_form.picture.get_paintable() is None:
            while ui.GLib.MainContext.default().pending():
                ui.GLib.MainContext.default().iteration(False)
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert threads and all(thread != main_thread for thread in threads)
        assert window.tag_form.artwork == data
        window.tag_form.set_art(data)
        window.tag_form.set_art(None)
        time.sleep(0.05)
        while ui.GLib.MainContext.default().pending():
            ui.GLib.MainContext.default().iteration(False)
        assert window.tag_form.picture.get_paintable() is None
    finally:
        window.destroy()


def test_secure_redirects_are_bounded_and_do_not_forward_default_authorization(tmp_path):
    from audiobook_utility.network import secure_stream
    seen = []
    def respond(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": "https://second.example/book"})
        return httpx.Response(200, content=b"public")
    with httpx.Client(headers={"Authorization": "Bearer synthetic"}, transport=httpx.MockTransport(respond)) as client:
        with secure_stream(client, "https://first.example/book") as response:
            assert response.read() == b"public"
    assert "authorization" in seen[0].headers and "authorization" not in seen[1].headers
    seen.clear()
    with httpx.Client(transport=httpx.MockTransport(lambda request: (seen.append(request) or httpx.Response(
            302, headers={"location": "/loop"})))) as client:
        with pytest.raises(UtilityError, match="too many"):
            with secure_stream(client, "https://first.example/loop"):
                pass
    assert len(seen) == 6


def test_auth_resave_failure_happens_before_transfer(tmp_path, monkeypatch):
    import audible
    from audiobook_utility import audible_service
    store = MemoryStore()
    store.put("auth", {"fixture": "old"})
    class Auth:
        def to_dict(self):
            return {"fixture": "refreshed"}
    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def post(self, *a, **k):
            return {"content_license": {"status_code": "Granted", "content_metadata": {
                "content_url": {"offline_url": "https://cdn.example/book"}, "content_reference": {"content_format": "MPEG"}}}}
    service = AudibleService(store=store, client_factory=lambda **k: Client(), receipts=Receipts(tmp_path / "records.json"))
    def fail(*a):
        raise UtilityError("Fake unavailable keyring")
    monkeypatch.setattr(store, "put", fail)
    monkeypatch.setattr(audible.Authenticator, "from_dict", lambda *a: Auth())
    with patch.object(audible_service, "download") as transfer:
        with pytest.raises(UtilityError, match="keyring"):
            service.download_book(Book.parse(item(1)), tmp_path, threading.Event())
        transfer.assert_not_called()


def test_additional_ca_is_validated_merged_and_removed_after_use(tmp_path, monkeypatch):
    import certifi
    from datetime import datetime, timedelta, timezone
    import os
    import ssl
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    spec = importlib.util.spec_from_file_location("trust", Path(__file__).parents[1] / "tools/appimage/appimage_trust.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic remediation CA")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    additional = tmp_path / "public-ca.pem"
    additional.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    monkeypatch.setenv("SSL_CERT_FILE", "previous-value")
    with module.trust_environment(base=certifi.where(), additional=additional):
        merged = Path(os.environ["SSL_CERT_FILE"])
        context = ssl.create_default_context(cafile=str(merged))
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert any(("commonName", "Synthetic remediation CA") in entry for c in context.get_ca_certs() for entry in c["subject"])
        assert merged.is_file()
    assert not merged.exists() and os.environ["SSL_CERT_FILE"] == "previous-value"
    additional.write_text("not a certificate")
    with pytest.raises(ssl.SSLError):
        with module.trust_environment(base=certifi.where(), additional=additional):
            pytest.fail("Invalid CA was accepted")


def test_native_runtime_diagnostics_do_not_need_bundled_python(tmp_path):
    import subprocess
    source = Path(__file__).parents[1] / "tools/appimage/AppRun.c"
    binary = tmp_path / "launcher-fixture"
    subprocess.run(["gcc", "-Wall", "-Wextra", str(source), "-o", str(binary)], check=True, capture_output=True)
    result = subprocess.run([str(binary), "--diagnose-runtime"], capture_output=True, text=True)
    assert result.returncode in {0, 2}
    assert "Unprivileged user namespace probe:" in result.stdout
    assert "No host policy or WebKit sandbox setting was changed" in result.stdout


def test_portability_runner_uses_supplied_fixture_without_install_or_overwrite(tmp_path):
    import json
    import subprocess
    import sys
    fake = tmp_path / "Synthetic image with spaces"
    fake.write_text("#!" + sys.executable + "\nprint('synthetic portability fixture')\n")
    fake.chmod(0o755)
    report = tmp_path / "evidence.json"
    script = Path(__file__).parents[1] / "tools/check-portability.py"
    result = subprocess.run([sys.executable, "-B", str(script), "--image", str(fake), "--output", str(report)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["passed"] and len(evidence["checks"]) == 3
    before = report.read_bytes()
    again = subprocess.run([sys.executable, "-B", str(script), "--image", str(fake), "--output", str(report)],
                           capture_output=True, text=True)
    assert again.returncode != 0 and report.read_bytes() == before


def test_thumbnail_total_deadline_stops_trickle_and_closes_response(tmp_path, monkeypatch):
    from audiobook_utility import thumbnails
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    clock = [0]
    closed = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(5):
                clock[0] += 8
                yield b"small"
        def close(self):
            closed.append(True)
    with patch.object(thumbnails.time, "monotonic", side_effect=lambda: clock[0]):
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Stream()))) as client:
            assert thumbnail("https://images.example/test", client=client) is None
    assert clock[0] == 16 and closed

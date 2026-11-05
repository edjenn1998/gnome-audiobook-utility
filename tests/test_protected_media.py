import base64
import hashlib
import json
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from audiobook_utility import audible_service
from audiobook_utility.audible_service import AudibleService
from audiobook_utility.credentials import SecretStore
from audiobook_utility.download import download
from audiobook_utility.files import Cancelled, UtilityError
from audiobook_utility.media import convert, private_options, probe
from audiobook_utility.metadata import read_tags
from audiobook_utility.receipts import Receipts


def decoded_audio(path):
    return subprocess.check_output(["ffmpeg", "-v", "error", "-xerror", "-i", str(path),
                                    "-map", "0:a:0", "-f", "s16le", "-"])


def test_aaxc_inspection_and_conversion(encrypted_aaxc, tmp_path):
    source, reference, voucher = encrypted_aaxc
    original = source.read_bytes()
    options = ["-audible_key", voucher["key"], "-audible_iv", voucher["iv"]]
    info = probe(source, options)
    assert info.codec == "aac"
    assert len(info.chapters) == 2
    output = tmp_path / "converted.m4b"
    convert(source, output, threading.Event(), input_options=options)
    assert probe(output).codec == "aac"
    assert decoded_audio(output) == decoded_audio(reference)
    assert read_tags(output) == read_tags(reference)
    assert [(c["start_time"], c["end_time"], c["tags"]["title"]) for c in probe(output).chapters] == [
        (c["start_time"], c["end_time"], c["tags"]["title"]) for c in probe(reference).chapters]
    assert source.read_bytes() == original


@pytest.fixture
def secure_store(monkeypatch):
    # Exercise SecretStore's real JSON/attribute handling without a desktop session.
    class Collection:
        def __init__(self):
            self.items = {}

        def create_item(self, label, attributes, secret, **kwargs):
            self.items[attributes["key"]] = (attributes, secret)

        def search_items(self, attributes):
            return [SimpleNamespace(get_secret=lambda value=secret: value)
                    for attrs, secret in self.items.values()
                    if all(attrs.get(k) == v for k, v in attributes.items())]
    collection = Collection()
    store = SecretStore()
    from contextlib import nullcontext
    monkeypatch.setattr(store, "_collection", lambda: nullcontext(collection))
    return store


@pytest.mark.parametrize("delivery_type", ["SinglePartBook", "MultiPartBook"])
@pytest.mark.parametrize("content_format", ["AAX_44_128", "AAX_22_64"])
def test_download_voucher_restart_move_probe_convert(encrypted_aaxc, tmp_path, secure_store, monkeypatch, delivery_type, content_format):
    source, reference, voucher = encrypted_aaxc
    asin = "B000000001"
    secure_store.put("auth", {"fixture": "existing session"})
    legacy = {"key": "55" * 16, "iv": "66" * 16}
    secure_store.put("media:" + asin, legacy)
    # Generate a real upstream-compatible encrypted license response from fixture-only identities.
    auth = SimpleNamespace(device_info={"device_serial_number": "fixture-device", "device_type": "fixture-type"},
                           customer_info={"user_id": "fixture-customer"})
    material = hashlib.sha256(b"fixture-typefixture-devicefixture-customerB000000001").digest()
    plaintext = json.dumps(voucher).encode()
    plaintext += bytes(-len(plaintext) % 16)
    encryptor = Cipher(algorithms.AES(material[:16]), modes.CBC(material[16:])).encryptor()
    encrypted_voucher = base64.b64encode(encryptor.update(plaintext) + encryptor.finalize()).decode()
    response = {"content_license": {"asin": asin, "status_code": "Granted",
        "license_response": encrypted_voucher, "content_metadata": {
            "content_url": {"offline_url": "https://cdn.example/synthetic"},
            "content_reference": {"content_format": content_format}}}}
    class Client:
        def __init__(self):
            self.auth = auth

        def post(self, endpoint, **kwargs):
            assert endpoint == f"content/{asin}/licenserequest"
            return response

        def get(self, endpoint, **kwargs):
            assert endpoint == "library" and "parent_asin" not in kwargs
            return {"items": [{"asin": asin, "title": "Title [ABRIDGED]",
                               "authors": [{"name": "Author"}], "runtime_length_min": 1,
                               "content_delivery_type": delivery_type,
                               "has_children": delivery_type == "MultiPartBook",
                               "customer_rights": {"is_consumable_offline": True}}]}
    receipts = Receipts(tmp_path / "state/downloads.json")
    service = AudibleService(secure_store, receipts=receipts)
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    body = source.read_bytes()
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, content=body, headers={"content-type": "audio/aax", "content-length": str(len(body))}))) as http:
        monkeypatch.setattr(audible_service, "download",
            lambda url, target, cancel, progress, **kw: download(url, target, cancel, progress, client=http, **kw))
        books = service.library(threading.Event())
        assert len(books) == 1 and books[0].asin == asin and books[0].downloadable
        path = service.download_book(books[0], tmp_path / "downloads", threading.Event())
    assert path.name == "Title [ABRIDGED].aaxc"
    record = receipts.load()[asin]
    assert secure_store.get(record["license_key"]) == voucher
    assert record["license_key"].startswith("media:" + asin + ":")
    assert secure_store.get("media:" + asin) == legacy
    assert secure_store.get("auth") == {"fixture": "existing session"}
    assert voucher["key"] not in receipts.path.read_text()
    assert voucher["iv"] not in receipts.path.read_text()
    fresh_service = AudibleService(secure_store, receipts=Receipts(receipts.path))
    assert fresh_service.input_options(path) == ["-audible_key", voucher["key"], "-audible_iv", voucher["iv"]]
    # The title-only filename and later renamed imports both resolve by receipt.
    moved = tmp_path / "renamed 'copy'.aaxc"
    path.rename(moved)
    fresh_service = AudibleService(secure_store, receipts=Receipts(receipts.path))
    options = fresh_service.input_options(moved)
    assert options == ["-audible_key", voucher["key"], "-audible_iv", voucher["iv"]]
    assert len(probe(moved, options).chapters) == 2
    output = tmp_path / "finished.m4b"
    convert(moved, output, threading.Event(), input_options=options)
    assert decoded_audio(output) == decoded_audio(reference)
    assert read_tags(output) == read_tags(reference)


def test_existing_receipt_and_legacy_key_survive_rename(encrypted_aaxc, tmp_path, secure_store):
    source, _, voucher = encrypted_aaxc
    receipts = Receipts(tmp_path / "downloads.json")
    receipts.record("B000000001", source, threading.Event())
    secure_store.put("media:B000000001", voucher)
    moved = tmp_path / "new name.aaxc"
    source.rename(moved)
    options = AudibleService(secure_store, receipts=receipts).input_options(moved)
    assert options == ["-audible_key", voucher["key"], "-audible_iv", voucher["iv"]]


def test_legacy_filename_uses_trailing_asin(encrypted_aaxc, tmp_path, secure_store):
    source, _, voucher = encrypted_aaxc
    renamed = source.with_name("Book [ABRIDGED] [B000000001] (2).aaxc")
    source.rename(renamed)
    secure_store.put("media:B000000001", voucher)
    service = AudibleService(secure_store, receipts=Receipts(tmp_path / "missing.json"))
    assert service.input_options(renamed)[1] == voucher["key"]


def test_receipts_keep_older_file_license(tmp_path, secure_store):
    first, second = tmp_path / "first.aaxc", tmp_path / "second.aaxc"
    first.write_bytes(b"first encrypted file")
    second.write_bytes(b"different ciphertext")
    receipts = Receipts(tmp_path / "downloads.json")
    voucher1 = {"key": "11" * 16, "iv": "22" * 16}
    voucher2 = {"key": "33" * 16, "iv": "44" * 16}
    for path, key, voucher in [(first, "media:B000000001:old", voucher1),
                               (second, "media:B000000001:new", voucher2)]:
        receipts.record("B000000001", path, threading.Event(), license_key=key)
        secure_store.put(key, voucher)
    service = AudibleService(secure_store, receipts=Receipts(receipts.path))
    assert service.input_options(first)[1] == voucher1["key"]
    assert service.input_options(second)[1] == voucher2["key"]


@pytest.mark.parametrize("voucher", [None, {}, {"key": "bad", "iv": "11" * 16},
                                    {"key": "22" * 16, "iv": "not-hex-sensitive"}])
def test_missing_or_invalid_voucher(encrypted_aaxc, tmp_path, secure_store, voucher):
    source, _, _ = encrypted_aaxc
    if voucher is not None:
        secure_store.put("media:B000000001", voucher)
    service = AudibleService(secure_store, receipts=Receipts(tmp_path / "missing.json"))
    with pytest.raises(UtilityError) as failure:
        service.input_options(source)
    assert "not-hex-sensitive" not in str(failure.value)


def test_changed_file_and_cancelled_association(tmp_path, secure_store):
    source = tmp_path / "Book [B000000001].aaxc"
    source.write_bytes(b"original ciphertext")
    receipts = Receipts(tmp_path / "downloads.json")
    receipts.record("B000000001", source, threading.Event())
    secure_store.put("media:B000000001", {"key": "11" * 16, "iv": "22" * 16})
    service = AudibleService(secure_store, receipts=receipts)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        service.input_options(source, cancel)
    source.write_bytes(b"modified ciphertext")
    with pytest.raises(UtilityError, match="no longer matches"):
        service.input_options(source)


def test_secret_transport_and_reporting(encrypted_aaxc, tmp_path, monkeypatch):
    source, _, voucher = encrypted_aaxc
    options = AudibleService.voucher_options(voucher)
    commands = []
    original_run, original_popen = subprocess.run, subprocess.Popen
    def observe_run(args, **kwargs):
        commands.append(args)
        assert "FFREPORT" not in kwargs["env"]
        return original_run(args, **kwargs)
    def observe_popen(args, **kwargs):
        commands.append(args)
        assert "FFREPORT" not in kwargs["env"]
        return original_popen(args, **kwargs)
    report = tmp_path / "must-not-exist.log"
    monkeypatch.setenv("FFREPORT", f"file={report}:level=48")
    monkeypatch.setattr(subprocess, "run", observe_run)
    monkeypatch.setattr(subprocess, "Popen", observe_popen)
    convert(source, tmp_path / "safe.m4b", threading.Event(), input_options=options)
    assert not report.exists()
    for command in commands:
        assert all(voucher[field] not in " ".join(command) for field in ("key", "iv"))
    with private_options([*options, "-i", str(source)], tool="ffmpeg") as command:
        path = Path(command[command.index("-i") + 1])
        assert path.read_text().startswith("ffconcat version 1.0\n")
        assert f"option audible_key {voucher['key']}" in path.read_text()
    assert not path.exists()


def test_wrong_key_does_not_publish_output(encrypted_aaxc, tmp_path):
    source, _, voucher = encrypted_aaxc
    original = source.read_bytes()
    output = tmp_path / "invalid.m4b"
    with pytest.raises(UtilityError):
        convert(source, output, threading.Event(), input_options=[
            "-audible_key", "00" * 16, "-audible_iv", voucher["iv"]])
    assert not output.exists()
    assert source.read_bytes() == original
    assert not list(tmp_path.glob(".audiobook-*"))


def test_aaxc_mp3_output(encrypted_aaxc, tmp_path):
    source, _, voucher = encrypted_aaxc
    output = tmp_path / "converted.mp3"
    convert(source, output, threading.Event(), bitrate=128,
            input_options=AudibleService.voucher_options(voucher))
    assert probe(output).codec == "mp3"
    assert read_tags(output)[0]["title"] == "Synthetic audiobook"
    assert decoded_audio(output)


def test_native_import_uses_saved_license(encrypted_aaxc, tmp_path, secure_store, monkeypatch, native_app):
    from test_ui_workflows import wait
    from audiobook_utility.settings import Settings

    source, reference, voucher = encrypted_aaxc
    receipts = Receipts(tmp_path / "downloads.json")
    receipts.record("B000000001", source, threading.Event())
    secure_store.put("media:B000000001", voucher)
    moved = tmp_path / "Imported book.aaxc"
    source.rename(moved)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    native_app.activate()
    window = native_app.get_active_window()
    window.service = AudibleService(secure_store, receipts=receipts)
    window.settings = Settings(output=str(tmp_path / "outputs"))
    failures = []
    window.error = failures.append
    try:
        window.import_convert([moved])
        wait(window)
        assert not failures
        subtitle = window.convert_list.get_first_child().get_subtitle()
        assert "2 chapters" in subtitle and "Audible license loaded" in subtitle
        window.start_convert()
        wait(window)
        assert not failures
        assert decoded_audio(window.last_output) == decoded_audio(reference)
        assert len(probe(window.last_output).chapters) == 2
    finally:
        window.destroy()

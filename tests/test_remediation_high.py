from contextlib import contextmanager
import errno
import importlib.util
from pathlib import Path
import shutil
import subprocess
import threading
from unittest.mock import patch

import httpx
import pytest

from audiobook_utility import audible_service
from audiobook_utility.audible_service import AudibleService, Book
from audiobook_utility.credentials import SecretStore
from audiobook_utility.files import Cancelled, UtilityError
from audiobook_utility.media import convert
from audiobook_utility.receipts import Receipts
from test_audible import MemoryStore
from test_protected_media import decoded_audio


@pytest.mark.parametrize("suffix", [".m4b", ".m4a", ".mp3", ".bin", ".aax"])
def test_protected_brand_survives_misleading_suffix(encrypted_aaxc, tmp_path, suffix):
    original, reference, voucher = encrypted_aaxc
    source = tmp_path / ("misleading" + suffix)
    shutil.copyfile(original, source)
    receipts = Receipts(tmp_path / "receipts.json")
    receipts.record("B000000001", original, threading.Event())
    store = MemoryStore()
    store.put("media:B000000001", voucher)
    service = AudibleService(store=store, receipts=receipts)
    options = service.input_options(source)
    assert options == service.voucher_options(voucher)
    target = tmp_path / "verified.m4b"
    convert(source, target, threading.Event(), input_options=options)
    assert decoded_audio(target) == decoded_audio(reference)


@pytest.mark.parametrize("suffix", [".m4b", ".mp3", ".unknown"])
def test_protected_brand_without_license_never_publishes(encrypted_aaxc, tmp_path, suffix):
    original, _, _ = encrypted_aaxc
    source = tmp_path / ("no-license" + suffix)
    shutil.copyfile(original, source)
    output = tmp_path / "must-not-exist.m4b"
    with pytest.raises(UtilityError, match="[Pp]rotected|license"):
        convert(source, output, threading.Event())
    assert not output.exists()
    assert not list(tmp_path.glob(".audiobook-*"))


@pytest.fixture
def transaction(encrypted_aaxc, tmp_path, monkeypatch):
    source, reference, voucher = encrypted_aaxc
    store = MemoryStore()
    receipts = Receipts(tmp_path / "state/downloads.json")
    service = AudibleService(store=store, receipts=receipts)
    class Client:
        auth = object()
        def post(self, *args, **kwargs):
            return {"content_license": {"status_code": "Granted", "license_response": "fixture",
                    "content_metadata": {"content_url": {"offline_url": "https://cdn.example/book"},
                                         "content_reference": {"content_format": "AAX_22_64"}}}}
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    monkeypatch.setattr("audible.aescipher.decrypt_voucher_from_licenserequest", lambda *a: voucher)
    body = source.read_bytes()
    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, content=body, headers={"content-length": str(len(body)), "content-type": "audio/aax"})))
    from audiobook_utility.download import download
    monkeypatch.setattr(audible_service, "download",
                        lambda url, target, cancel, progress, **kw: download(url, target, cancel, progress, client=http, **kw))
    yield service, receipts, store, Book("B000000001", "Transaction title", "", 1, None, True), tmp_path
    http.close()


def test_receipt_commit_failure_retains_recoverable_license(transaction):
    service, receipts, store, book, folder = transaction
    with patch.object(receipts, "_write_records", side_effect=OSError(errno.ENOSPC, "synthetic disk full")):
        path = service.download_book(book, folder / "downloads", threading.Event())
        assert path.is_file()
        assert service.input_options(path)
        assert receipts.pending()
    service.recover_downloads(threading.Event())
    assert not receipts.pending()
    assert service.input_options(path)
    service.recover_downloads(threading.Event())
    assert len(receipts.load()[book.asin].get("previous", [])) == 0


def test_journal_failure_before_publication_leaves_no_file_or_key(transaction):
    service, receipts, store, book, folder = transaction
    with patch.object(receipts, "ready", side_effect=OSError(errno.ENOSPC, "synthetic disk full")):
        with pytest.raises(OSError):
            service.download_book(book, folder / "downloads", threading.Event())
    assert not list((folder / "downloads").glob("*.aaxc"))
    assert not store.data
    assert not receipts.pending()


def test_late_cancel_after_publication_keeps_completed_transaction(transaction):
    service, receipts, store, book, folder = transaction
    cancel = threading.Event()
    def progress(fraction, text):
        if fraction == 1:
            cancel.set()
    path = service.download_book(book, folder / "downloads", cancel, progress)
    assert path.is_file() and service.input_options(path)
    assert not receipts.pending()


def test_started_transaction_recovery_deletes_only_owned_orphan(transaction):
    service, receipts, store, book, folder = transaction
    store.put("media:B000000001:old", {"fixture": "keep"})
    reference = "media:B000000001:" + "a" * 32
    receipts.begin(book.asin, folder / "unfinished.aaxc", reference)
    store.put(reference, {"fixture": "orphan"})
    service.recover_downloads(threading.Event())
    assert reference not in store.data
    assert store.get("media:B000000001:old") == {"fixture": "keep"}
    assert not receipts.pending()


def test_recovery_commits_ready_publication_once(transaction):
    service, receipts, store, book, folder = transaction
    reference = "media:" + book.asin + ":" + "b" * 32
    path = folder / "completed.aaxc"
    path.write_bytes(b"synthetic completed bytes")
    tx = receipts.begin(book.asin, path, reference)
    store.put(reference, {"key": "1" * 32, "iv": "2" * 32})
    receipts.ready(tx, path, threading.Event())
    service.recover_downloads(threading.Event())
    service.recover_downloads(threading.Event())
    assert receipts.load()[book.asin]["license_key"] == reference
    assert store.get(reference) and not receipts.pending()


def test_recovery_skips_active_transaction(transaction):
    service, receipts, store, book, folder = transaction
    with receipts.transaction(book.asin, folder / "active.aaxc", None):
        service.recover_downloads(threading.Event())
        assert len(receipts.pending()) == 1


def test_cancel_before_publication_removes_only_new_transaction(transaction):
    service, receipts, store, book, folder = transaction
    store.put("media:B000000001:legacy", {"fixture": "preserve"})
    cancel = threading.Event()
    def progress(fraction, text):
        cancel.set()
    with pytest.raises(Cancelled):
        service.download_book(book, folder / "downloads", cancel, progress)
    assert not list((folder / "downloads").glob("*.aaxc"))
    assert list(store.data) == ["media:B000000001:legacy"]
    assert not receipts.pending()


def test_logout_preserves_licenses_and_explicit_purge_preserves_session():
    store = MemoryStore()
    store.put("auth", {"fixture": "session"})
    store.put("media:fixture", {"fixture": "license"})
    service = AudibleService(store=store)
    service.disconnect()
    assert store.get("auth") is None and store.get("media:fixture")
    store.put("auth", {"fixture": "new-session"})
    service.forget_media_licenses()
    assert store.get("auth") == {"fixture": "new-session"}
    assert store.get("media:fixture") is None


def test_secret_store_delete_scope_does_not_touch_other_application(monkeypatch):
    from audiobook_utility import APP_ID
    data = {"auth": (APP_ID, "auth"), "media": (APP_ID, "media:test"), "other": ("other.app", "auth")}
    class Item:
        def __init__(self, name):
            self.name = name
        def get_attributes(self):
            app, key = data[self.name]
            return {"application": app, "key": key}
        def delete(self):
            del data[self.name]
    class Collection:
        def search_items(self, attrs):
            return [Item(name) for name in list(data)
                    if all(Item(name).get_attributes().get(k) == v for k, v in attrs.items())]
    store = SecretStore()
    monkeypatch.setattr(store, "_collection", lambda: Collection())
    store.delete("auth")
    assert set(data) == {"media", "other"}
    store.clear_media()
    assert set(data) == {"other"}


def load_sources():
    spec = importlib.util.spec_from_file_location("approved_sources", Path(__file__).parents[1] / "package_sources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packaging_uses_approved_tracked_files_only(tmp_path):
    helper = load_sources()
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "src").mkdir()
    (root / "src/public.py").write_text("PUBLIC = True\n")
    (root / "PACKAGING_FILES.txt").write_text("PACKAGING_FILES.txt\nsrc/public.py\n")
    (root / ".gitignore").write_text("*.key\n.env\n*.aaxc\n")
    subprocess.run(["git", "-C", str(root), "add", "PACKAGING_FILES.txt", "src/public.py", ".gitignore"], check=True)
    for name in (".env", "private.key", "purchased.aaxc", "untracked.py"):
        (root / "src" / name).write_text("harmless private sentinel\n")
    destination = tmp_path / "snapshot"
    helper.copy_sources(root, destination)
    assert (destination / "src/public.py").is_file()
    assert not any((destination / "src" / name).exists() for name in (".env", "private.key", "purchased.aaxc", "untracked.py"))


def test_packaging_rejects_escaping_symlink(tmp_path):
    helper = load_sources()
    root = tmp_path / "snapshot"
    root.mkdir()
    (root / "PACKAGING_FILES.txt").write_text("PACKAGING_FILES.txt\npublic.py\n")
    outside = tmp_path / "outside.py"
    outside.write_text("PRIVATE = True")
    (root / "public.py").symlink_to(outside)
    with pytest.raises(ValueError, match="[Ss]ymlink|escape"):
        helper.source_files(root)


def test_packaging_hooks_exclude_private_files_in_synthetic_sdist(tmp_path):
    import tarfile
    import sys

    root = tmp_path / "fixture-project"
    root.mkdir()
    project = Path(__file__).parents[1]
    for name in ("setup.py", "package_sources.py"):
        shutil.copyfile(project / name, root / name)
    (root / "src/demo").mkdir(parents=True)
    (root / "src/demo/__init__.py").write_text("PUBLIC = True\n")
    (root / "pyproject.toml").write_text('[project]\nname="demo-review-fixture"\nversion="0.0.0"\n[tool.setuptools.packages.find]\nwhere=["src"]\n')
    names = ["setup.py", "package_sources.py", "pyproject.toml", "PACKAGING_FILES.txt", "src/demo/__init__.py"]
    (root / "PACKAGING_FILES.txt").write_text("\n".join(names) + "\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", *names], check=True)
    (root / "src/demo/untracked.py").write_text("PRIVATE = True\n")
    (root / "src/demo/.env").write_text("HARMLESS_SENTINEL=private\n")
    subprocess.run([sys.executable, "-B", "setup.py", "sdist", "--dist-dir", "out", "build_py", "--build-lib", "out/lib"],
                   cwd=root, check=True, capture_output=True, text=True)
    archive = next((root / "out").glob("*.tar.gz"))
    with tarfile.open(archive) as tar:
        files = tar.getnames()
        assert not any("untracked.py" in name or name.endswith("/.env") for name in files)
        assert any(name.endswith("/src/demo/__init__.py") for name in files)
    assert not (root / "out/lib/demo/untracked.py").exists()


def test_license_forgetting_requires_explicit_confirmation(native_app, tmp_path, monkeypatch):
    from test_ui_workflows import wait

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    native_app.activate()
    window = native_app.get_active_window()
    store = MemoryStore()
    store.put("auth", {"fixture": "session"})
    store.put("media:fixture", {"fixture": "keep"})
    window.service = AudibleService(store=store)
    try:
        window.confirm_forget_licenses()
        assert store.get("media:fixture")
        window.forget_dialog.emit("response", "cancel")
        assert store.get("media:fixture")
        window.confirm_forget_licenses()
        window.forget_dialog.emit("response", "forget")
        wait(window)
        assert store.get("media:fixture") is None and store.get("auth")
    finally:
        window.destroy()

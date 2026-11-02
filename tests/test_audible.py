import threading
from contextlib import contextmanager

import audible
import httpx
import pytest

from audiobook_utility.audible_service import AudibleService, Book, validate_redirect
from audiobook_utility.download import download
from audiobook_utility.files import Cancelled, UtilityError
from audiobook_utility.receipts import Receipts


class MemoryStore:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def put(self, key, data):
        self.data[key] = data

    def clear(self):
        self.data.clear()


@pytest.fixture
def store():
    return MemoryStore()


def item(number):
    return {"asin": f"B{number:09}", "title": f"Book {number}", "authors": [{"name": "Author"}],
            "runtime_length_min": "60", "product_images": {"121": "https://images.example/cover.jpg"},
            "customer_rights": {"is_consumable_offline": True}}


def test_book_parsing():
    book = Book.parse({"item": item(1)})
    assert book.title == "Book 1" and book.minutes == 60 and book.downloadable
    assert book.author == "Author"
    assert not Book.parse({"asin": "B000000000"}).downloadable


def test_auth_state_and_redirect(store, monkeypatch):
    service = AudibleService(store)
    assert not service.connected()
    class Auth:
        def to_dict(self):
            return {"fixture": "non-sensitive-test-session"}
    def login(**kwargs):
        assert kwargs["locale"] == "us"
        kwargs["login_url_callback"]("https://www.amazon.com/ap/signin?openid.return_to=https%3A%2F%2Fwww.amazon.com%2Fap%2Fmaplanding")
        return Auth()
    monkeypatch.setattr(audible.Authenticator, "from_login_external", login)
    service.connect(lambda url: "https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=fixture")
    assert service.connected()
    service.disconnect()
    assert not service.connected()
    for url in ["https://evil.example/ap/maplanding?openid.oa2.authorization_code=test", "http://www.amazon.com/ap/maplanding", "https://www.amazon.com/ap/signin"]:
        with pytest.raises(UtilityError):
            validate_redirect(url)


def test_pagination_and_cancellation(store, monkeypatch):
    service = AudibleService(store)
    calls = []
    class Client:
        def get(self, endpoint, **kwargs):
            calls.append(kwargs["page"])
            return {"items": [item(i) for i in range(100)] if kwargs["page"] == 1 else [item(100)]}
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    assert len(service.library(threading.Event())) == 101
    assert calls == [1, 2]
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        service.library(cancel)


def test_session_expiration_and_network(store, monkeypatch):
    store.put("auth", {})
    monkeypatch.setattr(audible.Authenticator, "from_dict", lambda data: audible.Authenticator())
    for failure, expected in [(httpx.ConnectError("fixture"), "Check your connection"),
                              (audible.exceptions.Unauthorized(httpx.Response(401, request=httpx.Request("GET", "https://api.example")), {}), "expired")]:
        def factory(**kwargs):
            raise failure
        service = AudibleService(store, factory)
        # Empty dict is deliberately an unauthenticated state.
        store.put("auth", {"fixture": True})
        with pytest.raises(UtilityError, match=expected):
            service.library(threading.Event())


def test_unauthenticated_request(store):
    with pytest.raises(UtilityError, match="Connect"):
        AudibleService(store).library(threading.Event())


def test_download_actual_audio_validation(audio, tmp_path):
    body = audio().read_bytes()
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, content=body, headers={"content-length": str(len(body)), "content-type": "audio/mpeg"})))
    target = tmp_path / "download.mp3"
    download("https://cdn.example/book", target, threading.Event(), client=client)
    assert target.read_bytes() == body
    receipts = Receipts(tmp_path / "receipts.json")
    receipts.record("B000000001", target, threading.Event())
    assert receipts.verified("B000000001", threading.Event()) == target
    target.write_bytes(b"corrupt")
    assert receipts.verified("B000000001", threading.Event()) is None


@pytest.mark.parametrize("mode", ["short", "html", "missing-length", "forbidden", "network"])
def test_failed_download_cleanup(tmp_path, mode, monkeypatch):
    # Eliminate backoff only for failure-path fixture tests.
    class FastEvent(threading.Event):
        def wait(self, timeout=None):
            return self.is_set()
    def response(request):
        if mode == "network":
            raise httpx.ConnectError("fixture")
        return httpx.Response(403 if mode == "forbidden" else 200,
            content=b"<html>not audio</html>" if mode == "html" else b"ID3fake",
            headers={"content-type": "text/html" if mode == "html" else "audio/mpeg",
                     "content-length": "0" if mode == "missing-length" else "99"})
    client = httpx.Client(transport=httpx.MockTransport(response))
    target = tmp_path / "output.aaxc"
    with pytest.raises(UtilityError):
        download("https://cdn.example/book", target, FastEvent(), client=client)
    assert not target.exists()
    assert not list(tmp_path.glob(".audiobook-*"))


def test_download_active_cancel(tmp_path):
    cancel = threading.Event()
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"ID3" + bytes(300000)
            cancel.set()
            yield bytes(300000)
    def response(request):
        return httpx.Response(200, stream=Stream(), headers={"content-type": "audio/mpeg", "content-length": "600003"})
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        with pytest.raises(Cancelled):
            download("https://cdn.example/book", tmp_path / "out.mp3", cancel, client=client)
    assert not list(tmp_path.iterdir())


def test_license_denial_preserves_state(store, tmp_path, monkeypatch):
    service = AudibleService(store, receipts=Receipts(tmp_path / "receipts.json"))
    class Client:
        def post(self, endpoint, **kwargs):
            assert endpoint == "content/B000000001/licenserequest"
            assert kwargs["body"]["consumption_type"] == "Download"
            return {"content_license": {"status_code": "Denied"}}
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    with pytest.raises(UtilityError, match="denied"):
        service.download_book(Book.parse(item(1)), tmp_path, threading.Event())
    assert not list(tmp_path.iterdir())


def test_unprotected_download_does_not_require_aaxc_voucher(store, audio, tmp_path, monkeypatch):
    from audiobook_utility import audible_service

    body = audio().read_bytes()
    service = AudibleService(store, receipts=Receipts(tmp_path / "receipts.json"))
    class Client:
        def post(self, endpoint, **kwargs):
            return {"content_license": {"status_code": "Granted", "license_response": "unused for MPEG",
                "content_metadata": {"content_url": {"offline_url": "https://cdn.example/book"},
                                     "content_reference": {"content_format": "MPEG"}}}}
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, content=body, headers={"content-type": "audio/mpeg", "content-length": str(len(body))}))) as http:
        monkeypatch.setattr(audible_service, "download",
            lambda url, target, cancel, progress: download(url, target, cancel, progress, client=http))
        output = service.download_book(Book.parse(item(1)), tmp_path, threading.Event())
    assert output.suffix == ".mp3" and output.read_bytes() == body
    assert output.name == "Book 1.mp3"
    assert not store.data


def test_multipart_library_preserves_whole_book_and_offline_rights(store, monkeypatch):
    service = AudibleService(store)
    parent = {**item(1), "title": "Collected audiobook", "has_children": True,
              "content_delivery_type": "MultiPartBook"}
    unavailable = {**item(3), "has_children": True, "content_delivery_type": "MultiPartBook",
                   "customer_rights": {"is_consumable_offline": False}}
    podcast = {**item(4), "has_children": True, "content_delivery_type": "PodcastParent"}
    calls = []
    class Client:
        def get(self, endpoint, **kwargs):
            calls.append(kwargs)
            assert "parent_asin" not in kwargs, "Child listing is not proof of downloadable child licenses"
            return {"items": [parent, unavailable, podcast]}
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    books = service.library(threading.Event())
    assert [book.asin for book in books] == [item(1)["asin"], item(3)["asin"], item(4)["asin"]]
    assert books[0].title == "Collected audiobook"
    assert books[0].author == "Author" and books[0].cover == parent["product_images"]["121"]
    assert books[0].downloadable and not books[1].downloadable
    assert len(calls) == 1


def test_missing_download_license_has_actionable_error(store, monkeypatch, tmp_path):
    service = AudibleService(store)
    class Client:
        def post(self, endpoint, **kwargs):
            raise audible.exceptions.NotFoundError(httpx.Response(404,
                request=httpx.Request("POST", "https://api.example/content/fixture/licenserequest")),
                {"message": "sensitive-server-value"})
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    with pytest.raises(UtilityError, match="HTTP 404") as failure:
        service.download_book(Book.parse(item(1)), tmp_path, threading.Event())
    assert "whole audiobook" in str(failure.value)
    assert "sensitive-server-value" not in str(failure.value)
    assert not list(tmp_path.iterdir())


def test_repeated_library_page_fails_instead_of_looping(store, monkeypatch):
    service = AudibleService(store)
    class Client:
        def get(self, endpoint, **kwargs):
            return {"items": [item(i) for i in range(100)]}
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    with pytest.raises(UtilityError, match="repeated"):
        service.library(threading.Event())


def test_cancel_during_library_response_is_observed(store, monkeypatch):
    service = AudibleService(store)
    cancel = threading.Event()
    class Client:
        def get(self, endpoint, **kwargs):
            cancel.set()
            return {"items": [item(1)]}
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    with pytest.raises(Cancelled):
        service.library(cancel)


@pytest.mark.parametrize("content_format", ["DASH", "AAX_22_64_DASH", None])
def test_unsupported_format_does_not_save_license_or_download(store, tmp_path, monkeypatch, content_format):
    service = AudibleService(store, receipts=Receipts(tmp_path / "receipts.json"))
    class Client:
        def post(self, endpoint, **kwargs):
            return {"content_license": {"status_code": "Granted", "license_response": "unused",
                    "content_metadata": {"content_url": {"offline_url": "https://cdn.example/book"},
                                         "content_reference": {"content_format": content_format}}}}
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    with pytest.raises(UtilityError, match="supported offline audio format"):
        service.download_book(Book.parse(item(1)), tmp_path, threading.Event())
    assert not store.data and not list(tmp_path.iterdir())


def test_missing_offline_url_is_not_reported_as_unsupported_format(store, tmp_path, monkeypatch):
    service = AudibleService(store, receipts=Receipts(tmp_path / "receipts.json"))
    class Client:
        def post(self, endpoint, **kwargs):
            return {"content_license": {"status_code": "Granted", "content_metadata": {
                    "content_reference": {"content_format": "AAX_22_64"}}}}
    @contextmanager
    def client():
        yield Client()
    monkeypatch.setattr(service, "client", client)
    with pytest.raises(UtilityError, match="offline download link"):
        service.download_book(Book.parse(item(1)), tmp_path, threading.Event())
    assert not store.data and not list(tmp_path.iterdir())

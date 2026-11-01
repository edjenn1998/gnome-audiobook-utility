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
        kwargs["login_url_callback"]("https://www.amazon.com/ap/signin")
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

import threading

import httpx
import pytest

from audiobook_utility.download import download
from audiobook_utility.files import UtilityError


class ImmediateRetry(threading.Event):
    def wait(self, timeout=None):
        return self.is_set()


class Interrupted(httpx.SyncByteStream):
    def __init__(self, body):
        self.body = body

    def __iter__(self):
        yield self.body[:262144]
        raise httpx.ReadError("Synthetic connection loss")


BODY = b"ID3" + bytes(range(256)) * 3072


def headers(body=BODY, etag='"version-one"', **extra):
    return {"content-length": str(len(body)), "content-type": "audio/mpeg", "etag": etag, **extra}


def test_interrupted_download_resumes_validated_bytes(tmp_path):
    requests = []
    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, stream=Interrupted(BODY), headers=headers())
        assert request.headers["range"] == "bytes=262144-"
        assert request.headers["if-range"] == '"version-one"'
        remainder = BODY[262144:]
        return httpx.Response(206, content=remainder, headers=headers(
            remainder, **{"content-range": f"bytes 262144-{len(BODY) - 1}/{len(BODY)}"}))
    target = tmp_path / "resumed.mp3"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        download("https://cdn.example/book", target, ImmediateRetry(), client=client)
    assert len(requests) == 2
    assert target.read_bytes() == BODY
    assert not list(tmp_path.glob(".audiobook-*"))


@pytest.mark.parametrize("etag", ["", 'W/"weak-version"'])
def test_unvalidated_partial_download_restarts(tmp_path, etag):
    calls = []
    def respond(request):
        calls.append(request)
        assert "range" not in request.headers
        if len(calls) == 1:
            return httpx.Response(200, stream=Interrupted(BODY), headers=headers(etag=etag))
        return httpx.Response(200, content=BODY, headers=headers())
    target = tmp_path / "restarted.mp3"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        download("https://cdn.example/book", target, ImmediateRetry(), client=client)
    assert target.read_bytes() == BODY
    assert len(calls) == 2


def test_ignored_range_replaces_partial_instead_of_appending(tmp_path):
    changed = b"ID3new representation" + bytes(400000)
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, stream=Interrupted(BODY), headers=headers())
        assert request.headers["range"] == "bytes=262144-"
        return httpx.Response(200, content=changed, headers=headers(changed, etag='"version-two"'))
    target = tmp_path / "changed.mp3"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        download("https://cdn.example/book", target, ImmediateRetry(), client=client)
    assert target.read_bytes() == changed


@pytest.mark.parametrize("failure", ["etag", "start", "total", "length", "missing-range", "unsatisfiable"])
def test_bad_resume_discards_partial_and_restarts(tmp_path, failure):
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, stream=Interrupted(BODY), headers=headers())
        if len(calls) == 2:
            assert "range" in request.headers
            if failure == "unsatisfiable":
                return httpx.Response(416)
            remainder = BODY[262144:]
            values = headers(remainder, **{"content-range": f"bytes 262144-{len(BODY) - 1}/{len(BODY)}"})
            if failure == "etag":
                values["etag"] = '"different-object"'
            elif failure == "start":
                values["content-range"] = f"bytes 0-{len(remainder) - 1}/{len(BODY)}"
            elif failure == "total":
                values["content-range"] = f"bytes 262144-{len(BODY) - 1}/{len(BODY) + 1}"
            elif failure == "length":
                values["content-length"] = str(len(remainder) + 1)
            else:
                values.pop("content-range")
            return httpx.Response(206, content=remainder, headers=values)
        assert "range" not in request.headers
        return httpx.Response(200, content=BODY, headers=headers())
    target = tmp_path / "validated.mp3"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        download("https://cdn.example/book", target, ImmediateRetry(), client=client)
    assert target.read_bytes() == BODY
    assert len(calls) == 3


def test_repeated_connection_loss_never_publishes_partial(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, stream=Interrupted(BODY), headers=headers()))) as client:
        with pytest.raises(UtilityError, match="interrupted"):
            download("https://cdn.example/book", tmp_path / "incomplete.mp3", ImmediateRetry(), client=client)
    assert not list(tmp_path.iterdir())

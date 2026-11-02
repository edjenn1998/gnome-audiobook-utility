import re
import threading
from pathlib import Path

import httpx

from .files import Cancelled, UtilityError, staging


CONTENT_TYPES = {"audio/aax", "audio/vnd.audible.aax", "audio/audible", "audio/mp4",
                 "audio/x-m4a", "audio/mpeg", "audio/mp3", "application/octet-stream",
                 "binary/octet-stream", "application/aax"}


def strong_etag(response):
    value = response.headers.get("etag", "")
    return value if re.fullmatch(r'"[\x21\x23-\x7e]*"', value) else None


def content_length(response):
    value = response.headers.get("content-length", "")
    if not re.fullmatch(r"[0-9]{1,20}", value) or int(value) <= 0:
        raise UtilityError("The server did not supply a verifiable file length. Retry later.")
    return int(value)


def download(url: str, target: Path, cancel: threading.Event, progress=lambda *_: None,
             client: httpx.Client | None = None):
    if httpx.URL(url).scheme != "https":
        raise UtilityError("The download service supplied an insecure URL.")
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, connect=15), follow_redirects=True)
    try:
        # Keep partial bytes only for this operation. A strong validator prevents
        # combining different objects when a CDN URL changes during a retry.
        with staging(target) as temporary:
            count, expected, validator, signature = 0, None, None, b""
            for attempt in range(3):
                if cancel.is_set():
                    raise Cancelled("Download canceled.")
                headers = {"Accept-Encoding": "identity"}
                resuming = bool(count and validator and expected and count < expected)
                if resuming:
                    headers.update(Range=f"bytes={count}-", **{"If-Range": validator})
                else:
                    count, expected, validator, signature = 0, None, None, b""
                try:
                    with client.stream("GET", url, headers=headers) as response:
                        if response.status_code in {401, 403}:
                            raise UtilityError("Download authorization expired. Refresh the library and retry.")
                        if resuming and response.status_code == 416:
                            count, validator = 0, None
                            raise httpx.ReadError("Range no longer available")
                        response.raise_for_status()
                        if response.url.scheme != "https":
                            raise UtilityError("The download redirected to an insecure connection.")
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if content_type not in CONTENT_TYPES:
                            raise UtilityError("The service returned an unsupported response instead of audiobook audio.")
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            raise UtilityError("The server returned encoded audio that cannot be verified safely.")
                        length = content_length(response)
                        if response.status_code == 206:
                            match = re.fullmatch(r"bytes ([0-9]{1,20})-([0-9]{1,20})/([0-9]{1,20})",
                                                 response.headers.get("content-range", ""))
                            if (not resuming or not match or strong_etag(response) != validator
                                    or int(match[1]) != count or int(match[3]) != expected
                                    or int(match[2]) < count or int(match[2]) >= expected
                                    or int(match[2]) - count + 1 != length):
                                count, validator = 0, None
                                raise httpx.ReadError("Invalid resumed response")
                            response_end = int(match[2]) + 1
                        elif response.status_code == 200:
                            # A server may ignore Range or reject If-Range by sending
                            # the complete new representation. Never append that body.
                            count, signature = 0, b""
                            expected, validator = length, strong_etag(response)
                            response_end = expected
                        else:
                            raise UtilityError("The server did not return a complete audio response.")
                        with temporary.open("r+b") as output:
                            output.seek(count)
                            output.truncate()
                            for chunk in response.iter_bytes(256 * 1024):
                                if cancel.is_set():
                                    raise Cancelled("Download canceled; incomplete data removed.")
                                if len(signature) < 32:
                                    signature += chunk[:32 - len(signature)]
                                if count + len(chunk) > response_end:
                                    raise UtilityError("Download exceeded the expected file size.")
                                output.write(chunk)
                                count += len(chunk)
                                progress(min(0.99, count / expected),
                                         "Resuming audiobook" if resuming else "Downloading audiobook")
                        if count != expected:
                            raise httpx.ReadError("Incomplete download")
                        if not (b"ftyp" in signature[:16] or signature.startswith(b"ID3") or
                                (len(signature) >= 2 and signature[0] == 255 and signature[1] & 0xE0 == 0xE0)):
                            raise UtilityError("Downloaded data is not a supported MP3/AAX/AAXC container.")
                        if cancel.is_set():
                            raise Cancelled("Download canceled.")
                    break
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500 or exc.response.status_code == 429
                    if attempt == 2 or not retryable:
                        raise UtilityError("Download interrupted. Check your connection and retry.") from None
                    if cancel.wait(2 ** attempt):
                        raise Cancelled("Download canceled.")
        progress(1, "Download verified")
        return target
    finally:
        if own_client:
            client.close()

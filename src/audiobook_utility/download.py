import threading
from pathlib import Path

import httpx

from .files import Cancelled, UtilityError, staging


def download(url: str, target: Path, cancel: threading.Event, progress=lambda *_: None,
             client: httpx.Client | None = None):
    if httpx.URL(url).scheme != "https":
        raise UtilityError("The download service supplied an insecure URL.")
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, connect=15), follow_redirects=True)
    try:
        for attempt in range(3):
            if cancel.is_set():
                raise Cancelled("Download canceled.")
            try:
                with staging(target) as temporary:
                    with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
                        if response.status_code in {401, 403}:
                            raise UtilityError("Download authorization expired. Refresh the library and retry.")
                        response.raise_for_status()
                        if response.url.scheme != "https":
                            raise UtilityError("The download redirected to an insecure connection.")
                        content_type = response.headers.get("content-type", "").split(";", 1)[0]
                        if content_type not in {"audio/aax", "audio/vnd.audible.aax", "audio/mp4", "audio/mpeg", "application/octet-stream", "binary/octet-stream", "application/aax"}:
                            raise UtilityError("The service returned an unsupported response instead of audiobook audio.")
                        try:
                            expected = int(response.headers.get("content-length", "0"))
                        except ValueError:
                            expected = 0
                        if expected <= 0:
                            raise UtilityError("The server did not supply a verifiable file length. Retry later.")
                        count = 0
                        signature = b""
                        with temporary.open("wb") as output:
                            for chunk in response.iter_bytes(256 * 1024):
                                if cancel.is_set():
                                    raise Cancelled("Download canceled; incomplete data removed.")
                                if len(signature) < 32:
                                    signature += chunk[:32 - len(signature)]
                                output.write(chunk)
                                count += len(chunk)
                                if count > expected:
                                    raise UtilityError("Download exceeded the expected file size.")
                                progress(min(0.99, count / expected), "Downloading audiobook")
                        if count != expected:
                            raise httpx.ReadError("Incomplete download")
                        if not (b"ftyp" in signature[:16] or signature.startswith(b"ID3") or
                                (len(signature) >= 2 and signature[0] == 255 and signature[1] & 0xE0 == 0xE0)):
                            raise UtilityError("Downloaded data is not a supported MP3/AAX/AAXC container.")
                        if cancel.is_set():
                            raise Cancelled("Download canceled.")
                progress(1, "Download verified")
                return target
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500 or exc.response.status_code == 429
                if attempt == 2 or not retryable:
                    raise UtilityError("Download interrupted. Check your connection and retry.") from None
                if cancel.wait(2 ** attempt):
                    raise Cancelled("Download canceled.")
    finally:
        if own_client:
            client.close()

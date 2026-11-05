import hashlib
import os
from pathlib import Path
import threading
import time

import httpx

from .files import Cancelled, UtilityError, staging
from .metadata import prepare_preview, validate_artwork
from .network import check_transfer, https_url, secure_stream


def thumbnail(url, cancel=None, client=None):
    """Best-effort bounded HTTPS preview; cancellation is never swallowed."""
    cancel = cancel or threading.Event()
    if not url:
        return None
    try:
        https_url(url)
    except UtilityError:
        return None
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "audiobook-utility/covers"
    path = cache / hashlib.sha256(url.encode()).hexdigest()
    own_client = client is None
    client = client or httpx.Client()
    deadline = time.monotonic() + 15
    try:
        check_transfer(cancel, deadline)
        if path.is_file() and path.stat().st_size <= 1024 * 1024:
            return prepare_preview(validate_artwork(path.read_bytes())[0], (96, 128))
        with secure_stream(client, url, cancel=cancel, deadline=deadline) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                check_transfer(cancel, deadline)
                data.extend(chunk)
                if len(data) > 1024 * 1024:
                    return None
        check_transfer(cancel, deadline)
        preview = prepare_preview(bytes(data), (96, 128))
        with staging(path, replace=True) as temporary:
            temporary.write_bytes(preview)
        return preview
    except Cancelled:
        raise
    except (httpx.HTTPError, httpx.InvalidURL, TypeError, ValueError, OSError, UtilityError):
        return None
    finally:
        if own_client:
            client.close()

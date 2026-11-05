import hashlib
import os
import re
import stat
from pathlib import Path
import threading
import time

import httpx

from .files import Cancelled, UtilityError, staging
from .metadata import prepare_preview, validate_artwork
from .network import check_transfer, https_url, secure_stream


def prune_cache(cache, max_bytes=64 * 1024 * 1024, max_entries=1000, now=None):
    """Expire owned regular entries and evict oldest entries within a fixed quota."""
    now = time.time() if now is None else now
    entries = []
    for path in cache.iterdir() if cache.exists() else ():
        if not re.fullmatch(r"[0-9a-f]{64}", path.name):
            continue
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            if now - info.st_mtime > 30 * 86400:
                path.unlink(missing_ok=True)
            else:
                entries.append((info.st_atime, path, info.st_size))
        except OSError:
            continue
    total = sum(item[2] for item in entries)
    count = len(entries)
    for _, path, size in sorted(entries):
        if total <= max_bytes and count <= max_entries:
            break
        try:
            path.unlink(missing_ok=True)
            total -= size
            count -= 1
        except OSError:
            continue


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
        prune_cache(cache)
        if path.is_file() and not path.is_symlink():
            try:
                if path.stat().st_size > 1024 * 1024:
                    raise ValueError("Oversized cache entry")
                return prepare_preview(validate_artwork(path.read_bytes())[0], (96, 128))
            except (ValueError, OSError, UtilityError):
                path.unlink(missing_ok=True)
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
        prune_cache(cache)
        return preview
    except Cancelled:
        raise
    except (httpx.HTTPError, httpx.InvalidURL, TypeError, ValueError, OSError, UtilityError):
        return None
    finally:
        if own_client:
            client.close()

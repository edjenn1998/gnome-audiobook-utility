import hashlib
import os
from pathlib import Path

import httpx

from .files import UtilityError, staging
from .metadata import validate_artwork


def thumbnail(url: str | None) -> bytes | None:
    """Best-effort bounded HTTPS thumbnail fetch, invoked only in a worker."""
    if not url or httpx.URL(url).scheme != "https":
        return None
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "audiobook-utility/covers"
    path = cache / hashlib.sha256(url.encode()).hexdigest()
    try:
        if path.is_file() and path.stat().st_size <= 1024 * 1024:
            return validate_artwork(path.read_bytes())[0]
        with httpx.stream("GET", url, timeout=5, follow_redirects=True) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes(65536):
                data.extend(chunk)
                if len(data) > 1024 * 1024:
                    return None
        result = validate_artwork(bytes(data))[0]
        with staging(path, replace=True) as temporary:
            temporary.write_bytes(result)
        return result
    except (httpx.HTTPError, OSError, UtilityError):
        return None

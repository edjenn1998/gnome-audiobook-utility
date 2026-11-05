"""Bounded HTTPS transfers; validate each redirect before opening its connection."""
from contextlib import contextmanager
import time

import httpx

from .files import Cancelled, UtilityError


def https_url(value):
    try:
        url = httpx.URL(value)
        if url.scheme != "https" or not url.host or url.userinfo:
            raise ValueError
        return url
    except (httpx.InvalidURL, TypeError, ValueError):
        raise UtilityError("The service supplied an invalid or insecure URL; HTTPS is required.") from None


def check_transfer(cancel, deadline):
    if cancel is not None and cancel.is_set():
        raise Cancelled("Network operation canceled.")
    if time.monotonic() >= deadline:
        raise UtilityError("The network operation exceeded its time limit. Retry later.")


@contextmanager
def secure_stream(client, url, headers=None, cancel=None, deadline=None):
    current = https_url(url)
    deadline = deadline if deadline is not None else time.monotonic() + 30
    origin = (current.host, current.port)
    for _ in range(6):
        check_transfer(cancel, deadline)
        request = client.build_request("GET", current, headers=headers,
                                       timeout=httpx.Timeout(2, connect=5))
        if (current.host, current.port) != origin:
            request.headers.pop("authorization", None)
            if "cookie" in client.headers:
                request.headers.pop("cookie", None)
        response = client.send(request, stream=True, follow_redirects=False, auth=None)
        try:
            check_transfer(cancel, deadline)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise UtilityError("The service returned a redirect without a destination.")
                try:
                    current = https_url(current.join(location))
                except (httpx.InvalidURL, ValueError):
                    raise UtilityError("The service returned an invalid HTTPS redirect.") from None
                continue
            yield response
            return
        finally:
            response.close()
    raise UtilityError("The service returned too many HTTPS redirects.")

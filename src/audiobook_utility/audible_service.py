import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import audible

from .credentials import SecretStore
from .download import download
from .files import Cancelled, UtilityError, destination
from .receipts import Receipts

# Upstream debug records may include signed requests, tokens and vouchers.
for _name in ("audible", "httpx", "httpcore"):
    logging.getLogger(_name).disabled = True
    logging.getLogger(_name).addHandler(logging.NullHandler())
    logging.getLogger(_name).propagate = False


@dataclass
class Book:
    asin: str
    title: str
    author: str
    minutes: int
    cover: str | None
    downloadable: bool
    cover_data: bytes | None = None
    local_path: Path | None = None

    @classmethod
    def parse(cls, item):
        item = item.get("item", item)
        images = item.get("product_images") or {}
        return cls(item["asin"], item.get("title") or item["asin"],
                   ", ".join(a["name"] for a in item.get("authors", []) if a.get("name")),
                   int(item.get("runtime_length_min") or 0),
                   images.get("121") or images.get("500"),
                   bool((item.get("customer_rights") or {}).get("is_consumable_offline")))


def validate_redirect(url: str) -> str:
    parsed = urlparse(url.strip())
    if (parsed.scheme != "https" or parsed.hostname not in {"www.amazon.com", "www.audible.com"}
            or parsed.path != "/ap/maplanding"
            or not parse_qs(parsed.query).get("openid.oa2.authorization_code")):
        raise UtilityError("Paste the complete Amazon/Audible maplanding URL after browser sign-in.")
    return url.strip()


class AudibleService:
    def __init__(self, store=None, client_factory=None, receipts=None):
        self.store = store or SecretStore()
        self.client_factory = client_factory or audible.Client
        self.receipts = receipts or Receipts()

    def connect(self, browser_callback):
        # Check secure persistence before launching a browser.
        self.store.get("auth")
        try:
            auth = audible.Authenticator.from_login_external(
                locale="us", login_url_callback=lambda url: validate_redirect(browser_callback(url)))
            self.store.put("auth", auth.to_dict())
        except (UtilityError, Cancelled):
            raise
        except Exception:
            raise UtilityError("Audible sign-in failed. Retry in your browser; authentication may have changed upstream.") from None

    def connected(self):
        return self.store.get("auth") is not None

    def disconnect(self):
        self.store.clear()

    @contextmanager
    def client(self):
        data = self.store.get("auth")
        if not data:
            raise UtilityError("Connect your Audible.com account first.")
        try:
            auth = audible.Authenticator.from_dict(data)
            with self.client_factory(auth=auth, timeout=30) as client:
                yield client
            self.store.put("auth", auth.to_dict())
        except (UtilityError, Cancelled):
            raise
        except audible.exceptions.Unauthorized:
            raise UtilityError("Your Audible session expired. Disconnect and sign in again.") from None
        except Exception:
            raise UtilityError("Audible request failed. Check your connection, then refresh or reconnect your account.") from None

    def library(self, cancel: threading.Event) -> list[Book]:
        books = []
        seen = set()
        with self.client() as client:
            page = 1
            while True:
                if cancel.is_set():
                    raise Cancelled("Library refresh canceled.")
                data = client.get("library", page=page, num_results=100,
                                  response_groups="contributors,media,product_attrs,customer_rights",
                                  image_sizes="121,500", status="Active")
                items = data.get("items", [])
                new = 0
                for item in items:
                    book = Book.parse(item)
                    if book.asin not in seen:
                        seen.add(book.asin)
                        books.append(book)
                        new += 1
                if not items or len(items) < 100:
                    break
                if not new:
                    raise UtilityError("Audible repeated a library page. Refresh again later.")
                page += 1
        return books

    def download_book(self, book: Book, folder: Path, cancel: threading.Event, progress=lambda *_: None):
        if not book.downloadable:
            raise UtilityError("This title is not available for offline download on your account.")
        with self.client() as client:
            # Protocol follows audible-cli LibraryItem.get_license; entitlement is server-enforced.
            license_data = client.post(f"content/{book.asin}/licenserequest", body={
                "supported_drm_types": ["Mpeg", "Adrm"], "quality": "High",
                "consumption_type": "Download", "response_groups": "content_reference",
            })
            content = license_data.get("content_license", {})
            if content.get("status_code") != "Granted":
                raise UtilityError("Audible denied this download license. The title may be unavailable or temporarily limited.")
            metadata = content.get("content_metadata") or {}
            url = (metadata.get("content_url") or {}).get("offline_url")
            format = (metadata.get("content_reference") or {}).get("content_format", "")
            if not url or format.lower() not in {"mpeg", "aax", "aax_22_32", "aax_44_64", "aax_44_128", "aaxc"}:
                raise UtilityError("Audible did not provide a supported offline audio format.")
            if content.get("license_response"):
                from audible.aescipher import decrypt_voucher_from_licenserequest
                try:
                    voucher = decrypt_voucher_from_licenserequest(client.auth, license_data)
                except Exception:
                    raise UtilityError("Could not preserve this title's media license securely.") from None
                self.store.put("media:" + book.asin, voucher)
            suffix = ".mp3" if format.lower() == "mpeg" else ".aaxc"
            # ASIN identifies downloaded protected audio independently of a title's filename.
            target = destination(folder, f"{book.title} [{book.asin}]", suffix)
            download(url, target, cancel, progress)
            self.receipts.record(book.asin, target, cancel)
            return target

    def input_options(self, source: Path) -> list[str]:
        if source.suffix.lower() == ".aax":
            with self.client() as client:
                return ["-activation_bytes", client.auth.get_activation_bytes()]
        if source.suffix.lower() == ".aaxc":
            import re
            match = re.search(r"\[([A-Z0-9]+)\]", source.stem)
            if not match:
                raise UtilityError("Cannot identify this AAXC license. Use its original downloaded filename.")
            voucher = self.store.get("media:" + match[1])
            if not voucher or not voucher.get("key") or not voucher.get("iv"):
                raise UtilityError("This AAXC file has no media license in your desktop keyring.")
            return ["-audible_key", voucher["key"], "-audible_iv", voucher["iv"]]
        return []

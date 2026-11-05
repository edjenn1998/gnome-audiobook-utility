import logging
import math
import re
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import audible
import httpx

from .credentials import SecretStore
from .download import download
from .files import Cancelled, UtilityError, destination
from .login_flow import callback_target, validate_redirect
from .media import protected_format
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
    minutes: int | None
    cover: str | None
    downloadable: bool | None
    cover_data: bytes | None = None
    local_path: Path | None = None

    @classmethod
    def parse(cls, item):
        if not isinstance(item, dict):
            raise UtilityError("Invalid library item identity.")
        item = item.get("item", item)
        if not isinstance(item, dict) or not isinstance(item.get("asin"), str) or not re.fullmatch(r"[A-Z0-9]{10}", item["asin"]):
            raise UtilityError("Invalid library item identity.")
        images = item.get("product_images")
        images = images if isinstance(images, dict) else {}
        authors = item.get("authors")
        authors = authors if isinstance(authors, list) else []
        try:
            duration = float(item.get("runtime_length_min"))
            minutes = int(duration) if math.isfinite(duration) and duration >= 0 else None
        except (ValueError, TypeError, OverflowError):
            minutes = None
        rights = item.get("customer_rights")
        eligible = rights.get("is_consumable_offline") if isinstance(rights, dict) else None
        eligible = eligible if type(eligible) is bool else None
        title = item.get("title")
        cover = images.get("121") or images.get("500")
        return cls(item["asin"], title if isinstance(title, str) and title.strip() else item["asin"],
                   ", ".join(a["name"] for a in authors if isinstance(a, dict) and isinstance(a.get("name"), str)),
                   minutes, cover if isinstance(cover, str) else None, eligible)


class AudibleService:
    def __init__(self, store=None, client_factory=None, receipts=None):
        self.store = store or SecretStore()
        self.client_factory = client_factory or audible.Client
        self.receipts = receipts or Receipts()
        self.library_skipped = 0

    def connect(self, browser_callback, cancel: threading.Event | None = None):
        # Check secure persistence before launching a browser.
        cancel = cancel or threading.Event()
        if cancel.is_set():
            raise Cancelled("Audible sign-in canceled.")
        self.store.get("auth")
        try:
            def capture(url):
                target = callback_target(url)
                if cancel.is_set():
                    raise Cancelled("Audible sign-in canceled.")
                result = browser_callback(url)
                if cancel.is_set():
                    raise Cancelled("Audible sign-in canceled.")
                return validate_redirect(result, target)
            auth = audible.Authenticator.from_login_external(
                locale="us", login_url_callback=capture)
            if cancel.is_set():
                raise Cancelled("Audible sign-in canceled. Your saved account and media licenses were kept.")
            self.store.put("auth", auth.to_dict())
        except (UtilityError, Cancelled):
            raise
        except Exception:
            raise UtilityError("Audible sign-in failed. Retry in your browser; authentication may have changed upstream.") from None

    def connected(self):
        return self.store.get("auth") is not None

    def disconnect(self):
        self.store.delete("auth")

    def forget_media_licenses(self):
        self.store.clear_media()

    def recover_downloads(self, cancel):
        self.receipts.recover(self.store.delete, cancel)

    @contextmanager
    def client(self):
        data = self.store.get("auth")
        if not data:
            raise UtilityError("Connect your Audible.com account first.")
        try:
            auth = audible.Authenticator.from_dict(data)
        except Exception as exc:
            raise UtilityError("Saved Audible authentication could not be read. Log in again; download licenses will be kept.") from exc
        try:
            with self.client_factory(auth=auth, timeout=30) as client:
                yield client
            self.store.put("auth", auth.to_dict())
        except (UtilityError, Cancelled):
            raise
        except audible.exceptions.Unauthorized as exc:
            raise UtilityError("Your Audible session expired. Connect your account again; saved media licenses will be kept.") from exc
        except audible.exceptions.RatelimitError as exc:
            raise UtilityError("Audible is temporarily limiting requests. Wait before retrying; another login is not needed.") from exc
        except (httpx.TransportError, httpx.HTTPStatusError, audible.exceptions.RequestError) as exc:
            raise UtilityError("Audible request failed. Check your connection, then refresh or retry later.") from exc

    def library(self, cancel: threading.Event) -> list[Book]:
        self.recover_downloads(cancel)
        books = []
        self.library_skipped = 0
        seen = set()
        with self.client() as client:
            page = 1
            while True:
                if cancel.is_set():
                    raise Cancelled("Library refresh canceled.")
                data = client.get("library", page=page, num_results=100,
                                  response_groups="contributors,media,product_attrs,customer_rights",
                                  image_sizes="121,500", status="Active")
                if cancel.is_set():
                    raise Cancelled("Library refresh canceled.")
                if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
                    raise UtilityError("Audible returned invalid library data. Retry the refresh later.")
                items = data.get("items", [])
                new = 0
                for item in items:
                    try:
                        book = Book.parse(item)
                    except UtilityError:
                        self.library_skipped += 1
                        continue
                    if book.asin not in seen:
                        seen.add(book.asin)
                        books.append(book)
                        new += 1
                if not items or len(items) < 100:
                    break
                if not new:
                    raise UtilityError("Audible repeated a library page. Refresh again later.")
                page += 1
            # MultiPartBook entries can license the complete audiobook. Replacing
            # them with AudioPart children breaks downloads: child library rights
            # do not establish that the content-license endpoint supports them.
        return books

    def download_book(self, book: Book, folder: Path, cancel: threading.Event, progress=lambda *_: None):
        if cancel.is_set():
            raise Cancelled("Download canceled.")
        if book.downloadable is not True:
            raise UtilityError("This title is not available for offline download on your account.")
        with self.client() as client:
            # Protocol follows audible-cli LibraryItem.get_license; entitlement is server-enforced.
            try:
                license_data = client.post(f"content/{book.asin}/licenserequest", body={
                    "supported_drm_types": ["Mpeg", "Adrm"], "quality": "High",
                    "consumption_type": "Download", "response_groups": "content_reference",
                }, headers={
                    "X-Amzn-RequestId": secrets.token_hex(20).upper(),
                    "X-ADP-SW": "37801821", "X-ADP-Transport": "WIFI", "X-ADP-LTO": "120",
                    "X-Device-Type-Id": "A2CZJZGLK2JJVM", "device_idiom": "phone",
                })
            except audible.exceptions.NotFoundError as exc:
                raise UtilityError("Audible could not provide a download license for this entry (HTTP 404). Refresh the library and select the whole audiobook rather than an individual part.") from exc
            content = license_data.get("content_license", {})
            if cancel.is_set():
                raise Cancelled("Download canceled.")
            if content.get("status_code") != "Granted":
                raise UtilityError("Audible denied this download license. The title may be unavailable or temporarily limited.")
            metadata = content.get("content_metadata") or {}
            url = (metadata.get("content_url") or {}).get("offline_url")
            format = (metadata.get("content_reference") or {}).get("content_format", "")
            if not isinstance(url, str) or not url:
                raise UtilityError("Audible granted a license but did not provide an offline download link for this title. Retry later.")
            format = format.lower() if isinstance(format, str) else ""
            # AAX_<sample rate>_<bitrate> denotes quality, not a different DRM.
            # A fixed list incorrectly rejected valid titles such as AAX_22_64.
            if format not in {"mpeg", "aax", "aaxc"} and not re.fullmatch(r"aax_[1-9][0-9]{0,2}_[1-9][0-9]{0,3}", format):
                raise UtilityError("Audible did not provide a supported offline audio format.")
            license_key, voucher = None, None
            if format != "mpeg" and not content.get("license_response"):
                raise UtilityError("Audible supplied protected audio without its media voucher. Retry the download to obtain a complete license.")
            if format != "mpeg" and content.get("license_response"):
                from audible.aescipher import decrypt_voucher_from_licenserequest
                try:
                    voucher = decrypt_voucher_from_licenserequest(client.auth, license_data)
                except Exception:
                    raise UtilityError("Could not preserve this title's media license securely.") from None
                self.voucher_options(voucher)
                # A new license must not replace the one needed by an older file.
                license_key = "media:" + book.asin + ":" + secrets.token_hex(16)
        # The API client/auth persistence finishes before any long transfer or
        # local publication, so local failures cannot be mislabeled as HTTP errors.
        suffix = ".mp3" if format == "mpeg" else ".aaxc"
        target = destination(folder, book.title, suffix)
        with self.receipts.transaction(book.asin, target, license_key) as tx:
            try:
                if license_key:
                    self.store.put(license_key, voucher)
                download(url, target, cancel, progress,
                         before_publish=lambda temporary: self.receipts.ready(tx, temporary, cancel))
            except Exception:
                if not self.receipts.published(tx):
                    try:
                        if license_key:
                            self.store.delete(license_key)
                        self.receipts.abort(tx)
                    except (UtilityError, OSError):
                        pass
                    raise
            try:
                self.receipts.commit(tx)
            except (UtilityError, OSError):
                progress(1, "Download saved; durable receipt recovery is pending")
        return target

    @staticmethod
    def voucher_options(voucher, diagnostics: dict | None = None) -> list[str]:
        if diagnostics is not None:
            diagnostics["voucher_present"] = isinstance(voucher, dict)
            for field in ("key", "iv"):
                value = voucher.get(field) if isinstance(voucher, dict) else None
                valid = isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{32}", value))
                diagnostics[f"{field}_valid_16_byte_hex"] = valid
        if not isinstance(voucher, dict) or any(
                not isinstance(voucher.get(field), str)
                or not re.fullmatch(r"[0-9a-fA-F]{32}", voucher[field])
                for field in ("key", "iv")):
            raise UtilityError("The saved AAXC media voucher is missing a valid 16-byte key or IV. Download the title again to obtain a valid license.")
        return ["-audible_key", voucher["key"], "-audible_iv", voucher["iv"]]

    def input_options(self, source: Path, cancel: threading.Event | None = None,
                      diagnostics: dict | None = None) -> list[str]:
        if cancel and cancel.is_set():
            raise Cancelled("License lookup canceled.")
        kind = protected_format(source)
        if kind == "aax":
            with self.client() as client:
                return ["-activation_bytes", client.auth.get_activation_bytes()]
        if kind == "aaxc":
            association = self.receipts.association(source, cancel or threading.Event(), diagnostics)
            if association:
                asin, license_key = association
                if diagnostics is not None:
                    diagnostics["association_method"] = "receipt-SHA256"
            else:
                # Compatibility with files downloaded before per-file receipts existed.
                # Match the trailing ASIN only, never bracketed text in a book's title.
                match = re.search(r"\[([A-Z0-9]{10})\](?: \(\d+\))?$", source.stem)
                if not match:
                    raise UtilityError("Cannot associate this AAXC file with a saved download. Restore its download record and desktop keyring license, or import the original downloaded file.")
                license_key = "media:" + match[1]
                asin = match[1]
                if diagnostics is not None:
                    diagnostics.update(association_method="legacy-filename", license_scope="legacy-ASIN")
            if diagnostics is not None:
                diagnostics["license_reference_matches_receipt_ASIN"] = (
                    isinstance(license_key, str) and
                    (license_key == "media:" + asin or license_key.startswith("media:" + asin + ":")))
                diagnostics["keyring_lookup"] = "attempted"
            try:
                voucher = self.store.get(license_key)
            except UtilityError:
                if diagnostics is not None:
                    diagnostics["keyring_lookup"] = "failed"
                raise
            if diagnostics is not None:
                diagnostics["keyring_lookup"] = "found" if voucher else "missing"
                diagnostics["voucher_ASIN_matches_receipt"] = (
                    voucher["asin"] == asin if isinstance(voucher, dict) and isinstance(voucher.get("asin"), str)
                    else "not-present-in-voucher")
            if not voucher:
                raise UtilityError("This AAXC file has no media license in your desktop keyring.")
            return self.voucher_options(voucher, diagnostics)
        return []

import threading
from urllib.parse import urlencode

import audible
import pytest

from audiobook_utility.audible_service import AudibleService
from audiobook_utility.files import Cancelled, UtilityError
from audiobook_utility.login_flow import LoginRequest, callback_target, validate_redirect
from test_audible import MemoryStore

TARGET = "https://www.amazon.com/ap/maplanding"
LOGIN = "https://www.amazon.com/ap/signin?" + urlencode({"openid.return_to": TARGET})
CALLBACK = TARGET + "?openid.oa2.authorization_code=synthetic-test-code"


def test_callback_capture_ignores_intermediate_pages_and_consumes_result():
    request = LoginRequest(LOGIN, threading.Event())
    assert not request.receive("https://www.amazon.com/ap/mfa?otp=synthetic")
    assert not request.ready.is_set()
    assert request.receive(CALLBACK)
    assert request.wait() == CALLBACK
    assert request._response is None and request.url == ""
    assert "synthetic-test-code" not in repr(request)


@pytest.mark.parametrize("uri", [
    "http://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=test",
    "https://www.amazon.com:8443/ap/maplanding?openid.oa2.authorization_code=test",
    "https://user@www.amazon.com/ap/maplanding?openid.oa2.authorization_code=test",
    "https://www.amazon.com.evil.example/ap/maplanding?openid.oa2.authorization_code=test",
    "https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=one&openid.oa2.authorization_code=two",
    "https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=",
    "https://www.amazon.com/ap/maplanding?error=access_denied",
    "https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=test#fragment",
    "https://www.audible.com/ap/maplanding?openid.oa2.authorization_code=test",
])
def test_invalid_or_wrong_destination_callback_is_rejected(uri):
    with pytest.raises(UtilityError) as failure:
        validate_redirect(uri, TARGET)
    assert uri not in str(failure.value)


def test_backend_callback_is_derived_without_rewriting_redirect():
    assert callback_target(LOGIN) == TARGET
    for url in ("https://evil.example/ap/signin", "https://www.amazon.com/ap/signin",
                "https://www.amazon.com/ap/signin?" + urlencode({"openid.return_to": "http://localhost/callback"})):
        with pytest.raises(UtilityError):
            callback_target(url)


def test_callback_error_and_timeout_release_waiter():
    request = LoginRequest(LOGIN, threading.Event())
    assert request.receive(TARGET + "?error=access_denied&error_description=private-error-text")
    with pytest.raises(UtilityError) as failure:
        request.wait()
    assert "private-error-text" not in str(failure.value)
    timed_out = LoginRequest(LOGIN, threading.Event(), timeout=0)
    with pytest.raises(UtilityError, match="timed out"):
        timed_out.wait()


def test_canceled_or_failed_reauthentication_preserves_saved_account(monkeypatch):
    store = MemoryStore()
    store.put("auth", {"fixture": "saved-session"})
    store.put("media:fixture", {"fixture": "saved-media-license"})
    before = store.data.copy()
    cancel = threading.Event()
    def register(**kwargs):
        assert kwargs["login_url_callback"](LOGIN) == CALLBACK
        cancel.set()
        return type("Auth", (), {"to_dict": lambda self: {"fixture": "replacement"}})()
    monkeypatch.setattr(audible.Authenticator, "from_login_external", register)
    with pytest.raises(Cancelled):
        AudibleService(store).connect(lambda _: CALLBACK, cancel)
    assert store.data == before
    def failed(**kwargs):
        kwargs["login_url_callback"](LOGIN)
        raise RuntimeError("synthetic-token-never-display")
    monkeypatch.setattr(audible.Authenticator, "from_login_external", failed)
    with pytest.raises(UtilityError) as failure:
        AudibleService(store).connect(lambda _: CALLBACK)
    assert "synthetic-token-never-display" not in str(failure.value)
    assert store.data == before


@pytest.mark.parametrize("scenario", ["success", "cancel", "callback-error", "registration-error", "network-error", "missing-webkit"])
def test_native_webkit_login_callback_and_cleanup(native_app, tmp_path, monkeypatch, scenario):
    from audiobook_utility.login_window import webkit_modules
    from audiobook_utility.ui import GLib
    from test_ui_workflows import wait

    WebKit, _ = webkit_modules()
    if scenario == "missing-webkit":
        from audiobook_utility import login_window
        def missing():
            raise UtilityError("Automatic sign-in needs WebKitGTK 6.")
        monkeypatch.setattr(login_window, "webkit_modules", missing)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    callback = TARGET + "?error=access_denied" if scenario == "callback-error" else CALLBACK
    loaded = []
    def load_fixture(view, uri):
        loaded.append(uri)
        if scenario in {"cancel", "network-error"}:
            view.load_html("<html><body>Simulated Amazon sign-in</body></html>", "https://www.amazon.com/")
        else:
            # The real WebKit navigation/policy signals intercept this redirect;
            # the callback is never fetched from the external network.
            view.load_html(f'<html><head><meta http-equiv="refresh" content="0;url={callback}"></head></html>',
                           "https://www.amazon.com/")
    monkeypatch.setattr(WebKit.WebView, "load_uri", load_fixture)
    store = MemoryStore()
    store.put("auth", {"fixture": "saved-session"})
    store.put("media:fixture", {"fixture": "saved-media-license"})
    registrations = []
    def register(**kwargs):
        result = kwargs["login_url_callback"](LOGIN)
        registrations.append(result)
        if scenario == "registration-error":
            raise RuntimeError("synthetic-sensitive-registration-error")
        return type("Auth", (), {"to_dict": lambda self: {"fixture": "new-session"}})()
    monkeypatch.setattr(audible.Authenticator, "from_login_external", register)
    native_app.activate()
    window = native_app.get_active_window()
    failures = []
    window.error = failures.append
    window.service = AudibleService(store)
    try:
        window.connect_audible()
        if scenario in {"cancel", "network-error"}:
            import time
            deadline = time.monotonic() + 10
            while not loaded:
                while GLib.MainContext.default().pending():
                    GLib.MainContext.default().iteration(False)
                time.sleep(0.01)
                assert time.monotonic() < deadline
            login = window.login_window
            assert login.session.is_ephemeral()
            if scenario == "cancel":
                login.close_requested()
            else:
                error = GLib.Error.new_literal(WebKit.network_error_quark(),
                                               "private-url-or-server-message", WebKit.NetworkError.FAILED)
                login.load_failed(login.view, WebKit.LoadEvent.STARTED, CALLBACK, error)
        wait(window)
        assert window.login_window is None
        assert store.get("media:fixture") == {"fixture": "saved-media-license"}
        if scenario == "success":
            assert registrations == [CALLBACK]
            assert store.get("auth") == {"fixture": "new-session"}
            assert "Connected to Audible.com" in window.account_label.get_text()
            assert not failures
        else:
            assert store.get("auth") == {"fixture": "saved-session"}
            assert bool(failures) == (scenario != "cancel")
        log = tmp_path / "state/audiobook-utility/diagnostics.log"
        text = log.read_text() if log.exists() else ""
        assert "synthetic-test-code" not in text and "private-url-or-server-message" not in text
        assert "synthetic-sensitive-registration-error" not in text
    finally:
        if window.login_window:
            window.login_window.close_requested()
            wait(window)
        window.destroy()

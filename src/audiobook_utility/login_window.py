"""Isolated WebKit sign-in window; account registration stays in audible."""
from urllib.parse import urlsplit

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from .files import UtilityError


def webkit_modules():
    try:
        gi.require_version("WebKit", "6.0")
        gi.require_version("Soup", "3.0")
        from gi.repository import Soup, WebKit
        return WebKit, Soup
    except (ImportError, ValueError):
        raise UtilityError("Automatic sign-in needs WebKitGTK 6. On CachyOS/Arch, install webkitgtk-6.0, then try Login to Audible again. Your saved account still works.") from None


class LoginWindow(Adw.Window):
    def __init__(self, parent, request):
        WebKit, Soup = webkit_modules()
        super().__init__(transient_for=parent, modal=True, title="Login to Audible",
                         default_width=540, default_height=720)
        self.request = request
        self._closed = False
        self._poll = 0
        self._WebKit = WebKit
        self.session = WebKit.NetworkSession.new_ephemeral()
        self.view = WebKit.WebView(network_session=self.session)
        settings = self.view.get_settings()
        from audible.login import USER_AGENT, build_init_cookies
        settings.set_user_agent(USER_AGENT)
        settings.set_enable_developer_extras(False)
        settings.set_enable_write_console_messages_to_stdout(False)
        self._view_handlers = [
            self.view.connect("decide-policy", self.decide_policy),
            self.view.connect("notify::uri", self.uri_changed),
            self.view.connect("load-failed", self.load_failed),
            self.view.connect("load-failed-with-tls-errors", self.tls_failed),
            self.view.connect("web-process-terminated", self.process_terminated),
            self.view.connect("context-menu", lambda *_: True),
        ]
        self.connect("close-request", self.close_requested)
        controller = Gtk.EventControllerKey()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self.key_pressed)
        self.add_controller(controller)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Login to Audible", css_classes=["heading"]))
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close_requested())
        header.pack_start(cancel)
        toolbar.add_top_bar(header)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.origin = Gtk.Label(label="Secure Amazon sign-in", margin_top=6, margin_bottom=6)
        content.append(self.origin)
        self.pages = Gtk.Stack(vexpand=True)
        self.pages.add_named(self.view, "browser")
        finishing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        finishing.append(Gtk.Spinner(spinning=True))
        finishing.append(Gtk.Label(label="Completing secure sign-in…", wrap=True))
        self.pages.add_named(finishing, "finishing")
        content.append(self.pages)
        self.hint = Gtk.Label(label="Sign in normally and complete any Amazon verification. This window closes automatically when connected.",
                              wrap=True, margin_start=18, margin_end=18, margin_top=6, margin_bottom=12)
        content.append(self.hint)
        toolbar.set_content(content)
        self.set_content(toolbar)
        self._poll = GLib.timeout_add(100, self.poll_cancel)

        # Match upstream's browser helper, using only temporary app-identification
        # cookies. Neither these cookies nor the user's browser session touch disk.
        manager = self.session.get_cookie_manager()
        initial = build_init_cookies()
        self._pending_cookies = len(initial)
        for name, value in initial.items():
            cookie = Soup.Cookie.new(name, value, urlsplit(request.url).hostname, "/", -1)
            cookie.set_secure(True)
            manager.add_cookie(cookie, None, self.cookie_added)

    def cookie_added(self, manager, result):
        if self._closed:
            return
        try:
            manager.add_cookie_finish(result)
        except GLib.Error:
            self.request.fail(UtilityError("The temporary sign-in browser could not start. Try Login to Audible again."))
            return
        self._pending_cookies -= 1
        if not self._pending_cookies and not self.request.ready.is_set() and not self.request.cancel_event.is_set():
            self.view.load_uri(self.request.url)

    def capture(self, uri):
        if not uri or not self.request.receive(uri):
            return False
        self.pages.set_visible_child_name("finishing")
        self.origin.set_text("Completing Audible account connection")
        self.hint.set_text("Your credentials will be saved securely in the desktop keyring.")
        return True

    def decide_policy(self, view, decision, kind):
        WebKit = self._WebKit
        if kind not in {WebKit.PolicyDecisionType.NAVIGATION_ACTION, WebKit.PolicyDecisionType.NEW_WINDOW_ACTION}:
            return False
        uri = decision.get_navigation_action().get_request().get_uri()
        if self.capture(uri):
            decision.ignore()
            return True
        try:
            secure = urlsplit(uri).scheme == "https"
        except ValueError:
            secure = False
        if not secure:
            decision.ignore()
            self.request.fail(UtilityError("The sign-in page tried to leave HTTPS. Close sign-in and try again."))
            return True
        if kind == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
            # Verification links use this same isolated session, never a separate
            # system browser that would lose callback capture or expose the URL.
            decision.ignore()
            view.load_uri(uri)
            return True
        return False

    def uri_changed(self, view, *_):
        if self._closed or self.request.ready.is_set():
            return
        uri = view.get_uri()
        if self.capture(uri):
            view.stop_loading()
        elif uri:
            try:
                host = urlsplit(uri).hostname
                self.origin.set_text(f"Secure sign-in · {host}" if host else "Secure Amazon sign-in")
            except ValueError:
                pass

    def load_failed(self, view, event, uri, error):
        WebKit = self._WebKit
        if self._closed or self.request.ready.is_set():
            return True
        if error.matches(WebKit.network_error_quark(), WebKit.NetworkError.CANCELLED):
            return True
        self.request.fail(UtilityError("Could not load Amazon sign-in. Check your connection and try Login to Audible again."))
        return True

    def tls_failed(self, *_):
        self.request.fail(UtilityError("Amazon sign-in could not establish a trusted HTTPS connection. Check your system clock and network, then try again."))
        return True

    def process_terminated(self, *_):
        if not self._closed and not self.request.ready.is_set():
            self.request.fail(UtilityError("The sign-in browser stopped unexpectedly. Try Login to Audible again."))

    def poll_cancel(self):
        if self._closed:
            self._poll = 0
            return False
        if self.request.cancel_event.is_set():
            self.request.cancel()
            self._poll = 0
            self.finish()
            return False
        return True

    def key_pressed(self, controller, key, code, state):
        if key == Gdk.KEY_Escape:
            self.close_requested()
            return True
        return False

    def close_requested(self, *_):
        self.request.cancel()
        self.finish()
        return True

    def finish(self):
        """Close after success/failure without turning successful login into cancel."""
        if self._closed:
            return
        self._closed = True
        if self._poll:
            GLib.source_remove(self._poll)
            self._poll = 0
        view, self.view = self.view, None
        for handler in self._view_handlers:
            view.disconnect(handler)
        self._view_handlers.clear()
        view.stop_loading()
        view.terminate_web_process()
        self.pages.remove(view)
        self.session = None
        self.destroy()

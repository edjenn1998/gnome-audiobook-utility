import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from . import APP_ID  # noqa: E402


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        if self.get_active_window():
            self.get_active_window().present()
            return
        window = Adw.ApplicationWindow(application=self, title="Audiobook Utility",
                                       default_width=900, default_height=700)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(Adw.HeaderBar())
        box.append(Adw.StatusPage(title="Audiobook Utility", description="Convert, merge and edit audiobooks",
                                  icon_name="audio-x-generic-symbolic"))
        window.set_content(box)
        window.present()

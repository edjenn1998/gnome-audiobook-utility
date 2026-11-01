def main():
    import sys
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk
        if (Gtk.get_major_version(), Gtk.get_minor_version()) < (4, 10) or (Adw.get_major_version(), Adw.get_minor_version()) < (1, 5):
            raise ValueError("GTK 4.10 and Libadwaita 1.5 or newer are required")
    except (ImportError, ValueError) as exc:
        print(f"Cannot start Audiobook Utility: {exc}. Install GTK4, Libadwaita and PyGObject.", file=sys.stderr)
        return 1
    from .ui import Application
    return Application().run(None)


if __name__ == "__main__":
    raise SystemExit(main())

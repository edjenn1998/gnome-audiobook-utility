import time

from audiobook_utility.audible_service import Book


def settle():
    from audiobook_utility.ui import GLib
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(0.005)


def test_library_toolbar_is_outside_scroll_and_stays_visible(native_app, tmp_path, monkeypatch):
    from audiobook_utility.ui import Gtk, Window

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    native_app.activate()
    window = native_app.get_active_window()
    window.stack.set_visible_child_name("audible")
    window.library_loaded([Book(f"B{i:09}", f"Audiobook {i}", "Synthetic author", 60, None, True)
                           for i in range(150)])
    try:
        settle()
        # No page-wide scroller surrounds the toolbar; there is exactly one
        # library scroller, containing the rows rather than their actions.
        parent = window.library_toolbar.get_parent()
        while parent:
            assert not isinstance(parent, Gtk.ScrolledWindow)
            parent = parent.get_parent()
        assert window.book_list.is_ancestor(window.library_scroll)
        assert not window.library_toolbar.is_ancestor(window.library_scroll)
        before = window.library_toolbar.compute_bounds(window)[1]
        progress_before = window.progress.compute_bounds(window)[1]
        adjustment = window.library_scroll.get_vadjustment()
        assert adjustment.get_upper() > adjustment.get_page_size()
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        settle()
        after = window.library_toolbar.compute_bounds(window)[1]
        assert before.get_y() == after.get_y()
        assert window.progress.compute_bounds(window)[1].get_y() == progress_before.get_y()
        assert window.library_toolbar.get_mapped() and window.select_visible_button.is_sensitive()
        # Some window managers retain the user size of an already-presented
        # window. Request the compact size before presenting a fresh surface.
        window.destroy()
        window = Window(native_app)
        window.set_default_size(400, 780)
        window.stack.set_visible_child_name("audible")
        window.library_loaded([Book(f"B{i:09}", f"Audiobook {i}", "Synthetic author", 60, None, True)
                               for i in range(150)])
        window.present()
        settle()
        assert window.get_width() <= 420
        assert window.library_scroll.get_height() > 40
        assert window.library_toolbar.get_mapped()
        assert window.download_selected_button.get_width() <= window.get_width() - 36
    finally:
        window.destroy()


def test_library_actions_follow_visible_eligible_selection(native_app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    native_app.activate()
    window = native_app.get_active_window()
    books = [Book("B000000001", "Alpha", "Author", 60, None, True),
             Book("B000000002", "Beta", "Author", 60, None, True),
             Book("B000000003", "Unavailable", "Author", 60, None, False)]
    window.library_loaded(books)
    try:
        assert window.select_visible_button.get_sensitive()
        assert not window.clear_selection_button.get_sensitive()
        assert not window.download_selected_button.get_sensitive()
        window.select_visible_button.emit("clicked")
        assert window.book_checks == {books[0].asin: True, books[1].asin: True}
        assert not window.select_visible_button.get_sensitive()
        assert window.download_selected_button.get_sensitive()
        window.search.set_text("Alpha")
        window.render_books()
        window.clear_selection_button.emit("clicked")
        assert not window.book_checks[books[0].asin] and window.book_checks[books[1].asin]
        assert window.download_selected_button.get_sensitive()  # hidden selections remain eligible
        assert not window.clear_selection_button.get_sensitive()
        window.selection_changed(books[1].asin, False)
        assert not window.download_selected_button.get_sensitive()
        window.search.set_text("Unavailable")
        window.render_books()
        assert not window.select_visible_button.get_sensitive()
        window.busy = True
        window.update_library_actions()
        assert not window.download_selected_button.get_sensitive()
    finally:
        window.busy = False
        window.destroy()

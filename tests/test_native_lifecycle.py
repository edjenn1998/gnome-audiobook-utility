from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from audiobook_utility.credentials import SecretStore
from audiobook_utility.files import UtilityError


@pytest.mark.parametrize("operation", ["get", "put", "delete", "clear", "clear_media"])
@pytest.mark.parametrize("failure", [None, "collection", "operation"])
def test_keyring_connection_is_closed(operation, failure, monkeypatch):
    import secretstorage
    connection = Mock()
    collection = Mock()
    collection.is_locked.return_value = False
    collection.search_items.return_value = []
    monkeypatch.setattr(secretstorage, "dbus_init", lambda: connection)
    if failure == "collection":
        def acquire(_):
            raise OSError("synthetic unavailable service")
        monkeypatch.setattr(secretstorage, "get_default_collection", acquire)
    else:
        monkeypatch.setattr(secretstorage, "get_default_collection", lambda _: collection)
    if failure == "operation":
        collection.search_items.side_effect = OSError("synthetic item failure")
        collection.create_item.side_effect = OSError("synthetic item failure")
    method = getattr(SecretStore(), operation)
    arguments = ("auth", {}) if operation == "put" else ("auth",) if operation in {"get", "delete"} else ()
    if failure:
        with pytest.raises(UtilityError):
            method(*arguments)
    else:
        method(*arguments)
    connection.close.assert_called_once_with()


def test_open_action_is_page_specific_and_closed_windows_reject_work(native_app):
    from audiobook_utility.ui import Gdk
    native_app.activate()
    window = native_app.get_active_window()
    chosen = []
    window.choose = lambda *args, **kwargs: chosen.append((args, kwargs))
    try:
        window.stack.set_visible_child_name("audible")
        assert not window.key_pressed(None, Gdk.KEY_o, 0, Gdk.ModifierType.CONTROL_MASK)
        window.activate_action("win.open", None)
        assert not chosen
        window.stack.set_visible_child_name("merge")
        window.activate_action("win.open", None)
        assert chosen[-1][0] == (window.import_merge,)
        window.cleanup_resources()
        window.work("Closed", lambda *_: pytest.fail("Worker started after destruction"))
        assert not window.busy
    finally:
        window.destroy()


def test_login_escape_cancels_without_interacting_with_credentials():
    from audiobook_utility.login_window import Gdk, LoginWindow
    request = SimpleNamespace(cancel=Mock())
    window = SimpleNamespace(request=request, finish=Mock())
    window.close_requested = lambda: LoginWindow.close_requested(window)
    assert not LoginWindow.key_pressed(window, None, Gdk.KEY_a, 0, 0)
    assert LoginWindow.key_pressed(window, None, Gdk.KEY_Escape, 0, 0)
    request.cancel.assert_called_once_with()
    window.finish.assert_called_once_with()

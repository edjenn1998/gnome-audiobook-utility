import json
from contextlib import contextmanager

from . import APP_ID
from .files import UtilityError


class SecretStore:
    """Secret Service only; never falls back to plaintext storage."""

    @contextmanager
    def _collection(self):
        import secretstorage
        connection = None
        try:
            try:
                connection = secretstorage.dbus_init()
                collection = secretstorage.get_default_collection(connection)
                if collection.is_locked():
                    collection.unlock()
                if collection.is_locked():
                    raise UtilityError("Unlock your desktop keyring, then connect again.")
            except UtilityError:
                raise
            except Exception as exc:
                raise UtilityError("Desktop keyring unavailable. Start or unlock a Secret Service keyring.") from exc
            yield collection
        finally:
            if connection is not None:
                connection.close()

    def get(self, key: str):
        try:
            with self._collection() as collection:
                for item in collection.search_items({"application": APP_ID, "key": key}):
                    return json.loads(item.get_secret().decode())
                return None
        except UtilityError:
            raise
        except Exception as exc:
            raise UtilityError("Could not read the desktop keyring.") from exc

    def put(self, key: str, data):
        try:
            with self._collection() as collection:
                collection.create_item("Audiobook Utility session" if key == "auth" else "Audiobook Utility media license",
                    {"application": APP_ID, "key": key}, json.dumps(data).encode(), replace=True,
                    content_type="application/json")
        except UtilityError:
            raise
        except Exception as exc:
            raise UtilityError("Could not save to the desktop keyring.") from exc

    def clear(self):
        try:
            with self._collection() as collection:
                for item in collection.search_items({"application": APP_ID}):
                    item.delete()
        except UtilityError:
            raise
        except Exception as exc:
            raise UtilityError("Could not remove account data from the desktop keyring.") from exc

    def delete(self, key: str):
        try:
            with self._collection() as collection:
                for item in collection.search_items({"application": APP_ID, "key": key}):
                    item.delete()
        except UtilityError:
            raise
        except Exception as exc:
            raise UtilityError("Could not remove the selected item from the desktop keyring.") from exc

    def clear_media(self):
        try:
            with self._collection() as collection:
                for item in collection.search_items({"application": APP_ID}):
                    if item.get_attributes().get("key", "").startswith("media:"):
                        item.delete()
        except UtilityError:
            raise
        except Exception as exc:
            raise UtilityError("Some media licenses could not be removed. Retry explicit license deletion.") from exc

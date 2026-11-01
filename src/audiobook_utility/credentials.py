import json

from . import APP_ID
from .files import UtilityError


class SecretStore:
    """Secret Service only; never falls back to plaintext storage."""

    def _collection(self):
        import secretstorage
        try:
            connection = secretstorage.dbus_init()
            collection = secretstorage.get_default_collection(connection)
            if collection.is_locked():
                collection.unlock()
            if collection.is_locked():
                raise UtilityError("Unlock your desktop keyring, then connect again.")
            return collection
        except Exception as exc:
            raise UtilityError("Desktop keyring unavailable. Start or unlock a Secret Service keyring.") from exc

    def get(self, key: str):
        try:
            items = self._collection().search_items({"application": APP_ID, "key": key})
            for item in items:
                return json.loads(item.get_secret().decode())
            return None
        except UtilityError:
            raise
        except Exception as exc:
            raise UtilityError("Could not read the desktop keyring.") from exc

    def put(self, key: str, data):
        try:
            self._collection().create_item("Audiobook Utility session" if key == "auth" else "Audiobook Utility media license",
                {"application": APP_ID, "key": key}, json.dumps(data).encode(), replace=True,
                content_type="application/json")
        except UtilityError:
            raise
        except Exception as exc:
            raise UtilityError("Could not save to the desktop keyring.") from exc

    def clear(self):
        try:
            for item in self._collection().search_items({"application": APP_ID}):
                item.delete()
        except UtilityError:
            raise
        except Exception as exc:
            raise UtilityError("Could not remove account data from the desktop keyring.") from exc

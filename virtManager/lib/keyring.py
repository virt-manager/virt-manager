# Copyright (C) 2006, 2013 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gio
from gi.repository import GLib

from virtinst import log

from ..baseclass import vmmGObject


class _vmmSecret(object):
    def __init__(self, name, secret=None, attributes=None):
        self.name = name
        self.secret = secret
        self.attributes = attributes

    def get_secret(self):
        return self.secret
    def get_name(self):
        return self.name


class vmmKeyring(vmmGObject):
    """
    freedesktop Secret API abstraction
    """
    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = vmmKeyring()
        return cls._instance

    def __init__(self):
        vmmGObject.__init__(self)

        self._collection = None

        try:
            self._dbus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._service = Gio.DBusProxy.new_sync(self._dbus, 0, None,
                                    "org.freedesktop.secrets",
                                    "/org/freedesktop/secrets",
                                    "org.freedesktop.Secret.Service", None)

            self._session = self._service.OpenSession("(sv)", "plain",
                                                      GLib.Variant("s", ""))[1]

            self._collection = Gio.DBusProxy.new_sync(self._dbus, 0, None,
                                "org.freedesktop.secrets",
                                "/org/freedesktop/secrets/aliases/default",
                                "org.freedesktop.Secret.Collection", None)

            log.debug("Using keyring session %s", self._session)
        except Exception:  # pragma: no cover
            log.exception("Error determining keyring")

    def _cleanup(self):
        pass  # pragma: no cover

    def _find_secret_item_path(self, uuid, hvuri):
        attributes = {
            "uuid": uuid,
            "hvuri": hvuri,
        }
        unlocked, locked = self._service.SearchItems("(a{ss})", attributes)
        if not unlocked:
            if locked:
                log.warning(  # pragma: no cover
                        "Item found, but it's locked")
            return None
        return unlocked[0]

    def _do_prompt_if_needed(self, path):
        if path == "/":
            return
        iface = Gio.DBusProxy.new_sync(  # pragma: no cover
                self._dbus, 0, None,
                "org.freedesktop.secrets", path,
                "org.freedesktop.Secret.Prompt", None)
        iface.Prompt("(s)", "")  # pragma: no cover

    def _add_secret(self, secret):
        try:
            props = {
                "org.freedesktop.Secret.Item.Label": GLib.Variant("s", secret.get_name()),
                "org.freedesktop.Secret.Item.Attributes": GLib.Variant("a{ss}", secret.attributes),
            }
            params = (self._session, [],
                      [ord(v) for v in secret.get_secret()],
                      "text/plain; charset=utf8")
            replace = True

            dummy, prompt = self._collection.CreateItem("(a{sv}(oayays)b)",
                                              props, params, replace)
            self._do_prompt_if_needed(prompt)
        except Exception:  # pragma: no cover
            log.exception("Failed to add keyring secret")

    def _del_secret(self, uuid, hvuri):
        try:
            path = self._find_secret_item_path(uuid, hvuri)
            if path is None:
                return None

            iface = Gio.DBusProxy.new_sync(self._dbus, 0, None,
                                           "org.freedesktop.secrets", path,
                                           "org.freedesktop.Secret.Item", None)
            prompt = iface.Delete()
            self._do_prompt_if_needed(prompt)
        except Exception:  # pragma: no cover
            log.exception("Failed to delete keyring secret")

    def _get_secret(self, uuid, hvuri):
        ret = None
        try:
            path = self._find_secret_item_path(uuid, hvuri)
            if path is None:
                return None

            iface = Gio.DBusProxy.new_sync(self._dbus, 0, None,
                                    "org.freedesktop.secrets", path,
                                    "org.freedesktop.Secret.Item", None)

            secretbytes = iface.GetSecret("(o)", self._session)[2]
            label = iface.get_cached_property("Label").unpack().strip("'")
            dbusattrs = iface.get_cached_property("Attributes").unpack()

            secret = "".join([chr(c) for c in secretbytes])

            attrs = {}
            for key, val in dbusattrs.items():
                if key not in ["hvuri", "uuid"]:
                    continue
                attrs["%s" % key] = "%s" % val

            ret = _vmmSecret(label, secret, attrs)
        except Exception:  # pragma: no cover
            log.exception("Failed to get keyring secret uuid=%r hvuri=%r", uuid, hvuri)

        return ret


    ##############
    # Public API #
    ##############

    def is_available(self):
        return not (self._collection is None)

    def _get_secret_name(self, vm):
        return "vm-console-" + vm.get_uuid()

    def get_console_password(self, vm):
        if not self.is_available():
            return ("", "")  # pragma: no cover

        secret = self._get_secret(vm.get_uuid(), vm.conn.get_uri())
        if secret is None:
            return ("", "")  # pragma: no cover

        return (secret.get_secret(), vm.get_console_username() or "")

    def set_console_password(self, vm, password, username=""):
        if not self.is_available():
            return  # pragma: no cover


        secret = _vmmSecret(self._get_secret_name(vm), password,
                           {"uuid": vm.get_uuid(),
                            "hvuri": vm.conn.get_uri()})
        vm.set_console_username(username)
        self._add_secret(secret)

    def del_console_password(self, vm):
        if not self.is_available():
            return  # pragma: no cover

        self._del_secret(vm.get_uuid(), vm.conn.get_uri())
        vm.del_console_username()

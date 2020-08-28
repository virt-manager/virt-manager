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

    def _add_secret(self, secret):
        ret = None
        try:
            props = {
                "org.freedesktop.Secret.Item.Label": GLib.Variant("s", secret.get_name()),
                "org.freedesktop.Secret.Item.Attributes": GLib.Variant("a{ss}", secret.attributes),
            }
            params = (self._session, [],
                      [ord(v) for v in secret.get_secret()],
                      "text/plain; charset=utf8")
            replace = True

            _id = self._collection.CreateItem("(a{sv}(oayays)b)",
                                              props, params, replace)[0]
            ret = int(_id.rsplit("/")[-1])
        except Exception:  # pragma: no cover
            log.exception("Failed to add keyring secret")

        return ret

    def _del_secret(self, _id):
        try:
            path = self._collection.get_object_path() + "/" + str(_id)
            iface = Gio.DBusProxy.new_sync(self._dbus, 0, None,
                                           "org.freedesktop.secrets", path,
                                           "org.freedesktop.Secret.Item", None)
            iface.Delete("(s)", "/")
        except Exception:
            log.exception("Failed to delete keyring secret")

    def _get_secret(self, _id):
        ret = None
        try:
            path = self._collection.get_object_path() + "/" + str(_id)
            iface = Gio.DBusProxy.new_sync(self._dbus, 0, None,
                                    "org.freedesktop.secrets", path,
                                    "org.freedesktop.Secret.Item", None)

            secretbytes = iface.GetSecret("(o)", self._session)[2]
            label = iface.get_cached_property("Label").unpack().strip("'")
            dbusattrs = iface.get_cached_property("Attributes").unpack()

            secret = u"".join([chr(c) for c in secretbytes])

            attrs = {}
            for key, val in dbusattrs.items():
                if key not in ["hvuri", "uuid"]:
                    continue
                attrs["%s" % key] = "%s" % val

            ret = _vmmSecret(label, secret, attrs)
        except Exception:  # pragma: no cover
            log.exception("Failed to get keyring secret id=%s", _id)

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

        username, keyid = vm.get_console_password()

        if keyid == -1:
            return ("", "")

        secret = self._get_secret(keyid)
        if secret is None or secret.get_name() != self._get_secret_name(vm):
            return ("", "")  # pragma: no cover

        if (secret.attributes.get("hvuri", None) != vm.conn.get_uri() or
            secret.attributes.get("uuid", None) != vm.get_uuid()):
            return ("", "")  # pragma: no cover

        return (secret.get_secret(), username or "")

    def set_console_password(self, vm, password, username=""):
        if not self.is_available():
            return  # pragma: no cover

        secret = _vmmSecret(self._get_secret_name(vm), password,
                           {"uuid": vm.get_uuid(),
                            "hvuri": vm.conn.get_uri()})
        keyid = self._add_secret(secret)
        if keyid is None:
            return  # pragma: no cover

        vm.set_console_password(username, keyid)

    def del_console_password(self, vm):
        if not self.is_available():
            return  # pragma: no cover

        ignore, keyid = vm.get_console_password()
        if keyid == -1:
            return

        self._del_secret(keyid)
        vm.del_console_password()

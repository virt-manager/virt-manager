# Copyright (C) 2006, 2013 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging

from gi.repository import Gio
from gi.repository import GLib


class vmmSecret(object):
    def __init__(self, name, secret=None, attributes=None):
        self.name = name
        self.secret = secret
        self.attributes = attributes

    def get_secret(self):
        return self.secret
    def get_name(self):
        return self.name


class vmmKeyring(object):

    def __init__(self):
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

            logging.debug("Using keyring session %s", self._session)
        except Exception:
            logging.exception("Error determining keyring")


    ##############
    # Public API #
    ##############

    def is_available(self):
        return not (self._collection is None)

    def add_secret(self, secret):
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
        except Exception:
            logging.exception("Failed to add keyring secret")

        return ret

    def del_secret(self, _id):
        try:
            path = self._collection.get_object_path() + "/" + str(_id)
            iface = Gio.DBusProxy.new_sync(self._dbus, 0, None,
                                           "org.freedesktop.secrets", path,
                                           "org.freedesktop.Secret.Item", None)
            iface.Delete("(s)", "/")
        except Exception:
            logging.exception("Failed to delete keyring secret")

    def get_secret(self, _id):
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

            ret = vmmSecret(label, secret, attrs)
        except Exception:
            logging.exception("Failed to get keyring secret id=%s", _id)

        return ret

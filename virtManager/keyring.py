#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.
#

import logging

try:
    from gi.repository import GnomeKeyring  # pylint: disable=E0611
except:
    GnomeKeyring = None
    logging.debug("GnomeKeyring bindings not installed, no keyring support")


class vmmSecret(object):
    def __init__(self, name, secret=None, attributes=None):
        self.name = name
        self.secret = secret

        self.attributes = {}
        if isinstance(attributes, dict):
            self.attributes = attributes
        elif isinstance(attributes, list):
            for attr in attributes:
                self.attributes[attr.name] = attr.get_string()

    def get_secret(self):
        return self.secret
    def get_name(self):
        return self.name

    def get_attributes_for_keyring(self):
        attrs = GnomeKeyring.attribute_list_new()
        for key, value in self.attributes.items():
            GnomeKeyring.attribute_list_append_string(attrs, key, value)
        return attrs


class vmmKeyring(object):
    def __init__(self):
        self.keyring = None
        if GnomeKeyring is None:
            return

        try:
            result = GnomeKeyring.get_default_keyring_sync()
            if result and result[0] == GnomeKeyring.Result.OK:
                self.keyring = result[1]

            if self.keyring is None:
                self.keyring = 'default'
                logging.debug("No default keyring, creating '%s'",
                              self.keyring)
                try:
                    GnomeKeyring.create_sync(self.keyring, None)
                except GnomeKeyring.AlreadyExistsError:
                    pass
        except:
            logging.exception("Error determining keyring")
            self.keyring = None

    def is_available(self):
        return not (self.keyring is None)

    def add_secret(self, secret):
        _id = None
        try:
            result, _id = GnomeKeyring.item_create_sync(
                                    self.keyring,
                                    GnomeKeyring.ItemType.GENERIC_SECRET,
                                    secret.get_name(),
                                    secret.get_attributes_for_keyring(),
                                    secret.get_secret(),
                                    True)

            if result != GnomeKeyring.Result.OK:
                raise RuntimeError("Creating keyring item failed with: %s" %
                                   repr(result))
        except:
            logging.exception("Failed to add keyring secret")

        return _id

    def get_secret(self, _id):
        """
        ignore, item = GnomeKeyring.item_get_info_sync(self.keyring, _id)
        if item is None:
            return

        sec = None
        try:
            result, attrs = GnomeKeyring.item_get_attributes_sync(
                                                        self.keyring, _id)
            if result != GnomeKeyring.Result.OK:
                raise RuntimeError("Fetching keyring attributes failed "
                                   "with %s" % result)

            sec = vmmSecret(item.get_display_name(), item.get_secret(), attrs)
        except:
            logging.exception("Failed to lookup keyring item %s", item)

        return sec
        """
        # FIXME: Uncomment this once gnome-keyring is fixed
        # https://bugzilla.gnome.org/show_bug.cgi?id=691638
        ignore = _id
        return None

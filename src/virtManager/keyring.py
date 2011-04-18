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
from virtManager.secret import vmmSecret

import logging

haveKeyring = False

try:
    import gnomekeyring
    haveKeyring = True
except:
    logging.warning("gnomekeyring bindings not installed, no keyring support")

class vmmKeyring(object):
    def __init__(self):
        self.keyring = None
        if not haveKeyring:
            return

        try:
            self.keyring = gnomekeyring.get_default_keyring_sync()
            if self.keyring == None:
                # Code borrowed from
                # http://trac.gajim.org/browser/src/common/passwords.py
                self.keyring = 'default'
                try:
                    gnomekeyring.create_sync(self.keyring, None)
                except gnomekeyring.AlreadyExistsError:
                    pass
        except:
            logging.exception("Error determining keyring")
            self.keyring = None

    def is_available(self):
        return not (self.keyring == None)

    def add_secret(self, secret):
        _id = None
        try:
            _id = gnomekeyring.item_create_sync(self.keyring,
                                               gnomekeyring.ITEM_GENERIC_SECRET,
                                               secret.get_name(),
                                               secret.get_attributes(),
                                               secret.get_secret(),
                                               True)

        except:
            logging.exception("Failed to add keyring secret")

        return _id

    def get_secret(self, _id):
        sec = None
        try:
            item = gnomekeyring.item_get_info_sync(self.keyring, _id)
            attrs = gnomekeyring.item_get_attributes_sync(self.keyring, _id)
            sec = vmmSecret(item.get_display_name(), item.get_secret(), attrs)
        except:
            pass

        return sec

    def clear_secret(self, _id):
        try:
            gnomekeyring.item_delete_sync(self.keyring, _id)
            return True
        except:
            return False

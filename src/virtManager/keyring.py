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

import sys
import logging

haveKeyring = False

try:
    import gnomekeyring
    haveKeyring = True
except:
    logging.warning("No support for gnome-keyring")
    pass

class vmmKeyring:

    def __init__(self):
        if haveKeyring:
            try:
                if not("default" in gnomekeyring.list_keyring_names_sync()):
                    gnomekeyring.create_sync("default", None)
                self.keyring = gnomekeyring.get_default_keyring_sync()
            except:
                logging.warning(("Keyring unavailable: '%s'") % (str((sys.exc_info())[0]) + " "  + str((sys.exc_info())[1])))
                self.keyring = None
        else:
            self.keyring = None


    def is_available(self):
        if self.keyring == None:
            return False
        return True

    def add_secret(self, secret):
        try:
            id = gnomekeyring.item_create_sync(self.keyring,
                                               gnomekeyring.ITEM_GENERIC_SECRET,
                                               secret.get_name(),
                                               secret.get_attributes(),
                                               secret.get_secret(),
                                               True)
            
            return id
        except:
            return None

    def get_secret(self, id):
        try:
            item = gnomekeyring.item_get_info_sync(self.keyring, id)
            
            attrs = gnomekeyring.item_get_attributes_sync(self.keyring, id)
            
            return vmmSecret(item.get_display_name(), item.get_secret(), attrs)
        except:
            return None
        

    def clear_secret(self, id):
        try:
            gnomekeyring.item_delete_sync(self.keyring, id)
            return True
        except:
            return False


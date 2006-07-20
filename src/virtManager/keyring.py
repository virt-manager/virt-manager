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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#
#
# There is no python binding for keyring in FC5 so we use
# ctypes to do the magic. This code is scary, but works
# pretty well...so far
#
# XXX audit this code for memory leaks. The gnome-keyring API
# docs are non-existant so i've no clue what bits are the callers
# responsibility to free() :-(

import gtk

from ctypes import *
import gobject

from virtManager.secret import *

class vmmKeyring:
    # Map to GnomeKeyringAttribute struct
    # XXX lame that we have  32 & 64 bit variant
    # need to get the Union stuff working for the
    # 'value' field which should solve the padding
    # problems automagically
    class Attribute64(Structure):
        _fields_ =[('name', c_char_p),
                   ('type', c_int),
                   ('pad', c_int),
                   ('value', c_char_p)]
    class Attribute32(Structure):
        _fields_ =[('name', c_char_p),
                   ('type', c_int),
                   ('value', c_char_p)]

    # Hack to map to GArray struct in glib
    class GArray(Structure):
        _fields_ = [('data', c_char_p),
                    ('len', c_uint)]

    def __init__(self):
        # Load the two libs we need to play with
        self.glib = cdll.LoadLibrary("libglib-2.0.so")
        self.krlib = cdll.LoadLibrary("libgnome-keyring.so")

        # Declare the callback type
        cbtype = CFUNCTYPE(c_void_p, c_int, c_char_p, c_void_p)
        self.cb = cbtype(self._get_default_keyring_complete)

        # This gets filled out by callback with keyring name
        self.keyring = None
        
        # Get the keyring name
        f = self.krlib.gnome_keyring_get_default_keyring(self.cb, None, None)
        # Block until complete
        # XXX lame - blocks whole UI
        gtk.main()

        # User might have denied access
        if self.keyring == None:
            raise "Cannot access default keyring"


    def add_secret(self, secret):
        # We need to store the attributes in an array
        g_array_new = self.glib.g_array_new
        g_array_new.restype = c_void_p

        # XXX remove this lame 32/64 bit fork
        if sizeof(c_void_p) == 4:
            attrs = g_array_new(c_int(0), c_int(0), sizeof(c_char_p) + sizeof(c_int) + sizeof(c_char_p))
        else:
            attrs = g_array_new(c_int(0), c_int(0), sizeof(c_char_p) + sizeof(c_int) + sizeof(c_int)  + sizeof(c_char_p))

        # Key a hold of them so they not immediately garbage collected
        saveAttrs = {}
        for key in secret.list_attributes():
            # Add all attributes to array
            a = None
            # XXX remove this lame 32/64 bit fork
            if sizeof(c_void_p) == 4:
                a = vmmKeyring.Attribute32(name= c_char_p(key),
                                           type= c_int(0),
                                           value= c_char_p(str(secret.get_attribute(key))))
            else:
                a = vmmKeyring.Attribute64(name= c_char_p(key),
                                           type= c_int(0),
                                           pad= c_int(0),
                                           value= c_char_p(str(secret.get_attribute(key))))
            saveAttrs[key] = a
            self.glib.g_array_append_vals(attrs, byref(a), 1)

        # Declare callback type
        cbaddtype = CFUNCTYPE(c_void_p, c_int, c_int, POINTER(c_int))
        self.cbadd = cbaddtype(self._add_secret_complete)

        # Fetch handle to our function
        creator = self.krlib.gnome_keyring_item_create
        creator.restype = c_void_p
        # Callback will populate id of the secret in this
        id = c_int(-1)

        # Now add the secret
        creator(None, c_int(0), c_char_p(secret.get_name()), attrs, c_char_p(secret.get_secret()), c_int(1), self.cbadd, pointer(id), None)
        # Block until compelte
        gtk.main()

        # Release attributes no longer neede
        self.glib.g_array_free(attrs)

        return id.value

    def get_secret(self, id):
        # Declare the callback type
        cbgetinfotype = CFUNCTYPE(c_void_p, c_int, c_void_p, POINTER(c_int))
        self.cbgetinfo = cbgetinfotype(self._get_item_info_complete)

        # Fetch the method we want to call
        getinfo = self.krlib.gnome_keyring_item_get_info
        getinfo.restype = c_void_p

        # We need this in callback
        i = c_int(id)

        # Fetch the basic info
        p = getinfo(c_char_p(self.keyring), c_int(id), self.cbgetinfo, pointer(i), None)
        # Block until done
        gtk.main()
        if self.secrets.has_key(id):
            # Declare callback type
            cbgetattrstype = CFUNCTYPE(c_void_p, c_int, POINTER(vmmKeyring.GArray), POINTER(c_int))
            self.cbgetattrs = cbgetattrstype(self._get_item_attrs_complete)

            # Declare function we wnt to call to get attributes
            getattrs = self.krlib.gnome_keyring_item_get_attributes
            getattrs.restype = c_void_p

            # Fetch the attrs
            getattrs(c_char_p(self.keyring), c_int(id), self.cbgetattrs, pointer(i), None)
            # Block until done
            gtk.main()
            
            secret = self.secrets[id]
            del self.secrets[id]
            return secret
        else:
            return None

    def clear_secret(self, id):
        # Declare the callback type
        cbdeletetype = CFUNCTYPE(c_void_p, c_int, c_void_p)
        self.cbdelete = cbdeletetype(self._delete_item_complete)

        # Fetch the method we want to call
        getinfo = self.krlib.gnome_keyring_item_delete
        getinfo.restype = c_void_p

        # Fetch the basic info
        p = getinfo(c_char_p(self.keyring), c_int(id), self.cbdelete, None, None)
        # Block until done
        gtk.main()

    def _get_default_keyring_complete(self, status, name, data):
        if status != 0:
            self.keyring = None
            gtk.main_quit()
            return
        # Save name of default keyring somewhere safe
        if name == None:
            name = ""
        self.keyring = name
        gtk.main_quit()

    def _add_secret_complete(self, status, id, data):
        if status != 0:
            data.contents.value = -1
            gtk.main_quit()
            return
        data.contents.value = id
        gtk.main_quit()

    def _delete_item_complete(self, status, data):
        gtk.main_quit()

    def _get_item_info_complete(self, status, info, data=None):
        if status != 0:
            gtk.main_quit()
            return

        getname = self.krlib.gnome_keyring_item_info_get_display_name
        getname.restype = c_char_p

        getsecret = self.krlib.gnome_keyring_item_info_get_secret
        getsecret.restype = c_char_p

        name = getname(info)
        secret = getsecret(info)

        self.secrets[data.contents.value] = vmmSecret(name, secret)

        gtk.main_quit()

    def _get_item_attrs_complete(self, status, attrs, data=None):
        if status != 0:
            gtk.main_quit()
            return

        # XXX @#%$&(#%@  glib has a macro for accessing
        # elements in array which can obviously can't use
        # from python. Figure out nasty pointer magic here...

        gtk.main_quit()

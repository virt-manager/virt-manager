#
# Copyright (C) 2008 Red Hat, Inc.
# Copyright (C) 2008 Cole Robinson <crobinso@redhat.com>
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

import gobject
import virtinst.util as util

class vmmStorageVolume(gobject.GObject):
    __gsignals__ = { }

    def __init__(self, config, connection, vol, name):
        self.__gobject_init__()
        self.config = config
        self.connection = connection
        self.vol = vol              # Libvirt storage volume object
        self.name = name
        self._xml = None             # Cache xml rather than repeated lookups
        self._update_xml()

    def get_connection(self):
        return self.connection

    def get_name(self):
        return self.name

    def get_path(self):
        return self.vol.path()

    def get_pool(self):
        pobj = self.vol.storagePoolLookupByVolume()
        return self.connection.get_pool_by_name(pobj.name())

    def delete(self):
        self.vol.delete(0)
        del(self.vol)

    def get_xml(self):
        if self._xml is None:
            self._update_xml()
        return self._xml

    def get_target_path(self):
        return util.get_xml_path(self.get_xml(),"/volume/target/path")

    def get_format(self):
        return util.get_xml_path(self.get_xml(),"/volume/target/format/@type")

    def get_allocation(self):
        return long(util.get_xml_path(self.get_xml(),"/volume/allocation"))
    def get_capacity(self):
        return long(util.get_xml_path(self.get_xml(),"/volume/capacity"))

    def get_pretty_capacity(self):
        return self._prettyify(self.get_capacity())
    def get_pretty_allocation(self):
        return self._prettyify(self.get_allocation())

    def get_type(self):
        return util.get_xml_path(self.get_xml(),"/volume/format/@type")

    def _update_xml(self):
        self._xml = self.vol.XMLDesc(0)

    def _prettyify(self, val):
        if val > (1024*1024*1024):
            return "%2.2f GB" % (val/(1024.0*1024.0*1024.0))
        else:
            return "%2.2f MB" % (val/(1024.0*1024.0))

gobject.type_register(vmmStorageVolume)

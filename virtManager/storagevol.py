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

from virtinst.util import xpath

from virtManager import util
from virtManager.libvirtobject import vmmLibvirtObject


class vmmStorageVolume(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key)

        self._name = key

    # Required class methods
    def get_name(self):
        return self._name
    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)

    def get_path(self):
        return self._backend.path()

    def get_pool(self):
        pobj = self._backend.storagePoolLookupByVolume()
        return self.conn.get_pool_by_name(pobj.name())

    def delete(self):
        self._backend.delete(0)
        self._backend = None

    def get_target_path(self):
        return xpath(self.get_xml(), "/volume/target/path")

    def get_format(self):
        return xpath(self.get_xml(), "/volume/target/format/@type")

    def get_allocation(self):
        return long(xpath(self.get_xml(), "/volume/allocation"))
    def get_capacity(self):
        return long(xpath(self.get_xml(), "/volume/capacity"))

    def get_pretty_capacity(self):
        return util.pretty_bytes(self.get_capacity())
    def get_pretty_allocation(self):
        return util.pretty_bytes(self.get_allocation())

    def get_type(self):
        return xpath(self.get_xml(), "/volume/format/@type")

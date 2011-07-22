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

from virtManager import util
from virtManager.libvirtobject import vmmLibvirtObject

class vmmStorageVolume(vmmLibvirtObject):
    def __init__(self, conn, vol, name):
        vmmLibvirtObject.__init__(self, conn)

        self.vol = vol      # Libvirt storage volume object
        self.name = name

    # Required class methods
    def get_name(self):
        return self.name
    def _XMLDesc(self, flags):
        return self.vol.XMLDesc(flags)

    def get_path(self):
        return self.vol.path()

    def get_pool(self):
        pobj = self.vol.storagePoolLookupByVolume()
        return self.conn.get_pool_by_name(pobj.name())

    def delete(self):
        self.vol.delete(0)
        del(self.vol)

    def get_target_path(self):
        return util.xpath(self.get_xml(), "/volume/target/path")

    def get_format(self):
        return util.xpath(self.get_xml(), "/volume/target/format/@type")

    def get_allocation(self):
        return long(util.xpath(self.get_xml(), "/volume/allocation"))
    def get_capacity(self):
        return long(util.xpath(self.get_xml(), "/volume/capacity"))

    def get_pretty_capacity(self):
        return util.pretty_bytes(self.get_capacity())
    def get_pretty_allocation(self):
        return util.pretty_bytes(self.get_allocation())

    def get_type(self):
        return util.xpath(self.get_xml(), "/volume/format/@type")

vmmLibvirtObject.type_register(vmmStorageVolume)

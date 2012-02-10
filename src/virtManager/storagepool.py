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

import virtinst

from virtManager import util
from virtManager.libvirtobject import vmmLibvirtObject
from virtManager.storagevol import vmmStorageVolume

class vmmStoragePool(vmmLibvirtObject):
    def __init__(self, conn, pool, uuid, active):
        vmmLibvirtObject.__init__(self, conn)

        self.pool = pool            # Libvirt pool object
        self.uuid = uuid            # String UUID
        self.active = active        # bool indicating if it is running

        self._volumes = {}          # UUID->vmmStorageVolume mapping of the
                                    # pools associated volumes

        self.refresh()

    # Required class methods
    def get_name(self):
        return self.pool.name()
    def _XMLDesc(self, flags):
        return self.pool.XMLDesc(flags)
    def _define(self, xml):
        return self.conn.vmm.storagePoolDefineXML(xml, 0)


    def set_active(self, state):
        self.active = state
        self.refresh_xml()

    def is_active(self):
        return self.active

    def can_change_alloc(self):
        typ = self.get_type()
        return (typ in [virtinst.Storage.StoragePool.TYPE_LOGICAL])

    def get_uuid(self):
        return self.uuid

    def start(self):
        self.pool.create(0)
        self.idle_add(self.refresh_xml)

    def stop(self):
        self.pool.destroy()
        self.idle_add(self.refresh_xml)

    def delete(self, nodelete=True):
        if nodelete:
            self.pool.undefine()
        else:
            self.pool.delete(0)
        del(self.pool)

    def set_autostart(self, value):
        self.pool.setAutostart(value)

    def get_autostart(self):
        return self.pool.autostart()

    def get_target_path(self):
        return util.xpath(self.get_xml(), "/pool/target/path")

    def get_allocation(self):
        return long(util.xpath(self.get_xml(), "/pool/allocation"))
    def get_available(self):
        return long(util.xpath(self.get_xml(), "/pool/available"))
    def get_capacity(self):
        return long(util.xpath(self.get_xml(), "/pool/capacity"))

    def get_pretty_allocation(self):
        return util.pretty_bytes(self.get_allocation())
    def get_pretty_available(self):
        return util.pretty_bytes(self.get_available())
    def get_pretty_capacity(self):
        return util.pretty_bytes(self.get_capacity())

    def get_type(self):
        return util.xpath(self.get_xml(), "/pool/@type")

    def get_volumes(self):
        self.update_volumes()
        return self._volumes

    def get_volume(self, uuid):
        return self._volumes[uuid]

    def refresh(self):
        if not self.active:
            return

        def cb():
            self.refresh_xml()
            self.update_volumes(refresh=True)
            self.emit("refreshed")

        self.pool.refresh(0)
        self.idle_add(cb)

    def update_volumes(self, refresh=False):
        if not self.is_active():
            self._volumes = {}
            return

        vols = self.pool.listVolumes()
        new_vol_list = {}

        for volname in vols:
            if volname in self._volumes:
                new_vol_list[volname] = self._volumes[volname]
                if refresh:
                    new_vol_list[volname].refresh_xml()
            else:
                new_vol_list[volname] = vmmStorageVolume(self.conn,
                                    self.pool.storageVolLookupByName(volname),
                                    volname)
        self._volumes = new_vol_list

vmmLibvirtObject.type_register(vmmStoragePool)
vmmStoragePool.signal_new(vmmStoragePool, "refreshed", [])

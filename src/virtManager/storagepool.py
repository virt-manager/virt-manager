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
import libvirt
import libxml2
import logging
import virtinst
import virtinst.util as util

from virtManager.storagevol import vmmStorageVolume

class vmmStoragePool(gobject.GObject):
    __gsignals__ = { }

    def __init__(self, config, connection, pool, uuid, active):
        self.__gobject_init__()
        self.config = config
        self.connection = connection
        self.pool = pool            # Libvirt pool object
        self.uuid = uuid            # String UUID
        self.active = active        # bool indicating if it is running

        self._volumes = {}          # UUID->vmmStorageVolume mapping of the
                                    # pools associated volumes
        self._xml = None            # xml cache
        self._update_xml()
        self.update_volumes()

    def set_active(self, state):
        self.active = state
        self._update_xml()

    def is_active(self):
        return self.active

    def can_change_alloc(self):
        type = self.get_type()
        return (type in [virtinst.Storage.StoragePool.TYPE_LOGICAL])

    def get_connection(self):
        return self.connection

    def get_name(self):
        return self.pool.name()

    def get_uuid(self):
        return self.uuid

    def start(self):
        self.pool.create(0)
        self._update_xml()

    def stop(self):
        self.pool.destroy()
        self._update_xml()

    def delete(self, nodelete=True):
        if nodelete:
            self.pool.undefine()
        else:
            self.pool.delete(0)
        del(self.pool)

    def _update_xml(self):
        self._xml = self.pool.XMLDesc(0)

    def get_xml(self):
        if self._xml is None:
            self._update_xml()
        return self._xml

    def set_autostart(self, value):
        self.pool.setAutostart(value)

    def get_autostart(self):
        return self.pool.autostart()

    def get_target_path(self):
        return util.get_xml_path(self.get_xml(), "/pool/target/path")

    def get_allocation(self):
        return long(util.get_xml_path(self.get_xml(), "/pool/allocation"))
    def get_available(self):
        return long(util.get_xml_path(self.get_xml(), "/pool/available"))
    def get_capacity(self):
        return long(util.get_xml_path(self.get_xml(), "/pool/capacity"))

    def get_pretty_allocation(self):
        return self._prettyify(self.get_allocation())
    def get_pretty_available(self):
        return self._prettyify(self.get_available())
    def get_pretty_capacity(self):
        return self._prettyify(self.get_capacity())

    def get_type(self):
        return util.get_xml_path(self.get_xml(), "/pool/@type")

    def get_volumes(self):
        self.update_volumes()
        return self._volumes

    def get_volume(self, uuid):
        return self._volumes[uuid]

    def refresh(self):
        self.pool.refresh(0)

    def update_volumes(self):
        if not self.is_active():
            self._volumes = {}
            return

        vols = self.pool.listVolumes()
        new_vol_list = {}

        for volname in vols:
            if self._volumes.has_key(volname):
                new_vol_list[volname] = self._volumes[volname]
            else:
                new_vol_list[volname] = vmmStorageVolume(self.config,
                                                         self.connection,
                                                         self.pool.storageVolLookupByName(volname),
                                                         volname)
        self._volumes = new_vol_list


    def _prettyify(self, val):
        if val > (1024*1024*1024):
            return "%2.2f GB" % (val/(1024.0*1024.0*1024.0))
        else:
            return "%2.2f MB" % (val/(1024.0*1024.0))

gobject.type_register(vmmStoragePool)

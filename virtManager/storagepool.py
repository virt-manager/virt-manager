#
# Copyright (C) 2008, 2013 Red Hat, Inc.
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

# pylint: disable=E0611
from gi.repository import GObject
# pylint: enable=E0611

from virtinst import pollhelpers
from virtinst import StoragePool, StorageVolume
from virtinst import util

from virtManager.libvirtobject import vmmLibvirtObject


class vmmStorageVolume(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, StorageVolume)


    ##########################
    # Required class methods #
    ##########################

    def get_name(self):
        return self.get_xmlobj().name
    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)


    ###########
    # Actions #
    ###########

    def get_parent_pool(self):
        pobj = self._backend.storagePoolLookupByVolume()
        return self.conn.get_pool_by_name(pobj.name())

    def delete(self, force=True):
        ignore = force
        self._backend.delete(0)
        self._backend = None


    #################
    # XML accessors #
    #################

    def get_target_path(self):
        return self.get_xmlobj().target_path or ""
    def get_format(self):
        return self.get_xmlobj().format
    def get_capacity(self):
        return self.get_xmlobj().capacity
    def get_allocation(self):
        return self.get_xmlobj().allocation

    def get_pretty_capacity(self):
        return util.pretty_bytes(self.get_capacity())
    def get_pretty_allocation(self):
        return util.pretty_bytes(self.get_allocation())


class vmmStoragePool(vmmLibvirtObject):
    __gsignals__ = {
        "refreshed": (GObject.SignalFlags.RUN_FIRST, None, [])
    }

    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, StoragePool)

        self._active = True
        self._support_isactive = None

        self._volumes = {}

        self.tick()
        self.refresh()


    ##########################
    # Required class methods #
    ##########################

    def get_name(self):
        return self.get_xmlobj().name
    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def _define(self, xml):
        return self.conn.define_pool(xml)


    ###########
    # Actions #
    ###########

    def is_active(self):
        return self._active
    def _backend_get_active(self):
        if self._support_isactive is None:
            self._support_isactive = self.conn.check_support(
                self.conn.SUPPORT_POOL_ISACTIVE, self._backend)

        if not self._support_isactive:
            return True
        return bool(self._backend.isActive())

    def _set_active(self, state):
        if state == self._active:
            return
        self.idle_emit(state and "started" or "stopped")
        self._active = state
        self.refresh_xml()

    def _kick_conn(self):
        self.conn.schedule_priority_tick(pollpool=True)
    def tick(self):
        self._set_active(self._backend_get_active())

    def set_autostart(self, value):
        self._backend.setAutostart(value)
    def get_autostart(self):
        return self._backend.autostart()

    def can_change_alloc(self):
        typ = self.get_type()
        return (typ in [StoragePool.TYPE_LOGICAL])
    def supports_volume_creation(self):
        return self.get_xmlobj().supports_volume_creation()

    def start(self):
        self._backend.create(0)
        self._kick_conn()
        self.idle_add(self.refresh_xml)

    def stop(self):
        self._backend.destroy()
        self._kick_conn()
        self.idle_add(self.refresh_xml)

    def delete(self, force=True):
        ignore = force
        self._backend.undefine()
        self._backend = None
        self._kick_conn()

    def refresh(self):
        if not self.is_active():
            return

        def cb():
            self.refresh_xml()
            self.update_volumes(refresh=True)
            self.emit("refreshed")

        self._backend.refresh(0)
        self.idle_add(cb)

    def define_name(self, newname):
        return self._define_name_helper("storagepool",
                                        self.conn.rename_pool,
                                        newname)

    ###################
    # Volume handling #
    ###################

    def get_volumes(self, refresh=True):
        if refresh:
            self.update_volumes()
        return self._volumes

    def get_volume(self, uuid):
        return self._volumes[uuid]

    def update_volumes(self, refresh=False):
        if not self.is_active():
            self._volumes = {}
            return

        (ignore, new, allvols) = pollhelpers.fetch_volumes(
            self.conn.get_backend(), self.get_backend(), self._volumes.copy(),
            lambda obj, key: vmmStorageVolume(self.conn, obj, key))

        for volname in allvols:
            if volname not in new and refresh:
                allvols[volname].refresh_xml()
        self._volumes = allvols


    #################
    # XML accessors #
    #################

    def get_type(self):
        return self.get_xmlobj().type
    def get_uuid(self):
        return self.get_xmlobj().uuid
    def get_target_path(self):
        return self.get_xmlobj().target_path or ""

    def get_allocation(self):
        return self.get_xmlobj().allocation
    def get_available(self):
        return self.get_xmlobj().available
    def get_capacity(self):
        return self.get_xmlobj().capacity

    def get_pretty_allocation(self):
        return util.pretty_bytes(self.get_allocation())
    def get_pretty_available(self):
        return util.pretty_bytes(self.get_available())
    def get_pretty_capacity(self):
        return util.pretty_bytes(self.get_capacity())

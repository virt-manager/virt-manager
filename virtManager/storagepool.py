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

import logging
import time

from gi.repository import GObject

from virtinst import pollhelpers
from virtinst import StoragePool, StorageVolume
from virtinst import util

from .libvirtobject import vmmLibvirtObject


class vmmStorageVolume(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, StorageVolume)


    ##########################
    # Required class methods #
    ##########################

    def _conn_tick_poll_param(self):
        return None
    def class_name(self):
        return "volume"

    def _XMLDesc(self, flags):
        try:
            return self._backend.XMLDesc(flags)
        except Exception as e:
            logging.debug("XMLDesc for vol=%s failed: %s",
                self._backend.key(), e)
            raise

    def _get_backend_status(self):
        return self._STATUS_ACTIVE

    def tick(self, stats_update=True):
        # Deliberately empty
        ignore = stats_update
    def _init_libvirt_state(self):
        self.ensure_latest_xml()


    ###########
    # Actions #
    ###########

    def get_parent_pool(self):
        name = self._backend.storagePoolLookupByVolume().name()
        for pool in self.conn.list_pools():
            if pool.get_name() == name:
                return pool

    def delete(self, force=True):
        ignore = force
        self._backend.delete(0)
        self._backend = None


    #################
    # XML accessors #
    #################

    def get_key(self):
        return self.get_xmlobj().key or ""
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

    def get_pretty_name(self, pooltype):
        name = self.get_name()
        if pooltype != "iscsi":
            return name

        key = self.get_key()
        if not key:
            return name
        return "%s (%s)" % (name, key)


class vmmStoragePool(vmmLibvirtObject):
    __gsignals__ = {
        "refreshed": (GObject.SignalFlags.RUN_FIRST, None, [])
    }

    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, StoragePool)

        self._last_refresh_time = 0
        self._volumes = None


    ##########################
    # Required class methods #
    ##########################

    def _conn_tick_poll_param(self):
        return "pollpool"
    def class_name(self):
        return "pool"

    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def _define(self, xml):
        return self.conn.define_pool(xml)
    def _using_events(self):
        return self.conn.using_storage_pool_events
    def _check_supports_isactive(self):
        return self.conn.check_support(
            self.conn.SUPPORT_POOL_ISACTIVE, self._backend)
    def _get_backend_status(self):
        return self._backend_get_active()

    def tick(self, stats_update=True):
        ignore = stats_update
        self._refresh_status()

    def _init_libvirt_state(self):
        self.tick()
        if not self.conn.is_active():
            # We only want to refresh a pool on initial conn startup,
            # since the pools may be out of date. But if a storage pool
            # shows up while the conn is connected, this means it was
            # just 'defined' recently and doesn't need to be refreshed.
            self.refresh(_from_object_init=True)
        for vol in self.get_volumes():
            vol.init_libvirt_state()

    def _invalidate_xml(self):
        vmmLibvirtObject._invalidate_xml(self)
        self._volumes = None


    ###########
    # Actions #
    ###########

    @vmmLibvirtObject.lifecycle_action
    def start(self):
        self._backend.create(0)

    @vmmLibvirtObject.lifecycle_action
    def stop(self):
        self._backend.destroy()

    @vmmLibvirtObject.lifecycle_action
    def delete(self, force=True):
        ignore = force
        self._backend.undefine()
        self._backend = None

    def refresh(self, _from_object_init=False):
        """
        :param _from_object_init: Only used for the refresh() call from
            _init_libvirt_state. Tells us to not refresh the XML, since
            we just updated it.
        """
        if not self.is_active():
            return

        self._backend.refresh(0)
        if self._using_events() and not _from_object_init:
            # If we are using events, we let the event loop trigger
            # the cache update for us. Except if from init_libvirt_state,
            # we want the update to be done immediately
            return

        self.refresh_pool_cache_from_event_loop(
            _from_object_init=_from_object_init)

    def refresh_pool_cache_from_event_loop(self, _from_object_init=False):
        if not _from_object_init:
            self.ensure_latest_xml()
        self._update_volumes(force=True)
        self.idle_emit("refreshed")
        self._last_refresh_time = time.time()

    def secs_since_last_refresh(self):
        return time.time() - self._last_refresh_time


    ###################
    # Volume handling #
    ###################

    def get_volumes(self):
        self._update_volumes(force=False)
        return self._volumes[:]

    def get_volume(self, key):
        for vol in self.get_volumes():
            if vol.get_connkey() == key:
                return vol
        return None

    def _update_volumes(self, force):
        if not self.is_active():
            self._volumes = []
            return
        if not force and self._volumes is not None:
            return

        keymap = dict((o.get_connkey(), o) for o in self._volumes or [])
        (ignore, ignore, allvols) = pollhelpers.fetch_volumes(
            self.conn.get_backend(), self.get_backend(), keymap,
            lambda obj, key: vmmStorageVolume(self.conn, obj, key))
        self._volumes = allvols


    #########################
    # XML/config operations #
    #########################

    def set_autostart(self, value):
        self._backend.setAutostart(value)
    def get_autostart(self):
        return self._backend.autostart()

    def can_change_alloc(self):
        typ = self.get_type()
        return (typ in [StoragePool.TYPE_LOGICAL, StoragePool.TYPE_ZFS])
    def supports_volume_creation(self):
        return self.get_xmlobj().supports_volume_creation()

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

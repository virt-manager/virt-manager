#
# Copyright (C) 2007 Red Hat, Inc.
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
import dbus
import logging

from virtManager.mediadev import vmmMediaDevice

class vmmOpticalDriveHelper(gobject.GObject):
    __gsignals__ = {
        "optical-added"  : (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                            [object]),
        "optical-media-added"  : (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                                  [object]),
        "device-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                           [str]),
    }

    def __init__(self):
        self.__gobject_init__()

        self.bus = None
        self.hal_iface = None

        # Mapping of HAL path -> vmmMediaDevice
        self.device_info = {}

        self._dbus_connect()
        self.populate_opt_media()

    def _dbus_connect(self):
        try:
            self.bus = dbus.SystemBus()
            hal_object = self.bus.get_object('org.freedesktop.Hal',
                                             '/org/freedesktop/Hal/Manager')
            self.hal_iface = dbus.Interface(hal_object,
                                            'org.freedesktop.Hal.Manager')
        except Exception, e:
            logging.error("Unable to connect to HAL to list cdrom "
                          "volumes: '%s'", e)
            raise

        # Track device add/removes so we can detect newly inserted CD media
        self.hal_iface.connect_to_signal("DeviceAdded", self._device_added)
        self.hal_iface.connect_to_signal("DeviceRemoved", self._device_removed)

    def connect(self, name, callback, *args):
        # Override connect, so when a new caller attaches to optical-added,
        # they get the full list of current devices
        handle_id = gobject.GObject.connect(self, name, callback, *args)

        if name == "optical-added":
            for dev in self.device_info.values():
                self.emit("optical-added", dev)

        return handle_id

    def populate_opt_media(self):
        volinfo = {}

        for path in self.hal_iface.FindDeviceByCapability("storage.cdrom"):
            # Make sure we only populate CDROM devs
            if not self.is_cdrom(path):
                continue

            devnode, media_label, media_hal_path = self._fetch_cdrom_info(path)
            obj = vmmMediaDevice(str(devnode), str(path), media_label,
                                 media_hal_path)

            self.device_info[str(devnode)] = obj

    def _device_added(self, path):
        media_label = None
        media_hal_path = None
        devpath = None
        signal = None

        if self.is_cdrom_media(path):
            media_hal_path = path
            media_label, devpath = self._fetch_media_info(path)
            signal = "optical-media-added"
        elif self.is_cdrom(path):
            devpath, media_label, media_hal_path = self._fetch_cdrom_info(path)
            signal = "optical-added"
        else:
            # Not a relevant device
            return

        obj = vmmMediaDevice(devpath, path, media_label, media_hal_path)
        self.device_info[devpath] = obj

        self.emit(signal, obj)

    def _device_removed(self, path):
        self.emit("device-removed", str(path))

    def dbus_dev_lookup(self, halpath):
        obj = self.bus.get_object("org.freedesktop.Hal", halpath)
        objif = dbus.Interface(obj, "org.freedesktop.Hal.Device")
        return objif

    def is_cdrom_media(self, halpath):
        obj = self.dbus_dev_lookup(halpath)
        return bool(obj.QueryCapability("volume") and
                    obj.GetPropertyBoolean("volume.is_disc") and
                    obj.GetPropertyBoolean("volume.disc.has_data"))

    def is_cdrom(self, halpath):
        obj = self.dbus_dev_lookup(halpath)
        return bool(obj.QueryCapability("storage.cdrom"))


    def _fetch_media_info(self, halpath):
        label = None
        devnode = None

        volif = self.dbus_dev_lookup(halpath)

        devnode = volif.GetProperty("block.device")
        label = volif.GetProperty("volume.label")
        if not label:
            label = devnode

        return (label and str(label), devnode and str(devnode))

    def _fetch_cdrom_info(self, halpath):
        devif = self.dbus_dev_lookup(halpath)

        devnode = devif.GetProperty("block.device")
        media_label = None
        media_hal_path = None

        if devnode:
            media_label, media_hal_path = self._find_media_for_devpath(devnode)

        return (devnode and str(devnode), media_label, media_hal_path)

    def _find_media_for_devpath(self, devpath):
        for path in self.hal_iface.FindDeviceByCapability("volume"):
            if not self.is_cdrom_media(path):
                continue

            label, devnode = self._fetch_media_info(path)

            if devnode == devpath:
                return (label, path)

        return None, None

gobject.type_register(vmmOpticalDriveHelper)

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
import gtk

from virtManager.mediadev import vmmMediaDevice

class vmmOpticalDriveHelper(gobject.GObject):
    __gsignals__ = {
        "optical-added"  : (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                            [object]),
        "optical-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
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

        # Find info about all current present media
        for path in self.hal_iface.FindDeviceByCapability("volume"):
            label, devnode = self._fetch_device_info(path)

            if not devnode:
                # Not an applicable device
                continue

            volinfo[devnode] = (label, path)

        for path in self.hal_iface.FindDeviceByCapability("storage.cdrom"):
            # Make sure we only populate CDROM devs
            dev = self.bus.get_object("org.freedesktop.Hal", path)
            devif = dbus.Interface(dev, "org.freedesktop.Hal.Device")
            devnode = devif.GetProperty("block.device")

            if volinfo.has_key(devnode):
                label, path = volinfo[devnode]
            else:
                label, path = None, None

            obj = vmmMediaDevice(str(devnode), str(path), label)

            self.device_info[str(devnode)] = obj

    def _device_added(self, path):
        label, devnode = self._fetch_device_info(path)

        if not devnode:
            # Not an applicable device
            return

        obj = vmmMediaDevice(str(devnode), str(path), str(label))
        self.device_info[str(devnode)] = obj

        logging.debug("Optical device added: %s" % obj.pretty_label())
        self.emit("optical-added", obj)

    def _device_removed(self, path):
        logging.debug("Optical device removed: %s" % str(path))
        self.emit("optical-removed", str(path))

    def _fetch_device_info(self, path):
        label = None
        devnode = None

        vol = self.bus.get_object("org.freedesktop.Hal", path)
        volif = dbus.Interface(vol, "org.freedesktop.Hal.Device")
        if volif.QueryCapability("volume"):

            if (volif.GetPropertyBoolean("volume.is_disc") and
                volif.GetPropertyBoolean("volume.disc.has_data")):

                devnode = volif.GetProperty("block.device")
                label = volif.GetProperty("volume.label")
                if label == None or len(label) == 0:
                    label = devnode

        return (label and str(label), devnode and str(devnode))

gobject.type_register(vmmOpticalDriveHelper)

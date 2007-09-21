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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import gobject
import dbus

class vmmOpticalDriveHelper(gobject.GObject):
    __gsignals__ = {}

    def __init__(self, widget):
        self.__gobject_init__()
        self.widget = widget
        self.model = self.widget.get_model()
        try:
            # Get a connection to the SYSTEM bus
            self.bus = dbus.SystemBus()
            # Get a handle to the HAL service
            hal_object = self.bus.get_object('org.freedesktop.Hal', '/org/freedesktop/Hal/Manager')
            self.hal_iface = dbus.Interface(hal_object, 'org.freedesktop.Hal.Manager')
            self.populate_opt_media()
        except Exception, e:
            logging.error("Unable to connect to HAL to list cdrom volumes: '%s'", e)
            self.bus = None
            self.hal_iface = None
            raise

    def populate_opt_media(self):
        # get a list of optical devices with data discs in, for FV installs
        vollabel = {}
        volpath = {}
        # Track device add/removes so we can detect newly inserted CD media
        self.hal_iface.connect_to_signal("DeviceAdded", self._device_added)
        self.hal_iface.connect_to_signal("DeviceRemoved", self._device_removed)

        # Find info about all current present media
        for d in self.hal_iface.FindDeviceByCapability("volume"):
            vol = self.bus.get_object("org.freedesktop.Hal", d)
            if vol.GetPropertyBoolean("volume.is_disc") and \
                   vol.GetPropertyBoolean("volume.disc.has_data"):
                devnode = vol.GetProperty("block.device")
                label = vol.GetProperty("volume.label")
                if label == None or len(label) == 0:
                    label = devnode
                vollabel[devnode] = label
                volpath[devnode] = d

        for d in self.hal_iface.FindDeviceByCapability("storage.cdrom"):
            dev = self.bus.get_object("org.freedesktop.Hal", d)
            devnode = dev.GetProperty("block.device")
            if vollabel.has_key(devnode):
                self.model.append([devnode, vollabel[devnode], True, volpath[devnode]])
            else:
                self.model.append([devnode, _("No media present"), False, None])

    def _device_added(self, path):
        vol = self.bus.get_object("org.freedesktop.Hal", path)
        if vol.QueryCapability("volume"):
            if vol.GetPropertyBoolean("volume.is_disc") and \
                   vol.GetPropertyBoolean("volume.disc.has_data"):
                devnode = vol.GetProperty("block.device")
                label = vol.GetProperty("volume.label")
                if label == None or len(label) == 0:
                    label = devnode

                # Search for the row with matching device node and
                # fill in info about inserted media
                for row in self.model:
                    if row[0] == devnode:
                        row[1] = label
                        row[2] = True
                        row[3] = path

    def _device_removed(self, path):
        vol = self.bus.get_object("org.freedesktop.Hal", path)

        active = self.widget.get_active()
        idx = 0
        # Search for the row containing matching HAL volume path
        # and update (clear) it, de-activating it if its currently
        # selected
        for row in self.model:
            if row[3] == path:
                row[1] = _("No media present")
                row[2] = False
                row[3] = None
                if idx == active:
                    self.widget.set_active(-1)
            idx = idx + 1
 

gobject.type_register(vmmOpticalDriveHelper)

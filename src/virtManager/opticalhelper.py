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

OPTICAL_PATH = 0
OPTICAL_LABEL = 1
OPTICAL_IS_MEDIA_PRESENT = 2
OPTICAL_HAL_PATH = 3
OPTICAL_MEDIADEV = 4

def init_optical_combo(widget, empty_sensitive=False):
    # [Device path, pretty label, has_media?, unique hal path, vmmMediaDevice]
    model = gtk.ListStore(str, str, bool, str, object)
    widget.set_model(model)
    model.clear()

    text = gtk.CellRendererText()
    widget.pack_start(text, True)
    widget.add_attribute(text, 'text', 1)
    if not empty_sensitive:
        widget.add_attribute(text, 'sensitive', 2)

    helper = vmmOpticalDriveHelper()
    helper.connect("optical-added", optical_added, widget)
    helper.connect("optical-removed", optical_removed, widget)

    widget.set_active(-1)
    optical_set_default_selection(widget)

def set_row_from_object(row):
    obj = row[OPTICAL_MEDIADEV]
    row[OPTICAL_PATH] = obj.get_path()
    row[OPTICAL_LABEL] = obj.pretty_label()
    row[OPTICAL_IS_MEDIA_PRESENT] = bool(obj.get_media_label())
    row[OPTICAL_HAL_PATH] = obj.get_key()

def optical_removed(ignore_helper, halpath, widget):
    model = widget.get_model()
    active = widget.get_active()
    idx = 0
    # Search for the row containing matching HAL volume path
    # and update (clear) it, de-activating it if its currently
    # selected
    for row in model:
        if row[OPTICAL_HAL_PATH] == halpath:
            row[OPTICAL_MEDIADEV].set_media_label(None)
            set_row_from_object(row)

            if idx == active:
                widget.set_active(-1)
        idx = idx + 1

    optical_set_default_selection(widget)

def optical_added(ignore_helper, newobj, widget):
    model = widget.get_model()
    active = widget.get_active()
    idx = 0
    found = False

    # Search for the row with matching device node and
    # fill in info about inserted media. If model has no current
    # selection, select the new media.
    for row in model:
        if row[OPTICAL_PATH] == newobj.get_path():
            found = True
            row[OPTICAL_MEDIADEV] = newobj
            set_row_from_object(row)

            if active == -1:
                widget.set_active(idx)

        idx = idx + 1

    if not found:
        # Brand new device
        row = [None, None, None, None, newobj]
        set_row_from_object(row)
        model.append(row)
        if active == -1:
            widget.set_active(len(model) - 1)

def optical_set_default_selection(widget):
    # Set the first active cdrom device as selected, otherwise none
    model = widget.get_model()
    idx = 0
    active = widget.get_active()

    if active != -1:
        # already a selection, don't change it
        return

    for row in model:
        if row[OPTICAL_IS_MEDIA_PRESENT] == True:
            widget.set_active(idx)
            return
        idx += 1

    widget.set_active(-1)

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

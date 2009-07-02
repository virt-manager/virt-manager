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

OPTICAL_PATH = 0
OPTICAL_LABEL = 1
OPTICAL_IS_MEDIA_PRESENT = 2
OPTICAL_HAL_PATH = 3

def init_optical_combo(widget, empty_sensitive=False):
    # These fields should match up with vmmOpticalHelper.device_info
    model = gtk.ListStore(str, str, bool, str)
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
    for row in helper.get_device_info():
        model.append(row)

    widget.set_active(-1)
    set_default_selection(widget)

def optical_removed(ignore_helper, halpath, widget):
    model = widget.get_model()
    active = widget.get_active()
    idx = 0
    # Search for the row containing matching HAL volume path
    # and update (clear) it, de-activating it if its currently
    # selected
    for row in model:
        if row[OPTICAL_HAL_PATH] == halpath:
            row[OPTICAL_LABEL] = display_label(row[OPTICAL_PATH], None)
            row[OPTICAL_IS_MEDIA_PRESENT] = False
            row[OPTICAL_HAL_PATH] = None
            if idx == active:
                widget.set_active(-1)
        idx = idx + 1

    set_default_selection(widget)

def optical_added(ignore_helper, newrow, widget):
    model = widget.get_model()
    active = widget.get_active()
    idx = 0

    # Search for the row with matching device node and
    # fill in info about inserted media. If model has no current
    # selection, select the new media.
    for row in model:
        if row[OPTICAL_PATH] == newrow[OPTICAL_PATH]:
            for i in range(0, len(row)):
                row[i] = newrow[i]
            if active == -1:
                widget.set_active(idx)
            idx = idx + 1

def set_default_selection(widget):
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

def display_label(devnode, media_label):
    if not media_label:
        media_label = _("No media present")
    return "%s (%s)" % (media_label, devnode)

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

        # List of lists, containing all relevant device info. Sublist is:
        # [ HAL device name,
        #   Pretty label to show,
        #   Is media present?,
        #   Filesystem path, e.g. /dev/sr0 ]
        self.device_info = []

        self._dbus_connect()
        self.populate_opt_media()

    def get_device_info(self):
        return self.device_info

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


    def populate_opt_media(self):
        volinfo = {}
        self.device_info = []

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
                present = True
            else:
                label, path = None, None
                present = False

            row = []
            row.insert(OPTICAL_PATH, str(devnode))
            row.insert(OPTICAL_LABEL, display_label(devnode, label))
            row.insert(OPTICAL_IS_MEDIA_PRESENT, present)
            row.insert(OPTICAL_HAL_PATH, str(path))

            self.device_info.append(row)

    def _device_added(self, path):
        label, devnode = self._fetch_device_info(path)

        if not devnode:
            # Not an applicable device
            return

        row = []
        row.insert(OPTICAL_PATH, str(devnode))
        row.insert(OPTICAL_LABEL, display_label(devnode, label))
        row.insert(OPTICAL_IS_MEDIA_PRESENT, True)
        row.insert(OPTICAL_HAL_PATH, str(path))

        logging.debug("Optical device added: %s" % row)
        self.emit("optical-added", row)

    def _device_removed(self, path):
        logging.debug("Optical device removed: %s" % path)
        self.emit("optical-removed", path)

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

        return (label, devnode)

gobject.type_register(vmmOpticalDriveHelper)

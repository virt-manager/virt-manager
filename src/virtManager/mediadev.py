#
# Copyright (C) 2009 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
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

import virtinst

from virtManager.baseclass import vmmGObject

MEDIA_FLOPPY = "floppy"
MEDIA_CDROM = "cdrom"

MEDIA_TIMEOUT = 3

class vmmMediaDevice(vmmGObject):
    @staticmethod
    def mediadev_from_nodedev(dev):
        nodedev = dev.get_virtinst_obj()

        if nodedev.device_type != "storage":
            return None

        if nodedev.drive_type not in [MEDIA_CDROM, MEDIA_FLOPPY]:
            return None

        drvtype = nodedev.drive_type
        path = nodedev.block
        key = nodedev.name
        has_media = nodedev.media_available
        media_label = nodedev.media_label
        media_key = None

        obj = vmmMediaDevice(path, key, has_media, media_label, media_key,
                             dev, drvtype)
        obj.do_poll = True

        return obj

    def __init__(self, path, key, has_media, media_label, media_key,
                 nodedev_obj=None, media_type=MEDIA_CDROM):
        vmmGObject.__init__(self)

        self.path = path
        self.key = key
        self._has_media = has_media
        self.media_label = media_label
        self.media_key = media_key
        self.media_type = media_type

        self.nodedev_obj = nodedev_obj
        self.do_poll = False
        self.last_tick = 0

    def _cleanup(self):
        pass

    def get_path(self):
        return self.path

    def get_key(self):
        return self.key

    def get_media_type(self):
        return self.media_type

    def has_media(self):
        return self._has_media
    def get_media_label(self):
        return self.media_label
    def get_media_key(self):
        return self.media_key

    def set_media(self, has_media, media_label, media_key):
        self._has_media = has_media
        self.media_label = media_label
        self.media_key = media_key
    def clear_media(self):
        self.set_media(None, None, None)

    def pretty_label(self):
        media_label = self.get_media_label()
        has_media = self.has_media()
        if not has_media:
            media_label = _("No media detected")
        elif not media_label:
            media_label = _("Media Unknown")

        return "%s (%s)" % (media_label, self.get_path())


    ############################
    # HAL media signal helpers #
    ############################

    def set_hal_media_signals(self, halhelper):
        halhelper.connect("optical-media-added", self.hal_media_added)
        halhelper.connect("device-removed", self.hal_media_removed)

    def hal_media_added(self, ignore, devpath, media_label, media_key):
        if devpath != self.get_path():
            return

        self.set_media(True, media_label, media_key)
        self.emit("media-added")

    def hal_media_removed(self, ignore, media_hal_path):
        if media_hal_path != self.get_media_key():
            return

        self.clear_media()
        self.emit("media-removed")


    #########################################
    # Nodedev API polling for media updates #
    #########################################

    def tick(self):
        if not self.nodedev_obj:
            return

        if not self.nodedev_obj.conn.is_active():
            return

        if (time.time() - self.last_tick) < MEDIA_TIMEOUT:
            return
        self.last_tick = time.time()

        try:
            self.nodedev_obj.refresh_xml()
            xml = self.nodedev_obj.get_xml()
        except:
            # Assume the device was removed
            return

        try:
            vobj = virtinst.NodeDeviceParser.parse(xml)
            has_media = vobj.media_available
        except:
            logging.exception("Node device CDROM polling failed")
            return

        if has_media == self.has_media():
            return

        self.set_media(has_media, None, None)
        self.idle_emit(has_media and "media-added" or "media-removed")


vmmGObject.type_register(vmmMediaDevice)
vmmMediaDevice.signal_new(vmmMediaDevice, "media-added", [])
vmmMediaDevice.signal_new(vmmMediaDevice, "media-removed", [])

#
# Copyright (C) 2009, 2013 Red Hat, Inc.
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

from gi.repository import GObject

import logging

from virtinst import NodeDevice

from virtManager.baseclass import vmmGObject

MEDIA_FLOPPY = "floppy"
MEDIA_CDROM = "cdrom"


class vmmMediaDevice(vmmGObject):
    __gsignals__ = {
        "media-added": (GObject.SignalFlags.RUN_FIRST, None, []),
        "media-removed": (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    @staticmethod
    def mediadev_from_nodedev(dev):
        nodedev = dev.get_xmlobj()

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


    #########################################
    # Nodedev API polling for media updates #
    #########################################

    def tick(self):
        if not self.nodedev_obj:
            return
        if not self.nodedev_obj.conn.is_active():
            return

        try:
            self.nodedev_obj.refresh_xml()
            xml = self.nodedev_obj.get_xml()
        except:
            # Assume the device was removed
            return

        try:
            vobj = NodeDevice.parse(self.nodedev_obj.conn.get_backend(), xml)
            has_media = vobj.media_available or False
        except:
            logging.exception("Node device CDROM polling failed")
            return

        if has_media == self.has_media():
            return

        self.set_media(has_media, None, None)
        self.idle_emit(has_media and "media-added" or "media-removed")

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

import gobject

class vmmMediaDevice(gobject.GObject):
    __gsignals__ = {
        "media-added"  : (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                          []),
        "media-removed"  : (gobject.SIGNAL_RUN_FIRST,
                            gobject.TYPE_NONE, []),
    }

    def __init__(self, path, key, media_label, media_key):
        self.__gobject_init__()

        self.path = path
        self.key = key
        self.media_label = media_label
        self.media_key = media_key

    def get_path(self):
        return self.path

    def get_key(self):
        return self.key

    def has_media(self):
        return self.has_media

    def get_media_label(self):
        return self.media_label
    def get_media_key(self):
        return self.media_key

    def set_media(self, media_label, media_key):
        self.media_label = media_label
        self.media_key = media_key
    def clear_media(self):
        self.set_media(None, None)

    def pretty_label(self):
        media_label = self.get_media_label()
        if not media_label:
            media_label = _("No media present")
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

        self.set_media(media_label, media_key)
        self.emit("media-added")

    def hal_media_removed(self, ignore, media_hal_path):
        if media_hal_path != self.get_media_key():
            return

        self.clear_media()
        self.emit("media-removed")


gobject.type_register(vmmMediaDevice)

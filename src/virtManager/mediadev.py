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
    __gsignals__ = {}

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
        self.media_label = None
        self.media_key = None

    def pretty_label(self):
        media_label = self.get_media_label()
        if not media_label:
            media_label = _("No media present")
        return "%s (%s)" % (media_label, self.get_path())

gobject.type_register(vmmMediaDevice)

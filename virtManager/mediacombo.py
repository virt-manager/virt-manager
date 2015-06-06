#
# Copyright (C) 2014 Red Hat, Inc.
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

from gi.repository import Gtk

from . import uiutil
from .baseclass import vmmGObjectUI


class vmmMediaCombo(vmmGObjectUI):
    MEDIA_FLOPPY = "floppy"
    MEDIA_CDROM = "cdrom"

    OPTICAL_FIELDS = 4
    (OPTICAL_DEV_PATH,
    OPTICAL_LABEL,
    OPTICAL_HAS_MEDIA,
    OPTICAL_DEV_KEY) = range(OPTICAL_FIELDS)

    def __init__(self, conn, builder, topwin, media_type):
        vmmGObjectUI.__init__(self, None, None, builder=builder, topwin=topwin)
        self.conn = conn
        self.media_type = media_type

        self.top_box = None
        self.combo = None
        self._warn_icon = None
        self._populated = False
        self._init_ui()

    def _cleanup(self):
        self.conn = None
        self.top_box.destroy()
        self.top_box = None


    ##########################
    # Initialization methods #
    ##########################

    def _init_ui(self):
        self.top_box = Gtk.Box()
        self.top_box.set_spacing(6)
        self.top_box.set_orientation(Gtk.Orientation.HORIZONTAL)
        self._warn_icon = Gtk.Image()
        self._warn_icon.set_from_stock(
            Gtk.STOCK_DIALOG_WARNING, Gtk.IconSize.MENU)
        self.combo = Gtk.ComboBox()
        self.top_box.add(self.combo)
        self.top_box.add(self._warn_icon)
        self.top_box.show_all()

        # [Device path, pretty label, has_media?, device key]
        fields = []
        fields.insert(self.OPTICAL_DEV_PATH, str)
        fields.insert(self.OPTICAL_LABEL, str)
        fields.insert(self.OPTICAL_HAS_MEDIA, bool)
        fields.insert(self.OPTICAL_DEV_KEY, str)
        self.combo.set_model(Gtk.ListStore(*fields))

        text = Gtk.CellRendererText()
        self.combo.pack_start(text, True)
        self.combo.add_attribute(text, 'text', self.OPTICAL_LABEL)

        error = None
        if not self.conn.is_nodedev_capable():
            error = _("Libvirt version does not support media listing.")
        self._warn_icon.set_tooltip_text(error)
        self._warn_icon.set_visible(bool(error))


    def _set_mediadev_default(self):
        model = self.combo.get_model()
        if len(model) != 0:
            return

        row = [None] * self.OPTICAL_FIELDS
        row[self.OPTICAL_DEV_PATH] = None
        row[self.OPTICAL_LABEL] = _("No device present")
        row[self.OPTICAL_HAS_MEDIA] = False
        row[self.OPTICAL_DEV_KEY] = None
        model.append(row)

    def _pretty_label(self, nodedev):
        media_label = nodedev.xmlobj.media_label
        if not nodedev.xmlobj.media_available:
            media_label = _("No media detected")
        elif not nodedev.xmlobj.media_label:
            media_label = _("Media Unknown")

        return "%s (%s)" % (media_label, nodedev.xmlobj.block)

    def _mediadev_set_default_selection(self):
        # Set the first active cdrom device as selected, otherwise none
        widget = self.combo
        model = widget.get_model()
        idx = 0
        active = widget.get_active()

        if active != -1:
            # already a selection, don't change it
            return

        for row in model:
            if row[self.OPTICAL_HAS_MEDIA] is True:
                widget.set_active(idx)
                return
            idx += 1

        widget.set_active(0)

    def _populate_media(self):
        if self._populated:
            return

        widget = self.combo
        model = widget.get_model()
        model.clear()

        for nodedev in self.conn.filter_nodedevs(devtype="storage"):
            if not (nodedev.xmlobj.device_type == "storage" and
                    nodedev.xmlobj.drive_type in ["cdrom", "floppy"]):
                continue
            if nodedev.xmlobj.drive_type != self.media_type:
                continue

            row = [None] * self.OPTICAL_FIELDS
            row[self.OPTICAL_DEV_PATH] = nodedev.xmlobj.block
            row[self.OPTICAL_LABEL] = self._pretty_label(nodedev)
            row[self.OPTICAL_HAS_MEDIA] = nodedev.xmlobj.media_available
            row[self.OPTICAL_DEV_KEY] = nodedev.xmlobj.name
            model.append(row)

        self._set_mediadev_default()

        widget.set_active(-1)
        self._mediadev_set_default_selection()
        self._populated = True


    ##############
    # Public API #
    ##############

    def reset_state(self):
        try:
            self._populate_media()
        except:
            logging.debug("Error populating mediadev combo", exc_info=True)

    def get_path(self):
        return uiutil.get_list_selection(
            self.combo, column=self.OPTICAL_DEV_PATH)

    def has_media(self):
        return uiutil.get_list_selection(
            self.combo, column=self.OPTICAL_HAS_MEDIA) or False

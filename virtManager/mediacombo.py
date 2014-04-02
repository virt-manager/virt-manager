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

from gi.repository import Gtk

from virtManager import uiutil
from virtManager.baseclass import vmmGObjectUI


class vmmMediaCombo(vmmGObjectUI):
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
        try:
            self.conn.disconnect_by_func(self._mediadev_added)
            self.conn.disconnect_by_func(self._mediadev_removed)
        except:
            pass

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

        # [Device path, pretty label, has_media?, device key, media key,
        #  vmmMediaDevice, is valid device]
        fields = []
        fields.insert(self.OPTICAL_DEV_PATH, str)
        fields.insert(self.OPTICAL_LABEL, str)
        fields.insert(self.OPTICAL_HAS_MEDIA, bool)
        fields.insert(self.OPTICAL_DEV_KEY, str)
        self.combo.set_model(Gtk.ListStore(*fields))

        text = Gtk.CellRendererText()
        self.combo.pack_start(text, True)
        self.combo.add_attribute(text, 'text', self.OPTICAL_LABEL)

        error = self.conn.mediadev_error
        self._warn_icon.set_visible(bool(error))
        self._warn_icon.set_tooltip_text(error)


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

    def _set_mediadev_row_from_object(self, row, obj):
        row[self.OPTICAL_DEV_PATH] = obj.get_path()
        row[self.OPTICAL_LABEL] = obj.pretty_label()
        row[self.OPTICAL_HAS_MEDIA] = obj.has_media()
        row[self.OPTICAL_DEV_KEY] = obj.get_key()

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

    def _mediadev_media_changed(self, newobj):
        widget = self.combo
        model = widget.get_model()
        active = widget.get_active()
        idx = 0

        # Search for the row with matching device node and
        # fill in info about inserted media. If model has no current
        # selection, select the new media.
        for row in model:
            if row[self.OPTICAL_DEV_PATH] == newobj.get_path():
                self._set_mediadev_row_from_object(row, newobj)
                has_media = row[self.OPTICAL_HAS_MEDIA]

                if has_media and active == -1:
                    widget.set_active(idx)
                elif not has_media and active == idx:
                    widget.set_active(-1)

            idx = idx + 1

        self._mediadev_set_default_selection()

    def _mediadev_added(self, ignore, newobj):
        widget = self.combo
        model = widget.get_model()

        if newobj.get_media_type() != self.media_type:
            return
        if model is None:
            return

        if len(model) == 1 and model[0][self.OPTICAL_DEV_PATH] is None:
            # Only entry is the 'No device' entry
            model.clear()

        newobj.connect("media-added", self._mediadev_media_changed)
        newobj.connect("media-removed", self._mediadev_media_changed)

        # Brand new device
        row = [None] * self.OPTICAL_FIELDS
        self._set_mediadev_row_from_object(row, newobj)
        model.append(row)

        self._mediadev_set_default_selection()

    def _mediadev_removed(self, ignore, key):
        widget = self.combo
        model = widget.get_model()
        active = widget.get_active()
        idx = 0

        for row in model:
            if row[self.OPTICAL_DEV_KEY] == key:
                # Whole device removed
                del(model[idx])

                if idx > active and active != -1:
                    widget.set_active(active - 1)
                elif idx == active:
                    widget.set_active(-1)

            idx += 1

        self._set_mediadev_default()
        self._mediadev_set_default_selection()

    def _populate_media(self):
        if self._populated:
            return

        widget = self.combo
        model = widget.get_model()
        model.clear()
        self._set_mediadev_default()

        self.conn.connect("mediadev-added", self._mediadev_added)
        self.conn.connect("mediadev-removed", self._mediadev_removed)

        widget.set_active(-1)
        self._mediadev_set_default_selection()
        self._populated = True


    ##############
    # Public API #
    ##############

    def reset_state(self):
        self._populate_media()

    def get_path(self):
        return uiutil.get_list_selection(self.combo, self.OPTICAL_DEV_PATH)

    def has_media(self):
        return uiutil.get_list_selection(self.combo, self.OPTICAL_HAS_MEDIA)

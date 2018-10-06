# Copyright (C) 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gtk

from . import uiutil
from .baseclass import vmmGObject, vmmGObjectUI


class vmmMediaCombo(vmmGObjectUI):
    __gsignals__ = {
        "changed": (vmmGObject.RUN_FIRST, None, [object]),
        "activate": (vmmGObject.RUN_FIRST, None, [object]),
    }

    MEDIA_TYPE_FLOPPY = "floppy"
    MEDIA_TYPE_CDROM = "cdrom"

    MEDIA_FIELDS_NUM = 4
    (MEDIA_FIELD_PATH,
    MEDIA_FIELD_LABEL,
    MEDIA_FIELD_HAS_MEDIA,
    MEDIA_FIELD_KEY) = range(MEDIA_FIELDS_NUM)

    def __init__(self, conn, builder, topwin):
        vmmGObjectUI.__init__(self, None, None, builder=builder, topwin=topwin)
        self.conn = conn

        self.top_box = None
        self._combo = None
        self._populated = False
        self._init_ui()

        self._iso_rows = []
        self._cdrom_rows = []
        self._floppy_rows = []
        self._rows_inited = False

        self.add_gsettings_handle(
                self.config.on_iso_paths_changed(self._iso_paths_changed_cb))


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
        self._combo = Gtk.ComboBox(has_entry=True)
        self._combo.set_entry_text_column(self.MEDIA_FIELD_LABEL)
        self._combo.get_accessible().set_name("media-combo")
        def separator_cb(_model, _iter):
            return _model[_iter][self.MEDIA_FIELD_PATH] is None
        self._combo.set_row_separator_func(separator_cb)

        self._entry = self._combo.get_child()
        self._entry.set_placeholder_text(_("No media selected"))
        self._entry.set_hexpand(True)
        self._entry.get_accessible().set_name("media-entry")
        self._entry.connect("changed", self._on_entry_changed_cb)
        self._entry.connect("activate", self._on_entry_activated_cb)
        self._entry.connect("icon-press", self._on_entry_icon_press_cb)

        self._browse = Gtk.Button()

        self.top_box.add(self._combo)
        self.top_box.show_all()

        # [path, label, has_media?, device key]
        store = Gtk.ListStore(str, str, bool, str)
        self._combo.set_model(store)

    def _make_row(self, path, label, has_media, key):
        row = [None] * self.MEDIA_FIELDS_NUM
        row[self.MEDIA_FIELD_PATH] = path
        row[self.MEDIA_FIELD_LABEL] = label
        row[self.MEDIA_FIELD_HAS_MEDIA] = has_media
        row[self.MEDIA_FIELD_KEY] = key
        return row

    def _make_nodedev_rows(self, media_type):
        rows = []
        for nodedev in self.conn.filter_nodedevs(devtype="storage"):
            if not (nodedev.xmlobj.device_type == "storage" and
                    nodedev.xmlobj.drive_type in ["cdrom", "floppy"]):
                continue
            if nodedev.xmlobj.drive_type != media_type:
                continue

            media_label = nodedev.xmlobj.media_label
            if not nodedev.xmlobj.media_available:
                media_label = _("No media detected")
            elif not nodedev.xmlobj.media_label:
                media_label = _("Media Unknown")
            label = "%s (%s)" % (media_label, nodedev.xmlobj.block)

            row = self._make_row(nodedev.xmlobj.block, label,
                    nodedev.xmlobj.media_available,
                    nodedev.xmlobj.name)
            rows.append(row)
        return rows

    def _make_iso_rows(self):
        rows = []
        for path in self.config.get_iso_paths():
            row = self._make_row(path, path, True, path)
            rows.append(row)
        return rows

    def _init_rows(self):
        self._cdrom_rows = self._make_nodedev_rows("cdrom")
        self._floppy_rows = self._make_nodedev_rows("floppy")
        self._iso_rows = self._make_iso_rows()
        self._rows_inited = True


    ################
    # UI callbacks #
    ################

    def _on_entry_changed_cb(self, src):
        self.emit("changed", self._entry)

    def _on_entry_activated_cb(self, src):
        self.emit("activate", self._entry)

    def _on_entry_icon_press_cb(self, src, icon_pos, event):
        self._entry.set_text("")

    def _iso_paths_changed_cb(self):
        self._iso_rows = self._make_iso_rows()


    ##############
    # Public API #
    ##############

    def set_conn(self, conn):
        if conn == self.conn:
            return
        self.conn = conn
        self._init_rows()

    def reset_state(self, is_floppy=False):
        if not self._rows_inited:
            self._init_rows()

        model = self._combo.get_model()
        model.clear()

        for row in self._iso_rows:
            model.append(row)

        nodedev_rows = self._cdrom_rows
        if is_floppy:
            nodedev_rows = self._floppy_rows

        if len(model) and nodedev_rows:
            model.append(self._make_row(None, None, False, None))
        for row in nodedev_rows:
            model.append(row)

        self._combo.set_active(-1)

    def get_path(self, store_media=True):
        ret = uiutil.get_list_selection(
            self._combo, column=self.MEDIA_FIELD_PATH)
        if store_media and not ret.startswith("/dev"):
            self.config.add_iso_path(ret)
        return ret

    def set_path(self, path):
        uiutil.set_list_selection(
            self._combo, path, column=self.MEDIA_FIELD_PATH)
        self._entry.set_position(-1)

    def set_mnemonic_label(self, label):
        label.set_mnemonic_widget(self._entry)

    def show_clear_icon(self):
        pos = Gtk.EntryIconPosition.SECONDARY
        self._entry.set_icon_from_icon_name(pos, "edit-clear-symbolic")
        self._entry.set_icon_activatable(pos, True)

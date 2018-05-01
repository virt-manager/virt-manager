# Copyright (C) 2018 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gtk

import virtinst

from .baseclass import vmmGObjectUI


class vmmOSList(vmmGObjectUI):
    __gsignals__ = {
        "os-selected": (vmmGObjectUI.RUN_FIRST, None, [object])
    }

    def __init__(self):
        vmmGObjectUI.__init__(self, "oslist.ui", "vmm-oslist")
        self._cleanup_on_app_close()

        self._filter_name = None
        self._filter_eol = True

        self.builder.connect_signals({
            "on_include_eol_toggled": self._eol_toggled,
        })

        self._init_state()

    def _init_state(self):

        self.topwin.set_modal(False)
        os_list = self.widget("os-list")

        # (os object, label)
        os_list_model = Gtk.ListStore(object, str)

        all_os = virtinst.OSDB.list_os()

        for os in all_os:
            os_list_model.append([os, "%s (%s)" % (os.label, os.name)])

        self._os_list_model = Gtk.TreeModelFilter(child_model=os_list_model)
        self._os_list_model.set_visible_func(self._filter_os)

        os_list.set_model(self._os_list_model)

        nameCol = Gtk.TreeViewColumn(_("Name"))
        nameCol.set_spacing(6)

        text = Gtk.CellRendererText()
        nameCol.pack_start(text, True)
        nameCol.add_attribute(text, 'text', 1)
        os_list.append_column(nameCol)

        os_list.connect("row_activated", self._os_selected_cb)

    def _eol_toggled(self, src):
        self._filter_eol = not src.get_active()
        self._refilter()

    def _os_selected_cb(self, tree_view, path, column):
        model, titer = tree_view.get_selection().get_selected()
        if titer is None:
            self.emit("os-selected", None)
        else:
            self.emit("os-selected", model[titer][0])

    def _filter_os(self, model, titer, ignore1):
        os = model.get(titer, 0)[0]
        if self._filter_eol:
            if os.eol:
                return False

        if self._filter_name is not None and self._filter_name != "":
            label = os.label.lower()
            name = os.name.lower()
            if (label.find(self._filter_name) == -1 and
                name.find(self._filter_name) == -1):
                return False

        return True

    def _refilter(self):
        os_list = self.widget("os-list")
        sel = os_list.get_selection()
        sel.unselect_all()
        self._os_list_model.refilter()

    def filter_name(self, partial_name):
        self._filter_name = partial_name.lower()
        self._refilter()

    def show(self, parent):
        self.topwin.set_relative_to(parent)
        self.topwin.popup()

    def hide(self):
        self.topwin.popdown()

    def _cleanup(self):
        pass

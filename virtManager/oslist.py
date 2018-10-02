# Copyright (C) 2018 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gdk, Gtk

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
        self._selected_os = None
        self.search_entry = self.widget("os-name")
        self.search_entry.set_placeholder_text(_("Type to start searching..."))
        self.eol_text = self.widget("eol-warn").get_text()

        self.builder.connect_signals({
            "on_include_eol_toggled": self._eol_toggled_cb,

            "on_os_name_activate": self._entry_activate_cb,
            "on_os_name_key_press_event": self._key_press_cb,
            "on_os_name_search_changed": self._search_changed_cb,
            "on_os_name_stop_search": self._stop_search_cb,
            "on_os_list_row_activated": self._os_selected_cb,
        })

        self._init_state()

    def _cleanup(self):
        pass


    ###########
    # UI init #
    ###########

    def _init_state(self):
        os_list = self.widget("os-list")

        # (os object, label)
        os_list_model = Gtk.ListStore(object, str)

        all_os = virtinst.OSDB.list_os()

        for os in all_os:
            os_list_model.append([os, "%s (%s)" % (os.label, os.name)])

        model_filter = Gtk.TreeModelFilter(child_model=os_list_model)
        model_filter.set_visible_func(self._filter_os_cb)

        os_list.set_model(model_filter)

        nameCol = Gtk.TreeViewColumn(_("Name"))
        nameCol.set_spacing(6)

        text = Gtk.CellRendererText()
        nameCol.pack_start(text, True)
        nameCol.add_attribute(text, 'text', 1)
        os_list.append_column(nameCol)


    ###################
    # Private helpers #
    ###################

    def _set_default_selection(self):
        os_list = self.widget("os-list")
        sel = os_list.get_selection()
        if not self.topwin.get_visible():
            return
        if not len(os_list.get_model()):
            return
        sel.select_iter(os_list.get_model()[0].iter)

    def _refilter(self):
        os_list = self.widget("os-list")
        sel = os_list.get_selection()
        sel.unselect_all()
        os_list.get_model().refilter()
        self._set_default_selection()

    def _filter_by_name(self, partial_name):
        self._filter_name = partial_name.lower()
        self._refilter()

    def _clear_filter(self):
        self._filter_by_name("")
        self.widget("os-scroll").get_vadjustment().set_value(0)

    def _sync_os_selection(self):
        model, titer = self.widget("os-list").get_selection().get_selected()
        self._selected_os = None
        if titer:
            self._selected_os = model[titer][0]
            self.search_entry.set_text(self._selected_os.label)

        self.emit("os-selected", self._selected_os)

    def _show_popover(self):
        # Match width to the search_entry width. Height is based on
        # whatever we can fit into the hardcoded create wizard sizes
        r = self.search_entry.get_allocation()
        self.topwin.set_size_request(r.width, 350)

        self.topwin.set_relative_to(self.search_entry)
        self.topwin.popup()
        self._set_default_selection()


    ################
    # UI Callbacks #
    ################

    def _entry_activate_cb(self, src):
        os_list = self.widget("os-list")
        sel = os_list.get_selection()
        model, rows = sel.get_selected_rows()
        if rows:
            self.select_os(model[rows[0]][0])

    def _key_press_cb(self, src, event):
        if Gdk.keyval_name(event.keyval) != "Down":
            return
        self._show_popover()
        self.widget("os-list").grab_focus()

    def _eol_toggled_cb(self, src):
        self._filter_eol = not src.get_active()
        self._refilter()

    def _search_changed_cb(self, src):
        """
        Called text in search_entry is changed
        """
        searchname = src.get_text().strip()
        selected_label = None
        if self._selected_os:
            selected_label = self._selected_os.label

        if (not src.get_sensitive() or
            not searchname or
            selected_label == searchname):
            self.topwin.popdown()
            self._clear_filter()
            return

        self._filter_by_name(searchname)
        self._show_popover()

    def _stop_search_cb(self, src):
        """
        Called when the search window is closed, like with Escape key
        """
        if self._selected_os:
            self.search_entry.set_text(self._selected_os.label)
        else:
            self.search_entry.set_text("")

    def _os_selected_cb(self, src,  path, column):
        self._sync_os_selection()

    def _filter_os_cb(self, model, titer, ignore1):
        osobj = model.get(titer, 0)[0]
        if osobj.is_generic():
            return True

        if self._filter_eol:
            if osobj.eol:
                return False

        if self._filter_name is not None and self._filter_name != "":
            label = osobj.label.lower()
            name = osobj.name.lower()
            if (label.find(self._filter_name) == -1 and
                name.find(self._filter_name) == -1):
                return False

        return True


    ###############
    # Public APIs #
    ###############

    def reset_state(self):
        self._selected_os = None
        self.search_entry.set_text("")
        self._clear_filter()
        self._sync_os_selection()

    def select_os(self, vmosobj):
        self._clear_filter()

        os_list = self.widget("os-list")
        if vmosobj.eol and not self.widget("include-eol").get_active():
            self.widget("include-eol").set_active(True)

        for row in os_list.get_model():
            osobj = row[0]
            if osobj.name != vmosobj.name:
                continue

            os_list.get_selection().select_iter(row.iter)
            self._sync_os_selection()
            return

    def get_selected_os(self):
        return self._selected_os

    def set_sensitive(self, sensitive):
        if sensitive == self.search_entry.get_sensitive():
            return

        if not sensitive:
            self.search_entry.set_sensitive(False)
            self.reset_state()
        else:
            if self._selected_os:
                self.select_os(self._selected_os)
            else:
                self.reset_state()
            self.search_entry.set_sensitive(True)

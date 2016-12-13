#
# Copyright (C) 2008, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2008 Cole Robinson <crobinso@redhat.com>
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

from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk

from virtinst import StorageVolume

from . import uiutil
from .baseclass import vmmGObjectUI
from .asyncjob import vmmAsyncJob


class vmmCreateVolume(vmmGObjectUI):
    __gsignals__ = {
        "vol-created": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
    }

    def __init__(self, conn, parent_pool):
        vmmGObjectUI.__init__(self, "createvol.ui", "vmm-create-vol")
        self.conn = conn
        self.parent_pool = parent_pool

        self.name_hint = None
        self.vol = None
        self.storage_browser = None

        self.builder.connect_signals({
            "on_vmm_create_vol_delete_event" : self.close,
            "on_vol_cancel_clicked"  : self.close,
            "on_vol_create_clicked"  : self.finish,

            "on_vol_name_changed"    : self.vol_name_changed,
            "on_vol_format_changed"  : self.vol_format_changed,
            "on_backing_store_changed" : self._show_alloc,
            "on_vol_allocation_value_changed" : self.vol_allocation_changed,
            "on_vol_capacity_value_changed"   : self.vol_capacity_changed,
            "on_backing_browse_clicked" : self.browse_backing,
        })
        self.bind_escape_key_close()

        self._init_state()
        self.reset_state()


    def show(self, parent):
        try:
            parent_xml = self.parent_pool.xmlobj.get_xml_config()
        except:
            logging.debug("Error getting parent_pool xml", exc_info=True)
            parent_xml = None

        logging.debug("Showing new volume wizard for parent_pool=\n%s",
            parent_xml)
        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing new volume wizard")
        self.topwin.hide()
        if self.storage_browser:
            self.storage_browser.close()
        self.set_modal(False)
        return 1

    def _cleanup(self):
        self.conn = None
        self.parent_pool = None

        if self.storage_browser:
            self.storage_browser.cleanup()
            self.storage_browser = None

    def set_name_hint(self, hint):
        self.name_hint = hint

    def set_modal(self, modal):
        self.topwin.set_modal(bool(modal))

    def set_parent_pool(self, conn, pool):
        self.conn = conn
        self.parent_pool = pool


    def default_vol_name(self):
        if not self.name_hint:
            return ""

        suffix = self.default_suffix()
        ret = ""
        try:
            ret = StorageVolume.find_free_name(
                self.parent_pool.get_backend(), self.name_hint, suffix=suffix)
        except:
            logging.exception("Error finding a default vol name")

        return ret

    def default_suffix(self):
        if self.vol.file_type != self.vol.TYPE_FILE:
            return ""
        return StorageVolume.get_file_extension_for_format(
            self.get_config_format())

    def _init_state(self):
        blue = Gdk.color_parse("#0072A8")
        self.widget("header").modify_bg(Gtk.StateType.NORMAL, blue)

        format_list = self.widget("vol-format")
        format_model = Gtk.ListStore(str, str)
        format_list.set_model(format_model)
        uiutil.init_combo_text_column(format_list, 1)


    def _make_stub_vol(self):
        self.vol = StorageVolume(self.conn.get_backend())
        self.vol.pool = self.parent_pool.get_backend()

    def _can_only_sparse(self):
        if self.get_config_format() == "qcow2":
            return True
        if (self.widget("backing-store").is_visible() and
            self.widget("backing-store").get_text()):
            return True
        return False
    def _can_alloc(self):
        if self._can_only_sparse():
            return False
        if self.parent_pool.get_type() == "logical":
            # Sparse LVM volumes don't auto grow, so alloc=0 is useless
            return False
        return True
    def _show_alloc(self, *args, **kwargs):
        ignore = args
        ignore = kwargs
        uiutil.set_grid_row_visible(
            self.widget("vol-allocation"), self._can_alloc())

    def _can_backing(self):
        if self.parent_pool.get_type() == "logical":
            return True
        if self.get_config_format() == "qcow2":
            return True
        return False
    def _show_backing(self):
        uiutil.set_grid_row_visible(
            self.widget("backing-expander"), self._can_backing())

    def reset_state(self):
        self._make_stub_vol()

        self.widget("vol-name").set_text(self.default_vol_name() or "")
        self.widget("vol-name").grab_focus()
        self.vol_name_changed(self.widget("vol-name"))

        self.populate_vol_format()
        hasformat = bool(len(self.vol.list_formats()))
        uiutil.set_grid_row_visible(self.widget("vol-format"), hasformat)
        if hasformat:
            # Select the default storage format
            self.widget("vol-format").set_active(0)
            default = self.conn.get_default_storage_format()
            for row in self.widget("vol-format").get_model():
                if row[0] == default:
                    self.widget("vol-format").set_active_iter(row.iter)
                    break

        default_alloc = 0
        default_cap = 20

        self.widget("backing-store").set_text("")
        alloc = default_alloc
        if not self._can_alloc():
            alloc = default_cap
        self._show_alloc()
        self._show_backing()
        self.widget("backing-expander").set_expanded(False)

        self.widget("vol-allocation").set_range(0,
            int(self.parent_pool.get_available() / 1024 / 1024 / 1024))
        self.widget("vol-allocation").set_value(alloc)
        self.widget("vol-capacity").set_range(0.1, 1000000)
        self.widget("vol-capacity").set_value(default_cap)

        self.widget("vol-parent-name").set_markup(
                        "<b>" + self.parent_pool.get_name() + "'s</b>")
        self.widget("vol-parent-space").set_text(
                        self.parent_pool.get_pretty_available())


    def get_config_format(self):
        return uiutil.get_list_selection(self.widget("vol-format"))

    def populate_vol_format(self):
        stable_whitelist = ["raw", "qcow2", "qed"]
        model = self.widget("vol-format").get_model()
        model.clear()

        formats = self.vol.list_formats()
        if self.vol.list_create_formats() is not None:
            formats = self.vol.list_create_formats()

        if (self.vol.file_type == self.vol.TYPE_FILE and
            self.conn.stable_defaults()):
            newfmts = []
            for f in stable_whitelist:
                if f in formats:
                    newfmts.append(f)
            formats = newfmts

        for f in formats:
            model.append([f, f])

    def vol_name_changed(self, src):
        text = src.get_text()

        suffix = self.default_suffix()
        if "." in text:
            suffix = ""
        self.widget("vol-name-suffix").set_text(suffix)
        self.widget("vol-create").set_sensitive(bool(text))

    def vol_allocation_changed(self, src):
        cap_widget = self.widget("vol-capacity")

        alloc = src.get_value()
        cap   = cap_widget.get_value()

        if alloc > cap:
            cap_widget.set_value(alloc)

    def vol_capacity_changed(self, src):
        alloc_widget = self.widget("vol-allocation")

        cap   = src.get_value()
        alloc = self.widget("vol-allocation").get_value()

        if cap < alloc:
            alloc_widget.set_value(cap)

    def vol_format_changed(self, src):
        ignore = src
        self._show_alloc()
        self._show_backing()
        self.widget("vol-name").emit("changed")

    def browse_backing(self, src):
        ignore = src
        self._browse_file()

    def _signal_vol_created(self, pool, volname):
        self.emit("vol-created", pool.get_connkey(), volname)

    def _finish_cb(self, error, details):
        self.topwin.set_sensitive(True)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.TOP_LEFT_ARROW))

        if error:
            error = _("Error creating vol: %s") % error
            self.show_err(error,
                          details=details)
        else:
            self.parent_pool.connect("refreshed", self._signal_vol_created,
                self.vol.name)
            self.idle_add(self.parent_pool.refresh)
            self.close()

    def finish(self, src_ignore):
        try:
            if not self.validate():
                return
        except Exception, e:
            self.show_err(_("Uncaught error validating input: %s") % str(e))
            return

        self.topwin.set_sensitive(False)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.WATCH))

        progWin = vmmAsyncJob(self._async_vol_create, [],
                              self._finish_cb, [],
                              _("Creating storage volume..."),
                              _("Creating the storage volume may take a "
                                "while..."),
                              self.topwin)
        progWin.run()

    def _async_vol_create(self, asyncjob):
        conn = self.conn.get_backend()

        # Lookup different pool obj
        newpool = conn.storagePoolLookupByName(self.parent_pool.get_name())
        self.vol.pool = newpool

        meter = asyncjob.get_meter()
        logging.debug("Starting backround vol creation.")
        self.vol.install(meter=meter)
        logging.debug("vol creation complete.")

    def validate(self):
        name = self.widget("vol-name").get_text()
        suffix = self.widget("vol-name-suffix").get_text()
        volname = name + suffix
        fmt = self.get_config_format()
        alloc = self.widget("vol-allocation").get_value()
        cap = self.widget("vol-capacity").get_value()
        backing = self.widget("backing-store").get_text()
        if not self.widget("vol-allocation").get_visible():
            alloc = cap
            if self._can_only_sparse():
                alloc = 0

        try:
            self._make_stub_vol()
            self.vol.name = volname
            self.vol.capacity = (cap * 1024 * 1024 * 1024)
            self.vol.allocation = (alloc * 1024 * 1024 * 1024)
            if backing:
                self.vol.backing_store = backing
            if fmt:
                self.vol.format = fmt
            self.vol.validate()
        except ValueError, e:
            return self.val_err(_("Volume Parameter Error"), e)
        return True

    def show_err(self, info, details=None):
        self.err.show_err(info, details, modal=self.topwin.get_modal())

    def val_err(self, info, details):
        return self.err.val_err(info, details, modal=self.topwin.get_modal())

    def _browse_file(self):
        if self.storage_browser and self.storage_browser.conn != self.conn:
            self.storage_browser.cleanup()
            self.storage_browser = None

        if self.storage_browser is None:
            def cb(src, text):
                ignore = src
                self.widget("backing-store").set_text(text)

            from .storagebrowse import vmmStorageBrowser
            self.storage_browser = vmmStorageBrowser(self.conn)
            self.storage_browser.set_finish_cb(cb)
            self.storage_browser.topwin.set_modal(self.topwin.get_modal())
            self.storage_browser.set_browse_reason(
                self.config.CONFIG_DIR_IMAGE)

        self.storage_browser.show(self.topwin)

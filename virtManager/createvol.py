#
# Copyright (C) 2008, 2013 Red Hat, Inc.
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

# pylint: disable=E0611
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk
# pylint: enable=E0611

from virtManager.baseclass import vmmGObjectUI
from virtManager.asyncjob import vmmAsyncJob

from virtinst import StorageVolume

DEFAULT_ALLOC = 0
DEFAULT_CAP   = 8192


class vmmCreateVolume(vmmGObjectUI):
    __gsignals__ = {
        "vol-created": (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    def __init__(self, conn, parent_pool):
        vmmGObjectUI.__init__(self, "vmm-create-vol.ui", "vmm-create-vol")
        self.conn = conn
        self.parent_pool = parent_pool

        self.name_hint = None
        self.vol = None

        self.builder.connect_signals({
            "on_vmm_create_vol_delete_event" : self.close,
            "on_vol_cancel_clicked"  : self.close,
            "on_vol_create_clicked"  : self.finish,
            "on_vol_name_changed"    : self.vol_name_changed,
            "on_vol_allocation_value_changed" : self.vol_allocation_changed,
            "on_vol_capacity_value_changed"   : self.vol_capacity_changed,
        })
        self.bind_escape_key_close()

        format_list = self.widget("vol-format")
        format_model = Gtk.ListStore(str, str)
        format_list.set_model(format_model)
        text2 = Gtk.CellRendererText()
        format_list.pack_start(text2, False)
        format_list.add_attribute(text2, 'text', 1)

        self.widget("vol-info-view").modify_bg(Gtk.StateType.NORMAL,
                                               Gdk.Color.parse("grey")[1])

        finish_img = Gtk.Image.new_from_stock(Gtk.STOCK_QUIT,
                                              Gtk.IconSize.BUTTON)
        self.widget("vol-create").set_image(finish_img)

        self.reset_state()


    def show(self, parent):
        logging.debug("Showing new volume wizard")
        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing new volume wizard")
        self.topwin.hide()
        self.set_modal(False)
        return 1

    def _cleanup(self):
        self.conn = None
        self.parent_pool = None

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
            ret = StorageVolume.find_free_name(self.name_hint,
                                pool_object=self.parent_pool.get_backend(),
                                suffix=suffix)
            ret = ret.rstrip(suffix)
        except:
            pass

        return ret

    def default_suffix(self):
        suffix = ""
        if self.vol.file_type == self.vol.TYPE_FILE:
            suffix = ".img"
        return suffix

    def _make_stub_vol(self):
        self.vol = StorageVolume(self.conn.get_backend())
        self.vol.pool = self.parent_pool.get_backend()

    def reset_state(self):
        self._make_stub_vol()

        default_name = self.default_vol_name()
        self.widget("vol-name").set_text("")
        self.widget("vol-create").set_sensitive(False)
        if default_name:
            self.widget("vol-name").set_text(default_name)

        self.widget("vol-name").grab_focus()
        self.populate_vol_format()
        self.populate_vol_suffix()

        if len(self.vol.list_formats()):
            self.widget("vol-format").set_sensitive(True)
            self.widget("vol-format").set_active(0)
        else:
            self.widget("vol-format").set_sensitive(False)

        alloc = DEFAULT_ALLOC
        if self.parent_pool.get_type() == "logical":
            # Sparse LVM volumes don't auto grow, so alloc=0 is useless
            alloc = DEFAULT_CAP

        self.widget("vol-allocation").set_range(0,
                        int(self.parent_pool.get_available() / 1024 / 1024))
        self.widget("vol-allocation").set_value(alloc)
        self.widget("vol-capacity").set_range(1,
                        int(self.parent_pool.get_available() / 1024 / 1024))
        self.widget("vol-capacity").set_value(DEFAULT_CAP)

        self.widget("vol-parent-name").set_markup(
                        "<b>" + self.parent_pool.get_name() + "'s</b>")
        self.widget("vol-parent-space").set_text(
                        self.parent_pool.get_pretty_available())


    def get_config_format(self):
        format_combo = self.widget("vol-format")
        model = format_combo.get_model()
        if format_combo.get_active_iter() is not None:
            model = format_combo.get_model()
            return model.get_value(format_combo.get_active_iter(), 0)
        return None

    def populate_vol_format(self):
        rhel6_file_whitelist = ["raw", "qcow2", "qed"]
        model = self.widget("vol-format").get_model()
        model.clear()

        formats = self.vol.list_formats()
        if self.vol.list_create_formats() is not None:
            formats = self.vol.list_create_formats()

        if (self.vol.file_type == self.vol.TYPE_FILE and
            not self.conn.rhel6_defaults_caps()):
            newfmts = []
            for f in rhel6_file_whitelist:
                if f in formats:
                    newfmts.append(f)
            formats = newfmts

        for f in formats:
            model.append([f, f])

    def populate_vol_suffix(self):
        self.widget("vol-name-suffix").set_text(self.default_suffix())

    def vol_name_changed(self, src):
        text = src.get_text()
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

    def _finish_cb(self, error, details):
        self.topwin.set_sensitive(True)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.TOP_LEFT_ARROW))

        if error:
            error = _("Error creating vol: %s") % error
            self.show_err(error,
                          details=details)
        else:
            # vol-created will refresh the parent pool
            self.emit("vol-created")
            self.close()

    def finish(self, src_ignore):
        try:
            if not self.validate():
                return
        except Exception, e:
            self.show_err(_("Uncaught error validating input: %s") % str(e))
            return

        logging.debug("Creating volume with xml:\n%s",
                      self.vol.get_xml_config())

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

        try:
            self._make_stub_vol()
            self.vol.capacity = cap
            self.vol.name = volname
            self.vol.allocation = (alloc * 1024 * 1024)
            self.vol.capacity = (cap * 1024 * 1024)
            if fmt:
                self.vol.format = fmt
            self.vol.validate()
        except ValueError, e:
            return self.val_err(_("Volume Parameter Error"), e)
        return True

    def show_err(self, info, details=None):
        self.err.show_err(info, details, modal=self.topwin.get_modal())

    def val_err(self, info, details):
        modal = self.topwin.get_modal()
        ret = False
        try:
            self.topwin.set_modal(False)
            ret = self.err.val_err(info, details, modal=modal)
        finally:
            self.topwin.set_modal(modal)

        return ret

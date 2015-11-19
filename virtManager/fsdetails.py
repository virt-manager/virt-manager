#
# Copyright (C) 2006-2007, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
# Copyright (C) 2014 SUSE LINUX Products GmbH, Nuernberg, Germany.
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
from gi.repository import GObject

from virtinst import VirtualFilesystem, StorageVolume
from virtinst import util
from . import uiutil
from .baseclass import vmmGObjectUI
from .storagebrowse import vmmStorageBrowser


class vmmFSDetails(vmmGObjectUI):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, [])
    }

    def __init__(self, vm, builder, topwin):
        vmmGObjectUI.__init__(self, "fsdetails.ui",
                              None, builder=builder, topwin=topwin)

        self.vm = vm
        self.conn = vm.conn

        self._dev = None
        self.storage_browser = None

        self.builder.connect_signals({
            "on_fs_type_combo_changed": self.change_field,
            "on_fs_driver_combo_changed": self.change_field,
            "on_fs_source_browse_clicked": self.browse_fs_source,
            "on_fs_mode_combo_changed": self.notify_change,
            "on_fs_wrpolicy_combo_changed": self.notify_change,
            "on_fs_readonly_toggled": self.notify_change,
            "on_fs_format_combo_changed": self.notify_change,
            "on_fs_source_changed": self.notify_change,
            "on_fs_ram_source_changed": self.notify_change,
            "on_fs_target_changed": self.notify_change,
        })

        self.set_initial_state()
        self.top_box = self.widget("vmm-fs-details")

    def _cleanup(self):
        self.vm = None
        self.conn = None
        self._dev = None

        if self.storage_browser:
            self.storage_browser.cleanup()
            self.storage_browser = None

    def show_pair_combo(self, basename, show_combo):
        combo = self.widget(basename + "-combo")
        label = self.widget(basename + "-label")

        combo.set_visible(show_combo)
        label.set_visible(not show_combo)

    def show_check_button(self, basename, show):
        check = self.widget(basename)
        check.set_visible(show)

    ##########################
    # Initialization methods #
    ##########################

    def set_initial_state(self):
        def simple_store_set(comboname, values, sort=True, capitalize=True):
            combo = self.widget(comboname)
            model = Gtk.ListStore(str, str)
            combo.set_model(model)
            uiutil.init_combo_text_column(combo, 1)
            if sort:
                model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
            if capitalize:
                for val in values:
                    model.append([val, val.capitalize()])
            else:
                for val in values:
                    model.append([val.lower(), val])

        # Filesystem widgets
        if self.conn.is_openvz():
            simple_store_set("fs-type-combo",
                [VirtualFilesystem.TYPE_MOUNT,
                 VirtualFilesystem.TYPE_TEMPLATE], sort=False)
        elif self.conn.is_lxc():
            simple_store_set("fs-type-combo",
                [VirtualFilesystem.TYPE_MOUNT,
                 VirtualFilesystem.TYPE_FILE,
                 VirtualFilesystem.TYPE_BLOCK,
                 VirtualFilesystem.TYPE_RAM], sort=False)
        else:
            simple_store_set("fs-type-combo", [VirtualFilesystem.TYPE_MOUNT])
            self.widget("fs-type-label").set_text(VirtualFilesystem.TYPE_MOUNT)

        simple_store_set("fs-mode-combo", VirtualFilesystem.MODES)
        if self.conn.is_qemu() or self.conn.is_test_conn():
            simple_store_set("fs-driver-combo",
                [VirtualFilesystem.DRIVER_PATH,
                 VirtualFilesystem.DRIVER_HANDLE,
                 VirtualFilesystem.DRIVER_DEFAULT])
        elif self.conn.is_lxc():
            simple_store_set("fs-driver-combo",
                [VirtualFilesystem.DRIVER_LOOP,
                 VirtualFilesystem.DRIVER_NBD,
                 VirtualFilesystem.DRIVER_DEFAULT])
        else:
            simple_store_set("fs-driver-combo",
                [VirtualFilesystem.DRIVER_DEFAULT])
        simple_store_set("fs-format-combo",
            StorageVolume.ALL_FORMATS, capitalize=False)
        simple_store_set("fs-wrpolicy-combo", VirtualFilesystem.WRPOLICIES)
        self.show_pair_combo("fs-type",
            self.conn.is_openvz() or self.conn.is_lxc())
        self.show_check_button("fs-readonly",
                self.conn.is_qemu() or
                self.conn.is_test_conn() or
                self.conn.is_lxc())

    def reset_state(self):
        self.widget("fs-type-combo").set_active(0)
        self.widget("fs-mode-combo").set_active(0)
        self.widget("fs-driver-combo").set_active(0)
        self.widget("fs-format-combo").set_active(0)
        self.widget("fs-wrpolicy-combo").set_active(0)
        self.widget("fs-source").set_text("")
        self.widget("fs-target").set_text("")
        self.widget("fs-readonly").set_active(False)

    # Getters
    def get_dev(self):
        return self._dev

    def get_config_fs_mode(self):
        return uiutil.get_list_selection(self.widget("fs-mode-combo"),
                                         check_visible=True)

    def get_config_fs_wrpolicy(self):
        return uiutil.get_list_selection(self.widget("fs-wrpolicy-combo"),
                                         check_visible=True)

    def get_config_fs_type(self):
        return uiutil.get_list_selection(self.widget("fs-type-combo"),
                                         check_visible=True)

    def get_config_fs_readonly(self):
        if not self.widget("fs-readonly").is_visible():
            return None
        return self.widget("fs-readonly").get_active()

    def get_config_fs_driver(self):
        return uiutil.get_list_selection(self.widget("fs-driver-combo"),
                                         check_visible=True)

    def get_config_fs_format(self):
        return uiutil.get_list_selection(self.widget("fs-format-combo"),
                                         check_visible=True)

    # Setters
    def set_dev(self, dev):
        self._dev = dev

        self.set_config_value("fs-type", dev.type or "default")
        self.set_config_value("fs-mode", dev.accessmode or "default")
        self.set_config_value("fs-driver", dev.driver or "default")
        self.set_config_value("fs-wrpolicy", dev.wrpolicy or "default")
        self.set_config_value("fs-format", dev.format or "default")
        if dev.type != VirtualFilesystem.TYPE_RAM:
            self.widget("fs-source").set_text(dev.source)
        else:
            self.set_config_ram_usage(dev.source, dev.units)
        self.widget("fs-target").set_text(dev.target or "")
        self.widget("fs-readonly").set_active(dev.readonly)

        self.show_pair_combo("fs-type",
            self.conn.is_openvz() or self.conn.is_lxc())

    def set_config_ram_usage(self, usage, units):
        value = int(usage)

        units = units.lower()
        if units == "bytes" or units == "byte":
            units = "b"

        value = util.convert_units(value, units.lower(), 'mb')
        self.widget("fs-ram-source-spin").set_value(value)

    def set_config_value(self, name, value):
        combo = self.widget("%s-combo" % name)
        label = self.widget("%s-label" % name)

        idx = -1
        model_list = [x[0] for x in combo.get_model()]
        model_in_list = (value in model_list)
        if model_in_list:
            idx = model_list.index(value)

        combo.set_active(idx)
        if label:
            label.set_text(value)

    # listeners
    def notify_change(self, ignore):
        self.emit("changed")

    def browse_fs_source(self, ignore1):
        self._browse_file(self.widget("fs-source"), isdir=True)

    def update_fs_rows(self):
        fstype = self.get_config_fs_type()
        fsdriver = self.get_config_fs_driver()
        ismount = bool(
                fstype == VirtualFilesystem.TYPE_MOUNT or
                self.conn.is_qemu() or self.conn.is_test_conn())

        show_mode = bool(ismount and
            (fsdriver == VirtualFilesystem.DRIVER_PATH or
            fsdriver == VirtualFilesystem.DRIVER_DEFAULT))
        uiutil.set_grid_row_visible(self.widget("fs-mode-box"), show_mode)

        show_wrpol = bool(ismount and
            fsdriver and (fsdriver == VirtualFilesystem.DRIVER_PATH or
            fsdriver == VirtualFilesystem.DRIVER_HANDLE))
        uiutil.set_grid_row_visible(self.widget("fs-wrpolicy-box"),
                                       show_wrpol)

        show_ram_source = fstype == VirtualFilesystem.TYPE_RAM
        uiutil.set_grid_row_visible(
            self.widget("fs-ram-source-box"), show_ram_source)
        uiutil.set_grid_row_visible(
            self.widget("fs-source-box"), not show_ram_source)

        show_format = bool(
            fsdriver == VirtualFilesystem.DRIVER_NBD)
        uiutil.set_grid_row_visible(self.widget("fs-format-box"), show_format)
        self.show_pair_combo("fs-format", True)

        show_mode_combo = False
        show_driver_combo = False
        show_wrpolicy_combo = self.conn.is_qemu() or self.conn.is_test_conn()
        if fstype == VirtualFilesystem.TYPE_TEMPLATE:
            source_text = _("Te_mplate:")
        else:
            source_text = _("_Source path:")
            show_mode_combo = self.conn.is_qemu() or self.conn.is_test_conn()
            show_driver_combo = (self.conn.is_qemu() or
                                 self.conn.is_lxc() or
                                 self.conn.is_test_conn())

        self.widget("fs-source-title").set_text(source_text)
        self.widget("fs-source-title").set_use_underline(True)
        self.show_pair_combo("fs-mode", show_mode_combo)
        self.show_pair_combo("fs-driver", show_driver_combo)
        self.show_pair_combo("fs-wrpolicy", show_wrpolicy_combo)

    def change_field(self, src):
        self.update_fs_rows()
        self.notify_change(src)

    # Page validation method
    def validate_page_filesystem(self):
        conn = self.conn.get_backend()
        source = self.widget("fs-source").get_text()
        target = self.widget("fs-target").get_text()
        usage = uiutil.spin_get_helper(self.widget("fs-ram-source-spin"))
        mode = self.get_config_fs_mode()
        fstype = self.get_config_fs_type()
        readonly = self.get_config_fs_readonly()
        driver = self.get_config_fs_driver()
        fsformat = self.get_config_fs_format()
        wrpolicy = self.get_config_fs_wrpolicy()

        if not source and fstype != VirtualFilesystem.TYPE_RAM:
            return self.err.val_err(_("A filesystem source must be specified"))
        elif usage == 0 and fstype == VirtualFilesystem.TYPE_RAM:
            return self.err.val_err(
                _("A RAM filesystem usage must be specified"))
        if not target:
            return self.err.val_err(_("A filesystem target must be specified"))

        try:
            self._dev = VirtualFilesystem(conn)
            if fstype == VirtualFilesystem.TYPE_RAM:
                self._dev.source = usage
                self._dev.units = 'MiB'
            else:
                self._dev.source = source
            self._dev.target = target
            if mode:
                self._dev.accessmode = mode
            if fstype:
                self._dev.type = fstype
            if readonly:
                self._dev.readonly = readonly
            if driver:
                self._dev.driver = driver
                if driver == VirtualFilesystem.DRIVER_LOOP:
                    self._dev.format = "raw"
                elif driver == VirtualFilesystem.DRIVER_NBD:
                    self._dev.format = fsformat
            if wrpolicy:
                self._dev.wrpolicy = wrpolicy
        except Exception, e:
            return self.err.val_err(_("Filesystem parameter error"), e)

    def _browse_file(self, textent, isdir=False):
        def set_storage_cb(src, path):
            if path:
                textent.set_text(path)

        reason = (isdir and
                  self.config.CONFIG_DIR_FS or
                  self.config.CONFIG_DIR_IMAGE)

        if self.storage_browser and self.storage_browser.conn != self.conn:
            self.storage_browser.cleanup()
            self.storage_browser = None
        if self.storage_browser is None:
            self.storage_browser = vmmStorageBrowser(self.conn)

        self.storage_browser.set_stable_defaults(self.vm.stable_defaults())
        self.storage_browser.set_finish_cb(set_storage_cb)
        self.storage_browser.set_browse_reason(reason)

        self.storage_browser.show(self.topwin.get_ancestor(Gtk.Window))

# Copyright (C) 2006-2007, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
# Copyright (C) 2014 SUSE LINUX Products GmbH, Nuernberg, Germany.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gtk

from virtinst import DeviceFilesystem

from ..lib import uiutil
from ..baseclass import vmmGObjectUI
from ..storagebrowse import vmmStorageBrowser


class vmmFSDetails(vmmGObjectUI):
    __gsignals__ = {
        "changed": (vmmGObjectUI.RUN_FIRST, None, [])
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
            # [XML value, label]
            model = Gtk.ListStore(str, str)
            combo.set_model(model)
            uiutil.init_combo_text_column(combo, 1)
            if sort:
                model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

            for xmlval in values:
                label = xmlval
                if xmlval is None:
                    label = "Default"
                if capitalize:
                    label = label.capitalize()
                model.append([xmlval, label])

        # Filesystem widgets
        if self.conn.is_container_only():
            simple_store_set("fs-type-combo",
                [DeviceFilesystem.TYPE_MOUNT,
                 DeviceFilesystem.TYPE_FILE,
                 DeviceFilesystem.TYPE_BLOCK,
                 DeviceFilesystem.TYPE_RAM], sort=False)
        else:
            simple_store_set("fs-type-combo", [DeviceFilesystem.TYPE_MOUNT])
            self.widget("fs-type-label").set_text(DeviceFilesystem.TYPE_MOUNT)

        simple_store_set("fs-mode-combo", DeviceFilesystem.MODES + [None])

        drivers = []
        if self.conn.is_qemu() or self.conn.is_test():
            drivers += [DeviceFilesystem.DRIVER_PATH,
                    DeviceFilesystem.DRIVER_HANDLE]
        if self.conn.is_lxc() or self.conn.is_test():
            drivers += [DeviceFilesystem.DRIVER_LOOP,
                 DeviceFilesystem.DRIVER_NBD]
        simple_store_set("fs-driver-combo", drivers + [None])

        simple_store_set("fs-format-combo", ["raw", "qcow2"], capitalize=False)
        self.show_pair_combo("fs-type", self.conn.is_container_only())
        self.show_check_button("fs-readonly",
                self.conn.is_qemu() or
                self.conn.is_test() or
                self.conn.is_lxc())

    def reset_state(self):
        self.widget("fs-type-combo").set_active(0)
        self.widget("fs-mode-combo").set_active(0)
        self.widget("fs-driver-combo").set_active(0)
        self.widget("fs-format-combo").set_active(0)
        self.widget("fs-source").set_text("")
        self.widget("fs-target").set_text("")
        self.widget("fs-readonly").set_active(False)

    # Getters
    def get_config_fs_mode(self):
        return uiutil.get_list_selection(self.widget("fs-mode-combo"),
                                         check_visible=True)

    def get_config_fs_type(self):
        if self.widget("fs-type-label").is_visible():
            return self.widget("fs-type-label").get_text()
        return uiutil.get_list_selection(self.widget("fs-type-combo"),
                                         check_visible=True)

    def get_config_fs_readonly(self):
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

        self.set_config_value("fs-type", dev.type)
        self.set_config_value("fs-mode", dev.accessmode)
        self.set_config_value("fs-driver", dev.driver_type)
        self.set_config_value("fs-format", dev.driver_format)
        if dev.type != DeviceFilesystem.TYPE_RAM:
            self.widget("fs-source").set_text(dev.source)
        else:
            self.widget("fs-ram-source-spin").set_value(int(dev.source) // 1024)
        self.widget("fs-target").set_text(dev.target or "")
        self.widget("fs-readonly").set_active(dev.readonly)

        self.show_pair_combo("fs-type", self.conn.is_container_only())

    def set_config_value(self, name, value):
        combo = self.widget("%s-combo" % name)
        label = self.widget("%s-label" % name)

        uiutil.set_list_selection(combo, value)
        if label:
            label.set_text(value or "default")

    # listeners
    def notify_change(self, ignore):
        self.emit("changed")

    def browse_fs_source(self, ignore1):
        self._browse_file(self.widget("fs-source"), isdir=True)

    def update_fs_rows(self):
        fstype = self.get_config_fs_type()
        fsdriver = self.get_config_fs_driver()
        ismount = bool(
                fstype == DeviceFilesystem.TYPE_MOUNT or
                self.conn.is_qemu() or self.conn.is_test())

        show_mode = bool(ismount and
            (fsdriver == DeviceFilesystem.DRIVER_PATH or
            fsdriver is None))
        uiutil.set_grid_row_visible(self.widget("fs-mode-box"), show_mode)

        show_ram_source = fstype == DeviceFilesystem.TYPE_RAM
        uiutil.set_grid_row_visible(
            self.widget("fs-ram-source-box"), show_ram_source)
        uiutil.set_grid_row_visible(
            self.widget("fs-source-box"), not show_ram_source)

        show_format = bool(
            fsdriver == DeviceFilesystem.DRIVER_NBD)
        uiutil.set_grid_row_visible(self.widget("fs-format-box"), show_format)
        self.show_pair_combo("fs-format", True)

        show_mode_combo = False
        show_driver_combo = False
        if fstype == DeviceFilesystem.TYPE_TEMPLATE:
            source_text = _("Te_mplate:")
        else:
            source_text = _("_Source path:")
            show_mode_combo = self.conn.is_qemu() or self.conn.is_test()
            show_driver_combo = (self.conn.is_qemu() or
                                 self.conn.is_lxc() or
                                 self.conn.is_test())

        self.widget("fs-source-title").set_text(source_text)
        self.widget("fs-source-title").set_use_underline(True)
        self.show_pair_combo("fs-mode", show_mode_combo)
        self.show_pair_combo("fs-driver", show_driver_combo)

    def change_field(self, src):
        self.update_fs_rows()
        self.notify_change(src)


    ####################
    # Internal helpers #
    ####################

    def _browse_file(self, textent, isdir=False):
        def set_storage_cb(src, path):
            if path:
                textent.set_text(path)

        reason = (isdir and
                  self.config.CONFIG_DIR_FS or
                  self.config.CONFIG_DIR_IMAGE)

        if self.storage_browser is None:
            self.storage_browser = vmmStorageBrowser(self.conn)

        self.storage_browser.set_finish_cb(set_storage_cb)
        self.storage_browser.set_browse_reason(reason)

        self.storage_browser.show(self.topwin.get_ancestor(Gtk.Window))


    ###################
    # Device building #
    ###################

    def _build_xmlobj(self):
        conn = self.conn.get_backend()
        source = self.widget("fs-source").get_text()
        target = self.widget("fs-target").get_text()
        usage = uiutil.spin_get_helper(self.widget("fs-ram-source-spin"))
        mode = self.get_config_fs_mode()
        fstype = self.get_config_fs_type()
        readonly = self.get_config_fs_readonly()
        driver = self.get_config_fs_driver()
        fsformat = self.get_config_fs_format()

        dev = DeviceFilesystem(conn)
        if fstype == DeviceFilesystem.TYPE_RAM:
            dev.source = usage
            dev.source_units = 'MiB'
        else:
            dev.source = source
        dev.target = target
        dev.validate_target(target)
        if mode:
            dev.accessmode = mode
        if fstype:
            dev.type = fstype
        if readonly:
            dev.readonly = readonly
        if driver:
            dev.driver_type = driver
            if driver == DeviceFilesystem.DRIVER_LOOP:
                dev.driver_format = "raw"
            elif driver == DeviceFilesystem.DRIVER_NBD:
                dev.driver_format = fsformat

        dev.validate()
        return dev

    def build_xmlobj(self):
        self._dev = self._build_xmlobj()
        return self._dev

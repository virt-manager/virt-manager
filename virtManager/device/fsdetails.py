# Copyright (C) 2006-2007, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
# Copyright (C) 2014 SUSE LINUX Products GmbH, Nuernberg, Germany.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gtk

from virtinst import DeviceFilesystem
from virtinst import xmlutil

from ..lib import uiutil
from ..baseclass import vmmGObjectUI
from ..storagebrowse import vmmStorageBrowser


_EDIT_FS_ENUM = range(1, 8)
(
    _EDIT_FS_TYPE,
    _EDIT_FS_DRIVER,
    _EDIT_FS_SOURCE,
    _EDIT_FS_RAM_SOURCE,
    _EDIT_FS_READONLY,
    _EDIT_FS_TARGET,
    _EDIT_FS_FORMAT,
) = _EDIT_FS_ENUM


class vmmFSDetails(vmmGObjectUI):
    __gsignals__ = {
        "changed": (vmmGObjectUI.RUN_FIRST, None, [])
    }

    def __init__(self, vm, builder, topwin):
        vmmGObjectUI.__init__(self, "fsdetails.ui",
                              None, builder=builder, topwin=topwin)

        self.vm = vm
        self.conn = vm.conn

        self._storage_browser = None
        self._active_edits = []

        def _e(edittype):
            def signal_cb(*args):
                self._change_cb(edittype)
            return signal_cb

        self.builder.connect_signals({
            "on_fs_source_browse_clicked": self._browse_fs_source_cb,
            "on_fs_type_combo_changed": _e(_EDIT_FS_TYPE),
            "on_fs_driver_combo_changed": _e(_EDIT_FS_DRIVER),
            "on_fs_readonly_toggled": _e(_EDIT_FS_READONLY),
            "on_fs_format_combo_changed": _e(_EDIT_FS_FORMAT),
            "on_fs_source_changed": _e(_EDIT_FS_SOURCE),
            "on_fs_ram_source_changed": _e(_EDIT_FS_RAM_SOURCE),
            "on_fs_target_changed": _e(_EDIT_FS_TARGET),
        })

        self._init_ui()
        self.top_box = self.widget("vmm-fs-details")

    def _cleanup(self):
        self.vm = None
        self.conn = None

        if self._storage_browser:
            self._storage_browser.cleanup()
            self._storage_browser = None


    ##########################
    # Initialization methods #
    ##########################

    def _init_ui(self):
        def simple_store_set(comboname, values):
            combo = self.widget(comboname)
            # [XML value, label]
            model = Gtk.ListStore(str, str)
            combo.set_model(model)
            uiutil.init_combo_text_column(combo, 1)

            for xmlval in values:
                label = xmlval
                if xmlval is None:
                    label = _("Hypervisor default")
                model.append([xmlval, label])

        # Filesystem widgets
        if self.conn.is_container_only():
            simple_store_set("fs-type-combo",
                [DeviceFilesystem.TYPE_MOUNT,
                 DeviceFilesystem.TYPE_FILE,
                 DeviceFilesystem.TYPE_BLOCK,
                 DeviceFilesystem.TYPE_RAM])
        else:
            simple_store_set("fs-type-combo", [DeviceFilesystem.TYPE_MOUNT])

        if self.conn.is_container_only():
            simple_store_set("fs-driver-combo",
                    [DeviceFilesystem.DRIVER_LOOP,
                     DeviceFilesystem.DRIVER_NBD,
                     None])
        else:
            domcaps = self.vm.get_domain_capabilities()
            rows = []
            if domcaps.supports_filesystem_virtiofs():
                rows.append(["virtiofs", "virtiofs"])
            rows.append([None, "virtio-9p"])
            uiutil.build_simple_combo(
                    self.widget("fs-driver-combo"), rows, sort=False)

        simple_store_set("fs-format-combo", ["raw", "qcow2"])
        self.widget("fs-readonly").set_visible(
                self.conn.is_qemu() or
                self.conn.is_test() or
                self.conn.is_lxc())


    ##############
    # UI syncing #
    ##############

    def _sync_ui(self):
        fstype = uiutil.get_list_selection(self.widget("fs-type-combo"))
        fsdriver = uiutil.get_list_selection(self.widget("fs-driver-combo"))
        is_qemu = self.conn.is_qemu() or self.conn.is_test()

        show_ram_source = fstype == DeviceFilesystem.TYPE_RAM
        uiutil.set_grid_row_visible(
            self.widget("fs-ram-source-box"), show_ram_source)
        uiutil.set_grid_row_visible(
            self.widget("fs-source-box"), not show_ram_source)

        show_format = bool(
            fsdriver == DeviceFilesystem.DRIVER_NBD)
        uiutil.set_grid_row_visible(
                self.widget("fs-format-combo"), show_format)

        show_driver_combo = is_qemu or fstype == DeviceFilesystem.TYPE_FILE

        if fstype == DeviceFilesystem.TYPE_TEMPLATE:
            source_text = _("Te_mplate:")
        else:
            source_text = _("_Source path:")

        self.widget("fs-source-title").set_text(source_text)
        self.widget("fs-source-title").set_use_underline(True)
        uiutil.set_grid_row_visible(
                self.widget("fs-type-combo"), not is_qemu)
        uiutil.set_grid_row_visible(
                self.widget("fs-driver-combo"), show_driver_combo)

        need_shared_mem = fsdriver == "virtiofs"
        have_shared_mem, _shared_mem_err = self.vm.has_shared_mem()
        show_shared_mem_warn = need_shared_mem and not have_shared_mem
        uiutil.set_grid_row_visible(
                self.widget("fs-driver-warn-box"), show_shared_mem_warn)
        if show_shared_mem_warn:
            label = _(
                    "You may need to 'Enable shared memory' on the 'Memory' screen.")
            self.widget("fs-driver-warn").set_markup(
                    "<small>%s</small>" % xmlutil.xml_escape(label))


    ##############
    # Public API #
    ##############

    def reset_state(self):
        self.widget("fs-type-combo").set_active(0)
        self.widget("fs-driver-combo").set_active(0)
        self.widget("fs-format-combo").set_active(0)
        self.widget("fs-source").set_text("")
        self.widget("fs-target").set_text("")
        self.widget("fs-readonly").set_active(False)
        self._sync_ui()
        self._active_edits = []

    def set_dev(self, dev):
        self.reset_state()

        uiutil.set_list_selection(
                self.widget("fs-type-combo"), dev.type)
        uiutil.set_list_selection(
                self.widget("fs-driver-combo"), dev.driver_type)
        uiutil.set_list_selection(
                self.widget("fs-format-combo"), dev.driver_format)

        if dev.type != DeviceFilesystem.TYPE_RAM:
            self.widget("fs-source").set_text(dev.source)
        else:
            self.widget("fs-ram-source-spin").set_value(int(dev.source) // 1024)
        self.widget("fs-target").set_text(dev.target or "")
        self.widget("fs-readonly").set_active(dev.readonly)

        self._active_edits = []


    ###################
    # Device building #
    ###################

    def _set_values(self, dev):
        fstype = uiutil.get_list_selection(self.widget("fs-type-combo"))
        usage = uiutil.spin_get_helper(self.widget("fs-ram-source-spin"))

        source = self.widget("fs-source").get_text()
        target = self.widget("fs-target").get_text()
        readonly = self.widget("fs-readonly").get_active()

        fsformat = uiutil.get_list_selection(self.widget("fs-format-combo"))
        if not self.widget("fs-format-combo").get_visible():
            fsformat = None

        driver = uiutil.get_list_selection(self.widget("fs-driver-combo"))
        if not self.widget("fs-driver-combo").get_visible():
            driver = None

        if _EDIT_FS_TYPE in self._active_edits:
            dev.type = fstype
        if (_EDIT_FS_RAM_SOURCE in self._active_edits or
            _EDIT_FS_SOURCE in self._active_edits):
            if fstype == DeviceFilesystem.TYPE_RAM:
                dev.source = usage
                dev.source_units = 'MiB'
            else:
                dev.source = source
        if _EDIT_FS_TARGET in self._active_edits:
            dev.target = target
        if _EDIT_FS_READONLY in self._active_edits:
            dev.readonly = readonly
        if _EDIT_FS_DRIVER in self._active_edits:
            origdriver = dev.driver_type
            dev.driver_type = driver
            if origdriver == "virtiofs" or driver == "virtiofs":
                # Need to reset the accessmode for virtiofs
                dev.accessmode = dev.default_accessmode()
        if _EDIT_FS_FORMAT in self._active_edits:
            dev.driver_format = fsformat

    def build_device(self):
        self._active_edits = _EDIT_FS_ENUM[:]

        conn = self.conn.get_backend()
        dev = DeviceFilesystem(conn)
        self._set_values(dev)

        dev.validate_target(dev.target)
        dev.validate()
        return dev

    def update_device(self, dev):
        newdev = DeviceFilesystem(dev.conn, parsexml=dev.get_xml())
        self._set_values(newdev)
        return newdev


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

        if self._storage_browser is None:
            self._storage_browser = vmmStorageBrowser(self.conn)

        self._storage_browser.set_finish_cb(set_storage_cb)
        self._storage_browser.set_browse_reason(reason)
        self._storage_browser.show(self.topwin.get_ancestor(Gtk.Window))


    #############
    # Listeners #
    #############

    def _change_cb(self, edittype):
        self._sync_ui()
        if edittype not in self._active_edits:
            self._active_edits.append(edittype)
        self.emit("changed")

    def _browse_fs_source_cb(self, src):
        self._browse_file(self.widget("fs-source"), isdir=True)

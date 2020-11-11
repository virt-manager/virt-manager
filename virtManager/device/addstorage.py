# Copyright (C) 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from gi.repository import Gtk

import virtinst
from virtinst import log

from ..lib import uiutil
from ..baseclass import vmmGObjectUI

(
    _EDIT_CACHE,
    _EDIT_DISCARD,
    _EDIT_DETECT_ZEROES,
    _EDIT_RO,
    _EDIT_SHARE,
    _EDIT_REMOVABLE,
    _EDIT_SERIAL,
) = range(1, 8)


class vmmAddStorage(vmmGObjectUI):
    __gsignals__ = {
        "browse-clicked": (vmmGObjectUI.RUN_FIRST, None, [object]),
        "storage-toggled": (vmmGObjectUI.RUN_FIRST, None, [object]),
        "changed": (vmmGObjectUI.RUN_FIRST, None, []),
    }

    def __init__(self, conn, builder, topwin):
        vmmGObjectUI.__init__(self, "addstorage.ui", None,
                              builder=builder, topwin=topwin)
        self.conn = conn

        def _e(edittype):
            def signal_cb(*args):
                self._change_cb(edittype)
            return signal_cb

        self.builder.connect_signals({
            "on_storage_browse_clicked": self._browse_storage,
            "on_storage_select_toggled": self._toggle_storage_select,
            "on_disk_cache_combo_changed": _e(_EDIT_CACHE),
            "on_disk_discard_combo_changed": _e(_EDIT_DISCARD),
            "on_disk_detect_zeroes_combo_changed": _e(_EDIT_DETECT_ZEROES),
            "on_disk_readonly_changed": _e(_EDIT_RO),
            "on_disk_shareable_changed": _e(_EDIT_SHARE),
            "on_disk_removable_changed": _e(_EDIT_REMOVABLE),
            "on_disk_serial_changed": _e(_EDIT_SERIAL),
        })

        self._active_edits = []
        self.top_box = self.widget("storage-box")
        self.advanced_top_box = self.widget("storage-advanced-box")
        self._init_ui()

    def _cleanup(self):
        self.conn = None
        self.top_box.destroy()
        self.advanced_top_box.destroy()


    ##########################
    # Initialization methods #
    ##########################

    def _host_disk_space(self):
        try:
            pool = self.conn.get_default_pool()
            if pool and pool.is_active():
                # Rate limit this, since it can be spammed at dialog startup time
                if pool.secs_since_last_refresh() > 10:
                    pool.refresh()
                avail = int(pool.get_available())
                return float(avail / 1024.0 / 1024.0 / 1024.0)
        except Exception:  # pragma: no cover
            log.exception("Error determining host disk space")
        return -1

    def _update_host_space(self):
        widget = self.widget("phys-hd-label")
        max_storage = self._host_disk_space()

        def pretty_storage(size):
            if size == -1:
                return "Unknown GiB"
            return "%.1f GiB" % float(size)

        hd_label = (_("%s available in the default location") %
                    pretty_storage(max_storage))
        hd_label = ("<span>%s</span>" % hd_label)
        widget.set_markup(hd_label)

    def _init_ui(self):
        # Disk cache combo
        values = [[None, _("Hypervisor default")]]
        for m in virtinst.DeviceDisk.CACHE_MODES:
            values.append([m, m])
        uiutil.build_simple_combo(
                self.widget("disk-cache"), values, sort=False)

        # Discard combo
        values = [[None, _("Hypervisor default")]]
        for m in virtinst.DeviceDisk.DISCARD_MODES:
            values.append([m, m])
        uiutil.build_simple_combo(
                self.widget("disk-discard"), values, sort=False)

        # Detect zeroes combo
        values = [[None, _("Hypervisor default")]]
        for m in virtinst.DeviceDisk.DETECT_ZEROES_MODES:
            values.append([m, m])
        uiutil.build_simple_combo(
                self.widget("disk-detect-zeroes"), values, sort=False)


    ##############
    # Public API #
    ##############

    @staticmethod
    def check_path_search(src, conn, path):
        skip_paths = src.config.get_perms_fix_ignore()
        searchdata = virtinst.DeviceDisk.check_path_search(
            conn.get_backend(), path)

        broken_paths = searchdata.fixlist[:]
        for p in broken_paths[:]:
            if p in skip_paths:
                broken_paths.remove(p)

        if not broken_paths:
            return

        log.debug("No search access for dirs: %s", broken_paths)
        resp, chkres = src.err.warn_chkbox(
                        _("The emulator may not have search permissions "
                          "for the path '%s'.") % path,
                        _("Do you want to correct this now?"),
                        _("Don't ask about these directories again."),
                        buttons=Gtk.ButtonsType.YES_NO)

        if chkres:
            src.config.add_perms_fix_ignore(broken_paths)
        if not resp:
            return

        log.debug("Attempting to correct permission issues.")
        errors = virtinst.DeviceDisk.fix_path_search(searchdata)
        if not errors:
            return

        errmsg = _("Errors were encountered changing permissions for the "
                   "following directories:")
        details = ""
        for p, error in errors.items():
            if p in broken_paths:
                details += "%s : %s\n" % (p, error)
        details += "\nIt is very likely the VM will fail to start up."

        log.debug("Permission errors:\n%s", details)

        ignore, chkres = src.err.err_chkbox(errmsg, details,
                             _("Don't ask about these directories again."))

        if chkres:
            src.config.add_perms_fix_ignore(list(errors.keys()))

    def reset_state(self):
        self._update_host_space()
        self._active_edits = []
        self.widget("storage-create").set_active(True)
        self.widget("storage-size").set_value(20)
        self.widget("storage-entry").set_text("")
        self.widget("storage-create-box").set_sensitive(True)
        self.widget("disk-cache").set_active(0)
        self.widget("disk-discard").set_active(0)
        self.widget("disk-detect-zeroes").set_active(0)
        self.widget("disk-serial").set_text("")
        self.widget("storage-advanced").set_expanded(False)
        self.widget("disk-readonly").set_active(False)
        self.widget("disk-shareable").set_active(False)
        self.widget("disk-removable").set_active(False)
        uiutil.set_grid_row_visible(self.widget("disk-removable"), False)

        storage_tooltip = None

        can_storage = (not self.conn.is_remote() or
                       self.conn.support.conn_storage())
        use_storage = self.widget("storage-select")
        storage_area = self.widget("storage-box")

        storage_area.set_sensitive(can_storage)
        if not can_storage:  # pragma: no cover
            storage_tooltip = _("Connection does not support storage"
                                " management.")
            use_storage.set_sensitive(True)
        storage_area.set_tooltip_text(storage_tooltip or "")

    def get_default_path(self, name, collideguest=None):
        pool = self.conn.get_default_pool()
        if not pool:
            return  # pragma: no cover

        fmt = self.conn.get_default_storage_format()
        suffix = virtinst.StorageVolume.get_file_extension_for_format(fmt)
        suffix = suffix or ".img"

        path = virtinst.StorageVolume.find_free_name(
            self.conn.get_backend(), pool.get_backend(), name,
            suffix=suffix, collideguest=collideguest)

        return os.path.join(pool.xmlobj.target_path, path)

    def is_default_storage(self):
        return self.widget("storage-create").get_active()

    def build_device(self, vmname,
            path=None, device="disk", collideguest=None):
        if path is None:
            if self.is_default_storage():
                path = self.get_default_path(vmname, collideguest=collideguest)
            else:
                path = self.widget("storage-entry").get_text().strip()

        disk = virtinst.DeviceDisk(self.conn.get_backend())
        disk.set_source_path(path or None)
        disk.device = device
        vals = self.get_values()

        if vals.get("cache") is not None:
            disk.driver_cache = vals.get("cache")
        if vals.get("discard") is not None:
            disk.driver_discard = vals.get("discard")
        if vals.get("detect_zeroes") is not None:
            disk.driver_detect_zeroes = vals.get("detect_zeroes")
        if vals.get("readonly") is not None:
            disk.read_only = vals.get("readonly")
        if vals.get("shareable") is not None:
            disk.shareable = vals.get("shareable")
        if vals.get("serial") is not None:
            disk.serial = vals.get("serial")
        if (vals.get("removable") is not None and
            self.widget("disk-removable").get_visible()):
            disk.removable = vals.get("removable")

        if disk.wants_storage_creation():
            path = disk.get_source_path()
            pool = disk.get_parent_pool()
            size = uiutil.spin_get_helper(self.widget("storage-size"))
            fmt = self.conn.get_default_storage_format()

            # If the user changed the default disk format to raw, assume
            # they want to maximize performance, so fully allocate the
            # disk image. Otherwise use sparse
            sparse = fmt != 'raw'

            vol_install = virtinst.DeviceDisk.build_vol_install(
                disk.conn, os.path.basename(path), pool,
                size, sparse)
            disk.set_vol_install(vol_install)

            if disk.get_vol_install().supports_format():
                log.debug("Using default prefs format=%s for path=%s",
                    fmt, path)
                disk.get_vol_install().format = fmt
            else:
                log.debug("path=%s can not use default prefs format=%s, "
                        "not setting it", path, fmt)  # pragma: no cover

        return disk

    def validate_device(self, disk):
        if disk.is_empty() and disk.device in ["disk", "lun"]:
            return self.err.val_err(_("A storage path must be specified."))

        disk.validate()
        path = disk.get_source_path()

        # Disk collision
        names = disk.is_conflict_disk()
        if names:
            msg = (_("Disk '%(path)s' is already in use by other "
                   "guests %(names)s") %
                   {"path": path, "names": names})
            res = self.err.yes_no(msg,
                    _("Do you really want to use the disk?"))
            if not res:
                return False

        self.check_path_search(self, self.conn, path)


    ##################
    # Device editing #
    ##################

    def set_disk_bus(self, bus):
        show_removable = (bus == "usb")
        uiutil.set_grid_row_visible(
                self.widget("disk-removable"), show_removable)

    def set_dev(self, disk):
        cache = disk.driver_cache
        discard = disk.driver_discard
        detect_zeroes = disk.driver_detect_zeroes
        ro = disk.read_only
        share = disk.shareable
        removable = disk.removable
        serial = disk.serial

        self.set_disk_bus(disk.bus)

        uiutil.set_list_selection(self.widget("disk-cache"), cache)
        uiutil.set_list_selection(self.widget("disk-discard"), discard)
        uiutil.set_list_selection(
                self.widget("disk-detect-zeroes"), detect_zeroes)

        self.widget("disk-serial").set_text(serial or "")
        self.widget("disk-readonly").set_active(ro)
        self.widget("disk-readonly").set_sensitive(not disk.is_cdrom())
        self.widget("disk-shareable").set_active(share)
        self.widget("disk-removable").set_active(removable)

        # This comes last
        self._active_edits = []


    def get_values(self):
        ret = {}

        if _EDIT_CACHE in self._active_edits:
            ret["cache"] = uiutil.get_list_selection(
                    self.widget("disk-cache"))
        if _EDIT_DISCARD in self._active_edits:
            ret["discard"] = uiutil.get_list_selection(
                    self.widget("disk-discard"))
        if _EDIT_DETECT_ZEROES in self._active_edits:
            ret["detect_zeroes"] = uiutil.get_list_selection(
                    self.widget("disk-detect-zeroes"))
        if _EDIT_RO in self._active_edits:
            ret["readonly"] = self.widget("disk-readonly").get_active()
        if _EDIT_SHARE in self._active_edits:
            ret["shareable"] = self.widget("disk-shareable").get_active()
        if _EDIT_REMOVABLE in self._active_edits:
            ret["removable"] = bool(
                self.widget("disk-removable").get_active())
        if _EDIT_SERIAL in self._active_edits:
            ret["serial"] = self.widget("disk-serial").get_text()

        return ret


    #############
    # Listeners #
    #############

    def _browse_storage(self, ignore):
        self.emit("browse-clicked", self.widget("storage-entry"))

    def _toggle_storage_select(self, src):
        act = src.get_active()
        self.widget("storage-browse-box").set_sensitive(act)
        self.emit("storage-toggled", src)

    def _change_cb(self, edittype):
        if edittype not in self._active_edits:
            self._active_edits.append(edittype)
        self.emit("changed")

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


class vmmAddStorage(vmmGObjectUI):
    __gsignals__ = {
        "browse-clicked": (vmmGObjectUI.RUN_FIRST, None, [object]),
        "storage-toggled": (vmmGObjectUI.RUN_FIRST, None, [object])
    }

    def __init__(self, conn, builder, topwin):
        vmmGObjectUI.__init__(self, "addstorage.ui", None,
                              builder=builder, topwin=topwin)
        self.conn = conn

        self.builder.connect_signals({
            "on_storage_browse_clicked": self._browse_storage,
            "on_storage_select_toggled": self._toggle_storage_select,
        })

        self.top_box = self.widget("storage-box")

    def _cleanup(self):
        self.conn = None


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
        except Exception:
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
        hd_label = ("<span color='#484848'>%s</span>" % hd_label)
        widget.set_markup(hd_label)


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
        errors = virtinst.DeviceDisk.fix_path_search(
                conn.get_backend(), searchdata)
        if not errors:
            return

        errmsg = _("Errors were encountered changing permissions for the "
                   "following directories:")
        details = ""
        for p, error in errors.items():
            if p not in broken_paths:
                continue
            details += "%s : %s\n" % (p, error)
        details += "\nIt is very likely the VM will fail to start up."

        log.debug("Permission errors:\n%s", details)

        ignore, chkres = src.err.err_chkbox(errmsg, details,
                             _("Don't ask about these directories again."))

        if chkres:
            src.config.add_perms_fix_ignore(list(errors.keys()))

    def reset_state(self):
        self._update_host_space()
        self.widget("storage-create").set_active(True)
        self.widget("storage-size").set_value(20)
        self.widget("storage-entry").set_text("")
        self.widget("storage-create-box").set_sensitive(True)

        storage_tooltip = None

        can_storage = (not self.conn.is_remote() or
                       self.conn.is_storage_capable())
        use_storage = self.widget("storage-select")
        storage_area = self.widget("storage-box")

        storage_area.set_sensitive(can_storage)
        if not can_storage:
            storage_tooltip = _("Connection does not support storage"
                                " management.")
            use_storage.set_sensitive(True)
        storage_area.set_tooltip_text(storage_tooltip or "")

    def get_default_path(self, name, collideguest=None):
        pool = self.conn.get_default_pool()
        if not pool:
            return

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
        disk.path = path or None
        disk.device = device

        if disk.wants_storage_creation():
            pool = disk.get_parent_pool()
            size = uiutil.spin_get_helper(self.widget("storage-size"))
            sparse = False

            vol_install = virtinst.DeviceDisk.build_vol_install(
                disk.conn, os.path.basename(disk.path), pool,
                size, sparse)
            disk.set_vol_install(vol_install)

            fmt = self.conn.get_default_storage_format()
            if disk.get_vol_install().supports_format():
                log.debug("Using default prefs format=%s for path=%s",
                    fmt, disk.path)
                disk.get_vol_install().format = fmt
            else:
                log.debug("path=%s can not use default prefs format=%s, "
                    "not setting it", disk.path, fmt)

        return disk

    def validate_device(self, disk):
        if not disk.path and disk.device in ["disk", "lun"]:
            return self.err.val_err(_("A storage path must be specified."))

        disk.validate()

        isfatal, errmsg = disk.is_size_conflict()
        if not isfatal and errmsg:
            # Fatal errors are reported when setting 'size'
            res = self.err.ok_cancel(_("Not Enough Free Space"), errmsg)
            if not res:
                return False

        # Disk collision
        names = disk.is_conflict_disk()
        if names:
            res = self.err.yes_no(
                    _('Disk "%s" is already in use by other guests %s') %
                     (disk.path, names),
                    _("Do you really want to use the disk?"))
            if not res:
                return False

        self.check_path_search(self, self.conn, disk.path)


    #############
    # Listeners #
    #############

    def _browse_storage(self, ignore):
        self.emit("browse-clicked", self.widget("storage-entry"))

    def _toggle_storage_select(self, src):
        act = src.get_active()
        self.widget("storage-browse-box").set_sensitive(act)
        self.emit("storage-toggled", src)

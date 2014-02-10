#
# Copyright (C) 2014 Red Hat, Inc.
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
import os
import statvfs

# pylint: disable=E0611
from gi.repository import GObject
from gi.repository import Gtk
# pylint: enable=E0611

import virtinst
from virtManager import uiutil
from virtManager.baseclass import vmmGObjectUI


class vmmAddStorage(vmmGObjectUI):
    __gsignals__ = {
        "browse-clicked": (GObject.SignalFlags.RUN_FIRST, None, [object]),
        "storage-toggled": (GObject.SignalFlags.RUN_FIRST, None, [object])
    }

    def __init__(self, conn, builder, topwin):
        vmmGObjectUI.__init__(self, "addstorage.ui", None,
                              builder=builder, topwin=topwin)
        self.conn = conn
        self.storage_browser = None

        self.builder.connect_signals({
            "on_config_storage_browse_clicked": self._browse_storage,
            "on_config_storage_select_toggled": self._toggle_storage_select,
        })

        self.top_box = self.widget("config-storage-box")

    def _cleanup(self):
        self.conn = None


    ##########################
    # Initialization methods #
    ##########################

    def _get_default_dir(self):
        pool = self.conn.get_default_pool()
        if pool:
            return pool.get_target_path()
        return self.config.get_default_image_dir(self.conn)

    def _get_ideal_path_info(self, name):
        path = self._get_default_dir()
        fmt = self.conn.get_default_storage_format()
        suffix = virtinst.StorageVolume.get_file_extension_for_format(fmt)
        return (path, name, suffix or ".img")

    def _get_ideal_path(self, name):
        target, name, suffix = self._get_ideal_path_info(name)
        return os.path.join(target, name) + suffix

    def _host_disk_space(self):
        pool = self.conn.get_default_pool()
        path = self._get_default_dir()

        avail = 0
        if pool and pool.is_active():
            # FIXME: make sure not inactive?
            # FIXME: use a conn specific function after we send pool-added
            pool.refresh()
            avail = int(pool.get_available())

        elif not self.conn.is_remote() and os.path.exists(path):
            vfs = os.statvfs(os.path.dirname(path))
            avail = vfs[statvfs.F_FRSIZE] * vfs[statvfs.F_BAVAIL]

        return float(avail / 1024.0 / 1024.0 / 1024.0)


    def _update_host_space(self):
        widget = self.widget("phys-hd-label")
        try:
            max_storage = self._host_disk_space()
        except:
            logging.exception("Error determining host disk space")
            widget.set_markup("")
            return

        def pretty_storage(size):
            return "%.1f GB" % float(size)

        hd_label = ("%s available in the default location" %
                    pretty_storage(max_storage))
        hd_label = ("<span color='#484848'>%s</span>" % hd_label)
        widget.set_markup(hd_label)

    def _is_default_storage(self):
        return bool(self.widget("config-storage-create").get_active())

    def _check_default_pool_active(self):
        default_pool = self.conn.get_default_pool()
        if default_pool and not default_pool.is_active():
            res = self.err.yes_no(_("Default pool is not active."),
                             _("Storage pool '%s' is not active. "
                               "Would you like to start the pool "
                               "now?") % default_pool.get_name())
            if not res:
                return False

            # Try to start the pool
            try:
                default_pool.start()
                logging.info("Started pool '%s'", default_pool.get_name())
            except Exception, e:
                return self.err.show_err(_("Could not start storage_pool "
                                      "'%s': %s") %
                                    (default_pool.get_name(), str(e)))
        return True


    ##############
    # Public API #
    ##############

    @staticmethod
    def check_path_search(src, conn, path):
        skip_paths = src.config.get_perms_fix_ignore()
        user, broken_paths = virtinst.VirtualDisk.check_path_search(
            conn.get_backend(), path)

        for p in broken_paths[:]:
            if p in skip_paths:
                broken_paths.remove(p)

        if not broken_paths:
            return

        logging.debug("No search access for dirs: %s", broken_paths)
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

        logging.debug("Attempting to correct permission issues.")
        errors = virtinst.VirtualDisk.fix_path_search_for_user(
            conn.get_backend(), path, user)
        if not errors:
            return

        errmsg = _("Errors were encountered changing permissions for the "
                   "following directories:")
        details = ""
        for path, error in errors.items():
            if path not in broken_paths:
                continue
            details += "%s : %s\n" % (path, error)

        logging.debug("Permission errors:\n%s", details)

        ignore, chkres = src.err.err_chkbox(errmsg, details,
                             _("Don't ask about these directories again."))

        if chkres:
            src.config.add_perms_fix_ignore(errors.keys())

    def reset_state(self):
        self._update_host_space()
        self.widget("config-storage-create").set_active(True)
        self.widget("config-storage-size").set_value(8)
        self.widget("config-storage-entry").set_text("")
        self.widget("config-storage-nosparse").set_active(True)

        fmt = self.conn.get_default_storage_format()
        can_alloc = fmt in ["raw"]
        self.widget("config-storage-nosparse").set_active(can_alloc)
        self.widget("config-storage-nosparse").set_sensitive(can_alloc)
        self.widget("config-storage-nosparse").set_tooltip_text(
            not can_alloc and
            (_("Disk format '%s' does not support full allocation.") % fmt) or
            "")

        storage_tooltip = None

        can_storage = (not self.conn.is_remote() or
                       self.conn.is_storage_capable())
        use_storage = self.widget("config-storage-select")
        storage_area = self.widget("config-storage-box")

        storage_area.set_sensitive(can_storage)
        if not can_storage:
            storage_tooltip = _("Connection does not support storage"
                                " management.")
            use_storage.set_sensitive(True)
        storage_area.set_tooltip_text(storage_tooltip or "")

    def get_default_path(self, name, collidelist=None):
        collidelist = collidelist or []
        pool = self.conn.get_default_pool()

        default_dir = self._get_default_dir()

        def path_exists(p):
            return os.path.exists(p) or p in collidelist

        if not pool:
            # Use old generating method
            origf = os.path.join(default_dir, name + ".img")
            f = origf

            n = 1
            while path_exists(f) and n < 100:
                f = os.path.join(default_dir, name +
                                 "-" + str(n) + ".img")
                n += 1

            if path_exists(f):
                f = origf

            path = f
        else:
            target, ignore, suffix = self._get_ideal_path_info(name)

            # Sanitize collidelist to work with the collision checker
            newcollidelist = []
            for c in collidelist:
                if c and os.path.dirname(c) == pool.get_target_path():
                    newcollidelist.append(os.path.basename(c))

            path = virtinst.StorageVolume.find_free_name(
                pool.get_backend(), name,
                suffix=suffix, collidelist=newcollidelist)

            path = os.path.join(target, path)

        return path

    def is_default_storage(self):
        return self.widget("config-storage-create").get_active()

    def _check_ideal_path(self, path, vmname, collidelist):
        # See if the ideal disk path (/default/pool/vmname.img)
        # exists, and if unused, prompt the use for using it
        conn = self.conn.get_backend()
        ideal = self._get_ideal_path(vmname)
        if ideal in collidelist:
            return path

        do_exist = False
        ret = True
        try:
            do_exist = virtinst.VirtualDisk.path_exists(conn, ideal)
            ret = virtinst.VirtualDisk.path_in_use_by(conn, ideal)
        except:
            logging.exception("Error checking default path usage")

        if not do_exist or ret:
            return path

        do_use = self.err.yes_no(
            _("The following storage already exists, but is not\n"
              "in use by any virtual machine:\n\n%s\n\n"
              "Would you like to reuse this storage?") % ideal)

        if do_use:
            return ideal
        return path

    def validate_storage(self, vmname,
                         path=None, size=None, sparse=None,
                         device="disk", fmt=None, collidelist=None):
        collidelist = collidelist or []
        use_storage = self.widget("config-storage-box").is_sensitive()
        is_default = self.is_default_storage()
        conn = self.conn.get_backend()

        # Validate storage
        if not use_storage:
            return True

        # Make sure default pool is running
        if is_default:
            ret = self._check_default_pool_active()
            if not ret:
                return False

        readonly = False
        if device == virtinst.VirtualDisk.DEVICE_CDROM:
            readonly = True

        try:
            if size is None and sparse is None:
                size = uiutil.spin_get_helper(
                    self.widget("config-storage-size"))
                sparse = (
                    not self.widget("config-storage-nosparse").get_active())
            if path is None:
                if is_default:
                    path = self.get_default_path(vmname, collidelist)
                else:
                    path = self.widget("config-storage-entry").get_text()

            if is_default:
                path = self._check_ideal_path(path, vmname, collidelist)

            if not path and device != "disk":
                return self.err.val_err(_("A storage path must be specified."))

            disk = virtinst.VirtualDisk(conn)
            disk.path = path
            disk.read_only = readonly
            disk.device = device
            disk.set_create_storage(size=size, sparse=sparse,
                                    fmt=fmt or None)

            if not fmt:
                fmt = self.conn.get_default_storage_format()
                if (self.is_default_storage() and
                    disk.get_vol_install() and
                    fmt in disk.get_vol_install().list_formats()):
                    logging.debug("Setting disk format from prefs: %s", fmt)
                    disk.get_vol_install().format = fmt

            disk.validate()
        except Exception, e:
            return self.err.val_err(_("Storage parameter error."), e)

        return disk

    def validate_disk_object(self, disk):
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
        self.emit("browse-clicked", self.widget("config-storage-entry"))

    def _toggle_storage_select(self, src):
        act = src.get_active()
        self.widget("config-storage-browse-box").set_sensitive(act)
        self.emit("storage-toggled", src)

# Copyright (C) 2009, 2013 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import collections

from gi.repository import Gtk
from gi.repository import Pango

import virtinst
from virtinst import Cloner
from virtinst import log
from virtinst import xmlutil

from .lib import uiutil
from .baseclass import vmmGObjectUI
from .asyncjob import vmmAsyncJob
from .storagebrowse import vmmStorageBrowser


def _get_cloneable_msg(diskinfo):
    """Is the passed path even clone-able"""
    if diskinfo.get_cloneable_msg():
        return diskinfo.get_cloneable_msg()
    if diskinfo.disk.is_empty():
        return _("No storage to clone.")


class _StorageInfo:
    """
    Our wrapper class that is close to Cloner _DiskInfo content.
    We track all user choices explicitly in this class, and then
    serialize them into the actual cloner diskinfo once the
    user clicks 'Clone' to complete the process.
    """
    def __init__(self, vm, cloner, diskinfo):
        self._diskinfo = diskinfo
        self._orig_disk = diskinfo.disk
        self._orig_vm_name = vm.get_name()
        self._new_vm_name = cloner.new_guest.name

        self.share_msg = diskinfo.get_share_msg()
        self.cloneable_msg = _get_cloneable_msg(diskinfo)

        self._manual_path = None
        self._generated_path = (diskinfo.new_disk and
                diskinfo.new_disk.get_source_path())
        if not self._generated_path:
            self._reset_generated_path()

        self._is_clone_requested = diskinfo.is_clone_requested()

        if self.share_msg or not self.is_cloneable():
            self._is_clone_requested = False

    def is_cloneable(self):
        return not bool(self.cloneable_msg)
    def is_clone_requested(self):
        return self._is_clone_requested
    def is_share_requested(self):
        return not self._is_clone_requested
    def warn_about_sharing(self):
        return not self.share_msg

    def get_target(self):
        return self._orig_disk.target
    def get_orig_disk_path(self):
        return self._orig_disk.get_source_path()
    def get_new_disk_path(self):
        if self._manual_path:
            return self._manual_path
        return self._generated_path

    def set_clone_requested(self, val):
        self._is_clone_requested = bool(val)
    def set_manual_path(self, val):
        self._manual_path = val
    def set_new_vm_name(self, val):
        if not val or val == self._new_vm_name:
            return
        self._new_vm_name = val
        self._reset_generated_path()

    def _reset_generated_path(self):
        self._generated_path = Cloner.generate_clone_disk_path(
            self._orig_disk.conn,
            self._orig_vm_name,
            self._new_vm_name,
            self._orig_disk.get_source_path())

    def set_values_on_diskinfo(self, diskinfo):
        if not self._is_clone_requested:
            diskinfo.set_share_requested()
            diskinfo.new_disk = None
            return

        diskinfo.set_clone_requested()
        sparse = True
        newpath = self.get_new_disk_path()
        diskinfo.set_new_path(newpath, sparse)


    ###################
    # UI info helpers #
    ###################

    def get_tooltip(self):
        lines = []
        lines.append(_("Disk target: %s") % self.get_target())
        lines.append(_("Original path: %s") % self.get_orig_disk_path())
        if self.get_new_disk_path():
            lines.append(_("New path: %s") % self.get_new_disk_path())
        lines.append("\n")

        if self.share_msg:
            lines.append(_("Storage is safe to share: %(reason)s") % {
                "reason": self.share_msg})
        else:
            lines.append(
                _("Sharing this storage is potentially dangerous."))

        if self.cloneable_msg:
            lines.append(_("Storage is not cloneable: %(reason)s") % {
                "reason": self.cloneable_msg})
        return "\n".join(lines)

    def get_markup(self, vm):
        lines = []

        line = ""
        path = self.get_orig_disk_path()
        if path:
            line += path
        else:
            line += _("No storage.")
        lines.append(line)

        line = ""
        if self.is_share_requested():
            line += _("Share disk with %s") % vm.get_name()
        if self.is_clone_requested():
            line += _("Clone this disk")
            sizelabel = self.get_size_label()
            if sizelabel:
                line += " (%s)" % sizelabel
        if line:
            lines.append(line)

        label = "\n".join(lines)
        markup = "<small>%s</small>" % xmlutil.xml_escape(label)
        return markup

    def get_icon_name(self):
        if self._orig_disk.is_floppy():
            return "media-floppy"
        if self._orig_disk.is_cdrom():
            return "media-optical"
        return "drive-harddisk"

    def get_size_label(self):
        size = self._orig_disk.get_size()
        if not size:
            return ""  # pragma: no cover
        return "%.1f GiB" % float(size)


class vmmCloneVM(vmmGObjectUI):
    @classmethod
    def show_instance(cls, parentobj, vm):
        try:
            # Maintain one dialog per connection
            uri = vm.conn.get_uri()
            if cls._instances is None:
                cls._instances = {}
            if uri not in cls._instances:
                cls._instances[uri] = vmmCloneVM()
            cls._instances[uri].show(parentobj.topwin, vm)
        except Exception as e:  # pragma: no cover
            parentobj.err.show_err(
                    _("Error launching clone dialog: %s") % str(e))

    def __init__(self):
        vmmGObjectUI.__init__(self, "clone.ui", "vmm-clone")
        self.vm = None

        self._storage_list = None
        self._storage_browser = None

        self._storage_dialog = self.widget("vmm-change-storage")
        self._storage_dialog.set_transient_for(self.topwin)

        self.builder.connect_signals({
            "on_clone_delete_event": self._close_cb,
            "on_clone_cancel_clicked": self._close_cb,
            "on_clone_ok_clicked": self._finish_clicked_cb,
            "on_storage_selection_changed": self._storage_selection_changed_cb,
            "on_storage_details_clicked": self._storage_details_clicked_cb,

            # Storage subdialog signals
            "on_vmm_change_storage_delete_event": self._storage_dialog_close_cb,
            "on_change_storage_cancel_clicked": self._storage_dialog_close_cb,
            "on_change_storage_ok_clicked": self._storage_dialog_finish_cb,
            "on_change_storage_doclone_toggled": self._storage_dialog_doclone_toggled_cb,
            "on_change_storage_browse_clicked": self._storage_dialog_browse_cb,
        })
        self.bind_escape_key_close()
        self._cleanup_on_app_close()

        self._init_ui()


    #######################
    # Standard UI methods #
    #######################

    @property
    def conn(self):
        return self.vm and self.vm.conn or None

    def show(self, parent, vm):
        log.debug("Showing clone wizard")
        self._set_vm(vm)
        self._reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.resize(1, 1)
        self.topwin.present()

    def _storage_dialog_close(self):
        self._storage_dialog.hide()
        return 1

    def close(self, ignore1=None, ignore2=None):
        log.debug("Closing clone wizard")
        self._storage_dialog_close()
        self.topwin.hide()

        self._set_vm(None)
        self._storage_list = None
        return 1

    def _vm_removed_cb(self, _conn, vm):
        if self.vm == vm:
            self.close()

    def _set_vm(self, newvm):
        oldvm = self.vm
        if oldvm:
            oldvm.conn.disconnect_by_obj(self)
        if newvm:
            newvm.conn.connect("vm-removed", self._vm_removed_cb)
        self.vm = newvm

    def _cleanup(self):
        self._storage_dialog.destroy()
        self._storage_dialog = None

        if self._storage_browser:
            self._storage_browser.cleanup()
            self._storage_browser = None


    ###########
    # UI init #
    ###########

    def _init_ui(self):
        storage_list = self.widget("storage-list")

        # [disk target, tooltip]
        model = Gtk.ListStore(str, str)
        storage_list.set_model(model)
        storage_list.set_tooltip_column(1)

        cloneCol = Gtk.TreeViewColumn(_("Clone"))
        pathCol = Gtk.TreeViewColumn(_("Storage"))
        pathCol.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
        pathCol.set_expand(True)

        storage_list.append_column(cloneCol)
        storage_list.append_column(pathCol)

        def separator_cb(_model, _iter):
            return _model[_iter][0] == "separator"
        storage_list.set_row_separator_func(separator_cb)

        chkbox = Gtk.CellRendererToggle()
        chkbox.connect('toggled', self._storage_clone_toggled_cb)
        chkimg = Gtk.CellRendererPixbuf()
        chkimg.set_property('stock-size', Gtk.IconSize.MENU)
        cloneCol.pack_start(chkimg, False)
        cloneCol.pack_start(chkbox, False)

        def chk_cell_data_cb(column, cell, model, _iter, data):
            target = model[_iter][0]
            if target == "separator":
                return
            sinfo = self._storage_list[target]
            visible = sinfo.is_cloneable()
            active = sinfo.is_clone_requested()
            _chkimg = column.get_cells()[0]
            _chkbox = column.get_cells()[1]
            _chkbox.set_property('active', active)
            _chkbox.set_property('visible', visible)
            _chkimg.set_property('visible', not visible)
            icon = Gtk.STOCK_INFO
            if sinfo.warn_about_sharing():
                icon = Gtk.STOCK_DIALOG_WARNING
            _chkimg.set_property('stock-id', icon)
            tooltip = sinfo.get_tooltip()
            if tooltip != model[_iter][1]:
                model[_iter][1] = tooltip

        cloneCol.set_cell_data_func(chkbox, chk_cell_data_cb)
        cloneCol.set_cell_data_func(chkimg, chk_cell_data_cb)

        pathtxt = Gtk.CellRendererText()
        pathCol.set_sort_column_id(0)
        pathtxt.set_property("width-chars", 30)
        pathtxt.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        pathimg = Gtk.CellRendererPixbuf()
        pathimg.set_property('stock-size', Gtk.IconSize.MENU)
        pathimg.set_padding(3, 0)
        pathCol.pack_start(pathimg, False)
        pathCol.pack_start(pathtxt, True)

        def path_cb(column, cell, model, _iter, data):
            target = model[_iter][0]
            if target == "separator":
                return
            sinfo = self._storage_list[target]
            _pathimg = column.get_cells()[0]
            _pathtxt = column.get_cells()[1]
            markup = sinfo.get_markup(self.vm)
            _pathtxt.set_property('markup', markup)
            _pathimg.set_property('icon-name', sinfo.get_icon_name())

        pathCol.set_cell_data_func(pathtxt, path_cb)
        pathCol.set_cell_data_func(pathimg, path_cb)


    def _reset_state(self):
        self.widget("clone-cancel").grab_focus()
        self.widget("clone-new-name").set_text("")

        # Populate default clone values
        cloner = self._build_cloner()
        cloner.prepare()
        self.widget("clone-orig-name").set_text(cloner.src_name)
        self.widget("clone-new-name").set_text(cloner.new_guest.name)

        uiutil.set_grid_row_visible(
            self.widget("clone-dest-host"), self.conn.is_remote())
        self.widget("clone-dest-host").set_text(self.conn.get_pretty_desc())

        # Collect info about all the VMs disks
        self._storage_list = collections.OrderedDict()

        for diskinfo in cloner.get_diskinfos():
            sinfo = _StorageInfo(self.vm, cloner, diskinfo)
            self._storage_list[sinfo.get_target()] = sinfo

        self._populate_storage_ui()


    #######################
    # Functional routines #
    #######################

    def _build_cloner(self):
        conn = self.conn.get_backend()
        orig_name = self.vm.get_name()
        new_name = self.widget("clone-new-name").get_text()
        cloner = Cloner(conn, src_name=orig_name)
        if new_name:
            cloner.set_clone_name(new_name)
        return cloner


    #######################
    # Storage UI building #
    #######################

    def _set_paths_from_clone_name(self):
        newname = self.widget("clone-new-name").get_text()
        for sinfo in list(self._storage_list.values()):
            sinfo.set_new_vm_name(newname)

    def _populate_storage_ui(self):
        """
        Fill in the storage UI from the collected StorageInfo classes
        """
        model = self.widget("storage-list").get_model()
        model.clear()
        for sinfo in self._storage_list.values():
            model.append([sinfo.get_target(), sinfo.get_tooltip()])
            model.append(["separator", None])

    def _storage_clone_toggled_cb(self, src, treepath):
        model = self.widget("storage-list").get_model()
        row = model[treepath]
        target = row[0]
        sinfo = self._storage_list[target]
        active = not src.get_property("active")
        sinfo.set_clone_requested(active)
        model.emit("row-changed", row.path, row.iter)


    ###########################
    # Storage window handling #
    ###########################

    def _show_storage_window(self):
        tgt = uiutil.get_list_selection(self.widget("storage-list"))
        sinfo = self._storage_list[tgt]

        # If storage paths are dependent on manually entered clone name,
        # make sure they are up to date
        self._set_paths_from_clone_name()

        orig = sinfo.get_orig_disk_path()
        new = sinfo.get_new_disk_path()
        size = sinfo.get_size_label()
        can_clone = sinfo.is_cloneable()
        do_clone = sinfo.is_clone_requested()

        self.widget("change-storage-doclone").set_active(True)
        self.widget("change-storage-doclone").toggled()
        self.widget("change-storage-orig").set_text(orig)
        self.widget("change-storage-target").set_text(tgt)
        self.widget("change-storage-size").set_text(size or "-")
        self.widget("change-storage-doclone").set_active(do_clone)

        self.widget("change-storage-new").set_text(new or "")
        self.widget("change-storage-doclone").set_sensitive(can_clone)

        self.widget("vmm-change-storage").show_all()


    def _storage_dialog_finish(self):
        target = self.widget("change-storage-target").get_text()
        sinfo = self._storage_list[target]

        # Sync 'do clone' checkbox, and main dialog combo
        do_clone = self.widget("change-storage-doclone").get_active()
        sinfo.set_clone_requested(do_clone)

        if not do_clone:
            self._storage_dialog_close()
            return

        new_path = self.widget("change-storage-new").get_text()

        if virtinst.DeviceDisk.path_definitely_exists(
                self.vm.conn.get_backend(), new_path):
            text1 = _("Cloning will overwrite the existing file")
            text2 = _("Using an existing image will overwrite "
                      "the path during the clone process. Are "
                      "you sure you want to use this path?")
            res = self.err.yes_no(text1, text2)
            if not res:
                return

        sinfo.set_manual_path(new_path)
        self._storage_dialog_close()


    ###################
    # Finish routines #
    ###################

    def _validate(self, cloner):
        new_paths = []
        warn_str = ""
        for sinfo in self._storage_list.values():
            if sinfo.is_clone_requested():
                new_paths.append(sinfo.get_new_disk_path())
                continue
            if not sinfo.warn_about_sharing():
                continue
            warn_str += "%s: %s\n" % (
                    sinfo.get_target(), sinfo.get_orig_disk_path())

        if warn_str:
            res = self.err.ok_cancel(
                _("Sharing storage may cause data to be overwritten."),
                _("The following disk devices will be shared with %(vmname)s:"
                  "\n\n%(pathlist)s\n"
                  "Running the new guest could overwrite data in these "
                  "disk images.") % {
                      "vmname": self.vm.get_name(), "pathlist": warn_str})
            if not res:
                return False

        for diskinfo in cloner.get_diskinfos():
            diskinfo.raise_error()

    def _finish_cb(self, error, details, conn, cloner):
        self.reset_finish_cursor()

        if error is not None:
            error = (_("Error creating virtual machine clone '%(vm)s': "
                       "%(error)s") % {
                     "vm": cloner.new_guest.name,
                     "error": error,
                     })
            self.err.show_err(error, details=details)
            return

        conn.schedule_priority_tick(pollvm=True)
        self.close()

    def _async_clone(self, asyncjob, cloner):
        meter = asyncjob.get_meter()

        refresh_pools = []
        for diskinfo in cloner.get_nonshare_diskinfos():
            disk = diskinfo.new_disk
            pool = disk.get_parent_pool()
            if not pool:
                continue

            poolname = pool.name()
            if poolname not in refresh_pools:
                refresh_pools.append(poolname)

        cloner.start_duplicate(meter)

        for poolname in refresh_pools:
            try:
                pool = self.conn.get_pool_by_name(poolname)
                self.idle_add(pool.refresh)
            except Exception:  # pragma: no cover
                log.debug("Error looking up pool=%s for refresh after "
                        "VM clone.", poolname, exc_info=True)

    def _build_final_cloner(self):
        self._set_paths_from_clone_name()

        cloner = self._build_cloner()
        for diskinfo in cloner.get_diskinfos():
            target = diskinfo.disk.target
            sinfo = self._storage_list[target]
            sinfo.set_values_on_diskinfo(diskinfo)

        cloner.prepare()
        for diskinfo in cloner.get_diskinfos():
            diskinfo.raise_error()

        if self._validate(cloner) is False:
            return
        return cloner

    def _finish(self):
        try:
            cloner = self._build_final_cloner()
            if not cloner:
                return
        except Exception as e:
            msg = _("Error with clone settings: %s") % str(e)
            return self.err.show_err(msg)

        self.set_finish_cursor()

        title = (_("Creating virtual machine clone '%s'") %
                 cloner.new_guest.name)

        text = title
        if cloner.get_nonshare_diskinfos():
            text = (_("Creating virtual machine clone '%s' and selected "
                      "storage (this may take a while)") %
                    cloner.new_guest.name)

        progWin = vmmAsyncJob(self._async_clone, [cloner],
                              self._finish_cb, [self.conn, cloner],
                              title, text, self.topwin)
        progWin.run()


    ################
    # UI listeners #
    ################

    def _close_cb(self, src, event=None):
        return self.close()
    def _finish_clicked_cb(self, src):
        return self._finish()

    def _storage_selection_changed_cb(self, src):
        row = uiutil.get_list_selected_row(self.widget("storage-list"))
        self.widget("storage-details-button").set_sensitive(bool(row))

    def _storage_details_clicked_cb(self, src):
        self._show_storage_window()

    def _storage_dialog_doclone_toggled_cb(self, src):
        do_clone = src.get_active()
        self.widget("change-storage-new").set_sensitive(do_clone)
        self.widget("change-storage-browse").set_sensitive(do_clone)

    def _storage_dialog_close_cb(self, src, event=None):
        return self._storage_dialog_close()
    def _storage_dialog_finish_cb(self, src):
        self._storage_dialog_finish()

    def _storage_dialog_browse_cb(self, ignore):
        def callback(src_ignore, txt):
            self.widget("change-storage-new").set_text(txt)

        if self._storage_browser is None:
            self._storage_browser = vmmStorageBrowser(self.conn)
            self._storage_browser.set_finish_cb(callback)

        self._storage_browser.show(self.topwin)

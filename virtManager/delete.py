# Copyright (C) 2009, 2012-2014 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import stat
import traceback

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Pango

import virtinst
from virtinst import log
from virtinst import xmlutil

from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI
from .lib import uiutil

STORAGE_ROW_CONFIRM = 0
STORAGE_ROW_CANT_DELETE = 1
STORAGE_ROW_PATH = 2
STORAGE_ROW_TARGET = 3
STORAGE_ROW_ICON_SHOW = 4
STORAGE_ROW_ICON = 5
STORAGE_ROW_ICON_SIZE = 6
STORAGE_ROW_TOOLTIP = 7


class vmmDeleteDialog(vmmGObjectUI):

    disk = None
    @classmethod
    def show_instance(cls, parentobj, vm):
        try:
            if not cls._instance:
                cls._instance = vmmDeleteDialog()
            cls._instance.show(parentobj.topwin, vm)
        except Exception as e:
            parentobj.err.show_err(
                    _("Error launching delete dialog: %s") % str(e))

    def __init__(self):
        vmmGObjectUI.__init__(self, "delete.ui", "vmm-delete")
        self.vm = None

        self.builder.connect_signals({
            "on_vmm_delete_delete_event": self.close,
            "on_delete_cancel_clicked": self.close,
            "on_delete_ok_clicked": self._finish_clicked_cb,
            "on_delete_remove_storage_toggled": self._toggle_remove_storage,
        })
        self.bind_escape_key_close()
        self._cleanup_on_app_close()

        self._init_state()

    def _init_state(self):
        blue = Gdk.Color.parse("#0072A8")[1]
        self.widget("header").modify_bg(Gtk.StateType.NORMAL, blue)

        _prepare_storage_list(self.widget("delete-storage-list"))

    def show(self, parent, vm):
        log.debug("Showing delete wizard")
        self._set_vm(vm)
        self._reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        log.debug("Closing delete wizard")
        self.topwin.hide()
        self._set_vm(None)
        return 1

    def set_disk(self, disk):
        self.disk = disk

    def _cleanup(self):
        pass



    ##########################
    # Initialization methods #
    ##########################

    def _set_vm(self, newvm):
        oldvm = self.vm
        if oldvm:
            oldvm.conn.disconnect_by_obj(self)
        if newvm:
            newvm.conn.connect("vm-removed", self._vm_removed)
        self.vm = newvm

    def _reset_state(self):
        # Set VM name or disk.target in title'
        if self.disk:
            text = self.disk.target
        else:
            text = self.vm.get_name()

        title_str = ("<span size='large' color='white'>%s '%s'</span>" %
                     (_("Delete"), xmlutil.xml_escape(text)))
        self.widget("header-label").set_markup(title_str)

        self.topwin.resize(1, 1)
        self.widget("delete-cancel").grab_focus()

        # Show warning message if VM is running
        vm_active = self.vm.is_active()
        uiutil.set_grid_row_visible(
            self.widget("delete-warn-running-vm-box"), vm_active)

        # Enable storage removal by default
        self.widget("delete-remove-storage").set_active(True)
        self.widget("delete-remove-storage").toggled()
        if self.disk:
            diskdatas =[_DiskData.from_disk(self.disk),]
        else:
            diskdatas = _build_diskdata_for_vm(self.vm)
        _populate_storage_list(self.widget("delete-storage-list"),
                               self.vm, self.vm.conn, diskdatas)


    ################
    # UI listeners #
    ################

    def _finish_clicked_cb(self, src):
        self._finish()

    def _vm_removed(self, _conn, connkey):
        if self.vm.get_connkey() == connkey:
            self.close()

    def _toggle_remove_storage(self, src):
        dodel = src.get_active()
        uiutil.set_grid_row_visible(
            self.widget("delete-storage-scroll"), dodel)


    #########################
    # finish/delete methods #
    #########################

    def _get_paths_to_delete(self):
        del_list = self.widget("delete-storage-list")
        model = del_list.get_model()

        paths = []
        if self.widget("delete-remove-storage").get_active():
            for row in model:
                if (not row[STORAGE_ROW_CANT_DELETE] and
                    row[STORAGE_ROW_CONFIRM]):
                    paths.append(row[STORAGE_ROW_PATH])
        return paths

    def _delete_finished_cb(self, error, details):
        self.reset_finish_cursor()

        if error is not None:
            self.err.show_err(error, details=details)

        self.close()

    def _finish(self):
        devs = self._get_paths_to_delete()

        if devs:
            title = _("Are you sure you want to delete the storage?")
            message = (_("The following paths will be deleted:\n\n%s") %
                       "\n".join(devs))
            ret = self.err.chkbox_helper(
                self.config.get_confirm_delstorage,
                self.config.set_confirm_delstorage,
                text1=title, text2=message)
            if not ret:
                return

        self.set_finish_cursor()

        if self.disk:
            title = _("Deleting the selected storage")
            text = _('%s') % self.disk.target
        else:
            title = _("Deleting virtual machine '%s'") % self.vm.get_name()
            text = title
            if devs:
                text = title + _(" and selected storage (this may take a while)")


        progWin = vmmAsyncJob(self._async_delete, [self.vm, devs],
                              self._delete_finished_cb, [],
                              title, text, self.topwin)
        progWin.run()
        self._set_vm(None)

    def _async_delete(self, asyncjob, vm, paths):
        storage_errors = []
        details = ""
        undefine = vm.is_persistent()

        try:
            if vm.is_active():
                log.debug("Forcing VM '%s' power off.", vm.get_name())
                vm.destroy()

            conn = vm.conn.get_backend()
            meter = asyncjob.get_meter()
            if not paths and self.disk:
                vm.remove_device(self.disk)

            for path in paths:
                try:
                    log.debug("Deleting path: %s", path)
                    meter.start(text=_("Deleting path '%s'") % path)
                    self._async_delete_dev(vm, conn, path, meter)
                except Exception as e:
                    storage_errors.append((str(e),
                                          "".join(traceback.format_exc())))
                meter.end(0)

            if undefine and not self.disk:
                log.debug("Removing VM '%s'", vm.get_name())
                vm.delete()

        except Exception as e:
            error = (_("Error deleting virtual machine '%s': %s") %
                      (vm.get_name(), str(e)))
            details = "".join(traceback.format_exc())


        storage_errstr = ""
        for errinfo in storage_errors:
            storage_errstr += "%s\n%s\n" % (errinfo[0], errinfo[1])

        if not storage_errstr and not details:
            return

        # We had extra storage errors. If there was another error message,
        # errors to it. Otherwise, build the main error around them.
        if details:
            details += "\n\n"
            details += _("Additionally, there were errors removing"
                                    " certain storage devices: \n")
            details += storage_errstr
        else:
            error = _("Errors encountered while removing certain "
                               "storage devices.")
            details = storage_errstr

        if error:
            asyncjob.set_error(error, details)
        vm.conn.schedule_priority_tick(pollvm=True)

    def _async_delete_dev(self, vm, conn, path, ignore):
        vol = None

        try:
            vol = conn.storageVolLookupByPath(path)
        except Exception:
            log.debug("Path '%s' is not managed. Deleting locally", path)

        if vol:
            vol.delete(0)
        else:
            os.unlink(path)
        self._async_delete_xmldev(vm, path, ignore)

    def _async_delete_xmldev(self, vm, path, ignore):
        for d in vm.xmlobj.devices.disk:
            if d.path == path:
                dev = d
                break
        vm.remove_device(dev)


###################
# UI init helpers #
###################

class _DiskData:
    """
    Helper class to contain all info we need to decide whether we
    should default to deleting a path
    """
    @staticmethod
    def from_disk(disk):
        """
        Build _DiskData from a DeviceDisk object
        """
        return _DiskData(
                disk.target,
                disk.path,
                disk.read_only,
                disk.shareable,
                disk.device in ["cdrom", "floppy"])

    def __init__(self, label, path, ro, shared, is_media):
        self.label = label
        self.path = path
        self.ro = ro
        self.shared = shared
        self.is_media = is_media


def _build_diskdata_for_vm(vm):
    """
    Return a list of _DiskData for all VM resources the app attempts to delete
    """
    diskdatas = []
    for disk in vm.xmlobj.devices.disk:
        diskdatas.append(_DiskData.from_disk(disk))

    diskdatas.append(
            _DiskData("kernel", vm.get_xmlobj().os.kernel, True, False, True))
    diskdatas.append(
            _DiskData("initrd", vm.get_xmlobj().os.initrd, True, False, True))
    diskdatas.append(
            _DiskData("dtb", vm.get_xmlobj().os.dtb, True, False, True))

    return diskdatas


def _populate_storage_list(storage_list, vm, conn, diskdatas):
    """
    Fill in the storage list UI from the passed list of _DiskData
    """
    model = storage_list.get_model()
    model.clear()

    for diskdata in diskdatas:
        if not diskdata.path:
            continue

        # There are a few pieces here
        # 1) Can we even delete the storage? If not, make the checkbox
        #    inconsistent. self.can_delete decides this for us, and if
        #    we can't delete, gives us a nice message to show the user
        #    for that row.
        #
        # 2) If we can delete, do we want to delete this storage by
        #    default? Reasons not to, are if the storage is marked
        #    readonly or shareable, or is in use by another VM.

        default = False
        definfo = None
        vol = conn.get_vol_by_path(diskdata.path)
        can_del, delinfo = _can_delete(conn, vol, diskdata.path)

        if can_del:
            default, definfo = _do_we_default(conn, vm.get_name(), vol,
                                              diskdata)

        info = None
        if not can_del:
            info = delinfo
        elif not default:
            info = definfo

        icon = Gtk.STOCK_DIALOG_WARNING
        icon_size = Gtk.IconSize.LARGE_TOOLBAR

        row = [default, not can_del, diskdata.path, diskdata.label,
               bool(info), icon, icon_size, info]
        model.append(row)


def _prepare_storage_list(storage_list):
    # Checkbox, deleteable?, storage path, target (hda), icon stock,
    # icon size, tooltip
    model = Gtk.ListStore(bool, bool, str, str, bool, str, int, str)
    storage_list.set_model(model)
    storage_list.set_tooltip_column(STORAGE_ROW_TOOLTIP)

    confirmCol = Gtk.TreeViewColumn()
    targetCol = Gtk.TreeViewColumn(_("Target"))
    infoCol = Gtk.TreeViewColumn()
    pathCol = Gtk.TreeViewColumn(_("Storage Path"))
    pathCol.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
    pathCol.set_expand(True)

    storage_list.append_column(confirmCol)
    storage_list.append_column(pathCol)
    storage_list.append_column(targetCol)
    storage_list.append_column(infoCol)

    chkbox = Gtk.CellRendererToggle()
    chkbox.connect('toggled', _storage_item_toggled, storage_list)
    confirmCol.pack_start(chkbox, False)
    confirmCol.add_attribute(chkbox, 'active', STORAGE_ROW_CONFIRM)
    confirmCol.add_attribute(chkbox, 'inconsistent',
                             STORAGE_ROW_CANT_DELETE)
    confirmCol.set_sort_column_id(STORAGE_ROW_CANT_DELETE)

    path_txt = Gtk.CellRendererText()
    pathCol.pack_start(path_txt, True)
    pathCol.add_attribute(path_txt, 'text', STORAGE_ROW_PATH)
    pathCol.set_sort_column_id(STORAGE_ROW_PATH)
    path_txt.set_property("width-chars", 50)
    path_txt.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)

    target_txt = Gtk.CellRendererText()
    targetCol.pack_start(target_txt, False)
    targetCol.add_attribute(target_txt, 'text', STORAGE_ROW_TARGET)
    targetCol.set_sort_column_id(STORAGE_ROW_TARGET)

    info_img = Gtk.CellRendererPixbuf()
    infoCol.pack_start(info_img, False)
    infoCol.add_attribute(info_img, 'visible', STORAGE_ROW_ICON_SHOW)
    infoCol.add_attribute(info_img, 'stock-id', STORAGE_ROW_ICON)
    infoCol.add_attribute(info_img, 'stock-size', STORAGE_ROW_ICON_SIZE)
    infoCol.set_sort_column_id(STORAGE_ROW_ICON)


def _storage_item_toggled(src, index, storage_list):
    active = src.get_active()

    model = storage_list.get_model()
    model[index][STORAGE_ROW_CONFIRM] = not active


def _can_delete(conn, vol, path):
    """Is the passed path even deleteable"""
    ret = True
    msg = None

    if vol:
        # Managed storage
        pool_type = vol.get_parent_pool().get_type()
        if pool_type == virtinst.StoragePool.TYPE_ISCSI:
            msg = _("Cannot delete iscsi share.")
        elif pool_type == virtinst.StoragePool.TYPE_SCSI:
            msg = _("Cannot delete SCSI device.")
    else:
        if conn.is_remote():
            msg = _("Cannot delete unmanaged remote storage.")
        elif not os.path.exists(path):
            msg = _("Path does not exist.")
        elif not os.access(os.path.dirname(path), os.W_OK):
            msg = _("No write access to parent directory.")
        elif stat.S_ISBLK(os.stat(path)[stat.ST_MODE]):
            msg = _("Cannot delete unmanaged block device.")

    if msg:
        ret = False

    return (ret, msg)


def _do_we_default(conn, vm_name, vol, diskdata):
    """ Returns (do we delete by default?, info string if not)"""
    info = ""

    def append_str(str1, str2, delim="\n"):
        if not str2:
            return str1
        if str1:
            str1 += delim
        str1 += str2
        return str1

    if diskdata.ro:
        info = append_str(info, _("Storage is read-only."))
    elif not vol and not os.access(diskdata.path, os.W_OK):
        info = append_str(info, _("No write access to path."))

    if diskdata.shared:
        info = append_str(info, _("Storage is marked as shareable."))

    if not info and diskdata.is_media:
        info = append_str(info, _("Storage is a media device."))

    try:
        names = virtinst.DeviceDisk.path_in_use_by(conn.get_backend(),
                diskdata.path)

        if len(names) > 1:
            namestr = ""
            names.remove(vm_name)
            for name in names:
                namestr = append_str(namestr, name, delim="\n- ")
            info = append_str(info, _("Storage is in use by the following "
                                      "virtual machines:\n- %s " % namestr))
    except Exception as e:
        log.exception("Failed checking disk conflict: %s", str(e))

    return (not info, info)

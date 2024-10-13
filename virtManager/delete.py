# Copyright (C) 2009, 2012-2014 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import stat
import traceback

from gi.repository import Gtk
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


class _vmmDeleteBase(vmmGObjectUI):
    """
    Base class for both types of VM/device storage deleting wizards
    """
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

        self.topwin.set_title(self._get_dialog_title())
        self._init_state()


    def _init_state(self):
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
            newvm.conn.connect("vm-removed", self._vm_removed_cb)
        self.vm = newvm

    def _reset_state(self):
        # Set VM name or disk.target in title'
        text = self._get_dialog_text()

        title_str = ("<span size='large'>%s</span>" %
                     xmlutil.xml_escape(text))
        self.widget("header-label").set_markup(title_str)

        self.topwin.resize(1, 1)
        self.widget("delete-cancel").grab_focus()

        # Show warning message if VM is running
        vm_active = self._vm_active_status()
        uiutil.set_grid_row_visible(
            self.widget("delete-warn-running-vm-box"), vm_active)

        # Enable storage removal by default
        remove_storage_default = self._get_remove_storage_default()
        self.widget("delete-remove-storage").set_active(remove_storage_default)
        self.widget("delete-remove-storage").toggled()
        diskdatas = self._get_disk_datas()
        _populate_storage_list(self.widget("delete-storage-list"),
                               self.vm, self.vm.conn, diskdatas)


    ################
    # UI listeners #
    ################

    def _finish_clicked_cb(self, src):
        self._finish()

    def _vm_removed_cb(self, _conn, vm):
        if self.vm == vm:
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
        paths = self._get_paths_to_delete()

        if paths:
            title = _("Are you sure you want to delete the storage?")
            message = (_("The following paths will be deleted:\n\n%s") %
                       "\n".join(paths))
            ret = self.err.chkbox_helper(
                self.config.get_confirm_delstorage,
                self.config.set_confirm_delstorage,
                text1=title, text2=message)
            if not ret:
                return

        self.set_finish_cursor()

        if not self._remove_device(paths):
            # Don't delete storage if device removal failed
            self._delete_finished_cb(None, None)
            return

        title, text = self._get_progress_text(paths)

        progWin = vmmAsyncJob(self._async_delete, [self.vm, paths],
                              self._delete_finished_cb, [],
                              title, text, self.topwin)
        progWin.run()
        self._set_vm(None)

    def _async_delete(self, asyncjob, vm, paths):
        errdata = None
        storage_errors = []

        try:
            self._destroy_vm(vm)

            conn = vm.conn.get_backend()
            meter = asyncjob.get_meter()
            storage_errors = self._async_delete_paths(paths, conn, meter)

            self._delete_vm(vm)
            vm.conn.schedule_priority_tick(pollvm=True)
        except Exception as e:  # pragma: no cover
            errdata = (
                 (_("Error deleting virtual machine '%(vm)s': %(error)s") %
                   {"vm": vm.get_name(), "error": str(e)}),
                 "".join(traceback.format_exc()))

        if not storage_errors and not errdata:
            return

        storage_errstr = ""
        for errinfo in storage_errors:
            storage_errstr += "%s\n%s\n" % (errinfo[0], errinfo[1])

        # We had extra storage errors. If there was another error message,
        # errors to it. Otherwise, build the main error around them.
        if errdata:  # pragma: no cover
            error, details = errdata
            details += "\n\n"
            details += _("Additionally, there were errors removing"
                         " certain storage devices: \n")
            details += storage_errstr
        else:
            error = _("Errors encountered while removing certain "
                      "storage devices.")
            details = storage_errstr

        asyncjob.set_error(error, details)

    def _async_delete_paths(self, paths, conn, meter):
        storage_errors = []
        for path in paths:
            try:
                log.debug("Deleting path: %s", path)
                meter.start(_("Deleting path '%s'") % path, None)
                self._async_delete_path(conn, path, meter)
            except Exception as e:
                storage_errors.append((str(e),
                                          "".join(traceback.format_exc())))
            meter.end()
        return storage_errors

    def _async_delete_path(self, conn, path, ignore):
        try:
            vol = conn.storageVolLookupByPath(path)
        except Exception:
            vol = None
            log.debug("Path '%s' is not managed. Deleting locally", path)

        if vol:
            vol.delete(0)
        else:
            os.unlink(path)


    ################
    # Subclass API #
    ################

    def _get_dialog_title(self):
        raise NotImplementedError
    def _get_dialog_text(self):
        raise NotImplementedError
    def _get_progress_text(self, paths):
        raise NotImplementedError
    def _get_disk_datas(self):
        raise NotImplementedError
    def _vm_active_status(self):
        raise NotImplementedError
    def _delete_vm(self, vm):
        raise NotImplementedError
    def _remove_device(self, paths):
        raise NotImplementedError
    def _destroy_vm(self, vm):
        raise NotImplementedError
    def _get_remove_storage_default(self):
        raise NotImplementedError


class vmmDeleteDialog(_vmmDeleteBase):
    """
    Dialog for deleting a VM and optionally its storage
    """
    @classmethod
    def show_instance(cls, parentobj, vm):
        try:
            if not cls._instance:
                cls._instance = vmmDeleteDialog()
            cls._instance.show(parentobj.topwin, vm)
        except Exception as e:  # pragma: no cover
            parentobj.err.show_err(
                    _("Error launching delete dialog: %s") % str(e))

    def _get_dialog_title(self):
        return _("Delete Virtual Machine")

    def _get_dialog_text(self):
        return _("Delete '%(vmname)s'") % {"vmname": self.vm.get_name()}

    def _get_progress_text(self, paths):
        if paths:
            title = _("Deleting virtual machine '%s' and selected storage "
                      "(this may take a while)") % self.vm.get_name()
            text = title
        else:
            title = _("Deleting virtual machine '%s'") % self.vm.get_name()
            text = title
        return [title, text]

    def _get_remove_storage_default(self):
        return True

    def _get_disk_datas(self):
        return _build_diskdata_for_vm(self.vm)

    def _vm_active_status(self):
        vm_active = self.vm.is_active()
        return vm_active

    def _remove_device(self, paths):
        dummy = paths
        return True

    def _delete_vm(self, vm):
        if vm.is_persistent():
            log.debug("Removing VM '%s'", vm.get_name())
            vm.delete()

    def _destroy_vm(self, vm):
        if vm.is_active():
            log.debug("Forcing VM '%s' power off.", vm.get_name())
            vm.destroy()


class vmmDeleteStorage(_vmmDeleteBase):
    """
    Dialog for removing a disk device from a VM and optionally deleting
    its storage
    """
    @staticmethod
    def remove_devobj_internal(vm, err, devobj, deleting_storage=False):
        log.debug("Removing device: %s", devobj)

        # Define the change
        try:
            vm.remove_device(devobj)
        except Exception as e:  # pragma: no cover
            err.show_err(_("Error Removing Device: %s") % str(e))
            return

        # Try to hot remove
        detach_err = ()
        try:
            vm.detach_device(devobj)
        except Exception as e:
            log.debug("Device could not be hotUNplugged: %s", str(e))
            detach_err = (str(e), "".join(traceback.format_exc()))

        if not detach_err:
            return True

        msg = _("This change will take effect after the next guest shutdown.")
        if deleting_storage:
            msg += " "
            msg += _("Storage will not be deleted.")

        err.show_err(
            _("Device could not be removed from the running machine"),
            details=(detach_err[0] + "\n\n" + detach_err[1]), text2=msg,
            buttons=Gtk.ButtonsType.OK,
            dialog_type=Gtk.MessageType.INFO)

    def __init__(self, disk):
        _vmmDeleteBase.__init__(self)
        self.disk = disk

    def _get_dialog_title(self):
        return _("Remove Disk Device")

    def _get_dialog_text(self):
        return _("Remove disk device '%(target)s'") % {
                "target": self.disk.target}

    def _get_progress_text(self, paths):
        if paths:
            title = _("Removing disk device '%s' and selected storage "
                      "(this may take a while)") % self.disk.target
        else:
            title = _("Removing disk device '%s'") % self.disk.target
        text = title
        return [title, text]

    def _get_remove_storage_default(self):
        return False

    def _get_disk_datas(self):
        return [_DiskData.from_disk(self.disk)]

    def _vm_active_status(self):
        return False

    def _remove_device(self, paths):
        deleting_storage = bool(paths)
        return vmmDeleteStorage.remove_devobj_internal(
                self.vm, self.err, self.disk,
                deleting_storage=deleting_storage)

    def _delete_vm(self, vm):
        pass

    def _destroy_vm(self, vm):
        pass


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
                disk.get_source_path(),
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

        icon = "dialog-warning"
        icon_size = Gtk.IconSize.LARGE_TOOLBAR

        row = [default, not can_del, diskdata.path, diskdata.label,
               bool(info), icon, icon_size, info]
        model.append(row)


def _prepare_storage_list(storage_list):
    # Checkbox, deletable?, storage path, target (hda), icon name,
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
    def sensitive_cb(column, cell, model, _iter, data):
        row = model[_iter]
        inconsistent = row[STORAGE_ROW_CANT_DELETE]
        sensitive = not inconsistent
        active = row[STORAGE_ROW_CONFIRM]
        chk = column.get_cells()[0]
        chk.set_property('inconsistent', inconsistent)
        chk.set_property('active', active)
        chk.set_property('sensitive', sensitive)
    confirmCol.set_cell_data_func(chkbox, sensitive_cb)
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
    infoCol.add_attribute(info_img, 'icon-name', STORAGE_ROW_ICON)
    infoCol.add_attribute(info_img, 'stock-size', STORAGE_ROW_ICON_SIZE)
    infoCol.set_sort_column_id(STORAGE_ROW_ICON)


def _storage_item_toggled(src, index, storage_list):
    active = src.get_active()

    model = storage_list.get_model()
    model[index][STORAGE_ROW_CONFIRM] = not active


def _can_delete(conn, vol, path):
    """Is the passed path even deletable"""
    msg = None

    if vol:
        # Managed storage
        pool_type = vol.get_parent_pool().get_type()
        if pool_type == virtinst.StoragePool.TYPE_ISCSI:
            msg = _("Cannot delete iSCSI share.")  # pragma: no cover
        elif pool_type == virtinst.StoragePool.TYPE_SCSI:
            msg = _("Cannot delete SCSI device.")  # pragma: no cover
    else:
        if conn.is_remote():
            msg = _("Cannot delete unmanaged remote storage.")
        elif not os.path.exists(path):
            msg = _("Path does not exist.")
        elif not os.access(os.path.dirname(path), os.W_OK):
            msg = _("No write access to parent directory.")
        elif stat.S_ISBLK(os.stat(path)[stat.ST_MODE]):  # pragma: no cover
            msg = _("Cannot delete unmanaged block device.")

    can_delete = bool(not msg)
    return (can_delete, msg)


def _do_we_default(conn, vm_name, vol, diskdata):
    """ Returns (do we delete by default?, info string if not)"""
    info = []

    if diskdata.ro:
        info.append(_("Storage is read-only."))
    elif not vol and not os.access(diskdata.path, os.W_OK):
        info.append(_("No write access to path."))

    if diskdata.shared:
        info.append(_("Storage is marked as shareable."))

    if not info and diskdata.is_media:
        info.append(_("Storage is a media device."))

    try:
        names = virtinst.DeviceDisk.path_in_use_by(conn.get_backend(),
                diskdata.path)

        if len(names) > 1:
            names.remove(vm_name)
            namestr = "\n- ".join(names)
            msg = _("Storage is in use by the following virtual machines")
            msg += "\n- " + namestr
            info.append(msg)
    except Exception as e:  # pragma: no cover
        log.exception("Failed checking disk conflict: %s", str(e))
        info.append(_("Failed to check disk usage conflict."))

    infostr = "\n".join(info)
    do_default = bool(not infostr)
    return (do_default, infostr)

#
# Copyright (C) 2009 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
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

import gtk

import os
import stat
import traceback
import logging

import virtinst

from virtManager import util
from virtManager.baseclass import vmmGObjectUI
from virtManager.asyncjob import vmmAsyncJob

STORAGE_ROW_CONFIRM = 0
STORAGE_ROW_CANT_DELETE = 1
STORAGE_ROW_PATH = 2
STORAGE_ROW_TARGET = 3
STORAGE_ROW_ICON_SHOW = 4
STORAGE_ROW_ICON = 5
STORAGE_ROW_ICON_SIZE = 6
STORAGE_ROW_TOOLTIP = 7

class vmmDeleteDialog(vmmGObjectUI):
    def __init__(self):
        vmmGObjectUI.__init__(self, "vmm-delete.ui", "vmm-delete")
        self.vm = None
        self.conn = None

        self.window.connect_signals({
            "on_vmm_delete_delete_event" : self.close,
            "on_delete_cancel_clicked" : self.close,
            "on_delete_ok_clicked" : self.finish,
            "on_delete_remove_storage_toggled" : self.toggle_remove_storage,
        })
        self.bind_escape_key_close()

        image = gtk.image_new_from_icon_name("vm_delete_wizard",
                                             gtk.ICON_SIZE_DIALOG)
        image.show()
        self.widget("icon-box").pack_end(image, False)

        prepare_storage_list(self.widget("delete-storage-list"))

    def toggle_remove_storage(self, src):
        dodel = src.get_active()
        self.widget("delete-storage-list").set_sensitive(dodel)


    def show(self, vm, parent):
        logging.debug("Showing delete wizard")
        self.vm = vm
        self.conn = vm.conn

        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing delete wizard")
        self.topwin.hide()
        self.vm = None
        self.conn = None
        return 1

    def _cleanup(self):
        self.close()

        self.vm = None
        self.conn = None

    def reset_state(self):

        # Set VM name in title'
        title_str = ("<span size='x-large'>%s '%s'</span>" %
                     (_("Delete"), util.xml_escape(self.vm.get_name())))
        self.widget("delete-main-label").set_markup(title_str)

        self.widget("delete-cancel").grab_focus()

        # Disable storage removal by default
        self.widget("delete-remove-storage").set_active(False)
        self.widget("delete-remove-storage").toggled()

        populate_storage_list(self.widget("delete-storage-list"),
                              self.vm, self.conn)

    def get_config_format(self):
        format_combo = self.widget("vol-format")
        model = format_combo.get_model()
        if format_combo.get_active_iter() != None:
            model = format_combo.get_model()
            return model.get_value(format_combo.get_active_iter(), 0)
        return None

    def get_paths_to_delete(self):
        del_list = self.widget("delete-storage-list")
        model = del_list.get_model()

        paths = []
        if self.widget("delete-remove-storage").get_active():
            for row in model:
                if (not row[STORAGE_ROW_CANT_DELETE] and
                    row[STORAGE_ROW_CONFIRM]):
                    paths.append(row[STORAGE_ROW_PATH])
        return paths

    def finish(self, src_ignore):
        devs = self.get_paths_to_delete()

        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        title = _("Deleting virtual machine '%s'") % self.vm.get_name()
        text = title
        if devs:
            text = title + _(" and selected storage (this may take a while)")

        progWin = vmmAsyncJob(self._async_delete, [devs],
                              title, text, self.topwin)
        error, details = progWin.run()

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))
        conn = self.conn

        if error is not None:
            self.err.show_err(error, details=details)

        conn.tick(noStatsUpdate=True)

        self.close()

    def _async_delete(self, asyncjob, paths):
        newconn = None
        storage_errors = []
        details = ""

        try:
            # Open a seperate connection to install on since this is async
            logging.debug("Threading off connection to delete vol.")
            newconn = util.dup_conn(self.conn).vmm
            meter = asyncjob.get_meter()

            for path in paths:
                try:
                    logging.debug("Deleting path: %s", path)
                    meter.start(text=_("Deleting path '%s'") % path)
                    self._async_delete_path(newconn, path, meter)
                except Exception, e:
                    storage_errors.append((str(e),
                                          "".join(traceback.format_exc())))
                meter.end(0)

            logging.debug("Removing VM '%s'", self.vm.get_name())
            self.vm.delete()

        except Exception, e:
            error = (_("Error deleting virtual machine '%s': %s") %
                      (self.vm.get_name(), str(e)))
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

    def _async_delete_path(self, conn, path, ignore):
        vol = None

        try:
            vol = conn.storageVolLookupByPath(path)
        except:
            logging.debug("Path '%s' is not managed. Deleting locally", path)

        if vol:
            vol.delete(0)
        else:
            os.unlink(path)


def populate_storage_list(storage_list, vm, conn):
    model = storage_list.get_model()
    model.clear()

    for disk in vm.get_disk_devices():
        vol = None

        target = disk.target
        path = disk.path
        ro = disk.read_only
        shared = disk.shareable

        # There are a few pieces here
        # 1) Can we even delete the storage? If not, make the checkbox
        #    inconsistent. self.can_delete decides this for us, and if
        #    we can't delete, gives us a nice message to show the user
        #    for that row.
        #
        # 2) If we can delete, do we want to delete this storage by
        #    default? Reasons not to, are if the storage is marked
        #    readonly or sharable, or is in use by another VM.

        if not path:
            continue

        default = False
        definfo = None
        vol = conn.get_vol_by_path(path)
        can_del, delinfo = can_delete(conn, vol, path)

        if can_del:
            default, definfo = do_we_default(conn, vm.get_name(), vol,
                                             path, ro, shared)

        info = None
        if not can_del:
            info = delinfo
        elif not default:
            info = definfo

        icon = gtk.STOCK_DIALOG_WARNING
        icon_size = gtk.ICON_SIZE_LARGE_TOOLBAR

        row = [default, not can_del, path, target,
               bool(info), icon, icon_size, info]
        model.append(row)


def prepare_storage_list(storage_list):
    # Checkbox, deleteable?, storage path, target (hda), icon stock,
    # icon size, tooltip
    model = gtk.ListStore(bool, bool, str, str, bool, str, int, str)
    storage_list.set_model(model)
    try:
        storage_list.set_tooltip_column(STORAGE_ROW_TOOLTIP)
    except:
        # FIXME: use tooltip wrapper for this
        pass

    confirmCol = gtk.TreeViewColumn()
    pathCol = gtk.TreeViewColumn(_("Storage Path"))
    targetCol = gtk.TreeViewColumn(_("Target"))
    infoCol = gtk.TreeViewColumn()

    storage_list.append_column(confirmCol)
    storage_list.append_column(pathCol)
    storage_list.append_column(targetCol)
    storage_list.append_column(infoCol)

    chkbox = gtk.CellRendererToggle()
    chkbox.connect('toggled', storage_item_toggled, storage_list)
    confirmCol.pack_start(chkbox, False)
    confirmCol.add_attribute(chkbox, 'active', STORAGE_ROW_CONFIRM)
    confirmCol.add_attribute(chkbox, 'inconsistent',
                             STORAGE_ROW_CANT_DELETE)
    confirmCol.set_sort_column_id(STORAGE_ROW_CANT_DELETE)

    path_txt = gtk.CellRendererText()
    pathCol.pack_start(path_txt, True)
    pathCol.add_attribute(path_txt, 'text', STORAGE_ROW_PATH)
    pathCol.set_sort_column_id(STORAGE_ROW_PATH)

    target_txt = gtk.CellRendererText()
    targetCol.pack_start(target_txt, False)
    targetCol.add_attribute(target_txt, 'text', STORAGE_ROW_TARGET)
    targetCol.set_sort_column_id(STORAGE_ROW_TARGET)

    info_img = gtk.CellRendererPixbuf()
    infoCol.pack_start(info_img, False)
    infoCol.add_attribute(info_img, 'visible', STORAGE_ROW_ICON_SHOW)
    infoCol.add_attribute(info_img, 'stock-id', STORAGE_ROW_ICON)
    infoCol.add_attribute(info_img, 'stock-size', STORAGE_ROW_ICON_SIZE)
    infoCol.set_sort_column_id(STORAGE_ROW_ICON)

def storage_item_toggled(src, index, storage_list):
    active = src.get_active()

    model = storage_list.get_model()
    model[index][STORAGE_ROW_CONFIRM] = not active

def can_delete(conn, vol, path):
    """Is the passed path even deleteable"""
    ret = True
    msg = None

    if vol:
        # Managed storage
        if (vol.get_pool().get_type() ==
            virtinst.Storage.StoragePool.TYPE_ISCSI):
            msg = _("Cannot delete iscsi share.")
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

def do_we_default(conn, vm_name, vol, path, ro, shared):
    """ Returns (do we delete by default?, info string if not)"""
    info = ""

    def append_str(str1, str2, delim="\n"):
        if not str2:
            return str1
        if str1:
            str1 += delim
        str1 += str2
        return str1

    if ro:
        info = append_str(info, _("Storage is read-only."))
    elif not vol and not os.access(path, os.W_OK):
        info = append_str(info, _("No write access to path."))

    if shared:
        info = append_str(info, _("Storage is marked as shareable."))

    try:
        names = virtinst.VirtualDisk.path_in_use_by(conn.vmm, path)

        if len(names) > 1:
            namestr = ""
            names.remove(vm_name)
            for name in names:
                namestr = append_str(namestr, name, delim="\n- ")
            info = append_str(info, _("Storage is in use by the following "
                                      "virtual machines:\n- %s " % namestr))
    except Exception, e:
        logging.exception("Failed checking disk conflict: %s", str(e))

    return (not info, info)

vmmGObjectUI.type_register(vmmDeleteDialog)

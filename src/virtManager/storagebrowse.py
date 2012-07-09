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

import logging

import gtk

import virtinst

import virtManager.host
import virtManager.util as util
from virtManager.createvol import vmmCreateVolume
from virtManager.baseclass import vmmGObjectUI

class vmmStorageBrowser(vmmGObjectUI):
    def __init__(self, conn):
        vmmGObjectUI.__init__(self,
                            "vmm-storage-browse.ui",
                            "vmm-storage-browse")
        self.conn = conn

        self.conn_signal_ids = []
        self.finish_cb_id = None

        # Add Volume wizard
        self.addvol = None

        # Name of VM we are choosing storage for, can be used to recommend
        # volume name if creating
        self.vm_name = None

        # Arguments to pass to util.browse_local for local storage
        self.browse_reason = None
        self.rhel6_defaults = True
        self.local_args = {}

        self.window.connect_signals({
            "on_vmm_storage_browse_delete_event" : self.close,
            "on_browse_cancel_clicked" : self.close,
            "on_browse_local_clicked" : self.browse_local,
            "on_new_volume_clicked" : self.new_volume,
            "on_choose_volume_clicked" : self.finish,
            "on_vol_list_row_activated" : self.finish,
        })
        self.bind_escape_key_close()

        finish_img = gtk.image_new_from_stock(gtk.STOCK_NEW,
                                              gtk.ICON_SIZE_BUTTON)
        self.widget("new-volume").set_image(finish_img)
        finish_img = gtk.image_new_from_stock(gtk.STOCK_OPEN,
                                              gtk.ICON_SIZE_BUTTON)
        self.widget("choose-volume").set_image(finish_img)

        self.set_initial_state()

    def show(self, parent, conn=None):
        logging.debug("Showing storage browser")
        self.reset_state(conn)
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing storage browser")
        self.topwin.hide()
        if self.addvol:
            self.addvol.close()
        return 1

    def _cleanup(self):
        self.remove_conn()
        self.conn = None

        if self.addvol:
            self.addvol.cleanup()
            self.addvol = None

    def remove_conn(self):
        if not self.conn:
            return

        for i in self.conn_signal_ids:
            self.conn.disconnect(i)

    def set_finish_cb(self, callback):
        if self.finish_cb_id:
            self.disconnect(self.finish_cb_id)
        self.finish_cb_id = self.connect("storage-browse-finish", callback)

    def set_browse_reason(self, reason):
        self.browse_reason = reason

    def set_local_arg(self, arg, val):
        self.local_args[arg] = val

    def set_vm_name(self, name):
        self.vm_name = name

    def set_initial_state(self):
        pool_list = self.widget("pool-list")
        virtManager.host.init_pool_list(pool_list, self.pool_selected)

        # (Key, Name, Cap, Format, Used By, sensitive)
        vol_list = self.widget("vol-list")
        volListModel = gtk.ListStore(str, str, str, str, str, bool)
        vol_list.set_model(volListModel)

        vol_list.get_selection().connect("changed", self.vol_selected)
        volCol = gtk.TreeViewColumn(_("Name"))
        vol_txt1 = gtk.CellRendererText()
        volCol.pack_start(vol_txt1, True)
        volCol.add_attribute(vol_txt1, 'text', 1)
        volCol.add_attribute(vol_txt1, 'sensitive', 5)
        volCol.set_sort_column_id(1)
        vol_list.append_column(volCol)

        volSizeCol = gtk.TreeViewColumn(_("Size"))
        vol_txt2 = gtk.CellRendererText()
        volSizeCol.pack_start(vol_txt2, False)
        volSizeCol.add_attribute(vol_txt2, 'text', 2)
        volSizeCol.add_attribute(vol_txt2, 'sensitive', 5)
        volSizeCol.set_sort_column_id(2)
        vol_list.append_column(volSizeCol)

        volPathCol = gtk.TreeViewColumn(_("Format"))
        vol_txt4 = gtk.CellRendererText()
        volPathCol.pack_start(vol_txt4, False)
        volPathCol.add_attribute(vol_txt4, 'text', 3)
        volPathCol.add_attribute(vol_txt4, 'sensitive', 5)
        volPathCol.set_sort_column_id(3)
        vol_list.append_column(volPathCol)

        volUseCol = gtk.TreeViewColumn(_("Used By"))
        vol_txt5 = gtk.CellRendererText()
        volUseCol.pack_start(vol_txt5, False)
        volUseCol.add_attribute(vol_txt5, 'text', 4)
        volUseCol.add_attribute(vol_txt5, 'sensitive', 5)
        volUseCol.set_sort_column_id(4)
        vol_list.append_column(volUseCol)

        volListModel.set_sort_column_id(1, gtk.SORT_ASCENDING)

    def reset_state(self, conn=None):
        if conn and conn != self.conn:
            self.remove_conn()
            self.conn = conn

        pool_list = self.widget("pool-list")
        virtManager.host.populate_storage_pools(pool_list, self.conn)

        ids = []
        ids.append(self.conn.connect("pool-added",
                                     self.repopulate_storage_pools))
        ids.append(self.conn.connect("pool-removed",
                                     self.repopulate_storage_pools))
        ids.append(self.conn.connect("pool-started",
                                     self.refresh_storage_pool))
        ids.append(self.conn.connect("pool-stopped",
                                     self.refresh_storage_pool))
        self.conn_signal_ids = ids

        # FIXME: Need a connection specific "vol-added" function?
        #        Won't be able to pick that change up from outside?

        # Manually trigger vol_selected, so buttons are in the correct state
        self.vol_selected()
        self.pool_selected()

        tooltip = None
        is_remote = self.conn.is_remote()
        self.widget("browse-local").set_sensitive(not is_remote)
        if is_remote:
            tooltip = _("Cannot use local storage on remote connection.")
        util.tooltip_wrapper(self.widget("browse-local"),
                             tooltip)

        # Set data based on browse type
        self.local_args["dialog_type"] = None
        self.local_args["browse_reason"] = self.browse_reason

        data = self.config.browse_reason_data.get(self.browse_reason)
        if data:
            self.topwin.set_title(data["storage_title"])
            self.local_args["dialog_name"] = data["local_title"]
            self.local_args["dialog_type"] = data.get("dialog_type")
            self.local_args["choose_button"] = data.get("choose_button")


    # Convenience helpers
    def allow_create(self):
        data = self.config.browse_reason_data.get(self.browse_reason)
        if not data:
            return True

        return data["enable_create"]

    def current_pool(self):
        row = util.get_list_selection(self.widget("pool-list"))
        if not row:
            return
        return self.conn.get_pool(row[0])

    def current_vol_row(self):
        if not self.current_pool():
            return
        return util.get_list_selection(self.widget("vol-list"))

    def current_vol(self):
        pool = self.current_pool()
        row = self.current_vol_row()
        if not pool or not row:
            return
        return pool.get_volume(row[0])

    def refresh_storage_pool(self, src_ignore, uuid):
        pool_list = self.widget("pool-list")
        virtManager.host.refresh_pool_in_list(pool_list, self.conn, uuid)
        curpool = self.current_pool()
        if curpool.uuid != uuid:
            return

        # Currently selected pool changed state: force a 'pool_selected' to
        # update vol list
        self.pool_selected(self.widget("pool-list").get_selection())

    def repopulate_storage_pools(self, src_ignore, uuid_ignore):
        pool_list = self.widget("pool-list")
        virtManager.host.populate_storage_pools(pool_list, self.conn)


    # Listeners

    def pool_selected(self, src_ignore=None):
        pool = self.current_pool()
        newvol = bool(pool)
        if pool:
            newvol = pool.is_active()

        newvol = newvol and self.allow_create()
        self.widget("new-volume").set_sensitive(newvol)

        self.populate_storage_volumes()

    def vol_selected(self, ignore=None):
        vol = self.current_vol_row()
        canchoose = bool(vol and vol[5])
        self.widget("choose-volume").set_sensitive(canchoose)

    def refresh_current_pool(self, ignore):
        cp = self.current_pool()
        if cp is None:
            return
        cp.refresh()
        self.refresh_storage_pool(None, cp.get_uuid())

    def new_volume(self, src_ignore):
        pool = self.current_pool()
        if pool is None:
            return

        try:
            if self.addvol is None:
                self.addvol = vmmCreateVolume(self.conn, pool)
                self.addvol.connect("vol-created", self.refresh_current_pool)
            else:
                self.addvol.set_parent_pool(pool)
            self.addvol.set_modal(True)
            self.addvol.set_name_hint(self.vm_name)
            self.addvol.show(self.topwin)
        except Exception, e:
            self.show_err(_("Error launching volume wizard: %s") % str(e))

    def browse_local(self, src_ignore):
        if not self.local_args.get("dialog_name"):
            self.local_args["dialog_name"] = None

        filename = util.browse_local(parent=self.topwin,
                                     conn=self.conn,
                                     **self.local_args)
        if filename:
            self._do_finish(path=filename)

    def finish(self, ignore=None, ignore1=None, ignore2=None):
        self._do_finish()

    def _do_finish(self, path=None):
        if not path:
            path = self.current_vol().get_path()
        self.emit("storage-browse-finish", path)
        self.close()


    # Do stuff!
    def populate_storage_volumes(self):
        model = self.widget("vol-list").get_model()
        model.clear()
        dironly = self.browse_reason == self.config.CONFIG_DIR_FS

        pool = self.current_pool()
        if not pool:
            return

        vols = pool.get_volumes()
        for key in vols.keys():
            vol = vols[key]
            sensitive = True
            try:
                path = vol.get_target_path()
                fmt = vol.get_format() or ""
            except Exception:
                logging.exception("Failed to determine volume parameters, "
                                  "skipping volume %s", key)
                continue

            namestr = None

            try:
                if path:
                    names = virtinst.VirtualDisk.path_in_use_by(
                                                self.conn.vmm, path)
                    namestr = ", ".join(names)
                    if not namestr:
                        namestr = None
            except:
                logging.exception("Failed to determine if storage volume in "
                                  "use.")

            if dironly and fmt != 'dir':
                sensitive = False
            elif not self.rhel6_defaults:
                if fmt == "vmdk":
                    sensitive = False

            model.append([key, vol.get_name(), vol.get_pretty_capacity(),
                          fmt, namestr, sensitive])

    def show_err(self, info, details=None):
        self.err.show_err(info,
                          details=details,
                          async=False)

vmmGObjectUI.type_register(vmmStorageBrowser)
vmmStorageBrowser.signal_new(vmmStorageBrowser, "storage-browse-finish", [str])

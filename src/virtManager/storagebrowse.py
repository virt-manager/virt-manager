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

import gobject
import gtk

import traceback
import logging

import virtinst

import virtManager.host
import virtManager.util as util
from virtManager.createvol import vmmCreateVolume
from virtManager.config import vmmConfig
from virtManager.baseclass import vmmGObjectUI

class vmmStorageBrowser(vmmGObjectUI):
    __gsignals__ = {
        #"vol-created": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [])
        "storage-browse-finish": (gobject.SIGNAL_RUN_FIRST,
                                  gobject.TYPE_NONE, [str]),
    }

    def __init__(self, conn):
        vmmGObjectUI.__init__(self,
                            "vmm-storage-browse.glade",
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
        self.local_args = {}

        self.window.signal_autoconnect({
            "on_vmm_storage_browse_delete_event" : self.close,
            "on_browse_cancel_clicked" : self.close,
            "on_browse_local_clicked" : self.browse_local,
            "on_new_volume_clicked" : self.new_volume,
            "on_choose_volume_clicked" : self.finish,
            "on_vol_list_row_activated" : self.finish,
        })
        util.bind_escape_key_close(self)

        finish_img = gtk.image_new_from_stock(gtk.STOCK_NEW,
                                              gtk.ICON_SIZE_BUTTON)
        self.window.get_widget("new-volume").set_image(finish_img)
        finish_img = gtk.image_new_from_stock(gtk.STOCK_OPEN,
                                              gtk.ICON_SIZE_BUTTON)
        self.window.get_widget("choose-volume").set_image(finish_img)

        self.set_initial_state()

    def show(self, conn=None):
        self.reset_state(conn)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        self.topwin.hide()
        if self.addvol:
            self.addvol.close()
        return 1

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
        pool_list = self.window.get_widget("pool-list")
        virtManager.host.init_pool_list(pool_list, self.pool_selected)

        # (Key, Name, Cap, Format, Used By)
        vol_list = self.window.get_widget("vol-list")
        volListModel = gtk.ListStore(str, str, str, str, str)
        vol_list.set_model(volListModel)

        vol_list.get_selection().connect("changed", self.vol_selected)
        volCol = gtk.TreeViewColumn(_("Name"))
        vol_txt1 = gtk.CellRendererText()
        volCol.pack_start(vol_txt1, True)
        volCol.add_attribute(vol_txt1, 'text', 1)
        volCol.set_sort_column_id(1)
        vol_list.append_column(volCol)

        volSizeCol = gtk.TreeViewColumn(_("Size"))
        vol_txt2 = gtk.CellRendererText()
        volSizeCol.pack_start(vol_txt2, False)
        volSizeCol.add_attribute(vol_txt2, 'text', 2)
        volSizeCol.set_sort_column_id(2)
        vol_list.append_column(volSizeCol)

        volPathCol = gtk.TreeViewColumn(_("Format"))
        vol_txt4 = gtk.CellRendererText()
        volPathCol.pack_start(vol_txt4, False)
        volPathCol.add_attribute(vol_txt4, 'text', 3)
        volPathCol.set_sort_column_id(3)
        vol_list.append_column(volPathCol)

        volUseCol = gtk.TreeViewColumn(_("Used By"))
        vol_txt5 = gtk.CellRendererText()
        volUseCol.pack_start(vol_txt5, False)
        volUseCol.add_attribute(vol_txt5, 'text', 4)
        volUseCol.set_sort_column_id(4)
        vol_list.append_column(volUseCol)

        volListModel.set_sort_column_id(1, gtk.SORT_ASCENDING)


    def reset_state(self, conn=None):
        if conn and conn != self.conn:
            for i in self.conn_signal_ids:
                self.conn.disconnect(i)
            self.conn = conn

        pool_list = self.window.get_widget("pool-list")
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

        tooltip = None
        is_remote = self.conn.is_remote()
        self.window.get_widget("browse-local").set_sensitive(not is_remote)
        if is_remote:
            tooltip = _("Cannot use local storage on remote connection.")
        util.tooltip_wrapper(self.window.get_widget("browse-local"),
                             tooltip)

        # Set data based on browse type
        self.local_args["browse_reason"] = self.browse_reason
        if not vmmConfig.browse_reason_data.has_key(self.browse_reason):
            return

        data = vmmConfig.browse_reason_data[self.browse_reason]
        self.topwin.set_title(data["storage_title"])
        self.local_args["dialog_name"] = data["local_title"]

        allow_create = data["enable_create"]
        self.window.get_widget("new-volume").set_sensitive(allow_create)

    # Convenience helpers
    def current_pool(self):
        sel = self.window.get_widget("pool-list").get_selection()
        active = sel.get_selected()
        if active[1] != None:
            curruuid = active[0].get_value(active[1], 0)
            return self.conn.get_pool(curruuid)
        return None

    def current_vol(self):
        pool = self.current_pool()
        if not pool:
            return None
        sel = self.window.get_widget("vol-list").get_selection()
        active = sel.get_selected()
        if active[1] != None:
            curruuid = active[0].get_value(active[1], 0)
            return pool.get_volume(curruuid)
        return None

    def refresh_storage_pool(self, src_ignore, uri_ignore, uuid):
        pool_list = self.window.get_widget("pool-list")
        virtManager.host.refresh_pool_in_list(pool_list, self.conn, uuid)
        curpool = self.current_pool()
        if curpool.uuid != uuid:
            return

        # Currently selected pool changed state: force a 'pool_selected' to
        # update vol list
        self.pool_selected(self.window.get_widget("pool-list").get_selection())

    def repopulate_storage_pools(self, src_ignore, uri_ignore, uuid_ignore):
        pool_list = self.window.get_widget("pool-list")
        virtManager.host.populate_storage_pools(pool_list, self.conn)


    # Listeners

    def pool_selected(self, src_ignore):
        pool = self.current_pool()
        self.window.get_widget("new-volume").set_sensitive(bool(pool))
        if pool:
            self.window.get_widget("new-volume").set_sensitive(pool.is_active())
        self.populate_storage_volumes()

    def vol_selected(self, ignore=None):
        vol = self.current_vol()
        self.window.get_widget("choose-volume").set_sensitive(bool(vol))

    def refresh_current_pool(self, ignore):
        cp = self.current_pool()
        if cp is None:
            return
        cp.refresh()
        self.refresh_storage_pool(None, None, cp.get_uuid())

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
            self.addvol.show()
        except Exception, e:
            self.show_err(_("Error launching volume wizard: %s") % str(e),
                          "".join(traceback.format_exc()))

    def browse_local(self, src_ignore):
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
        model = self.window.get_widget("vol-list").get_model()
        model.clear()

        pool = self.current_pool()
        if not pool:
            return

        vols = pool.get_volumes()
        for key in vols.keys():
            vol = vols[key]

            path = vol.get_target_path()
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

            model.append([key, vol.get_name(), vol.get_pretty_capacity(),
                          vol.get_format() or "", namestr])

    def show_err(self, info, details):
        self.err.show_err(info, details, async=False)

vmmGObjectUI.type_register(vmmStorageBrowser)

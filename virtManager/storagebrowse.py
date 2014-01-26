#
# Copyright (C) 2009, 2013, 2014 Red Hat, Inc.
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

# pylint: disable=E0611
from gi.repository import GObject
from gi.repository import Gtk
# pylint: enable=E0611

from virtManager import host
from virtManager.createvol import vmmCreateVolume
from virtManager.baseclass import vmmGObjectUI
from virtManager import uiutil


class vmmStorageBrowser(vmmGObjectUI):
    __gsignals__ = {
        "storage-browse-finish": (GObject.SignalFlags.RUN_FIRST, None, [str]),
    }

    def __init__(self, conn):
        vmmGObjectUI.__init__(self, "storagebrowse.ui", "vmm-storage-browse")
        self.conn = conn

        self.conn_signal_ids = []
        self.finish_cb_id = None
        self.can_new_volume = True
        self._first_run = False

        # Add Volume wizard
        self.addvol = None

        # Name of VM we are choosing storage for, can be used to recommend
        # volume name if creating
        self.vm_name = None

        # Arguments to pass to util.browse_local for local storage
        self.browse_reason = None
        self.local_args = {}

        self.stable_defaults = False

        self.builder.connect_signals({
            "on_vmm_storage_browse_delete_event" : self.close,
            "on_browse_cancel_clicked" : self.close,
            "on_browse_local_clicked" : self.browse_local,
            "on_new_volume_clicked" : self.new_volume,
            "on_choose_volume_clicked" : self.finish,
            "on_vol_list_row_activated" : self.finish,
            "on_vol_list_changed": self.vol_selected,
        })
        self.bind_escape_key_close()

        self.set_initial_state()

    def show(self, parent, conn):
        logging.debug("Showing storage browser")
        self.reset_state(conn)
        self.topwin.set_transient_for(parent)
        self.topwin.present()
        self.conn.schedule_priority_tick(pollpool=True)

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
        host.init_pool_list(pool_list, self.pool_selected)

        # (Key, Name, Cap, Format, Used By, sensitive)
        vol_list = self.widget("vol-list")
        volListModel = Gtk.ListStore(str, str, str, str, str, bool)
        vol_list.set_model(volListModel)

        volCol = Gtk.TreeViewColumn(_("Name"))
        vol_txt1 = Gtk.CellRendererText()
        volCol.pack_start(vol_txt1, True)
        volCol.add_attribute(vol_txt1, 'text', 1)
        volCol.add_attribute(vol_txt1, 'sensitive', 5)
        volCol.set_sort_column_id(1)
        vol_list.append_column(volCol)

        volSizeCol = Gtk.TreeViewColumn(_("Size"))
        vol_txt2 = Gtk.CellRendererText()
        volSizeCol.pack_start(vol_txt2, False)
        volSizeCol.add_attribute(vol_txt2, 'text', 2)
        volSizeCol.add_attribute(vol_txt2, 'sensitive', 5)
        volSizeCol.set_sort_column_id(2)
        vol_list.append_column(volSizeCol)

        volPathCol = Gtk.TreeViewColumn(_("Format"))
        vol_txt4 = Gtk.CellRendererText()
        volPathCol.pack_start(vol_txt4, False)
        volPathCol.add_attribute(vol_txt4, 'text', 3)
        volPathCol.add_attribute(vol_txt4, 'sensitive', 5)
        volPathCol.set_sort_column_id(3)
        vol_list.append_column(volPathCol)

        volUseCol = Gtk.TreeViewColumn(_("Used By"))
        vol_txt5 = Gtk.CellRendererText()
        volUseCol.pack_start(vol_txt5, False)
        volUseCol.add_attribute(vol_txt5, 'text', 4)
        volUseCol.add_attribute(vol_txt5, 'sensitive', 5)
        volUseCol.set_sort_column_id(4)
        vol_list.append_column(volUseCol)

        volListModel.set_sort_column_id(1, Gtk.SortType.ASCENDING)

    def reset_state(self, conn):
        self.remove_conn()
        self.conn = conn

        self.repopulate_storage_pools()

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

        if not self._first_run:
            self._first_run = True
            pool = self.conn.get_default_pool()
            uiutil.set_row_selection(
                self.widget("pool-list"), pool and pool.get_uuid() or None)
        # Manually trigger vol_selected, so buttons are in the correct state
        self.vol_selected()
        self.pool_selected()

        tooltip = ""
        is_remote = self.conn.is_remote()
        self.widget("browse-local").set_sensitive(not is_remote)
        if is_remote:
            tooltip = _("Cannot use local storage on remote connection.")
        self.widget("browse-local").set_tooltip_text(tooltip)

        # Set data based on browse type
        self.local_args["dialog_type"] = None
        self.local_args["browse_reason"] = self.browse_reason

        data = self.config.browse_reason_data.get(self.browse_reason)
        if data:
            self.topwin.set_title(data["storage_title"])
            self.local_args["dialog_name"] = data["local_title"]
            self.local_args["dialog_type"] = data.get("dialog_type")
            self.local_args["choose_button"] = data.get("choose_button")

        self.widget("new-volume").set_visible(self.can_new_volume)


    # Convenience helpers
    def allow_create(self):
        data = self.config.browse_reason_data.get(self.browse_reason)
        if not data:
            return True

        return data["enable_create"]

    def current_pool(self):
        row = uiutil.get_list_selection(self.widget("pool-list"))
        if not row:
            return
        try:
            return self.conn.get_pool(row[0])
        except KeyError:
            return None

    def current_vol_row(self):
        if not self.current_pool():
            return
        return uiutil.get_list_selection(self.widget("vol-list"))

    def current_vol(self):
        pool = self.current_pool()
        row = self.current_vol_row()
        if not pool or not row:
            return
        return pool.get_volume(row[0])

    def refresh_storage_pool(self, src_ignore, uuid):
        pool_list = self.widget("pool-list")
        host.refresh_pool_in_list(pool_list, self.conn, uuid)
        curpool = self.current_pool()
        if curpool.get_uuid() != uuid:
            return

        # Currently selected pool changed state: force a 'pool_selected' to
        # update vol list
        self.pool_selected(self.widget("pool-list").get_selection())

    def repopulate_storage_pools(self, src_ignore=None, uuid_ignore=None):
        pool_list = self.widget("pool-list")
        host.populate_storage_pools(pool_list, self.conn, self.current_pool())


    # Listeners

    def pool_selected(self, src_ignore=None):
        pool = self.current_pool()

        newvol = bool(pool)
        if pool:
            pool.tick()
            newvol = pool.is_active()

        newvol = newvol and self.allow_create()
        self.widget("new-volume").set_sensitive(newvol)

        self.populate_storage_volumes()

    def vol_selected(self, ignore=None):
        vol = self.current_vol_row()
        canchoose = bool(vol and vol[5])
        self.widget("choose-volume").set_sensitive(canchoose)

    def refresh_current_pool(self, createvol):
        cp = self.current_pool()
        if cp is None:
            return
        cp.refresh()

        self.refresh_storage_pool(None, cp.get_uuid())

        vol_list = self.widget("vol-list")
        def select_volume(model, path, it, volume_name):
            if model.get(it, 0)[0] == volume_name:
                uiutil.set_list_selection(vol_list, path)

        vol_list.get_model().foreach(select_volume, createvol.vol.name)

    def new_volume(self, src_ignore):
        pool = self.current_pool()
        if pool is None:
            return

        try:
            if self.addvol is None:
                self.addvol = vmmCreateVolume(self.conn, pool)
                self.addvol.connect("vol-created", self.refresh_current_pool)
            else:
                self.addvol.set_parent_pool(self.conn, pool)
            self.addvol.set_modal(True)
            self.addvol.set_name_hint(self.vm_name)
            self.addvol.show(self.topwin)
        except Exception, e:
            self.show_err(_("Error launching volume wizard: %s") % str(e))

    def browse_local(self, src_ignore):
        if not self.local_args.get("dialog_name"):
            self.local_args["dialog_name"] = None

        filename = self.err.browse_local(
            self.conn, **self.local_args)
        if filename:
            self._do_finish(path=filename)

    def finish(self, ignore=None, ignore1=None, ignore2=None):
        self._do_finish()

    def _do_finish(self, path=None):
        if not path:
            path = self.current_vol().get_target_path()
        self.emit("storage-browse-finish", path)
        self.close()


    # Do stuff!
    def populate_storage_volumes(self):
        list_widget = self.widget("vol-list")
        pool = self.current_pool()

        def sensitive_cb(fmt):
            if ((self.browse_reason == self.config.CONFIG_DIR_FS)
                and fmt != 'dir'):
                return False
            elif self.stable_defaults:
                if fmt == "vmdk":
                    return False
            return True

        host.populate_storage_volumes(list_widget, pool, sensitive_cb)

    def show_err(self, info, details=None):
        self.err.show_err(info,
                          details=details,
                          modal=True)

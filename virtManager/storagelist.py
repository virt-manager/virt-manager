#
# Copyright (C) 2015 Red Hat, Inc.
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

from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository import GObject

from virtinst import StoragePool
from virtinst import VirtualDisk

from . import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI
from .createpool import vmmCreatePool
from .createvol import vmmCreateVolume


EDIT_POOL_IDS = (
EDIT_POOL_NAME,
EDIT_POOL_AUTOSTART,
) = range(2)

VOL_NUM_COLUMNS = 7
(VOL_COLUMN_KEY,
 VOL_COLUMN_NAME,
 VOL_COLUMN_CAPACITY,
 VOL_COLUMN_SIZESTR,
 VOL_COLUMN_FORMAT,
 VOL_COLUMN_INUSEBY,
 VOL_COLUMN_SENSITIVE) = range(VOL_NUM_COLUMNS)

POOL_NUM_COLUMNS = 4
(POOL_COLUMN_CONNKEY,
 POOL_COLUMN_LABEL,
 POOL_COLUMN_ISACTIVE,
 POOL_COLUMN_PERCENT) = range(POOL_NUM_COLUMNS)

ICON_RUNNING = "state_running"
ICON_SHUTOFF = "state_shutoff"


def _get_pool_size_percent(pool):
    cap = pool.get_capacity()
    alloc = pool.get_allocation()
    if not cap or alloc is None:
        per = 0
    else:
        per = int(((float(alloc) / float(cap)) * 100))
    return "<span size='small' color='#484848'>%s%%</span>" % int(per)


class vmmStorageList(vmmGObjectUI):
    __gsignals__ = {
        "browse-clicked": (GObject.SignalFlags.RUN_FIRST, None, []),
        "volume-chosen": (GObject.SignalFlags.RUN_FIRST, None, [object]),
        "cancel-clicked": (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    def __init__(self, conn, builder, topwin, vol_sensitive_cb=None):
        vmmGObjectUI.__init__(self, "storagelist.ui",
                              None, builder=builder, topwin=topwin)
        self.conn = conn

        # Callback function for setting volume row sensitivity. Used
        # by storage browser to disallow selecting certain volumes
        self._vol_sensitive_cb = vol_sensitive_cb

        # Name hint passed to addvol. Set by storagebrowser
        self._name_hint = None

        self._active_edits = []
        self._addpool = None
        self._addvol = None
        self._volmenu = None
        self.top_box = self.widget("storage-grid")

        self.builder.connect_signals({
            "on_pool_add_clicked": self._pool_add,
            "on_pool_stop_clicked": self._pool_stop,
            "on_pool_start_clicked": self._pool_start,
            "on_pool_delete_clicked": self._pool_delete,
            "on_pool_refresh_clicked": self._pool_refresh,
            "on_pool_apply_clicked": (lambda *x: self._pool_apply()),

            "on_vol_delete_clicked": self._vol_delete,
            "on_vol_list_button_press_event": self._vol_popup_menu,
            "on_vol_list_changed": self._vol_selected,
            "on_vol_add_clicked": self._vol_add,

            "on_browse_cancel_clicked": self._cancel_clicked,
            "on_browse_local_clicked": self._browse_local_clicked,
            "on_choose_volume_clicked": self._choose_volume_clicked,
            "on_vol_list_row_activated": self._vol_list_row_activated,

            "on_pool_name_changed": (lambda *x:
                self._enable_pool_apply(x, EDIT_POOL_NAME)),
            "on_pool_autostart_toggled": self._pool_autostart_changed,
        })

        self._init_ui()


    def _cleanup(self):
        try:
            self.conn.disconnect_by_func(self._conn_pool_count_changed)
            self.conn.disconnect_by_func(self._conn_pool_count_changed)
            self.conn.disconnect_by_func(self._conn_state_changed)
        except Exception:
            pass
        self.conn = None

        if self._addpool:
            self._addpool.cleanup()
            self._addpool = None

        if self._addvol:
            self._addvol.cleanup()
            self._addvol = None

        self._volmenu.destroy()
        self._volmenu = None

    def close(self, ignore1=None, ignore2=None):
        if self._addvol:
            self._addvol.close()
        if self._addpool:
            self._addpool.close()
        if self._volmenu:
            self._volmenu.hide()


    ##########################
    # Initialization methods #
    ##########################

    def _cap_sort_func(self, model, iter1, iter2, ignore):
        return cmp(int(model[iter1][VOL_COLUMN_CAPACITY]),
                   int(model[iter2][VOL_COLUMN_CAPACITY]))

    def _init_ui(self):
        self.widget("storage-pages").set_show_tabs(False)

        # These are enabled in storagebrowser.py
        self.widget("browse-local").set_visible(False)
        self.widget("browse-cancel").set_visible(False)
        self.widget("choose-volume").set_visible(False)

        # Volume list popup menu
        self._volmenu = Gtk.Menu()
        volCopyPath = Gtk.ImageMenuItem.new_with_label(_("Copy Volume Path"))
        volCopyImage = Gtk.Image()
        volCopyImage.set_from_stock(Gtk.STOCK_COPY, Gtk.IconSize.MENU)
        volCopyPath.set_image(volCopyImage)
        volCopyPath.show()
        volCopyPath.connect("activate", self._vol_copy_path)
        self._volmenu.add(volCopyPath)

        # Volume list
        # [key, name, sizestr, capacity, format, in use by string, sensitive]
        volListModel = Gtk.ListStore(str, str, str, str, str, str, bool)
        self.widget("vol-list").set_model(volListModel)

        volCol = Gtk.TreeViewColumn(_("Volumes"))
        vol_txt1 = Gtk.CellRendererText()
        volCol.pack_start(vol_txt1, True)
        volCol.add_attribute(vol_txt1, 'text', VOL_COLUMN_NAME)
        volCol.add_attribute(vol_txt1, 'sensitive', VOL_COLUMN_SENSITIVE)
        volCol.set_sort_column_id(VOL_COLUMN_NAME)
        self.widget("vol-list").append_column(volCol)

        volSizeCol = Gtk.TreeViewColumn(_("Size"))
        vol_txt2 = Gtk.CellRendererText()
        volSizeCol.pack_start(vol_txt2, False)
        volSizeCol.add_attribute(vol_txt2, 'text', VOL_COLUMN_SIZESTR)
        volSizeCol.add_attribute(vol_txt2, 'sensitive', VOL_COLUMN_SENSITIVE)
        volSizeCol.set_sort_column_id(VOL_COLUMN_CAPACITY)
        self.widget("vol-list").append_column(volSizeCol)
        volListModel.set_sort_func(VOL_COLUMN_CAPACITY, self._cap_sort_func)

        volFormatCol = Gtk.TreeViewColumn(_("Format"))
        vol_txt3 = Gtk.CellRendererText()
        volFormatCol.pack_start(vol_txt3, False)
        volFormatCol.add_attribute(vol_txt3, 'text', VOL_COLUMN_FORMAT)
        volFormatCol.add_attribute(vol_txt3, 'sensitive', VOL_COLUMN_SENSITIVE)
        volFormatCol.set_sort_column_id(VOL_COLUMN_FORMAT)
        self.widget("vol-list").append_column(volFormatCol)

        volUseCol = Gtk.TreeViewColumn(_("Used By"))
        vol_txt4 = Gtk.CellRendererText()
        volUseCol.pack_start(vol_txt4, False)
        volUseCol.add_attribute(vol_txt4, 'text', VOL_COLUMN_INUSEBY)
        volUseCol.add_attribute(vol_txt4, 'sensitive', VOL_COLUMN_SENSITIVE)
        volUseCol.set_sort_column_id(VOL_COLUMN_INUSEBY)
        self.widget("vol-list").append_column(volUseCol)

        volListModel.set_sort_column_id(VOL_COLUMN_NAME,
            Gtk.SortType.ASCENDING)

        # Init pool list
        # [connkey, label, pool.is_active(), percent string]
        pool_list = self.widget("pool-list")
        poolListModel = Gtk.ListStore(str, str, bool, str)
        pool_list.set_model(poolListModel)

        poolCol = Gtk.TreeViewColumn(_("Storage Pools"))
        pool_txt = Gtk.CellRendererText()
        pool_per = Gtk.CellRendererText()
        poolCol.pack_start(pool_per, False)
        poolCol.pack_start(pool_txt, True)
        poolCol.add_attribute(pool_txt, 'markup', POOL_COLUMN_LABEL)
        poolCol.add_attribute(pool_txt, 'sensitive', POOL_COLUMN_ISACTIVE)
        poolCol.add_attribute(pool_per, 'markup', POOL_COLUMN_PERCENT)
        pool_list.append_column(poolCol)
        poolListModel.set_sort_column_id(POOL_COLUMN_LABEL,
            Gtk.SortType.ASCENDING)

        pool_list.get_selection().connect("changed", self._pool_selected)
        pool_list.get_selection().set_select_function(
            (lambda *x: self._confirm_changes()), None)

        # Populate list and connect conn signals
        self._populate_pools()
        self.conn.connect("pool-added", self._conn_pool_count_changed)
        self.conn.connect("pool-removed", self._conn_pool_count_changed)
        self.conn.connect("state-changed", self._conn_state_changed)

        self._conn_state_changed()


    ###############
    # Public APIs #
    ###############

    def refresh_page(self):
        self._populate_vols()
        self.conn.schedule_priority_tick(pollpool=True)

    def set_name_hint(self, val):
        self._name_hint = val


    ####################
    # Internal helpers #
    ####################

    def _current_pool(self):
        connkey = uiutil.get_list_selection(self.widget("pool-list"))
        return connkey and self.conn.get_pool(connkey)

    def _current_vol(self):
        pool = self._current_pool()
        if not pool:
            return None

        connkey = uiutil.get_list_selection(self.widget("vol-list"))
        return connkey and pool.get_volume(connkey)

    def _enable_pool_apply(self, *arglist):
        edittype = arglist[-1]
        self.widget("pool-apply").set_sensitive(True)
        if edittype not in self._active_edits:
            self._active_edits.append(edittype)

    def _disable_pool_apply(self):
        for i in EDIT_POOL_IDS:
            if i in self._active_edits:
                self._active_edits.remove(i)

        self.widget("pool-apply").set_sensitive(False)

    def _update_pool_row(self, connkey):
        for row in self.widget("pool-list").get_model():
            if row[POOL_COLUMN_CONNKEY] != connkey:
                continue

            # Update active sensitivity and percent available for passed key
            pool = self.conn.get_pool(connkey)
            row[POOL_COLUMN_ISACTIVE] = pool.is_active()
            row[POOL_COLUMN_PERCENT] = _get_pool_size_percent(pool)
            break

        curpool = self._current_pool()
        if not curpool or curpool.get_connkey() != connkey:
            return

        # Currently selected pool changed state: force a 'pool_selected' to
        # update vol list
        self._pool_selected(self.widget("pool-list").get_selection())

    def _reset_pool_state(self):
        self.widget("pool-details").set_sensitive(False)
        self.widget("pool-name-entry").set_text("")
        self.widget("pool-sizes").set_markup("")
        self.widget("pool-location").set_text("")
        self.widget("pool-state-icon").set_from_icon_name(
            ICON_SHUTOFF, Gtk.IconSize.BUTTON)
        self.widget("pool-state").set_text(_("Inactive"))
        self.widget("vol-list").get_model().clear()
        self.widget("pool-autostart").set_label(_("On Boot"))
        self.widget("pool-autostart").set_active(False)

        self.widget("pool-delete").set_sensitive(False)
        self.widget("pool-stop").set_sensitive(False)
        self.widget("pool-start").set_sensitive(False)
        self.widget("pool-refresh").set_sensitive(False)
        self.widget("vol-add").set_sensitive(False)
        self.widget("vol-delete").set_sensitive(False)
        self.widget("vol-list").set_sensitive(False)
        self._disable_pool_apply()

    def _populate_pool_state(self, connkey):
        pool = self.conn.get_pool(connkey)
        auto = pool.get_autostart()
        active = pool.is_active()

        # Set pool details state
        self.widget("pool-details").set_sensitive(True)
        self.widget("pool-name-entry").set_text(pool.get_name())
        self.widget("pool-name-entry").set_editable(not active)
        self.widget("pool-sizes").set_markup(
                _("%s Free / <i>%s In Use</i>") %
                (pool.get_pretty_available(), pool.get_pretty_allocation()))
        self.widget("pool-location").set_text(
                pool.get_target_path())
        self.widget("pool-state-icon").set_from_icon_name(
                ((active and ICON_RUNNING) or ICON_SHUTOFF),
                Gtk.IconSize.BUTTON)
        self.widget("pool-state").set_text(
                (active and _("Active")) or _("Inactive"))
        self.widget("pool-autostart").set_label(_("On Boot"))
        self.widget("pool-autostart").set_active(auto)

        self.widget("vol-list").set_sensitive(active)
        self._populate_vols()

        self.widget("pool-delete").set_sensitive(not active)
        self.widget("pool-stop").set_sensitive(active)
        self.widget("pool-start").set_sensitive(not active)
        self.widget("pool-refresh").set_sensitive(active)
        self.widget("vol-add").set_sensitive(active)
        self.widget("vol-add").set_tooltip_text(_("Create new volume"))
        self.widget("vol-delete").set_sensitive(False)

        if active and not pool.supports_volume_creation():
            self.widget("vol-add").set_sensitive(False)
            self.widget("vol-add").set_tooltip_text(
                _("Pool does not support volume creation"))

    def _set_storage_error_page(self, msg):
        self._reset_pool_state()
        self.widget("storage-pages").set_current_page(1)
        self.widget("storage-error-label").set_text(msg)

    def _populate_pools(self):
        pool_list = self.widget("pool-list")
        curpool = self._current_pool()

        model = pool_list.get_model()
        # Prevent events while the model is modified
        pool_list.set_model(None)
        try:
            pool_list.get_selection().unselect_all()
            model.clear()

            for pool in self.conn.list_pools():
                try:
                    pool.disconnect_by_func(self._pool_changed)
                    pool.disconnect_by_func(self._pool_changed)
                except Exception:
                    pass
                pool.connect("state-changed", self._pool_changed)
                pool.connect("refreshed", self._pool_changed)

                name = pool.get_name()
                typ = StoragePool.get_pool_type_desc(pool.get_type())
                label = "%s\n<span size='small'>%s</span>" % (name, typ)

                row = [None] * POOL_NUM_COLUMNS
                row[POOL_COLUMN_CONNKEY] = pool.get_connkey()
                row[POOL_COLUMN_LABEL] = label
                row[POOL_COLUMN_ISACTIVE] = pool.is_active()
                row[POOL_COLUMN_PERCENT] = _get_pool_size_percent(pool)

                model.append(row)
        finally:
            pool_list.set_model(model)

        uiutil.set_list_selection(pool_list,
            curpool and curpool.get_connkey() or None)

    def _populate_vols(self):
        list_widget = self.widget("vol-list")
        pool = self._current_pool()
        vols = pool and pool.get_volumes() or []
        model = list_widget.get_model()
        list_widget.get_selection().unselect_all()
        model.clear()

        vadj = self.widget("vol-scroll").get_vadjustment()
        vscroll_percent = vadj.get_value() / max(vadj.get_upper(), 1)

        for vol in vols:
            key = vol.get_connkey()

            try:
                path = vol.get_target_path()
                name = vol.get_pretty_name(pool.get_type())
                cap = str(vol.get_capacity())
                sizestr = vol.get_pretty_capacity()
                fmt = vol.get_format() or ""
            except Exception:
                logging.debug("Error getting volume info for '%s', "
                              "hiding it", key, exc_info=True)
                continue

            namestr = None
            try:
                if path:
                    names = VirtualDisk.path_in_use_by(vol.conn.get_backend(),
                                                       path)
                    namestr = ", ".join(names)
                    if not namestr:
                        namestr = None
            except Exception:
                logging.exception("Failed to determine if storage volume in "
                                  "use.")

            sensitive = True
            if self._vol_sensitive_cb:
                sensitive = self._vol_sensitive_cb(fmt)

            row = [None] * VOL_NUM_COLUMNS
            row[VOL_COLUMN_KEY] = key
            row[VOL_COLUMN_NAME] = name
            row[VOL_COLUMN_SIZESTR] = sizestr
            row[VOL_COLUMN_CAPACITY] = cap
            row[VOL_COLUMN_FORMAT] = fmt
            row[VOL_COLUMN_INUSEBY] = namestr
            row[VOL_COLUMN_SENSITIVE] = sensitive
            model.append(row)

        def _reset_vscroll_position():
            vadj.set_value(vadj.get_upper() * vscroll_percent)
        self.idle_add(_reset_vscroll_position)

    def _confirm_changes(self):
        if not self._active_edits:
            return True

        if self.err.chkbox_helper(
                self.config.get_confirm_unapplied,
                self.config.set_confirm_unapplied,
                text1=(_("There are unapplied changes. "
                         "Would you like to apply them now?")),
                chktext=_("Don't warn me again."),
                default=False):

            if all([edit in EDIT_POOL_IDS for edit in self._active_edits]):
                self._pool_apply()

        self._active_edits = []
        return True


    #############
    # Listeners #
    #############

    def _browse_local_clicked(self, src):
        ignore = src
        self.emit("browse-clicked")

    def _choose_volume_clicked(self, src):
        ignore = src
        self.emit("volume-chosen", self._current_vol())

    def _vol_list_row_activated(self, src, treeiter, viewcol):
        ignore = src
        ignore = treeiter
        ignore = viewcol
        self.emit("volume-chosen", self._current_vol())

    def _pool_selected(self, src):
        model, treeiter = src.get_selected()
        if treeiter is None:
            self._set_storage_error_page(_("No storage pool selected."))
            return

        self.widget("storage-pages").set_current_page(0)
        connkey = model[treeiter][0]

        try:
            self._populate_pool_state(connkey)
        except Exception as e:
            logging.exception(e)
            self._set_storage_error_page(_("Error selecting pool: %s") % e)
        self._disable_pool_apply()

    def _pool_created(self, src, connkey):
        # The pool list will have already been updated, since this
        # signal arrives only after pool-added. So all we do here is
        # select the pool we just created.
        ignore = src
        uiutil.set_list_selection(self.widget("pool-list"), connkey)

    def _vol_created(self, src, pool_connkey, volname):
        # The vol list will have already been updated, since this
        # signal arrives only after pool-refreshed. So all we do here is
        # select the vol we just created.
        ignore = src
        pool = self._current_pool()
        if not pool or pool.get_connkey() != pool_connkey:
            return

        # Select the new volume
        uiutil.set_list_selection(self.widget("vol-list"), volname)

    def _pool_autostart_changed(self, src):
        ignore = src
        self._enable_pool_apply(EDIT_POOL_AUTOSTART)

    def _vol_selected(self, src):
        model, treeiter = src.get_selected()
        self.widget("vol-delete").set_sensitive(bool(treeiter))

        can_choose = bool(treeiter and model[treeiter][VOL_COLUMN_SENSITIVE])
        self.widget("choose-volume").set_sensitive(can_choose)

    def _vol_popup_menu(self, widget_ignore, event):
        if event.button != 3:
            return

        self._volmenu.popup(None, None, None, None, 0, event.time)

    def _cancel_clicked(self, src):
        ignore = src
        self.emit("cancel-clicked")


    ##############################
    # Connection event listeners #
    ##############################

    def _conn_state_changed(self, ignore=None):
        conn_active = self.conn.is_active()
        self.widget("pool-add").set_sensitive(conn_active and
            self.conn.is_storage_capable())

        if conn_active and not self.conn.is_storage_capable():
            self._set_storage_error_page(
                _("Libvirt connection does not support storage management."))

        if conn_active:
            uiutil.set_list_selection_by_number(self.widget("pool-list"), 0)
            return

        self._set_storage_error_page(_("Connection not active."))
        self._populate_pools()

    def _pool_changed(self, pool):
        self._update_pool_row(pool.get_connkey())

    def _conn_pool_count_changed(self, src, connkey):
        ignore = src
        ignore = connkey
        self._populate_pools()


    #########################
    # Pool action listeners #
    #########################

    def _pool_stop(self, src_ignore):
        pool = self._current_pool()
        if pool is None:
            return

        logging.debug("Stopping pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(pool.stop, [], self,
                            _("Error stopping pool '%s'") % pool.get_name())

    def _pool_start(self, src):
        ignore = src
        pool = self._current_pool()
        if pool is None:
            return

        logging.debug("Starting pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(pool.start, [], self,
                            _("Error starting pool '%s'") % pool.get_name())

    def _pool_add(self, src):
        ignore = src
        logging.debug("Launching 'Add Pool' wizard")

        try:
            if self._addpool is None:
                self._addpool = vmmCreatePool(self.conn)
                self._addpool.connect("pool-created", self._pool_created)
            self._addpool.show(self.topwin)
        except Exception as e:
            self.err.show_err(_("Error launching pool wizard: %s") % str(e))

    def _pool_delete(self, src):
        ignore = src
        pool = self._current_pool()
        if pool is None:
            return

        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the pool %s?") % pool.get_name())
        if not result:
            return

        logging.debug("Deleting pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(pool.delete, [], self,
                            _("Error deleting pool '%s'") % pool.get_name())

    def _pool_refresh(self, src):
        ignore = src
        if not self._confirm_changes():
            return

        pool = self._current_pool()
        if pool is None:
            return

        logging.debug("Refresh pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(pool.refresh, [], self,
                            _("Error refreshing pool '%s'") % pool.get_name())

    def _pool_apply(self):
        pool = self._current_pool()
        if pool is None:
            return

        logging.debug("Applying changes for pool '%s'", pool.get_name())
        try:
            if EDIT_POOL_AUTOSTART in self._active_edits:
                auto = self.widget("pool-autostart").get_active()
                pool.set_autostart(auto)
            if EDIT_POOL_NAME in self._active_edits:
                pool.define_name(self.widget("pool-name-entry").get_text())
                self.idle_add(self._populate_pools)
        except Exception as e:
            self.err.show_err(_("Error changing pool settings: %s") % str(e))
            return

        self._disable_pool_apply()


    ###########################
    # Volume action listeners #
    ###########################

    def _vol_copy_path(self, src):
        ignore = src
        vol = self._current_vol()
        if not vol:
            return

        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        target_path = vol.get_target_path()
        if target_path:
            clipboard.set_text(target_path, -1)

    def _vol_add(self, src):
        ignore = src
        pool = self._current_pool()
        if pool is None:
            return

        logging.debug("Launching 'Add Volume' wizard for pool '%s'",
                      pool.get_name())
        try:
            if self._addvol is None:
                self._addvol = vmmCreateVolume(self.conn, pool)
                self._addvol.connect("vol-created", self._vol_created)
            else:
                self._addvol.set_parent_pool(self.conn, pool)
            self._addvol.set_modal(self.topwin.get_modal())
            self._addvol.set_name_hint(self._name_hint)
            self._addvol.show(self.topwin)
        except Exception as e:
            self.err.show_err(_("Error launching volume wizard: %s") % str(e))

    def _vol_delete(self, src_ignore):
        vol = self._current_vol()
        if vol is None:
            return

        pool = self._current_pool()
        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the volume %s?") % vol.get_name())
        if not result:
            return

        def cb():
            vol.delete()
            def idlecb():
                pool.refresh()
            self.idle_add(idlecb)

        logging.debug("Deleting volume '%s'", vol.get_name())
        vmmAsyncJob.simple_async_noshow(cb, [], self,
                        _("Error deleting volume '%s'") % vol.get_name())

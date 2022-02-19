# Copyright (C) 2015 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository import Pango

from virtinst import DeviceDisk
from virtinst import log

from .lib import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI
from .createpool import vmmCreatePool
from .createvol import vmmCreateVolume
from .object.storagepool import vmmStoragePool
from .xmleditor import vmmXMLEditor


EDIT_POOL_IDS = (
EDIT_POOL_NAME,
EDIT_POOL_AUTOSTART,
EDIT_POOL_XML,
) = list(range(3))

VOL_NUM_COLUMNS = 7
(VOL_COLUMN_HANDLE,
 VOL_COLUMN_NAME,
 VOL_COLUMN_CAPACITY,
 VOL_COLUMN_SIZESTR,
 VOL_COLUMN_FORMAT,
 VOL_COLUMN_INUSEBY,
 VOL_COLUMN_SENSITIVE) = range(VOL_NUM_COLUMNS)

POOL_NUM_COLUMNS = 4
(POOL_COLUMN_HANDLE,
 POOL_COLUMN_LABEL,
 POOL_COLUMN_ISACTIVE,
 POOL_COLUMN_PERCENT) = range(POOL_NUM_COLUMNS)

ICON_RUNNING = "state_running"
ICON_SHUTOFF = "state_shutoff"


def _get_pool_size_percent(pool):
    cap = pool.get_capacity()
    alloc = pool.get_allocation()
    per = 0
    if cap and alloc is not None:
        per = int(((float(alloc) / float(cap)) * 100))
    return "<span size='small'>%s%%</span>" % int(per)


class vmmHostStorage(vmmGObjectUI):
    __gsignals__ = {
        "browse-clicked": (vmmGObjectUI.RUN_FIRST, None, []),
        "volume-chosen": (vmmGObjectUI.RUN_FIRST, None, [object]),
        "cancel-clicked": (vmmGObjectUI.RUN_FIRST, None, []),
    }

    def __init__(self, conn, builder, topwin, vol_sensitive_cb=None):
        vmmGObjectUI.__init__(self, "hoststorage.ui",
                              None, builder=builder, topwin=topwin)
        self.conn = conn

        # Callback function for setting volume row sensitivity. Used
        # by storage browser to disallow selecting certain volumes
        self._vol_sensitive_cb = vol_sensitive_cb

        # Name hint passed to addvol. Set by storagebrowser
        self._name_hint = None

        self._active_edits = set()
        self._addpool = None
        self._addvol = None
        self._volmenu = None
        self._xmleditor = None
        self.top_box = self.widget("storage-grid")

        self.builder.connect_signals({
            "on_pool_add_clicked": self._pool_add_cb,
            "on_pool_stop_clicked": self._pool_stop_cb,
            "on_pool_start_clicked": self._pool_start_cb,
            "on_pool_delete_clicked": self._pool_delete_cb,
            "on_pool_refresh_clicked": self._pool_refresh_cb,
            "on_pool_apply_clicked": (lambda *x: self._pool_apply()),

            "on_vol_delete_clicked": self._vol_delete_cb,
            "on_vol_list_button_press_event": self._vol_popup_menu_cb,
            "on_vol_list_changed": self._vol_selected_cb,
            "on_vol_add_clicked": self._vol_add_cb,

            "on_browse_cancel_clicked": self._cancel_clicked_cb,
            "on_browse_local_clicked": self._browse_local_clicked_cb,
            "on_choose_volume_clicked": self._choose_volume_clicked_cb,
            "on_vol_list_row_activated": self._vol_list_row_activated_cb,

            "on_pool_name_changed": (lambda *x:
                self._enable_pool_apply(EDIT_POOL_NAME)),
            "on_pool_autostart_toggled": self._pool_autostart_changed_cb,
        })

        self._init_ui()
        self._populate_pools()
        self._refresh_conn_state()
        self.conn.connect("pool-added", self._conn_pools_changed_cb)
        self.conn.connect("pool-removed", self._conn_pools_changed_cb)
        self.conn.connect("state-changed", self._conn_state_changed_cb)


    #######################
    # Standard UI methods #
    #######################

    def _cleanup(self):
        try:
            self.conn.disconnect_by_obj(self)
        except Exception:  # pragma: no cover
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

        self._xmleditor.cleanup()
        self._xmleditor = None

    def close(self, ignore1=None, ignore2=None):
        if self._addvol:
            self._addvol.close()
        if self._addpool:
            self._addpool.close()
        if self._volmenu:
            self._volmenu.hide()


    ###########
    # UI init #
    ###########

    def _cap_sort_func_cb(self, model, iter1, iter2, userdata):
        def _cmp(a, b):
            return ((a > b) - (a < b))

        return _cmp(int(model[iter1][VOL_COLUMN_CAPACITY]),
                    int(model[iter2][VOL_COLUMN_CAPACITY]))

    def _init_ui(self):
        self.widget("storage-pages").set_show_tabs(False)

        self._xmleditor = vmmXMLEditor(self.builder, self.topwin,
                self.widget("pool-details-align"),
                self.widget("pool-details"))
        self._xmleditor.connect("changed",
                lambda s: self._enable_pool_apply(EDIT_POOL_XML))
        self._xmleditor.connect("xml-requested",
                self._xmleditor_xml_requested_cb)
        self._xmleditor.connect("xml-reset",
                self._xmleditor_xml_reset_cb)

        # These are enabled in storagebrowser.py
        self.widget("browse-local").set_visible(False)
        self.widget("browse-cancel").set_visible(False)
        self.widget("choose-volume").set_visible(False)

        # Volume list popup menu
        self._volmenu = Gtk.Menu()
        volCopyPath = Gtk.MenuItem.new_with_mnemonic(_("Copy Volume Path"))
        volCopyPath.show()
        volCopyPath.connect("activate", self._vol_copy_path_cb)
        self._volmenu.add(volCopyPath)

        # Volume list
        # [obj, name, sizestr, capacity, format, in use by string, sensitive]
        volListModel = Gtk.ListStore(object, str, str, str, str, str, bool)
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
        volListModel.set_sort_func(VOL_COLUMN_CAPACITY, self._cap_sort_func_cb)

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
        # [pool object, label, pool.is_active(), percent string]
        pool_list = self.widget("pool-list")
        poolListModel = Gtk.ListStore(object, str, bool, str)
        pool_list.set_model(poolListModel)

        poolCol = Gtk.TreeViewColumn(_("Storage Pools"))
        pool_txt = Gtk.CellRendererText()
        pool_txt.set_property("ellipsize", Pango.EllipsizeMode.END)
        pool_per = Gtk.CellRendererText()
        poolCol.pack_start(pool_per, False)
        poolCol.pack_start(pool_txt, True)
        poolCol.add_attribute(pool_txt, 'markup', POOL_COLUMN_LABEL)
        poolCol.add_attribute(pool_txt, 'sensitive', POOL_COLUMN_ISACTIVE)
        poolCol.add_attribute(pool_per, 'markup', POOL_COLUMN_PERCENT)
        pool_list.append_column(poolCol)
        poolListModel.set_sort_column_id(POOL_COLUMN_LABEL,
            Gtk.SortType.ASCENDING)

        pool_list.get_selection().connect("changed", self._pool_selected_cb)
        pool_list.get_selection().set_select_function(
            (lambda *x: self._confirm_changes()), None)


    ###############
    # Public APIs #
    ###############

    def refresh_page(self):
        self._populate_vols()
        self.conn.schedule_priority_tick(pollpool=True)

    def set_name_hint(self, val):
        self._name_hint = val


    #################
    # UI populating #
    #################

    def _refresh_conn_state(self):
        conn_active = self.conn.is_active()
        self.widget("pool-add").set_sensitive(conn_active and
            self.conn.support.conn_storage())

        if conn_active and not self.conn.support.conn_storage():
            self._set_error_page(  # pragma: no cover
                _("Libvirt connection does not support storage management."))

        if conn_active:
            uiutil.set_list_selection_by_number(self.widget("pool-list"), 0)
            return

        self._populate_pools()
        self._set_error_page(_("Connection not active."))

    def _current_pool(self):
        return uiutil.get_list_selection(self.widget("pool-list"))

    def _current_vol(self):
        pool = self._current_pool()
        if not pool:
            return None  # pragma: no cover
        return uiutil.get_list_selection(self.widget("vol-list"))

    def _update_pool_row(self, pool):
        for row in self.widget("pool-list").get_model():
            if row[POOL_COLUMN_HANDLE] != pool:
                continue

            # Update active sensitivity and percent available for passed key
            row[POOL_COLUMN_ISACTIVE] = pool.is_active()
            row[POOL_COLUMN_PERCENT] = _get_pool_size_percent(pool)
            break

        curpool = self._current_pool()
        if curpool == pool:
            self._refresh_current_pool()

    def _populate_pool_state(self, pool):
        auto = pool.get_autostart()
        active = pool.is_active()

        # Set pool details state
        self.widget("pool-details").set_sensitive(True)
        self.widget("pool-name-entry").set_text(pool.get_name())
        self.widget("pool-name-entry").set_editable(not active)
        self.widget("pool-sizes").set_markup(
                _("%(bytesfree)s Free / <i>%(bytesinuse)s In Use</i>") %
                {"bytesfree": pool.get_pretty_available(),
                 "bytesinuse": pool.get_pretty_allocation()})
        self.widget("pool-location").set_text(
                pool.get_target_path())
        self.widget("pool-state-icon").set_from_icon_name(
                ((active and ICON_RUNNING) or ICON_SHUTOFF),
                Gtk.IconSize.BUTTON)
        self.widget("pool-state").set_text(pool.run_status())
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

        if (active and
            not vmmStoragePool.supports_volume_creation(pool.get_type())):
            self.widget("vol-add").set_sensitive(False)
            self.widget("vol-add").set_tooltip_text(
                _("Pool does not support volume creation"))

        self._xmleditor.set_xml_from_libvirtobject(pool)

    def _set_error_page(self, msg):
        self.widget("storage-pages").set_current_page(1)
        self.widget("storage-error-label").set_text(msg)
        self.widget("pool-delete").set_sensitive(False)
        self.widget("pool-stop").set_sensitive(False)
        self.widget("pool-start").set_sensitive(False)
        self._disable_pool_apply()

    def _refresh_current_pool(self):
        pool = self._current_pool()
        if not pool:
            self._set_error_page(_("No storage pool selected."))
            return

        self.widget("storage-pages").set_current_page(0)

        try:
            self._populate_pool_state(pool)
        except Exception as e:  # pragma: no cover
            log.exception(e)
            self._set_error_page(_("Error selecting pool: %s") % e)
        self._disable_pool_apply()

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
                pool.disconnect_by_obj(self)
                pool.connect("state-changed", self._pool_changed_cb)
                pool.connect("refreshed", self._pool_changed_cb)

                name = pool.get_name()
                typ = vmmStoragePool.pretty_type(pool.get_type())
                label = "%s\n<span size='small'>%s</span>" % (name, typ)

                row = [None] * POOL_NUM_COLUMNS
                row[POOL_COLUMN_HANDLE] = pool
                row[POOL_COLUMN_LABEL] = label
                row[POOL_COLUMN_ISACTIVE] = pool.is_active()
                row[POOL_COLUMN_PERCENT] = _get_pool_size_percent(pool)

                model.append(row)
        finally:
            pool_list.set_model(model)

        uiutil.set_list_selection(pool_list, curpool)

    def _populate_vols(self):
        list_widget = self.widget("vol-list")
        pool = self._current_pool()
        vols = pool and pool.get_volumes() or []
        model = list_widget.get_model()
        list_widget.get_selection().unselect_all()
        model.clear()

        vadj = self.widget("vol-scroll").get_vadjustment()
        vscroll_percent = vadj.get_value() // max(vadj.get_upper(), 1)

        for vol in vols:
            try:
                path = vol.get_target_path()
                name = vol.get_pretty_name(pool.get_type())
                cap = str(vol.get_capacity())
                sizestr = vol.get_pretty_capacity()
                fmt = vol.get_format() or ""
            except Exception:  # pragma: no cover
                log.debug("Error getting volume info for '%s', "
                              "hiding it", vol, exc_info=True)
                continue

            namestr = None
            try:
                if path:
                    names = DeviceDisk.path_in_use_by(vol.conn.get_backend(),
                                                       path)
                    namestr = ", ".join(names)
                    if not namestr:
                        namestr = None
            except Exception:  # pragma: no cover
                log.exception("Failed to determine if storage volume in "
                                  "use.")

            sensitive = True
            if self._vol_sensitive_cb:
                sensitive = self._vol_sensitive_cb(fmt)

            row = [None] * VOL_NUM_COLUMNS
            row[VOL_COLUMN_HANDLE] = vol
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


    ##########################
    # Pool lifecycle actions #
    ##########################

    def _pool_stop_cb(self, src):
        pool = self._current_pool()
        if pool is None:
            return  # pragma: no cover

        log.debug("Stopping pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(pool.stop, [], self,
                            _("Error stopping pool '%s'") % pool.get_name())

    def _pool_start_cb(self, src):
        pool = self._current_pool()
        if pool is None:
            return  # pragma: no cover

        log.debug("Starting pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(pool.start, [], self,
                            _("Error starting pool '%s'") % pool.get_name())

    def _pool_add_cb(self, src):
        log.debug("Launching 'Add Pool' wizard")

        try:
            if self._addpool is None:
                self._addpool = vmmCreatePool(self.conn)
            self._addpool.show(self.topwin)
        except Exception as e:  # pragma: no cover
            self.err.show_err(_("Error launching pool wizard: %s") % str(e))

    def _pool_delete_cb(self, src):
        pool = self._current_pool()
        if pool is None:
            return  # pragma: no cover

        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the pool %s?") % pool.get_name())
        if not result:
            return

        log.debug("Deleting pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(pool.delete, [], self,
                            _("Error deleting pool '%s'") % pool.get_name())

    def _pool_refresh_cb(self, src):
        pool = self._current_pool()
        if pool is None:
            return  # pragma: no cover

        self._confirm_changes()

        log.debug("Refresh pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(pool.refresh, [], self,
                            _("Error refreshing pool '%s'") % pool.get_name())


    ###########################
    # Volume action listeners #
    ###########################

    def _vol_copy_path_cb(self, src):
        vol = self._current_vol()
        if not vol:
            return  # pragma: no cover

        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        target_path = vol.get_target_path()
        if target_path:
            clipboard.set_text(target_path, -1)

    def _vol_add_cb(self, src):
        pool = self._current_pool()
        if pool is None:
            return  # pragma: no cover

        log.debug("Launching 'Add Volume' wizard for pool '%s'",
                      pool.get_name())
        try:
            if self._addvol is None:
                self._addvol = vmmCreateVolume(self.conn, pool)
                self._addvol.connect("vol-created", self._vol_created_cb)
            else:
                self._addvol.set_parent_pool(pool)
            self._addvol.set_modal(self.topwin.get_modal())
            self._addvol.set_name_hint(self._name_hint)
            self._addvol.show(self.topwin)
        except Exception as e:  # pragma: no cover
            self.err.show_err(_("Error launching volume wizard: %s") % str(e))

    def _vol_delete_cb(self, src):
        vol = self._current_vol()
        if vol is None:
            return  # pragma: no cover

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

        log.debug("Deleting volume '%s'", vol.get_name())
        vmmAsyncJob.simple_async_noshow(cb, [], self,
                        _("Error deleting volume '%s'") % vol.get_name())


    #############################
    # pool apply/config actions #
    #############################

    def _pool_apply(self):
        pool = self._current_pool()
        if pool is None:
            return  # pragma: no cover

        log.debug("Applying changes for pool '%s'", pool.get_name())
        try:
            if EDIT_POOL_AUTOSTART in self._active_edits:
                auto = self.widget("pool-autostart").get_active()
                pool.set_autostart(auto)

            if EDIT_POOL_NAME in self._active_edits:
                pool.define_name(self.widget("pool-name-entry").get_text())
                self.idle_add(self._populate_pools)

            if EDIT_POOL_XML in self._active_edits:
                pool.define_xml(self._xmleditor.get_xml())
        except Exception as e:
            self.err.show_err(_("Error changing pool settings: %s") % str(e))
            return

        self._disable_pool_apply()

    def _enable_pool_apply(self, edittype):
        self._active_edits.add(edittype)
        self.widget("pool-apply").set_sensitive(True)
        self._xmleditor.details_changed = True

    def _disable_pool_apply(self):
        self._active_edits = set()
        self.widget("pool-apply").set_sensitive(False)
        self._xmleditor.details_changed = False

    def _confirm_changes(self):
        if (self.is_visible() and
            self._active_edits and
            self.err.confirm_unapplied_changes()):
            self._pool_apply()

        self._disable_pool_apply()
        return True


    #############
    # Listeners #
    #############

    def _browse_local_clicked_cb(self, src):
        self.emit("browse-clicked")

    def _choose_volume_clicked_cb(self, src):
        self.emit("volume-chosen", self._current_vol())

    def _vol_list_row_activated_cb(self, src, treeiter, viewcol):
        self.emit("volume-chosen", self._current_vol())

    def _vol_created_cb(self, src, pool, vol):
        # The vol list will have already been updated, since this
        # signal arrives only after pool-refreshed. So all we do here is
        # select the vol we just created.
        curpool = self._current_pool()
        if curpool != pool:
            return  # pragma: no cover
        uiutil.set_list_selection(self.widget("vol-list"), vol)

    def _pool_autostart_changed_cb(self, src):
        self._enable_pool_apply(EDIT_POOL_AUTOSTART)

    def _vol_selected_cb(self, src):
        model, treeiter = src.get_selected()
        self.widget("vol-delete").set_sensitive(bool(treeiter))

        can_choose = bool(treeiter and model[treeiter][VOL_COLUMN_SENSITIVE])
        self.widget("choose-volume").set_sensitive(can_choose)

    def _vol_popup_menu_cb(self, src, event):
        if event.button != 3:
            return

        self._volmenu.popup_at_pointer(event)

    def _cancel_clicked_cb(self, src):
        self.emit("cancel-clicked")

    def _pool_changed_cb(self, pool):
        self._update_pool_row(pool)

    def _conn_state_changed_cb(self, conn):
        self._refresh_conn_state()

    def _conn_pools_changed_cb(self, src, pool):
        self._populate_pools()

    def _pool_selected_cb(self, selection):
        self._refresh_current_pool()

    def _xmleditor_xml_requested_cb(self, src):
        self._refresh_current_pool()

    def _xmleditor_xml_reset_cb(self, src):
        self._refresh_current_pool()

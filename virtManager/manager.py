#
# Copyright (C) 2006-2008, 2013-2014 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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

from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf

import libvirt

from virtinst import util

from . import vmmenu
from . import uiutil
from .baseclass import vmmGObjectUI
from .graphwidgets import CellRendererSparkline

# Number of data points for performance graphs
GRAPH_LEN = 40

# fields in the tree model data set
(ROW_HANDLE,
ROW_SORT_KEY,
ROW_MARKUP,
ROW_STATUS_ICON,
ROW_HINT,
ROW_IS_CONN,
ROW_IS_CONN_CONNECTED,
ROW_IS_VM,
ROW_IS_VM_RUNNING,
ROW_COLOR,
ROW_INSPECTION_OS_ICON) = range(11)

# Columns in the tree view
(COL_NAME,
COL_GUEST_CPU,
COL_HOST_CPU,
COL_MEM,
COL_DISK,
COL_NETWORK) = range(6)


def _style_get_prop(widget, propname):
    value = GObject.Value()
    value.init(GObject.TYPE_INT)
    widget.style_get_property(propname, value)
    return value.get_int()


def _get_inspection_icon_pixbuf(vm, w, h):
    # libguestfs gives us the PNG data as a string.
    png_data = vm.inspection.icon
    if png_data is None:
        return None

    try:
        pb = GdkPixbuf.PixbufLoader()
        pb.set_size(w, h)
        pb.write(png_data)
        pb.close()
        return pb.get_pixbuf()
    except:
        logging.exception("Error loading inspection icon data")
        vm.inspection.icon = None
        return None


class vmmManager(vmmGObjectUI):
    __gsignals__ = {
        "action-show-connect": (GObject.SignalFlags.RUN_FIRST, None, []),
        "action-show-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-show-about": (GObject.SignalFlags.RUN_FIRST, None, []),
        "action-show-host": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "action-show-preferences": (GObject.SignalFlags.RUN_FIRST, None, []),
        "action-show-create": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "action-suspend-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-resume-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-run-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-shutdown-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-reset-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-reboot-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-destroy-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-save-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-migrate-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-delete-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-clone-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-exit-app": (GObject.SignalFlags.RUN_FIRST, None, []),
        "manager-closed": (GObject.SignalFlags.RUN_FIRST, None, []),
        "manager-opened": (GObject.SignalFlags.RUN_FIRST, None, []),
        "remove-conn": (GObject.SignalFlags.RUN_FIRST, None, [str]),
    }

    def __init__(self):
        vmmGObjectUI.__init__(self, "manager.ui", "vmm-manager")

        # Mapping of rowkey -> tree model rows to
        # allow O(1) access instead of O(n)
        self.rows = {}

        w, h = self.config.get_manager_window_size()
        self.topwin.set_default_size(w or 550, h or 550)
        self.prev_position = None
        self._window_size = None

        self.vmmenu = vmmenu.VMActionMenu(self, self.current_vm)
        self.connmenu = Gtk.Menu()
        self.connmenu_items = {}

        self.builder.connect_signals({
            "on_menu_view_guest_cpu_usage_activate":
                    self.toggle_stats_visible_guest_cpu,
            "on_menu_view_host_cpu_usage_activate":
                    self.toggle_stats_visible_host_cpu,
            "on_menu_view_memory_usage_activate":
                    self.toggle_stats_visible_memory_usage,
            "on_menu_view_disk_io_activate" :
                    self.toggle_stats_visible_disk,
            "on_menu_view_network_traffic_activate":
                    self.toggle_stats_visible_network,

            "on_vm_manager_delete_event": self.close,
            "on_vmm_manager_configure_event": self.window_resized,
            "on_menu_file_add_connection_activate": self.new_conn,
            "on_menu_new_vm_activate": self.new_vm,
            "on_menu_file_quit_activate": self.exit_app,
            "on_menu_file_close_activate": self.close,
            "on_vmm_close_clicked": self.close,
            "on_vm_open_clicked": self.show_vm,
            "on_vm_run_clicked": self.start_vm,
            "on_vm_new_clicked": self.new_vm,
            "on_vm_shutdown_clicked": self.poweroff_vm,
            "on_vm_pause_clicked": self.pause_vm_button,
            "on_menu_edit_details_activate": self.show_vm,
            "on_menu_edit_delete_activate": self.do_delete,
            "on_menu_host_details_activate": self.show_host,

            "on_vm_list_row_activated": self.show_vm,
            "on_vm_list_button_press_event": self.popup_vm_menu_button,
            "on_vm_list_key_press_event": self.popup_vm_menu_key,

            "on_menu_edit_preferences_activate": self.show_preferences,
            "on_menu_help_about_activate": self.show_about,
        })

        # There seem to be ref counting issues with calling
        # list.get_column, so avoid it
        self.diskcol = None
        self.netcol = None
        self.memcol = None
        self.guestcpucol = None
        self.hostcpucol = None
        self.spacer_txt = None
        self.init_vmlist()

        self.init_stats()
        self.init_toolbar()
        self.init_context_menus()

        self.update_current_selection()
        self.widget("vm-list").get_selection().connect(
            "changed", self.update_current_selection)

        self.max_disk_rate = 10.0
        self.max_net_rate = 10.0

        # Initialize stat polling columns based on global polling
        # preferences (we want signal handlers for this)
        self.enable_polling(COL_GUEST_CPU)
        self.enable_polling(COL_DISK)
        self.enable_polling(COL_NETWORK)
        self.enable_polling(COL_MEM)


    ##################
    # Common methods #
    ##################

    def show(self):
        vis = self.is_visible()
        self.topwin.present()
        if vis:
            return

        logging.debug("Showing manager")
        if self.prev_position:
            self.topwin.move(*self.prev_position)
            self.prev_position = None

        self.emit("manager-opened")

    def close(self, src_ignore=None, src2_ignore=None):
        if not self.is_visible():
            return

        logging.debug("Closing manager")
        self.prev_position = self.topwin.get_position()
        self.topwin.hide()
        self.emit("manager-closed")

        return 1


    def _cleanup(self):
        self.rows = None

        self.diskcol = None
        self.guestcpucol = None
        self.memcol = None
        self.hostcpucol = None
        self.netcol = None

        self.vmmenu.destroy()
        self.vmmenu = None
        self.connmenu.destroy()
        self.connmenu = None
        self.connmenu_items = None

        if self._window_size:
            self.config.set_manager_window_size(*self._window_size)


    def is_visible(self):
        return bool(self.topwin.get_visible())

    def set_startup_error(self, msg):
        self.widget("vm-notebook").set_current_page(1)
        self.widget("startup-error-label").set_text(msg)

    ################
    # Init methods #
    ################

    def init_stats(self):
        self.add_gsettings_handle(
            self.config.on_vmlist_guest_cpu_usage_visible_changed(
                                self.toggle_guest_cpu_usage_visible_widget))
        self.add_gsettings_handle(
            self.config.on_vmlist_host_cpu_usage_visible_changed(
                                self.toggle_host_cpu_usage_visible_widget))
        self.add_gsettings_handle(
            self.config.on_vmlist_memory_usage_visible_changed(
                                self.toggle_memory_usage_visible_widget))
        self.add_gsettings_handle(
            self.config.on_vmlist_disk_io_visible_changed(
                                self.toggle_disk_io_visible_widget))
        self.add_gsettings_handle(
            self.config.on_vmlist_network_traffic_visible_changed(
                                self.toggle_network_traffic_visible_widget))

        # Register callbacks with the global stats enable/disable values
        # that disable the associated vmlist widgets if reporting is disabled
        self.add_gsettings_handle(
            self.config.on_stats_enable_cpu_poll_changed(
                self.enable_polling, COL_GUEST_CPU))
        self.add_gsettings_handle(
            self.config.on_stats_enable_disk_poll_changed(
                self.enable_polling, COL_DISK))
        self.add_gsettings_handle(
            self.config.on_stats_enable_net_poll_changed(
                self.enable_polling, COL_NETWORK))
        self.add_gsettings_handle(
            self.config.on_stats_enable_memory_poll_changed(
                self.enable_polling, COL_MEM))

        self.toggle_guest_cpu_usage_visible_widget()
        self.toggle_host_cpu_usage_visible_widget()
        self.toggle_memory_usage_visible_widget()
        self.toggle_disk_io_visible_widget()
        self.toggle_network_traffic_visible_widget()


    def init_toolbar(self):
        self.widget("vm-new").set_icon_name("vm_new")
        self.widget("vm-open").set_icon_name("icon_console")

        menu = vmmenu.VMShutdownMenu(self, self.current_vm)
        self.widget("vm-shutdown").set_icon_name("system-shutdown")
        self.widget("vm-shutdown").set_menu(menu)

        tool = self.widget("vm-toolbar")
        tool.set_property("icon-size", Gtk.IconSize.LARGE_TOOLBAR)
        for c in tool.get_children():
            c.set_homogeneous(False)

    def init_context_menus(self):
        def add_to_menu(idx, text, icon, cb):
            if text[0:3] == 'gtk':
                item = Gtk.ImageMenuItem.new_from_stock(text, None)
            else:
                item = Gtk.ImageMenuItem.new_with_mnemonic(text)
            if icon:
                item.set_image(icon)
            if cb:
                item.connect("activate", cb)
            self.connmenu.add(item)
            self.connmenu_items[idx] = item

        # Build connection context menu
        add_to_menu("create", Gtk.STOCK_NEW, None, self.new_vm)
        add_to_menu("connect", Gtk.STOCK_CONNECT, None, self.open_conn)
        add_to_menu("disconnect", Gtk.STOCK_DISCONNECT, None,
                      self.close_conn)
        self.connmenu.add(Gtk.SeparatorMenuItem())
        add_to_menu("delete", Gtk.STOCK_DELETE, None, self.do_delete)
        self.connmenu.add(Gtk.SeparatorMenuItem())
        add_to_menu("details", _("D_etails"), None, self.show_host)
        self.connmenu.show_all()

    def init_vmlist(self):
        vmlist = self.widget("vm-list")
        self.widget("vm-notebook").set_show_tabs(False)

        rowtypes = []
        rowtypes.insert(ROW_HANDLE, object)  # backing object
        rowtypes.insert(ROW_SORT_KEY, str)  # object name
        rowtypes.insert(ROW_MARKUP, str)  # row markup text
        rowtypes.insert(ROW_STATUS_ICON, str)  # status icon name
        rowtypes.insert(ROW_HINT, str)  # row tooltip
        rowtypes.insert(ROW_IS_CONN, bool)  # if object is a connection
        rowtypes.insert(ROW_IS_CONN_CONNECTED, bool)  # if conn is connected
        rowtypes.insert(ROW_IS_VM, bool)  # if row is VM
        rowtypes.insert(ROW_IS_VM_RUNNING, bool)  # if VM is running
        rowtypes.insert(ROW_COLOR, str)  # row markup color string
        rowtypes.insert(ROW_INSPECTION_OS_ICON, GdkPixbuf.Pixbuf)  # OS icon

        model = Gtk.TreeStore(*rowtypes)
        vmlist.set_model(model)
        vmlist.set_tooltip_column(ROW_HINT)
        vmlist.set_headers_visible(True)
        vmlist.set_level_indentation(
                -(_style_get_prop(vmlist, "expander-size") + 3))

        nameCol = Gtk.TreeViewColumn(_("Name"))
        nameCol.set_expand(True)
        nameCol.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
        nameCol.set_spacing(6)
        nameCol.set_sort_column_id(COL_NAME)

        vmlist.append_column(nameCol)

        status_icon = Gtk.CellRendererPixbuf()
        status_icon.set_property("stock-size", Gtk.IconSize.DND)
        nameCol.pack_start(status_icon, False)
        nameCol.add_attribute(status_icon, 'icon-name', ROW_STATUS_ICON)
        nameCol.add_attribute(status_icon, 'visible', ROW_IS_VM)

        inspection_os_icon = Gtk.CellRendererPixbuf()
        nameCol.pack_start(inspection_os_icon, False)
        nameCol.add_attribute(inspection_os_icon, 'pixbuf',
                                ROW_INSPECTION_OS_ICON)
        nameCol.add_attribute(inspection_os_icon, 'visible', ROW_IS_VM)

        name_txt = Gtk.CellRendererText()
        nameCol.pack_start(name_txt, True)
        nameCol.add_attribute(name_txt, 'markup', ROW_MARKUP)
        nameCol.add_attribute(name_txt, 'foreground', ROW_COLOR)

        self.spacer_txt = Gtk.CellRendererText()
        self.spacer_txt.set_property("ypad", 4)
        self.spacer_txt.set_property("visible", False)
        nameCol.pack_end(self.spacer_txt, False)

        def make_stats_column(title, colnum):
            col = Gtk.TreeViewColumn(title)
            col.set_min_width(140)

            txt = Gtk.CellRendererText()
            txt.set_property("ypad", 4)
            col.pack_start(txt, True)
            col.add_attribute(txt, 'visible', ROW_IS_CONN)

            img = CellRendererSparkline()
            img.set_property("xpad", 6)
            img.set_property("ypad", 12)
            img.set_property("reversed", True)
            col.pack_start(img, True)
            col.add_attribute(img, 'visible', ROW_IS_VM)

            col.set_sort_column_id(colnum)
            vmlist.append_column(col)
            return col

        self.guestcpucol = make_stats_column(_("CPU usage"), COL_GUEST_CPU)
        self.hostcpucol = make_stats_column(_("Host CPU usage"), COL_HOST_CPU)
        self.memcol = make_stats_column(_("Memory usage"), COL_MEM)
        self.diskcol = make_stats_column(_("Disk I/O"), COL_DISK)
        self.netcol = make_stats_column(_("Network I/O"), COL_NETWORK)

        model.set_sort_func(COL_NAME, self.vmlist_name_sorter)
        model.set_sort_func(COL_GUEST_CPU, self.vmlist_guest_cpu_usage_sorter)
        model.set_sort_func(COL_HOST_CPU, self.vmlist_host_cpu_usage_sorter)
        model.set_sort_func(COL_MEM, self.vmlist_memory_usage_sorter)
        model.set_sort_func(COL_DISK, self.vmlist_disk_io_sorter)
        model.set_sort_func(COL_NETWORK, self.vmlist_network_usage_sorter)
        model.set_sort_column_id(COL_NAME, Gtk.SortType.ASCENDING)

    ##################
    # Helper methods #
    ##################

    def current_row(self):
        return uiutil.get_list_selected_row(self.widget("vm-list"))

    def current_vm(self):
        row = self.current_row()
        if not row or row[ROW_IS_CONN]:
            return None

        return row[ROW_HANDLE]

    def current_conn(self):
        row = self.current_row()
        if not row:
            return None

        handle = row[ROW_HANDLE]
        if row[ROW_IS_CONN]:
            return handle
        else:
            return handle.conn

    def current_conn_uri(self, default_selection=False):
        vmlist = self.widget("vm-list")
        model = vmlist.get_model()

        conn = self.current_conn()
        if conn is None and default_selection:
            # Nothing selected, use first connection row
            for row in model:
                if row[ROW_IS_CONN]:
                    conn = row[ROW_HANDLE]
                    break

        if conn:
            return conn.get_uri()
        return None

    ####################
    # Action listeners #
    ####################

    def window_resized(self, ignore, ignore2):
        if not self.is_visible():
            return
        self._window_size = self.topwin.get_size()

    def exit_app(self, src_ignore=None, src2_ignore=None):
        self.emit("action-exit-app")

    def new_conn(self, src_ignore=None):
        self.emit("action-show-connect")

    def new_vm(self, src_ignore=None):
        self.emit("action-show-create", self.current_conn_uri())

    def show_about(self, src_ignore):
        self.emit("action-show-about")

    def show_preferences(self, src_ignore):
        self.emit("action-show-preferences")

    def show_host(self, src_ignore):
        uri = self.current_conn_uri(default_selection=True)
        self.emit("action-show-host", uri)

    def show_vm(self, ignore, ignore2=None, ignore3=None):
        conn = self.current_conn()
        vm = self.current_vm()
        if conn is None:
            return

        if vm:
            self.emit("action-show-domain", conn.get_uri(), vm.get_connkey())
        else:
            if not self.open_conn():
                self.emit("action-show-host", conn.get_uri())

    def do_delete(self, ignore=None):
        conn = self.current_conn()
        vm = self.current_vm()
        if vm is None:
            self._do_delete_conn(conn)
        else:
            self.emit("action-delete-domain", conn.get_uri(), vm.get_connkey())

    def _do_delete_conn(self, conn):
        if conn is None:
            return

        result = self.err.yes_no(_("This will remove the connection:\n\n%s\n\n"
                                   "Are you sure?") % conn.get_uri())
        if not result:
            return

        self.emit("remove-conn", conn.get_uri())

    def set_pause_state(self, state):
        src = self.widget("vm-pause")
        try:
            src.handler_block_by_func(self.pause_vm_button)
            src.set_active(state)
        finally:
            src.handler_unblock_by_func(self.pause_vm_button)

    def pause_vm_button(self, src):
        do_pause = src.get_active()

        # Set button state back to original value: just let the status
        # update function fix things for us
        self.set_pause_state(not do_pause)

        if do_pause:
            self.pause_vm(None)
        else:
            self.resume_vm(None)

    def start_vm(self, ignore):
        vm = self.current_vm()
        if vm is None:
            return
        self.emit("action-run-domain", vm.conn.get_uri(), vm.get_connkey())

    def poweroff_vm(self, ignore):
        vm = self.current_vm()
        if vm is None:
            return
        self.emit("action-shutdown-domain",
            vm.conn.get_uri(), vm.get_connkey())

    def pause_vm(self, ignore):
        vm = self.current_vm()
        if vm is None:
            return
        self.emit("action-suspend-domain", vm.conn.get_uri(), vm.get_connkey())

    def resume_vm(self, ignore):
        vm = self.current_vm()
        if vm is None:
            return
        self.emit("action-resume-domain", vm.conn.get_uri(), vm.get_connkey())

    def close_conn(self, ignore):
        conn = self.current_conn()
        if not conn.is_disconnected():
            conn.close()

    def open_conn(self, ignore=None):
        conn = self.current_conn()
        if conn.is_disconnected():
            conn.open()
            return True


    ####################################
    # VM add/remove management methods #
    ####################################

    def vm_row_key(self, vm):
        return vm.get_uuid() + ":" + vm.conn.get_uri()

    def vm_added(self, conn, connkey):
        vm = conn.get_vm(connkey)
        if not vm:
            return

        row_key = self.vm_row_key(vm)
        if row_key in self.rows:
            return

        row = self._build_row(None, vm)
        parent = self.rows[conn.get_uri()].iter
        model = self.widget("vm-list").get_model()
        _iter = model.append(parent, row)
        path = model.get_path(_iter)
        self.rows[row_key] = model[path]

        vm.connect("state-changed", self.vm_changed)
        vm.connect("resources-sampled", self.vm_row_updated)
        vm.connect("inspection-changed", self.vm_inspection_changed)

        # Expand a connection when adding a vm to it
        self.widget("vm-list").expand_row(model.get_path(parent), False)

    def vm_removed(self, conn, connkey):
        vmlist = self.widget("vm-list")
        model = vmlist.get_model()

        parent = self.rows[conn.get_uri()].iter
        for row in range(model.iter_n_children(parent)):
            vm = model[model.iter_nth_child(parent, row)][ROW_HANDLE]
            if vm.get_connkey() == connkey:
                model.remove(model.iter_nth_child(parent, row))
                del self.rows[self.vm_row_key(vm)]
                break

    def _build_conn_hint(self, conn):
        hint = conn.get_uri()
        if conn.is_disconnected():
            hint += " (%s)" % _("Double click to connect")
        return hint

    def _build_conn_markup(self, conn, name):
        name = util.xml_escape(name)
        text = name
        if conn.is_disconnected():
            text += " - " + _("Not Connected")
        elif conn.is_connecting():
            text += " - " + _("Connecting...")

        markup = "<span size='smaller'>%s</span>" % text
        return markup

    def _build_conn_color(self, conn):
        color = "#000000"
        if conn.is_disconnected():
            color = "#5b5b5b"
        return color

    def _build_vm_markup(self, name, status):
        domtext     = ("<span size='smaller' weight='bold'>%s</span>" %
                       util.xml_escape(name))
        statetext   = "<span size='smaller'>%s</span>" % status
        return domtext + "\n" + statetext

    def _build_row(self, conn, vm):
        if conn:
            name = conn.get_pretty_desc()
            markup = self._build_conn_markup(conn, name)
            status = ("<span size='smaller'>%s</span>" %
                      conn.get_state_text())
            status_icon = None
            hint = self._build_conn_hint(conn)
            color = self._build_conn_color(conn)
            os_icon = None
        else:
            name = vm.get_name_or_title()
            status = vm.run_status()
            markup = self._build_vm_markup(name, status)
            status_icon = vm.run_status_icon_name()
            hint = vm.get_description()
            color = None
            os_icon = _get_inspection_icon_pixbuf(vm, 16, 16)

        row = []
        row.insert(ROW_HANDLE, conn or vm)
        row.insert(ROW_SORT_KEY, name)
        row.insert(ROW_MARKUP, markup)
        row.insert(ROW_STATUS_ICON, status_icon)
        row.insert(ROW_HINT, util.xml_escape(hint))
        row.insert(ROW_IS_CONN, bool(conn))
        row.insert(ROW_IS_CONN_CONNECTED,
                   bool(conn) and not conn.is_disconnected())
        row.insert(ROW_IS_VM, bool(vm))
        row.insert(ROW_IS_VM_RUNNING, bool(vm) and vm.is_active())
        row.insert(ROW_COLOR, color)
        row.insert(ROW_INSPECTION_OS_ICON, os_icon)

        return row

    def add_conn(self, engine_ignore, conn):
        # Called from engine.py signal conn-added

        # Make sure error page isn't showing
        self.widget("vm-notebook").set_current_page(0)

        if conn.get_uri() in self.rows:
            return

        model = self.widget("vm-list").get_model()
        row = self._build_row(conn, None)
        _iter = model.append(None, row)
        path = model.get_path(_iter)
        self.rows[conn.get_uri()] = model[path]

        conn.connect("vm-added", self.vm_added)
        conn.connect("vm-removed", self.vm_removed)
        conn.connect("resources-sampled", self.conn_row_updated)
        conn.connect("state-changed", self.conn_state_changed)

    def remove_conn(self, engine_ignore, uri):
        # Called from engine.py signal conn-removed

        model = self.widget("vm-list").get_model()
        parent = self.rows[uri].iter

        if parent is None:
            return

        child = model.iter_children(parent)
        while child is not None:
            del self.rows[self.vm_row_key(model[child][ROW_HANDLE])]
            model.remove(child)
            child = model.iter_children(parent)
        model.remove(parent)

        del self.rows[uri]


    #############################
    # State/UI updating methods #
    #############################

    def vm_row_updated(self, vm):
        row = self.rows.get(self.vm_row_key(vm), None)
        if row is None:
            return
        self.widget("vm-list").get_model().row_changed(row.path, row.iter)

    def vm_changed(self, vm):
        row = self.rows.get(self.vm_row_key(vm), None)
        if row is None:
            return

        try:
            if vm == self.current_vm():
                self.update_current_selection()

            name = vm.get_name_or_title()
            status = vm.run_status()

            row[ROW_SORT_KEY] = name
            row[ROW_STATUS_ICON] = vm.run_status_icon_name()
            row[ROW_IS_VM_RUNNING] = vm.is_active()
            row[ROW_MARKUP] = self._build_vm_markup(name, status)

            desc = vm.get_description()
            row[ROW_HINT] = util.xml_escape(desc)
        except libvirt.libvirtError, e:
            if util.exception_is_libvirt_error(e, "VIR_ERR_NO_DOMAIN"):
                return
            raise

        self.vm_row_updated(vm)

    def vm_inspection_changed(self, vm):
        row = self.rows.get(self.vm_row_key(vm), None)
        if row is None:
            return

        new_icon = _get_inspection_icon_pixbuf(vm, 16, 16)
        row[ROW_INSPECTION_OS_ICON] = new_icon

        self.vm_row_updated(vm)

    def set_initial_selection(self, uri):
        vmlist = self.widget("vm-list")
        model = vmlist.get_model()
        it = model.get_iter_first()
        selected = None
        while it:
            key = model.get_value(it, ROW_HANDLE)

            if key.get_uri() == uri:
                vmlist.get_selection().select_iter(it)
                return

            if not selected:
                vmlist.get_selection().select_iter(it)
                selected = key
            elif key.get_autoconnect() and not selected.get_autoconnect():
                vmlist.get_selection().select_iter(it)
                selected = key
                if not uri:
                    return

            it = model.iter_next(it)

    def conn_state_changed(self, conn):
        row = self.rows[conn.get_uri()]
        row[ROW_SORT_KEY] = conn.get_pretty_desc()
        row[ROW_MARKUP] = self._build_conn_markup(conn, row[ROW_SORT_KEY])
        row[ROW_IS_CONN_CONNECTED] = not conn.is_disconnected()
        row[ROW_COLOR] = self._build_conn_color(conn)
        row[ROW_HINT] = self._build_conn_hint(conn)

        if not conn.is_active():
            # Connection went inactive, delete any VM child nodes
            parent = row.iter
            if parent is not None:
                model = self.widget("vm-list").get_model()
                child = model.iter_children(parent)
                while child is not None:
                    vm = model[child][ROW_HANDLE]
                    del self.rows[self.vm_row_key(vm)]
                    model.remove(child)
                    child = model.iter_children(parent)

        self.conn_row_updated(conn)
        self.update_current_selection()

    def conn_row_updated(self, conn):
        row = self.rows[conn.get_uri()]

        self.max_disk_rate = max(self.max_disk_rate, conn.disk_io_max_rate())
        self.max_net_rate = max(self.max_net_rate,
                                conn.network_traffic_max_rate())

        self.widget("vm-list").get_model().row_changed(row.path, row.iter)

    def change_run_text(self, can_restore):
        if can_restore:
            text = _("_Restore")
        else:
            text = _("_Run")
        strip_text = text.replace("_", "")

        self.vmmenu.change_run_text(text)
        self.widget("vm-run").set_label(strip_text)

    def update_current_selection(self, ignore=None):
        vm = self.current_vm()

        show_open = bool(vm)
        show_details = bool(vm)
        host_details = bool(len(self.rows))

        show_run = bool(vm and vm.is_runable())
        is_paused = bool(vm and vm.is_paused())
        if is_paused:
            show_pause = bool(vm and vm.is_unpauseable())
        else:
            show_pause = bool(vm and vm.is_pauseable())
        show_shutdown = bool(vm and vm.is_stoppable())

        if vm and vm.managedsave_supported:
            self.change_run_text(vm.has_managed_save())

        self.widget("vm-open").set_sensitive(show_open)
        self.widget("vm-run").set_sensitive(show_run)
        self.widget("vm-shutdown").set_sensitive(show_shutdown)
        self.widget("vm-shutdown").get_menu().update_widget_states(vm)

        self.set_pause_state(is_paused)
        self.widget("vm-pause").set_sensitive(show_pause)

        if is_paused:
            pauseTooltip = _("Resume the virtual machine")
        else:
            pauseTooltip = _("Pause the virtual machine")
        self.widget("vm-pause").set_tooltip_text(pauseTooltip)

        self.widget("menu_edit_details").set_sensitive(show_details)
        self.widget("menu_host_details").set_sensitive(host_details)

    def popup_vm_menu_key(self, widget_ignore, event):
        if Gdk.keyval_name(event.keyval) != "Menu":
            return False

        model, treeiter = self.widget("vm-list").get_selection().get_selected()
        self.popup_vm_menu(model, treeiter, event)
        return True

    def popup_vm_menu_button(self, widget, event):
        if event.button != 3:
            return False

        tup = widget.get_path_at_pos(int(event.x), int(event.y))
        if tup is None:
            return False
        path = tup[0]
        model = widget.get_model()
        _iter = model.get_iter(path)

        self.popup_vm_menu(model, _iter, event)
        return False

    def popup_vm_menu(self, model, _iter, event):
        if model.iter_parent(_iter) is not None:
            # Popup the vm menu
            vm = model[_iter][ROW_HANDLE]
            self.vmmenu.update_widget_states(vm)
            self.vmmenu.popup(None, None, None, None, 0, event.time)
        else:
            # Pop up connection menu
            conn = model[_iter][ROW_HANDLE]
            disconn = conn.is_disconnected()
            conning = conn.is_connecting()

            self.connmenu_items["create"].set_sensitive(not disconn)
            self.connmenu_items["disconnect"].set_sensitive(not (disconn or
                                                                 conning))
            self.connmenu_items["connect"].set_sensitive(disconn)
            self.connmenu_items["delete"].set_sensitive(disconn)

            self.connmenu.popup(None, None, None, None, 0, event.time)


    #################
    # Stats methods #
    #################

    def vmlist_name_sorter(self, model, iter1, iter2, ignore):
        key1 = str(model[iter1][ROW_SORT_KEY]).lower()
        key2 = str(model[iter2][ROW_SORT_KEY]).lower()
        return cmp(key1, key2)

    def vmlist_guest_cpu_usage_sorter(self, model, iter1, iter2, ignore):
        obj1 = model[iter1][ROW_HANDLE]
        obj2 = model[iter2][ROW_HANDLE]

        return cmp(obj1.guest_cpu_time_percentage(),
                   obj2.guest_cpu_time_percentage())

    def vmlist_host_cpu_usage_sorter(self, model, iter1, iter2, ignore):
        obj1 = model[iter1][ROW_HANDLE]
        obj2 = model[iter2][ROW_HANDLE]

        return cmp(obj1.host_cpu_time_percentage(),
                   obj2.host_cpu_time_percentage())

    def vmlist_memory_usage_sorter(self, model, iter1, iter2, ignore):
        obj1 = model[iter1][ROW_HANDLE]
        obj2 = model[iter2][ROW_HANDLE]

        return cmp(obj1.stats_memory(),
                   obj2.stats_memory())

    def vmlist_disk_io_sorter(self, model, iter1, iter2, ignore):
        obj1 = model[iter1][ROW_HANDLE]
        obj2 = model[iter2][ROW_HANDLE]

        return cmp(obj1.disk_io_rate(), obj2.disk_io_rate())

    def vmlist_network_usage_sorter(self, model, iter1, iter2, ignore):
        obj1 = model[iter1][ROW_HANDLE]
        obj2 = model[iter2][ROW_HANDLE]

        return cmp(obj1.network_traffic_rate(), obj2.network_traffic_rate())

    def enable_polling(self, column):
        # pylint: disable=redefined-variable-type
        if column == COL_GUEST_CPU:
            widgn = ["menu_view_stats_guest_cpu", "menu_view_stats_host_cpu"]
            do_enable = self.config.get_stats_enable_cpu_poll()
        if column == COL_DISK:
            widgn = "menu_view_stats_disk"
            do_enable = self.config.get_stats_enable_disk_poll()
        elif column == COL_NETWORK:
            widgn = "menu_view_stats_network"
            do_enable = self.config.get_stats_enable_net_poll()
        elif column == COL_MEM:
            widgn = "menu_view_stats_memory"
            do_enable = self.config.get_stats_enable_memory_poll()

        for w in util.listify(widgn):
            widget = self.widget(w)
            tool_text = ""

            if do_enable:
                widget.set_sensitive(True)
            else:
                if widget.get_active():
                    widget.set_active(False)
                widget.set_sensitive(False)
                tool_text = _("Disabled in preferences dialog.")
            widget.set_tooltip_text(tool_text)

    def _toggle_graph_helper(self, do_show, col, datafunc, menu):
        img = -1
        for child in col.get_cells():
            if isinstance(child, CellRendererSparkline):
                img = child
        datafunc = do_show and datafunc or None

        col.set_cell_data_func(img, datafunc, None)
        col.set_visible(do_show)
        self.widget(menu).set_active(do_show)

        any_visible = any([c.get_visible() for c in
            [self.netcol, self.diskcol, self.memcol,
             self.guestcpucol, self.hostcpucol]])
        self.spacer_txt.set_property("visible", not any_visible)

    def toggle_network_traffic_visible_widget(self):
        self._toggle_graph_helper(
            self.config.is_vmlist_network_traffic_visible(), self.netcol,
            self.network_traffic_img, "menu_view_stats_network")
    def toggle_disk_io_visible_widget(self):
        self._toggle_graph_helper(
            self.config.is_vmlist_disk_io_visible(), self.diskcol,
            self.disk_io_img, "menu_view_stats_disk")
    def toggle_memory_usage_visible_widget(self):
        self._toggle_graph_helper(
            self.config.is_vmlist_memory_usage_visible(), self.memcol,
            self.memory_usage_img, "menu_view_stats_memory")
    def toggle_guest_cpu_usage_visible_widget(self):
        self._toggle_graph_helper(
            self.config.is_vmlist_guest_cpu_usage_visible(), self.guestcpucol,
            self.guest_cpu_usage_img, "menu_view_stats_guest_cpu")
    def toggle_host_cpu_usage_visible_widget(self):
        self._toggle_graph_helper(
            self.config.is_vmlist_host_cpu_usage_visible(), self.hostcpucol,
            self.host_cpu_usage_img, "menu_view_stats_host_cpu")

    def toggle_stats_visible(self, src, stats_id):
        visible = src.get_active()
        set_stats = {
            COL_GUEST_CPU: self.config.set_vmlist_guest_cpu_usage_visible,
            COL_HOST_CPU: self.config.set_vmlist_host_cpu_usage_visible,
            COL_MEM: self.config.set_vmlist_memory_usage_visible,
            COL_DISK: self.config.set_vmlist_disk_io_visible,
            COL_NETWORK: self.config.set_vmlist_network_traffic_visible,
        }
        set_stats[stats_id](visible)

    def toggle_stats_visible_guest_cpu(self, src):
        self.toggle_stats_visible(src, COL_GUEST_CPU)
    def toggle_stats_visible_host_cpu(self, src):
        self.toggle_stats_visible(src, COL_HOST_CPU)
    def toggle_stats_visible_memory_usage(self, src):
        self.toggle_stats_visible(src, COL_MEM)
    def toggle_stats_visible_disk(self, src):
        self.toggle_stats_visible(src, COL_DISK)
    def toggle_stats_visible_network(self, src):
        self.toggle_stats_visible(src, COL_NETWORK)

    def guest_cpu_usage_img(self, column_ignore, cell, model, _iter, data):
        obj = model[_iter][ROW_HANDLE]
        if obj is None or not hasattr(obj, "conn"):
            return

        data = obj.guest_cpu_time_vector(GRAPH_LEN)
        cell.set_property('data_array', data)

    def host_cpu_usage_img(self, column_ignore, cell, model, _iter, data):
        obj = model[_iter][ROW_HANDLE]
        if obj is None or not hasattr(obj, "conn"):
            return

        data = obj.host_cpu_time_vector(GRAPH_LEN)
        cell.set_property('data_array', data)

    def memory_usage_img(self, column_ignore, cell, model, _iter, data):
        obj = model[_iter][ROW_HANDLE]
        if obj is None or not hasattr(obj, "conn"):
            return

        data = obj.stats_memory_vector(GRAPH_LEN)
        cell.set_property('data_array', data)

    def disk_io_img(self, column_ignore, cell, model, _iter, data):
        obj = model[_iter][ROW_HANDLE]
        if obj is None or not hasattr(obj, "conn"):
            return

        d1, d2 = obj.disk_io_vectors(GRAPH_LEN, self.max_disk_rate)
        data = [(x + y) / 2 for x, y in zip(d1, d2)]
        cell.set_property('data_array', data)

    def network_traffic_img(self, column_ignore, cell, model, _iter, data):
        obj = model[_iter][ROW_HANDLE]
        if obj is None or not hasattr(obj, "conn"):
            return

        d1, d2 = obj.network_traffic_vectors(GRAPH_LEN, self.max_net_rate)
        data = [(x + y) / 2 for x, y in zip(d1, d2)]
        cell.set_property('data_array', data)

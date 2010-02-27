#
# Copyright (C) 2006-2008 Red Hat, Inc.
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

import gobject
import gtk
import gtk.glade
import logging
import traceback

import virtManager.config as cfg
import virtManager.uihelpers as uihelpers
from virtManager.connection import vmmConnection
from virtManager.asyncjob import vmmAsyncJob
from virtManager.error import vmmErrorDialog
from virtManager.delete import vmmDeleteDialog
from virtManager.graphwidgets import CellRendererSparkline
from virtManager import util as util


# fields in the tree model data set
ROW_HANDLE = 0
ROW_NAME = 1
ROW_MARKUP = 2
ROW_STATUS = 3
ROW_STATUS_ICON = 4
ROW_KEY = 5
ROW_HINT = 6
ROW_IS_CONN = 7
ROW_IS_CONN_CONNECTED = 8
ROW_IS_VM = 9
ROW_IS_VM_RUNNING = 10
ROW_COLOR = 11

# Columns in the tree view
COL_NAME = 0
COL_CPU = 1
COL_DISK = 2
COL_NETWORK = 3

rcstring = """
style "toolbar-style" {
    #GtkToolbar::button_relief = GTK_RELIEF_NONE
    #GtkToolbar::shadow_type = GTK_SHADOW_NONE
    GtkToolbar::internal_padding = 2
}
style "treeview-style" {
    GtkTreeView::indent_expanders = 0
}

class "GtkToolbar" style "toolbar-style"
class "GtkTreeView" style "treeview-style"
"""
gtk.rc_parse_string(rcstring)


class vmmManager(gobject.GObject):
    __gsignals__ = {
        "action-show-connect":(gobject.SIGNAL_RUN_FIRST,
                                  gobject.TYPE_NONE, []),
        "action-show-console": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-terminal": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-refresh-console": (gobject.SIGNAL_RUN_FIRST,
                                   gobject.TYPE_NONE, (str,str)),
        "action-refresh-terminal": (gobject.SIGNAL_RUN_FIRST,
                                    gobject.TYPE_NONE, (str,str)),
        "action-show-details": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-about": (gobject.SIGNAL_RUN_FIRST,
                              gobject.TYPE_NONE, []),
        "action-show-host": (gobject.SIGNAL_RUN_FIRST,
                              gobject.TYPE_NONE, [str]),
        "action-show-preferences": (gobject.SIGNAL_RUN_FIRST,
                                    gobject.TYPE_NONE, []),
        "action-show-create": (gobject.SIGNAL_RUN_FIRST,
                               gobject.TYPE_NONE, [str]),
        "action-suspend-domain": (gobject.SIGNAL_RUN_FIRST,
                                  gobject.TYPE_NONE, (str, str)),
        "action-resume-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str, str)),
        "action-run-domain": (gobject.SIGNAL_RUN_FIRST,
                              gobject.TYPE_NONE, (str, str)),
        "action-shutdown-domain": (gobject.SIGNAL_RUN_FIRST,
                                   gobject.TYPE_NONE, (str, str)),
        "action-reboot-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str, str)),
        "action-destroy-domain": (gobject.SIGNAL_RUN_FIRST,
                                  gobject.TYPE_NONE, (str, str)),
        "action-connect": (gobject.SIGNAL_RUN_FIRST,
                           gobject.TYPE_NONE, [str]),
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                               gobject.TYPE_NONE, [str]),
        "action-migrate-domain": (gobject.SIGNAL_RUN_FIRST,
                                  gobject.TYPE_NONE, (str,str)),
        "action-clone-domain": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-exit-app": (gobject.SIGNAL_RUN_FIRST,
                            gobject.TYPE_NONE, []),}

    def __init__(self, config, engine):
        self.__gobject_init__()
        self.window = gtk.glade.XML((config.get_glade_dir() +
                                     "/vmm-manager.glade"),
                                     "vmm-manager", domain="virt-manager")
        self.err = vmmErrorDialog(self.window.get_widget("vmm-manager"),
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))
        self.topwin = self.window.get_widget("vmm-manager")

        self.config = config
        self.engine = engine

        self.delete_dialog = None
        self.startup_error = None
        self.ignore_pause = False

        # Mapping of VM UUID -> tree model rows to
        # allow O(1) access instead of O(n)
        self.rows = {}

        w, h = self.config.get_manager_window_size()
        self.topwin.set_default_size(w or 550, h or 550)

        self.init_vmlist()
        self.init_stats()
        self.init_toolbar()

        self.vmmenu = gtk.Menu()
        self.vmmenushutdown = gtk.Menu()
        self.vmmenu_items = {}
        self.vmmenushutdown_items = {}
        self.connmenu = gtk.Menu()
        self.connmenu_items = {}
        self.init_context_menus()

        self.window.signal_autoconnect({
            "on_menu_view_cpu_usage_activate":  (self.toggle_stats_visible,
                                                    cfg.STATS_CPU),
            "on_menu_view_disk_io_activate" :   (self.toggle_stats_visible,
                                                    cfg.STATS_DISK),
            "on_menu_view_network_traffic_activate": (self.toggle_stats_visible,
                                                cfg.STATS_NETWORK),

            "on_vm_manager_delete_event": self.close,
            "on_vmm_manager_configure_event": self.window_resized,
            "on_menu_file_add_connection_activate": self.new_connection,
            "on_menu_file_quit_activate": self.exit_app,
            "on_menu_file_close_activate": self.close,
            "on_menu_restore_saved_activate": self.restore_saved,
            "on_vmm_close_clicked": self.close,
            "on_vm_open_clicked": self.open_vm_console,
            "on_vm_run_clicked": self.start_vm,
            "on_vm_new_clicked": self.new_vm,
            "on_vm_shutdown_clicked": self.poweroff_vm,
            "on_vm_pause_clicked": self.pause_vm_button,
            "on_menu_edit_details_activate": self.open_vm_console,
            "on_menu_edit_delete_activate": self.do_delete,
            "on_menu_host_details_activate": self.show_host,

            "on_vm_list_row_activated": self.open_vm_console,
            "on_vm_list_button_press_event": self.popup_vm_menu_button,
            "on_vm_list_key_press_event": self.popup_vm_menu_key,

            "on_menu_edit_preferences_activate": self.show_preferences,
            "on_menu_help_about_activate": self.show_about,
            "on_menu_help_activate": self.show_help,
            })

        # XXX: Help docs useless/out of date
        self.window.get_widget("menu_help").hide()

        self.vm_selected()
        self.window.get_widget("vm-list").get_selection().connect("changed",
                                                            self.vm_selected)

        # Initialize stat polling columns based on global polling
        # preferences (we want signal handlers for this)
        for typ, init_val in \
            [ (cfg.STATS_DISK,
               self.config.get_stats_enable_disk_poll()),
              (cfg.STATS_NETWORK,
               self.config.get_stats_enable_net_poll())]:
            self.enable_polling(None, None, init_val, typ)

        self.engine.connect("connection-added", self._add_connection)
        self.engine.connect("connection-removed", self._remove_connection)

        # Select first list entry
        vmlist = self.window.get_widget("vm-list")
        if len(vmlist.get_model()) == 0:
            self.startup_error = _("Could not populate a default connection. "
                                   "Make sure the appropriate virtualization "
                                   "packages are installed (kvm, qemu, etc.) "
                                   "and that libvirtd has been restarted to "
                                   "notice the changes.\n\n"
                                   "A hypervisor connection can be manually "
                                   "added via \nFile->Add Connection")
        else:
            vmlist.get_selection().select_iter(vmlist.get_model().get_iter_first())

    ##################
    # Common methods #
    ##################

    def show(self):
        if self.is_visible():
            self.topwin.present()
            return
        self.topwin.present()

        self.engine.increment_window_counter()

        if self.startup_error:
            self.err.val_err(_("Error determining default hypervisor."),
                             self.startup_error, _("Startup Error"))
            self.startup_error = None

    def close(self, src=None, src2=None):
        if self.is_visible():
            win = self.window.get_widget("vmm-manager")
            win.hide()
            self.engine.decrement_window_counter()
            return 1

    def is_visible(self):
        if self.window.get_widget("vmm-manager").flags() & gtk.VISIBLE:
            return 1
        return 0


    ################
    # Init methods #
    ################

    def init_stats(self):
        self.config.on_vmlist_cpu_usage_visible_changed(
                                    self.toggle_cpu_usage_visible_widget)
        self.config.on_vmlist_disk_io_visible_changed(
                                    self.toggle_disk_io_visible_widget)
        self.config.on_vmlist_network_traffic_visible_changed(
                                    self.toggle_network_traffic_visible_widget)

        # Register callbacks with the global stats enable/disable values
        # that disable the associated vmlist widgets if reporting is disabled
        self.config.on_stats_enable_disk_poll_changed(self.enable_polling,
                                                      cfg.STATS_DISK)
        self.config.on_stats_enable_net_poll_changed(self.enable_polling,
                                                     cfg.STATS_NETWORK)

        self.window.get_widget("menu_view_stats_cpu").set_active(
                            self.config.is_vmlist_cpu_usage_visible())
        self.window.get_widget("menu_view_stats_disk").set_active(
                            self.config.is_vmlist_disk_io_visible())
        self.window.get_widget("menu_view_stats_network").set_active(
                            self.config.is_vmlist_network_traffic_visible())

    def init_toolbar(self):
        def set_toolbar_image(widget, iconfile, l, w):
            filename = self.config.get_icon_dir() + "/%s" % iconfile
            pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(filename, l, w)
            image = gtk.Image()
            image.set_from_pixbuf(pixbuf)
            image.show_all()
            self.window.get_widget(widget).set_icon_widget(image)

        set_toolbar_image("vm-new", "vm_new_wizard.png", 28, 28)
        set_toolbar_image("vm-open", "icon_console.png", 24, 24)
        uihelpers.build_shutdown_button_menu(
                                   self.config,
                                   self.window.get_widget("vm-shutdown"),
                                   self.poweroff_vm,
                                   self.reboot_vm,
                                   self.destroy_vm)

        tool = self.window.get_widget("vm-toolbar")
        util.safe_set_prop(tool, "icon-size", gtk.ICON_SIZE_LARGE_TOOLBAR)
        for c in tool.get_children():
            c.set_homogeneous(False)

    def init_context_menus(self):
        def build_icon(name):
            return gtk.image_new_from_icon_name(name, gtk.ICON_SIZE_MENU)

        def build_stock(name):
            return gtk.image_new_from_stock(name, gtk.ICON_SIZE_MENU)

        icon_name = self.config.get_shutdown_icon_name()
        shutdownmenu_icon   = build_icon(icon_name)
        reboot_icon         = build_icon(icon_name)
        shutdown_icon       = build_icon(icon_name)
        destroy_icon        = build_icon(icon_name)
        run_icon            = build_stock(gtk.STOCK_MEDIA_PLAY)
        pause_icon          = build_stock(gtk.STOCK_MEDIA_PAUSE)
        resume_icon         = build_stock(gtk.STOCK_MEDIA_PAUSE)
        delete_icon         = build_stock(gtk.STOCK_DELETE)

        self.vmmenu_items["run"] = gtk.ImageMenuItem(_("_Run"))
        self.vmmenu_items["run"].set_image(run_icon)
        self.vmmenu_items["run"].show()
        self.vmmenu_items["run"].connect("activate", self.start_vm)
        self.vmmenu.add(self.vmmenu_items["run"])

        self.vmmenu_items["pause"] = gtk.ImageMenuItem(_("_Pause"))
        self.vmmenu_items["pause"].set_image(pause_icon)
        self.vmmenu_items["pause"].set_sensitive(False)
        self.vmmenu_items["pause"].show()
        self.vmmenu_items["pause"].connect("activate", self.pause_vm)
        self.vmmenu.add(self.vmmenu_items["pause"])

        self.vmmenu_items["resume"] = gtk.ImageMenuItem(_("R_esume"))
        self.vmmenu_items["resume"].set_image(resume_icon)
        self.vmmenu_items["resume"].show()
        self.vmmenu_items["resume"].connect("activate", self.resume_vm)
        self.vmmenu.add(self.vmmenu_items["resume"])


        self.vmmenu_items["shutdown"] = gtk.ImageMenuItem(_("_Shut Down"))
        self.vmmenu_items["shutdown"].set_image(shutdownmenu_icon)
        self.vmmenu_items["shutdown"].set_submenu(self.vmmenushutdown)
        self.vmmenu_items["shutdown"].show()
        self.vmmenu.add(self.vmmenu_items["shutdown"])

        self.vmmenushutdown_items["reboot"] = gtk.ImageMenuItem(_("_Reboot"))
        self.vmmenushutdown_items["reboot"].set_image(reboot_icon)
        self.vmmenushutdown_items["reboot"].show()
        self.vmmenushutdown_items["reboot"].connect("activate", self.reboot_vm)
        self.vmmenushutdown.add(self.vmmenushutdown_items["reboot"])

        self.vmmenushutdown_items["poweroff"] = gtk.ImageMenuItem(_("_Shut Down"))
        self.vmmenushutdown_items["poweroff"].set_image(shutdown_icon)
        self.vmmenushutdown_items["poweroff"].show()
        self.vmmenushutdown_items["poweroff"].connect("activate",
                                                      self.poweroff_vm)
        self.vmmenushutdown.add(self.vmmenushutdown_items["poweroff"])

        self.vmmenushutdown_items["forcepoweroff"] = gtk.ImageMenuItem(_("_Force Off"))
        self.vmmenushutdown_items["forcepoweroff"].set_image(destroy_icon)
        self.vmmenushutdown_items["forcepoweroff"].show()
        self.vmmenushutdown_items["forcepoweroff"].connect("activate",
                                                           self.destroy_vm)
        self.vmmenushutdown.add(self.vmmenushutdown_items["forcepoweroff"])

        self.vmmenu_items["hsep1"] = gtk.SeparatorMenuItem()
        self.vmmenu_items["hsep1"].show()
        self.vmmenu.add(self.vmmenu_items["hsep1"])

        self.vmmenu_items["clone"] = gtk.ImageMenuItem("_Clone")
        self.vmmenu_items["clone"].show()
        self.vmmenu_items["clone"].connect("activate", self.open_clone_window)
        self.vmmenu.add(self.vmmenu_items["clone"])

        self.vmmenu_items["migrate"] = gtk.ImageMenuItem(_("_Migrate..."))
        self.vmmenu_items["migrate"].show()
        self.vmmenu_items["migrate"].connect("activate", self.migrate_vm)
        self.vmmenu.add(self.vmmenu_items["migrate"])

        self.vmmenu_items["delete"] = gtk.ImageMenuItem("_Delete")
        self.vmmenu_items["delete"].set_image(delete_icon)
        self.vmmenu_items["delete"].show()
        self.vmmenu_items["delete"].connect("activate", self.do_delete)
        self.vmmenu.add(self.vmmenu_items["delete"])

        self.vmmenu_items["hsep2"] = gtk.SeparatorMenuItem()
        self.vmmenu_items["hsep2"].show()
        self.vmmenu.add(self.vmmenu_items["hsep2"])

        self.vmmenu_items["open"] = gtk.ImageMenuItem(gtk.STOCK_OPEN)
        self.vmmenu_items["open"].connect("activate", self.open_vm_console)
        self.vmmenu_items["open"].show()
        self.vmmenu.add(self.vmmenu_items["open"])

        self.vmmenu.show()

        self.connmenu_items["create"] = gtk.ImageMenuItem(gtk.STOCK_NEW)
        self.connmenu_items["create"].show()
        self.connmenu_items["create"].connect("activate", self.new_vm)
        self.connmenu.add(self.connmenu_items["create"])

        self.connmenu_items["connect"] = gtk.ImageMenuItem(gtk.STOCK_CONNECT)
        self.connmenu_items["connect"].show()
        self.connmenu_items["connect"].connect("activate",
                                               self.open_connection)
        self.connmenu.add(self.connmenu_items["connect"])

        self.connmenu_items["disconnect"] = gtk.ImageMenuItem(gtk.STOCK_DISCONNECT)
        self.connmenu_items["disconnect"].show()
        self.connmenu_items["disconnect"].connect("activate",
                                                  self.close_connection)
        self.connmenu.add(self.connmenu_items["disconnect"])

        self.connmenu_items["hsep1"] = gtk.SeparatorMenuItem()
        self.connmenu_items["hsep1"].show()
        self.connmenu.add(self.connmenu_items["hsep1"])

        self.connmenu_items["delete"] = gtk.ImageMenuItem(gtk.STOCK_DELETE)
        self.connmenu_items["delete"].show()
        self.connmenu_items["delete"].connect("activate",
                                              self.do_delete)
        self.connmenu.add(self.connmenu_items["delete"])

        self.connmenu_items["hsep2"] = gtk.SeparatorMenuItem()
        self.connmenu_items["hsep2"].show()
        self.connmenu.add(self.connmenu_items["hsep2"])

        self.connmenu_items["details"] = gtk.ImageMenuItem(_("_Details"))
        self.connmenu_items["details"].connect("activate", self.show_host)
        self.connmenu_items["details"].show()
        self.connmenu.add(self.connmenu_items["details"])

        self.connmenu.show()

    def init_vmlist(self):
        vmlist = self.window.get_widget("vm-list")

        # Handle, name, markup, status, status icon, key/uuid, hint, is conn,
        # is conn connected, is vm, is vm running, fg color
        model = gtk.TreeStore(object, str, str, str, gtk.gdk.Pixbuf, str, str,
                              bool, bool, bool, bool, gtk.gdk.Color)
        vmlist.set_model(model)
        util.tooltip_wrapper(vmlist, ROW_HINT, "set_tooltip_column")

        vmlist.set_headers_visible(True)
        if hasattr(vmlist, "set_level_indentation"):
            vmlist.set_level_indentation(-15)

        nameCol = gtk.TreeViewColumn(_("Name"))
        nameCol.set_expand(True)
        nameCol.set_spacing(6)
        cpuUsageCol = gtk.TreeViewColumn(_("CPU usage"))
        diskIOCol = gtk.TreeViewColumn(_("Disk I/O"))
        networkTrafficCol = gtk.TreeViewColumn(_("Network I/O"))

        cpuUsageCol.set_min_width(140)
        diskIOCol.set_min_width(140)
        networkTrafficCol.set_min_width(140)

        statusCol = nameCol
        vmlist.append_column(nameCol)
        vmlist.append_column(cpuUsageCol)
        vmlist.append_column(diskIOCol)
        vmlist.append_column(networkTrafficCol)

        # For the columns which follow, we deliberately bind columns
        # to fields in the list store & on each update copy the info
        # out of the vmmDomain object into the store. Although this
        # sounds foolish, empirically this is faster than using the
        # set_cell_data_func() callbacks to pull the data out of
        # vmmDomain on demand. I suspect this is because the latter
        # needs to do many transitions  C<->Python for callbacks
        # which are relatively slow.

        status_icon = gtk.CellRendererPixbuf()
        statusCol.pack_start(status_icon, False)
        statusCol.add_attribute(status_icon, 'pixbuf', ROW_STATUS_ICON)
        statusCol.add_attribute(status_icon, 'visible', ROW_IS_VM)

        name_txt = gtk.CellRendererText()
        nameCol.pack_start(name_txt, True)
        nameCol.add_attribute(name_txt, 'markup', ROW_MARKUP)
        nameCol.add_attribute(name_txt, 'foreground-gdk', ROW_COLOR)
        nameCol.set_sort_column_id(COL_NAME)

        cpuUsage_txt = gtk.CellRendererText()
        cpuUsage_img = CellRendererSparkline()
        cpuUsage_img.set_property("xpad", 6)
        cpuUsage_img.set_property("ypad", 12)
        cpuUsage_img.set_property("reversed", True)
        cpuUsageCol.pack_start(cpuUsage_img, True)
        cpuUsageCol.pack_start(cpuUsage_txt, False)
        cpuUsageCol.add_attribute(cpuUsage_img, 'visible', ROW_IS_VM)
        cpuUsageCol.add_attribute(cpuUsage_txt, 'visible', ROW_IS_CONN)
        cpuUsageCol.set_cell_data_func(cpuUsage_img, self.cpu_usage_img, None)
        cpuUsageCol.set_visible(self.config.is_vmlist_cpu_usage_visible())
        cpuUsageCol.set_sort_column_id(COL_CPU)

        diskIO_img = CellRendererSparkline()
        diskIO_img.set_property("xpad", 6)
        diskIO_img.set_property("ypad", 12)
        diskIO_img.set_property("reversed", True)
        diskIOCol.pack_start(diskIO_img, True)
        diskIOCol.add_attribute(diskIO_img, 'visible', ROW_IS_VM)
        diskIOCol.set_cell_data_func(diskIO_img, self.disk_io_img, None)
        diskIOCol.set_visible(self.config.is_vmlist_disk_io_visible())
        diskIOCol.set_sort_column_id(COL_DISK)

        networkTraffic_img = CellRendererSparkline()
        networkTraffic_img.set_property("xpad", 6)
        networkTraffic_img.set_property("ypad", 12)
        networkTraffic_img.set_property("reversed", True)
        networkTrafficCol.pack_start(networkTraffic_img, True)
        networkTrafficCol.add_attribute(networkTraffic_img, 'visible', ROW_IS_VM)
        networkTrafficCol.set_cell_data_func(networkTraffic_img,
                                             self.network_traffic_img, None)
        networkTrafficCol.set_visible(self.config.is_vmlist_network_traffic_visible())
        networkTrafficCol.set_sort_column_id(COL_NETWORK)

        model.set_sort_func(COL_NAME, self.vmlist_name_sorter)
        model.set_sort_func(COL_CPU, self.vmlist_cpu_usage_sorter)
        model.set_sort_func(COL_DISK, self.vmlist_disk_io_sorter)
        model.set_sort_func(COL_NETWORK, self.vmlist_network_usage_sorter)

        model.set_sort_column_id(COL_NAME, gtk.SORT_ASCENDING)


    ##################
    # Helper methods #
    ##################

    def current_row(self):
        vmlist = self.window.get_widget("vm-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()

        treestore, treeiter = active
        if treeiter != None:
            return treestore[treeiter]
        return None

    def current_vm(self):
        row = self.current_row()
        if not row or row[ROW_IS_CONN]:
            return None

        return row[ROW_HANDLE]

    def current_connection(self):
        row = self.current_row()
        if not row:
            return None

        handle = row[ROW_HANDLE]
        if row[ROW_IS_CONN]:
            return handle
        else:
            return handle.get_connection()

    def current_vmuuid(self):
        vm = self.current_vm()
        if vm is None:
            return None
        return vm.get_uuid()

    def current_connection_uri(self):
        conn = self.current_connection()
        if conn is None:
            return None
        return conn.get_uri()

    ####################
    # Action listeners #
    ####################

    def window_resized(self, ignore, event):
        # Sometimes dimensions change when window isn't visible
        if not self.is_visible():
            return

        self.config.set_manager_window_size(event.width, event.height)

    def exit_app(self, src=None, src2=None):
        self.emit("action-exit-app")

    def new_connection(self, src=None):
        self.emit("action-show-connect")

    def new_vm(self, ignore=None):
        self.emit("action-show-create", self.current_connection_uri())

    def show_about(self, src):
        self.emit("action-show-about")

    def show_help(self, src):
        self.emit("action-show-help", None)

    def show_preferences(self, src):
        self.emit("action-show-preferences")

    def show_host(self, src):
        self.emit("action-show-host", self.current_connection_uri())

    def open_vm_console(self,ignore,ignore2=None,ignore3=None):
        if self.current_vmuuid():
            self.emit("action-show-console",
                      self.current_connection_uri(), self.current_vmuuid())
        elif self.current_connection():
            if not self.open_connection():
                self.emit("action-show-host", self.current_connection_uri())

    def open_clone_window(self, ignore1=None, ignore2=None, ignore3=None):
        if self.current_vmuuid():
            self.emit("action-clone-domain", self.current_connection_uri(),
                      self.current_vmuuid())

    def show_vm_details(self,ignore):
        conn = self.current_connection()
        if conn is None:
            return
        vm = self.current_vm()
        if vm is None:
            self.emit("action-show-host", conn.get_uri())
        else:
            self.emit("action-show-console",
                      conn.get_uri(), self.vm.get_uuid())

    def restore_saved(self, src=None):
        conn = self.current_connection()
        if conn.is_remote():
            self.err.val_err(_("Restoring virtual machines over remote "
                               "connections is not yet supported"))
            return

        path = util.browse_local(self.window.get_widget("vmm-manager"),
                                 _("Restore Virtual Machine"),
                                 self.config, conn,
                                 browse_reason=self.config.CONFIG_DIR_RESTORE)

        if not path:
            return

        progWin = vmmAsyncJob(self.config, self.restore_saved_callback,
                              [path], _("Restoring Virtual Machine"))
        progWin.run()
        error, details = progWin.get_error()

        if error is not None:
            self.err.show_err(error, details,
                              title=_("Error restoring domain"))

    def restore_saved_callback(self, file_to_load, asyncjob):
        try:
            newconn = util.dup_conn(self.config, self.current_connection(),
                                    return_conn_class=True)
            newconn.restore(file_to_load)
        except Exception, e:
            err = (_("Error restoring domain '%s': %s") %
                                  (file_to_load, str(e)))
            details = "".join(traceback.format_exc())
            asyncjob.set_error(err, details)

    def do_delete(self, ignore=None):
        conn = self.current_connection()
        vm = self.current_vm()
        if vm is None:
            self._do_delete_connection(conn)
        else:
            self._do_delete_vm(vm)

    def _do_delete_connection(self, conn):
        if conn is None:
            return

        result = self.err.yes_no(_("This will remove the connection:\n\n%s\n\n"
                                   "Are you sure?") % conn.get_uri())
        if not result:
            return
        self.engine.remove_connection(conn.get_uri())

    def _do_delete_vm(self, vm):
        if vm.is_active():
            return

        if not self.delete_dialog:
            self.delete_dialog = vmmDeleteDialog(self.config, vm)
        else:
            self.delete_dialog.set_vm(vm)

        self.delete_dialog.show()

    def set_pause_state(self, state):
        src = self.window.get_widget("vm-pause")
        try:
            self.ignore_pause = True
            src.set_active(state)
        finally:
            self.ignore_pause = False

    def pause_vm_button(self, src):
        if self.ignore_pause:
            return

        do_pause = src.get_active()

        if do_pause:
            self.pause_vm(None)
        else:
            self.resume_vm(None)

        # Set button state back to original value: just let the status
        # update function fix things for us
        self.set_pause_state(not do_pause)

    def start_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-run-domain",
                      vm.get_connection().get_uri(), vm.get_uuid())

    def reboot_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-reboot-domain",
                      vm.get_connection().get_uri(), vm.get_uuid())

    def poweroff_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-shutdown-domain",
                      vm.get_connection().get_uri(), vm.get_uuid())

    def destroy_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-destroy-domain",
                      vm.get_connection().get_uri(), vm.get_uuid())

    def pause_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-suspend-domain",
                      vm.get_connection().get_uri(), vm.get_uuid())

    def resume_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-resume-domain",
                      vm.get_connection().get_uri(), vm.get_uuid())

    def migrate_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-migrate-domain",
                      vm.get_connection().get_uri(), vm.get_uuid())

    def close_connection(self, ignore):
        conn = self.current_connection()
        if conn.get_state() != vmmConnection.STATE_DISCONNECTED:
            conn.close()

    def open_connection(self, ignore = None):
        conn = self.current_connection()
        if conn.get_state() == vmmConnection.STATE_DISCONNECTED:
            conn.open()
            return True

    def _connect_error(self, conn, details):
        if conn.get_driver() == "xen" and not conn.is_remote():
            self.err.show_err(_("Unable to open a connection to the Xen hypervisor/daemon.\n\n" +
                              "Verify that:\n" +
                              " - A Xen host kernel was booted\n" +
                              " - The Xen service has been started\n"),
                              details,
                              title=_("Virtual Machine Manager Connection Failure"))
        else:
            self.err.show_err(_("Unable to open a connection to the libvirt "
                                "management daemon.\n\n" +
                                "Libvirt URI is: %s\n\n" % conn.get_uri() +
                                "Verify that:\n" +
                                " - The 'libvirtd' daemon has been started\n"),
                              details,
                              title=_("Virtual Machine Manager Connection "
                                      "Failure"))


    ####################################
    # VM add/remove management methods #
    ####################################

    def vm_row_key(self, vm):
        return vm.get_uuid() + ":" + vm.get_connection().get_uri()

    def vm_added(self, connection, uri, vmuuid):
        vm = connection.get_vm(vmuuid)
        vm.connect("status-changed", self.vm_status_changed)
        vm.connect("resources-sampled", self.vm_resources_sampled)

        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        self._append_vm(model, vm, connection)

    def vm_removed(self, connection, uri, vmuuid):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        parent = self.rows[connection.get_uri()].iter
        for row in range(model.iter_n_children(parent)):
            vm = model.get_value(model.iter_nth_child(parent, row), ROW_HANDLE)
            if vm.get_uuid() == vmuuid:
                model.remove(model.iter_nth_child(parent, row))
                del self.rows[self.vm_row_key(vm)]
                break

    def vm_started(self, connection, uri, vmuuid):
        vm = connection.get_vm(vmuuid)
        logging.debug("VM %s started" % vm.get_name())
        if self.config.get_console_popup() == 2 and not vm.is_management_domain():
            # user has requested consoles on all vms
            gtype = vm.get_graphics_console()[0]
            if gtype == "vnc":
                self.emit("action-show-console", uri, vmuuid)
            elif not connection.is_remote():
                self.emit("action-show-terminal", uri, vmuuid)
        else:
            self.emit("action-refresh-console", uri, vmuuid)

    def _build_conn_hint(self, conn):
        hint = conn.get_uri()
        if conn.state == conn.STATE_DISCONNECTED:
            hint += " (%s)" % _("Double click to connect")
        return hint

    def _build_conn_markup(self, conn, row):
        if conn.state == conn.STATE_DISCONNECTED:
            markup = ("<span font_desc='9'>%s - "
                      "Not Connected</span>" % row[ROW_NAME])
        elif conn.state == conn.STATE_CONNECTING:
            markup = ("<span font_desc='9'>%s - "
                      "Connecting...</span>" % row[ROW_NAME])
        else:
            markup = ("<span font_desc='9'>%s</span>" % row[ROW_NAME])
        return markup

    def _build_conn_color(self, conn):
        color = None
        if conn.state != conn.STATE_DISCONNECTED:
            color = gtk.gdk.Color(0, 0, 0)
        else:
            # Color code #5b5b5b
            color = gtk.gdk.Color(23296, 23296, 23296)
        return color

    def _build_vm_markup(self, vm, row):
        markup = ("<span font_desc='10'>%s</span>\n"
                  "<span font_desc='8'>%s</span>" %
                  (row[ROW_NAME], row[ROW_STATUS]))
        return markup

    def _append_vm(self, model, vm, conn):
        row_key = self.vm_row_key(vm)
        if self.rows.has_key(row_key):
            return

        parent = self.rows[conn.get_uri()].iter
        row = []
        row.insert(ROW_HANDLE, vm)
        row.insert(ROW_NAME, vm.get_name())
        row.insert(ROW_MARKUP, "")
        row.insert(ROW_STATUS, vm.run_status())
        row.insert(ROW_STATUS_ICON, vm.run_status_icon_large())
        row.insert(ROW_KEY, vm.get_uuid())
        row.insert(ROW_HINT, None)
        row.insert(ROW_IS_CONN, False)
        row.insert(ROW_IS_CONN_CONNECTED, True)
        row.insert(ROW_IS_VM, True)
        row.insert(ROW_IS_VM_RUNNING, vm.is_active())
        row.insert(ROW_COLOR, gtk.gdk.Color(0, 0, 0))

        row[ROW_MARKUP] = self._build_vm_markup(vm, row)

        _iter = model.append(parent, row)
        path = model.get_path(_iter)
        self.rows[row_key] = model[path]
        # Expand a connection when adding a vm to it
        self.window.get_widget("vm-list").expand_row(model.get_path(parent), False)

    def _append_connection(self, model, conn):
        row = []
        row.insert(ROW_HANDLE, conn)
        row.insert(ROW_NAME, conn.get_pretty_desc_inactive(False))
        row.insert(ROW_MARKUP, self._build_conn_markup(conn, row))
        row.insert(ROW_STATUS, ("<span font_desc='9'>%s</span>" %
                                conn.get_state_text()))
        row.insert(ROW_STATUS_ICON, None)
        row.insert(ROW_KEY, conn.get_uri())
        row.insert(ROW_HINT, self._build_conn_hint(conn))
        row.insert(ROW_IS_CONN, True)
        row.insert(ROW_IS_CONN_CONNECTED,
                   conn.state != conn.STATE_DISCONNECTED)
        row.insert(ROW_IS_VM, False)
        row.insert(ROW_IS_VM_RUNNING, False)
        row.insert(ROW_COLOR, self._build_conn_color(conn))

        _iter = model.append(None, row)
        path = model.get_path(_iter)
        self.rows[conn.get_uri()] = model[path]
        return _iter

    def _add_connection(self, engine, conn):
        if self.rows.has_key(conn.get_uri()):
            return

        conn.connect("vm-added", self.vm_added)
        conn.connect("vm-removed", self.vm_removed)
        conn.connect("resources-sampled", self.conn_refresh_resources)
        conn.connect("state-changed", self.conn_state_changed)
        conn.connect("connect-error", self._connect_error)
        conn.connect("vm-started", self.vm_started)

        # add the connection to the treeModel
        vmlist = self.window.get_widget("vm-list")
        row = self._append_connection(vmlist.get_model(), conn)
        vmlist.get_selection().select_iter(row)

    def _remove_connection(self, engine, conn):
        model = self.window.get_widget("vm-list").get_model()
        parent = self.rows[conn.get_uri()].iter
        if parent is not None:
            child = model.iter_children(parent)
            while child is not None:
                del self.rows[self.vm_row_key(model.get_value(child, ROW_HANDLE))]
                model.remove(child)
                child = model.iter_children(parent)
            model.remove(parent)
            del self.rows[conn.get_uri()]


    #############################
    # State/UI updating methods #
    #############################

    def vm_status_changed(self, vm, status, ignore):
        parent = self.rows[vm.get_connection().get_uri()].iter

        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        missing = True
        for row in range(model.iter_n_children(parent)):
            _iter = model.iter_nth_child(parent, row)
            if model.get_value(_iter, ROW_KEY) == vm.get_uuid():
                missing = False
                break

        if missing:
            self._append_vm(model, vm, vm.get_connection())

        # Update run/shutdown/pause button states
        self.vm_selected()

    def vm_resources_sampled(self, vm):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        if not self.rows.has_key(self.vm_row_key(vm)):
            return

        row = self.rows[self.vm_row_key(vm)]
        row[ROW_STATUS] = vm.run_status()
        row[ROW_STATUS_ICON] = vm.run_status_icon_large()
        row[ROW_IS_VM_RUNNING] = vm.is_active()
        row[ROW_MARKUP] = self._build_vm_markup(vm, row)
        model.row_changed(row.path, row.iter)

    def conn_state_changed(self, conn):
        self.conn_refresh_resources(conn)
        self.vm_selected()

    def conn_refresh_resources(self, conn):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()
        row = self.rows[conn.get_uri()]

        row[ROW_MARKUP] = self._build_conn_markup(conn, row)
        row[ROW_STATUS] = "<span font_desc='9'>%s</span>" % conn.get_state_text()
        row[ROW_IS_CONN_CONNECTED] = conn.state != conn.STATE_DISCONNECTED
        row[ROW_HINT] = self._build_conn_hint(conn)
        row[ROW_COLOR] = self._build_conn_color(conn)

        if conn.get_state() in [vmmConnection.STATE_DISCONNECTED,
                                vmmConnection.STATE_CONNECTING]:
            # Connection went inactive, delete any VM child nodes
            parent = self.rows[conn.get_uri()].iter
            if parent is not None:
                child = model.iter_children(parent)
                while child is not None:
                    del self.rows[self.vm_row_key(model.get_value(child, ROW_HANDLE))]
                    model.remove(child)
                    child = model.iter_children(parent)
        model.row_changed(row.path, row.iter)


    def vm_selected(self, ignore=None):
        conn = self.current_connection()
        vm = self.current_vm()

        show_open = bool(vm)
        show_details = bool(vm)
        host_details = bool(vm or conn)
        delete = bool((vm and vm.is_runable()) or
                      (not vm and conn))
        show_run = bool(vm and vm.is_runable())
        is_paused = bool(vm and vm.is_paused())
        if is_paused:
            show_pause = bool(vm and vm.is_unpauseable())
        else:
            show_pause = bool(vm and vm.is_pauseable())
        show_shutdown = bool(vm and vm.is_stoppable())
        restore = bool(conn and conn.get_state() == vmmConnection.STATE_ACTIVE)

        self.window.get_widget("vm-open").set_sensitive(show_open)
        self.window.get_widget("vm-run").set_sensitive(show_run)
        self.window.get_widget("vm-shutdown").set_sensitive(show_shutdown)
        self.set_pause_state(is_paused)
        self.window.get_widget("vm-pause").set_sensitive(show_pause)

        self.window.get_widget("menu_edit_details").set_sensitive(show_details)
        self.window.get_widget("menu_host_details").set_sensitive(host_details)
        self.window.get_widget("menu_edit_delete").set_sensitive(delete)
        self.window.get_widget("menu_file_restore_saved").set_sensitive(restore)

    def popup_vm_menu_key(self, widget, event):
        if gtk.gdk.keyval_name(event.keyval) != "Menu":
            return False

        vmlist = self.window.get_widget("vm-list")
        treeselection = vmlist.get_selection()
        model, _iter = treeselection.get_selected()
        self.popup_vm_menu(model, _iter, event)
        return True

    def popup_vm_menu_button(self, widget, event):
        if event.button != 3:
            return False

        tup = widget.get_path_at_pos(int(event.x), int(event.y))
        if tup == None:
            return False
        path = tup[0]
        model = widget.get_model()
        _iter = model.get_iter(path)

        self.popup_vm_menu(model, _iter, event)
        return False

    def popup_vm_menu(self, model, _iter, event):
        if model.iter_parent(_iter) != None:
            # Popup the vm menu
            vm = model.get_value(_iter, ROW_HANDLE)

            destroy = vm.is_destroyable()
            run     = vm.is_runable()
            stop    = vm.is_stoppable()
            paused  = vm.is_paused()
            ro      = vm.is_read_only()

            self.vmmenu_items["run"].set_sensitive(run)
            self.vmmenu_items["shutdown"].set_sensitive(stop)
            self.vmmenu_items["pause"].set_property("visible", not paused)
            self.vmmenu_items["pause"].set_sensitive(stop)
            self.vmmenu_items["resume"].set_property("visible", paused)
            self.vmmenu_items["resume"].set_sensitive(paused)
            self.vmmenu_items["migrate"].set_sensitive(stop)
            self.vmmenu_items["clone"].set_sensitive(not ro)
            self.vmmenu_items["delete"].set_sensitive(run)

            self.vmmenushutdown_items["poweroff"].set_sensitive(stop)
            self.vmmenushutdown_items["reboot"].set_sensitive(stop)
            self.vmmenushutdown_items["forcepoweroff"].set_sensitive(destroy)
            self.vmmenu.popup(None, None, None, 0, event.time)
        else:
            # Pop up connection menu
            conn = model.get_value(_iter, ROW_HANDLE)
            disconn = (conn.get_state() == vmmConnection.STATE_DISCONNECTED)
            conning = (conn.get_state() == vmmConnection.STATE_CONNECTING)

            self.connmenu_items["create"].set_sensitive(not disconn)
            self.connmenu_items["disconnect"].set_sensitive(not (disconn or
                                                                 conning))
            self.connmenu_items["connect"].set_sensitive(disconn)
            self.connmenu_items["delete"].set_sensitive(disconn)

            self.connmenu.popup(None, None, None, 0, event.time)


    #################
    # Stats methods #
    #################

    def vmlist_name_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_NAME),
                   model.get_value(iter2, ROW_NAME))

    def vmlist_cpu_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).cpu_time_percentage(), model.get_value(iter2, ROW_HANDLE).cpu_time_percentage())

    def vmlist_disk_io_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).disk_io_rate(), model.get_value(iter2, ROW_HANDLE).disk_io_rate())

    def vmlist_network_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).network_traffic_rate(), model.get_value(iter2, ROW_HANDLE).network_traffic_rate())

    def enable_polling(self, ignore1, ignore2, conf_entry, userdata):
        if userdata == cfg.STATS_DISK:
            widgn = "menu_view_stats_disk"
        elif userdata == cfg.STATS_NETWORK:
            widgn = "menu_view_stats_network"
        widget = self.window.get_widget(widgn)

        tool_text = ""
        if conf_entry and (conf_entry == True or \
                           conf_entry.get_value().get_bool()):
            widget.set_sensitive(True)
        else:
            if widget.get_active():
                widget.set_active(False)
            widget.set_sensitive(False)
            tool_text = _("Disabled in preferences dialog.")

        util.tooltip_wrapper(widget, tool_text)

    def toggle_network_traffic_visible_widget(self, *ignore):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_NETWORK)
        col.set_visible(self.config.is_vmlist_network_traffic_visible())

    def toggle_disk_io_visible_widget(self, *ignore):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_DISK)
        col.set_visible(self.config.is_vmlist_disk_io_visible())

    def toggle_cpu_usage_visible_widget(self, *ignore):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_CPU)
        col.set_visible(self.config.is_vmlist_cpu_usage_visible())

    def toggle_stats_visible(self, src, stats_id):
        visible = src.get_active()
        set_stats = {
        cfg.STATS_CPU: self.config.set_vmlist_cpu_usage_visible,
        cfg.STATS_DISK: self.config.set_vmlist_disk_io_visible,
        cfg.STATS_NETWORK: self.config.set_vmlist_network_traffic_visible,
        }
        set_stats[stats_id](visible)

    def cpu_usage_img(self,  column, cell, model, _iter, data):
        if model.get_value(_iter, ROW_HANDLE) is None:
            return
        data = model.get_value(_iter, ROW_HANDLE).cpu_time_vector_limit(40)
        cell.set_property('data_array', data)

    def disk_io_img(self,  column, cell, model, _iter, data):
        if model.get_value(_iter, ROW_HANDLE) is None:
            return
        data = model.get_value(_iter, ROW_HANDLE).disk_io_vector_limit(40)
        cell.set_property('data_array', data)

    def network_traffic_img(self,  column, cell, model, _iter, data):
        if model.get_value(_iter, ROW_HANDLE) is None:
            return
        data = model.get_value(_iter, ROW_HANDLE).network_traffic_vector_limit(40)
        cell.set_property('data_array', data)

gobject.type_register(vmmManager)

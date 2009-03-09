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

import sparkline
import libvirt

from virtManager.connection import vmmConnection
from virtManager.asyncjob import vmmAsyncJob
from virtManager.error import vmmErrorDialog
from virtManager.delete import vmmDeleteDialog
from virtManager import util as util

VMLIST_SORT_ID = 1
VMLIST_SORT_NAME = 2
VMLIST_SORT_CPU_USAGE = 3
VMLIST_SORT_MEMORY_USAGE = 4
VMLIST_SORT_DISK_IO = 5
VMLIST_SORT_NETWORK_USAGE = 6

# fields in the tree model data set
ROW_HANDLE = 0
ROW_NAME = 1
ROW_ID = 2
ROW_STATUS = 3
ROW_STATUS_ICON = 4
ROW_CPU = 5
ROW_VCPUS = 6
ROW_MEM = 7
ROW_MEM_USAGE = 8
ROW_KEY = 9
ROW_HINT = 10
ROW_DISK_RD = 11
ROW_DISK_WR = 12
ROW_NET_RX = 13
ROW_NET_TX = 14

# Columns in the tree view
COL_NAME = 0
COL_ID = 1
COL_STATUS = 2
COL_CPU = 3
COL_VCPU = 4
COL_MEM = 5
COL_DISK = 6
COL_NETWORK = 7

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
                                  gobject.TYPE_NONE, (str,str,str)),
        "action-exit-app": (gobject.SIGNAL_RUN_FIRST,
                            gobject.TYPE_NONE, []),}

    def __init__(self, config, engine):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-manager.glade", "vmm-manager", domain="virt-manager")
        self.err = vmmErrorDialog(self.window.get_widget("vmm-manager"),
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))
        self.config = config
        self.engine = engine

        self.delete_dialog = None
        self.startup_error = None

        self.prepare_vmlist()

        self.config.on_vmlist_domain_id_visible_changed(self.toggle_domain_id_visible_widget)
        self.config.on_vmlist_status_visible_changed(self.toggle_status_visible_widget)
        self.config.on_vmlist_cpu_usage_visible_changed(self.toggle_cpu_usage_visible_widget)
        self.config.on_vmlist_virtual_cpus_visible_changed(self.toggle_virtual_cpus_visible_widget)
        self.config.on_vmlist_memory_usage_visible_changed(self.toggle_memory_usage_visible_widget)
        self.config.on_vmlist_disk_io_visible_changed(self.toggle_disk_io_visible_widget)
        self.config.on_vmlist_network_traffic_visible_changed(self.toggle_network_traffic_visible_widget)

        self.window.get_widget("menu_view_domain_id").set_active(self.config.is_vmlist_domain_id_visible())
        self.window.get_widget("menu_view_status").set_active(self.config.is_vmlist_status_visible())
        self.window.get_widget("menu_view_cpu_usage").set_active(self.config.is_vmlist_cpu_usage_visible())
        self.window.get_widget("menu_view_virtual_cpus").set_active(self.config.is_vmlist_virtual_cpus_visible())
        self.window.get_widget("menu_view_memory_usage").set_active(self.config.is_vmlist_memory_usage_visible())
        self.window.get_widget("menu_view_disk_io").set_active(self.config.is_vmlist_disk_io_visible())
        self.window.get_widget("menu_view_network_traffic").set_active(self.config.is_vmlist_network_traffic_visible())

        # Register callbacks with the global stats enable/disable values
        # that disable the associated vmlist widgets if reporting is disabled
        self.config.on_stats_enable_disk_poll_changed(self.enable_polling,
                                                      VMLIST_SORT_DISK_IO)
        self.config.on_stats_enable_net_poll_changed(self.enable_polling,
                                                     VMLIST_SORT_NETWORK_USAGE)
        self.config.on_stats_enable_cpu_poll_changed(self.enable_polling,
                                                     VMLIST_SORT_CPU_USAGE)
        self.config.on_stats_enable_mem_poll_changed(self.enable_polling,
                                                     VMLIST_SORT_MEMORY_USAGE)

        self.window.get_widget("vm-view").set_active(0)

        self.vmmenu_icons = {}
        self.vmmenu_icons["run"] = gtk.Image()
        self.vmmenu_icons["run"].set_from_stock(gtk.STOCK_MEDIA_PLAY,
                                                gtk.ICON_SIZE_MENU)
        self.vmmenu_icons["pause"] = gtk.Image()
        self.vmmenu_icons["pause"].set_from_stock(gtk.STOCK_MEDIA_PAUSE,
                                                  gtk.ICON_SIZE_MENU)
        self.vmmenu_icons["resume"] = gtk.Image()
        self.vmmenu_icons["resume"].set_from_stock(gtk.STOCK_MEDIA_PAUSE,
                                                   gtk.ICON_SIZE_MENU)
        self.vmmenu_icons["reboot"] = gtk.Image()
        self.vmmenu_icons["reboot"].set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/icon_shutdown.png", 18, 18))
        self.vmmenu_icons["poweroff"] = gtk.Image()
        self.vmmenu_icons["poweroff"].set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/icon_shutdown.png", 18, 18))
        self.vmmenu_icons["forcepoweroff"] = gtk.Image()
        self.vmmenu_icons["forcepoweroff"].set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/icon_shutdown.png", 18, 18))

        self.vmmenu = gtk.Menu()
        self.vmmenushutdown = gtk.Menu()
        self.vmmenu_items = {}
        self.vmmenushutdown_items = {}
        self.vmmenumigrate = gtk.Menu()

        self.vmmenu_items["run"] = gtk.ImageMenuItem("_Run")
        self.vmmenu_items["run"].set_image(self.vmmenu_icons["run"])
        self.vmmenu_items["run"].show()
        self.vmmenu_items["run"].connect("activate", self.start_vm)
        self.vmmenu.add(self.vmmenu_items["run"])

        self.vmmenu_items["pause"] = gtk.ImageMenuItem("_Pause")
        self.vmmenu_items["pause"].set_image(self.vmmenu_icons["pause"])
        self.vmmenu_items["pause"].set_sensitive(False)
        self.vmmenu_items["pause"].show()
        self.vmmenu_items["pause"].connect("activate", self.pause_vm)
        self.vmmenu.add(self.vmmenu_items["pause"])

        self.vmmenu_items["resume"] = gtk.ImageMenuItem("_Resume")
        self.vmmenu_items["resume"].set_image(self.vmmenu_icons["resume"])
        self.vmmenu_items["resume"].show()
        self.vmmenu_items["resume"].connect("activate", self.resume_vm)
        self.vmmenu.add(self.vmmenu_items["resume"])


        self.vmmenu_items["shutdown"] = gtk.MenuItem("_Shut Down")
        self.vmmenu_items["shutdown"].set_submenu(self.vmmenushutdown)
        self.vmmenu_items["shutdown"].show()
        self.vmmenu.add(self.vmmenu_items["shutdown"])

        self.vmmenushutdown_items["reboot"] = gtk.ImageMenuItem("_Reboot")
        self.vmmenushutdown_items["reboot"].set_image(self.vmmenu_icons["reboot"])
        self.vmmenushutdown_items["reboot"].show()
        self.vmmenushutdown_items["reboot"].connect("activate", self.reboot_vm)
        self.vmmenushutdown.add(self.vmmenushutdown_items["reboot"])

        self.vmmenushutdown_items["poweroff"] = gtk.ImageMenuItem("_Shut Down")
        self.vmmenushutdown_items["poweroff"].set_image(self.vmmenu_icons["poweroff"])
        self.vmmenushutdown_items["poweroff"].show()
        self.vmmenushutdown_items["poweroff"].connect("activate", self.poweroff_vm)
        self.vmmenushutdown.add(self.vmmenushutdown_items["poweroff"])

        self.vmmenushutdown_items["forcepoweroff"] = gtk.ImageMenuItem("_Force Off")
        self.vmmenushutdown_items["forcepoweroff"].set_image(self.vmmenu_icons["forcepoweroff"])
        self.vmmenushutdown_items["forcepoweroff"].show()
        self.vmmenushutdown_items["forcepoweroff"].connect("activate", self.destroy_vm)
        self.vmmenushutdown.add(self.vmmenushutdown_items["forcepoweroff"])

        self.vmmenu_items["hsep1"] = gtk.SeparatorMenuItem()
        self.vmmenu_items["hsep1"].show()
        self.vmmenu.add(self.vmmenu_items["hsep1"])

        self.vmmenu_items["migrate"] = gtk.ImageMenuItem("_Migrate")
        self.vmmenu_items["migrate"].set_submenu(self.vmmenumigrate)
        self.vmmenu_items["migrate"].show()
        self.vmmenu_items["migrate"].connect("activate",
                                             self.set_migrate_submenu)
        self.vmmenu.add(self.vmmenu_items["migrate"])

        self.vmmenu_items["hsep2"] = gtk.SeparatorMenuItem()
        self.vmmenu_items["hsep2"].show()
        self.vmmenu.add(self.vmmenu_items["hsep2"])

        self.vmmenu_items["open"] = gtk.ImageMenuItem(gtk.STOCK_OPEN)
        self.vmmenu_items["open"].connect("activate", self.open_vm_console)
        self.vmmenu_items["open"].show()
        self.vmmenu.add(self.vmmenu_items["open"])

        self.vmmenu.show()

        # Mapping of VM UUID -> tree model rows to
        # allow O(1) access instead of O(n)
        self.rows = {}

        self.connmenu = gtk.Menu()
        self.connmenu_items = {}

        self.connmenu_items["create"] = gtk.ImageMenuItem(gtk.STOCK_NEW)
        self.connmenu_items["create"].show()
        self.connmenu_items["create"].connect("activate", self.show_vm_create)
        self.connmenu.add(self.connmenu_items["create"])

        self.connmenu_items["connect"] = gtk.ImageMenuItem(gtk.STOCK_CONNECT)
        self.connmenu_items["connect"].show()
        self.connmenu_items["connect"].connect("activate", self.open_connection)
        self.connmenu.add(self.connmenu_items["connect"])

        self.connmenu_items["disconnect"] = gtk.ImageMenuItem(gtk.STOCK_DISCONNECT)
        self.connmenu_items["disconnect"].show()
        self.connmenu_items["disconnect"].connect("activate", self.close_connection)
        self.connmenu.add(self.connmenu_items["disconnect"])

        self.connmenu_items["hsep"] = gtk.SeparatorMenuItem()
        self.connmenu_items["hsep"].show()
        self.connmenu.add(self.connmenu_items["hsep"])

        self.connmenu_items["details"] = gtk.ImageMenuItem("_Details")
        self.connmenu_items["details"].connect("activate", self.show_host)
        self.connmenu_items["details"].show()
        self.connmenu.add(self.connmenu_items["details"])

        self.connmenu.show()

        self.window.signal_autoconnect({
            "on_menu_view_domain_id_activate" : self.toggle_domain_id_visible_conf,
            "on_menu_view_status_activate" : self.toggle_status_visible_conf,
            "on_menu_view_cpu_usage_activate" : self.toggle_cpu_usage_visible_conf,
            "on_menu_view_virtual_cpus_activate" : self.toggle_virtual_cpus_visible_conf,
            "on_menu_view_memory_usage_activate" : self.toggle_memory_usage_visible_conf,
            "on_menu_view_disk_io_activate" : self.toggle_disk_io_visible_conf,
            "on_menu_view_network_traffic_activate" : self.toggle_network_traffic_visible_conf,

            "on_vm_manager_delete_event": self.close,
            "on_menu_file_add_connection_activate": self.new_connection,
            "on_menu_file_quit_activate": self.exit_app,
            "on_menu_file_close_activate": self.close,
            "on_menu_restore_saved_activate": self.restore_saved,
            "on_vmm_close_clicked": self.close,
            "on_vm_open_clicked": self.open_vm_console,
            "on_vm_delete_clicked": self.delete_vm,
            "on_vm_new_clicked": self.new_vm,
            "on_menu_edit_details_activate": self.open_vm_console,
            "on_menu_edit_delete_activate": self.delete_vm,
            "on_menu_host_details_activate": self.show_host,

            "on_vm_view_changed": self.vm_view_changed,
            "on_vm_list_row_activated": self.open_vm_console,
            "on_vm_list_row_expanded": self.row_expanded,
            "on_vm_list_row_collapsed": self.row_collapsed,
            "on_vm_list_button_press_event": self.popup_vm_menu,

            "on_menu_edit_preferences_activate": self.show_preferences,
            "on_menu_help_about_activate": self.show_about,
            "on_menu_help_activate": self.show_help,
            })

        self.vm_selected(None)
        self.window.get_widget("vm-list").get_selection().connect("changed", self.vm_selected)

        # Initialize stat polling columns based on global polling
        # preferences (we want signal handlers for this)
        for typ, init_val in \
            [ (VMLIST_SORT_DISK_IO,
               self.config.get_stats_enable_disk_poll()),
              (VMLIST_SORT_NETWORK_USAGE,
               self.config.get_stats_enable_net_poll()),
              (VMLIST_SORT_CPU_USAGE,
               self.config.get_stats_enable_cpu_poll()),
              (VMLIST_SORT_MEMORY_USAGE,
               self.config.get_stats_enable_mem_poll())]:
            self.enable_polling(None, None, init_val, typ)

        # store any error message from the restore-domain callback
        self.restore_err = ""
        self.restore_err_details = ""

        self.window.get_widget("menu_file_restore_saved").set_sensitive(False)

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

    def show(self):
        win = self.window.get_widget("vmm-manager")
        if self.is_visible():
            win.present()
            return
        win.show_all()
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

    def exit_app(self, src=None, src2=None):
        self.emit("action-exit-app")

    def new_connection(self, src=None):
        self.emit("action-show-connect")

    def is_showing_active(self):
        active = self.window.get_widget("vm-view").get_active()
        if active in [0,1]:
            return True
        return False

    def is_showing_inactive(self):
        active = self.window.get_widget("vm-view").get_active()
        if active in [0,2]:
            return True
        return False

    def vm_row_key(self, vm):
        return vm.get_uuid() + ":" + vm.get_connection().get_uri()

    def restore_saved(self, src=None):
        conn = self.current_connection()
        if conn.is_remote():
            self.err.val_err(_("Restoring virtual machines over remote "
                               "connections is not yet supported"))
            return

        path = util.browse_local(self.window.get_widget("vmm-manager"),
                                 _("Restore Virtual Machine"),
                                 self.config.get_default_save_dir(conn))

        if path:
            if conn.is_valid_saved_image(path):
                progWin = vmmAsyncJob(self.config,
                                      self.restore_saved_callback,
                                      [path],
                                      _("Restoring Virtual Machine"))
                progWin.run()
            else:
                self.err.val_err(_("The file '%s' does not appear to be a "
                                   "valid saved machine image") % path)
                return

        if self.restore_err != "":
            self.err.show_err(self.restore_err, self.restore_err_details,
                              title=_("Error restoring domain"))
            self.restore_err = ""
            self.restore_details = ""

    def restore_saved_callback(self, file_to_load, ignore1=None):
        try:
            self.current_connection().restore(file_to_load)
        except Exception, e:
            self.restore_err = (_("Error restoring domain '%s': %s") %
                                  (file_to_load, str(e)))
            self.restore_err_details = "".join(traceback.format_exc())
            return


    def vm_view_changed(self, src):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        _iter = model.get_iter_first()
        while _iter is not None:
            conn = model.get_value(_iter, ROW_HANDLE)

            children = model.iter_children(_iter)
            while children is not None:
                vm = model.get_value(children, ROW_HANDLE)
                del self.rows[self.vm_row_key(vm)]
                model.remove(children)
                children = model.iter_children(_iter)

            if conn:
                uuids = conn.list_vm_uuids()
                for vmuuid in uuids:
                    vm = conn.get_vm(vmuuid)
                    if vm.is_active():
                        if not(self.is_showing_active()):
                            continue
                    else:
                        if not(self.is_showing_inactive()):
                            continue
                    self._append_vm(model, vm, conn)

            _iter = model.iter_next(_iter)


    def vm_added(self, connection, uri, vmuuid):
        vm = connection.get_vm(vmuuid)
        vm.connect("status-changed", self.vm_status_changed)
        vm.connect("resources-sampled", self.vm_resources_sampled)

        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        if vm.is_active():
            if not(self.is_showing_active()):
                return
        else:
            if not(self.is_showing_inactive()):
                return

        self._append_vm(model, vm, connection)

    def vm_started(self, connection, uri, vmuuid):
        vm = connection.get_vm(vmuuid)
        logging.debug("VM %s started" % vm.get_name())
        if self.config.get_console_popup() == 2 and not vm.is_management_domain():
            # user has requested consoles on all vms
            (gtype, ignore, ignore, ignore, ignore) = vm.get_graphics_console()
            if gtype == "vnc":
                self.emit("action-show-console", uri, vmuuid)
            elif not connection.is_remote():
                self.emit("action-show-terminal", uri, vmuuid)
        else:
            self.emit("action-refresh-console", uri, vmuuid)

    def _append_vm(self, model, vm, conn):
        logging.debug("About to append vm: %s" % vm.get_name())
        parent = self.rows[conn.get_uri()].iter
        row = []
        row.insert(ROW_HANDLE, vm)
        row.insert(ROW_NAME, vm.get_name())
        row.insert(ROW_ID, vm.get_id_pretty())
        row.insert(ROW_STATUS, vm.run_status())
        row.insert(ROW_STATUS_ICON, vm.run_status_icon())
        row.insert(ROW_CPU, vm.cpu_time_pretty())
        row.insert(ROW_VCPUS, vm.vcpu_count())
        row.insert(ROW_MEM, vm.get_memory_pretty())
        row.insert(ROW_MEM_USAGE, vm.current_memory_percentage())
        row.insert(ROW_KEY, vm.get_uuid())
        row.insert(ROW_DISK_RD, vm.disk_read_rate())
        row.insert(ROW_DISK_WR, vm.disk_write_rate())
        row.insert(ROW_NET_RX, vm.network_rx_rate())
        row.insert(ROW_NET_TX, vm.network_tx_rate())
        row.insert(ROW_HINT, None)

        _iter = model.append(parent, row)
        path = model.get_path(_iter)
        self.rows[self.vm_row_key(vm)] = model[path]
        # Expand a connection when adding a vm to it
        self.window.get_widget("vm-list").expand_row(model.get_path(parent), False)

    def _append_connection(self, model, conn):
        row = []
        row.insert(ROW_HANDLE, conn)
        row.insert(ROW_STATUS, conn.get_state_text())
        row.insert(ROW_NAME, conn.get_short_hostname())
        row.insert(ROW_ID, conn.get_driver())
        row.insert(ROW_STATUS_ICON, None)
        row.insert(ROW_CPU, "%2.2f %%" % conn.cpu_time_percentage())
        row.insert(ROW_VCPUS, conn.host_active_processor_count())
        row.insert(ROW_MEM, conn.pretty_current_memory())
        row.insert(ROW_MEM_USAGE, conn.current_memory_percentage())
        row.insert(ROW_KEY, conn.get_uri())
        row.insert(ROW_HINT, conn.get_uri())
        row.insert(ROW_DISK_RD, conn.disk_read_rate())
        row.insert(ROW_DISK_WR, conn.disk_write_rate())
        row.insert(ROW_NET_RX, conn.network_rx_rate())
        row.insert(ROW_NET_TX, conn.network_tx_rate())

        _iter = model.append(None, row)
        path = model.get_path(_iter)
        self.rows[conn.get_uri()] = model[path]
        return _iter

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

    def vm_status_changed(self, vm, status):
        parent = self.rows[vm.get_connection().get_uri()].iter
        wanted = False
        if vm.is_active():
            if self.is_showing_active():
                wanted = True
        else:
            if self.is_showing_inactive():
                wanted = True

        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        missing = True
        for row in range(model.iter_n_children(parent)):
            _iter = model.iter_nth_child(parent, row)
            if model.get_value(_iter, ROW_KEY) == vm.get_uuid():
                if wanted:
                    missing = False
                else:
                    model.remove(model.iter_nth_child(parent, row))
                    del self.rows[self.vm_row_key(vm)]
                break

        if missing and wanted:
            self._append_vm(model, vm, vm.get_connection())


    def vm_resources_sampled(self, vm):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        if not self.rows.has_key(self.vm_row_key(vm)):
            return

        row = self.rows[self.vm_row_key(vm)]
        # Handle, name, ID, status, status icon, cpu, cpu graph, vcpus, mem, mem bar, diskRead, diskWrite, netRx, netTx
        if vm.get_id() == -1:
            row[ROW_ID] = "-"
        else:
            row[ROW_ID] = vm.get_id()
        row[ROW_STATUS] = vm.run_status()
        row[ROW_STATUS_ICON] = vm.run_status_icon()
        row[ROW_CPU] = vm.cpu_time_pretty()
        row[ROW_VCPUS] = vm.vcpu_count()
        row[ROW_MEM] = vm.get_memory_pretty()
        row[ROW_MEM_USAGE] = vm.current_memory_percentage()
        row[ROW_DISK_RD] = vm.disk_read_rate()
        row[ROW_DISK_WR] = vm.disk_write_rate()
        row[ROW_NET_RX] = vm.network_rx_rate()
        row[ROW_NET_TX] = vm.network_tx_rate()
        model.row_changed(row.path, row.iter)

        if vm == self.current_vm():
            if vm.is_active():
                self.window.get_widget("vm-delete").set_sensitive(False)
                self.window.get_widget("menu_edit_delete").set_sensitive(False)
            else:
                self.window.get_widget("vm-delete").set_sensitive(True)
                self.window.get_widget("menu_edit_delete").set_sensitive(True)


    def conn_state_changed(self, conn):
        self.conn_refresh_resources(conn)
        self.vm_selected(self.window.get_widget("vm-list").get_selection())

    def conn_refresh_resources(self, conn):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()
        row = self.rows[conn.get_uri()]
        row[ROW_STATUS] = conn.get_state_text()
        row[ROW_CPU] = "%2.2f %%" % conn.cpu_time_percentage()
        row[ROW_VCPUS] = conn.host_active_processor_count()
        row[ROW_MEM] = conn.pretty_current_memory()
        row[ROW_MEM_USAGE] = conn.current_memory_percentage()
        row[ROW_DISK_RD] = conn.disk_read_rate()
        row[ROW_DISK_WR] = conn.disk_write_rate()
        row[ROW_NET_RX] = conn.network_rx_rate()
        row[ROW_NET_TX] = conn.network_tx_rate()
        if conn.get_state() in [vmmConnection.STATE_DISCONNECTED, vmmConnection.STATE_CONNECTING]:
            # Connection went inactive, delete any VM child nodes
            parent = self.rows[conn.get_uri()].iter
            if parent is not None:
                child = model.iter_children(parent)
                while child is not None:
                    del self.rows[self.vm_row_key(model.get_value(child, ROW_HANDLE))]
                    model.remove(child)
                    child = model.iter_children(parent)
        model.row_changed(row.path, row.iter)

    def current_vm(self):
        vmlist = self.window.get_widget("vm-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        # check that something is selected and that it is a vm, not a connection
        if active[1] != None and active[0].iter_parent(active[1]) != None:
            return active[0].get_value(active[1], ROW_HANDLE)
        return None

    def current_connection(self):
        # returns a uri
        vmlist = self.window.get_widget("vm-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            parent = active[0].iter_parent(active[1])
            # return the connection of the currently selected vm, or the
            # currently selected connection
            if parent is not None:
                return active[0].get_value(parent, ROW_HANDLE)
            else:
                return active[0].get_value(active[1], ROW_HANDLE)
        return None

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

    def show_vm_details(self,ignore):
        conn = self.current_connection()
        if conn is None:
            return
        vm = self.current_vm()
        if vm is None:
            self.emit("action-show-host", conn.get_uri())
        else:
            self.emit("action-show-console", conn.get_uri(), self.current_vmuuid())

    def show_vm_create(self,ignore):
        self.emit("action-show-create", self.current_connection_uri())

    def close_connection(self, ignore):
        conn = self.current_connection()
        if conn.get_state() != vmmConnection.STATE_DISCONNECTED:
            conn.close()

    def open_connection(self, ignore = None):
        conn = self.current_connection()
        if conn.get_state() == vmmConnection.STATE_DISCONNECTED:
            conn.open()

    def open_vm_console(self,ignore,ignore2=None,ignore3=None):
        if self.current_vmuuid():
            self.emit("action-show-console", self.current_connection_uri(), self.current_vmuuid())
        elif self.current_connection():
            self.open_connection()


    def vm_selected(self, selection):
        conn = self.current_connection()
        vm = self.current_vm()
        if selection == None or selection.count_selected_rows() == 0:
            # Nothing is selected
            self.window.get_widget("vm-open").set_sensitive(False)
            self.window.get_widget("vm-delete").set_sensitive(False)
            self.window.get_widget("menu_edit_details").set_sensitive(False)
            self.window.get_widget("menu_edit_delete").set_sensitive(False)
            self.window.get_widget("menu_host_details").set_sensitive(False)
            self.window.get_widget("menu_file_restore_saved").set_sensitive(False)
        elif vm is not None:
            # A VM is selected
            # this is strange to call this here, but it simplifies the code
            # updating the treeview
            self.vm_resources_sampled(vm)
            self.window.get_widget("vm-open").set_sensitive(True)
            if vm.status() == libvirt.VIR_DOMAIN_SHUTOFF:
                self.window.get_widget("vm-delete").set_sensitive(True)
            else:
                self.window.get_widget("vm-delete").set_sensitive(False)
            self.window.get_widget("menu_edit_details").set_sensitive(True)
            self.window.get_widget("menu_edit_delete").set_sensitive(True)
            self.window.get_widget("menu_host_details").set_sensitive(True)
            self.window.get_widget("menu_file_restore_saved").set_sensitive(False)
        else:
            # A connection is selected
            self.window.get_widget("vm-open").set_sensitive(False)
            if conn.get_state() == vmmConnection.STATE_DISCONNECTED:
                self.window.get_widget("vm-delete").set_sensitive(True)
            else:
                self.window.get_widget("vm-delete").set_sensitive(False)
            if conn.get_state() == vmmConnection.STATE_ACTIVE:
                self.window.get_widget("menu_file_restore_saved").set_sensitive(True)
            else:
                self.window.get_widget("menu_file_restore_saved").set_sensitive(False)
            self.window.get_widget("menu_edit_details").set_sensitive(False)
            self.window.get_widget("menu_edit_delete").set_sensitive(False)
            self.window.get_widget("menu_host_details").set_sensitive(True)

    def popup_vm_menu(self, widget, event):
        tup = widget.get_path_at_pos(int(event.x), int(event.y))
        if tup == None:
            return False
        path = tup[0]
        model = widget.get_model()
        _iter = model.get_iter(path)
        if model.iter_parent(_iter) != None:
            # a vm is selected, retrieve it from the first column of the model
            vm = model.get_value(_iter, ROW_HANDLE)
            if event.button == 3:
                # Update popup menu based upon vm status
                if vm.is_read_only() == True:
                    self.vmmenu_items["run"].set_sensitive(False)
                    self.vmmenu_items["pause"].set_sensitive(False)
                    self.vmmenu_items["pause"].show()
                    self.vmmenu_items["resume"].hide()
                    self.vmmenu_items["resume"].set_sensitive(False)
                    self.vmmenu_items["shutdown"].set_sensitive(False)
                    self.vmmenu_items["migrate"].set_sensitive(False)
                else:
                    if vm.status() == libvirt.VIR_DOMAIN_SHUTOFF:
                        self.vmmenu_items["run"].set_sensitive(True)
                        self.vmmenu_items["pause"].set_sensitive(False)
                        self.vmmenu_items["pause"].show()
                        self.vmmenu_items["resume"].hide()
                        self.vmmenu_items["resume"].set_sensitive(False)
                        self.vmmenu_items["shutdown"].set_sensitive(False)
                        self.vmmenu_items["migrate"].set_sensitive(True)
                    elif vm.status() == libvirt.VIR_DOMAIN_RUNNING:
                        self.vmmenu_items["run"].set_sensitive(False)
                        self.vmmenu_items["pause"].set_sensitive(True)
                        self.vmmenu_items["pause"].show()
                        self.vmmenu_items["resume"].hide()
                        self.vmmenu_items["resume"].set_sensitive(False)
                        self.vmmenu_items["shutdown"].set_sensitive(True)
                        self.vmmenu_items["migrate"].set_sensitive(True)
                    elif vm.status() == libvirt.VIR_DOMAIN_PAUSED:
                        self.vmmenu_items["run"].set_sensitive(False)
                        self.vmmenu_items["pause"].hide()
                        self.vmmenu_items["pause"].set_sensitive(False)
                        self.vmmenu_items["resume"].show()
                        self.vmmenu_items["resume"].set_sensitive(True)
                        self.vmmenu_items["shutdown"].set_sensitive(True)
                        self.vmmenu_items["migrate"].set_sensitive(True)
                self.vmmenu.popup(None, None, None, 0, event.time)
            return False
        else:
            conn = model.get_value(_iter, ROW_HANDLE)
            if event.button == 3:
                if conn.get_state() != vmmConnection.STATE_DISCONNECTED:
                    self.connmenu_items["create"].set_sensitive(True)
                    self.connmenu_items["disconnect"].set_sensitive(True)
                    self.connmenu_items["connect"].set_sensitive(False)
                else:
                    self.connmenu_items["create"].set_sensitive(False)
                    self.connmenu_items["disconnect"].set_sensitive(False)
                    self.connmenu_items["connect"].set_sensitive(True)
                self.connmenu.popup(None, None, None, 0, event.time)
            return False

    def new_vm(self, ignore=None):
        self.emit("action-show-create", self.current_connection_uri())

    def delete_vm(self, ignore=None):
        conn = self.current_connection()
        vm = self.current_vm()
        if vm is None:
            self._do_delete_connection(conn)
        else:
            self._do_delete_vm(vm)

    def _do_delete_connection(self, conn):
        if conn is None:
            return

        result = self.err.yes_no(_("This will remove the connection \"%s\","
                                   "are you sure?") %
                                   self.rows[conn.get_uri()][ROW_NAME])
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

    def show_about(self, src):
        self.emit("action-show-about")

    def show_help(self, src):
        # From the manager window, show the help document from the beginning
        self.emit("action-show-help", None) #No 'id', load the front page

    def show_preferences(self, src):
        self.emit("action-show-preferences")

    def show_host(self, src):
        self.emit("action-show-host", self.current_connection_uri())

    def prepare_vmlist(self):
        vmlist = self.window.get_widget("vm-list")

        # Handle, name, ID, status, status icon, cpu, [cpu graph], vcpus, mem, mem bar, uuid, diskRead, diskWrite, netRx, netTx
        model = gtk.TreeStore(object, str, str, str, gtk.gdk.Pixbuf, str, int, str, int, str, str, int, int, int, int)
        vmlist.set_model(model)
        util.tooltip_wrapper(vmlist, ROW_HINT, "set_tooltip_column")

        nameCol = gtk.TreeViewColumn(_("Name"))
        idCol = gtk.TreeViewColumn(_("ID"))
        statusCol = gtk.TreeViewColumn(_("Status"))
        cpuUsageCol = gtk.TreeViewColumn(_("CPU usage"))
        virtualCPUsCol = gtk.TreeViewColumn(_("CPUs"))
        memoryUsageCol = gtk.TreeViewColumn(_("Memory usage"))
        # FIXME: add KBytes/s tooltip
        diskIOCol = gtk.TreeViewColumn(_("Disk I/O"))
        networkTrafficCol = gtk.TreeViewColumn(_("Network I/O"))

        vmlist.append_column(nameCol)
        vmlist.append_column(idCol)
        vmlist.append_column(statusCol)
        vmlist.append_column(cpuUsageCol)
        vmlist.append_column(virtualCPUsCol)
        vmlist.append_column(memoryUsageCol)
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

        name_txt = gtk.CellRendererText()
        nameCol.pack_start(name_txt, True)
        nameCol.add_attribute(name_txt, 'text', ROW_NAME)
        nameCol.set_sort_column_id(VMLIST_SORT_NAME)

        id_txt = gtk.CellRendererText()
        idCol.pack_start(id_txt, True)
        idCol.add_attribute(id_txt, 'text', ROW_ID)
        idCol.set_visible(self.config.is_vmlist_domain_id_visible())
        idCol.set_sort_column_id(VMLIST_SORT_ID)

        status_txt = gtk.CellRendererText()
        status_icon = gtk.CellRendererPixbuf()
        statusCol.pack_start(status_icon, False)
        statusCol.pack_start(status_txt, False)
        statusCol.add_attribute(status_txt, 'text', ROW_STATUS)
        statusCol.add_attribute(status_icon, 'pixbuf', ROW_STATUS_ICON)
        statusCol.set_visible(self.config.is_vmlist_status_visible())

        cpuUsage_txt = gtk.CellRendererText()
        cpuUsage_img = sparkline.CellRendererSparkline()
        cpuUsage_img.set_property("reversed", True)
        cpuUsageCol.pack_start(cpuUsage_txt, False)
        cpuUsageCol.pack_start(cpuUsage_img, False)
        cpuUsageCol.add_attribute(cpuUsage_txt, 'text', ROW_CPU)
        cpuUsageCol.set_cell_data_func(cpuUsage_img, self.cpu_usage_img, None)
        cpuUsageCol.set_visible(self.config.is_vmlist_cpu_usage_visible())
        cpuUsageCol.set_sort_column_id(VMLIST_SORT_CPU_USAGE)

        virtualCPUs_txt = gtk.CellRendererText()
        virtualCPUsCol.pack_start(virtualCPUs_txt, False)
        virtualCPUsCol.add_attribute(virtualCPUs_txt, 'text', ROW_VCPUS)
        virtualCPUsCol.set_visible(self.config.is_vmlist_virtual_cpus_visible())

        memoryUsage_txt = gtk.CellRendererText()
        memoryUsage_img = gtk.CellRendererProgress()
        memoryUsageCol.pack_start(memoryUsage_txt, False)
        memoryUsageCol.pack_start(memoryUsage_img, False)
        memoryUsageCol.add_attribute(memoryUsage_txt, 'text', ROW_MEM)
        memoryUsageCol.add_attribute(memoryUsage_img, 'value', ROW_MEM_USAGE)
        memoryUsageCol.set_visible(self.config.is_vmlist_memory_usage_visible())
        memoryUsageCol.set_sort_column_id(VMLIST_SORT_MEMORY_USAGE)

        diskIOIn_txt = gtk.CellRendererText()
        diskIOOut_txt = gtk.CellRendererText()
        diskIO_img = sparkline.CellRendererSparkline()
        diskIO_img.set_property("reversed", True)
        diskIOCol.pack_start(diskIOIn_txt, False)
        diskIOCol.pack_start(diskIOOut_txt, False)
        diskIOCol.pack_start(diskIO_img, False)
        diskIOCol.add_attribute(diskIOIn_txt, 'text', ROW_DISK_RD)
        diskIOCol.add_attribute(diskIOOut_txt, 'text', ROW_DISK_WR)
        diskIOCol.set_cell_data_func(diskIO_img, self.disk_io_img, None)
        diskIOCol.set_visible(self.config.is_vmlist_disk_io_visible())
        diskIOCol.set_sort_column_id(VMLIST_SORT_DISK_IO)

        networkTrafficIn_txt = gtk.CellRendererText()
        networkTrafficOut_txt = gtk.CellRendererText()
        networkTraffic_img = sparkline.CellRendererSparkline()
        networkTraffic_img.set_property("reversed", True)
        networkTrafficCol.pack_start(networkTrafficIn_txt, False)
        networkTrafficCol.pack_start(networkTrafficOut_txt, False)
        networkTrafficCol.pack_start(networkTraffic_img, False)
        networkTrafficCol.add_attribute(networkTrafficIn_txt, 'text', ROW_NET_RX)
        networkTrafficCol.add_attribute(networkTrafficOut_txt, 'text', ROW_NET_TX)
        networkTrafficCol.set_cell_data_func(networkTraffic_img, self.network_traffic_img, None)
        networkTrafficCol.set_visible(self.config.is_vmlist_network_traffic_visible())
        networkTrafficCol.set_sort_column_id(VMLIST_SORT_NETWORK_USAGE)

        model.set_sort_func(VMLIST_SORT_ID, self.vmlist_domain_id_sorter)
        model.set_sort_func(VMLIST_SORT_NAME, self.vmlist_name_sorter)
        model.set_sort_func(VMLIST_SORT_CPU_USAGE, self.vmlist_cpu_usage_sorter)
        model.set_sort_func(VMLIST_SORT_MEMORY_USAGE, self.vmlist_memory_usage_sorter)
        model.set_sort_func(VMLIST_SORT_DISK_IO, self.vmlist_disk_io_sorter)
        model.set_sort_func(VMLIST_SORT_NETWORK_USAGE, self.vmlist_network_usage_sorter)

        model.set_sort_column_id(VMLIST_SORT_NAME, gtk.SORT_ASCENDING)


    def vmlist_domain_id_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).get_id(), model.get_value(iter2, ROW_HANDLE).get_id())

    def vmlist_name_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_NAME), model.get_value(iter2, ROW_NAME))

    def vmlist_cpu_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).cpu_time_percentage(), model.get_value(iter2, ROW_HANDLE).cpu_time_percentage())

    def vmlist_memory_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).current_memory_percentage(), model.get_value(iter2, ROW_HANDLE).current_memory_percentage())

    def vmlist_disk_io_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).disk_io_rate(), model.get_value(iter2, ROW_HANDLE).disk_io_rate())

    def vmlist_network_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).network_traffic_rate(), model.get_value(iter2, ROW_HANDLE).network_traffic_rate())

    def toggle_domain_id_visible_conf(self, menu):
        self.config.set_vmlist_domain_id_visible(menu.get_active())

    def toggle_domain_id_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_ID)
        col.set_visible(self.config.is_vmlist_domain_id_visible())

    def toggle_status_visible_conf(self, menu):
        self.config.set_vmlist_status_visible(menu.get_active())

    def toggle_status_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_STATUS)
        col.set_visible(self.config.is_vmlist_status_visible())

    def toggle_cpu_usage_visible_conf(self, menu):
        self.config.set_vmlist_cpu_usage_visible(menu.get_active())

    def toggle_cpu_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_CPU)
        col.set_visible(self.config.is_vmlist_cpu_usage_visible())

    def enable_polling(self, ignore1, ignore2, conf_entry, userdata):
        if userdata == VMLIST_SORT_CPU_USAGE:
            widgn = "menu_view_cpu_usage"
        elif userdata == VMLIST_SORT_MEMORY_USAGE:
            widgn = "menu_view_memory_usage"
        elif userdata == VMLIST_SORT_DISK_IO:
            widgn = "menu_view_disk_io"
        elif userdata == VMLIST_SORT_NETWORK_USAGE:
            widgn = "menu_view_network_traffic"
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

    def toggle_virtual_cpus_visible_conf(self, menu):
        self.config.set_vmlist_virtual_cpus_visible(menu.get_active())

    def toggle_virtual_cpus_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_VCPU)
        col.set_visible(self.config.is_vmlist_virtual_cpus_visible())

    def toggle_memory_usage_visible_conf(self, menu):
        self.config.set_vmlist_memory_usage_visible(menu.get_active())

    def toggle_memory_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_MEM)
        col.set_visible(self.config.is_vmlist_memory_usage_visible())

    def toggle_disk_io_visible_conf(self, menu):
        self.config.set_vmlist_disk_io_visible(menu.get_active())

    def toggle_disk_io_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_DISK)
        col.set_visible(self.config.is_vmlist_disk_io_visible())

    def toggle_network_traffic_visible_conf(self, menu):
        self.config.set_vmlist_network_traffic_visible(menu.get_active())

    def toggle_network_traffic_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_NETWORK)
        col.set_visible(self.config.is_vmlist_network_traffic_visible())

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

    def start_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-run-domain", vm.get_connection().get_uri(), vm.get_uuid())

    def reboot_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-reboot-domain", vm.get_connection().get_uri(), vm.get_uuid())

    def poweroff_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-shutdown-domain", vm.get_connection().get_uri(), vm.get_uuid())

    def destroy_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-destroy-domain", vm.get_connection().get_uri(), vm.get_uuid())

    def pause_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-suspend-domain", vm.get_connection().get_uri(), vm.get_uuid())

    def resume_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            self.emit("action-resume-domain", vm.get_connection().get_uri(), vm.get_uuid())

    def migrate(self, ignore):
        vm = self.current_vm()
        label = self.vmmenumigrate.get_active().get_image().get_stock()[0]
        hostname = label.split(" ")[0]
        if vm is not None:
            self.emit("action-migrate-domain", vm.get_connection().get_uri(),
                      vm.get_uuid(), hostname)

    def set_migrate_submenu(self, src):
        self.engine.populate_migrate_menu(self.vmmenumigrate, self.migrate)

    def _add_connection(self, engine, conn):
        conn.connect("vm-added", self.vm_added)
        conn.connect("vm-removed", self.vm_removed)
        conn.connect("resources-sampled", self.conn_refresh_resources)
        conn.connect("state-changed", self.conn_state_changed)
        conn.connect("connect-error", self._connect_error)
        conn.connect("vm-started", self.vm_started)
        # add the connection to the treeModel
        vmlist = self.window.get_widget("vm-list")
        if not self.rows.has_key(conn.get_uri()):
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

    def row_expanded(self, treeview, _iter, path):
        conn = treeview.get_model().get_value(_iter, ROW_HANDLE)
        conn.resume()

    def row_collapsed(self, treeview, _iter, path):
        conn = treeview.get_model().get_value(_iter, ROW_HANDLE)
        conn.pause()

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

gobject.type_register(vmmManager)

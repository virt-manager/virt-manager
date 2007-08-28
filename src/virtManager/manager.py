#
# Copyright (C) 2006 Red Hat, Inc.
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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import gobject
import gtk
import gtk.glade
import threading
import logging

import sparkline
import libvirt

import virtManager.connection as static_conn
from virtManager.asyncjob import vmmAsyncJob
        


VMLIST_SORT_ID = 1
VMLIST_SORT_NAME = 2
VMLIST_SORT_CPU_USAGE = 3
VMLIST_SORT_MEMORY_USAGE = 4
VMLIST_SORT_DISK_USAGE = 5
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
ROW_ACTION = 10

# Columns in the tree view
COL_NAME = 0
COL_ID = 1
COL_STATUS = 2
COL_CPU = 3
COL_VCPU = 4
COL_MEM = 5
COL_DISK = 6
COL_NETWORK = 7
COL_ACTION = 8

class vmmManager(gobject.GObject):
    __gsignals__ = {
        "action-show-connect":(gobject.SIGNAL_RUN_FIRST,
                                  gobject.TYPE_NONE, []),
        "action-show-console": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-terminal": (gobject.SIGNAL_RUN_FIRST,
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
        "action-connect": (gobject.SIGNAL_RUN_FIRST,
                           gobject.TYPE_NONE, [str]),
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                               gobject.TYPE_NONE, [str]),}

    def __init__(self, config):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-manager.glade", "vmm-manager", domain="virt-manager")
        self.config = config
        self.connections = {}
        self.prepare_vmlist()

        self.config.on_vmlist_domain_id_visible_changed(self.toggle_domain_id_visible_widget)
        self.config.on_vmlist_status_visible_changed(self.toggle_status_visible_widget)
        self.config.on_vmlist_cpu_usage_visible_changed(self.toggle_cpu_usage_visible_widget)
        self.config.on_vmlist_virtual_cpus_visible_changed(self.toggle_virtual_cpus_visible_widget)
        self.config.on_vmlist_memory_usage_visible_changed(self.toggle_memory_usage_visible_widget)
        self.config.on_vmlist_disk_usage_visible_changed(self.toggle_disk_usage_visible_widget)
        self.config.on_vmlist_network_traffic_visible_changed(self.toggle_network_traffic_visible_widget)

        self.window.get_widget("menu_view_domain_id").set_active(self.config.is_vmlist_domain_id_visible())
        self.window.get_widget("menu_view_status").set_active(self.config.is_vmlist_status_visible())
        self.window.get_widget("menu_view_cpu_usage").set_active(self.config.is_vmlist_cpu_usage_visible())
        self.window.get_widget("menu_view_virtual_cpus").set_active(self.config.is_vmlist_virtual_cpus_visible())
        self.window.get_widget("menu_view_memory_usage").set_active(self.config.is_vmlist_memory_usage_visible())
        self.window.get_widget("menu_view_disk_usage").set_active(self.config.is_vmlist_disk_usage_visible())
        self.window.get_widget("menu_view_network_traffic").set_active(self.config.is_vmlist_network_traffic_visible())
        self.window.get_widget("menu_view_disk_usage").set_sensitive(False)
        self.window.get_widget("menu_view_network_traffic").set_sensitive(False)

        self.window.get_widget("vm-view").set_active(0)

        self.vmmenu_icons = {}
        self.vmmenu_icons["run"] = gtk.Image()
        self.vmmenu_icons["run"].set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/icon_run.png", 18, 18))
        self.vmmenu_icons["pause"] = gtk.Image()
        self.vmmenu_icons["pause"].set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/icon_pause.png", 18, 18))
        self.vmmenu_icons["resume"] = gtk.Image()
        self.vmmenu_icons["resume"].set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/icon_pause.png", 18, 18))
        self.vmmenu_icons["shutdown"] = gtk.Image()
        self.vmmenu_icons["shutdown"].set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/icon_shutdown.png", 18, 18))

        self.vmmenu = gtk.Menu()
        self.vmmenu_items = {}

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

        self.vmmenu_items["shutdown"] = gtk.ImageMenuItem("_Shutdown")
        self.vmmenu_items["shutdown"].set_image(self.vmmenu_icons["shutdown"])
        self.vmmenu_items["shutdown"].show()
        self.vmmenu_items["shutdown"].connect("activate", self.stop_vm)
        self.vmmenu.add(self.vmmenu_items["shutdown"])

        self.vmmenu_items["hsep"] = gtk.SeparatorMenuItem()
        self.vmmenu_items["hsep"].show();
        self.vmmenu.add(self.vmmenu_items["hsep"])

        self.vmmenu_items["details"] = gtk.ImageMenuItem("_Details")
        self.vmmenu_items["details"].connect("activate", self.show_vm_details)
        self.vmmenu_items["details"].show()
        self.vmmenu.add(self.vmmenu_items["details"])

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
        self.connmenu_items["connect"].connect("activate", self.create_connection)
        self.connmenu.add(self.connmenu_items["connect"])

        self.connmenu_items["disconnect"] = gtk.ImageMenuItem(gtk.STOCK_DISCONNECT)
        self.connmenu_items["disconnect"].show()
        self.connmenu_items["disconnect"].connect("activate", self.destroy_connection)
        self.connmenu.add(self.connmenu_items["disconnect"])
        self.connmenu.show()

        self.window.signal_autoconnect({
            "on_menu_view_domain_id_activate" : self.toggle_domain_id_visible_conf,
            "on_menu_view_status_activate" : self.toggle_status_visible_conf,
            "on_menu_view_cpu_usage_activate" : self.toggle_cpu_usage_visible_conf,
            "on_menu_view_virtual_cpus_activate" : self.toggle_virtual_cpus_visible_conf,
            "on_menu_view_memory_usage_activate" : self.toggle_memory_usage_visible_conf,
            "on_menu_view_disk_usage_activate" : self.toggle_disk_usage_visible_conf,
            "on_menu_view_network_traffic_activate" : self.toggle_network_traffic_visible_conf,

            "on_vm_manager_delete_event": self.close,
            "on_menu_file_open_connection_activate": self.open_connection,
            "on_menu_file_quit_activate": self.exit_app,
            "on_menu_file_close_activate": self.close,
            "on_menu_restore_saved_activate": self.restore_saved,
            "on_vmm_close_clicked": self.close,
            "on_vm_details_clicked": self.show_vm_details,
            "on_vm_open_clicked": self.open_vm_console,
            "on_menu_edit_details_activate": self.show_vm_details,
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

        # store any error message from the restore-domain callback
        self.domain_restore_error = ""

        self.window.get_widget("menu_file_restore_saved").set_sensitive(False)

    def show(self):
        win = self.window.get_widget("vmm-manager")
        win.show_all()
        win.present()

    def close(self, src=None, src2=None):
        conns = self.connections.values()
        for conn in conns:
            conn.close()
        win = self.window.get_widget("vmm-manager")
        win.hide()
        return 1

    def is_visible(self):
        if self.window.get_widget("vmm-manager").flags() & gtk.VISIBLE:
           return 1
        return 0

    def exit_app(self, src=None, src2=None):
        gtk.main_quit()

    def open_connection(self, src=None):
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


    def restore_saved(self, src=None):

        # get filename
        self.fcdialog = gtk.FileChooserDialog(_("Restore Virtual Machine"),
                                              self.window.get_widget("vmm-manager"),
                                              gtk.FILE_CHOOSER_ACTION_OPEN,
                                              (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                               gtk.STOCK_OPEN, gtk.RESPONSE_ACCEPT),
                                              None)
        self.fcdialog.set_current_folder(self.config.get_default_save_dir(self.connections[self.get_current_connection()]))
        # pop up progress dialog
        response = self.fcdialog.run()
        self.fcdialog.hide()
        if(response == gtk.RESPONSE_ACCEPT):
            file_to_load = self.fcdialog.get_filename()
            if self.is_valid_saved_image(file_to_load):
                progWin = vmmAsyncJob(self.config,
                                      self.restore_saved_callback,
                                      [file_to_load],
                                      _("Restoring Virtual Machine"))
                progWin.run()
            else:
                err = gtk.MessageDialog(self.window.get_widget("vmm-manager"),
                                        gtk.DIALOG_DESTROY_WITH_PARENT,
                                        gtk.MESSAGE_ERROR,
                                        gtk.BUTTONS_OK,
                                        _("The file '%s' does not appear to be a valid saved machine image") % file_to_load)
                err.run()
                err.destroy()

        self.fcdialog.destroy()
        if(self.domain_restore_error != ""):
            self.error_msg = gtk.MessageDialog(self.window.get_widget("vmm-manager"),
                                               gtk.DIALOG_DESTROY_WITH_PARENT,
                                               gtk.MESSAGE_ERROR,
                                               gtk.BUTTONS_OK,
                                               self.domain_restore_error)
            self.error_msg.run()
            self.error_msg.destroy()
            self.domain_restore_error = ""

    def is_valid_saved_image(self, file):
        try:
            f = open(file, "r")
            magic = f.read(16)
            if magic != "LinuxGuestRecord":
                return False
            return True
        except:
            return False

    def restore_saved_callback(self, file_to_load, ignore1=None):
        status = self.connections[self.get_current_connection()].restore(file_to_load)
        if(status != 0):
            self.domain_restore_error = _("Error restoring domain '%s'. Is the domain already running?") % file_to_load

    def vm_view_changed(self, src):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()
        model.clear()
        self.rows = {}
        
        for uri in self.connections:
            conn = self.connections[uri]
            self._append_connection(model, uri)
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
            (gtype, host, port, transport) = vm.get_graphics_console()
            if gtype == "vnc":
                self.emit("action-show-console", uri, vmuuid)
            elif not connect.is_remote():
                self.emit("action-show-terminal", uri, vmuuid)

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
        row.insert(ROW_ACTION, "")
        iter = model.append(parent, row)
        path = model.get_path(iter)
        self.rows[vm.get_uuid()] = model[path]
        # Expand a connection when adding a vm to it
        self.window.get_widget("vm-list").expand_row(model.get_path(parent), False)

    def _append_connection(self, model, uri):
        row = []
        if self.connections.has_key(uri):
            row.insert(ROW_HANDLE, self.connections[uri])
            row.insert(ROW_STATUS, _("Connected"))
            row.insert(ROW_ACTION, "")
        else:
            row.insert(ROW_HANDLE, None)
            row.insert(ROW_STATUS, _("Disconnected"))
            row.insert(ROW_ACTION, gtk.STOCK_DELETE)
        row.insert(ROW_NAME, static_conn.get_short_hostname(uri))
        row.insert(ROW_ID, "")
        row.insert(ROW_STATUS_ICON, None)
        row.insert(ROW_CPU, "")
        row.insert(ROW_VCPUS, 0)
        row.insert(ROW_MEM, "")
        row.insert(ROW_MEM_USAGE, 0)
        row.insert(ROW_KEY, uri)
        iter = model.append(None, row)
        path = model.get_path(iter)
        self.rows[uri] = model[path]

    def vm_removed(self, connection, uri, vmuuid):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        parent = self.rows[connection.get_uri()].iter
        for row in range(model.iter_n_children(parent)):
            vm = model.get_value(model.iter_nth_child(parent, row), ROW_HANDLE)
            if vm.get_uuid() == vmuuid:
                model.remove(model.iter_nth_child(parent, row))
                del self.rows[vmuuid]
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
            iter = model.iter_nth_child(parent, row)
            if model.get_value(iter, ROW_KEY) == vm.get_uuid():
                if wanted:
                    missing = False
                else:
                    model.remove(model.iter_nth_child(parent, row))
                    del self.rows[vm.get_uuid()]
                break

        if missing and wanted:
            self._append_vm(model, vm, vm.get_connection())


    def vm_resources_sampled(self, vm):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        if not(self.rows.has_key(vm.get_uuid())):
            return

        row = self.rows[vm.get_uuid()]
        # Handle, name, ID, status, status icon, cpu, cpu graph, vcpus, mem, mem bar
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
        if vm.is_active():
            row[ROW_ACTION] = None
        else:
            row[ROW_ACTION] = gtk.STOCK_DELETE
        model.row_changed(row.path, row.iter)

    def conn_refresh_resources(self, connection):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()
        if not(self.rows.has_key(connection.get_uri())):
            return

        row = self.rows[connection.get_uri()]
        row[ROW_STATUS] = _("Active")
        row[ROW_CPU] = "%2.2f %%" % connection.cpu_time_percentage()
        row[ROW_VCPUS] = connection.host_active_processor_count()
        row[ROW_MEM] = connection.pretty_current_memory()
        row[ROW_MEM_USAGE] = connection.current_memory_percentage()
        row[ROW_ACTION] = gtk.STOCK_NEW
        model.row_changed(row.path, row.iter)

    def current_vm(self):
        vmlist = self.window.get_widget("vm-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        # check that something is selected and that it is a vm, not a connection
        if active[1] != None and active[0].iter_parent(active[1]) != None:
            return active[0].get_value(active[1], ROW_HANDLE)
        return None

    def get_current_connection(self):
        # returns a uri
        vmlist = self.window.get_widget("vm-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            parent = active[0].iter_parent(active[1])
            # return the connection of the currently selected vm, or the
            # currently selected connection
            if parent is not None:
                return active[0].get_value(parent, ROW_KEY)
            else:
                return active[0].get_value(active[1], ROW_KEY)
        return None

    def current_vmuuid(self):
        vm = self.current_vm()
        if vm is None:
            return None
        return vm.get_uuid()

    def show_vm_details(self,ignore):
        vm = self.current_vm()
        if vm is None:
            return
        conn = vm.get_connection()
        self.emit("action-show-details", conn.get_uri(), self.current_vmuuid())

    def show_vm_create(self,ignore):
        self.emit("action-show-create", self.get_current_connection())

    def destroy_connection(self, ignore):
        current_uri = self.get_current_connection()
        if self.connections.has_key(current_uri):
            self.connections[current_uri].close()

    def create_connection(self, ignore):
        current_uri = self.get_current_connection()
        if not self.connections.has_key(current_uri):
            self.emit("action-connect", current_uri)

    def open_vm_console(self,ignore,ignore2=None,ignore3=None):
        self.emit("action-show-console", self.get_current_connection(), self.current_vmuuid())


    def vm_selected(self, selection):
        vm = self.current_vm()
        if selection == None or selection.count_selected_rows() == 0:
            self.window.get_widget("vm-details").set_sensitive(False)
            self.window.get_widget("vm-open").set_sensitive(False)
            self.window.get_widget("menu_edit_details").set_sensitive(False)
        elif vm is not None:
            # this is strange to call this here, but it simplifies the code
            # updating the treeview
            self.vm_resources_sampled(vm)
            self.window.get_widget("vm-details").set_sensitive(True)
            self.window.get_widget("vm-open").set_sensitive(True)
            self.window.get_widget("menu_edit_details").set_sensitive(True)
        else:
            self.window.get_widget("vm-details").set_sensitive(False)
            self.window.get_widget("vm-open").set_sensitive(False)
            self.window.get_widget("menu_edit_details").set_sensitive(False)

    def popup_vm_menu(self, widget, event):
        tuple = widget.get_path_at_pos(int(event.x), int(event.y))
        if tuple == None:
            return False
        path = tuple[0]
        model = widget.get_model()
        iter = model.get_iter(path)
        if model.iter_parent(iter) != None:
            # a vm is selected, retrieve it from the first column of the model
            vm = model.get_value(iter, ROW_HANDLE)
            if event.button == 3:
                # Update popup menu based upon vm status
                if vm.is_read_only() == True:
                    self.vmmenu_items["run"].set_sensitive(False)
                    self.vmmenu_items["pause"].set_sensitive(False)
                    self.vmmenu_items["pause"].show()
                    self.vmmenu_items["resume"].hide()
                    self.vmmenu_items["resume"].set_sensitive(False)
                    self.vmmenu_items["shutdown"].set_sensitive(False)
                else:
                    if vm.status() == libvirt.VIR_DOMAIN_SHUTOFF:
                        self.vmmenu_items["run"].set_sensitive(True)
                        self.vmmenu_items["pause"].set_sensitive(False)
                        self.vmmenu_items["pause"].show()
                        self.vmmenu_items["resume"].hide()
                        self.vmmenu_items["resume"].set_sensitive(False)
                        self.vmmenu_items["shutdown"].set_sensitive(False)
                    elif vm.status() == libvirt.VIR_DOMAIN_RUNNING:
                        self.vmmenu_items["run"].set_sensitive(False)
                        self.vmmenu_items["pause"].set_sensitive(True)
                        self.vmmenu_items["pause"].show()
                        self.vmmenu_items["resume"].hide()
                        self.vmmenu_items["resume"].set_sensitive(False)
                        self.vmmenu_items["shutdown"].set_sensitive(True)
                    elif vm.status() == libvirt.VIR_DOMAIN_PAUSED:
                        self.vmmenu_items["run"].set_sensitive(False)
                        self.vmmenu_items["pause"].hide()
                        self.vmmenu_items["pause"].set_sensitive(False)
                        self.vmmenu_items["resume"].show()
                        self.vmmenu_items["resume"].set_sensitive(True)
                        self.vmmenu_items["shutdown"].set_sensitive(True)              
                self.vmmenu.popup(None, None, None, 0, event.time)
            elif event.button == 1:
                # check if the "delete" icon was clicked and act accordingly
                logging.debug("Clicked a VM row")
                area = widget.get_cell_area(path, widget.get_column(COL_ACTION))
                if int(event.x) > area.x and int(event.x) < area.x + area.width \
                       and not vm.is_active():
                    # are you sure you want to delete this VM?
                    warn = gtk.MessageDialog(self.window.get_widget("vmm-manager"),
                                             gtk.DIALOG_DESTROY_WITH_PARENT,
                                             gtk.MESSAGE_WARNING,
                                             gtk.BUTTONS_YES_NO,
                                             _("This will permanently delete the vm \"%s,\" are you sure?") % vm.get_name())
                    result = warn.run()
                    warn.destroy()
                    if result == gtk.RESPONSE_NO:
                        return
                    conn = vm.get_connection()
                    vm.delete()
                    conn.tick(noStatsUpdate=True)
            return False
        else:
            uri = model.get_value(iter, ROW_KEY)
            if event.button == 3:
                if self.connections.has_key(uri):
                    self.connmenu_items["create"].set_sensitive(True)
                    self.connmenu_items["disconnect"].set_sensitive(True)
                    self.connmenu_items["connect"].set_sensitive(False)
                else:
                    self.connmenu_items["create"].set_sensitive(False)
                    self.connmenu_items["disconnect"].set_sensitive(False)
                    self.connmenu_items["connect"].set_sensitive(True)
                self.connmenu.popup(None, None, None, 0, event.time)
            elif event.button == 1:
                logging.debug("Clicked a connection row")
                area = widget.get_cell_area(path, widget.get_column(COL_ACTION))
                if int(event.x) > area.x and int(event.x) < area.x + area.width:
                    # clicked the action column
                    if self.connections.has_key(uri):
                        self.emit("action-show-create", uri)
                    else:
                        warn = gtk.MessageDialog(self.window.get_widget("vmm-manager"),
                                                 gtk.DIALOG_DESTROY_WITH_PARENT,
                                                 gtk.MESSAGE_WARNING,
                                                 gtk.BUTTONS_YES_NO,
                                                 _("This will permanently delete the connection \"%s\", are you sure?") % self.rows[uri][ROW_NAME])
                        result = warn.run()
                        warn.destroy()
                        if result == gtk.RESPONSE_NO:
                            return
                        self.delete_connection(uri)
            return False 

    def show_about(self, src):
        self.emit("action-show-about")

    def show_help(self, src):
        # From the manager window, show the help document from the beginning
        self.emit("action-show-help", None) #No 'id', load the front page

    def show_preferences(self, src):
        self.emit("action-show-preferences")

    def show_host(self, src):
        self.emit("action-show-host", self.get_current_connection())

    def prepare_vmlist(self):
        vmlist = self.window.get_widget("vm-list")

        # Handle, name, ID, status, status icon, cpu, [cpu graph], vcpus, mem, mem bar, uuid, action icon
        model = gtk.TreeStore(object, str, str, str, gtk.gdk.Pixbuf, str, int, str, int, str, str)
        vmlist.set_model(model)

        nameCol = gtk.TreeViewColumn(_("Name"))
        idCol = gtk.TreeViewColumn(_("ID"))
        statusCol = gtk.TreeViewColumn(_("Status"))
        cpuUsageCol = gtk.TreeViewColumn(_("CPU usage"))
        virtualCPUsCol = gtk.TreeViewColumn(_("VCPUs"))
        memoryUsageCol = gtk.TreeViewColumn(_("Memory usage"))
        diskUsageCol = gtk.TreeViewColumn(_("Disk usage"))
        networkTrafficCol = gtk.TreeViewColumn(_("Network traffic"))
        #actionCol = gtk.TreeViewColumn(_("Action"))
        actionCol = gtk.TreeViewColumn("")

        vmlist.append_column(nameCol)
        vmlist.append_column(idCol)
        vmlist.append_column(statusCol)
        vmlist.append_column(cpuUsageCol)
        vmlist.append_column(virtualCPUsCol)
        vmlist.append_column(memoryUsageCol)
        vmlist.append_column(diskUsageCol)
        vmlist.append_column(networkTrafficCol)
        vmlist.append_column(actionCol)

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
        nameCol.add_attribute(name_txt, 'text', 1)
        nameCol.set_sort_column_id(VMLIST_SORT_NAME)

        id_txt = gtk.CellRendererText()
        idCol.pack_start(id_txt, True)
        idCol.add_attribute(id_txt, 'text', 2)
        idCol.set_visible(self.config.is_vmlist_domain_id_visible())
        idCol.set_sort_column_id(VMLIST_SORT_ID)

        status_txt = gtk.CellRendererText()
        status_icon = gtk.CellRendererPixbuf()
        statusCol.pack_start(status_icon, False)
        statusCol.pack_start(status_txt, False)
        statusCol.add_attribute(status_txt, 'text', 3)
        statusCol.add_attribute(status_icon, 'pixbuf', 4)
        statusCol.set_visible(self.config.is_vmlist_status_visible())

        cpuUsage_txt = gtk.CellRendererText()
        cpuUsage_img = sparkline.CellRendererSparkline()
        cpuUsageCol.pack_start(cpuUsage_txt, False)
        cpuUsageCol.pack_start(cpuUsage_img, False)
        cpuUsageCol.add_attribute(cpuUsage_txt, 'text', 5)
        cpuUsageCol.set_cell_data_func(cpuUsage_img, self.cpu_usage_img, None)
        cpuUsageCol.set_visible(self.config.is_vmlist_cpu_usage_visible())
        cpuUsageCol.set_sort_column_id(VMLIST_SORT_CPU_USAGE)

        virtualCPUs_txt = gtk.CellRendererText()
        virtualCPUsCol.pack_start(virtualCPUs_txt, False)
        virtualCPUsCol.add_attribute(virtualCPUs_txt, 'text', 6)
        virtualCPUsCol.set_visible(self.config.is_vmlist_virtual_cpus_visible())

        memoryUsage_txt = gtk.CellRendererText()
        memoryUsage_img = gtk.CellRendererProgress()
        memoryUsageCol.pack_start(memoryUsage_txt, False)
        memoryUsageCol.pack_start(memoryUsage_img, False)
        memoryUsageCol.add_attribute(memoryUsage_txt, 'text', 7)
        memoryUsageCol.add_attribute(memoryUsage_img, 'value', 8)
        memoryUsageCol.set_visible(self.config.is_vmlist_memory_usage_visible())
        memoryUsageCol.set_sort_column_id(VMLIST_SORT_MEMORY_USAGE)

        diskUsage_txt = gtk.CellRendererText()
        diskUsage_img = gtk.CellRendererProgress()
        diskUsageCol.pack_start(diskUsage_txt, False)
        diskUsageCol.pack_start(diskUsage_img, False)
        diskUsageCol.set_visible(self.config.is_vmlist_disk_usage_visible())
        diskUsageCol.set_sort_column_id(VMLIST_SORT_DISK_USAGE)

        networkTraffic_txt = gtk.CellRendererText()
        networkTraffic_img = gtk.CellRendererProgress()
        networkTrafficCol.pack_start(networkTraffic_txt, False)
        networkTrafficCol.pack_start(networkTraffic_img, False)
        networkTrafficCol.set_visible(self.config.is_vmlist_network_traffic_visible())
        networkTrafficCol.set_sort_column_id(VMLIST_SORT_NETWORK_USAGE)

        action_icon = gtk.CellRendererPixbuf()
        action_icon.set_property('stock-size', gtk.ICON_SIZE_MENU)
        actionCol.pack_start(action_icon, False)
        actionCol.add_attribute(action_icon, 'stock-id', 10)
        actionCol.set_visible(True)

        model.set_sort_func(VMLIST_SORT_ID, self.vmlist_domain_id_sorter)
        model.set_sort_func(VMLIST_SORT_NAME, self.vmlist_name_sorter)
        model.set_sort_func(VMLIST_SORT_CPU_USAGE, self.vmlist_cpu_usage_sorter)
        model.set_sort_func(VMLIST_SORT_MEMORY_USAGE, self.vmlist_memory_usage_sorter)
        model.set_sort_func(VMLIST_SORT_DISK_USAGE, self.vmlist_disk_usage_sorter)
        model.set_sort_func(VMLIST_SORT_NETWORK_USAGE, self.vmlist_network_usage_sorter)

        model.set_sort_column_id(VMLIST_SORT_NAME, gtk.SORT_ASCENDING)


    def vmlist_domain_id_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).get_id(), model.get_value(iter2, ROW_HANDLE).get_id())

    def vmlist_name_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_NAME), model.get_value(iter2, ROW_NAME))

    def vmlist_cpu_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).cpu_time(), model.get_value(iter2, ROW_HANDLE).cpu_time())

    def vmlist_memory_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).get_memory(), model.get_value(iter2, ROW_HANDLE).get_memory())

    def vmlist_disk_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).disk_usage(), model.get_value(iter2, ROW_HANDLE).disk_usage())

    def vmlist_network_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, ROW_HANDLE).network_traffic(), model.get_value(iter2, ROW_HANDLE).network_traffic())

    def toggle_domain_id_visible_conf(self, menu):
        self.config.set_vmlist_domain_id_visible(menu.get_active())

    def toggle_domain_id_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_domain_id")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_ID)
        col.set_visible(self.config.is_vmlist_domain_id_visible())

    def toggle_status_visible_conf(self, menu):
        self.config.set_vmlist_status_visible(menu.get_active())

    def toggle_status_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_status")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_STATUS)
        col.set_visible(self.config.is_vmlist_status_visible())

    def toggle_cpu_usage_visible_conf(self, menu):
        self.config.set_vmlist_cpu_usage_visible(menu.get_active())

    def toggle_cpu_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_cpu_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_CPU)
        col.set_visible(self.config.is_vmlist_cpu_usage_visible())

    def toggle_virtual_cpus_visible_conf(self, menu):
        self.config.set_vmlist_virtual_cpus_visible(menu.get_active())

    def toggle_virtual_cpus_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_virtual_cpus")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_VCPU)
        col.set_visible(self.config.is_vmlist_virtual_cpus_visible())

    def toggle_memory_usage_visible_conf(self, menu):
        self.config.set_vmlist_memory_usage_visible(menu.get_active())

    def toggle_memory_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_memory_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_MEM)
        col.set_visible(self.config.is_vmlist_memory_usage_visible())

    def toggle_disk_usage_visible_conf(self, menu):
        self.config.set_vmlist_disk_usage_visible(menu.get_active())

    def toggle_disk_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_disk_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_DISK)
        col.set_visible(self.config.is_vmlist_disk_usage_visible())

    def toggle_network_traffic_visible_conf(self, menu):
        self.config.set_vmlist_network_traffic_visible(menu.get_active())

    def toggle_network_traffic_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_network_traffic")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(COL_NETWORK)
        col.set_visible(self.config.is_vmlist_network_traffic_visible())

    def cpu_usage_img(self,  column, cell, model, iter, data):
        if model.get_value(iter, ROW_HANDLE) is None:
            return
        data = model.get_value(iter, ROW_HANDLE).cpu_time_vector_limit(40)
        data.reverse()
        cell.set_property('data_array', data)

    def start_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            vm.startup()

    def stop_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            vm.shutdown()

    def pause_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            vm.suspend()

    def resume_vm(self, ignore):
        vm = self.current_vm()
        if vm is not None:
            vm.resume()
        
    def connect_connection(self, connection):
        connection.connect("vm-added", self.vm_added)
        connection.connect("vm-removed", self.vm_removed)
        connection.connect("resources-sampled", self.conn_refresh_resources)
        connection.connect("vm-started", self.vm_started)
        self.connections[connection.uri] = connection
        self.add_connection(connection.uri)

    def add_connection(self, uri):
        # add the connection to the treeModel
        vmlist = self.window.get_widget("vm-list")
        if self.rows.has_key(uri):
            if self.connections.has_key(uri):
                self.rows[uri][ROW_HANDLE] = self.connections[uri]
        else:
            self._append_connection(vmlist.get_model(), uri)
            self.config.add_connection(uri)
                
    def disconnect_connection(self, uri):
        treeview = self.window.get_widget("vm-list")
        model = treeview.get_model()
        parent = self.rows[uri].iter
        if parent is not None:
            child = model.iter_children(parent)
            while child is not None:
                del self.rows[model.get_value(child, ROW_KEY)]
                model.remove(child)
                child = model.iter_children(parent)
        row = self.rows[uri]
        row[ROW_HANDLE] = None
        # keep uri and name for connection, so we can reconnect if needed
        row[ROW_STATUS] = _("Disconnected")
        row[ROW_VCPUS] = 0
        row[ROW_MEM] = ""
        row[ROW_MEM_USAGE] = 0
        row[ROW_ACTION] = gtk.STOCK_DELETE
        treeview.get_model().row_changed(row.path, row.iter)
        del self.connections[uri]

    def delete_connection(self, uri):
        model = self.window.get_widget("vm-list").get_model()
        parent = self.rows[uri].iter
        if self.rows[uri][ROW_HANDLE] is not None:
            # connection is still connected, don't delete it
            return
        if parent is not None:
            child = model.iter_children(parent)
            while child is not None:
                del self.rows[model.get_value(child, ROW_KEY)]
                model.remove(child)
                child = model.iter_children(parent)
            model.remove(parent)
            del self.rows[uri]
        self.config.remove_connection(uri)

    def row_expanded(self, treeview, iter, path):
        conn = treeview.get_model().get_value(iter,ROW_HANDLE)
        if conn is None:
            treeview.collapse_row(path, false)
            return
        logging.debug("Activating connection %s" % conn.get_name())
        conn.active = True
        
    def row_collapsed(self, treeview, iter, path):
        conn = treeview.get_model().get_value(iter,ROW_HANDLE)
        logging.debug("Deactivating connection %s" % conn.get_name())
        conn.active = False
        row = self.rows[conn.get_uri()]
        row[ROW_STATUS] = _("Inactive")
        row[ROW_CPU] = ""
        row[ROW_VCPUS] = 0
        row[ROW_MEM] = ""
        row[ROW_MEM_USAGE] = 0
        treeview.get_model().row_changed(row.path, row.iter)

gobject.type_register(vmmManager)

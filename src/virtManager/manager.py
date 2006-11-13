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

import sparkline

from virtManager.asyncjob import vmmAsyncJob

VMLIST_SORT_ID = 1
VMLIST_SORT_NAME = 2
VMLIST_SORT_CPU_USAGE = 3
VMLIST_SORT_MEMORY_USAGE = 4
VMLIST_SORT_DISK_USAGE = 5
VMLIST_SORT_NETWORK_USAGE = 6

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
        "action-show-preferences": (gobject.SIGNAL_RUN_FIRST,
                                    gobject.TYPE_NONE, []),
        "action-show-create": (gobject.SIGNAL_RUN_FIRST,
                               gobject.TYPE_NONE, [str]),}
    def __init__(self, config, connection):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-manager", domain="virt-manager")
        self.config = config
        self.connection = connection
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


        if self.connection.is_read_only():
            self.window.get_widget("menu_file_new").set_sensitive(False)
            self.window.get_widget("menu_file_restore_saved").set_sensitive(False)
            self.window.get_widget("vm-new").set_sensitive(False)
        else:
            self.window.get_widget("menu_file_new").set_sensitive(True)
            self.window.get_widget("vm-new").set_sensitive(True)
            self.window.get_widget("menu_file_restore_saved").set_sensitive(True)

        self.window.get_widget("vm-view").set_active(0)

        self.vmmenu = gtk.Menu()
        self.vmmenu_items = {}

        self.vmmenu_items["details"] = gtk.MenuItem("_Details")
        self.vmmenu_items["details"].connect("activate", self.show_vm_details)
        self.vmmenu_items["details"].show()
        self.vmmenu.add(self.vmmenu_items["details"])

        self.vmmenu_items["open"] = gtk.ImageMenuItem(gtk.STOCK_OPEN)
        self.vmmenu_items["open"].connect("activate", self.open_vm_console)
        self.vmmenu_items["open"].show()
        self.vmmenu.add(self.vmmenu_items["open"])

        self.vmmenu.show_all()

        # Mapping of VM UUID -> tree model rows to
        # allow O(1) access instead of O(n)
        self.rows = {}

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
            "on_menu_file_new_activate": self.show_vm_create,
            "on_menu_file_quit_activate": self.exit_app,
            "on_menu_file_close_activate": self.close,
            "on_menu_restore_saved_activate": self.restore_saved,
            "on_vmm_close_clicked": self.close,
            "on_vm_details_clicked": self.show_vm_details,
            "on_vm_open_clicked": self.open_vm_console,
            "on_vm_new_clicked": self.show_vm_create,
            "on_vm_delete_clicked": self.delete_vm,
            "on_menu_edit_details_activate": self.show_vm_details,

            "on_vm_view_changed": self.vm_view_changed,
            "on_vm_list_row_activated": self.open_vm_console,

            "on_vm_list_button_press_event": self.popup_vm_menu,

            "on_menu_edit_preferences_activate": self.show_preferences,
            "on_menu_help_about_activate": self.show_about,
            })

        self.vm_selected(None)
        self.window.get_widget("vm-list").get_selection().connect("changed", self.vm_selected)
        self.connection.connect("disconnected", self.close)

        self.connection.connect("vm-added", self.vm_added)
        self.connection.connect("vm-removed", self.vm_removed)

        win = self.window.get_widget("vmm-manager")
        win.set_title(win.get_title() + " (" + self.connection.get_name() + ")")

        # store any error message from the restore-domain callback
        self.domain_restore_error = ""

    def show(self):
        win = self.window.get_widget("vmm-manager")
        win.show_all()
        win.present()

    def close(self, src=None, src2=None):
        self.connection.close()
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

    def restore_saved_callback(self, file_to_load):
        status = self.connection.restore(file_to_load)
        if(status != 0):
            self.domain_restore_error = _("Error restoring domain '%s'. Is the domain already running?") % file_to_load

    def vm_view_changed(self, src):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()
        model.clear()
        self.rows = {}

        uuids = self.connection.list_vm_uuids()
        for vmuuid in uuids:
            vm = self.connection.get_vm(vmuuid)
            if vm.is_active():
                if not(self.is_showing_active()):
                    continue
            else:
                if not(self.is_showing_inactive()):
                    continue

            self._append_vm(model, vm)

    def vm_added(self, connection, uri, vmuuid):
        vm = self.connection.get_vm(vmuuid)
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

        self._append_vm(model, vm)

        if self.config.get_console_popup() == 2 and range(model.iter_n_children(None)) > 1:
            # user has requested consoles on all vms
            (gtype, host, port) = vm.get_graphics_console()
            if gtype == "vnc":
                self.emit("action-show-console", uri, vmuuid)
            else:
                self.emit("action-show-terminal", uri, vmuuid)
        
    def _append_vm(self, model, vm):
        # Handle, name, ID, status, status icon, cpu, [cpu graph], vcpus, mem, mem bar
        iter = model.append([vm, vm.get_name(), vm.get_id_pretty(), vm.run_status(), \
                             vm.run_status_icon(), vm.cpu_time_pretty(), vm.vcpu_count(), \
                             vm.current_memory_pretty(), vm.current_memory_percentage()])
        path = model.get_path(iter)
        self.rows[vm.get_uuid()] = model[path]

    def vm_removed(self, connection, uri, vmuuid):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        for row in range(model.iter_n_children(None)):
            vm = model.get_value(model.iter_nth_child(None, row), 0)
            if vm.get_uuid() == vmuuid:
                model.remove(model.iter_nth_child(None, row))
                del self.rows[vmuuid]
                break

    def vm_status_changed(self, vm, status):
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
        for row in range(model.iter_n_children(None)):
            iter = model.iter_nth_child(None, row)
            if model.get_value(iter, 0).get_uuid() == vm.get_uuid():
                if wanted:
                    missing = False
                else:
                    model.remove(model.iter_nth_child(None, row))
                    del self.rows[vm.get_uuid()]
                break

        if missing and wanted:
            self._append_vm(model, vm)


    def vm_resources_sampled(self, vm):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        if not(self.rows.has_key(vm.get_uuid())):
            return

        row = self.rows[vm.get_uuid()]
        # Handle, name, ID, status, status icon, cpu, cpu graph, vcpus, mem, mem bar
        if vm.get_id() == -1:
            row[2] = "-"
        else:
            row[2] = vm.get_id()
        row[3] = vm.run_status()
        row[4] = vm.run_status_icon()
        row[5] = vm.cpu_time_pretty()
        row[6] = vm.vcpu_count()
        row[7] = vm.current_memory_pretty()
        row[8] = vm.current_memory_percentage()
        model.row_changed(row.path, row.iter)

    def current_vm(self):
        vmlist = self.window.get_widget("vm-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            return active[0].get_value(active[1], 0)
        return None

    def current_vmuuid(self):
        vm = self.current_vm()
        if vm is None:
            return None
        return vm.get_uuid()

    def delete_vm(self, src=None):
        vm = self.current_vm()
        if vm is None or vm.is_active():
            return

        vm.delete()
        self.connection.tick(noStatsUpdate=True)

    def show_vm_details(self,ignore):
        self.emit("action-show-details", self.connection.get_uri(), self.current_vmuuid())

    def show_vm_create(self,ignore):
        self.emit("action-show-create", self.connection.get_uri())

    def open_vm_console(self,ignore,ignore2=None,ignore3=None):
        self.emit("action-show-console", self.connection.get_uri(), self.current_vmuuid())


    def vm_selected(self, selection):
        if selection == None or selection.count_selected_rows() == 0:
            self.window.get_widget("vm-delete").set_sensitive(False)
            self.window.get_widget("vm-details").set_sensitive(False)
            self.window.get_widget("vm-open").set_sensitive(False)
            self.window.get_widget("menu_edit_delete").set_sensitive(False)
            self.window.get_widget("menu_edit_details").set_sensitive(False)
        else:
            vm = self.current_vm()
            if vm.is_active():
                self.window.get_widget("vm-delete").set_sensitive(False)
                self.window.get_widget("menu_edit_delete").set_sensitive(False)
            else:
                self.window.get_widget("vm-delete").set_sensitive(True)
                self.window.get_widget("menu_edit_delete").set_sensitive(True)
            self.window.get_widget("vm-details").set_sensitive(True)
            self.window.get_widget("vm-open").set_sensitive(True)
            self.window.get_widget("menu_edit_details").set_sensitive(True)

    def popup_vm_menu(self, widget, event):
        vm = self.current_vm()
        if vm != None:
            if event.button == 3:
                self.vmmenu.popup(None, None, None, 0, event.time)

    def show_about(self, src):
        self.emit("action-show-about")

    def show_preferences(self, src):
        self.emit("action-show-preferences")

    def prepare_vmlist(self):
        vmlist = self.window.get_widget("vm-list")

        # Handle, name, ID, status, status icon, cpu, [cpu graph], vcpus, mem, mem bar
        model = gtk.ListStore(object, str, str, str, gtk.gdk.Pixbuf, str, int, str, int)
        vmlist.set_model(model)

        idCol = gtk.TreeViewColumn(_("ID"))
        nameCol = gtk.TreeViewColumn(_("Name"))
        statusCol = gtk.TreeViewColumn(_("Status"))
        cpuUsageCol = gtk.TreeViewColumn(_("CPU usage"))
        virtualCPUsCol = gtk.TreeViewColumn(_("VCPUs"))
        memoryUsageCol = gtk.TreeViewColumn(_("Memory usage"))
        diskUsageCol = gtk.TreeViewColumn(_("Disk usage"))
        networkTrafficCol = gtk.TreeViewColumn(_("Network traffic"))

        vmlist.append_column(idCol)
        vmlist.append_column(nameCol)
        vmlist.append_column(statusCol)
        vmlist.append_column(cpuUsageCol)
        vmlist.append_column(virtualCPUsCol)
        vmlist.append_column(memoryUsageCol)
        vmlist.append_column(diskUsageCol)
        vmlist.append_column(networkTrafficCol)

        # For the columsn which follow, we delibrately bind columns
        # to fields in the list store & on each update copy the info
        # out of the vmmDomain object into the store. Although this
        # sounds foolish, empirically this is faster than using the
        # set_cell_data_func() callbacks to pull the data out of
        # vmmDomain on demand. I suspect this is because the latter
        # needs to do many transitions  C<->Python for callbacks
        # which are relatively slow.

        id_txt = gtk.CellRendererText()
        idCol.pack_start(id_txt, True)
        idCol.add_attribute(id_txt, 'text', 2)
        idCol.set_visible(self.config.is_vmlist_domain_id_visible())
        idCol.set_sort_column_id(VMLIST_SORT_ID)

        name_txt = gtk.CellRendererText()
        nameCol.pack_start(name_txt, True)
        nameCol.add_attribute(name_txt, 'text', 1)
        nameCol.set_sort_column_id(VMLIST_SORT_NAME)

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

        model.set_sort_func(VMLIST_SORT_ID, self.vmlist_domain_id_sorter)
        model.set_sort_func(VMLIST_SORT_NAME, self.vmlist_name_sorter)
        model.set_sort_func(VMLIST_SORT_CPU_USAGE, self.vmlist_cpu_usage_sorter)
        model.set_sort_func(VMLIST_SORT_MEMORY_USAGE, self.vmlist_memory_usage_sorter)
        model.set_sort_func(VMLIST_SORT_DISK_USAGE, self.vmlist_disk_usage_sorter)
        model.set_sort_func(VMLIST_SORT_NETWORK_USAGE, self.vmlist_network_usage_sorter)

        model.set_sort_column_id(VMLIST_SORT_NAME, gtk.SORT_ASCENDING)


    def vmlist_domain_id_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, 0).get_id(), model.get_value(iter2, 0).get_id())

    def vmlist_name_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, 1), model.get_value(iter2, 1))

    def vmlist_cpu_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, 0).cpu_time(), model.get_value(iter2, 0).cpu_time())

    def vmlist_memory_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, 0).current_memory(), model.get_value(iter2, 0).current_memory())

    def vmlist_disk_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, 0).disk_usage(), model.get_value(iter2, 0).disk_usage())

    def vmlist_network_usage_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, 0).network_traffic(), model.get_value(iter2, 0).network_traffic())

    def toggle_domain_id_visible_conf(self, menu):
        self.config.set_vmlist_domain_id_visible(menu.get_active())

    def toggle_domain_id_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_domain_id")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(0)
        col.set_visible(self.config.is_vmlist_domain_id_visible())

    def toggle_status_visible_conf(self, menu):
        self.config.set_vmlist_status_visible(menu.get_active())

    def toggle_status_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_status")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(2)
        col.set_visible(self.config.is_vmlist_status_visible())

    def toggle_cpu_usage_visible_conf(self, menu):
        self.config.set_vmlist_cpu_usage_visible(menu.get_active())

    def toggle_cpu_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_cpu_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(3)
        col.set_visible(self.config.is_vmlist_cpu_usage_visible())

    def toggle_virtual_cpus_visible_conf(self, menu):
        self.config.set_vmlist_virtual_cpus_visible(menu.get_active())

    def toggle_virtual_cpus_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_virtual_cpus")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(4)
        col.set_visible(self.config.is_vmlist_virtual_cpus_visible())

    def toggle_memory_usage_visible_conf(self, menu):
        self.config.set_vmlist_memory_usage_visible(menu.get_active())

    def toggle_memory_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_memory_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(5)
        col.set_visible(self.config.is_vmlist_memory_usage_visible())

    def toggle_disk_usage_visible_conf(self, menu):
        self.config.set_vmlist_disk_usage_visible(menu.get_active())

    def toggle_disk_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_disk_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(6)
        col.set_visible(self.config.is_vmlist_disk_usage_visible())

    def toggle_network_traffic_visible_conf(self, menu):
        self.config.set_vmlist_network_traffic_visible(menu.get_active())

    def toggle_network_traffic_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_network_traffic")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(7)
        col.set_visible(self.config.is_vmlist_network_traffic_visible())

    def cpu_usage_img(self,  column, cell, model, iter, data):
        data = model.get_value(iter, 0).cpu_time_vector_limit(40)
        data.reverse()
        cell.set_property('data_array', data)

gobject.type_register(vmmManager)

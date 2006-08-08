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
        "action-show-details": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-about": (gobject.SIGNAL_RUN_FIRST,
                              gobject.TYPE_NONE, []),
        "action-show-preferences": (gobject.SIGNAL_RUN_FIRST,
                                    gobject.TYPE_NONE, []),
        "action-show-create": (gobject.SIGNAL_RUN_FIRST,
                               gobject.TYPE_NONE, []),}
    def __init__(self, config, connection):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-manager")
        self.config = config
        self.connection = connection
        self.prepare_vmlist()

        self.connection.connect("vm-added", self.vm_added)
        self.connection.connect("vm-removed", self.vm_removed)

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


        self.window.get_widget("menu_file_new").set_sensitive(True)
        self.window.get_widget("vm-new").set_sensitive(True)
        self.window.get_widget("vm-view").set_sensitive(False)
        self.window.get_widget("vm-view").set_active(0)

        self.vmmenu = gtk.Menu()
        self.vmmenu_items = {}

        self.vmmenu_items["details"] = gtk.MenuItem("_Details")
        self.vmmenu_items["details"].connect("activate", self.show_vm_details)
        self.vmmenu_items["details"].show()
        self.vmmenu.add(self.vmmenu_items["details"])

        self.vmmenu_items["open"] = gtk.MenuItem("Open")
        self.vmmenu_items["open"].connect("activate", self.open_vm_console)
        self.vmmenu_items["open"].show()
        self.vmmenu.add(self.vmmenu_items["open"])

        self.vmmenu.show_all()


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
            "on_menu_edit_details_activate": self.show_vm_details,

            "on_vm_list_row_activated": self.open_vm_console,

            "on_vm_list_button_press_event": self.popup_vm_menu,

            "on_menu_edit_preferences_activate": self.show_preferences,
            "on_menu_help_about_activate": self.show_about,
            })

        self.vm_selected(None)
        self.window.get_widget("vm-list").get_selection().connect("changed", self.vm_selected)
        self.connection.connect("disconnected", self.close)

        # store any error message from the restore-domain callback
        self.domain_restore_error = ""

    def show(self):
        win = self.window.get_widget("vmm-manager")
        win.show_all()
        win.present()

    def close(self, src=None, src2=None):
        self.connection.disconnect()
        win = self.window.get_widget("vmm-manager")
        win.hide()
        return 1

    def exit_app(self, src=None, src2=None):
        gtk.main_quit()

    def open_connection(self, src=None):
        self.emit("action-show-connect")

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
            progWin = vmmAsyncJob(self.config,
                                  self.restore_saved_callback,
                                  [file_to_load],
                                  _("Restoring Virtual Machine"))
            progWin.run()
            
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
            

    def restore_saved_callback(self, file_to_load):
        status = self.connection.restore(file_to_load)
        if(status != 0):
            self.domain_restore_error = _("Error restoring domain '%s'. Is the domain already running?") % file_to_load
        

    def vm_added(self, connection, uri, vmuuid):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        dup = 0
        for row in range(model.iter_n_children(None)):
            vm = model.get_value(model.iter_nth_child(None, row), 0)
            if vm == vmuuid:
                dup = 1

        vm = self.connection.get_vm(vmuuid)

        if dup != 1:
            model.append([vmuuid, vm.get_name()])
            vm.connect("status-changed", self.vm_status_changed)
            vm.connect("resources-sampled", self.vm_resources_sampled)


    def vm_removed(self, connection, uri, vmuuid):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        dup = 0
        for row in range(model.iter_n_children(None)):
            vm = model.get_value(model.iter_nth_child(None, row), 0)
            if vm == vmuuid:
                model.remove(model.iter_nth_child(None, row))
                break

    def vm_status_changed(self, domain, status):
        self.vm_updated(domain.get_uuid())

    def vm_resources_sampled(self, domain):
        self.vm_updated(domain.get_uuid())

    def vm_updated(self, vmuuid):
        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        for row in range(model.iter_n_children(None)):
            iter = model.iter_nth_child(None, row)
            if model.get_value(iter, 0) == vmuuid:
                model.row_changed(str(row), iter)

    def current_vm(self):
        vmlist = self.window.get_widget("vm-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            return active[0].get_value(active[1], 0)
        return None

    def show_vm_details(self,ignore):
        self.emit("action-show-details", self.connection.get_uri(), self.current_vm())

    def show_vm_create(self,ignore):
        self.emit("action-show-create")

    def open_vm_console(self,ignore,ignore2=None,ignore3=None):
        self.emit("action-show-console", self.connection.get_uri(), self.current_vm())


    def vm_selected(self, selection):
        if selection == None or selection.count_selected_rows() == 0:
            self.window.get_widget("vm-delete").set_sensitive(False)
            self.window.get_widget("vm-details").set_sensitive(False)
            self.window.get_widget("vm-open").set_sensitive(False)
            self.window.get_widget("menu_edit_delete").set_sensitive(False)
            self.window.get_widget("menu_edit_details").set_sensitive(False)
        else:
            #self.window.get_widget("vm-delete").set_sensitive(True)
            self.window.get_widget("vm-delete").set_sensitive(False)
            self.window.get_widget("vm-details").set_sensitive(True)
            self.window.get_widget("vm-open").set_sensitive(True)
            #self.window.get_widget("menu_edit_delete").set_sensitive(True)
            self.window.get_widget("menu_edit_delete").set_sensitive(False)
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

        model = gtk.ListStore(str, str)
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

        id_txt = gtk.CellRendererText()
        idCol.pack_start(id_txt, True)
        idCol.set_cell_data_func(id_txt, self.domain_id_text, None)
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
        statusCol.set_cell_data_func(status_txt, self.status_text, None)
        statusCol.set_cell_data_func(status_icon, self.status_icon, None)
        statusCol.set_visible(self.config.is_vmlist_status_visible())

        cpuUsage_txt = gtk.CellRendererText()
        #cpuUsage_img = gtk.CellRendererProgress()
        cpuUsage_img = sparkline.CellRendererSparkline()
        cpuUsageCol.pack_start(cpuUsage_txt, False)
        cpuUsageCol.pack_start(cpuUsage_img, False)
        cpuUsageCol.set_cell_data_func(cpuUsage_txt, self.cpu_usage_text, None)
        cpuUsageCol.set_cell_data_func(cpuUsage_img, self.cpu_usage_img, None)
        cpuUsageCol.set_visible(self.config.is_vmlist_cpu_usage_visible())
        cpuUsageCol.set_sort_column_id(VMLIST_SORT_CPU_USAGE)

        virtualCPUs_txt = gtk.CellRendererText()
        virtualCPUsCol.pack_start(virtualCPUs_txt, False)
        virtualCPUsCol.set_cell_data_func(virtualCPUs_txt, self.virtual_cpus_text, None)
        virtualCPUsCol.set_visible(self.config.is_vmlist_virtual_cpus_visible())

        memoryUsage_txt = gtk.CellRendererText()
        memoryUsage_img = gtk.CellRendererProgress()
        memoryUsageCol.pack_start(memoryUsage_txt, False)
        memoryUsageCol.pack_start(memoryUsage_img, False)
        memoryUsageCol.set_cell_data_func(memoryUsage_txt, self.memory_usage_text, None)
        memoryUsageCol.set_cell_data_func(memoryUsage_img, self.memory_usage_img, None)
        memoryUsageCol.set_visible(self.config.is_vmlist_memory_usage_visible())
        memoryUsageCol.set_sort_column_id(VMLIST_SORT_MEMORY_USAGE)

        diskUsage_txt = gtk.CellRendererText()
        diskUsage_img = gtk.CellRendererProgress()
        diskUsageCol.pack_start(diskUsage_txt, False)
        diskUsageCol.pack_start(diskUsage_img, False)
        diskUsageCol.set_cell_data_func(diskUsage_txt, self.disk_usage_text, None)
        diskUsageCol.set_cell_data_func(diskUsage_img, self.disk_usage_img, None)
        diskUsageCol.set_visible(self.config.is_vmlist_disk_usage_visible())
        diskUsageCol.set_sort_column_id(VMLIST_SORT_DISK_USAGE)

        networkTraffic_txt = gtk.CellRendererText()
        networkTraffic_img = gtk.CellRendererProgress()
        networkTrafficCol.pack_start(networkTraffic_txt, False)
        networkTrafficCol.pack_start(networkTraffic_img, False)
        networkTrafficCol.set_cell_data_func(networkTraffic_txt, self.network_traffic_text, None)
        networkTrafficCol.set_cell_data_func(networkTraffic_img, self.network_traffic_img, None)
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
        return cmp(self.connection.get_vm(model.get_value(iter1, 0)).get_id(), self.connection.get_vm(model.get_value(iter2, 0)).get_id())

    def vmlist_name_sorter(self, model, iter1, iter2):
        return cmp(model.get_value(iter1, 1), model.get_value(iter2, 1))

    def vmlist_cpu_usage_sorter(self, model, iter1, iter2):
        return cmp(self.connection.get_vm(model.get_value(iter1, 0)).cpu_time(), self.connection.get_vm(model.get_value(iter2, 0)).cpu_time())

    def vmlist_memory_usage_sorter(self, model, iter1, iter2):
        return cmp(self.connection.get_vm(model.get_value(iter1, 0)).current_memory(), self.connection.get_vm(model.get_value(iter2, 0)).current_memory())

    def vmlist_disk_usage_sorter(self, model, iter1, iter2):
        return cmp(self.connection.get_vm(model.get_value(iter1, 0)).disk_usage(), self.connection.get_vm(model.get_value(iter2, 0)).disk_usage())

    def vmlist_network_usage_sorter(self, model, iter1, iter2):
        return cmp(self.connection.get_vm(model.get_value(iter1, 0)).network_traffic(), self.connection.get_vm(model.get_value(iter2, 0)).network_traffic())

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


    def domain_id_text(self, column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        cell.set_property('text', str(self.connection.get_vm(uuid).get_id()))

    def status_text(self, column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        cell.set_property('text', self.connection.get_vm(uuid).run_status())

    def status_icon(self, column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        cell.set_property('pixbuf', self.connection.get_vm(uuid).run_status_icon())

    def cpu_usage_text(self,  column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        cell.set_property('text', "%2.2f %%" % self.connection.get_vm(uuid).cpu_time_percentage())

    def cpu_usage_img(self,  column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        #cell.set_property('text', '')
        #cell.set_property('value', self.connection.get_vm(uuid).cpu_time_percentage())
        data = self.connection.get_vm(uuid).cpu_time_vector()
        data.reverse()
        cell.set_property('data_array', data)

    def virtual_cpus_text(self,  column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        cell.set_property('text', str(self.connection.get_vm(uuid).vcpu_count()))


    def memory_usage_text(self,  column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        current = self.connection.get_vm(uuid).current_memory()
        currentPercent = self.connection.get_vm(uuid).current_memory_percentage()
        cell.set_property('text', "%s (%2.2f%%)" % (self.pretty_mem(current) , currentPercent))

    def memory_usage_img(self,  column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        currentPercent = self.connection.get_vm(uuid).current_memory_percentage()
        cell.set_property('text', '')
        cell.set_property('value', currentPercent)

    def disk_usage_text(self,  column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        current = self.connection.get_vm(uuid).disk_usage()
        currentPercent = self.connection.get_vm(uuid).disk_usage_percentage()
        cell.set_property('text', "%s (%2.2f%%)" % (self.pretty_mem(current) , currentPercent))

    def disk_usage_img(self,  column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        currentPercent = self.connection.get_vm(uuid).disk_usage_percentage()
        cell.set_property('text', '')
        cell.set_property('value', currentPercent)

    def network_traffic_text(self,  column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        current = self.connection.get_vm(uuid).network_traffic()
        currentPercent = self.connection.get_vm(uuid).network_traffic_percentage()
        cell.set_property('text', "%s (%2.2f%%)" % (self.pretty_mem(current) , currentPercent))

    def network_traffic_img(self,  column, cell, model, iter, data):
        uuid = model.get_value(iter, 0)
        currentPercent = self.connection.get_vm(uuid).network_traffic_percentage()
        cell.set_property('text', '')
        cell.set_property('value', currentPercent)

    # XXX or should we just always display MB ?
    def pretty_mem(self, mem):
        if mem > (1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.2f MB" % (mem/1024.0)

gobject.type_register(vmmManager)

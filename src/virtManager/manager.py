
import gobject
import gtk
import gtk.glade

import sparkline

VMLIST_SORT_NAME = 1
VMLIST_SORT_CPU_USAGE = 2
VMLIST_SORT_MEMORY_USAGE = 3
VMLIST_SORT_DISK_USAGE = 4
VMLIST_SORT_NETWORK_USAGE = 5

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
        }
    def __init__(self, config, connection):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-manager")
        self.config = config
        self.connection = connection
        self.prepare_vmlist()

        self.connection.connect("vm-added", self.vm_added)
        self.connection.connect("vm-removed", self.vm_removed)

        self.config.on_vmlist_status_visible_changed(self.toggle_status_visible_widget)
        self.config.on_vmlist_cpu_usage_visible_changed(self.toggle_cpu_usage_visible_widget)
        self.config.on_vmlist_memory_usage_visible_changed(self.toggle_memory_usage_visible_widget)
        self.config.on_vmlist_disk_usage_visible_changed(self.toggle_disk_usage_visible_widget)
        self.config.on_vmlist_network_traffic_visible_changed(self.toggle_network_traffic_visible_widget)

        self.window.get_widget("menu_view_status").set_active(self.config.is_vmlist_status_visible())
        self.window.get_widget("menu_view_cpu_usage").set_active(self.config.is_vmlist_cpu_usage_visible())
        self.window.get_widget("menu_view_memory_usage").set_active(self.config.is_vmlist_memory_usage_visible())
        self.window.get_widget("menu_view_disk_usage").set_active(self.config.is_vmlist_disk_usage_visible())
        self.window.get_widget("menu_view_network_traffic").set_active(self.config.is_vmlist_network_traffic_visible())

        self.window.get_widget("menu_file_new").set_sensitive(False)
        self.window.get_widget("vm-new").set_sensitive(False)
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
            "on_menu_view_status_activate" : self.toggle_status_visible_conf,
            "on_menu_view_cpu_usage_activate" : self.toggle_cpu_usage_visible_conf,
            "on_menu_view_memory_usage_activate" : self.toggle_memory_usage_visible_conf,
            "on_menu_view_disk_usage_activate" : self.toggle_disk_usage_visible_conf,
            "on_menu_view_network_traffic_activate" : self.toggle_network_traffic_visible_conf,

            "on_vm_manager_delete_event": self.close,
            "on_menu_file_open_connection_activate": self.open_connection,
            "on_menu_file_quit_activate": self.exit_app,
            "on_menu_file_close_activate": self.close,
            "on_vmm_close_clicked": self.close,
            "on_vm_details_clicked": self.show_vm_details,
            "on_vm_open_clicked": self.open_vm_console,
            "on_menu_edit_details_activate": self.show_vm_details,

            "on_vm_list_row_activated": self.open_vm_console,

            "on_vm_list_button_press_event": self.popup_vm_menu,

            "on_menu_edit_preferences_activate": self.show_preferences,
            "on_menu_help_about_activate": self.show_about,
            })

        self.vm_selected(None)
        self.window.get_widget("vm-list").get_selection().connect("changed", self.vm_selected)
        self.connection.connect("disconnected", self.close)

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
        self.emit("action-show-connect");

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

        nameCol = gtk.TreeViewColumn("Name")
        statusCol = gtk.TreeViewColumn("Status")
        cpuUsageCol = gtk.TreeViewColumn("CPU usage")
        memoryUsageCol = gtk.TreeViewColumn("Memory usage")
        diskUsageCol = gtk.TreeViewColumn("Disk usage")
        networkTrafficCol = gtk.TreeViewColumn("Network traffic")

        name_txt = gtk.CellRendererText()
        nameCol.pack_start(name_txt, True)
        nameCol.add_attribute(name_txt, 'text', 1)
        nameCol.set_sort_column_id(VMLIST_SORT_NAME)

        vmlist.append_column(nameCol)
        vmlist.append_column(statusCol)
        vmlist.append_column(cpuUsageCol)
        vmlist.append_column(memoryUsageCol)
        vmlist.append_column(diskUsageCol)
        vmlist.append_column(networkTrafficCol)

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

        model.set_sort_func(VMLIST_SORT_NAME, self.vmlist_name_sorter)
        model.set_sort_func(VMLIST_SORT_CPU_USAGE, self.vmlist_cpu_usage_sorter)
        model.set_sort_func(VMLIST_SORT_MEMORY_USAGE, self.vmlist_memory_usage_sorter)
        model.set_sort_func(VMLIST_SORT_DISK_USAGE, self.vmlist_disk_usage_sorter)
        model.set_sort_func(VMLIST_SORT_NETWORK_USAGE, self.vmlist_network_usage_sorter)

        model.set_sort_column_id(VMLIST_SORT_NAME, gtk.SORT_ASCENDING)


    # XXX does python have a built-in sort op like perl's <=> / cmp ?
    def sort_op(self, a, b):
        if a > b:
            return 1
        elif a < b:
            return -1
        return 0

    def vmlist_name_sorter(self, model, iter1, iter2):
        return self.sort_op(model.get_value(iter1, 0), model.get_value(iter2, 0))

    def vmlist_cpu_usage_sorter(self, model, iter1, iter2):
        return self.sort_op(self.connection.get_vm(model.get_value(iter1, 0)).cpu_time(), self.connection.get_vm(model.get_value(iter2, 0)).cpu_time())

    def vmlist_memory_usage_sorter(self, model, iter1, iter2):
        return self.sort_op(self.connection.get_vm(model.get_value(iter1, 0)).current_memory(), self.connection.get_vm(model.get_value(iter2, 0)).current_memory())

    def vmlist_disk_usage_sorter(self, model, iter1, iter2):
        return self.sort_op(self.connection.get_vm(model.get_value(iter1, 0)).disk_usage(), self.connection.get_vm(model.get_value(iter2, 0)).disk_usage())

    def vmlist_network_usage_sorter(self, model, iter1, iter2):
        return self.sort_op(self.connection.get_vm(model.get_value(iter1, 0)).network_traffic(), self.connection.get_vm(model.get_value(iter2, 0)).network_traffic())

    def toggle_status_visible_conf(self, menu):
        self.config.set_vmlist_status_visible(menu.get_active())

    def toggle_status_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_status")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(1)
        col.set_visible(self.config.is_vmlist_status_visible())

    def toggle_cpu_usage_visible_conf(self, menu):
        self.config.set_vmlist_cpu_usage_visible(menu.get_active())

    def toggle_cpu_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_cpu_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(2)
        col.set_visible(self.config.is_vmlist_cpu_usage_visible())

    def toggle_memory_usage_visible_conf(self, menu):
        self.config.set_vmlist_memory_usage_visible(menu.get_active())

    def toggle_memory_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_memory_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(3)
        col.set_visible(self.config.is_vmlist_memory_usage_visible())

    def toggle_disk_usage_visible_conf(self, menu):
        self.config.set_vmlist_disk_usage_visible(menu.get_active())

    def toggle_disk_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_disk_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(4)
        col.set_visible(self.config.is_vmlist_disk_usage_visible())

    def toggle_network_traffic_visible_conf(self, menu):
        self.config.set_vmlist_network_traffic_visible(menu.get_active())

    def toggle_network_traffic_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_network_traffic")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(5)
        col.set_visible(self.config.is_vmlist_network_traffic_visible())


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

#!/usr/bin/python

import gtk
import gobject
import gtk.gdk
import gtk.glade
import re
import os
import os.path
import libvirt

tickrate = 5000

# Ought not to hardcode stuff as being in /usr
gladedir = "/usr/share/gnome-vm-manager"

# Hack for dev purposes
if os.path.exists("./gnome-vm-manager.glade"):
    gladedir = "."

class vmmAbout:
    def __init__(self):
        self.window = gtk.glade.XML(gladedir + "/gnome-vm-manager.glade", "vm-about")
        self.window.get_widget("vm-about").hide()

    def show(self):
        dialog = self.window.get_widget("vm-about")
        dialog.set_version("0.1")
        dialog.show_all()


class vmmManager:
    def __init__(self):
        self.window = gtk.glade.XML(gladedir + "/gnome-vm-manager.glade", "vm-manager")
        self.vmm = libvirt.openReadOnly(None)
        #self.vmm = libvirt.open(None)

        self.stats = {}

        self.record_stats()
        self.populate_vms()
        self.tickrate = 5000
        self.about = None;
        
        self.timer = gobject.timeout_add(self.tickrate, self.refresh_stats)

        self.window.signal_autoconnect({
            "on_menu_view_status_activate" : self.toggle_status_column,
            "on_menu_view_cpu_usage_activate" : self.toggle_cpu_column,
            "on_menu_view_memory_usage_activate" : self.toggle_memory_column,
            "on_menu_view_disk_usage_activate" : self.toggle_disk_column,
            "on_menu_view_network_traffic_activate" : self.toggle_network_column,

            "on_vm_manager_delete_event": self.exit_app,
            "on_menu_file_quit_activate": self.exit_app,
            "on_vmm_close_clicked": self.exit_app,

            "on_menu_help_about_activate": self.show_about,
            })
        
    def exit_app(self, ignore=None,ignore2=None):
        gtk.main_quit()


    def show_about(self, ignore=None):
        if self.about == None:
            self.about = vmmAbout()
        self.about.show()
            
    def refresh_stats(self):
        self.record_stats()
        self.timer = gobject.timeout_add(self.tickrate, self.refresh_stats)

        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()
        print "Refresh " + str(model.iter_n_children(None))
        for row in range(model.iter_n_children(None)):
            model.row_changed(str(row), model.iter_nth_child(None, row))
    
    def record_stats(self):
        print "Record"
        doms = self.vmm.listDomainsID()
        if doms != None:
            for id in self.vmm.listDomainsID():
                vm = self.vmm.lookupByID(id)
                info = vm.info()
                name = vm.name()

                if not(self.stats.has_key(name)):
                    self.stats[name] = []
                if len(self.stats[name]) > 4:
                    self.stats[name] = (self.stats[name])[1:len(self.stats[name])]
                self.stats[name].append(info)
                # XXX why is max-mem wrong for Domain-0 when run as root ?!?!?!
                #print info

    def populate_vms(self):
        vmlist = self.window.get_widget("vm-list")

        model = gtk.ListStore(str)
        vmlist.set_model(model)

        nameCol = gtk.TreeViewColumn("Name")
        statusCol = gtk.TreeViewColumn("Status")
        cpuUsageCol = gtk.TreeViewColumn("CPU usage")
        memoryUsageCol = gtk.TreeViewColumn("Memory usage")
        diskUsageCol = gtk.TreeViewColumn("Disk usage")
        networkUsageCol = gtk.TreeViewColumn("Network traffic")

        name_txt = gtk.CellRendererText()
        nameCol.pack_start(name_txt, True)
        nameCol.add_attribute(name_txt, 'text', 0)

        vmlist.append_column(nameCol)
        vmlist.append_column(statusCol)
        vmlist.append_column(cpuUsageCol)
        vmlist.append_column(memoryUsageCol)
        vmlist.append_column(diskUsageCol)
        vmlist.append_column(networkUsageCol)

        status_txt = gtk.CellRendererText()
        statusCol.pack_start(status_txt, True)
        statusCol.set_cell_data_func(status_txt, self.status_text, None)
        
        cpuUsage_txt = gtk.CellRendererText()
        cpuUsageCol.pack_start(cpuUsage_txt, True)
        cpuUsageCol.set_cell_data_func(cpuUsage_txt, self.cpu_usage_text, None)
        
        memoryUsage_txt = gtk.CellRendererText()
        memoryUsageCol.pack_start(memoryUsage_txt, True)
        memoryUsageCol.set_cell_data_func(memoryUsage_txt, self.memory_usage_text, None)
        
        diskUsage_txt = gtk.CellRendererText()
        diskUsageCol.pack_start(diskUsage_txt, True)
        diskUsageCol.set_cell_data_func(diskUsage_txt, self.disk_usage_text, None)
        
        networkUsage_txt = gtk.CellRendererText()
        networkUsageCol.pack_start(networkUsage_txt, True)
        networkUsageCol.set_cell_data_func(networkUsage_txt, self.network_usage_text, None)
        
        doms = self.vmm.listDomainsID()
        if doms != None:
            for id in self.vmm.listDomainsID():
                vm = self.vmm.lookupByID(id)
                model.append([vm.name()])

    def toggle_status_column(self,menu):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(1)
        col.set_visible(menu.get_active())

    def toggle_cpu_column(self,menu):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(2)
        col.set_visible(menu.get_active())

    def toggle_memory_column(self,menu):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(3)
        col.set_visible(menu.get_active())

    def toggle_disk_column(self,menu):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(4)
        col.set_visible(menu.get_active())

    def toggle_network_column(self,menu):
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(5)
        col.set_visible(menu.get_active())


    def status_text(self, column, cell, model, iter, data):
        name = model.get_value(iter, 0)
        statusRecord = self.stats[name]
        info = statusRecord[len(statusRecord)-1]
        if info[0] == libvirt.VIR_DOMAIN_NOSTATE:
            cell.set_property('text', "Unknown")
        elif info[0] == libvirt.VIR_DOMAIN_RUNNING:
            cell.set_property('text', "Running")
        elif info[0] == libvirt.VIR_DOMAIN_BLOCKED:
            cell.set_property('text', "Blocked")
        elif info[0] == libvirt.VIR_DOMAIN_PAUSED:
            cell.set_property('text', "Paused")
        elif info[0] == libvirt.VIR_DOMAIN_SHUTDOWN:
            cell.set_property('text', "Shutdown")
        elif info[0] == libvirt.VIR_DOMAIN_SHUTOFF:
            cell.set_property('text', "Shutoff")
        elif info[0] == libvirt.VIR_DOMAIN_CRASHED:
            cell.set_property('text', "Crashed")

    def cpu_usage_text(self,  column, cell, model, iter, data):
        name = model.get_value(iter, 0)
        statusRecord = self.stats[name]
        nSample = len(statusRecord)

        if nSample < 2:
            cell.set_property('text', "-")
        else:
            total = 0
            for dom in self.stats.keys():
                last = self.stats[dom][len(self.stats[dom])-2]
                current = self.stats[dom][len(self.stats[dom])-1]
                total += current[4] - last[4]
                
            last = statusRecord[len(statusRecord)-2]
            current = statusRecord[len(statusRecord)-1]
            fraction = current[4] - last[4]

            percentage = fraction * 100.0 / total
            
            cell.set_property('text',"%2.2f %%" % percentage)

    def memory_usage_text(self,  column, cell, model, iter, data):
        name = model.get_value(iter, 0)
        statusRecord = self.stats[name]
        current = statusRecord[len(statusRecord)-1]

        cell.set_property('text', "%s of %s" % (self.pretty_mem(current[2]), self.pretty_mem(current[1])))
        #cell.set_property('text', self.pretty_mem(current[2]))

    def pretty_mem(self, mem):
        if mem > (1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.2f MB" % (mem/1024.0)

    def disk_usage_text(self,  column, cell, model, iter, data):
        #cell.set_property('text', "600 MB of 1 GB")
        cell.set_property('text', "-")

    def network_usage_text(self,  column, cell, model, iter, data):
        #cell.set_property('text', "100 bytes/sec")
        cell.set_property('text', "-")
        
# Run me!
def main():
    window = vmmManager()
    gtk.main()

if __name__ == "__main__":
    main()

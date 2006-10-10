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
import libvirt
import sparkline
import logging

class vmmDetails(gobject.GObject):
    __gsignals__ = {
        "action-show-console": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-terminal": (gobject.SIGNAL_RUN_FIRST,
                                   gobject.TYPE_NONE, (str,str)),
        "action-save-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str,str))
        }
    def __init__(self, config, vm):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-details")
        self.config = config
        self.vm = vm

        topwin = self.window.get_widget("vmm-details")
        topwin.hide()
        topwin.set_title(self.vm.get_name() + " " + topwin.get_title())

        self.window.get_widget("overview-name").set_text(self.vm.get_name())
        self.window.get_widget("overview-uuid").set_text(self.vm.get_uuid())

        self.window.get_widget("control-shutdown").set_icon_widget(gtk.Image())
        self.window.get_widget("control-shutdown").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_shutdown.png")

        self.window.get_widget("hw-panel").set_show_tabs(False)

        hwListModel = gtk.ListStore(int, str, gtk.gdk.Pixbuf)
        self.window.get_widget("hw-list").set_model(hwListModel)

        hwListModel.append([0, "Processor", gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")])
        #hwListModel.append([1, "Memory", gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_ram.png")])
        hwListModel.append([1, "Memory", gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")])
        hwListModel.append([2, "Disk", gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_hdd.png")])
        hwListModel.append([3, "Network", gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_ethernet.png")])
        #hwListModel.append([4, "Add hardware", gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_addnew.png")])

        self.window.get_widget("hw-list").get_selection().connect("changed", self.hw_selected)


        hwCol = gtk.TreeViewColumn("Hardware")
        hw_txt = gtk.CellRendererText()
        hw_img = gtk.CellRendererPixbuf()
        hwCol.pack_start(hw_txt, True)
        hwCol.pack_start(hw_img, False)
        hwCol.add_attribute(hw_txt, 'text', 1)
        hwCol.add_attribute(hw_img, 'pixbuf', 2)

        self.window.get_widget("hw-list").append_column(hwCol)

        self.cpu_usage_graph = sparkline.Sparkline()
        self.window.get_widget("graph-table").attach(self.cpu_usage_graph, 1, 2, 0, 1)

        self.memory_usage_graph = sparkline.Sparkline()
        self.window.get_widget("graph-table").attach(self.memory_usage_graph, 1, 2, 1, 2)


        self.network_traffic_graph = sparkline.Sparkline()
        self.window.get_widget("graph-table").attach(self.network_traffic_graph, 1, 2, 3, 4)

        self.window.signal_autoconnect({
            "on_close_details_clicked": self.close,
            "on_details_menu_close_activate": self.close,
            "on_vmm_details_delete_event": self.close,

            "on_control_run_clicked": self.control_vm_run,
            "on_control_shutdown_clicked": self.control_vm_shutdown,
            "on_control_pause_toggled": self.control_vm_pause,

            "on_details_menu_run_activate": self.control_vm_run,
            "on_details_menu_pause_activate": self.control_vm_pause,
            "on_details_menu_shutdown_activate": self.control_vm_shutdown,
            "on_details_menu_save_activate": self.control_vm_save_domain,

            "on_details_menu_graphics_activate": self.control_vm_console,
            "on_details_menu_serial_activate": self.control_vm_terminal,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,

            "on_config_cpus_apply_clicked": self.config_cpus_apply,
            "on_config_vcpus_changed": self.config_vm_cpus,
            "on_config_memory_changed": self.config_memory_value,
            "on_config_memory_apply_clicked": self.config_memory_apply
            })

        self.hw_selected()
        self.vm.connect("status-changed", self.update_widget_states)
        self.vm.connect("resources-sampled", self.refresh_resources)

        self.update_widget_states(vm, vm.status())
        self.refresh_resources(vm)

        self.prepare_disk_list()
        self.populate_disk_list()
        
        self.prepare_network_list()
        self.populate_network_list()

    def toggle_toolbar(self, src):
        if src.get_active():
            self.window.get_widget("details-toolbar").show()
        else:
            self.window.get_widget("details-toolbar").hide()

    def show(self):
        dialog = self.window.get_widget("vmm-details")
        dialog.show_all()
        self.window.get_widget("overview-network-traffic-text").hide()
        self.window.get_widget("overview-network-traffic-label").hide()
        self.window.get_widget("overview-disk-usage-bar").hide()
        self.window.get_widget("overview-disk-usage-text").hide()
        self.window.get_widget("overview-disk-usage-label").hide()
        self.network_traffic_graph.hide()
        dialog.present()

    def activate_performance_page(self):
        self.window.get_widget("details-pages").set_current_page(0)

    def activate_config_page(self):
        self.window.get_widget("details-pages").set_current_page(1)

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-details").hide()
        return 1

    def hw_selected(self, src=None):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            pagenum = active[0].get_value(active[1], 0)
            self.window.get_widget("hw-panel").set_sensitive(True)
            self.window.get_widget("hw-panel").set_current_page(pagenum)
            if self.vm.is_read_only():
                self.window.get_widget("hw-panel").get_nth_page(pagenum).set_sensitive(False)
            else:
                self.window.get_widget("hw-panel").get_nth_page(pagenum).set_sensitive(True)
        else:
            self.window.get_widget("hw-panel").set_sensitive(False)
        # When the user changes tabs on the hw panel, reset to the default state
        self.update_config_memory()
        self.update_config_cpus()
        self.update_state_cpus()
        self.window.get_widget("config-memory-apply").set_sensitive(False)
        self.window.get_widget("config-cpus-apply").set_sensitive(False)

    def control_vm_run(self, src):
        status = self.vm.status()
        if status != libvirt.VIR_DOMAIN_SHUTOFF:
            pass
        else:
            self.vm.startup()

    def control_vm_shutdown(self, src):
        status = self.vm.status()
        if not(status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]):
            self.vm.shutdown()
        else:
            logging.warning("Shutdown requested, but machine is already shutting down / shutoff")

    def control_vm_pause(self, src):
        if self.ignorePause:
            return

        status = self.vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
            logging.warning("Pause/resume requested, but machine is shutdown / shutoff")
        else:
            if status in [ libvirt.VIR_DOMAIN_PAUSED ]:
                if not src.get_active():
                    self.vm.resume()
                else:
                    logging.warning("Pause requested, but machine is already paused")
            else:
                if src.get_active():
                    self.vm.suspend()
                else:
                    logging.warning("Resume requested, but machine is already running")

        self.window.get_widget("control-pause").set_active(src.get_active())
        self.window.get_widget("details-menu-pause").set_active(src.get_active())

    def control_vm_terminal(self, src):
        self.emit("action-show-terminal", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_console(self, src):
        self.emit("action-show-console", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_save_domain(self, src):
        self.emit("action-save-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def update_widget_states(self, vm, status):
        self.ignorePause = True
        try:
            if status in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
                self.window.get_widget("control-run").set_sensitive(True)
                self.window.get_widget("details-menu-run").set_sensitive(True)
            else:
                self.window.get_widget("control-run").set_sensitive(False)
                self.window.get_widget("details-menu-run").set_sensitive(False)


            if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ] or vm.is_read_only():
                self.window.get_widget("control-pause").set_sensitive(False)
                self.window.get_widget("control-shutdown").set_sensitive(False)
                self.window.get_widget("details-menu-pause").set_sensitive(False)
                self.window.get_widget("details-menu-shutdown").set_sensitive(False)
                self.window.get_widget("details-menu-save").set_sensitive(False)
            else:
                self.window.get_widget("control-pause").set_sensitive(True)
                self.window.get_widget("control-shutdown").set_sensitive(True)
                self.window.get_widget("details-menu-pause").set_sensitive(True)
                self.window.get_widget("details-menu-shutdown").set_sensitive(True)
                self.window.get_widget("details-menu-save").set_sensitive(True)

                if status == libvirt.VIR_DOMAIN_PAUSED:
                    self.window.get_widget("control-pause").set_active(True)
                    self.window.get_widget("details-menu-pause").set_active(True)
                else:
                    self.window.get_widget("control-pause").set_active(False)
                    self.window.get_widget("details-menu-pause").set_active(False)
        except:
            self.ignorePause = False
        self.ignorePause = False

        self.window.get_widget("overview-status-text").set_text(self.vm.run_status())
        self.window.get_widget("overview-status-icon").set_from_pixbuf(self.vm.run_status_icon())

        if vm.is_serial_console_tty_accessible():
            self.window.get_widget("details-menu-serial").set_sensitive(True)
        else:
            self.window.get_widget("details-menu-serial").set_sensitive(False)

    def refresh_resources(self, vm):
        self.window.get_widget("overview-cpu-usage-text").set_text("%d %%" % self.vm.cpu_time_percentage())
        vm_maxmem = self.vm.maximum_memory()
        vm_memory = self.vm.current_memory()
        host_memory = self.vm.get_connection().host_memory_size()
        self.window.get_widget("overview-memory-usage-text").set_text("%d MB of %d MB" % (vm_memory/1024, host_memory/1024))

        history_len = self.config.get_stats_history_length()
        cpu_vector = self.vm.cpu_time_vector()
        cpu_vector.reverse()
        self.cpu_usage_graph.set_property("data_array", cpu_vector)

        memory_vector = self.vm.current_memory_vector()
        memory_vector.reverse()
        self.memory_usage_graph.set_property("data_array", memory_vector)

        network_vector = self.vm.network_traffic_vector()
        network_vector.reverse()
        self.network_traffic_graph.set_property("data_array", network_vector)

        # update HW config values
        self.window.get_widget("state-host-memory").set_text("%d MB" % (host_memory/1024))
        self.window.get_widget("config-memory").get_adjustment().upper = vm.maximum_memory()/1024
        self.window.get_widget("state-vm-maxmem").set_text("%d MB" % (vm_maxmem/1024))
        self.window.get_widget("state-vm-memory").set_text("%d MB" % (vm_memory/1024))

        self.window.get_widget("state-host-cpus").set_text("%d" % self.vm.get_connection().host_active_processor_count())
        self.window.get_widget("config-vcpus").get_adjustment().upper = vm.vcpu_max_count()
        self.window.get_widget("state-vm-vcpus").set_text("%d" % (vm.vcpu_count()))
        self.window.get_widget("state-vm-max-vcpus").set_text("%d" % (vm.vcpu_max_count()))

    def update_config_memory(self):
        self.window.get_widget("config-memory").get_adjustment().value = self.vm.current_memory()/1024

    def update_config_cpus(self):
        self.window.get_widget("config-vcpus").get_adjustment().value = self.vm.vcpu_count()

    def update_state_cpus(self):
        self.window.get_widget("state-host-cpus").set_text(`(self.vm.get_connection().host_maximum_processor_count())`)
    def config_cpus_apply(self, src):
        # Apply the change to the number of CPUs

        vcpus = self.window.get_widget("config-vcpus").get_adjustment().value

        # if requested # of CPUS > host CPUS, pop up warning dialog (not implemented yet)

        self.vm.set_vcpu_count(vcpus)
        self.window.get_widget("config-cpus-apply").set_sensitive(False)

    def config_vm_cpus(self, src):
        # cpu spinbox changed, make the apply button available
        self.window.get_widget("config-cpus-apply").set_sensitive(True)

    def config_memory_value(self, src):
        self.window.get_widget("config-memory-apply").set_sensitive(True)

    def config_memory_apply(self, src):
        memory = self.window.get_widget("config-memory").get_adjustment().value
        newmem = self.vm.set_memory(memory*1024)
        self.window.get_widget("config-memory-apply").set_sensitive(False)
        self.window.get_widget("state-vm-memory").set_text("%d MB" % (newmem/1024))

    def prepare_disk_list(self):
        disks = self.window.get_widget("storage-view")
        disksModel = gtk.TreeStore(str,str,str,str)
        disks.set_model(disksModel)

        diskType_col = gtk.TreeViewColumn("Type")
        diskType_text = gtk.CellRendererText()
        diskType_col.pack_start(diskType_text, True)
        diskType_col.add_attribute(diskType_text, 'text', 0)

        diskSrc_col = gtk.TreeViewColumn("Source")
        diskSrc_text = gtk.CellRendererText()
        diskSrc_col.pack_start(diskSrc_text, True)
        diskSrc_col.add_attribute(diskSrc_text, 'text', 1)

        diskDevice_col = gtk.TreeViewColumn("Device")
        diskDevice_text = gtk.CellRendererText()
        diskDevice_col.pack_start(diskDevice_text, True)
        diskDevice_col.add_attribute(diskDevice_text, 'text', 2)

        diskDst_col = gtk.TreeViewColumn(_("Destination"))
        diskDst_text = gtk.CellRendererText()
        diskDst_col.pack_start(diskDst_text, True)
        diskDst_col.add_attribute(diskDst_text, 'text', 3)

        disks.append_column(diskType_col)
        disks.append_column(diskSrc_col)
        disks.append_column(diskDevice_col)
        disks.append_column(diskDst_col)

    def populate_disk_list(self):
        diskList = self.vm.get_disk_devices()

        disks = self.window.get_widget("storage-view")
        disksModel = disks.get_model()
        for d in diskList:
            disksModel.append(None, d)
            
    def prepare_network_list(self):
        nets = self.window.get_widget("network-view")
        netsModel = gtk.TreeStore(str,str,str,str)
        nets.set_model(netsModel)

        netType_col = gtk.TreeViewColumn("Type")
        netType_text = gtk.CellRendererText()
        netType_col.pack_start(netType_text, True)
        netType_col.add_attribute(netType_text, 'text', 0)

        netSrc_col = gtk.TreeViewColumn("Source")
        netSrc_text = gtk.CellRendererText()
        netSrc_col.pack_start(netSrc_text, True)
        netSrc_col.add_attribute(netSrc_text, 'text', 1)

        netDevice_col = gtk.TreeViewColumn("Device")
        netDevice_text = gtk.CellRendererText()
        netDevice_col.pack_start(netDevice_text, True)
        netDevice_col.add_attribute(netDevice_text, 'text', 2)

        netDst_col = gtk.TreeViewColumn(_("MAC address"))
        netDst_text = gtk.CellRendererText()
        netDst_col.pack_start(netDst_text, True)
        netDst_col.add_attribute(netDst_text, 'text', 3)

        nets.append_column(netType_col)
        nets.append_column(netSrc_col)
        nets.append_column(netDevice_col)
        nets.append_column(netDst_col)

    def populate_network_list(self):
        netList = self.vm.get_network_devices()

        nets = self.window.get_widget("network-view")
        netsModel = nets.get_model()
        for d in netList:
            netsModel.append(None, d)
            

gobject.type_register(vmmDetails)

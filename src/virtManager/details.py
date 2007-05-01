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
import traceback

from virtManager.error import vmmErrorDialog
from virtManager.addhardware import vmmAddHardware

import virtinst
import urlgrabber.progress as progress

# HW types for the hw list model
VMM_HW_CPU = 0
VMM_HW_MEMORY = 1
VMM_HW_DISK = 2
VMM_HW_NIC = 3

class vmmDetails(gobject.GObject):
    __gsignals__ = {
        "action-show-console": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-terminal": (gobject.SIGNAL_RUN_FIRST,
                                   gobject.TYPE_NONE, (str,str)),
        "action-save-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str,str)),
        "action-destroy-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str,str)),
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                               gobject.TYPE_NONE, [str]),
        }
    def __init__(self, config, vm):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-details.glade", "vmm-details", domain="virt-manager")
        self.config = config
        self.vm = vm

        topwin = self.window.get_widget("vmm-details")
        topwin.hide()
        topwin.set_title(self.vm.get_name() + " " + topwin.get_title())

        # Don't allowing changing network/disks for Dom0
        if self.vm.is_management_domain():
            self.window.get_widget("add-hardware-button").set_sensitive(False)
        else:
            self.window.get_widget("add-hardware-button").set_sensitive(True)

        self.window.get_widget("overview-name").set_text(self.vm.get_name())
        self.window.get_widget("overview-uuid").set_text(self.vm.get_uuid())

        self.window.get_widget("control-shutdown").set_icon_widget(gtk.Image())
        self.window.get_widget("control-shutdown").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_shutdown.png")

        self.window.get_widget("hw-panel").set_show_tabs(False)

        self.addhw = None

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
            "on_details_menu_destroy_activate": self.control_vm_destroy,

            "on_details_menu_graphics_activate": self.control_vm_console,
            "on_details_menu_serial_activate": self.control_vm_terminal,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,

            "on_config_vcpus_apply_clicked": self.config_vcpus_apply,
            "on_config_vcpus_changed": self.config_vcpus_changed,
            "on_config_memory_changed": self.config_memory_changed,
            "on_config_maxmem_changed": self.config_maxmem_changed,
            "on_config_memory_apply_clicked": self.config_memory_apply,
            "on_details_help_activate": self.show_help,

            "on_config_disk_remove_clicked": self.remove_disk,
            "on_config_network_remove_clicked": self.remove_network,
            "on_add_hardware_button_clicked": self.add_hardware,
            })

        self.vm.connect("status-changed", self.update_widget_states)
        self.vm.connect("resources-sampled", self.refresh_resources)
        self.window.get_widget("hw-list").get_selection().connect("changed", self.hw_selected)

        self.update_widget_states(self.vm, self.vm.status())
        self.refresh_resources(self.vm)

        self.pixbuf_processor = gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")
        self.pixbuf_memory = gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")
        self.pixbuf_disk =  gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_hdd.png")
        self.pixbuf_nic =  gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_ethernet.png")
        self.prepare_hw_list()
        self.hw_selected()

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
        self.update_widget_states(self.vm, self.vm.status())

    def show_help(self, src):
        # From the Details window, show the help document from the Details page
        self.emit("action-show-help", "virt-manager-details-window")

    def activate_performance_page(self):
        self.window.get_widget("details-pages").set_current_page(0)

    def activate_config_page(self):
        self.window.get_widget("details-pages").set_current_page(1)

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-details").hide()
        return 1

    def is_visible(self):
        if self.window.get_widget("vmm-details").flags() & gtk.VISIBLE:
           return 1
        return 0

    def hw_selected(self, src=None):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            pagetype = active[0].get_value(active[1], 2)
            self.window.get_widget("hw-panel").set_sensitive(True)

            pagenum = -1
            if pagetype == VMM_HW_CPU:
                self.window.get_widget("config-vcpus-apply").set_sensitive(False)
                self.refresh_config_cpu()
                pagenum = 0
            elif pagetype == VMM_HW_MEMORY:
                self.window.get_widget("config-memory-apply").set_sensitive(False)
                self.refresh_config_memory()
                pagenum = 1
            elif pagetype == VMM_HW_DISK:
                self.refresh_disk_page()
                pagenum = 2
            elif pagetype == VMM_HW_NIC:
                self.refresh_network_page()
                pagenum = 3

            self.window.get_widget("hw-panel").set_current_page(pagenum)
        else:
            logging.debug("In hw_selected with null tree iter")
            self.window.get_widget("hw-panel").set_sensitive(False)
            selection.select_path(0)
            self.window.get_widget("hw-panel").set_current_page(0)

    def control_vm_run(self, src):
        status = self.vm.status()
        if status != libvirt.VIR_DOMAIN_SHUTOFF:
            pass
        else:
            try:
                self.vm.startup()
            except:
                (type, value, stacktrace) = sys.exc_info ()

                # Detailed error message, in English so it can be Googled.
                details = \
                        "Unable to start virtual machine '%s'" % \
                        (str(type) + " " + str(value) + "\n" + \
                         traceback.format_exc (stacktrace))

                dg = vmmErrorDialog(None, 0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                    str(value),
                                    details)
                dg.run()
                dg.hide()
                dg.destroy()


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

    def control_vm_destroy(self, src):
        self.emit("action-destroy-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def update_widget_states(self, vm, status):
        self.toggle_toolbar(self.window.get_widget("details-menu-view-toolbar"))
        self.ignorePause = True
        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF ] or vm.is_read_only():
            # apologies for the spaghetti, but the destroy choice is a special case
            self.window.get_widget("details-menu-destroy").set_sensitive(False)
        else:
            self.window.get_widget("details-menu-destroy").set_sensitive(True)
        try:
            if status in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
                self.window.get_widget("control-run").set_sensitive(True)
                self.window.get_widget("details-menu-run").set_sensitive(True)
                self.window.get_widget("config-vcpus").set_sensitive(True)
                self.window.get_widget("config-memory").set_sensitive(True)
                self.window.get_widget("config-maxmem").set_sensitive(True)
            else:
                self.window.get_widget("control-run").set_sensitive(False)
                self.window.get_widget("details-menu-run").set_sensitive(False)
                self.window.get_widget("config-vcpus").set_sensitive(self.vm.is_vcpu_hotplug_capable())
                self.window.get_widget("config-memory").set_sensitive(self.vm.is_memory_hotplug_capable())
                self.window.get_widget("config-maxmem").set_sensitive(False)

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

    def refresh_resources(self, ignore):
        details = self.window.get_widget("details-pages")
        if details.get_current_page() == 0:
            self.refresh_summary()
        else:
            # Add / remove new devices
            self.repopulate_hw_list()

            # Now refresh desired page
            hw_list = self.window.get_widget("hw-list")
            selection = hw_list.get_selection()
            active = selection.get_selected()
            if active[1] != None:
                pagetype = active[0].get_value(active[1], 2)
                device_info = active[0].get_value(active[1], 3)
                hw_model = hw_list.get_model()
                if pagetype == VMM_HW_CPU:
                    self.refresh_config_cpu()
                elif pagetype == VMM_HW_MEMORY:
                    self.refresh_config_memory()
                elif pagetype == VMM_HW_DISK:
                    self.refresh_disk_page()
                elif pagetype == VMM_HW_NIC:
                    self.refresh_network_page()

    def refresh_summary(self):
        self.window.get_widget("overview-cpu-usage-text").set_text("%d %%" % self.vm.cpu_time_percentage())
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

    def refresh_config_cpu(self):
        self.window.get_widget("state-host-cpus").set_text("%d" % self.vm.get_connection().host_active_processor_count())
        status = self.vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
            self.window.get_widget("config-vcpus").get_adjustment().upper = 32
            self.window.get_widget("state-vm-maxvcpus").set_text("32")
        else:
            self.window.get_widget("config-vcpus").get_adjustment().upper = self.vm.vcpu_max_count()
            self.window.get_widget("state-vm-maxvcpus").set_text("%d" % (self.vm.vcpu_max_count()))

        if not(self.window.get_widget("config-vcpus-apply").get_property("sensitive")):
            self.window.get_widget("config-vcpus").get_adjustment().value = self.vm.vcpu_count()
            # XXX hack - changing the value above will have just re-triggered
            # the callback making apply button sensitive again. So we have to
            # turn it off again....
            self.window.get_widget("config-vcpus-apply").set_sensitive(False)
        self.window.get_widget("state-vm-vcpus").set_text("%d" % (self.vm.vcpu_count()))

    def refresh_config_memory(self):
        self.window.get_widget("state-host-memory").set_text("%d MB" % (self.vm.get_connection().host_memory_size()/1024))
        if self.window.get_widget("config-memory-apply").get_property("sensitive"):
            self.window.get_widget("config-memory").get_adjustment().upper = self.window.get_widget("config-maxmem").get_adjustment().value
        else:
            self.window.get_widget("config-memory").get_adjustment().value = self.vm.get_memory()/1024
            self.window.get_widget("config-maxmem").get_adjustment().value = self.vm.maximum_memory()/1024
            # XXX hack - changing the value above will have just re-triggered
            # the callback making apply button sensitive again. So we have to
            # turn it off again....
            self.window.get_widget("config-memory-apply").set_sensitive(False)

        self.window.get_widget("state-vm-memory").set_text("%d MB" % (self.vm.get_memory()/1024))

    def refresh_disk_page(self):
        # get the currently selected line
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            diskinfo = active[0].get_value(active[1], 3)
            self.window.get_widget("disk-source-type").set_text(diskinfo[0])
            self.window.get_widget("disk-source-path").set_text(diskinfo[1])
            self.window.get_widget("disk-target-type").set_text(diskinfo[2])
            self.window.get_widget("disk-target-device").set_text(diskinfo[3])

    def refresh_network_page(self):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            netinfo = active[0].get_value(active[1], 3)
            self.window.get_widget("network-source-type").set_text(netinfo[0])
            if netinfo[1] is not None:
                self.window.get_widget("network-source-device").set_text(netinfo[1])
            else:
                self.window.get_widget("network-source-device").set_text("-")
            self.window.get_widget("network-mac-address").set_text(netinfo[3])

    def config_vcpus_changed(self, src):
        self.window.get_widget("config-vcpus-apply").set_sensitive(True)

    def config_vcpus_apply(self, src):
        vcpus = self.window.get_widget("config-vcpus").get_adjustment().value
        logging.info("Setting vcpus for " + self.vm.get_uuid() + " to " + str(vcpus))
        self.vm.set_vcpu_count(vcpus)
        self.window.get_widget("config-vcpus-apply").set_sensitive(False)

    def config_memory_changed(self, src):
        self.window.get_widget("config-memory-apply").set_sensitive(True)

    def config_maxmem_changed(self, src):
        self.window.get_widget("config-memory-apply").set_sensitive(True)
        memory = self.window.get_widget("config-maxmem").get_adjustment().value
        memadj = self.window.get_widget("config-memory").get_adjustment()
        memadj.upper = memory
        if memadj.value > memory:
            memadj.value = memory

    def config_memory_apply(self, src):
        status = self.vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
            memory = self.window.get_widget("config-maxmem").get_adjustment().value
            logging.info("Setting max memory for " + self.vm.get_uuid() + " to " + str(memory))
            self.vm.set_max_memory(memory*1024)
        memory = self.window.get_widget("config-memory").get_adjustment().value
        logging.info("Setting memory for " + self.vm.get_uuid() + " to " + str(memory))
        self.vm.set_memory(memory*1024)

        self.window.get_widget("config-memory-apply").set_sensitive(False)


    def remove_disk(self, src):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            diskinfo = active[0].get_value(active[1], 3)

            vbd = virtinst.VirtualDisk(path=diskinfo[1], type=diskinfo[0], device=diskinfo[2])
            xml = vbd.get_xml_config(diskinfo[3])

            self.vm.remove_device(xml)

    def remove_network(self, src):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            netinfo = active[0].get_value(active[1], 3)

            vnic = None
            if netinfo[0] == "bridge":
                vnic = virtinst.VirtualNetworkInterface(type=netinfo[0], bridge=netinfo[1], macaddr=netinfo[3])
            elif net[0] == "network":
                vnic = virtinst.VirtualNetworkInterface(type=netinfo[0], network=netinfo[1], macaddr=netinfo[3])
            else:
                vnic = virtinst.VirtualNetworkInterface(type=netinfo[0], macaddr=netinfo[3])

            xml = vnic.get_xml_config()
            self.vm.remove_device(xml)


    def prepare_hw_list(self):
        hw_list_model = gtk.ListStore(str, gtk.gdk.Pixbuf, int, gobject.TYPE_PYOBJECT)
        self.window.get_widget("hw-list").set_model(hw_list_model)

        hwCol = gtk.TreeViewColumn("Hardware")
        hw_txt = gtk.CellRendererText()
        hw_img = gtk.CellRendererPixbuf()
        hwCol.pack_start(hw_txt, True)
        hwCol.pack_start(hw_img, False)
        hwCol.add_attribute(hw_txt, 'text', 0)
        hwCol.add_attribute(hw_img, 'pixbuf', 1)
        self.window.get_widget("hw-list").append_column(hwCol)

        self.populate_hw_list()

    def populate_hw_list(self):
        hw_list_model = self.window.get_widget("hw-list").get_model()
        hw_list_model.clear()
        hw_list_model.append(["Processor", self.pixbuf_processor, VMM_HW_CPU, []])
        hw_list_model.append(["Memory", self.pixbuf_memory, VMM_HW_MEMORY, []])
        self.repopulate_hw_list()

    def repopulate_hw_list(self):
        hw_list = self.window.get_widget("hw-list")
        hw_list_model = hw_list.get_model()

        # Populate list of disks
        currentDisks = {}
        for disk in self.vm.get_disk_devices():
            missing = True
            insertAt = 0
            currentDisks[disk[3]] = 1
            for row in hw_list_model:
                if row[2] == VMM_HW_DISK and row[3][3] == disk[3]:
                    # Update metadata
                    row[3] = disk
                    missing = False
                # The insert position must be *before* any NICs
                if row[2] != VMM_HW_NIC:
                    insertAt = insertAt + 1

            # Add in row
            if missing:
                hw_list_model.insert(insertAt, ["Disk %s" % disk[3], self.pixbuf_disk, VMM_HW_DISK, disk])

        # Populate list of NICs
        currentNICs = {}
        nic_number = 0
        for nic in self.vm.get_network_devices():
            missing = True
            insertAt = 0
            currentNICs[nic[3]] = 1
            for row in hw_list_model:
                if row[2] == VMM_HW_NIC and row[3][3] == nic[3]:
                    # Update metadata
                    row[3] = nic
                    missing = False

                # Insert position is at end....
                # XXX until we add support for Mice, etc
                insertAt = insertAt + 1

            # Add in row
            if missing:
                hw_list_model.insert(insertAt, ["NIC %s" % nic[3][-3:], self.pixbuf_nic, VMM_HW_NIC, nic])

        # Now remove any no longer current devs
        devs = range(len(hw_list_model))
        devs.reverse()
        for i in devs:
            iter = hw_list_model.iter_nth_child(None, i)
            row = hw_list_model[i]
            removeIt = False

            if row[2] == VMM_HW_DISK and not currentDisks.has_key(row[3][3]):
                removeIt = True
            elif row[2] == VMM_HW_NIC and not currentNICs.has_key(row[3][3]):
                removeIt = True

            if removeIt:
                # Re-select the first row, if we're viewing the device
                # we're about to remove
                (selModel, selIter) = hw_list.get_selection().get_selected()
                selType = selModel.get_value(selIter, 2)
                selInfo = selModel.get_value(selIter, 3)
                if selType == row[2] and selInfo[3] == row[3][3]:
                    hw_list.get_selection().select_iter(selModel.iter_nth_child(None, 0))

                # Now actually remove it
                hw_list_model.remove(iter)


    def add_hardware(self, src):
        if self.addhw is None:
            self.addhw = vmmAddHardware(self.config, self.vm)

        self.addhw.show()


gobject.type_register(vmmDetails)

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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.
#

import gobject
import gtk
import gtk.glade
import libvirt
import sparkline
import logging
import traceback
import sys

from virtManager.error import vmmErrorDialog
from virtManager.addhardware import vmmAddHardware
from virtManager.choosecd import vmmChooseCD

import virtinst
import urlgrabber.progress as progress

# Columns in hw list model
HW_LIST_COL_LABEL = 0
HW_LIST_COL_STOCK_ID = 1
HW_LIST_COL_STOCK_SIZE = 2
HW_LIST_COL_PIXBUF = 3
HW_LIST_COL_TYPE = 4
HW_LIST_COL_DEVICE = 5

# Types for the hw list model
HW_LIST_TYPE_CPU = 0
HW_LIST_TYPE_MEMORY = 1
HW_LIST_TYPE_DISK = 2
HW_LIST_TYPE_NIC = 3
HW_LIST_TYPE_INPUT = 4
HW_LIST_TYPE_GRAPHICS = 5

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
        "action-suspend-domain": (gobject.SIGNAL_RUN_FIRST,
                                  gobject.TYPE_NONE, (str, str)),
        "action-resume-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str, str)),
        "action-run-domain": (gobject.SIGNAL_RUN_FIRST,
                              gobject.TYPE_NONE, (str, str)),
        "action-shutdown-domain": (gobject.SIGNAL_RUN_FIRST,
                                   gobject.TYPE_NONE, (str, str)),
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
        # XXX also disable for remote connections for now
        if self.vm.is_management_domain() or self.vm.get_connection().is_remote():
            self.window.get_widget("add-hardware-button").set_sensitive(False)
        else:
            self.window.get_widget("add-hardware-button").set_sensitive(True)

        self.window.get_widget("overview-name").set_text(self.vm.get_name())
        self.window.get_widget("overview-uuid").set_text(self.vm.get_uuid())

        self.window.get_widget("control-shutdown").set_icon_widget(gtk.Image())
        self.window.get_widget("control-shutdown").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_shutdown.png")

        self.window.get_widget("hw-panel").set_show_tabs(False)

        self.addhw = None
        self.choose_cd = None
        
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
            "on_details_menu_shutdown_activate": self.control_vm_shutdown,
            "on_details_menu_save_activate": self.control_vm_save_domain,
            "on_details_menu_destroy_activate": self.control_vm_destroy,
            "on_details_menu_pause_activate": self.control_vm_pause,

            "on_details_menu_graphics_activate": self.control_vm_console,
            "on_details_menu_serial_activate": self.control_vm_terminal,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,

            "on_config_vcpus_apply_clicked": self.config_vcpus_apply,
            "on_config_vcpus_changed": self.config_vcpus_changed,
            "on_config_memory_changed": self.config_memory_changed,
            "on_config_maxmem_changed": self.config_maxmem_changed,
            "on_config_memory_apply_clicked": self.config_memory_apply,
            "on_details_help_activate": self.show_help,

            "on_config_cdrom_connect_clicked": self.toggle_cdrom,
            "on_config_disk_remove_clicked": self.remove_disk,
            "on_config_network_remove_clicked": self.remove_network,
            "on_config_input_remove_clicked": self.remove_input,
            "on_config_graphics_remove_clicked": self.remove_graphics,
            "on_add_hardware_button_clicked": self.add_hardware,
            })

        self.vm.connect("status-changed", self.update_widget_states)
        self.vm.connect("resources-sampled", self.refresh_resources)
        self.window.get_widget("hw-list").get_selection().connect("changed", self.hw_selected)

        self.update_widget_states(self.vm, self.vm.status())
        self.refresh_resources(self.vm)

        self.pixbuf_processor = gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")
        self.pixbuf_memory = gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")
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
            pagetype = active[0].get_value(active[1], HW_LIST_COL_TYPE)
            self.window.get_widget("hw-panel").set_sensitive(True)

            pagenum = pagetype
            if pagetype == HW_LIST_TYPE_CPU:
                self.window.get_widget("config-vcpus-apply").set_sensitive(False)
                self.refresh_config_cpu()
            elif pagetype == HW_LIST_TYPE_MEMORY:
                self.window.get_widget("config-memory-apply").set_sensitive(False)
                self.refresh_config_memory()
            elif pagetype == HW_LIST_TYPE_DISK:
                self.refresh_disk_page()
            elif pagetype == HW_LIST_TYPE_NIC:
                self.refresh_network_page()
            elif pagetype == HW_LIST_TYPE_INPUT:
                self.refresh_input_page()
            elif pagetype == HW_LIST_TYPE_GRAPHICS:
                self.refresh_graphics_page()
            else:
                pagenum = -1

            self.window.get_widget("hw-panel").set_current_page(pagenum)
        else:
            logging.debug("In hw_selected with null tree iter")
            self.window.get_widget("hw-panel").set_sensitive(False)
            selection.select_path(0)
            self.window.get_widget("hw-panel").set_current_page(0)

    def control_vm_pause(self, src):
        if self.ignorePause:
            return

        if src.get_active():
            self.emit("action-suspend-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())
        else:
            self.emit("action-resume-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

        self.update_widget_states(self.vm, self.vm.status())

    def control_vm_run(self, src):
        self.emit("action-run-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_shutdown(self, src):
        self.emit("action-shutdown-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())     

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

    def refresh_resources(self, ignore=None):
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
                pagetype = active[0].get_value(active[1], HW_LIST_COL_TYPE)
                device_info = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
                hw_model = hw_list.get_model()
                if pagetype == HW_LIST_TYPE_CPU:
                    self.refresh_config_cpu()
                elif pagetype == HW_LIST_TYPE_MEMORY:
                    self.refresh_config_memory()
                elif pagetype == HW_LIST_TYPE_DISK:
                    self.refresh_disk_page()
                elif pagetype == HW_LIST_TYPE_NIC:
                    self.refresh_network_page()
                elif pagetype == HW_LIST_TYPE_INPUT:
                    self.refresh_input_page()
                elif pagetype == HW_LIST_TYPE_GRAPHICS:
                    self.refresh_graphics_page()

    def refresh_summary(self):
        self.window.get_widget("overview-cpu-usage-text").set_text("%d %%" % self.vm.cpu_time_percentage())
        vm_memory = self.vm.current_memory()
        host_memory = self.vm.get_connection().host_memory_size()
        self.window.get_widget("overview-memory-usage-text").set_text("%d MB of %d MB" % \
                                                                      (int(round(vm_memory/1024.0)), \
                                                                       int(round(host_memory/1024.0))))

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
            cpu_max = self.vm.get_connection().get_max_vcpus()
            self.window.get_widget("config-vcpus").get_adjustment().upper = cpu_max
            self.window.get_widget("state-vm-maxvcpus").set_text(str(cpu_max))
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
        self.window.get_widget("state-host-memory").set_text("%d MB" % (int(round(self.vm.get_connection().host_memory_size()/1024))))
        if self.window.get_widget("config-memory-apply").get_property("sensitive"):
            self.window.get_widget("config-memory").get_adjustment().upper = self.window.get_widget("config-maxmem").get_adjustment().value
        else:
            self.window.get_widget("config-memory").get_adjustment().value = int(round(self.vm.get_memory()/1024.0))
            self.window.get_widget("config-maxmem").get_adjustment().value = int(round(self.vm.maximum_memory()/1024.0))
            # XXX hack - changing the value above will have just re-triggered
            # the callback making apply button sensitive again. So we have to
            # turn it off again....
            self.window.get_widget("config-memory-apply").set_sensitive(False)

        self.window.get_widget("state-vm-memory").set_text("%d MB" % int(round(self.vm.get_memory()/1024.0)))

    def refresh_disk_page(self):
        # get the currently selected line
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            diskinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
            self.window.get_widget("disk-source-type").set_text(diskinfo[0])
            self.window.get_widget("disk-source-path").set_text(diskinfo[1])
            self.window.get_widget("disk-target-type").set_text(diskinfo[2])
            self.window.get_widget("disk-target-device").set_text(diskinfo[3])
            button = self.window.get_widget("config-cdrom-connect")
            if diskinfo[2] == "cdrom":
                if diskinfo[1] == "-":
                    # source device not connected
                    button.set_label(gtk.STOCK_CONNECT)
                else:
                    button.set_label(gtk.STOCK_DISCONNECT)
                button.show()
            else:
                button.hide()

    def refresh_network_page(self):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            netinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
            self.window.get_widget("network-source-type").set_text(netinfo[0])
            if netinfo[1] is not None:
                self.window.get_widget("network-source-device").set_text(netinfo[1])
            else:
                self.window.get_widget("network-source-device").set_text("-")
            self.window.get_widget("network-mac-address").set_text(netinfo[3])

    def refresh_input_page(self):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            inputinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
            if inputinfo[3] == "tablet:usb":
                self.window.get_widget("input-dev-type").set_text(_("EvTouch USB Graphics Tablet"))
            elif inputinfo[3] == "mouse:usb":
                self.window.get_widget("input-dev-type").set_text(_("Generic USB Mouse"))
            elif inputinfo[3] == "mouse:xen":
                self.window.get_widget("input-dev-type").set_text(_("Xen Mouse"))
            elif inputinfo[3] == "mouse:ps2":
                self.window.get_widget("input-dev-type").set_text(_("PS/2 Mouse"))
            else:
                self.window.get_widget("input-dev-type").set_text(inputinfo[0] + " " + inputinfo[1])

            if inputinfo[0] == "tablet":
                self.window.get_widget("input-dev-mode").set_text(_("Absolute Movement"))
            else:
                self.window.get_widget("input-dev-mode").set_text(_("Relative Movement"))

            # Can't remove primary Xen or PS/2 mice
            if inputinfo[0] == "mouse" and inputinfo[1] in ("xen", "ps2"):
                self.window.get_widget("config-input-remove").set_sensitive(False)
            else:
                self.window.get_widget("config-input-remove").set_sensitive(True)

    def refresh_graphics_page(self):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            inputinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
            if inputinfo[0] == "vnc":
                self.window.get_widget("graphics-type").set_text(_("VNC server"))
            elif inputinfo[0] == "sdl":
                self.window.get_widget("graphics-type").set_text(_("Local SDL window"))
            else:
                self.window.get_widget("graphics-type").set_text(inputinfo[0])

            if inputinfo[0] == "vnc":
                if inputinfo[1] == None:
                    self.window.get_widget("graphics-address").set_text("127.0.0.1")
                else:
                    self.window.get_widget("graphics-address").set_text(inputinfo[1])
                if int(inputinfo[2]) == -1:
                    self.window.get_widget("graphics-port").set_text(_("Automatically allocated"))
                else:
                    self.window.get_widget("graphics-port").set_text(inputinfo[2])
                self.window.get_widget("graphics-password").set_text("")
            else:
                self.window.get_widget("graphics-address").set_text(_("N/A"))
                self.window.get_widget("graphics-port").set_text(_("N/A"))
                self.window.get_widget("graphics-password").set_text("N/A")

            # Can't remove display from live guest
            if self.vm.is_active():
                self.window.get_widget("config-input-remove").set_sensitive(False)
            else:
                self.window.get_widget("config-input-remove").set_sensitive(True)

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
            diskinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
            if diskinfo[1] == "-":
                path = None
            else:
                path = diskinfo[1]

            try:
                vbd = virtinst.VirtualDisk(path=path, 
                                           type=diskinfo[0], 
                                           device=diskinfo[2])
            except Exception, e:
                self._err_dialog(_("Error Removing Disk: %s" % str(e)),
                            "".join(traceback.format_exc()))
                return

            xml = vbd.get_xml_config(diskinfo[3])
            self.remove_device(xml)
            self.refresh_resources()

    def remove_network(self, src):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            netinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)

            vnic = None
            try:
                if netinfo[0] == "bridge":
                    vnic = virtinst.VirtualNetworkInterface(type=netinfo[0], bridge=netinfo[1], macaddr=netinfo[3])
                elif netinfo[0] == "network":
                    vnic = virtinst.VirtualNetworkInterface(type=netinfo[0], network=netinfo[1], macaddr=netinfo[3])
                else:
                    vnic = virtinst.VirtualNetworkInterface(type=netinfo[0], macaddr=netinfo[3])
            except ValueError, e:
                self.err_dialog(_("Error Removing Network: %s" % str(e)),
                            "".join(traceback.format_exc()))
                return

            xml = vnic.get_xml_config()
            self.remove_device(xml)
            self.refresh_resources()

    def remove_input(self, src):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            inputinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)

            xml = "<input type='%s' bus='%s'/>" % (inputinfo[0], inputinfo[1])
            self.remove_device(xml)
            self.refresh_resources()

    def remove_graphics(self, src):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            inputinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)

            xml = "<graphics type='%s'/>" % inputinfo[0]
            self.remove_device(xml)
            self.refresh_resources()

    def prepare_hw_list(self):
        hw_list_model = gtk.ListStore(str, str, int, gtk.gdk.Pixbuf, int, gobject.TYPE_PYOBJECT)
        self.window.get_widget("hw-list").set_model(hw_list_model)

        hwCol = gtk.TreeViewColumn("Hardware")
        hw_txt = gtk.CellRendererText()
        hw_img = gtk.CellRendererPixbuf()
        hwCol.pack_start(hw_txt, True)
        hwCol.pack_start(hw_img, False)
        hwCol.add_attribute(hw_txt, 'text', HW_LIST_COL_LABEL)
        hwCol.add_attribute(hw_img, 'stock-id', HW_LIST_COL_STOCK_ID)
        hwCol.add_attribute(hw_img, 'stock-size', HW_LIST_COL_STOCK_SIZE)
        hwCol.add_attribute(hw_img, 'pixbuf', HW_LIST_COL_PIXBUF)
        self.window.get_widget("hw-list").append_column(hwCol)

        self.populate_hw_list()

    def populate_hw_list(self):
        hw_list_model = self.window.get_widget("hw-list").get_model()
        hw_list_model.clear()
        hw_list_model.append(["Processor", None, 0, self.pixbuf_processor, HW_LIST_TYPE_CPU, []])
        hw_list_model.append(["Memory", None, 0, self.pixbuf_memory, HW_LIST_TYPE_MEMORY, []])
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
                if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_DISK and row[HW_LIST_COL_DEVICE][3] == disk[3]:
                    # Update metadata
                    row[HW_LIST_COL_DEVICE] = disk
                    missing = False

                if row[HW_LIST_COL_TYPE] not in (HW_LIST_TYPE_NIC, HW_LIST_TYPE_INPUT, HW_LIST_TYPE_GRAPHICS):
                    insertAt = insertAt + 1

            # Add in row
            if missing:
                stock = gtk.STOCK_HARDDISK
                if disk[2] == "cdrom":
                    stock = gtk.STOCK_CDROM
                elif disk[2] == "floppy":
                    stock = gtk.STOCK_FLOPPY
                hw_list_model.insert(insertAt, ["Disk %s" % disk[3], stock, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_DISK, disk])

        # Populate list of NICs
        currentNICs = {}
        for nic in self.vm.get_network_devices():
            missing = True
            insertAt = 0
            currentNICs[nic[3]] = 1
            for row in hw_list_model:
                if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_NIC and row[HW_LIST_COL_DEVICE][3] == nic[3]:
                    # Update metadata
                    row[HW_LIST_COL_DEVICE] = nic
                    missing = False

                if row[HW_LIST_COL_TYPE] not in (HW_LIST_TYPE_INPUT,HW_LIST_TYPE_GRAPHICS):
                    insertAt = insertAt + 1

            # Add in row
            if missing:
                hw_list_model.insert(insertAt, ["NIC %s" % nic[3][-9:], gtk.STOCK_NETWORK, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_NIC, nic])

        # Populate list of input devices
        currentInputs = {}
        for input in self.vm.get_input_devices():
            missing = True
            insertAt = 0
            currentInputs[input[3]] = 1
            for row in hw_list_model:
                if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_INPUT and row[HW_LIST_COL_DEVICE][3] == input[3]:
                    # Update metadata
                    row[HW_LIST_COL_DEVICE] = input
                    missing = False

                if row[HW_LIST_COL_TYPE] not in (HW_LIST_TYPE_GRAPHICS,):
                    insertAt = insertAt + 1

            # Add in row
            if missing:
                if input[0] == "tablet":
                    hw_list_model.insert(insertAt, [_("Tablet"), gtk.STOCK_INDEX, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_INPUT, input])
                elif input[0] == "mouse":
                    hw_list_model.insert(insertAt, [_("Mouse"), gtk.STOCK_INDEX, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_INPUT, input])
                else:
                    hw_list_model.insert(insertAt, [_("Input"), gtk.STOCK_INDEX, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_INPUT, input])

        # Populate list of graphics devices
        currentGraphics = {}
        for graphic in self.vm.get_graphics_devices():
            missing = True
            insertAt = 0
            currentGraphics[graphic[3]] = 1
            for row in hw_list_model:
                if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_GRAPHICS and row[HW_LIST_COL_DEVICE][3] == graphic[3]:
                    # Update metadata
                    row[HW_LIST_COL_DEVICE] = graphic
                    missing = False

                insertAt = insertAt + 1

            # Add in row
            if missing:
                hw_list_model.insert(insertAt, [_("Display"), gtk.STOCK_SELECT_COLOR, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_GRAPHICS, graphic])

        # Now remove any no longer current devs
        devs = range(len(hw_list_model))
        devs.reverse()
        for i in devs:
            iter = hw_list_model.iter_nth_child(None, i)
            row = hw_list_model[i]
            removeIt = False

            if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_DISK and not currentDisks.has_key(row[HW_LIST_COL_DEVICE][3]):
                removeIt = True
            elif row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_NIC and not currentNICs.has_key(row[HW_LIST_COL_DEVICE][3]):
                removeIt = True
            elif row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_INPUT and not currentInputs.has_key(row[HW_LIST_COL_DEVICE][3]):
                removeIt = True
            elif row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_GRAPHICS and not currentGraphics.has_key(row[HW_LIST_COL_DEVICE][3]):
                removeIt = True

            if removeIt:
                # Re-select the first row, if we're viewing the device
                # we're about to remove
                (selModel, selIter) = hw_list.get_selection().get_selected()
                selType = selModel.get_value(selIter, HW_LIST_COL_TYPE)
                selInfo = selModel.get_value(selIter, HW_LIST_COL_DEVICE)
                if selType == row[HW_LIST_COL_TYPE] and selInfo[3] == row[HW_LIST_COL_DEVICE][3]:
                    hw_list.get_selection().select_iter(selModel.iter_nth_child(None, 0))

                # Now actually remove it
                hw_list_model.remove(iter)


    def add_hardware(self, src):
        if self.addhw is None:
            self.addhw = vmmAddHardware(self.config, self.vm)
            self.addhw.topwin.connect("hide", self.add_hardware_done)

        self.addhw.show()

    def add_hardware_done(self, ignore=None):
        self.refresh_resources()

    def toggle_cdrom(self, src):
        if src.get_label() == gtk.STOCK_DISCONNECT:
            #disconnect the cdrom
            try:
                self.vm.disconnect_cdrom_device(self.window.get_widget("disk-target-device").get_text())
            except Exception, e:
                self._err_dialog(_("Error Removing CDROM: %s" % str(e)),
                                 "".join(traceback.format_exc()))
                return
                
        else:
            # connect a new cdrom
            if self.choose_cd is None:
                self.choose_cd = vmmChooseCD(self.config, self.window.get_widget("disk-target-device").get_text())
                self.choose_cd.connect("cdrom-chosen", self.connect_cdrom)
            else:
                self.choose_cd.set_target(self.window.get_widget("disk-target-device").get_text())
            self.choose_cd.show()

    def connect_cdrom(self, src, type, source, target):
        try:
            self.vm.connect_cdrom_device(type, source, target)
        except Exception, e:            
            self._err_dialog(_("Error Connecting CDROM: %s" % str(e)),
                               "".join(traceback.format_exc()))

    def remove_device(self, xml):
        try:
            self.vm.remove_device(xml)
        except Exception, e:
            self._err_dialog(_("Error Removing Device: %s" % str(e)),
                             "".join(traceback.format_exc()))

    def _err_dialog(self, summary, details):
        dg = vmmErrorDialog(None, 0, gtk.MESSAGE_ERROR, 
                            gtk.BUTTONS_CLOSE, summary, details)
        dg.run()
        dg.hide()
        dg.destroy()
    
gobject.type_register(vmmDetails)

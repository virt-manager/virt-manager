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

import virtinst
import urlgrabber.progress as progress

# HW types for the hw list model
VMM_HW_CPU = 0
VMM_HW_MEMORY = 1
VMM_HW_DISK = 2
VMM_HW_NIC = 3
VMM_HW_DEVICES = [_("Virtual Disk"), _("Virtual NIC")]

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

        self.window.get_widget("overview-name").set_text(self.vm.get_name())
        self.window.get_widget("overview-uuid").set_text(self.vm.get_uuid())

        self.window.get_widget("control-shutdown").set_icon_widget(gtk.Image())
        self.window.get_widget("control-shutdown").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_shutdown.png")

        self.window.get_widget("hw-panel").set_show_tabs(False)


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

            #for adding vbds. Disgracefully copied from create.py.
            "on_storage_partition_address_browse_clicked" : self.browse_storage_partition_address,
            "on_storage_file_address_browse_clicked" : self.browse_storage_file_address,
            "on_storage_file_address_changed": self.toggle_storage_size,
            "on_storage_toggled" : self.change_storage_type,
            "on_add_hardware_button_clicked": self.add_hardware,
            "on_vnic_apply_clicked": self.add_vnic,
            "on_vnic_cancel_clicked": self.clean_up_add_hardware,
            "on_vbd_add_apply_clicked": self.add_vbd,
            "on_vbd_add_cancel_clicked": self.clean_up_add_hardware,
            
            })

        self.vm.connect("status-changed", self.update_widget_states)
        self.vm.connect("resources-sampled", self.refresh_resources)
        self.window.get_widget("hw-list").get_selection().connect("changed", self.hw_selected)

        # set up the list for new hardware devices
        hw_type_list = self.window.get_widget("add-hardware-device")
        hw_type_model = hw_type_list.get_model()
        for device_name in VMM_HW_DEVICES:
            hw_type_model.append([device_name])
        hw_type_list.set_active(0)

        # list for network pulldown
        network_list = self.window.get_widget("network-name-pulldown")
        network_model = gtk.ListStore(str, str, str)
        network_list.set_model(network_model)
        text = gtk.CellRendererText()
        network_list.pack_start(text, True)
        network_list.add_attribute(text, 'text', 0)

        #using this as the flag for whether the network page is in edit mode. Ugh.
        self.adding_hardware = False

        self.update_widget_states(vm, vm.status())
        self.refresh_resources(vm)

        self.pixbuf_processor = gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")
        self.pixbuf_memory = gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")
        self.pixbuf_disk =  gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_hdd.png")
        self.pixbuf_network =  gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_ethernet.png")
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
        self.adding_hardware = False
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            pagetype = active[0].get_value(active[1], 3)
            self.window.get_widget("hw-panel").set_sensitive(True)

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
                self.window.get_widget("network-name-pulldown").hide()
                self.window.get_widget("network-buttons").hide()
                self.window.get_widget("network-name").set_editable(False)
                self.window.get_widget("network-mac-address").set_editable(False)
                self.window.get_widget("net-devlabel-label").show()
                self.window.get_widget("network-device-name").show()
                self.refresh_network_page()
                pagenum = 3
            self.window.get_widget("hw-panel").set_current_page(pagenum)
        else:
            logging.debug("In hw_selected with null tree iter")
            self.window.get_widget("hw-panel").set_sensitive(True)
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
        self.refresh_summary()
        if self.window.get_widget("details-pages").get_current_page() == 1:
            #XXX for this week this only works for active domains, and it's temporary.
            if self.vm.is_active():
                self.window.get_widget("add-hardware-button").set_sensitive(True)
            else:
                self.window.get_widget("add-hardware-button").set_sensitive(False)
                
            if self.adding_hardware:
                return
            # reload the hw model, go to the correct page, and refresh that page
            hw_list = self.window.get_widget("hw-list")
            hw_panel = self.window.get_widget("hw-panel")
            selection = hw_list.get_selection()
            active = selection.get_selected()
            if active[1] != None:
                pagetype = active[0].get_value(active[1], 3)
                device_info = active[0].get_value(active[1], 4)
                self.populate_hw_list()
                hw_model = hw_list.get_model()
                if pagetype == VMM_HW_CPU:
                    self.refresh_config_cpu()
                    pagenum = 0
                    selection.select_path(0)
                elif pagetype == VMM_HW_MEMORY:
                    self.refresh_config_memory()
                    pagenum = 1
                    selection.select_path(1)
                elif pagetype == VMM_HW_DISK:
                    self.refresh_disk_page()
                    # try to match the old source dev to one of the new source devs
                    selection.select_path(0)
                    pagenum = 0
                    i=0
                    for hw in hw_model:
                        if hw[3] == VMM_HW_DISK: 
                            if device_info[1] == hw[4][1]:
                                selection.select_path(i)
                                pagenum = 2
                                break
                        i = i + 1
                elif pagetype == VMM_HW_NIC:
                    self.refresh_network_page()
                    selection.select_path(0)
                    pagenum = 0
                    i=0
                    for hw in hw_model:
                        if hw[3] == VMM_HW_NIC: 
                            if device_info[3] == hw[4][3]:
                                selection.select_path(i)
                                pagenum = 3
                                break
                        i = i + 1
                hw_panel.set_current_page(pagenum)

            else:
                logging.debug("In hw_selected with null tree iter")
                hw_panel.set_sensitive(True)
                selection.select_path(0)
                hw_panel.set_current_page(0)

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
            diskinfo = active[0].get_value(active[1], 4)
            # fill the fields on the screen
            self.window.get_widget("disk-type").set_text(diskinfo[0])
            self.window.get_widget("storage-source").set_text(diskinfo[1])
            self.window.get_widget("storage-device").set_text(diskinfo[2])
            self.window.get_widget("device-label").set_text(diskinfo[3])

    def refresh_network_page(self):
        # get the line what was clicked
        if not self.adding_hardware:
            # viewing net page, not adding a device. If adding, don't try to refresh
            vmlist = self.window.get_widget("hw-list")
            selection = vmlist.get_selection()
            active = selection.get_selected()
            if active[1] != None:
                netinfo = active[0].get_value(active[1], 4)
                if netinfo[1] == "-":
                    netname = "No network name"
                else:
                    netname = netinfo[1]
                name_widget = self.window.get_widget("network-name")
                name_widget.set_text(netname)
                name_widget.show()
                self.window.get_widget("network-mac-address").set_text(netinfo[3])
                self.window.get_widget("network-device-name").set_text(netinfo[2])
            
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


    def browse_storage_partition_address(self, src, ignore=None):
        part = self._browse_file(_("Locate Storage Partition"), "/dev")
        if part != None:
            self.window.get_widget("storage-partition-address").set_text(part)

    def browse_storage_file_address(self, src, ignore=None):
        self.window.get_widget("storage-file-size").set_sensitive(True)
        fcdialog = gtk.FileChooserDialog(_("Locate or Create New Storage File"),
                                         self.window.get_widget("vmm-create"),
                                         gtk.FILE_CHOOSER_ACTION_SAVE,
                                         (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                          gtk.STOCK_OPEN, gtk.RESPONSE_ACCEPT),
                                         None)
        fcdialog.set_do_overwrite_confirmation(True)
        fcdialog.connect("confirm-overwrite", self.confirm_overwrite_callback)
        response = fcdialog.run()
        fcdialog.hide()
        file = None
        if(response == gtk.RESPONSE_ACCEPT):
            file = fcdialog.get_filename()
        if file != None:
            self.window.get_widget("storage-file-address").set_text(file)

    def toggle_storage_size(self, ignore1=None, ignore2=None):
        file = self.get_config_disk_image()
        if file != None and len(file) > 0 and not(os.path.exists(file)):
            self.window.get_widget("storage-file-size").set_sensitive(True)
            self.window.get_widget("non-sparse").set_sensitive(True)
            self.window.get_widget("storage-file-size").set_value(4000)
        else:
            self.window.get_widget("storage-file-size").set_sensitive(False)
            self.window.get_widget("non-sparse").set_sensitive(False)
            if os.path.isfile(file):
                size = os.path.getsize(file)/(1024*1024)
                self.window.get_widget("storage-file-size").set_value(size)
            else:
                self.window.get_widget("storage-file-size").set_value(0)

    def confirm_overwrite_callback(self, chooser):
        # Only called when the user has chosen an existing file
        self.window.get_widget("storage-file-size").set_sensitive(False)
        return gtk.FILE_CHOOSER_CONFIRMATION_ACCEPT_FILENAME

    def change_storage_type(self, ignore=None):
        if self.window.get_widget("storage-partition").get_active():
            self.window.get_widget("storage-partition-box").set_sensitive(True)
            self.window.get_widget("storage-file-box").set_sensitive(False)
            self.window.get_widget("storage-file-size").set_sensitive(False)
            self.window.get_widget("non-sparse").set_sensitive(False)
        else:
            self.window.get_widget("storage-partition-box").set_sensitive(False)
            self.window.get_widget("storage-file-box").set_sensitive(True)
            self.toggle_storage_size()

    def prepare_hw_list(self):
        hw_list_model = gtk.ListStore(int, str, gtk.gdk.Pixbuf, int, gobject.TYPE_PYOBJECT)
        self.window.get_widget("hw-list").set_model(hw_list_model)
        self.populate_hw_list()

        hwCol = gtk.TreeViewColumn("Hardware")
        hw_txt = gtk.CellRendererText()
        hw_img = gtk.CellRendererPixbuf()
        hwCol.pack_start(hw_txt, True)
        hwCol.pack_start(hw_img, False)
        hwCol.add_attribute(hw_txt, 'text', 1)
        hwCol.add_attribute(hw_img, 'pixbuf', 2)
        self.window.get_widget("hw-list").append_column(hwCol)

    def populate_hw_list(self):
        hw_list_model = self.window.get_widget("hw-list").get_model()
        hw_list_model.clear()
        hw_list_model.append([0, "Processor", self.pixbuf_processor, VMM_HW_CPU, []])
        hw_list_model.append([1, "Memory", self.pixbuf_memory, VMM_HW_MEMORY, []])

        #all disks
        disk_list = self.vm.get_disk_devices()
        for i in range(len(disk_list)):
            hw_list_model.append([i + 2, "Disk %d" % (i + 1), self.pixbuf_disk, VMM_HW_DISK, disk_list[i]])

        #all nics
        nic_list = self.vm.get_network_devices()
        offset = len(disk_list) + 2
        for i in range(len(nic_list)):
            hw_list_model.append([offset + i, "Network %d" % (i + 1), self.pixbuf_network, VMM_HW_NIC, nic_list[i]])
        
    def add_hardware(self, src):
        self.adding_hardware = True
        widget = self.window.get_widget("add-hardware-device")
        iter = widget.get_active_iter()
        device = widget.get_model().get_value(iter, 0)
        if VMM_HW_DEVICES.index(device) == 0:
            # a new virtual disk
            self.window.get_widget("hw-panel").set_current_page(4)
        elif VMM_HW_DEVICES.index(device) == 1:
            # a new vnic
            network_menu = self.window.get_widget("network-name-pulldown")
            self.populate_network_model(network_menu.get_model())
            network_menu.set_active(0)
            network_menu.show()
            self.window.get_widget("network-buttons").show()
            self.window.get_widget("network-name").hide()
            mac_addr = self.window.get_widget("network-mac-address")
            mac_addr.set_editable(True)
            mac_addr.set_text("")
            self.window.get_widget("net-devlabel-label").hide()
            self.window.get_widget("network-device-name").hide()
            self.window.get_widget("hw-panel").set_current_page(3)
        else:
            pass
        
    def populate_network_model(self, model):
        model.clear()
        for uuid in self.vm.get_connection().list_net_uuids():
            net = self.vm.get_connection().get_net(uuid)
            model.append([net.get_label(), net.get_name(), "network"])
        br = virtinst.util.default_bridge()
        model.append([_("default bridge"), br, "bridge"])

    def add_vnic(self, src):
        network = None
        bridge = None
        net_name_widget = self.window.get_widget("network-name-pulldown")
        net_name = net_name_widget.get_model().get_value(net_name_widget.get_active_iter(), 1)
        net_type = net_name_widget.get_model().get_value(net_name_widget.get_active_iter(), 2)
        mac_addr = self.window.get_widget("network-mac-address").get_text()
        if mac_addr == "":
            mac_addr = None
        if net_type == "network":
            network = net_name
        else:
            bridge = net_name
        self.vm.add_network_device(mac_addr, net_type, bridge, network)
        self.clean_up_add_hardware()

    def add_vbd(self, src):
        # disks
#         filesize = None
#         if self.vm.is_hvm():
#             disknode = "hd"
#         else:
#             disknode = "xvd"
#         if self.get_config_disk_size() != None:
#             filesize = self.get_config_disk_size() / 1024.0
#         try:
#             d = virtinst.VirtualDisk(self.get_config_disk_image(), filesize, sparse = self.is_sparse_file())
#             if d.type == virtinst.VirtualDisk.TYPE_FILE and \
#                    self.vm.is_hvm() == False \
#                    and virtinst.util.is_blktap_capable():
#                 d.driver_name = virtinst.VirtualDisk.DRIVER_TAP
#             if d.type == virtinst.VirtualDisk.TYPE_FILE and not \
#                self.is_sparse_file():
#                 self.non_sparse = True
#             else:
#                 self.non_sparse = False
#         except ValueError, e:
#             self._validation_error_box(_("Invalid storage address"), e.args[0])
#             return

#         #XXX add the progress bar in here...
#         d.setup(progress.BaseMeter)
#         xml = d.get_xml_config(disknode)
#         logging.debug("Disk XML: %s" % d)
#         self.vm.add_disk_device(xml)
        self.clean_up_add_hardware()

    def get_config_disk_image(self):
        if self.window.get_widget("storage-partition").get_active():
            return self.window.get_widget("storage-partition-address").get_text()
        else:
            return self.window.get_widget("storage-file-address").get_text()

    def get_config_disk_size(self):
        if self.window.get_widget("storage-partition").get_active():
            return None
        else:
            return self.window.get_widget("storage-file-size").get_value()

    def is_sparse_file(self):
        if self.window.get_widget("non-sparse").get_active():
            return False
        else:
            return True

    def clean_up_add_hardware(self, src=None):
        self.adding_hardware = False
        self.hw_selected()
        
    def _validation_error_box(self, text1, text2=None):
        message_box = gtk.MessageDialog(self.window.get_widget("vmm-details"), \
                                                0, \
                                                gtk.MESSAGE_ERROR, \
                                                gtk.BUTTONS_OK, \
                                                text1)
        if text2 != None:
            message_box.format_secondary_text(text2)
        message_box.run()
        message_box.destroy()

    def _browse_file(self, dialog_name, folder=None, type=None):
        # user wants to browse for an ISO
        fcdialog = gtk.FileChooserDialog(dialog_name,
                                         self.window.get_widget("vmm-details"),
                                         gtk.FILE_CHOOSER_ACTION_OPEN,
                                         (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                          gtk.STOCK_OPEN, gtk.RESPONSE_ACCEPT),
                                         None)
        if type != None:
            f = gtk.FileFilter()
            f.add_pattern("*." + type)
            fcdialog.set_filter(f)
        if folder != None:
            fcdialog.set_current_folder(folder)
        response = fcdialog.run()
        fcdialog.hide()
        if(response == gtk.RESPONSE_ACCEPT):
            filename = fcdialog.get_filename()
            fcdialog.destroy()
            return filename
        else:
            fcdialog.destroy()
            return None

gobject.type_register(vmmDetails)

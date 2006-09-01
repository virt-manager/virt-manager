#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
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
import gtk.gdk
import gtk.glade
import xeninst 
import os, sys
import subprocess
import urlgrabber.grabber as grabber
import tempfile
import logging
import dbus

from rhpl.exception import installExceptionHandler
from rhpl.translate import _, N_, textdomain, utf8

from virtManager.asyncjob import vmmAsyncJob

VM_PARAVIRT = 1
VM_FULLY_VIRT = 2

VM_INSTALL_FROM_ISO = 1
VM_INSTALL_FROM_CD = 2

VM_STORAGE_PARTITION = 1
VM_STORAGE_FILE = 2

DEFAULT_STORAGE_FILE_SIZE = 500

class vmmCreate(gobject.GObject):
    __gsignals__ = {
        "action-show-console": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-terminal": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        }
    def __init__(self, config, connection):
        self.__gobject_init__()
        self.config = config
        self.connection = connection
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-create")
        self.topwin = self.window.get_widget("vmm-create")
        self.topwin.hide()
        # Get a connection to the SYSTEM bus
        self.bus = dbus.SystemBus()
        # Get a handle to the HAL service
        hal_object = self.bus.get_object('org.freedesktop.Hal', '/org/freedesktop/Hal/Manager')
        self.hal_iface = dbus.Interface(hal_object, 'org.freedesktop.Hal.Manager')

        self.window.signal_autoconnect({
            "on_create_pages_switch_page" : self.page_changed,
            "on_create_cancel_clicked" : self.close,
            "on_vmm_create_delete_event" : self.close,
            "on_create_back_clicked" : self.back,
            "on_create_forward_clicked" : self.forward,
            "on_create_finish_clicked" : self.finish,
            "on_create_vm_name_focus_out_event" : self.set_name,
            "on_virt_method_toggled" : self.set_virt_method,
            "on_media_toggled" : self.set_install_from,
            "on_fv_iso_location_browse_clicked" : self.browse_iso_location,
            "on_storage_partition_address_browse_clicked" : self.browse_storage_partition_address,
            "on_storage_file_address_browse_clicked" : self.browse_storage_file_address,
            "on_storage_toggled" : self.set_storage_type,
            "on_storage_file_size_changed" : self.set_storage_file_size,
            "on_create_memory_max_value_changed" : self.set_max_memory,
            "on_create_memory_startup_value_changed" : self.set_startup_memory,
            "on_create_vcpus_changed" : self.set_vcpus,
            "on_cd_focus_out_event" : self.choose_media_location,
            "on_cd_path_changed" : self.choose_media_location,
            })

        self.set_initial_state()
        
    def show(self):
        self.vm_added_handle = self.connection.connect("vm-added", self.open_vm_console)
        self.topwin.show()

    def _init_members(self):
        #the dahta
        self.vm_name = None
        self.virt_method = VM_PARAVIRT
        self.install_fv_media_type = VM_INSTALL_FROM_ISO
        self.install_media_address = None
        self.install_kickstart_address = None
        self.storage_method = VM_STORAGE_PARTITION
        self.storage_partition_address = None
        self.storage_file_address = None
        self.storage_file_size = DEFAULT_STORAGE_FILE_SIZE
        self.max_memory = 0
        self.startup_memory = 0
        self.vcpus = 1
        self.vm_uuid = None
        self.vm_added_handle = None
        self.install_error = None

    def set_initial_state(self):
        notebook = self.window.get_widget("create-pages")
        notebook.set_show_tabs(False)

        #XXX I don't think I should have to go through and set a bunch of background colors
        # in code, but apparently I do...
        black = gtk.gdk.color_parse("#000")
        self.window.get_widget("intro-title").modify_bg(gtk.STATE_NORMAL,black)
        self.window.get_widget("page1-title").modify_bg(gtk.STATE_NORMAL,black)
        self.window.get_widget("page2-title").modify_bg(gtk.STATE_NORMAL,black)
        self.window.get_widget("page3-title").modify_bg(gtk.STATE_NORMAL,black)
        self.window.get_widget("page3a-title").modify_bg(gtk.STATE_NORMAL,black)
        self.window.get_widget("page4-title").modify_bg(gtk.STATE_NORMAL,black)
        self.window.get_widget("page5-title").modify_bg(gtk.STATE_NORMAL,black)
        self.window.get_widget("page6-title").modify_bg(gtk.STATE_NORMAL,black)

        # set up the list for the cd-path widget
        self.opt_media_list = self.window.get_widget("cd-path")
        model = gtk.ListStore(str)
        self.opt_media_list.set_model(model)
        text = gtk.CellRendererText()
        self.opt_media_list.pack_start(text, True)
        self.opt_media_list.add_attribute(text, 'text', 0)

        self.reset_state()

    def reset_state(self):
        self._init_members()
        notebook = self.window.get_widget("create-pages")
        notebook.set_current_page(0)
        # Hide the "finish" button until the appropriate time
        self.window.get_widget("create-finish").hide()
        self.window.get_widget("create-forward").show()
        self.window.get_widget("create-back").set_sensitive(False)
        self.window.get_widget("storage-file-size").set_sensitive(False)


    def forward(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        if(self.validate(notebook.get_current_page()) != True):
            return

        if (notebook.get_current_page() == 2 and self.virt_method == VM_PARAVIRT):
            notebook.set_current_page(4)
        elif (notebook.get_current_page() == 3 and self.virt_method == VM_FULLY_VIRT):
            notebook.set_current_page(5)
        else:
            notebook.next_page()

    def back(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        # do this always, since there's no "leaving a notebook page" event.
        self.window.get_widget("create-finish").hide()
        self.window.get_widget("create-forward").show()
        if notebook.get_current_page() == 4 and self.virt_method == VM_PARAVIRT:
            notebook.set_current_page(2)
        elif notebook.get_current_page() == 5 and self.virt_method == VM_FULLY_VIRT:
            notebook.set_current_page(3)
        else:
            notebook.prev_page()

        
    def page_changed(self, notebook, page, page_number):
        # would you like some spaghetti with your salad, sir?
        
        if page_number == 0:
            #set up the front page
            self.window.get_widget("create-back").set_sensitive(False)
            
        elif page_number == 1:
            #set up the system-name page
            name_widget = self.window.get_widget("create-vm-name")
            if self.vm_name != None:
                name_widget.set_text(self.vm_name)
            else:
                name_widget.set_text("")
            name_widget.grab_focus()
                
        elif page_number == 2:
            #set up the virt method page
            if self.virt_method == VM_PARAVIRT:
                self.window.get_widget("virt-method-pv").set_active(True)
            else:
                self.window.get_widget("virt-method-fv").set_active(True)
                
        elif page_number == 3:
            #set up the fv install media page
            model = self.opt_media_list.get_model()
            model.clear()
            #make sure the model has one empty item
            model.append()
            devs = self._get_optical_devices()
            for dev in devs:
                model.append([dev])
            if self.install_media_address != None:
                self.window.get_widget("fv-iso-location").set_text(self.install_media_address)
            else:
                self.window.get_widget("fv-iso-location").set_text("")
            if self.install_fv_media_type == VM_INSTALL_FROM_ISO:
                self.window.get_widget("media-iso-image").set_active(True)
                self.window.get_widget("fv-iso-location-box").set_sensitive(True)
            else:
                self.window.get_widget("media-physical").set_active(True)
                self.window.get_widget("fv-iso-location-box").set_sensitive(False)
                
        elif page_number == 4:
            #set up the pv install media page
            url_widget = self.window.get_widget("pv-media-url")
            ks_widget = self.window.get_widget("pv-ks-url")
            if self.install_media_address != None:
                url_widget.set_text(self.install_media_address)
            else:
                url_widget.set_text("")
            if self.install_kickstart_address != None:
                ks_widget.set_text(self.install_kickstart_address)
            else:
                ks_widget.set_text("")
            url_widget.grab_focus()
                
        elif page_number == 5:
            #set up the storage space page
            partwidget = self.window.get_widget("storage-partition-address")
            filewidget = self.window.get_widget("storage-file-address")

            if self.storage_partition_address != None:
                partwidget.set_text(self.storage_partition_address)
            else:
                partwidget.set_text("")
            if self.storage_file_address != None:
                filewidget.set_text(self.storage_file_address)
            else:
                filewidget.set_text("")
            if self.storage_method == VM_STORAGE_PARTITION:
                self.window.get_widget("storage-partition").set_active(True)
                self.window.get_widget("storage-partition-box").set_sensitive(True)
                self.window.get_widget("storage-file-box").set_sensitive(False)
            else:
                self.window.get_widget("storage-file-backed").set_active(True)
                self.window.get_widget("storage-partition-box").set_sensitive(False)
                self.window.get_widget("storage-file-box").set_sensitive(True)
                
        elif page_number == 6:
            # memory stuff
            max_mem = self.connection.host_memory_size()/1024 # in megabytes from henceforth

            #avoid absurdity, hopefully
            if self.max_memory == 0:
                self.max_memory = int(max_mem / 2)
            if self.startup_memory > self.max_memory:
                self.startup_memory = self.max_memory
                        
            max_mem_slider = self.window.get_widget("create-memory-max")
            self.window.get_widget("create-host-memory").set_text("%d MB" % max_mem)
            max_mem_slider.get_adjustment().upper = max_mem
            max_mem_slider.get_adjustment().value = self.max_memory
            startup_mem_slider = self.window.get_widget("create-memory-startup")
            startup_mem_slider.get_adjustment().upper = self.max_memory
            startup_mem_slider.get_adjustment().value = self.startup_memory
            startup_mem_slider.set_value(self.max_memory)

            #vcpu stuff
            max_cpus = self.connection.host_maximum_processor_count()
            self.window.get_widget("create-cpus-physical").set_text(`max_cpus`)
            cpu_spinbox = self.window.get_widget("create-vcpus").get_adjustment()
            cpu_spinbox.upper = max_cpus
            cpu_spinbox.value = self.vcpus
            
        elif page_number == 7:
            #set up the congrats page
            congrats = self.window.get_widget("create-congrats-label")
            
            # XXX the validation doesn't really go here
            if self.vm_name == None: self.vm_name = "No Name"
            
            congrats.set_text(_("Congratulations, you have successfully created a new virtual system, <b>\"%s\"</b>. \nYou'll now be able to view and work with \"%s\" in the virtual machine manager.") % (self.vm_name, self.vm_name) )
            congrats.set_use_markup(True)
            self.window.get_widget("create-forward").hide()
            self.window.get_widget("create-finish").show()
        
    def close(self, ignore1=None,ignore2=None):
        self.connection.disconnect(int(self.vm_added_handle))
        self.vm_added_handle = None
        self.topwin.hide()
        return 1
    
    def finish(self, ignore=None):
        #begin DEBUG STUFF
        if self.install_kickstart_address == None:
            ks = "None"
        else:
            ks = self.install_kickstart_address
        if self.storage_file_size==None:
            sfs = "Preset"
        else:
            sfs = `self.storage_file_size/1024`
        if self.storage_method == VM_STORAGE_PARTITION:
            saddr = self.storage_partition_address
        else:
            saddr = self.storage_file_address
        logging.debug("your vm properties: \n Name=" + self.vm_name + \
              "\n Virt method: " + `self.virt_method` + \
              "\n Install media type (fv): " + `self.install_fv_media_type` + \
              "\n Install media address: " + self.install_media_address + \
              "\n Install kickstart address: " + ks + \
              "\n Install storage type: " + `self.storage_method` + \
              "\n Install storage address: " + saddr + \
              "\n Install storage file size: " + sfs + \
              "\n Install max kernel memory: " + `int(self.max_memory)` + \
              "\n Install startup kernel memory: " + `int(self.startup_memory)` + \
              "\n Install vcpus: " + `int(self.vcpus)`)
        # end DEBUG STUFF
        
        # first things first, are we trying to create a fully virt guest?
        if self.virt_method == VM_FULLY_VIRT:
            guest = xeninst.FullVirtGuest()
            try:
                guest.cdrom = self.install_media_address
            except ValueError, e:
                self._validation_error_box(_("Invalid FV media address"),e.args[0])
                self.install_media_address = None
        else:
            guest = xeninst.ParaVirtGuest()
            try:
                guest.location = self.install_media_address
            except ValueError, e:
                self._validation_error_box(_("Invalid PV media address"), e.args[0])
                self.install_media_address = None
                return
            if self.install_kickstart_address != None and self.install_kickstart_address != "":
                guest.extraargs = "ks=%s" % self.install_kickstart_address
                    
        # set the name
        try:
            guest.name = self.vm_name
        except ValueError, e:
            self._validation_error_box(_("Invalid system name"), e.args[0])
            self.vm_name = None
            return
        
        # set the memory
        try:
            guest.memory = int(self.max_memory)
        except ValueError:
            self._validation_error_box(_("Invalid memory setting"), e.args[0])
            self.max_memory = None
            return

        # set vcpus
        guest.vcpus = int(self.vcpus)
        
        # disks
        if self.storage_method == VM_STORAGE_PARTITION:
            saddr = self.storage_partition_address
        else:
            saddr = self.storage_file_address

        filesize = None
        if self.storage_file_size != None:
            filesize = int(self.storage_file_size)/1024
        try:
            d = xeninst.XenDisk(saddr, filesize)
        except ValueError, e:
            self._validation_error_box(_("Invalid storage address"), e.args[0])
            self.storage_partition_address = self.storage_file_address = self.storage_file_size = None
            return
        guest.disks.append(d)

        # network
        n = xeninst.XenNetworkInterface(None)
        guest.nics.append(n)

        #grab the uuid before we start
        self.vm_uuid = xeninst.util.uuidToString(xeninst.util.randomUUID())
        guest.set_uuid(self.vm_uuid)

        # set up the graphics to use SDL
        guest.graphics = "vnc"

        #let's go
        self.install_error = None
        progWin = vmmAsyncJob(self.config, self.do_install, [guest],
                              title=_("Creating Virtual Machine"))
        progWin.run()
        if self.install_error != None:
            self._validation_error_box(_("Guest Install Error"), self.install_error)
            return
        self.close()

    def do_install(self, guest):
        try:
            guest.start_install(False)
        except RuntimeError, e:
            self.install_error = "ERROR: %s" % e
            logging.exception(e)
            return
    
    def set_name(self, src, ignore=None):
        self.vm_name = src.get_text()

    def set_virt_method(self, button):
        if button.get_active():
            if button.name == "virt-method-pv":
                self.virt_method = VM_PARAVIRT
            else:
                self.virt_method = VM_FULLY_VIRT
            self.install_media_address = None

    def set_install_from(self, button):
        if button.get_active():
            if button.name == "media-iso-image":
                self.install_fv_media_type = VM_INSTALL_FROM_ISO
                self.window.get_widget("fv-iso-location-box").set_sensitive(True)
                self.opt_media_list.set_sensitive(False)
            elif button.name == "media-physical":
                self.install_fv_media_type = VM_INSTALL_FROM_CD
                self.window.get_widget("fv-iso-location-box").set_sensitive(False)
                self.opt_media_list.set_sensitive(True)
                self.opt_media_list.set_active(0)
            
    def choose_media_location(self, src):
        model = self.opt_media_list.get_model()
        logging.debug("User chose: " + model.get_value(self.opt_media_list.get_active_iter(), 0))
        self.install_media_address = model.get_value(self.opt_media_list.get_active_iter(), 0)
        
    def browse_iso_location(self, ignore1=None, ignore2=None):
        self.install_media_address = self._browse_file(_("Locate ISO Image"))
        if self.install_media_address != None:
            self.window.get_widget("fv-iso-location").set_text(self.install_media_address)

    def _browse_file(self, dialog_name, folder=None):
        # user wants to browse for an ISO
        fcdialog = gtk.FileChooserDialog(dialog_name,
                                         self.window.get_widget("vmm-create"),
                                         gtk.FILE_CHOOSER_ACTION_OPEN,
                                         (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                          gtk.STOCK_OPEN, gtk.RESPONSE_ACCEPT),
                                         None)
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
        
    def set_media_address(self, src, ignore=None):
        self.install_media_address = src.get_text().strip()
    
    def set_kickstart_address(self, src, ignore=None):
        self.install_kickstart_address = src.get_text().strip()

    def set_storage_partition_address(self, src, ignore=None):
        self.storage_partition_address = src.get_text()

    def set_storage_file_address(self, src, ignore=None):
        self.storage_file_address = src.get_text()

    def browse_storage_partition_address(self, src, ignore=None):
        self.storage_partition_address = self._browse_file(_("Locate Storage Partition"), "/dev")
        if self.storage_partition_address != None:
            self.window.get_widget("storage-partition-address").set_text(self.storage_partition_address)

    def browse_storage_file_address(self, src, ignore=None):
        # Reset the storage_file_size value
        if self.storage_file_size == None:
            self.storage_file_size = STORAGE_FILE_SIZE
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
        if(response == gtk.RESPONSE_ACCEPT):
            self.storage_file_address = fcdialog.get_filename()

        if self.storage_file_address != None:
            self.window.get_widget("storage-file-address").set_text(self.storage_file_address)

    def confirm_overwrite_callback(self, chooser):
        # Only called when the user has chosen an existing file
        self.window.get_widget("storage-file-size").set_sensitive(False)
        self.storage_file_size = None
        return gtk.FILE_CHOOSER_CONFIRMATION_ACCEPT_FILENAME
    
            
    def set_storage_type(self, button):
        if button.get_active():
            if button.name == "storage-partition":
                self.storage_method = VM_STORAGE_PARTITION
                self.window.get_widget("storage-partition-box").set_sensitive(True)
                self.window.get_widget("storage-file-box").set_sensitive(False)
            else:
                self.storage_method = VM_STORAGE_FILE
                self.window.get_widget("storage-partition-box").set_sensitive(False)
                self.window.get_widget("storage-file-box").set_sensitive(True)

    def set_storage_file_size(self, src):
        self.storage_file_size = src.get_adjustment().value

    def set_max_memory(self, src):
        self.max_memory = src.get_adjustment().value
        startup_mem_adjustment = self.window.get_widget("create-memory-startup").get_adjustment()
        if startup_mem_adjustment.value > self.max_memory:
            startup_mem_adjustment.value = self.max_memory
        startup_mem_adjustment.upper = self.max_memory

    def set_startup_memory(self, src):
        self.startup_memory = src.get_adjustment().value

    def set_vcpus(self, src):
        self.vcpus = src.get_adjustment().value

    def validate(self, page_num):
        if page_num == 1: # the system name page
            name = self.window.get_widget("create-vm-name").get_text()
            if len(name) > 50 or " " in name or len(name) == 0:
                self._validation_error_box(_("Invalid System Name"), \
                                           _("System name must be non-blank, less than 50 characters, and contain no spaces"))
                return False

        elif page_num == 2: # the virt method page
            if self.virt_method == VM_FULLY_VIRT and not xeninst.util.is_hvm_capable():
                self._validation_error_box(_("Hardware Support Required"), \
                                           _("Your hardware does not appear to support full virtualization. Only paravirtualized guests will be available on this hardware."))
                return False
            
        elif page_num == 3: # the fully virt media page
            if self.install_fv_media_type == VM_INSTALL_FROM_ISO:
                self.set_media_address(self.window.get_widget("fv-iso-location"))
                if (self.install_media_address == None or len(self.install_media_address) == 0):
                    self._validation_error_box(_("ISO Location Required"), \
                                               _("You must specify an ISO location for the guest install image"))
                    return False

        elif page_num == 4: # the paravirt media page
            self.set_media_address(self.window.get_widget("pv-media-url"))
            self.set_kickstart_address(self.window.get_widget("pv-ks-url"))
            if self.install_media_address == None or len(self.install_media_address) == 0:
                self._validation_error_box(_("URL Required"), \
                                           _("You must specify a URL for the install image for the guest install"))
                return False

        elif page_num == 5: # the storage page
            if self.window.get_widget("storage-partition").get_active():
                self.set_storage_partition_address(self.window.get_widget("storage-partition-address"))
            else:
                self.set_storage_file_address(self.window.get_widget("storage-file-address"))
                
            if (self.storage_partition_address == None or len(self.storage_partition_address) == 0) and (self.storage_file_address == None or len(self.storage_file_address) == 0):
                self._validation_error_box(_("Storage Address Required"), \
                                           _("You must specify a partition or a file for storage for the guest install"))
                return False

        # do this always, since there's no "leaving a notebook page" event.
        self.window.get_widget("create-back").set_sensitive(True)
        return True
    
    def _validation_error_box(self, text1, text2=None):
        message_box = gtk.MessageDialog(self.window.get_widget("vmm-create"), \
                                                0, \
                                                gtk.MESSAGE_ERROR, \
                                                gtk.BUTTONS_OK, \
                                                text1)
        if text2 != None:
            message_box.format_secondary_text(text2)
        message_box.run()
        message_box.destroy()

    def open_vm_console(self,ignore,uri,uuid):
        if uuid == self.vm_uuid:
            vm = self.connection.get_vm(uuid)
            (gtype, host, port) = vm.get_graphics_console()
            if gtype == "vnc":
                self.emit("action-show-console", self.connection.get_uri(), self.vm_uuid)
            else:
                self.emit("action-show-terminal", self.connection.get_uri(), self.vm_uuid)

    def _get_optical_devices(self):
        # get a list of optical devices with data discs in, for FV installs
        optical_device_list = []
        for d in self.hal_iface.FindDeviceByCapability("volume"):
            dev = self.bus.get_object("org.freedesktop.Hal", d)
            if dev.GetPropertyBoolean("volume.is_disc") and \
                   dev.GetPropertyBoolean("volume.disc.has_data") and \
                   dev.GetPropertyBoolean("volume.is_mounted"):
                optical_device_list.append(dev.GetProperty("volume.mount_point"))
        return optical_device_list
    
        

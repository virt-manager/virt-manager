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
import sys

from rhpl.exception import installExceptionHandler
from rhpl.translate import _, N_, textdomain, utf8

VM_PARAVIRT = 1
VM_FULLY_VIRT = 2

VM_INSTALL_FROM_ISO = 1
VM_INSTALL_FROM_CD = 2

VM_INSTALL_FROM_URL = 1
VM_INSTALL_FROM_KS_URL = 2

VM_STORAGE_PARTITION = 1
VM_STORAGE_FILE = 2


class vmmCreate(gobject.GObject):
    def __init__(self, config, connection):
        self.__gobject_init__()
        self.config = config
        self.connection = connection
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-create")
        self.topwin = self.window.get_widget("vmm-create")
        self.topwin.hide()
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
            "on_fv_iso_location_focus_out_event" : self.set_media_address,
            "on_pv_media_url_focus_out_event" : self.set_media_address,
            "on_pv_ks_url_focus_out_event" : self.set_media_address,
            "on_storage_partition_address_focus_out_event" : self.set_storage_address,
            "on_storage_file_address_focus_out_event" : self.set_storage_address,
            "on_storage_partition_address_browse_clicked" : self.browse_storage_partition_address,
            "on_storage_file_address_browse_clicked" : self.browse_storage_file_address,
            "on_storage_toggled" : self.set_storage_type,
            "on_storage_file_size_changed" : self.set_storage_file_size,
            "on_create_memory_max_value_changed" : self.set_max_memory,
            "on_create_memory_startup_value_changed" : self.set_startup_memory,
            "on_create_vcpus_changed" : self.set_vcpus,
            })

        self.set_initial_state()
        
    def show(self):
        self.topwin.show()

    def _init_members(self):
        #the dahta
        self.vm_name = None
        self.virt_method = VM_PARAVIRT

        # having two install-media fields is strange, but eliminates
        # some spaghetti in the UI
        self.install_fv_media_type = VM_INSTALL_FROM_ISO
        self.install_pv_media_type = VM_INSTALL_FROM_URL

        self.install_media_address = None
        self.storage_method = VM_STORAGE_PARTITION
        self.storage_address = None
        self.storage_file_size = None
        self.max_memory = 0
        self.startup_memory = 0
        self.vcpus = 1

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
            if self.vm_name != None:
                self.window.get_widget("create-vm-name").set_text(self.vm_name)
            else:
                self.window.get_widget("create-vm-name").set_text("")
                
        elif page_number == 2:
            #set up the virt method page
            if self.virt_method == VM_PARAVIRT:
                self.window.get_widget("virt-method-pv").set_active(True)
            else:
                self.window.get_widget("virt-method-fv").set_active(True)
                
        elif page_number == 3:
            #set up the fv install media page
            if self.install_fv_media_type == VM_INSTALL_FROM_ISO:
                self.window.get_widget("media-iso-image").set_active(True)
                self.window.get_widget("fv-iso-location-box").set_sensitive(True)
                if self.install_media_address != None:
                    self.window.get_widget("fv-iso-location").set_text(self.install_media_address)
                else:
                    self.window.get_widget("fv-iso-location").set_text("")
            else:
                self.window.get_widget("media-physical").set_active(True)
                self.window.get_widget("fv-iso-location-box").set_sensitive(False)
                
        elif page_number == 4:
            #set up the pv install media page
            if self.install_pv_media_type == VM_INSTALL_FROM_URL:
                self.window.get_widget("media-url-tree").set_active(True)
                self.window.get_widget("pv-media-url").set_sensitive(True)
                self.window.get_widget("pv-ks-url").set_sensitive(False)
            else:
                self.window.get_widget("media-url-ks").set_active(True)
                self.window.get_widget("pv-media-url").set_sensitive(False)
                self.window.get_widget("pv-ks-url").set_sensitive(True)
                
        elif page_number == 5:
            #set up the storage space page
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
                self.max_memory = max_mem / 2
            if self.startup_memory > self.max_memory:
                self.startup_memory = self.max_memory
                        
            max_mem_slider = self.window.get_widget("create-memory-max")
            self.window.get_widget("create-host-memory").set_text("%d MB" % max_mem)
            max_mem_slider.get_adjustment().upper = max_mem
            max_mem_slider.get_adjustment().value = self.max_memory
            startup_mem_slider = self.window.get_widget("create-memory-startup")
            startup_mem_slider.get_adjustment().upper = self.max_memory
            startup_mem_slider.get_adjustment().value = self.startup_memory

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
            
            congrats.set_text(_("Congratulations, you have successfully created a new virtual system, <b>\"%s\"</b>. \n\You'll now be able to view and work with \"%s\" in the virtual machine manager.") % (self.vm_name, self.vm_name) )
            congrats.set_use_markup(True)
            self.window.get_widget("create-forward").hide()
            self.window.get_widget("create-finish").show()
        
    def close(self, ignore1=None,ignore2=None):
        self.topwin.hide()
        return 1
    
    def finish(self, ignore=None):
        print "your vm properties: \n Name=" + self.vm_name + \
              "\n Virt method: " + `self.virt_method` + \
              "\n Install media type (fv): " + `self.install_fv_media_type` + \
              "\n Install media type (pv): " + `self.install_pv_media_type` + \
              "\n Install media address: " + self.install_media_address + \
              "\n Install storage type: " + `self.storage_method` + \
              "\n Install storage address: " + self.storage_address + \
              "\n Install storage file size: " + `self.storage_file_size/1024` + \
              "\n Install max kernel memory: " + `self.max_memory` + \
              "\n Install startup kernel memory: " + `self.startup_memory` + \
              "\n Install vcpus: " + `self.vcpus`
        
        # first things first, are we trying to create a fully virt guest?
        
        if self.virt_method == VM_FULLY_VIRT:
            guest = xeninst.FullVirtGuest()
            #XXX use HAL to get the local path for an install image
            if self.install_fv_media_type == VM_INSTALL_FROM_CD:
                self._validation_error_box(_("Installs from local CD are not yet supported"))
                return
            try:
                guest.cdrom = self.install_media_address
            except ValueError, e:
                self._validation_error_box(_("Invalid FV media address"),e.args[0])
                self.install_media_address = None
        else:
            guest = xeninst.ParaVirtGuest()
            if self.install_pv_media_type == VM_INSTALL_FROM_KS_URL:
                guest.extraargs = "ks=%s" % self.install_pv_media_type
            try:
                guest.location = self.install_media_address
            except ValueError, e:
                self._validation_error_box(_("Invalid PV media address"), e.args[0])
                self.install_media_address = None
                return

        # set the name
        try:
            guest.name = self.vm_name
        except ValueError, e:
            self._validation_error_box(_("Invalid system name"), e.args[0])
            self.vm_name = None
            return
        
        # set the memory
        try:
            guest.memory = self.max_memory
        except ValueError:
            self._validation_error_box(_("Invalid memory setting"), e.args[0])
            self.max_memory = None
            return
        
        # disks
        filesize = None
        if self.storage_file_size != None:
            filesize = int(self.storage_file_size/1024)
        try:
            d = xeninst.XenDisk(self.storage_address, filesize)
        except ValueError, e:
            self._validation_error_box(_("Invalid storage address"), e.args[0])
            self.storage_address = self.storage_file_size = None
            return
        guest.disks.append(d)

        # network
        n = xeninst.XenNetworkInterface(None)
        guest.nics.append(n)

        # let's go
        try:
            print "\n\nStarting install..."
            r = guest.start_install(True)
            print r
        except RuntimeError, e:
            print >> sys.stderr, "ERROR: ", e.args[0]
            return

        self.close()

    def set_name(self, src, ignore=None):
        self.vm_name = src.get_text()

    def set_virt_method(self, button):
        if button.get_active():
            if button.name == "virt-method-pv":
                self.virt_method = VM_PARAVIRT
            else:
                self.virt_method = VM_FULLY_VIRT

    def set_install_from(self, button):
        if button.get_active():
            if button.name == "media-iso-image":
                self.install_fv_media_type = VM_INSTALL_FROM_ISO
                self.window.get_widget("fv-iso-location-box").set_sensitive(True)
            elif button.name == "media-physical":
                self.install_fv_media_type = VM_INSTALL_FROM_CD
                self.window.get_widget("fv-iso-location-box").set_sensitive(False)
            elif button.name == "media-url-tree":
                self.install_pv_media_type = VM_INSTALL_FROM_URL
                self.window.get_widget("pv-media-url").set_sensitive(True)
                self.window.get_widget("pv-ks-url").set_sensitive(False)
            else:
                self.install_pv_media_type = VM_INSTALL_FROM_KS_URL
                self.window.get_widget("pv-media-url").set_sensitive(False)
                self.window.get_widget("pv-ks-url").set_sensitive(True)
            
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
        self.install_media_address = src.get_text()
    
    def set_storage_address(self, src, ignore=None):
        self.storage_address = src.get_text()

    def browse_storage_partition_address(self, src, ignore=None):
        self.storage_address = self._browse_file(_("Locate Storage Partition"), "/dev")
        if self.storage_address != None:
            self.window.get_widget("storage-partition-address").set_text(self.storage_address)

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
        if(response == gtk.RESPONSE_ACCEPT):
            self.storage_address = fcdialog.get_filename()

        if self.storage_address != None:
            self.window.get_widget("storage-file-address").set_text(self.storage_address)

    def confirm_overwrite_callback(self, chooser):
        # Only called when the user has chosen an existing file
        self.window.get_widget("storage-file-size").set_sensitive(False)
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
            if self.install_fv_media_type == VM_INSTALL_FROM_ISO and \
                   (self.install_media_address == None or len(self.install_media_address) == 0):
                self._validation_error_box(_("ISO Location Required"), \
                                           _("You must specify an ISO location for the guest install image"))
                return False

        elif page_num == 4: # the paravirt media page
            if self.install_media_address == None or len(self.install_media_address) == 0:
                self._validation_error_box(_("URL or Kickstart Location Required"), \
                                           _("You must specify a URL or a kickstart address for the guest install"))
                return False

        elif page_num == 5: # the storage page
            if self.storage_address == None or len(self.storage_address) == 0:
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

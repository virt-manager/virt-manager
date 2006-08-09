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

from rhpl.exception import installExceptionHandler
from rhpl.translate import _, N_, textdomain, utf8

VM_PARAVIRT = 1
VM_FULLY_VIRT = 2

VM_INSTALL_FROM_ISO = 1
VM_INSTALL_FROM_CD = 2
VM_INSTALL_FROM_URL = 3
VM_INSTALL_FROM_KS_URL = 4

VM_STORAGE_PARTITION = 1
VM_STORAGE_FILE = 2


class vmmCreate(gobject.GObject):
    def __init__(self, config):
        self.__gobject_init__()
        self.config = config
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
            "on_media_toggled" : self.set_install_from
            })

        self.set_initial_state()
        
    def show(self):
        self.topwin.show()

    def _init_members(self):
        #the dahta
        self.vm_name = ""
        self.virt_method = VM_PARAVIRT
        self.install_media_type = VM_INSTALL_FROM_ISO
        self.install_media_address = ""
        self.storage_method = VM_STORAGE_PARTITION
        self.memory = 0
        self.vcpus = 0

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

        # add code here to clear any previously set create wizard values and set
        # the buttons to the proper state

    def forward(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        # do this always, since there's no "leaving a notebook page" event.
        self.window.get_widget("create-back").set_sensitive(True)
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
        
        if page_number == 0:
            #set up the front page
            self.window.get_widget("create-back").set_sensitive(False)
        elif page_number == 1:
            #set up the system-name page
            self.window.get_widget("create-vm-name").set_text(self.vm_name)
        elif page_number == 2:
            #set up the virt method page
            if self.virt_method == VM_PARAVIRT:
                self.window.get_widget("virt-method-pv").set_active(True)
            else:
                self.window.get_widget("virt-method-fv").set_active(True)
        elif page_number == 3:
            #set up the fv install media page
            if self.install_media_type != VM_INSTALL_FROM_ISO and \
               self.install_media_type != VM_INSTALL_FROM_CD:
                self.install_media_type = VM_INSTALL_FROM_ISO
            if self.install_media_type == VM_INSTALL_FROM_ISO:
                self.window.get_widget("media-iso-image").set_active(True)
            else:
                self.window.get_widget("media-physical").set_active(True)
        elif page_number == 4:
            #set up the pv install media page
            if self.install_media_type != VM_INSTALL_FROM_URL and \
               self.install_media_type != VM_INSTALL_FROM_KS_URL:
                self.install_media_type = VM_INSTALL_FROM_URL
            if self.install_media_type == VM_INSTALL_FROM_URL:
                self.window.get_widget("media-url-tree").set_active(True)
            else:
                self.window.get_widget("media-url-ks").set_active(True)
        elif page_number == 5:
            #set up the storage space page
            print "loaded storage space page"
        elif page_number == 6:
            #set up the CPU and Memory page
            # if the user went backwards
            print "loaded cpu/memory page"
        elif page_number == 7:
            #set up the congrats page
            self.window.get_widget("create-forward").hide()
            self.window.get_widget("create-finish").show()
        
    def close(self, ignore1=None,ignore2=None):
        self.topwin.hide()
        return 1
    
    def finish(self, ignore=None):
        print "your vm properties: \n Name=" + self.vm_name + \
              "\n Virt method: " + `self.virt_method` + \
              "\n Install media type: " + `self.install_media_type`
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
                self.install_media_type = VM_INSTALL_FROM_ISO
                self.window.get_widget("fv-iso-location").set_sensitive(True)
            elif button.name == "media-physical":
                self.install_media_type = VM_INSTALL_FROM_CD
                self.window.get_widget("fv-iso-location").set_sensitive(False)
            elif button.name == "media-url-tree":
                self.install_media_type = VM_INSTALL_FROM_URL
                self.window.get_widget("pv-media-url").set_sensitive(True)
                self.window.get_widget("pv-ks-url").set_sensitive(False)
            else:
                self.install_media_type = VM_INSTALL_FROM_KS_URL
                self.window.get_widget("pv-media-url").set_sensitive(False)
                self.window.get_widget("pv-ks-url").set_sensitive(True)
            

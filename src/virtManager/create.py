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
import pango
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

VM_PARA_VIRT = 1
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
            "on_fv_iso_location_browse_clicked" : self.browse_iso_location,
            "on_create_memory_max_value_changed": self.set_max_memory,
            "on_storage_partition_address_browse_clicked" : self.browse_storage_partition_address,
            "on_storage_file_address_browse_clicked" : self.browse_storage_file_address,
            "on_storage_file_address_changed": self.toggle_storage_size,
            "on_storage_toggled" : self.change_storage_type,
            "on_media_toggled" : self.change_media_type,
            "on_pv_media_url_changed" : self.change_combo_box,
            "on_pv_ks_url_changed" : self.change_combo_box,
            })
        self.set_initial_state()

    def show(self):
        self.topwin.show()
        self.reset_state()
        self.topwin.present()

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
        cd_list = self.window.get_widget("cd-path")
        # Fields are raw device path, volume label, flag indicating
        # whether volume is present or not, and HAL path
        cd_model = gtk.ListStore(str, str, bool, str)
        cd_list.set_model(cd_model)
        text = gtk.CellRendererText()
        cd_list.pack_start(text, True)
        cd_list.add_attribute(text, 'text', 1)
        cd_list.add_attribute(text, 'sensitive', 2)
        self.populate_opt_media(cd_model)

        # set up the lists for the url widgets
        media_url_list = self.window.get_widget("pv-media-url")
        media_url_model = gtk.ListStore(str)
        media_url_list.set_model(media_url_model)
        media_url_list.set_text_column(0)

        ks_url_list = self.window.get_widget("pv-ks-url")
        ks_url_model = gtk.ListStore(str)
        ks_url_list.set_model(ks_url_model)
        ks_url_list.set_text_column(0)

        self.window.get_widget("create-cpus-physical").set_text(str(self.connection.host_maximum_processor_count()))

    def reset_state(self):
        notebook = self.window.get_widget("create-pages")
        notebook.set_current_page(0)
        # Hide the "finish" button until the appropriate time
        self.window.get_widget("create-finish").hide()
        self.window.get_widget("create-forward").show()
        self.window.get_widget("create-back").set_sensitive(False)
        self.window.get_widget("storage-file-size").set_sensitive(False)

        self.change_media_type()
        self.change_storage_type()
        self.window.get_widget("create-vm-name").set_text("")
        self.window.get_widget("virt-method-pv").set_active(True)
        self.window.get_widget("media-iso-image").set_active(True)
        self.window.get_widget("fv-iso-location").set_text("")
        self.window.get_widget("storage-partition").set_active(True)
        self.window.get_widget("storage-partition-address").set_text("")
        self.window.get_widget("storage-file-address").set_text("")
        self.window.get_widget("storage-file-size").set_value(2000)
        self.window.get_widget("create-memory-max").set_value(500)
        self.window.get_widget("create-memory-startup").set_value(500)
        self.window.get_widget("create-vcpus").set_value(1)
        model = self.window.get_widget("pv-media-url").get_model()
        self.populate_url_model(model, self.config.get_media_urls())
        model = self.window.get_widget("pv-ks-url").get_model()
        self.populate_url_model(model, self.config.get_kickstart_urls())

        self.install_error = None


    def forward(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        if(self.validate(notebook.get_current_page()) != True):
            return

        if notebook.get_current_page() == 1 and not xeninst.util.is_hvm_capable():
            notebook.set_current_page(4)
        elif (notebook.get_current_page() == 2 and self.get_config_method() == VM_PARA_VIRT):
            notebook.set_current_page(4)
        elif (notebook.get_current_page() == 3 and self.get_config_method() == VM_FULLY_VIRT):
            notebook.set_current_page(5)
        else:
            notebook.next_page()

    def back(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        # do this always, since there's no "leaving a notebook page" event.
        self.window.get_widget("create-finish").hide()
        self.window.get_widget("create-forward").show()
        if notebook.get_current_page() == 4 and self.get_config_method() == VM_PARA_VIRT:
            if xeninst.util.is_hvm_capable():
                notebook.set_current_page(2)
            else:
                notebook.set_current_page(1)
        elif notebook.get_current_page() == 5 and self.get_config_method() == VM_FULLY_VIRT:
            notebook.set_current_page(3)
        else:
            notebook.prev_page()

    def get_config_name(self):
        return self.window.get_widget("create-vm-name").get_text()

    def get_config_method(self):
        if self.window.get_widget("virt-method-pv").get_active():
            return VM_PARA_VIRT
        elif self.window.get_widget("virt-method-fv").get_active():
            return VM_FULLY_VIRT
        else:
            return VM_PARA_VIRT

    def get_config_install_source(self):
        if self.get_config_method() == VM_PARA_VIRT:
            widget = self.window.get_widget("pv-media-url")
            url= widget.child.get_text()
            # Add the URL to the list, if it's different
            self.config.add_media_url(url)
            self.populate_url_model(widget.get_model(), self.config.get_media_urls())
            return url
        else:
            if self.window.get_widget("media-iso-image").get_active():
                return self.window.get_widget("fv-iso-location").get_text()
            else:
                cd = self.window.get_widget("cd-path")
                model = cd.get_model()
                return model.get_value(cd.get_active_iter(), 0)

    def get_config_kickstart_source(self):
        if self.get_config_method() == VM_PARA_VIRT:
            widget = self.window.get_widget("pv-ks-url")
            url = widget.child.get_text()
            self.config.add_kickstart_url(url)
            self.populate_url_model(widget.get_model(), self.config.get_kickstart_urls())
            return url
        else:
            return ""

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

    def get_config_maximum_memory(self):
        return self.window.get_widget("create-memory-max").get_value()

    def get_config_initial_memory(self):
        return self.window.get_widget("create-memory-startup").get_value()

    def get_config_virtual_cpus(self):
        return self.window.get_widget("create-vcpus").get_value()

    def page_changed(self, notebook, page, page_number):
        # would you like some spaghetti with your salad, sir?

        if page_number == 0:
            self.window.get_widget("create-back").set_sensitive(False)
        elif page_number == 1:
            name_widget = self.window.get_widget("create-vm-name")
            name_widget.grab_focus()
        elif page_number == 2:
            #set up the virt method page
            pass
        elif page_number == 3:
            #set up the fv install media page
            pass
        elif page_number == 4:
            #set up the pv install media page
            url_widget = self.window.get_widget("pv-media-url")
            url_widget.grab_focus()
        elif page_number == 5:
            #set up the storage space page
            partwidget = self.window.get_widget("storage-partition-address")
            filewidget = self.window.get_widget("storage-file-address")
        elif page_number == 6:
            # memory stuff
            pass
        elif page_number == 7:
            self.window.get_widget("summary-name").set_text(self.get_config_name())
            if self.get_config_method() == VM_PARA_VIRT:
                self.window.get_widget("summary-method").set_text(_("Paravirtualized"))
            else:
                self.window.get_widget("summary-method").set_text(_("Fully virtualized"))
            self.window.get_widget("summary-install-source").set_text(self.get_config_install_source())
            self.window.get_widget("summary-kickstart-source").set_text(self.get_config_kickstart_source())
            self.window.get_widget("summary-disk-image").set_text(self.get_config_disk_image())
            disksize = self.get_config_disk_size()
            if disksize != None:
                self.window.get_widget("summary-disk-size").set_text(str(int(disksize)) + " MB")
            else:
                self.window.get_widget("summary-disk-size").set_text("-")
            self.window.get_widget("summary-max-memory").set_text(str(int(self.get_config_maximum_memory())) + " MB")
            self.window.get_widget("summary-initial-memory").set_text(str(int(self.get_config_initial_memory())) + " MB")
            self.window.get_widget("summary-virtual-cpus").set_text(str(int(self.get_config_virtual_cpus())))
            self.window.get_widget("create-forward").hide()
            self.window.get_widget("create-finish").show()

    def close(self, ignore1=None,ignore2=None):
        self.topwin.hide()
        return 1

    def finish(self, ignore=None):
        # first things first, are we trying to create a fully virt guest?
        if self.get_config_method() == VM_FULLY_VIRT:
            guest = xeninst.FullVirtGuest()
            try:
                guest.cdrom = self.get_config_install_source()
            except ValueError, e:
                self._validation_error_box(_("Invalid FV media address"),e.args[0])
        else:
            guest = xeninst.ParaVirtGuest()
            try:
                guest.location = self.get_config_install_source()
            except ValueError, e:
                self._validation_error_box(_("Invalid PV media address"), e.args[0])
                return
            ks = self.get_config_kickstart_source()
            if ks != None and len(ks) != 0:
                guest.extraargs = "ks=%s" % ks

        # set the name
        try:
            guest.name = self.get_config_name()
        except ValueError, e:
            self._validation_error_box(_("Invalid system name"), e.args[0])
            return

        # set the memory
        try:
            guest.memory = int(self.get_config_maximum_memory())
        except ValueError:
            self._validation_error_box(_("Invalid memory setting"), e.args[0])
            return

        # set vcpus
        guest.vcpus = int(self.get_config_virtual_cpus())

        # disks
        filesize = None
        if self.get_config_disk_size() != None:
            filesize = self.get_config_disk_size() / 1024.0
        try:
            d = xeninst.XenDisk(self.get_config_disk_image(), filesize)
            if d.type == xeninst.XenDisk.TYPE_FILE and \
                   self.get_config_method() == VM_PARA_VIRT \
                   and xeninst.util.is_blktap_capable():
                d.driver_name = xeninst.XenDisk.DRIVER_TAP
        except ValueError, e:
            self._validation_error_box(_("Invalid storage address"), e.args[0])
            return
        guest.disks.append(d)

        # uuid
        guest.uuid = xeninst.util.uuidToString(xeninst.util.randomUUID())

        # network
        n = xeninst.XenNetworkInterface(None)
        guest.nics.append(n)

        # set up the graphics to use SDL
        guest.graphics = "vnc"

        logging.debug("Creating a VM " + guest.name + \
                      "\n  UUID: " + guest.uuid + \
                      "\n  Source: " + self.get_config_install_source() + \
                      "\n  Kickstart: " + self.get_config_kickstart_source() + \
                      "\n  Memory: " + str(guest.memory) + \
                      "\n  # VCPUs: " + str(guest.vcpus) + \
                      "\n  Filesize: " + str(filesize) + \
                      "\n  Disk image: " + str(self.get_config_disk_image()))

        #let's go
        self.install_error = None
        progWin = vmmAsyncJob(self.config, self.do_install, [guest],
                              title=_("Creating Virtual Machine"))
        progWin.run()
        if self.install_error != None:
            logging.error("Async job failed to create VM " + str(self.install_error))
            self._validation_error_box(_("Guest Install Error"), self.install_error)
            # Don't close becase we allow user to go back in wizard & correct
            # their mistakes
            #self.close()
            return

        # Ensure new VM is loaded
        self.connection.tick(noStatsUpdate=True)

        vm = self.connection.get_vm(guest.uuid)
        (gtype, host, port) = vm.get_graphics_console()
        if gtype == "vnc":
            self.emit("action-show-console", self.connection.get_uri(), guest.uuid)
        else:
            self.emit("action-show-terminal", self.connection.get_uri(), guest.uuid)
        self.close()

    def do_install(self, guest):
        try:
            logging.debug("Starting background install process")
            dom = guest.start_install(False)
            if dom == None:
                self.install_error = "Guest installation failed to complete"
                logging.error("Guest install did not return a domain")
            else:
                logging.debug("Install completed")
        except Exception, e:
            self.install_error = "ERROR: %s" % e
            logging.exception("Could not complete install " + str(e))
            return

    def browse_iso_location(self, ignore1=None, ignore2=None):
        file = self._browse_file(_("Locate ISO Image"), type="iso")
        if file != None:
            self.window.get_widget("fv-iso-location").set_text(file)

    def _browse_file(self, dialog_name, folder=None, type=None):
        # user wants to browse for an ISO
        fcdialog = gtk.FileChooserDialog(dialog_name,
                                         self.window.get_widget("vmm-create"),
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
        else:
            self.window.get_widget("storage-file-size").set_sensitive(False)

    def confirm_overwrite_callback(self, chooser):
        # Only called when the user has chosen an existing file
        self.window.get_widget("storage-file-size").set_sensitive(False)
        return gtk.FILE_CHOOSER_CONFIRMATION_ACCEPT_FILENAME

    def change_media_type(self, ignore=None):
        if self.window.get_widget("media-iso-image").get_active():
            self.window.get_widget("fv-iso-location-box").set_sensitive(True)
            self.window.get_widget("cd-path").set_sensitive(False)
        else:
            self.window.get_widget("fv-iso-location-box").set_sensitive(False)
            self.window.get_widget("cd-path").set_sensitive(True)
            self.window.get_widget("cd-path").set_active(-1)

    def change_storage_type(self, ignore=None):
        if self.window.get_widget("storage-partition").get_active():
            self.window.get_widget("storage-partition-box").set_sensitive(True)
            self.window.get_widget("storage-file-box").set_sensitive(False)
            self.window.get_widget("storage-file-size").set_sensitive(False)
        else:
            self.window.get_widget("storage-partition-box").set_sensitive(False)
            self.window.get_widget("storage-file-box").set_sensitive(True)
            self.toggle_storage_size()

    def set_max_memory(self, src):
        max_memory = src.get_adjustment().value
        startup_mem_adjustment = self.window.get_widget("create-memory-startup").get_adjustment()
        if startup_mem_adjustment.value > max_memory:
            startup_mem_adjustment.value = max_memory
        startup_mem_adjustment.upper = max_memory

    def validate(self, page_num):
        if page_num == 1: # the system name page
            name = self.window.get_widget("create-vm-name").get_text()
            if len(name) > 50 or " " in name or len(name) == 0:
                self._validation_error_box(_("Invalid System Name"), \
                                           _("System name must be non-blank, less than 50 characters, and contain no spaces"))
                return False

        elif page_num == 2: # the virt method page
            if self.get_config_method() == VM_FULLY_VIRT and not xeninst.util.is_hvm_capable():
                self._validation_error_box(_("Hardware Support Required"), \
                                           _("Your hardware does not appear to support full virtualization. Only paravirtualized guests will be available on this hardware."))
                return False

        elif page_num == 3: # the fully virt media page
            if self.window.get_widget("media-iso-image").get_active():
                src = self.get_config_install_source()
                if src == None or len(src) == 0:
                    self._validation_error_box(_("ISO Path Required"), \
                                               _("You must specify an ISO location for the guest installation"))
                    return False
                elif not(os.path.exists(src)):
                    self._validation_error_box(_("ISO Path Not Found"), \
                                               _("You must specify a valid path to the ISO image for guest installation"))
                    return False
            else:
                cdlist = self.window.get_widget("cd-path")
                if cdlist.get_active() == -1:
                    self._validation_error_box(_("Install media required"), \
                                               _("You must select the CDROM install media for guest installation"))
                    return False
        elif page_num == 4: # the paravirt media page
            src = self.get_config_install_source()
            if src == None or len(src) == 0:
                self._validation_error_box(_("URL Required"), \
                                           _("You must specify a URL for the install image for the guest install"))
                return False

        elif page_num == 5: # the storage page
            disk = self.get_config_disk_image()
            if disk == None or len(disk) == 0:
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

    def populate_opt_media(self, model):
        # get a list of optical devices with data discs in, for FV installs
        vollabel = {}
        volpath = {}
        # Track device add/removes so we can detect newly inserted CD media
        self.hal_iface.connect_to_signal("DeviceAdded", self._device_added)
        self.hal_iface.connect_to_signal("DeviceRemoved", self._device_removed)

        # Find info about all current present media
        for d in self.hal_iface.FindDeviceByCapability("volume"):
            vol = self.bus.get_object("org.freedesktop.Hal", d)
            if vol.GetPropertyBoolean("volume.is_disc") and \
                   vol.GetPropertyBoolean("volume.disc.has_data"):
                devnode = vol.GetProperty("block.device")
                label = vol.GetProperty("volume.label")
                if label == None or len(label) == 0:
                    label = devnode
                vollabel[devnode] = label
                volpath[devnode] = d


        for d in self.hal_iface.FindDeviceByCapability("storage.cdrom"):
            dev = self.bus.get_object("org.freedesktop.Hal", d)
            devnode = dev.GetProperty("block.device")
            if vollabel.has_key(devnode):
                model.append([devnode, vollabel[devnode], True, volpath[devnode]])
            else:
                model.append([devnode, _("No media present"), False, None])

    def _device_added(self, path):
        vol = self.bus.get_object("org.freedesktop.Hal", path)
        if vol.QueryCapability("volume"):
            if vol.GetPropertyBoolean("volume.is_disc") and \
                   vol.GetPropertyBoolean("volume.disc.has_data"):
                devnode = vol.GetProperty("block.device")
                label = vol.GetProperty("volume.label")
                if label == None or len(label) == 0:
                    label = devnode

                cdlist = self.window.get_widget("cd-path")
                model = cdlist.get_model()

                # Search for the row with matching device node and
                # fill in info about inserted media
                for row in model:
                    if row[0] == devnode:
                        row[1] = label
                        row[2] = True
                        row[3] = path

    def _device_removed(self, path):
        vol = self.bus.get_object("org.freedesktop.Hal", path)
        cdlist = self.window.get_widget("cd-path")
        model = cdlist.get_model()

        active = cdlist.get_active()
        idx = 0
        # Search for the row containing matching HAL volume path
        # and update (clear) it, de-activating it if its currently
        # selected
        for row in model:
            if row[3] == path:
                row[1] = _("No media present")
                row[2] = False
                row[3] = None
                if idx == active:
                    cdlist.set_active(-1)
            idx = idx + 1

    def populate_url_model(self, model, urls):
        model.clear()
        for url in urls:
            model.append([url])
        
    def change_combo_box(self, box):
        model = box.get_model()
        try:
            box.child.set_text(model.get_value(box.get_active_iter(), 0))
        except TypeError, e:
            # pygtk throws a bogus type error here, ignore it
            return
        
                           

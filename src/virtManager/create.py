#
# Copyright (C) 2006, 2008 Red Hat, Inc.
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.
#

import gobject
import gtk
import gtk.gdk
import gtk.glade
import pango
import libvirt
import virtinst
import os, sys
import statvfs
import re
import subprocess
import urlgrabber.progress as progress
import tempfile
import logging
import dbus
import traceback

from virtManager.asyncjob import vmmAsyncJob
from virtManager.error import vmmErrorDialog
from virtManager.createmeter import vmmCreateMeter
from virtManager.opticalhelper import vmmOpticalDriveHelper

VM_PARA_VIRT = 1
VM_FULLY_VIRT = 2

VM_INSTALL_FROM_ISO = 1
VM_INSTALL_FROM_CD = 2

VM_STORAGE_PARTITION = 1
VM_STORAGE_FILE = 2

VM_INST_LOCAL = 1
VM_INST_TREE = 2
VM_INST_PXE = 3

DEFAULT_STORAGE_FILE_SIZE = 500

PAGE_INTRO = 0
PAGE_NAME = 1
PAGE_TYPE = 2
PAGE_INST = 3
PAGE_INST_LOCAL = 4
PAGE_INST_TREE = 5
PAGE_DISK = 6
PAGE_NETWORK = 7
PAGE_CPUMEM = 8
PAGE_SUMMARY = 9

class vmmCreate(gobject.GObject):
    __gsignals__ = {
        "action-show-console": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-terminal": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, [str]),
        }
    def __init__(self, config, connection):
        self.__gobject_init__()
        self.config = config
        self.connection = connection
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-create.glade", "vmm-create", domain="virt-manager")
        self.topwin = self.window.get_widget("vmm-create")
        self.err = vmmErrorDialog(self.topwin,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))
        self.topwin.hide()
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
            "on_network_toggled" : self.change_network_type,
            "on_mac_address_clicked" : self.change_macaddr_use,
            "on_media_toggled" : self.change_media_type,
            "on_os_type_changed" : self.change_os_type,
            "on_cpu_architecture_changed": self.change_cpu_arch,
            "on_virt_method_toggled": self.change_virt_method,
            "on_create_help_clicked": self.show_help,
            })

        self.caps = self.connection.get_capabilities()
        self.set_initial_state()

        # Guest to fill in with values along the way
        self._guest = virtinst.Guest(type=self.get_domain_type(),
                                     connection=self.connection.vmm,
                                     hypervisorURI=self.connection.get_uri())
        self._disk = None
        self._net = None

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
        for num in range(PAGE_SUMMARY+1):
            name = "page" + str(num) + "-title"
            self.window.get_widget(name).modify_bg(gtk.STATE_NORMAL,black)

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
        try:
            self.optical_helper = vmmOpticalDriveHelper(self.window.get_widget("cd-path"))
            self.window.get_widget("media-physical").set_sensitive(True)
        except Exception, e:
            logging.error("Unable to create optical-helper widget: '%s'", e)
            self.window.get_widget("media-physical").set_sensitive(False)

        self.window.get_widget("media-physical").set_sensitive(True)
        self.window.get_widget("storage-partition").set_sensitive(True)

        # set up the lists for the url widgets
        media_url_list = self.window.get_widget("pv-media-url")
        media_url_model = gtk.ListStore(str)
        media_url_list.set_model(media_url_model)
        media_url_list.set_text_column(0)

        ks_url_list = self.window.get_widget("pv-ks-url")
        ks_url_model = gtk.ListStore(str)
        ks_url_list.set_model(ks_url_model)
        ks_url_list.set_text_column(0)

        # set up the lists for the networks
        network_list = self.window.get_widget("net-network")
        network_model = gtk.ListStore(str, str)
        network_list.set_model(network_model)
        text = gtk.CellRendererText()
        network_list.pack_start(text, True)
        network_list.add_attribute(text, 'text', 1)

        device_list = self.window.get_widget("net-device")
        device_model = gtk.ListStore(str, str, bool)
        device_list.set_model(device_model)
        text = gtk.CellRendererText()
        device_list.pack_start(text, True)
        device_list.add_attribute(text, 'text', 1)
        device_list.add_attribute(text, 'sensitive', 2)

        # set up the lists for the os-type/os-variant widgets
        os_type_list = self.window.get_widget("os-type")
        os_type_model = gtk.ListStore(str, str)
        os_type_list.set_model(os_type_model)
        text = gtk.CellRendererText()
        os_type_list.pack_start(text, True)
        os_type_list.add_attribute(text, 'text', 1)

        os_variant_list = self.window.get_widget("os-variant")
        os_variant_model = gtk.ListStore(str, str)
        os_variant_list.set_model(os_variant_model)
        text = gtk.CellRendererText()
        os_variant_list.pack_start(text, True)
        os_variant_list.add_attribute(text, 'text', 1)

        self.window.get_widget("create-cpus-physical").set_text(str(self.connection.host_maximum_processor_count()))
        memory = int(self.connection.host_memory_size())
        self.window.get_widget("create-host-memory").set_text(self.pretty_memory(memory))
        self.window.get_widget("create-memory-max").set_range(50, memory/1024)

        archModel = gtk.ListStore(str)
        archList = self.window.get_widget("cpu-architecture")
        archList.set_model(archModel)

        hyperModel = gtk.ListStore(str)
        hyperList = self.window.get_widget("hypervisor")
        hyperList.set_model(hyperModel)

    def reset_state(self):
        notebook = self.window.get_widget("create-pages")
        notebook.set_current_page(0)
        # Hide the "finish" button until the appropriate time
        self.window.get_widget("create-finish").hide()
        self.window.get_widget("create-forward").show()
        self.window.get_widget("create-back").set_sensitive(False)
        self.window.get_widget("storage-file-size").set_sensitive(False)

        # If we don't have full-virt support disable the choice, and
        # display a message telling the user why it is not working
        has_pv = False
        has_fv = False

        for guest in self.caps.guests:
            if guest.os_type in ["xen", "linux"]:
                has_pv = True
            elif guest.os_type == "hvm":
                has_fv = True

        self.window.get_widget("virt-method-pv").set_sensitive(has_pv)
        self.window.get_widget("virt-method-fv").set_sensitive(has_fv)

        # prioritize pv if the option is available?
        self.window.get_widget("virt-method-fv").set_active(has_fv)
        self.window.get_widget("virt-method-pv").set_active(has_pv)
        self.change_virt_method() # repopulate arch and hypervisor lists

        if has_fv:
            self.window.get_widget("virt-method-fv-unsupported").hide()
            self.window.get_widget("virt-method-fv-disabled").hide()
        else:
            self.window.get_widget("virt-method-fv-unsupported").show()
            flags = self.caps.host.features.names()
            if "vmx" in flags or "svm" in flags:
                self.window.get_widget("virt-method-fv-disabled").show()
            else:
                self.window.get_widget("virt-method-fv-disabled").hide()


        self.change_media_type()
        self.change_storage_type()
        self.change_network_type()
        self.change_macaddr_use()
        self.window.get_widget("create-vm-name").set_text("")
        self.window.get_widget("media-iso-image").set_active(True)
        self.window.get_widget("fv-iso-location").set_text("")
        self.window.get_widget("storage-file-backed").set_active(True)
        self.window.get_widget("storage-partition-address").set_text("")
        self.window.get_widget("storage-file-address").set_text("")
        self.window.get_widget("storage-file-size").set_value(2000)
        self.window.get_widget("create-memory-max").set_value(512)
        self.window.get_widget("create-memory-startup").set_value(512)
        self.window.get_widget("create-vcpus").set_value(1)
        self.window.get_widget("create-vcpus").get_adjustment().upper = self.connection.get_max_vcpus()
        self.window.get_widget("non-sparse").set_active(True)
        model = self.window.get_widget("pv-media-url").get_model()
        self.populate_url_model(model, self.config.get_media_urls())
        model = self.window.get_widget("pv-ks-url").get_model()
        self.populate_url_model(model, self.config.get_kickstart_urls())

        # Fill list of OS types
        self.populate_os_type_model()
        self.window.get_widget("os-type").set_active(0)

        self.window.get_widget("net-type-network").set_active(True)
        self.window.get_widget("net-type-device").set_active(False)
        self.window.get_widget("mac-address").set_active(False)
        self.window.get_widget("create-mac-address").set_text("")

        net_box = self.window.get_widget("net-network")
        self.populate_network_model(net_box.get_model())
        net_box.set_active(0)

        dev_box = self.window.get_widget("net-device")
        res = self.populate_device_model(dev_box.get_model())
        if res[0]:
            dev_box.set_active(res[1])
        else:
            dev_box.set_active(-1)

        self.install_error = None


    def forward(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        try:
            if(self.validate(notebook.get_current_page()) != True):
                return
        except Exception, e:
            self.err.show_err(_("Uncaught error validating input: %s") % str(e),
                              "".join(traceback.format_exc()))
            return

        if notebook.get_current_page() == PAGE_INST:
            if self.get_config_install_method() == VM_INST_LOCAL:
                notebook.set_current_page(PAGE_INST_LOCAL)
            elif self.get_config_install_method() == VM_INST_TREE:
                notebook.set_current_page(PAGE_INST_TREE)
            else:
                # No config for PXE needed (yet)
                notebook.set_current_page(PAGE_DISK)
        elif notebook.get_current_page() in [PAGE_INST_TREE, PAGE_INST_LOCAL]:
            notebook.set_current_page(PAGE_DISK)
        elif notebook.get_current_page() == PAGE_DISK and self.connection.get_uri() == "qemu:///session":
            # Skip network for non-root
            notebook.set_current_page(PAGE_CPUMEM)
        else:
            notebook.next_page()

    def back(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        # do this always, since there's no "leaving a notebook page" event.
        self.window.get_widget("create-finish").hide()
        self.window.get_widget("create-forward").show()
        if notebook.get_current_page() in [PAGE_INST_TREE, PAGE_INST_LOCAL]:
            notebook.set_current_page(PAGE_INST)
        elif notebook.get_current_page() == PAGE_DISK:
            if self.get_config_install_method() == VM_INST_LOCAL:
                notebook.set_current_page(PAGE_INST_LOCAL)
            elif self.get_config_install_method() == VM_INST_TREE:
                notebook.set_current_page(PAGE_INST_TREE)
            else:
                # No config for PXE needed (yet)
                notebook.set_current_page(PAGE_INST)
        elif notebook.get_current_page() == PAGE_CPUMEM and self.connection.get_uri() == "qemu:///session":
            # Skip network for non-root
            notebook.set_current_page(PAGE_DISK)
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
        if self.get_config_install_method() == VM_INST_TREE:
            widget = self.window.get_widget("pv-media-url")
            url= widget.child.get_text().strip()
            # Add the URL to the list, if it's different
            self.config.add_media_url(url)
            self.populate_url_model(widget.get_model(), self.config.get_media_urls())
            return url
        elif self.get_config_install_method() == VM_INST_LOCAL:
            if self.window.get_widget("media-iso-image").get_active():
                return self.window.get_widget("fv-iso-location").get_text()
            else:
                return self.window.get_widget("cd-path").get_active_text()
        else:
            return "PXE"

    def get_config_installer(self, type, os_type):
        if self.get_config_install_method() == VM_INST_PXE:
            return virtinst.PXEInstaller(type = type, os_type = os_type)
        else:
            return virtinst.DistroInstaller(type = type, os_type = os_type)

    def get_config_kickstart_source(self):
        if self.get_config_install_method() == VM_INST_TREE:
            widget = self.window.get_widget("pv-ks-url")
            url = widget.child.get_text().strip()
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
        if not self.window.get_widget("storage-file-backed").get_active():
            return None
        if not self.window.get_widget("storage-file-size").get_editable():
            return None
        else:
            return self.window.get_widget("storage-file-size").get_value()
    
    def get_config_kernel_params(self):
	return self.window.get_widget("kernel-params").get_text()

    def get_config_network(self):
        if self.connection.get_uri() == "qemu:///session":
            return ["user"]

        if self.window.get_widget("net-type-network").get_active():
            net = self.window.get_widget("net-network")
            model = net.get_model()
            return ["network", model.get_value(net.get_active_iter(), 0)]
        else:
            dev = self.window.get_widget("net-device")
            model = dev.get_model()
            return ["bridge", model.get_value(dev.get_active_iter(), 0)]

    def get_config_macaddr(self):
        macaddr = None
        if self.window.get_widget("mac-address").get_active():
            macaddr = self.window.get_widget("create-mac-address").get_text()
        return macaddr

    def get_config_maximum_memory(self):
        return self.window.get_widget("create-memory-max").get_value()

    def get_config_initial_memory(self):
        return self.window.get_widget("create-memory-startup").get_value()

    def get_config_virtual_cpus(self):
        return self.window.get_widget("create-vcpus").get_value()

    def get_config_install_method(self):
        if self.window.get_widget("method-local").get_active():
            return VM_INST_LOCAL
        elif self.window.get_widget("method-tree").get_active():
            return VM_INST_TREE
        else:
            return VM_INST_PXE

    def get_config_os_type(self):
        type = self.window.get_widget("os-type")
        if type.get_active_iter() != None:
            return type.get_model().get_value(type.get_active_iter(), 0)
        return None

    def get_config_os_variant(self):
        variant = self.window.get_widget("os-variant")
        if variant.get_active_iter() != None:
            return variant.get_model().get_value(variant.get_active_iter(), 0)
        return None

    def get_config_os_label(self):
        variant = self.window.get_widget("os-variant")
        if variant.get_active_iter() != None:
            return variant.get_model().get_value(variant.get_active_iter(), 1)

        type = self.window.get_widget("os-type")
        if type.get_active_iter() != None:
            return type.get_model().get_value(type.get_active_iter(), 1)
        return "N/A"

    def page_changed(self, notebook, page, page_number):
        # would you like some spaghetti with your salad, sir?

        if page_number == PAGE_INTRO:
            self.window.get_widget("create-back").set_sensitive(False)
        elif page_number == PAGE_NAME:
            name_widget = self.window.get_widget("create-vm-name")
            name_widget.grab_focus()
        elif page_number == PAGE_TYPE:
            pass
        elif page_number == PAGE_INST:
            if self.get_config_method() == VM_PARA_VIRT:
                # Xen can't PXE or CDROM install :-(
                self.window.get_widget("method-local").set_sensitive(False)
                self.window.get_widget("method-pxe").set_sensitive(False)
                self.window.get_widget("method-tree").set_active(True)
            else:
                self.window.get_widget("method-local").set_sensitive(True)
                self.window.get_widget("method-pxe").set_sensitive(True)
        elif page_number == PAGE_INST_TREE:
            url_widget = self.window.get_widget("pv-media-url")
            url_widget.grab_focus()
        elif page_number == PAGE_INST_LOCAL:
            url_widget = self.window.get_widget("pv-media-url")
            url_widget.grab_focus()
        elif page_number == PAGE_DISK:
            self.change_storage_type()
        elif page_number == PAGE_NETWORK:
            pass
        elif page_number == PAGE_CPUMEM:
            pass
        elif page_number == PAGE_SUMMARY:
            self.window.get_widget("summary-name").set_text(self.get_config_name())
            if self.get_config_method() == VM_PARA_VIRT:
                self.window.get_widget("summary-method").set_text(_("Paravirtualized"))
                self.window.get_widget("summary-os-label").hide()
                self.window.get_widget("summary-os").hide()
            else:
                self.window.get_widget("summary-method").set_text(_("Fully virtualized"))
                self.window.get_widget("summary-os-label").show()
                self.window.get_widget("summary-os").set_text(self.get_config_os_label())
                self.window.get_widget("summary-os").show()
            self.window.get_widget("summary-install-source").set_text(self.get_config_install_source())
            self.window.get_widget("summary-kickstart-source").set_text(self.get_config_kickstart_source())
            if self._guest.extraargs is None:
                self.window.get_widget("summary-kernel-args-label").hide()
                self.window.get_widget("summary-kernel-args").hide()
            else:
                self.window.get_widget("summary-kernel-args-label").show()
                self.window.get_widget("summary-kernel-args").show()
                self.window.get_widget("summary-kernel-args").set_text(self._guest.extraargs)
            self.window.get_widget("summary-disk-image").set_text(self.get_config_disk_image())
            disksize = self.get_config_disk_size()
            if disksize != None:
                self.window.get_widget("summary-disk-size").set_text(str(int(disksize)) + " MB")
            else:
                self.window.get_widget("summary-disk-size").set_text("-")
            self.window.get_widget("summary-max-memory").set_text(str(int(self.get_config_maximum_memory())) + " MB")
            self.window.get_widget("summary-initial-memory").set_text(str(int(self.get_config_initial_memory())) + " MB")
            self.window.get_widget("summary-virtual-cpus").set_text(str(int(self.get_config_virtual_cpus())))
            net = self.get_config_network()
            if net[0] == "bridge":
                self.window.get_widget("summary-net-type").set_text(_("Shared physical device"))
                self.window.get_widget("summary-net-target").set_text(net[1])
            elif net[0] == "network":
                self.window.get_widget("summary-net-type").set_text(_("Virtual network"))
                self.window.get_widget("summary-net-target").set_text(net[1])
            elif net[0] == "user":
                self.window.get_widget("summary-net-type").set_text(_("Usermode networking"))
                self.window.get_widget("summary-net-target").set_text("-")
            else:
                raise ValueError, "Unknown networking type " + net[0]
            macaddr = self.get_config_macaddr()
            if macaddr != None:
                self.window.get_widget("summary-mac-address").set_text(macaddr)
            else:
                self.window.get_widget("summary-mac-address").set_text("-")

            self.window.get_widget("create-forward").hide()
            self.window.get_widget("create-finish").show()

    def close(self, ignore1=None,ignore2=None):
        self.topwin.hide()
        return 1

    def is_visible(self):
        if self.topwin.flags() & gtk.VISIBLE:
           return 1
        return 0

    def finish(self, ignore=None):
        # Validation should have mostly set up out guest. We just need
        # to take care of a few pieces we didn't touch

        guest = self._guest
        guest.hypervisorURI = self.connection.get_uri()

        # UUID, append disk and nic
        try:
            guest.uuid = virtinst.util.uuidToString(virtinst.util.randomUUID())
        except ValueError, E:
            return self.err.val_err(_("UUID Error"), str(e))

        # HACK: If usermode, and no nic is setup, use usermode networking
        if self.connection.get_uri() == "qemu:///session":
            try:
                self._net = virtinst.VirtualNetworkInterface(type="user")
            except ValueError, e:
                return self.err.val_err(_("Failed to set up usermode networking"), str(e))

        if self._disk is not None:
            guest.disks = [self._disk]
        else:
            logging.debug('No guest disks found in install phase.')
        if self._net is not None:
            guest.nics = [self._net]
        else:
            logging.debug('No guest nics found in install phase.')

        try:
            guest._graphics_dev = virtinst.VirtualGraphics(type=virtinst.VirtualGraphics.TYPE_VNC)
        except Exception, e:
            self.err.show_err(_("Error setting up graphics device:") + str(e),
                              "".join(traceback.format_exc()))
            return False

        logging.debug("Creating a VM " + guest.name + \
                      "\n  Type: " + guest.type + \
                      "\n  UUID: " + guest.uuid + \
                      "\n  Source: " + self.get_config_install_source() + \
                      "\n  OS: " + str(self.get_config_os_label()) + \
                      "\n  Kickstart: " + self.get_config_kickstart_source() + \
                      "\n  Memory: " + str(guest.memory) + \
                      "\n  Max Memory: " + str(guest.maxmemory) + \
                      "\n  # VCPUs: " + str(guest.vcpus) + \
                      "\n  Filesize: " + str(self._disk.size) + \
                      "\n  Disk image: " + str(self.get_config_disk_image()) +\
                      "\n  Non-sparse file: " + str(self.non_sparse))

        #let's go
        self.install_error = None
        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        if not self.non_sparse:
            logging.debug("Sparse file or partition selected")
        else:
            logging.debug("Non-sparse file selected")

        progWin = vmmAsyncJob(self.config, self.do_install, [guest],
                              title=_("Creating Virtual Machine"),
                              text=_("The virtual machine is now being created. " + \
                                     "Allocation of disk storage and retrieval of " + \
                                     "the installation images may take a few minutes " + \
                                     "to complete."))
        progWin.run()

        if self.install_error != None:
            self.err.show_err(self.install_error, self.install_details)
            self.topwin.set_sensitive(True)
            self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))
            # Don't close becase we allow user to go back in wizard & correct
            # their mistakes
            #self.close()
            return

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))
        # Ensure new VM is loaded
        self.connection.tick(noStatsUpdate=True)

        if self.config.get_console_popup() == 1:
            # user has requested console on new created vms only
            vm = self.connection.get_vm(guest.uuid)
            (gtype, host, port, transport, username) = vm.get_graphics_console()
            if gtype == "vnc":
                self.emit("action-show-console", self.connection.get_uri(), guest.uuid)
            else:
                self.emit("action-show-terminal", self.connection.get_uri(), guest.uuid)
        self.close()

    def do_install(self, guest, asyncjob):
        meter = vmmCreateMeter(asyncjob)
        try:
            logging.debug("Starting background install process")
            dom = guest.start_install(False, meter = meter)
            if dom == None:
                self.install_error = _("Guest installation failed to complete")
                self.install_details = self.install_error
                logging.error("Guest install did not return a domain")
            else:
                logging.debug("Install completed")
        except:
            (type, value, stacktrace) = sys.exc_info ()

            # Detailed error message, in English so it can be Googled.
            details = \
                    "Unable to complete install '%s'" % \
                    (str(type) + " " + str(value) + "\n" + \
                     traceback.format_exc (stacktrace))

            self.install_error = _("Unable to complete install: '%s'") % str(value)
            self.install_details = details
            logging.error(details)

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
        fcdialog.set_default_response(gtk.RESPONSE_ACCEPT)
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
        fcdialog = gtk.FileChooserDialog(_("Locate or Create New Storage File"),
                                         self.window.get_widget("vmm-create"),
                                         gtk.FILE_CHOOSER_ACTION_SAVE,
                                         (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                          gtk.STOCK_OPEN, gtk.RESPONSE_ACCEPT),
                                         None)
        fcdialog.set_default_response(gtk.RESPONSE_ACCEPT)
        fcdialog.set_current_folder(self.config.get_default_image_dir(self.connection))
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
            size = self.get_config_disk_size()
            if size == None:
                size = 4000
            self.window.get_widget("storage-file-size").set_value(size)
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

    def change_media_type(self, ignore=None):
        if self.window.get_widget("media-iso-image").get_active():
            self.window.get_widget("fv-iso-location-box").set_sensitive(True)
            self.window.get_widget("cd-path").set_sensitive(False)
        elif self.window.get_widget("media-physical").get_active():
            self.window.get_widget("fv-iso-location-box").set_sensitive(False)
            self.window.get_widget("cd-path").set_sensitive(True)
            self.window.get_widget("cd-path").set_active(-1)
        else:
            self.window.get_widget("fv-iso-location-box").set_sensitive(False)
            self.window.get_widget("cd-path").set_sensitive(False)

    def change_storage_type(self, ignore=None):
        if self.window.get_widget("storage-partition").get_active():
            self.window.get_widget("storage-partition-box").set_sensitive(True)
            self.window.get_widget("storage-file-box").set_sensitive(False)
            self.window.get_widget("storage-file-size").set_sensitive(False)
            self.window.get_widget("non-sparse").set_sensitive(False)
        else:
            self.window.get_widget("storage-partition-box").set_sensitive(False)
            self.window.get_widget("storage-file-box").set_sensitive(True)
            file = self.window.get_widget("storage-file-address").get_text()
            if file is None or file == "":
                dir = self.config.get_default_image_dir(self.connection)
                file = os.path.join(dir, self.get_config_name() + ".img")
                n = 1
                while os.path.exists(file) and n < 100:
                    file = os.path.join(dir, self.get_config_name() + "-" + str(n) + ".img")
                    n = n + 1
                if not os.path.exists(file):
                    self.window.get_widget("storage-file-address").set_text(file)
            self.toggle_storage_size()

    def change_network_type(self, ignore=None):
        if self.window.get_widget("net-type-network").get_active():
            self.window.get_widget("net-network").set_sensitive(True)
            self.window.get_widget("net-device").set_sensitive(False)
        else:
            self.window.get_widget("net-network").set_sensitive(False)
            self.window.get_widget("net-device").set_sensitive(True)

    def change_macaddr_use(self, ignore=None):
        if self.window.get_widget("mac-address").get_active():
            self.window.get_widget("create-mac-address").set_sensitive(True)
        else:
            self.window.get_widget("create-mac-address").set_sensitive(False)

    def set_max_memory(self, src):
        max_memory = src.get_adjustment().value
        startup_mem_adjustment = self.window.get_widget("create-memory-startup").get_adjustment()
        if startup_mem_adjustment.value > max_memory:
            startup_mem_adjustment.value = max_memory
        startup_mem_adjustment.upper = max_memory

    def set_max_vcpus(self, type):
        self.window.get_widget("create-vcpus").get_adjustment().upper = self.connection.get_max_vcpus(type)
        self.window.get_widget("config-max-vcpus").set_text(str(self.connection.get_max_vcpus(type)))

    def validate(self, page_num):

        # Setting the values in the Guest/Disk/Network virtinst objects
        # provides a lot of error checking for free, we just have to catch
        # the messages

        if page_num == PAGE_NAME:
            name = self.window.get_widget("create-vm-name").get_text()
            try:
                self._guest.name = name
            except ValueError, e:
                return self.err.val_err(_("Invalid System Name"), str(e))
        elif page_num == PAGE_TYPE:

            # Set up appropriate guest object dependent on selected type
            name = self._guest.name
            if self.get_config_method() == VM_PARA_VIRT:
                self._guest = virtinst.ParaVirtGuest(type=self.get_domain_type(),
                                                     hypervisorURI=self.connection.get_uri(),
                                                     connection=self.connection.vmm)
            else:
                self._guest = virtinst.FullVirtGuest(type=self.get_domain_type(),
                                                     arch=self.get_domain_arch(),
                                                     hypervisorURI=self.connection.get_uri(),
                                                     connection=self.connection.vmm)

            self._guest.name = name # Transfer name over

            # Set vcpu limits based on guest type
            try:
                self.set_max_vcpus(self.get_domain_type())
            except Exception, e:
                logging.exception(e)

        elif page_num == PAGE_INST:
            if self.get_config_method() == VM_PARA_VIRT:
                os_type = "xen"
            else:
                os_type = "hvm"
            self._guest.installer = self.get_config_installer(self.get_domain_type(), os_type)

            try:
                if self.get_config_os_type() is not None \
                   and self.get_config_os_type() != "generic":
                    logging.debug("OS Type: %s" % self.get_config_os_type())
                    self._guest.os_type = self.get_config_os_type()
            except ValueError, e:
                return self.err.val_err(_("Invalid FV OS Type"), str(e))
            try:
                if self.get_config_os_variant() is not None \
                   and self.get_config_os_type() != "generic":
                    logging.debug("OS Variant: %s" % self.get_config_os_variant())
                    self._guest.os_variant = self.get_config_os_variant()
            except ValueError, e:
                return self.err.val_err(_("Invalid FV OS Variant"), str(e))
        elif page_num == PAGE_INST_LOCAL:
            if self.get_config_method() == VM_PARA_VIRT:
                os_type = "xen"
            else:
                os_type = "hvm"
            self._guest.installer = self.get_config_installer(self.get_domain_type(), os_type)

            if self.window.get_widget("media-iso-image").get_active():

                src = self.get_config_install_source()
                try:
                    self._guest.cdrom = src
                except ValueError, e:
                    return self.err.val_err(_("ISO Path Not Found"), str(e))
            else:
                cdlist = self.window.get_widget("cd-path")
                src = self.get_config_install_source()
                try:
                    self._guest.cdrom = src
                except ValueError, e:
                    return self.err.val_err(_("CD-ROM Path Error"), str(e))
        elif page_num == PAGE_INST_TREE:

            src = self.get_config_install_source()
            if not src:
                return self.err.val_err(_("An install url is required."))
            try:
                self._guest.location = src
            except ValueError, e:
                return self.err.val_err(_("Invalid Install URL"), str(e))

            ks = self.get_config_kickstart_source()
            if ks is not None and len(ks) != 0:
                if not (ks.startswith("http://") or ks.startswith("ftp://") \
                        or ks.startswith("nfs:")):
                    return self.err.val_err(_("Kickstart URL Error"), \
                                            _("Kickstart location must be an NFS, HTTP or FTP source"))
                else:
                    self._guest.extraargs = "ks=%s" % (ks,)

            kernel_params = self.get_config_kernel_params()
            if kernel_params != "":
                if self._guest.extraargs is None:
                    self._guest.extraargs = kernel_params
                else:
                    self._guest.extraargs = "%s %s" % (self._guest.extraargs, kernel_params)
		self._guest.extraargs = self._guest.extraargs.strip()

        elif page_num == PAGE_DISK:
            
            disk = self.get_config_disk_image()
            if disk == None or len(disk) == 0:
                return self.err.val_err(_("Storage Address Required"), \
                                        _("You must specify a partition or a file for storage for the guest install"))

            if not self.window.get_widget("storage-partition").get_active():
                disk = self.get_config_disk_image()
                size = self.get_config_disk_size()
                if not os.path.exists(disk):
                    dir = os.path.dirname(os.path.abspath(disk))
                    if not os.path.exists(dir):
                        return self.err.val_err(_("Storage Path Does not exist"),
                                                _("The directory %s containing the disk image does not exist") % dir)
                    else:
                        vfs = os.statvfs(dir)
                        avail = vfs[statvfs.F_FRSIZE] * vfs[statvfs.F_BAVAIL]
                        need = size * 1024 * 1024
                        if need > avail:
                            if self.is_sparse_file():
                                res = self.err.yes_no(_("Not Enough Free Space"),
                                                      _("The filesystem will not have enough free space to fully allocate the sparse file when the guest is running. Use this path anyway?"))
                                if not res:
                                    return False
                            else:
                                return self.err.val_err(_("Not Enough Free Space"),
                                                        _("There is not enough free space to create the disk"))

            # Attempt to set disk
            filesize = None
            if self.get_config_disk_size() != None:
                filesize = self.get_config_disk_size() / 1024.0
            try:
                if self.window.get_widget("storage-partition").get_active():
                    type = virtinst.VirtualDisk.TYPE_BLOCK
                else:
                    type = virtinst.VirtualDisk.TYPE_FILE

                self._disk = virtinst.VirtualDisk(self.get_config_disk_image(),
                                                  filesize,
                                                  sparse = self.is_sparse_file(),
                                                  device = virtinst.VirtualDisk.DEVICE_DISK,
                                                  type = type)

                if self._disk.type == virtinst.VirtualDisk.TYPE_FILE and \
                   self.get_config_method() == VM_PARA_VIRT and \
                   virtinst.util.is_blktap_capable():
                    self._disk.driver_name = virtinst.VirtualDisk.DRIVER_TAP

                if self._disk.type == virtinst.VirtualDisk.TYPE_FILE and not \
                   self.is_sparse_file():
                    self.non_sparse = True
                else:
                    self.non_sparse = False
            except ValueError, e:
                return self.err.val_err(_("Invalid Storage Address"), str(e))

            if self._disk.is_conflict_disk(self.connection.vmm) is True:
               res = self.err.yes_no(_('Disk "%s" is already in use by another guest!' % disk), _("Do you really want to use the disk ?"))
               return res

        elif page_num == PAGE_NETWORK:

            if self.window.get_widget("net-type-network").get_active():
                if self.window.get_widget("net-network").get_active() == -1:
                    return self.err.val_err(_("Virtual Network Required"),
                                            _("You must select one of the virtual networks"))
            else:
                if self.window.get_widget("net-device").get_active() == -1:
                    return self.err.val_err(_("Physical Device Required"),
                                            _("You must select one of the physical devices"))

            net = self.get_config_network()
            if net[1] is None:
                return self.err.val_err(_("Invalid Physical Device"),
                                        _("The selected physical device must be bridged."))

            if self.window.get_widget("mac-address").get_active():
                mac = self.window.get_widget("create-mac-address").get_text()
                if mac is None or len(mac) == 0:
                    return self.err.val_err(_("Invalid MAC address"), \
                                            _("No MAC address was entered. Please enter a valid MAC address."))

            else:
                mac = None
            try:    
                if net[0] == "bridge":
                    self._net = virtinst.VirtualNetworkInterface(macaddr=mac, \
                                                                 type=net[0], \
                                                                 bridge=net[1])
                elif net[0] == "network":
                    self._net = virtinst.VirtualNetworkInterface(macaddr=mac, \
                                                                 type=net[0], \
                                                                 network=net[1])
                elif net[0] == "user":
                    self._net = virtinst.VirtualNetworkInterface(macaddr=mac, \
                                                                 type=net[0])
            except ValueError, e:
                return self.err.val_err(_("Network Parameter Error"), str(e))

            conflict = self._net.is_conflict_net(self.connection.vmm)
            if conflict[0]:
                return self.err.val_err(_("Mac address collision"), conflict[1])
            elif conflict[1] is not None:
                return self.err.yes_no(_("Mac address collision"),\
                                        conflict[1] + " " + _("Are you sure you want to use this address?"))

        elif page_num == PAGE_CPUMEM:

            # Set vcpus
            try:
                self._guest.vcpus = int(self.get_config_virtual_cpus())
            except ValueError, e: 
                return self.err.val_err(_("VCPU Count Error"), str(e))
            # Set Memory
            try:
                self._guest.memory = int(self.get_config_initial_memory())
            except ValueError, e: 
                return self.err.val_err(_("Memory Amount Error"), str(e))
            # Set Max Memory
            try:
                self._guest.maxmemory = int(self.get_config_maximum_memory())
            except ValueError, e: 
                return self.err.val_err(_("Max Memory Amount Error"), str(e))

        # do this always, since there's no "leaving a notebook page" event.
        self.window.get_widget("create-back").set_sensitive(True)
        return True

    def populate_url_model(self, model, urls):
        model.clear()
        for url in urls:
            model.append([url])

    def populate_os_type_model(self):
        model = self.window.get_widget("os-type").get_model()
        model.clear()
        model.append(["generic", "Generic"])
        types = virtinst.FullVirtGuest.list_os_types()
        types.sort()
        for type in types:
            model.append([type, virtinst.FullVirtGuest.get_os_type_label(type)])

    def populate_os_variant_model(self, type):
        model = self.window.get_widget("os-variant").get_model()
        model.clear()
        if type=="generic":
            model.append(["generic", "Generic"])
            return
        variants = virtinst.FullVirtGuest.list_os_variants(type)
        variants.sort()
        for variant in variants:
            model.append([variant, virtinst.FullVirtGuest.get_os_variant_label(type, variant)])

    def populate_network_model(self, model):
        model.clear()
        for uuid in self.connection.list_net_uuids():
            net = self.connection.get_net(uuid)
            model.append([net.get_label(), net.get_name()])

    def populate_device_model(self, model):
        model.clear()
        hasShared = False
        brIndex = -1
        for name in self.connection.list_net_device_paths():
            net = self.connection.get_net_device(name)
            if net.is_shared():
                hasShared = True
                if brIndex < 0:
                    brIndex = len(model)
                model.append([net.get_bridge(), "%s (%s %s)" % (net.get_name(), _("Bridge"), net.get_bridge()), True])
            else:
                model.append([net.get_bridge(), "%s (%s)" % (net.get_name(), _("Not bridged")), False])
        return (hasShared, brIndex)

    def change_os_type(self, box):
        model = box.get_model()
        if box.get_active_iter() != None:
            type = model.get_value(box.get_active_iter(), 0)
            self.populate_os_variant_model(type)
        variant = self.window.get_widget("os-variant")
        variant.set_active(0)

    def change_virt_method(self, ignore=None):
        arch = self.window.get_widget("cpu-architecture")

        if self.get_config_method() == VM_PARA_VIRT:
            nativeArch = self.repopulate_cpu_arch(arch.get_model(), ["xen", "linux"])
        else:
            nativeArch = self.repopulate_cpu_arch(arch.get_model(), ["hvm"])
        arch.set_active(nativeArch)
        self.change_cpu_arch()

    def change_cpu_arch(self, ignore=None):
        hypervisor = self.window.get_widget("hypervisor")
        arch = self.get_domain_arch()

        if arch is None:
            hypervisor.set_active(-1)
            hypervisor.set_sensitive(False)
            return

        hypervisor.set_sensitive(True)
        if self.get_config_method() == VM_PARA_VIRT:
            bestHyper = self.repopulate_hypervisor(hypervisor.get_model(), ["xen", "linux"], arch)
        else:
            bestHyper = self.repopulate_hypervisor(hypervisor.get_model(), ["hvm"], arch)
        hypervisor.set_active(bestHyper)

    def get_domain_arch(self):
        arch = self.window.get_widget("cpu-architecture")
        if arch.get_active() == -1:
            return None
        return arch.get_model()[arch.get_active()][0]

    def pretty_memory(self, mem):
        if mem > (1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.2f MB" % (mem/1024.0)

    def is_sparse_file(self):
        if self.window.get_widget("non-sparse").get_active():
            return False
        else:
            return True

    def get_domain_type(self):
        hypervisor = self.window.get_widget("hypervisor")

        if hypervisor.get_active() == -1:
            return None

        return hypervisor.get_model()[hypervisor.get_active()][0]

    def repopulate_cpu_arch(self, model, ostype):
        model.clear()
        i = 0
        native = -1
        for guest in self.caps.guests:
            if guest.os_type not in ostype:
                continue

            model.append([guest.arch])
            if guest.arch == self.caps.host.arch:
                native = i
            i = i + 1

        return native


    def repopulate_hypervisor(self, model, ostype, arch):
        model.clear()
        i = -1
        for guest in self.caps.guests:
            if guest.os_type not in ostype or guest.arch != arch:
                continue

            for domain in guest.domains:
                model.append([domain.hypervisor_type])
                i = i + 1

        return i

    def show_help(self, src):
        # help to show depends on the notebook page, yahoo
        page = self.window.get_widget("create-pages").get_current_page()
        if page == PAGE_INTRO:
            self.emit("action-show-help", "virt-manager-create-wizard")
        elif page == PAGE_NAME:
            self.emit("action-show-help", "virt-manager-system-name")
        elif page == PAGE_TYPE:
            self.emit("action-show-help", "virt-manager-virt-method")
        elif page == PAGE_INST:
            self.emit("action-show-help", "virt-manager-installation-media")
        elif page == PAGE_INST_LOCAL:
            self.emit("action-show-help", "virt-manager-installation-media-local")
        elif page == PAGE_INST_TREE:
            self.emit("action-show-help", "virt-manager-installation-media-tree")
        elif page == PAGE_DISK:
            self.emit("action-show-help", "virt-manager-storage-space")
        elif page == PAGE_NETWORK:
            self.emit("action-show-help", "virt-manager-network")
        elif page == PAGE_CPUMEM:
            self.emit("action-show-help", "virt-manager-memory-and-cpu")
        elif page == PAGE_SUMMARY:
            self.emit("action-show-help", "virt-manager-validation")

gobject.type_register(vmmCreate)

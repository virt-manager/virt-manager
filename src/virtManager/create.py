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
import libvirt
import virtinst
import os, sys
import re
import subprocess
import urlgrabber.progress as progress
import tempfile
import logging
import dbus
import traceback

from virtManager.asyncjob import vmmAsyncJob
from virtManager.error import vmmErrorDialog

VM_PARA_VIRT = 1
VM_FULLY_VIRT = 2

VM_INSTALL_FROM_ISO = 1
VM_INSTALL_FROM_CD = 2

VM_STORAGE_PARTITION = 1
VM_STORAGE_FILE = 2

DEFAULT_STORAGE_FILE_SIZE = 500

PAGE_INTRO = 0
PAGE_NAME = 1
PAGE_TYPE = 2
PAGE_FVINST = 3
PAGE_PVINST = 4
PAGE_DISK = 5
PAGE_NETWORK = 6
PAGE_CPUMEM = 7
PAGE_SUMMARY = 8

KEYBOARD_DIR = "/etc/sysconfig/keyboard"

class vmmCreateMeter(progress.BaseMeter):
    def __init__(self, asyncjob):
        # progress meter has to run asynchronously, so pass in the
        # async job to call back to with progress info
        progress.BaseMeter.__init__(self)
        self.asyncjob = asyncjob

    def _do_start(self, now):
        if self.text is not None:
            text = self.text
        else:
            text = self.basename
        if self.size is None:
            out = "    %5sB" % (0)
            self.asyncjob.pulse_pbar(out, text)
        else:
            out = "%3i%% %5sB" % (0, 0)
            self.asyncjob.set_pbar_fraction(0, out, text)

    def _do_update(self, amount_read, now=None):
        if self.text is not None:
            text = self.text
        else:
            text = self.basename
        fread = progress.format_number(amount_read)
        if self.size is None:
            out = "    %5sB" % (fread)
            self.asyncjob.pulse_pbar(out, text)
        else:
            frac = self.re.fraction_read()
            out = "%3i%% %5sB" % (frac*100, fread)
            self.asyncjob.set_pbar_fraction(frac, out, text)

    def _do_end(self, amount_read, now=None):
        if self.text is not None:
            text = self.text
        else:
            text = self.basename
        fread = progress.format_number(amount_read)
        if self.size is None:
            out = "    %5sB" % (fread)
            self.asyncjob.pulse_pbar(out, text)
        else:
            out = "%3i%% %5sB" % (100, fread)
            self.asyncjob.set_pbar_done(out, text)

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
            "on_media_toggled" : self.change_media_type,
            "on_os_type_changed" : self.change_os_type,
            "on_cpu_architecture_changed": self.change_cpu_arch,
            "on_virt_method_toggled": self.change_virt_method,
            "on_create_help_clicked": self.show_help,
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
            # Get a connection to the SYSTEM bus
            self.bus = dbus.SystemBus()
            # Get a handle to the HAL service
            hal_object = self.bus.get_object('org.freedesktop.Hal', '/org/freedesktop/Hal/Manager')
            self.hal_iface = dbus.Interface(hal_object, 'org.freedesktop.Hal.Manager')
            self.populate_opt_media(cd_model)
        except Exception, e:
            logging.error("Unable to connect to HAL to list cdrom volumes: '%s'", e)
            self.window.get_widget("media-physical").set_sensitive(False)
            self.bus = None
            self.hal_iface = None

        if os.getuid() != 0:
            self.window.get_widget("media-physical").set_sensitive(False)
            self.window.get_widget("storage-partition").set_sensitive(False)

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
        device_model = gtk.ListStore(str)
        device_list.set_model(device_model)
        text = gtk.CellRendererText()
        device_list.pack_start(text, True)
        device_list.add_attribute(text, 'text', 0)

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

        if self.connection.get_type() == "QEMU":
            self.window.get_widget("cpu-architecture").set_active(0)
        else:
            self.window.get_widget("cpu-architecture").set_active(-1)

        self.window.get_widget("cpu-architecture").set_sensitive(False)
        self.window.get_widget("cpu-accelerate").set_sensitive(False)
        self.change_virt_method()


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
        if self.connection.get_type() == "QEMU":
            self.window.get_widget("virt-method-pv").set_sensitive(False)
            self.window.get_widget("virt-method-fv").set_active(True)
            self.window.get_widget("virt-method-fv-unsupported").hide()
            self.window.get_widget("virt-method-fv-disabled").hide()
        else:
            self.window.get_widget("virt-method-pv").set_sensitive(True)
            self.window.get_widget("virt-method-pv").set_active(True)
            if virtinst.util.is_hvm_capable():
                self.window.get_widget("virt-method-fv").set_sensitive(True)
                self.window.get_widget("virt-method-fv-unsupported").hide()
                self.window.get_widget("virt-method-fv-disabled").hide()
            else:
                self.window.get_widget("virt-method-fv").set_sensitive(False)
                flags = virtinst.util.get_cpu_flags()
                if "vmx" in flags or "svm" in flags:
                    # Host has support, but disabled in bios
                    self.window.get_widget("virt-method-fv-unsupported").hide()
                    self.window.get_widget("virt-method-fv-disabled").show()
                else:
                    # Host has no support
                    self.window.get_widget("virt-method-fv-unsupported").show()
                    self.window.get_widget("virt-method-fv-disabled").hide()

        self.change_media_type()
        self.change_storage_type()
        self.change_network_type()
        self.window.get_widget("create-vm-name").set_text("")
        self.window.get_widget("media-iso-image").set_active(True)
        self.window.get_widget("fv-iso-location").set_text("")
        if os.getuid() == 0:
            self.window.get_widget("storage-partition").set_active(True)
        else:
            self.window.get_widget("storage-file-backed").set_active(True)
        self.window.get_widget("storage-partition-address").set_text("")
        self.window.get_widget("storage-file-address").set_text("")
        self.window.get_widget("storage-file-size").set_value(2000)
        self.window.get_widget("create-memory-max").set_value(500)
        self.window.get_widget("create-memory-startup").set_value(500)
        self.window.get_widget("create-vcpus").set_value(1)
        self.window.get_widget("non-sparse").set_active(True)
        model = self.window.get_widget("pv-media-url").get_model()
        self.populate_url_model(model, self.config.get_media_urls())
        model = self.window.get_widget("pv-ks-url").get_model()
        self.populate_url_model(model, self.config.get_kickstart_urls())

        # Fill list of OS types
        self.populate_os_type_model()
        self.window.get_widget("os-type").set_active(-1)

        model = self.window.get_widget("net-network").get_model()
        self.populate_network_model(model)
        device = self.window.get_widget("net-device").get_model()
        self.populate_device_model(device)
        self.install_error = None


    def forward(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        if(self.validate(notebook.get_current_page()) != True):
            return

        if (notebook.get_current_page() == PAGE_TYPE and self.get_config_method() == VM_PARA_VIRT):
            notebook.set_current_page(PAGE_PVINST)
        elif (notebook.get_current_page() == PAGE_FVINST and self.get_config_method() == VM_FULLY_VIRT):
            notebook.set_current_page(PAGE_DISK)
        elif (notebook.get_current_page() == PAGE_DISK and os.getuid() != 0):
            notebook.set_current_page(PAGE_CPUMEM)
        else:
            notebook.next_page()

    def back(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        # do this always, since there's no "leaving a notebook page" event.
        self.window.get_widget("create-finish").hide()
        self.window.get_widget("create-forward").show()
        if notebook.get_current_page() == PAGE_PVINST and self.get_config_method() == VM_PARA_VIRT:
            notebook.set_current_page(PAGE_TYPE)
        elif notebook.get_current_page() == PAGE_DISK and self.get_config_method() == VM_FULLY_VIRT:
            notebook.set_current_page(PAGE_FVINST)
        elif notebook.get_current_page() == PAGE_CPUMEM and os.getuid() != 0:
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

    def get_config_network(self):
        if os.getuid() != 0:
            return ["user"]

        if self.window.get_widget("net-type-network").get_active():
            net = self.window.get_widget("net-network")
            model = net.get_model()
            return ["network", model.get_value(net.get_active_iter(), 0)]
        else:
            dev = self.window.get_widget("net-device")
            model = dev.get_model()
            return ["bridge", model.get_value(dev.get_active_iter(), 0)]

    def get_config_maximum_memory(self):
        return self.window.get_widget("create-memory-max").get_value()

    def get_config_initial_memory(self):
        return self.window.get_widget("create-memory-startup").get_value()

    def get_config_virtual_cpus(self):
        return self.window.get_widget("create-vcpus").get_value()

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
        elif page_number == PAGE_FVINST:
            pass
        elif page_number == PAGE_PVINST:
            url_widget = self.window.get_widget("pv-media-url")
            url_widget.grab_focus()
        elif page_number == PAGE_DISK:
            partwidget = self.window.get_widget("storage-partition-address")
            filewidget = self.window.get_widget("storage-file-address")
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
        # first things first, are we trying to create a fully virt guest?
        if self.get_config_method() == VM_FULLY_VIRT:
            guest = virtinst.FullVirtGuest(type=self.get_domain_type(), \
                                           hypervisorURI=self.connection.get_uri(), \
                                           arch=self.get_domain_arch())
            try:
                guest.cdrom = self.get_config_install_source()
            except ValueError, e:
                self._validation_error_box(_("Invalid FV media address"),e.args[0])
            try:
                if self.get_config_os_type() is not None:
                    logging.debug("OS Type: %s" % self.get_config_os_type())
                    guest.os_type = self.get_config_os_type()
            except ValueError, e:
                self._validation_error_box(_("Invalid FV OS Type"),e.args[0])
            try:
                if self.get_config_os_variant() is not None:
                    logging.debug("OS Variant: %s" % self.get_config_os_variant())
                    guest.os_variant = self.get_config_os_variant()
            except ValueError, e:
                self._validation_error_box(_("Invalid FV OS Variant"),e.args[0])

        else:
            guest = virtinst.ParaVirtGuest(type=self.get_domain_type(), hypervisorURI=self.connection.get_uri())
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
            guest.memory = int(self.get_config_initial_memory())
        except ValueError:
            self._validation_error_box(_("Invalid memory setting"), e.args[0])
            return

        try:
            guest.maxmemory = int(self.get_config_maximum_memory())
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
            d = virtinst.VirtualDisk(self.get_config_disk_image(), filesize, sparse = self.is_sparse_file())
            if d.type == virtinst.VirtualDisk.TYPE_FILE and \
                   self.get_config_method() == VM_PARA_VIRT \
                   and virtinst.util.is_blktap_capable():
                d.driver_name = virtinst.VirtualDisk.DRIVER_TAP
            if d.type == virtinst.VirtualDisk.TYPE_FILE and not \
               self.is_sparse_file():
                self.non_sparse = True
            else:
                self.non_sparse = False
        except ValueError, e:
            self._validation_error_box(_("Invalid storage address"), e.args[0])
            return
        guest.disks.append(d)

        # uuid
        guest.uuid = virtinst.util.uuidToString(virtinst.util.randomUUID())

        # network
        net = self.get_config_network()
        if net[0] == "bridge":
            guest.nics.append(virtinst.VirtualNetworkInterface(type=net[0], bridge=net[1]))
        elif net[0] == "network":
            guest.nics.append(virtinst.VirtualNetworkInterface(type=net[0], network=net[1]))
        elif net[0] == "user":
            guest.nics.append(virtinst.VirtualNetworkInterface(type=net[0]))
        else:
            raise ValueError, "Unsupported networking type " + net[0]

        # set up the graphics to use SDL
        import keytable
        keymap = None
        vncport = None
        try:
            f = open(KEYBOARD_DIR, "r")
        except IOError, e:
            logging.debug('Could not open "/etc/sysconfig/keyboard" ' + str(e))
        else:
            while 1:
                s = f.readline()
                if s == "":
                    break
                if re.search("KEYTABLE", s) != None:
                    kt = s.split('"')[1]
                    if keytable.keytable.has_key(kt):
                        keymap = keytable.keytable[kt]
            f.close
        guest.graphics = (True, "vnc", vncport, keymap)

        logging.debug("Creating a VM " + guest.name + \
                      "\n  Type: " + guest.type + \
                      "\n  UUID: " + guest.uuid + \
                      "\n  Source: " + self.get_config_install_source() + \
                      "\n  OS: " + str(self.get_config_os_label()) + \
                      "\n  Kickstart: " + self.get_config_kickstart_source() + \
                      "\n  Memory: " + str(guest.memory) + \
                      "\n  Max Memory: " + str(guest.maxmemory) + \
                      "\n  # VCPUs: " + str(guest.vcpus) + \
                      "\n  Filesize: " + str(filesize) + \
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
            dg = vmmErrorDialog(None, 0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                self.install_error,
                                self.install_details)
            dg.run()
            dg.hide()
            dg.destroy()
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
            (gtype, host, port) = vm.get_graphics_console()
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
            self.window.get_widget("non-sparse").set_sensitive(False)
        else:
            self.window.get_widget("storage-partition-box").set_sensitive(False)
            self.window.get_widget("storage-file-box").set_sensitive(True)
            self.toggle_storage_size()

    def change_network_type(self, ignore=None):
        if self.window.get_widget("net-type-network").get_active():
            self.window.get_widget("net-network").set_sensitive(True)
            self.window.get_widget("net-device").set_sensitive(False)
        else:
            self.window.get_widget("net-network").set_sensitive(False)
            self.window.get_widget("net-device").set_sensitive(True)

    def set_max_memory(self, src):
        max_memory = src.get_adjustment().value
        startup_mem_adjustment = self.window.get_widget("create-memory-startup").get_adjustment()
        if startup_mem_adjustment.value > max_memory:
            startup_mem_adjustment.value = max_memory
        startup_mem_adjustment.upper = max_memory

    def validate(self, page_num):
        if page_num == PAGE_NAME:
            name = self.window.get_widget("create-vm-name").get_text()
            if len(name) > 50 or len(name) == 0:
                self._validation_error_box(_("Invalid System Name"), \
                                           _("System name must be non-blank and less than 50 characters"))
                return False
            if re.match("^[a-zA-Z0-9_]*$", name) == None:
                self._validation_error_box(_("Invalid System Name"), \
                                           _("System name may contain alphanumeric and '_' characters only"))
                return False


        elif page_num == PAGE_TYPE:
            if self.get_config_method() == VM_FULLY_VIRT and self.connection.get_type().startswith("Xen") and not virtinst.util.is_hvm_capable():
                self._validation_error_box(_("Hardware Support Required"), \
                                           _("Your hardware does not appear to support full virtualization. Only paravirtualized guests will be available on this hardware."))
                return False

        elif page_num == PAGE_FVINST:
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
        elif page_num == PAGE_PVINST:
            src = self.get_config_install_source()
            if src == None or len(src) == 0:
                self._validation_error_box(_("URL Required"), \
                                           _("You must specify a URL for the install image for the guest install"))
                return False

        elif page_num == PAGE_DISK:
            disk = self.get_config_disk_image()
            if disk == None or len(disk) == 0:
                self._validation_error_box(_("Storage Address Required"), \
                                           _("You must specify a partition or a file for storage for the guest install"))
                return False

            if not self.window.get_widget("storage-partition").get_active():
                if os.path.isdir(disk):
                    self._validation_error_box(_("Storage Address Is Directory"), \
                                               _("You chose 'Simple File' storage for your storage method, but chose a directory instead of a file. Please enter a new filename or choose an existing file."))
                    return False

            d = virtinst.VirtualDisk(self.get_config_disk_image(), self.get_config_disk_size(), sparse = self.is_sparse_file())
            if d.is_conflict_disk(self.connection.vmm) is True:
               res = self._yes_no_box(_('Disk "%s" is already in use by another guest!' % disk), \
                                               _("Do you really want to use the disk ?"))
               return res

        elif page_num == PAGE_NETWORK:
            if self.window.get_widget("net-type-network").get_active():
                if self.window.get_widget("net-network").get_active() == -1:
                    self._validation_error_box(_("Virtual Network Required"),
                                               _("You must select one of the virtual networks"))
                    return False
            else:
                if self.window.get_widget("net-device").get_active() == -1:
                    self._validation_error_box(_("Physical Device Required"),
                                               _("You must select one of the physical devices"))
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

    def _yes_no_box(self, text1, text2=None):
        #import pdb; pdb.set_trace()
        message_box = gtk.MessageDialog(self.window.get_widget("vmm-create"), \
                                                0, \
                                                gtk.MESSAGE_WARNING, \
                                                gtk.BUTTONS_YES_NO, \
                                                text1)
        if text2 != None:
            message_box.format_secondary_text(text2)
        if message_box.run()== gtk.RESPONSE_YES:
            res = True
        else:
            res = False
        message_box.destroy()
        return res

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

    def populate_os_type_model(self):
        model = self.window.get_widget("os-type").get_model()
        model.clear()
        types = virtinst.FullVirtGuest.list_os_types()
        types.sort()
        for type in types:
            model.append([type, virtinst.FullVirtGuest.get_os_type_label(type)])

    def populate_os_variant_model(self, type):
        model = self.window.get_widget("os-variant").get_model()
        model.clear()
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
        for name in self.connection.list_net_device_paths():
            net = self.connection.get_net_device(name)
            if net.is_shared():
                model.append([net.get_bridge()])

    def change_os_type(self, box):
        model = box.get_model()
        if box.get_active_iter() != None:
            type = model.get_value(box.get_active_iter(), 0)
            self.populate_os_variant_model(type)
        variant = self.window.get_widget("os-variant")
        variant.set_active(-1)

    def change_virt_method(self, ignore=None):
        arch = self.window.get_widget("cpu-architecture")
        if self.connection.get_type() != "QEMU" or self.window.get_widget("virt-method-pv").get_active():
            arch.set_sensitive(False)
        else:
            arch.set_sensitive(True)
        self.change_cpu_arch(arch)

    def change_cpu_arch(self, src):
        model = src.get_model()
        active = src.get_active()
        canAccel = False
        if active != -1 and src.get_property("sensitive") and \
               (virtinst.util.is_kvm_capable() or virtinst.util.is_kqemu_capable()):
            if os.uname()[4] == "i686" and model[active][0] == "i686":
                canAccel = True
            elif os.uname()[4] == "x86_64" and model[active][0] in ("i686", "x86_64"):
                canAccel = True

        self.window.get_widget("cpu-accelerate").set_sensitive(canAccel)
        self.window.get_widget("cpu-accelerate").set_active(canAccel)

    def get_domain_arch(self):
        if self.connection.get_type() != "QEMU":
            return None
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
        if self.connection.get_type() == "QEMU":
            if self.window.get_widget("cpu-accelerate").get_active():
                if virtinst.util.is_kvm_capable():
                    return "kvm"
                elif virtinst.util.is_kqemu_capable():
                    return "kqemu"
            return "qemu"
        else:
            return "xen"

    def show_help(self, src):
        # help to show depends on the notebook page, yahoo
        page = self.window.get_widget("create-pages").get_current_page()
        if page == PAGE_INTRO:
            self.emit("action-show-help", "virt-manager-create-wizard")
        elif page == PAGE_NAME:
            self.emit("action-show-help", "virt-manager-system-name")
        elif page == PAGE_TYPE:
            self.emit("action-show-help", "virt-manager-virt-method")
        elif page == PAGE_FVINST:
            self.emit("action-show-help", "virt-manager-installation-media-full-virt")
        elif page == PAGE_PVINST:
            self.emit("action-show-help", "virt-manager-installation-media-paravirt")
        elif page == PAGE_DISK:
            self.emit("action-show-help", "virt-manager-storage-space")
        elif page == PAGE_NETWORK:
            self.emit("action-show-help", "virt-manager-network")
        elif page == PAGE_CPUMEM:
            self.emit("action-show-help", "virt-manager-memory-and-cpu")
        elif page == PAGE_SUMMARY:
            self.emit("action-show-help", "virt-manager-validation")

gobject.type_register(vmmCreate)

#
# Copyright (C) 2006-2007 Red Hat, Inc.
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
from virtManager.createmeter import vmmCreateMeter

VM_STORAGE_PARTITION = 1
VM_STORAGE_FILE = 2

DEFAULT_STORAGE_FILE_SIZE = 500

PAGE_INTRO = 0
PAGE_DISK = 1
PAGE_NETWORK = 2
PAGE_SUMMARY = 3

class vmmAddHardware(gobject.GObject):
    __gsignals__ = {
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, [str]),
        }
    def __init__(self, config, vm):
        self.__gobject_init__()
        self.config = config
        self.vm = vm
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-add-hardware.glade", "vmm-add-hardware", domain="virt-manager")
        self.topwin = self.window.get_widget("vmm-add-hardware")
        self.topwin.hide()
        self.window.signal_autoconnect({
            "on_create_pages_switch_page" : self.page_changed,
            "on_create_cancel_clicked" : self.close,
            "on_vmm_create_delete_event" : self.close,
            "on_create_back_clicked" : self.back,
            "on_create_forward_clicked" : self.forward,
            "on_create_finish_clicked" : self.finish,
            "on_storage_partition_address_browse_clicked" : self.browse_storage_partition_address,
            "on_storage_file_address_browse_clicked" : self.browse_storage_file_address,
            "on_storage_file_address_changed": self.toggle_storage_size,
            "on_storage_toggled" : self.change_storage_type,
            "on_network_toggled" : self.change_network_type,
            "on_mac_address_clicked" : self.change_macaddr_use,
            "on_create_help_clicked": self.show_help,
            })

        hw_list = self.window.get_widget("hardware-type")
        model = gtk.ListStore(str, str, int)
        hw_list.set_model(model)
        icon = gtk.CellRendererPixbuf()
        hw_list.pack_start(icon, False)
        hw_list.add_attribute(icon, 'stock-id', 1)
        text = gtk.CellRendererText()
        hw_list.pack_start(text, True)
        hw_list.add_attribute(text, 'text', 0)
        model.append(["Storage device", gtk.STOCK_HARDDISK, PAGE_DISK])
        # User mode networking only allows a single card for now
        if self.vm.get_connection().get_type().lower() == "qemu" and os.getuid() == 0:
            model.append(["Network card", gtk.STOCK_NETWORK, PAGE_NETWORK])

        self.set_initial_state()

    def show(self):
        self.reset_state()
        self.topwin.show()
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

        if os.getuid() != 0:
            self.window.get_widget("storage-partition").set_sensitive(False)

        # set up the lists for the networks
        network_list = self.window.get_widget("net-network")
        network_model = gtk.ListStore(str, str)
        network_list.set_model(network_model)
        text = gtk.CellRendererText()
        network_list.pack_start(text, True)
        network_list.add_attribute(text, 'text', 1)

        device_list = self.window.get_widget("net-device")
        device_model = gtk.ListStore(str, bool)
        device_list.set_model(device_model)
        text = gtk.CellRendererText()
        device_list.pack_start(text, True)
        device_list.add_attribute(text, 'text', 0)
        device_list.add_attribute(text, 'sensitive', 1)

        target_list = self.window.get_widget("target-device")
        target_model = gtk.ListStore(str, int, str, str, str)
        target_list.set_model(target_model)
        icon = gtk.CellRendererPixbuf()
        target_list.pack_start(icon, False)
        target_list.add_attribute(icon, 'stock-id', 3)
        text = gtk.CellRendererText()
        target_list.pack_start(text, True)
        target_list.add_attribute(text, 'text', 4)

    def reset_state(self):
        notebook = self.window.get_widget("create-pages")
        notebook.set_current_page(0)
        # Hide the "finish" button until the appropriate time
        self.window.get_widget("create-finish").hide()
        self.window.get_widget("create-forward").show()
        self.window.get_widget("create-back").set_sensitive(False)
        self.window.get_widget("storage-file-size").set_sensitive(False)
        self.window.get_widget("create-help").hide()

        self.change_storage_type()
        self.change_network_type()
        self.change_macaddr_use()
        if os.getuid() == 0:
            self.window.get_widget("storage-partition").set_active(True)
        else:
            self.window.get_widget("storage-file-backed").set_active(True)
        self.window.get_widget("storage-partition-address").set_text("")
        self.window.get_widget("storage-file-address").set_text("")
        self.window.get_widget("storage-file-size").set_value(2000)
        self.window.get_widget("non-sparse").set_active(True)
        self.window.get_widget("hardware-type").set_active(0)

        self.window.get_widget("net-type-network").set_active(True)
        self.window.get_widget("net-type-device").set_active(False)
        self.window.get_widget("mac-address").set_active(False)
        self.window.get_widget("create-mac-address").set_text("")

        net_box = self.window.get_widget("net-network")
        self.populate_network_model(net_box.get_model())
        net_box.set_active(0)

        dev_box = self.window.get_widget("net-device")
        if self.populate_device_model(dev_box.get_model()):
            dev_box.set_active(0)
        else:
            dev_box.set_active(-1)

        target_list = self.window.get_widget("target-device")
        target_list.set_active(-1)


    def forward(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        if(self.validate(notebook.get_current_page()) != True):
            return

        if notebook.get_current_page() == PAGE_INTRO:
            notebook.set_current_page(self.get_config_hardware_type())
        else:
            notebook.set_current_page(PAGE_SUMMARY)
            self.window.get_widget("create-finish").show()
            self.window.get_widget("create-forward").hide()
        self.window.get_widget("create-back").set_sensitive(True)

    def back(self, ignore=None):
        notebook = self.window.get_widget("create-pages")

        if notebook.get_current_page() == PAGE_SUMMARY:
            notebook.set_current_page(self.get_config_hardware_type())
            self.window.get_widget("create-finish").hide()
        else:
            notebook.set_current_page(PAGE_INTRO)
            self.window.get_widget("create-back").set_sensitive(False)
        self.window.get_widget("create-forward").show()

    def get_config_hardware_type(self):
        type = self.window.get_widget("hardware-type")
        if type.get_active_iter() == None:
            return None
        return type.get_model().get_value(type.get_active_iter(), 2)

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

    def get_config_disk_target(self):
        target = self.window.get_widget("target-device")
        node = target.get_model().get_value(target.get_active_iter(), 0)
        maxnode = target.get_model().get_value(target.get_active_iter(), 1)
        device = target.get_model().get_value(target.get_active_iter(), 2)
        return node, maxnode, device

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

    def get_config_macaddr(self):
        macaddr = None
        if self.window.get_widget("mac-address").get_active():
            macaddr = self.window.get_widget("create-mac-address").get_text()
        return macaddr

    def page_changed(self, notebook, page, page_number):
        if page_number == PAGE_DISK:
            target = self.window.get_widget("target-device").get_model()
            self.populate_target_device_model(target)
        elif page_number == PAGE_NETWORK:
            pass
        elif page_number == PAGE_SUMMARY:
            hwpage = self.get_config_hardware_type()

            if hwpage == PAGE_DISK:
                self.window.get_widget("summary-disk").show()
                self.window.get_widget("summary-network").hide()
                self.window.get_widget("summary-disk-image").set_text(self.get_config_disk_image())
                disksize = self.get_config_disk_size()
                if disksize != None:
                    self.window.get_widget("summary-disk-size").set_text(str(int(disksize)) + " MB")
                else:
                    self.window.get_widget("summary-disk-size").set_text("-")
            elif hwpage == PAGE_NETWORK:
                self.window.get_widget("summary-disk").hide()
                self.window.get_widget("summary-network").show()
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

    def close(self, ignore1=None,ignore2=None):
        self.topwin.hide()
        return 1

    def is_visible(self):
        if self.topwin.flags() & gtk.VISIBLE:
           return 1
        return 0

    def finish(self, ignore=None):
        hw = self.get_config_hardware_type()

        self.install_error = None
        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        if hw == PAGE_NETWORK:
            self.add_network()
        elif hw == PAGE_DISK:
            self.add_storage()

        if self.install_error is not None:
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
        self.close()

    def add_network(self):
        net = self.get_config_network()
        mac = self.get_config_macaddr()
        vnic = None
        if net[0] == "bridge":
            vnic = virtinst.VirtualNetworkInterface(macaddr=mac, type=net[0], bridge=net[1])
        elif net[0] == "network":
            vnic = virtinst.VirtualNetworkInterface(macaddr=mac, type=net[0], network=net[1])
        else:
            raise ValueError, "Unsupported networking type " + net[0]

        vnic.setup(self.vm.get_connection().vmm)
        self.add_device(vnic.get_xml_config())

    def add_storage(self):
        node, maxnode, device = self.get_config_disk_target()
        filesize = None
        disk = None
        if self.get_config_disk_size() != None:
            filesize = self.get_config_disk_size() / 1024.0
        try:
            disk = virtinst.VirtualDisk(self.get_config_disk_image(),
                                        filesize,
                                        device = device,
                                        sparse = self.is_sparse_file())
            if disk.type == virtinst.VirtualDisk.TYPE_FILE and \
                   not self.vm.is_hvm() \
               and virtinst.util.is_blktap_capable():
                disk.driver_name = virtinst.VirtualDisk.DRIVER_TAP
        except ValueError, e:
            self._validation_error_box(_("Invalid storage address"), e.args[0])
            return

        used = {}
        for d in self.vm.get_disk_devices():
            dev = d[3]
            used[dev] = 1

        nodes = []
        if self.vm.is_hvm():
            # QEMU, only hdc can be a CDROM
            if self.vm.get_connection().get_type().lower() == "qemu" and \
                   device == virtinst.VirtualDisk.DEVICE_CDROM:
                nodes.append(node + "c")
            else:
                for n in range(maxnode):
                    nodes.append("%s%c" % (node, ord('a')+n))
        else:
            for n in range(maxnode):
                nodes.append("%s%c" % (node, ord('a')+n))

        node = None
        for n in nodes:
            if not used.has_key(n):
                node = n
                break

        if node is None:
            self._validation_error_box(_("Too many virtual disks"),
                                       _("There are no more available virtual disk device nodes"))
            return

        progWin = vmmAsyncJob(self.config, self.do_file_allocate, [disk],
                              title=_("Creating Storage File"),
                              text=_("Allocation of disk storage may take a few minutes " + \
                                     "to complete."))
        progWin.run()

        if self.install_error == None:
            self.add_device(disk.get_xml_config(node))

    def add_device(self, xml):
        logging.debug("Adding device " + xml)
        try:
            self.vm.add_device(xml)
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

    def do_file_allocate(self, disk, asyncjob):
        meter = vmmCreateMeter(asyncjob)
        try:
            logging.debug("Starting background file allocate process")
            disk.setup(meter)
            logging.debug("Allocation completed")
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

    def browse_storage_partition_address(self, src, ignore=None):
        part = self._browse_file(_("Locate Storage Partition"), "/dev")
        if part != None:
            self.window.get_widget("storage-partition-address").set_text(part)

    def browse_storage_file_address(self, src, ignore=None):
        self.window.get_widget("storage-file-size").set_sensitive(True)
        folder = self.config.get_default_image_dir(self.vm.get_connection())
        file = self._browse_file(_("Locate or Create New Storage File"), \
                                 folder=folder, confirm_overwrite=True)
        if file != None:
            self.window.get_widget("storage-file-address").set_text(file)

    def _browse_file(self, dialog_name, folder=None, type=None, confirm_overwrite=False):
        # user wants to browse for an ISO
        fcdialog = gtk.FileChooserDialog(dialog_name,
                                         self.window.get_widget("vmm-add-hardware"),
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
        if confirm_overwrite:
            fcdialog.set_do_overwrite_confirmation(True)
            fcdialog.connect("confirm-overwrite", self.confirm_overwrite_callback)
        response = fcdialog.run()
        fcdialog.hide()
        if(response == gtk.RESPONSE_ACCEPT):
            filename = fcdialog.get_filename()
            fcdialog.destroy()
            return filename
        else:
            fcdialog.destroy()
            return None

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

    def validate(self, page_num):
        if page_num == PAGE_INTRO:
            if self.get_config_hardware_type() == None:
                self._validation_error_box(_("Hardware Type Required"), \
                                           _("You must specify what type of hardware to add"))
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
            if d.is_conflict_disk(self.vm.get_connection().vmm) is True:
               res = self._yes_no_box(_('Disk "%s" is already in use by another guest!' % disk), \
                                               _("Do you really want to use the disk ?"))
               return res
           
            if self.window.get_widget("target-device").get_active() == -1:
               self._validation_error_box(_("Target Device Required"),
                                          _("You must select a target device for the disk"))
               return False

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

            if self.window.get_widget("mac-address").get_active():
                mac= self.window.get_widget("create-mac-address").get_text()
                if len(mac) != 17:
                    self._validation_error_box(_("Invalid MAC address"), \
                                               _("MAC adrress must be 17 characters"))
                    return False
                if re.match("^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$",mac) == None:
                    self._validation_error_box(_("Invalid MAC address"), \
                                               _("MAC address must be a form such as AA:BB:CC:DD:EE:FF, and MAC adrress may contain numeric and alphabet of A-F(a-f) and ':' characters only"))
                    return False
                hostdevs = virtinst.util.get_host_network_devices()
                for hostdev in hostdevs:
                    if mac.lower() == hostdev[4]:
                        return self._validation_error_box(_('MAC address "%s" is already in use by the host') % mac, \
                                                          _("Please enter a different MAC address or select no fixed MAC address"))
                vms = []
                for domains in self.vm.get_connection().vms.values():
                    vms.append(domains.vm)

                # get inactive Domains
                inactive_vm = []
                names = self.vm.get_connection().vmm.listDefinedDomains()
                for name in names:
                    vm = self.vm.get_connection().vmm.lookupByName(name)
                    inactive_vm.append(vm)

                vnic = virtinst.VirtualNetworkInterface(macaddr=mac)
                if (vnic.countMACaddr(vms) - vnic.countMACaddr(inactive_vm)) > 0:
                    return self._validation_error_box(_('MAC address "%s" is already in use by an active guest') % mac, \
                                                      _("Please enter a different MAC address or select no fixed MAC address"))
                elif vnic.countMACaddr(inactive_vm) > 0:
                    return self._yes_no_box(_('MAC address "%s" is already in use by another inactive guest!') % mac, \
                                            _("Do you really want to use the MAC address ?"))

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

    def populate_network_model(self, model):
        model.clear()
        for uuid in self.vm.get_connection().list_net_uuids():
            net = self.vm.get_connection().get_net(uuid)
            model.append([net.get_label(), net.get_name()])

    def populate_device_model(self, model):
        model.clear()
        hasShared = False
        for name in self.vm.get_connection().list_net_device_paths():
            net = self.vm.get_connection().get_net_device(name)
            if net.is_shared():
                hasShared = True
                model.append(["%s (%s %s)" % (net.get_name(), _("Bridge"), net.get_bridge()), True])
            else:
                model.append(["%s (%s)" % (net.get_name(), _("Not bridged")), False])
        return hasShared


    def populate_target_device_model(self, model):
        model.clear()
        if self.vm.is_hvm():
            model.append(["hd", 4, virtinst.VirtualDisk.DEVICE_DISK, gtk.STOCK_HARDDISK, "IDE disk"])
            model.append(["hd", 4, virtinst.VirtualDisk.DEVICE_CDROM, gtk.STOCK_CDROM, "IDE cdrom"])
            model.append(["fd", 2, virtinst.VirtualDisk.DEVICE_FLOPPY, gtk.STOCK_FLOPPY, "Floppy disk"])
            model.append(["sd", 7, virtinst.VirtualDisk.DEVICE_DISK, gtk.STOCK_HARDDISK, "SCSI disk"])
            if self.vm.get_connection().get_type().lower() == "xen":
                model.append(["xvd", 26, virtinst.VirtualDisk.DEVICE_DISK, gtk.STOCK_HARDDISK, "Virtual disk"])
            #model.append(["usb", virtinst.VirtualDisk.DEVICE_DISK, gtk.STOCK_HARDDISK, "USB disk"])
        else:
            model.append(["xvd", 26, virtinst.VirtualDisk.DEVICE_DISK, gtk.STOCK_HARDDISK, "Virtual disk"])

    def is_sparse_file(self):
        if self.window.get_widget("non-sparse").get_active():
            return False
        else:
            return True

    def show_help(self, src):
        # help to show depends on the notebook page, yahoo
        page = self.window.get_widget("create-pages").get_current_page()
        if page == PAGE_INTRO:
            self.emit("action-show-help", "virt-manager-create-wizard")
        elif page == PAGE_DISK:
            self.emit("action-show-help", "virt-manager-storage-space")
        elif page == PAGE_NETWORK:
            self.emit("action-show-help", "virt-manager-network")

gobject.type_register(vmmAddHardware)

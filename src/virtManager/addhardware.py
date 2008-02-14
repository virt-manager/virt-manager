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
import re
import subprocess
import urlgrabber.progress as progress
import tempfile
import logging
import dbus
import traceback
import statvfs

from virtManager.asyncjob import vmmAsyncJob
from virtManager.error import vmmErrorDialog
from virtManager.createmeter import vmmCreateMeter

VM_STORAGE_PARTITION = 1
VM_STORAGE_FILE = 2

DEFAULT_STORAGE_FILE_SIZE = 500

PAGE_INTRO = 0
PAGE_DISK = 1
PAGE_NETWORK = 2
PAGE_INPUT = 3
PAGE_GRAPHICS = 4
PAGE_SUMMARY = 5

class vmmAddHardware(gobject.GObject):
    __gsignals__ = {
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, [str]),
        }
    def __init__(self, config, vm):
        self.__gobject_init__()
        self.config = config
        self.vm = vm
        self._net = None
        self._disk = None
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
            "on_graphics_type_changed": self.change_graphics_type,
            "on_graphics_port_auto_toggled": self.change_port_auto,
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
        device_model = gtk.ListStore(str, str, bool)
        device_list.set_model(device_model)
        text = gtk.CellRendererText()
        device_list.pack_start(text, True)
        device_list.add_attribute(text, 'text', 1)
        device_list.add_attribute(text, 'sensitive', 2)

        target_list = self.window.get_widget("target-device")
        target_model = gtk.ListStore(str, int, str, str, str)
        target_list.set_model(target_model)
        icon = gtk.CellRendererPixbuf()
        target_list.pack_start(icon, False)
        target_list.add_attribute(icon, 'stock-id', 3)
        text = gtk.CellRendererText()
        target_list.pack_start(text, True)
        target_list.add_attribute(text, 'text', 4)

        input_list = self.window.get_widget("input-type")
        input_model = gtk.ListStore(str, str, str, bool)
        input_list.set_model(input_model)
        text = gtk.CellRendererText()
        input_list.pack_start(text, True)
        input_list.add_attribute(text, 'text', 0)
        input_list.add_attribute(text, 'sensitive', 3)

        graphics_list = self.window.get_widget("graphics-type")
        graphics_model = gtk.ListStore(str,str)
        graphics_list.set_model(graphics_model)
        text = gtk.CellRendererText()
        graphics_list.pack_start(text, True)
        graphics_list.add_attribute(text, 'text', 0)

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
        self.change_port_auto()
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

        input_box = self.window.get_widget("input-type")
        self.populate_input_model(input_box.get_model())
        input_box.set_active(0)

        graphics_box = self.window.get_widget("graphics-type")
        self.populate_graphics_model(graphics_box.get_model())
        graphics_box.set_active(0)
        self.window.get_widget("graphics-address").set_active(False)
        self.window.get_widget("graphics-port-auto").set_active(True)
        self.window.get_widget("graphics-password").set_text("")

        model = self.window.get_widget("hardware-type").get_model()
        model.clear()
        model.append(["Storage device", gtk.STOCK_HARDDISK, PAGE_DISK])
        # Can't use shared or virtual networking as regular user
        # Can only have one usermode network device
        if (os.getuid() == 0 or
            (self.vm.get_connection().get_type().lower() == "qemu" and
             len(self.vm.get_network_devices()) == 0)):
            model.append(["Network card", gtk.STOCK_NETWORK, PAGE_NETWORK])

        # Can only customize HVM guests, no Xen PV
        if self.vm.is_hvm():
            model.append(["Input device", gtk.STOCK_INDEX, PAGE_INPUT])
        model.append(["Graphics device", gtk.STOCK_SELECT_COLOR, PAGE_GRAPHICS])


    def forward(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        if(self.validate(notebook.get_current_page()) != True):
            return

        hwtype = self.get_config_hardware_type()
        if notebook.get_current_page() == PAGE_INTRO and \
           (hwtype != PAGE_NETWORK or os.getuid() == 0):
            notebook.set_current_page(hwtype)
        else:
            notebook.set_current_page(PAGE_SUMMARY)
            self.window.get_widget("create-finish").show()
            self.window.get_widget("create-forward").hide()
        self.window.get_widget("create-back").set_sensitive(True)

    def back(self, ignore=None):
        notebook = self.window.get_widget("create-pages")

        if notebook.get_current_page() == PAGE_SUMMARY:
            hwtype = self.get_config_hardware_type()
            if hwtype == PAGE_NETWORK and os.getuid() != 0:
                notebook.set_current_page(PAGE_INTRO)
            else:
                notebook.set_current_page(hwtype)
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
        if not self.window.get_widget("storage-file-size").get_editable():
            return None
        else:
            return self.window.get_widget("storage-file-size").get_value()

    def get_config_disk_target(self):
        target = self.window.get_widget("target-device")
        node = target.get_model().get_value(target.get_active_iter(), 0)
        maxnode = target.get_model().get_value(target.get_active_iter(), 1)
        device = target.get_model().get_value(target.get_active_iter(), 2)
        return node, maxnode, device

    def get_config_input(self):
        target = self.window.get_widget("input-type")
        label = target.get_model().get_value(target.get_active_iter(), 0)
        type = target.get_model().get_value(target.get_active_iter(), 1)
        bus = target.get_model().get_value(target.get_active_iter(), 2)
        return label, type, bus

    def get_config_graphics(self):
        type = self.window.get_widget("graphics-type")
        if type.get_active_iter() is None:
            return None
        return type.get_model().get_value(type.get_active_iter(), 1)

    def get_config_vnc_port(self):
        port = self.window.get_widget("graphics-port")
        portAuto = self.window.get_widget("graphics-port-auto")
        if portAuto.get_active():
            return -1
        return int(port.get_value())

    def get_config_vnc_address(self):
        addr = self.window.get_widget("graphics-address")
        if addr.get_active():
            return "0.0.0.0"
        return "127.0.0.1"

    def get_config_vnc_password(self):
        pw = self.window.get_widget("graphics-password")
        return pw.get_text()

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
            target = self.window.get_widget("target-device")
            if target.get_active() == -1:
                self.populate_target_device_model(target.get_model())
        elif page_number == PAGE_NETWORK:
            pass
        elif page_number == PAGE_SUMMARY:
            hwpage = self.get_config_hardware_type()
            self.window.get_widget("summary-disk").hide()
            self.window.get_widget("summary-network").hide()
            self.window.get_widget("summary-input").hide()
            self.window.get_widget("summary-graphics").hide()

            if hwpage == PAGE_DISK:
                self.window.get_widget("summary-disk").show()
                self.window.get_widget("summary-disk-image").set_text(self.get_config_disk_image())
                disksize = self.get_config_disk_size()
                if disksize != None:
                    self.window.get_widget("summary-disk-size").set_text(str(int(disksize)) + " MB")
                else:
                    self.window.get_widget("summary-disk-size").set_text("-")
            elif hwpage == PAGE_NETWORK:
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
            elif hwpage == PAGE_INPUT:
                self.window.get_widget("summary-input").show()
                input = self.get_config_input()
                self.window.get_widget("summary-input-type").set_text(input[0])
                if input[1] == "tablet":
                    self.window.get_widget("summary-input-mode").set_text(_("Absolute movement"))
                else:
                    self.window.get_widget("summary-input-mode").set_text(_("Relative movement"))
            elif hwpage == PAGE_GRAPHICS:
                self.window.get_widget("summary-graphics").show()
                graphics = self.get_config_graphics()
                if graphics == "vnc":
                    self.window.get_widget("summary-graphics-type").set_text("VNC server")
                else:
                    self.window.get_widget("summary-graphics-type").set_text("Local SDL window")
                if graphics == "vnc":
                    self.window.get_widget("summary-graphics-address").set_text(self.get_config_vnc_address())
                    if self.get_config_vnc_port() == -1:
                        self.window.get_widget("summary-graphics-port").set_text(_("Automatically allocated"))
                    else:
                        self.window.get_widget("summary-graphics-port").set_text(str(self.get_config_vnc_port()))
                    if self.get_config_vnc_password() is not None and self.get_config_vnc_password() != "":
                        self.window.get_widget("summary-graphics-password").set_text(_("Yes"))
                    else:
                        self.window.get_widget("summary-graphics-password").set_text(_("Yes"))
                else:
                    self.window.get_widget("summary-graphics-address").set_text(_("N/A"))
                    self.window.get_widget("summary-graphics-port").set_text(_("N/A"))
                    self.window.get_widget("summary-graphics-password").set_text(_("N/A"))

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
        elif hw == PAGE_INPUT:
            self.add_input()
        elif hw == PAGE_GRAPHICS:
            self.add_graphics()

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
        if self._net is None and os.getuid() != 0:
            self._net = virtinst.VirtualNetworkInterface(type="user")
        self._net.setup(self.vm.get_connection().vmm)
        self.add_device(self._net.get_xml_config())

    def add_input(self):
        input = self.get_config_input()
        xml = "<input type='%s' bus='%s'/>\n" % (input[1], input[2])
        self.add_device(xml)

    def add_graphics(self):
        graphics = self.get_config_graphics()
        if graphics == "vnc":
            port = self.get_config_vnc_port()
            pw = self.get_config_vnc_password()
            addr = self.get_config_vnc_address()
            if addr is None or addr == "":
                if pw is None or pw == "":
                    xml = "<graphics type='vnc' port='%d'/>" % (port,)
                else:
                    xml = "<graphics type='vnc' port='%d' passwd='%s'/>" % (port,pw)
            else:
                if pw is None or pw == "":
                    xml = "<graphics type='vnc' listen='%s' port='%d'/>" % (addr,port)
                else:
                    xml = "<graphics type='vnc' listen='%s' port='%d' passwd='%s'/>" % (addr,port,pw)
        else:
            xml = "<graphics type='sdl'/>"
        self.add_device(xml)

    def add_storage(self):
        node, maxnode, device = self.get_config_disk_target()

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
            value =  _("There are no more available virtual disk device nodes")
            details = "Unable to complete install: '%s'" % value
            self.install_error = _("Unable to complete install: '%s'") % value
            self.install_details = details
            return

        progWin = vmmAsyncJob(self.config, self.do_file_allocate, [self._disk],
                              title=_("Creating Storage File"),
                              text=_("Allocation of disk storage may take a few minutes " + \
                                     "to complete."))
        progWin.run()

        if self.install_error == None:
            self.add_device(self._disk.get_xml_config(node))

    def add_device(self, xml):
        logging.debug("Adding device " + xml)
        try:
            self.vm.add_device(xml)
        except Exception, e:
            details = "Unable to complete install: '%s'" % \
                      "".join(traceback.format_exc())
            self.install_error = _("Unable to complete install: '%s'") \
                                 % str(e)
            self.install_details = details
            logging.error(details)

    def do_file_allocate(self, disk, asyncjob):
        meter = vmmCreateMeter(asyncjob)
        try:
            logging.debug("Starting background file allocate process")
            disk.setup(meter)
            logging.debug("Allocation completed")
        except Exception, e:
            details = "Unable to complete install: '%s'" % \
                      "".join(traceback.format_exc())
            self.install_error = _("Unable to complete install: '%s'") \
                                 % str(e)
            self.install_details = details
            logging.error(details)

    def browse_storage_partition_address(self, src, ignore=None):
        part = self._browse_file(_("Locate Storage Partition"), "/dev")
        if part != None:
            self.window.get_widget("storage-partition-address").set_text(part)

    def browse_storage_file_address(self, src, ignore=None):
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

    def change_graphics_type(self,ignore=None):
        graphics = self.get_config_graphics()
        if graphics == "vnc":
            self.window.get_widget("graphics-port-auto").set_sensitive(True)
            self.window.get_widget("graphics-address").set_sensitive(True)
            self.window.get_widget("graphics-password").set_sensitive(True)
            self.change_port_auto()
        else:
            self.window.get_widget("graphics-port").set_sensitive(False)
            self.window.get_widget("graphics-port-auto").set_sensitive(False)
            self.window.get_widget("graphics-address").set_sensitive(False)
            self.window.get_widget("graphics-password").set_sensitive(False)

    def change_port_auto(self,ignore=None):
        if self.window.get_widget("graphics-port-auto").get_active():
            self.window.get_widget("graphics-port").set_sensitive(False)
        else:
            self.window.get_widget("graphics-port").set_sensitive(True)

    def validate(self, page_num):
        if page_num == PAGE_INTRO:
            if self.get_config_hardware_type() == None:
                self._validation_error_box(_("Hardware Type Required"), \
                                           _("You must specify what type of hardware to add"))
                return False
        elif page_num == PAGE_DISK:
            path = self.get_config_disk_image()
            if path == None or len(path) == 0:
                self._validation_error_box(_("Storage Path Required"), \
                                           _("You must specify a partition or a file for disk storage."))
                return False
            
            if self.window.get_widget("target-device").get_active() == -1:
                self._validation_error_box(_("Target Device Required"),
                                           _("You must select a target device for the disk"))
                return False

            node, nodemax, device = self.get_config_disk_target()
            if self.window.get_widget("storage-partition").get_active():
                type = virtinst.VirtualDisk.TYPE_BLOCK
            else:
                type = virtinst.VirtualDisk.TYPE_FILE
                   
            if not self.window.get_widget("storage-partition").get_active():
                size = self.get_config_disk_size()
                if not os.path.exists(path):
                    dir = os.path.dirname(os.path.abspath(path))
                    if not os.path.exists(dir):
                        self._validation_error_box(_("Storage Path Does not exist"),
                                                   _("The directory %s containing the disk image does not exist") % dir)
                        return False
                    else:
                        vfs = os.statvfs(dir)
                        avail = vfs[statvfs.F_FRSIZE] * vfs[statvfs.F_BAVAIL]
                        need = size * 1024 * 1024
                        if need > avail:
                            if self.is_sparse_file():
                                res = self._yes_no_box(_("Not Enough Free Space"),
                                                       _("The filesystem will not have enough free space to fully allocate the sparse file when the guest is running. Use this path anyway?"))
                                if not res:
                                    return False
                            else:
                                self._validation_error_box(_("Not Enough Free Space"),
                                                           _("There is not enough free space to create the disk"))
                                return False

            # Build disk object
            filesize = self.get_config_disk_size()
            if self.get_config_disk_size() != None:
                filesize = self.get_config_disk_size() / 1024.0
            readonly = False
            if device == virtinst.VirtualDisk.DEVICE_CDROM:
                readonly=True
                
            try:    
                self._disk = virtinst.VirtualDisk(self.get_config_disk_image(),
                                                  filesize,
                                                  type = type,
                                                  sparse = self.is_sparse_file(),
                                                  readOnly=readonly,
                                                  device=device)
                if self._disk.type == virtinst.VirtualDisk.TYPE_FILE and \
                   not self.vm.is_hvm() and virtinst.util.is_blktap_capable():
                    self._disk.driver_name = virtinst.VirtualDisk.DRIVER_TAP
            except ValueError, e:
                self._validation_error_box(_("Invalid Storage Parameters"), \
                                            str(e))
                return False
            
            if self._disk.is_conflict_disk(self.vm.get_connection().vmm) is True:
                res = self._yes_no_box(_('Disk "%s" is already in use by another guest!' % self._disk), \
                                       _("Do you really want to use the disk ?"))
                return res
        elif page_num == PAGE_NETWORK:
            net = self.get_config_network()
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

            mac = self.get_config_macaddr()
            if self.window.get_widget("mac-address").get_active():

                if mac is None or len(mac) == 0:
                    self._validation_error_box(_("Invalid MAC address"), \
                                               _("No MAC address was entered. Please enter a valid MAC address."))
                    return False
                
                try:     
                    self._net = virtinst.VirtualNetworkInterface(macaddr=mac)
                except ValueError, e:
                    self._validation_error_box(_("Invalid MAC address"), \
                                               str(e))
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

                if (self._net.countMACaddr(vms) - self._net.countMACaddr(inactive_vm)) > 0:
                    return self._validation_error_box(_('MAC address "%s" is already in use by an active guest') % mac, \
                                                      _("Please enter a different MAC address or select no fixed MAC address"))
                elif self._net.countMACaddr(inactive_vm) > 0:
                    return self._yes_no_box(_('MAC address "%s" is already in use by another inactive guest!') % mac, \
                                            _("Do you really want to use the MAC address ?"))

            
            try:
                if net[0] == "bridge":
                    self._net = virtinst.VirtualNetworkInterface(macaddr=mac, 
                                                                 type=net[0], 
                                                                 bridge=net[1])
                elif net[0] == "network":
                    self._net = virtinst.VirtualNetworkInterface(macaddr=mac, 
                                                                 type=net[0], 
                                                                 network=net[1])
                else:
                    raise ValueError, _("Unsupported networking type") + net[0]
            except ValueError, e:
                self._validation_error_box(_("Invalid Network Parameter"), \
                                           str(e))
                return False

        return True

    def _validation_error_box(self, text1, text2=None):
        message_box = gtk.MessageDialog(self.window.get_widget("vmm-add-hardware"), \
                                                0, \
                                                gtk.MESSAGE_ERROR, \
                                                gtk.BUTTONS_OK, \
                                                text1)
        if text2 != None:
            message_box.format_secondary_text(text2)
        message_box.run()
        message_box.destroy()

    def _yes_no_box(self, text1, text2=None):
        message_box = gtk.MessageDialog(self.window.get_widget("vmm-add-hardware"), \
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
                model.append([net.get_bridge(), "%s (%s %s)" % (net.get_name(), _("Bridge"), net.get_bridge()), True])
            else:
                model.append([net.get_bridge(), "%s (%s)" % (net.get_name(), _("Not bridged")), False])
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

    def populate_input_model(self, model):
        model.clear()
        model.append([_("EvTouch USB Graphics Tablet"), "tablet", "usb", True])
        # XXX libvirt needs to support 'model' for input devices to distinguish
        # wacom from evtouch tablets
        #model.append([_("Wacom Graphics Tablet"), "tablet", "usb", True])
        model.append([_("Generic USB Mouse"), "mouse", "usb", True])

    def populate_graphics_model(self, model):
        model.clear()
        model.append([_("VNC server"), "vnc"])
        # XXX inclined to just not give this choice at all
        model.append([_("Local SDL window"), "sdl"])

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

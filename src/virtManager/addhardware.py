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
import libvirt
import virtinst
import os
import logging
import traceback

import virtManager.util as vmmutil
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
        self._dev = None
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-add-hardware.glade", "vmm-add-hardware", domain="virt-manager")
        self.topwin = self.window.get_widget("vmm-add-hardware")
        self.err = vmmErrorDialog(self.topwin,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))
        self.install_error = ""
        self.install_details = ""

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
            "on_graphics_keymap_toggled": self.change_keymap,
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

        netmodel_list  = self.window.get_widget("net-model")
        netmodel_model = gtk.ListStore(str, str)
        netmodel_list.set_model(netmodel_model)
        text = gtk.CellRendererText()
        netmodel_list.pack_start(text, True)
        netmodel_list.add_attribute(text, 'text', 1)

        target_list = self.window.get_widget("target-device")
        target_model = gtk.ListStore(str, str, str, str)
        target_list.set_model(target_model)
        icon = gtk.CellRendererPixbuf()
        target_list.pack_start(icon, False)
        target_list.add_attribute(icon, 'stock-id', 2)
        text = gtk.CellRendererText()
        target_list.pack_start(text, True)
        target_list.add_attribute(text, 'text', 3)

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
        self.window.get_widget("storage-file-size").set_value(4000)
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
        res = self.populate_device_model(dev_box.get_model())
        if res[0]:
            dev_box.set_active(res[1])
        else:
            dev_box.set_active(-1)

        self.window.get_widget("net-model").set_active(0)

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
        self.window.get_widget("graphics-keymap").set_text("")
        self.window.get_widget("graphics-keymap-chk").set_active(True)

        model = self.window.get_widget("hardware-type").get_model()
        model.clear()
        model.append(["Storage", gtk.STOCK_HARDDISK, PAGE_DISK])
        # Can't use shared or virtual networking in qemu:///session
        # Can only have one usermode network device
        if not self.vm.get_connection().is_qemu_session() or \
           len(self.vm.get_network_devices()) == 0:
            model.append(["Network", gtk.STOCK_NETWORK, PAGE_NETWORK])

        # Can only customize HVM guests, no Xen PV
        if self.vm.is_hvm():
            model.append(["Input", gtk.STOCK_INDEX, PAGE_INPUT])
        model.append(["Graphics", gtk.STOCK_SELECT_COLOR, PAGE_GRAPHICS])


    def forward(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        try:
            if(self.validate(notebook.get_current_page()) != True):
                return
        except Exception, e:
            self.err.show_err(_("Uncaught error validating hardware input: %s") % str(e),
                              "".join(traceback.format_exc()))
            return

        hwtype = self.get_config_hardware_type()
        if notebook.get_current_page() == PAGE_INTRO and \
           (hwtype != PAGE_NETWORK or \
            not self.vm.get_connection().is_qemu_session()):
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
            if hwtype == PAGE_NETWORK and \
               self.vm.get_connection().is_qemu_session():
                notebook.set_current_page(PAGE_INTRO)
            else:
                notebook.set_current_page(hwtype)
            self.window.get_widget("create-finish").hide()
        else:
            notebook.set_current_page(PAGE_INTRO)
            self.window.get_widget("create-back").set_sensitive(False)
        self.window.get_widget("create-forward").show()

    def get_config_hardware_type(self):
        _type = self.window.get_widget("hardware-type")
        if _type.get_active_iter() == None:
            return None
        return _type.get_model().get_value(_type.get_active_iter(), 2)

    def get_config_disk_image(self):
        if self.window.get_widget("storage-partition").get_active():
            return self.window.get_widget("storage-partition-address").get_text()
        else:
            return self.window.get_widget("storage-file-address").get_text()

    def get_config_partition_size(self):
        try:
            partition_address = self.get_config_disk_image()
            fd = open(partition_address,"rb")
            fd.seek(0,2)
            block_size = fd.tell() / 1024 / 1024
            return block_size
        except Exception:
            details = "Unable to verify partition size: '%s'" % \
                      "".join(traceback.format_exc())
            logging.error(details)
            return None
        
    def get_config_disk_size(self):
        if self.window.get_widget("storage-partition").get_active():
            return self.get_config_partition_size()
        if not self.window.get_widget("storage-file-backed").get_active():
            return None
        if not self.window.get_widget("storage-file-size").get_editable():
            return None
        else:
            return self.window.get_widget("storage-file-size").get_value()

    def get_config_disk_target(self):
        target = self.window.get_widget("target-device")
        bus = target.get_model().get_value(target.get_active_iter(), 0)
        device = target.get_model().get_value(target.get_active_iter(), 1)
        return bus, device

    def get_config_input(self):
        target = self.window.get_widget("input-type")
        label = target.get_model().get_value(target.get_active_iter(), 0)
        _type = target.get_model().get_value(target.get_active_iter(), 1)
        bus = target.get_model().get_value(target.get_active_iter(), 2)
        return label, _type, bus

    def get_config_graphics(self):
        _type = self.window.get_widget("graphics-type")
        if _type.get_active_iter() is None:
            return None
        return _type.get_model().get_value(_type.get_active_iter(), 1)

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

    def get_config_keymap(self):
        g = self.window.get_widget("graphics-keymap")
        if g.get_property("sensitive") and g.get_text() != "":
            return g.get_text()
        else:
            return None

    def get_config_network(self):
        if self.vm.get_connection().is_qemu_session():
            return ["user"]

        if self.window.get_widget("net-type-network").get_active():
            net = self.window.get_widget("net-network")
            model = net.get_model()
            return ["network", model.get_value(net.get_active_iter(), 0)]
        else:
            dev = self.window.get_widget("net-device")
            model = dev.get_model()
            return ["bridge", model.get_value(dev.get_active_iter(), 0)]

    def get_config_net_model(self):
        model = self.window.get_widget("net-model")
        modelxml = model.get_model().get_value(model.get_active_iter(), 0)
        modelstr = model.get_model().get_value(model.get_active_iter(), 1)
        return modelxml, modelstr

    def get_config_macaddr(self):
        macaddr = None
        if self.window.get_widget("mac-address").get_active():
            macaddr = self.window.get_widget("create-mac-address").get_text()
        return macaddr

    def page_changed(self, notebook, page, page_number):
        remote = self.vm.get_connection().is_remote()
        if page_number == PAGE_DISK:
            self.change_storage_type()
            target = self.window.get_widget("target-device")
            if target.get_active() == -1:
                self.populate_target_device_model(target.get_model())
                target.set_active(0)

            self.window.get_widget("storage-partition-address-browse").set_sensitive(not remote)
            self.window.get_widget("storage-file-address-browse").set_sensitive(not remote)

        elif page_number == PAGE_NETWORK:
            netmodel = self.window.get_widget("net-model")
            if netmodel.get_active() == -1:
                self.populate_network_model_model(netmodel.get_model())
                netmodel.set_active(0)

            if remote:
                self.window.get_widget("net-type-network").set_active(True)
                self.window.get_widget("net-type-device").set_active(False)
                self.window.get_widget("net-type-device").set_sensitive(False)
                self.window.get_widget("net-device").set_active(-1)
            else:
                self.window.get_widget("net-type-device").set_sensitive(True)
            self.change_network_type()
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
                model = self.get_config_net_model()[1]
                self.window.get_widget("summary-net-model").set_text(model)
            elif hwpage == PAGE_INPUT:
                self.window.get_widget("summary-input").show()
                inp = self.get_config_input()
                self.window.get_widget("summary-input-type").set_text(inp[0])
                if inp[1] == "tablet":
                    self.window.get_widget("summary-input-mode").set_text(_("Absolute movement"))
                else:
                    self.window.get_widget("summary-input-mode").set_text(_("Relative movement"))
            elif hwpage == PAGE_GRAPHICS:
                self.window.get_widget("summary-graphics").show()
                graphics = self.get_config_graphics()
                if graphics == "vnc":
                    self.window.get_widget("summary-graphics-type").set_text(_("VNC server"))
                else:
                    self.window.get_widget("summary-graphics-type").set_text(_("Local SDL window"))
                if graphics == "vnc":
                    self.window.get_widget("summary-graphics-address").set_text(self.get_config_vnc_address())
                    if self.get_config_vnc_port() == -1:
                        self.window.get_widget("summary-graphics-port").set_text(_("Automatically allocated"))
                    else:
                        self.window.get_widget("summary-graphics-port").set_text(str(self.get_config_vnc_port()))
                    if self.get_config_vnc_password() is not None and self.get_config_vnc_password() != "":
                        self.window.get_widget("summary-graphics-password").set_text(_("Yes"))
                    else:
                        self.window.get_widget("summary-graphics-password").set_text(_("No"))
                    if self.get_config_keymap() != "":
                        self.window.get_widget("summary-graphics-keymap").set_text(str(self.get_config_keymap()))
                    else:
                        self.window.get_widget("summary-graphics-keymap").set_text(_("Same as host"))

                else:
                    self.window.get_widget("summary-graphics-address").set_text(_("N/A"))
                    self.window.get_widget("summary-graphics-port").set_text(_("N/A"))
                    self.window.get_widget("summary-graphics-password").set_text(_("N/A"))
                    self.window.get_widget("summary-graphics-keymap").set_text(_("N/A"))

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
            self.err.show_err(self.install_error, self.install_details)
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
        if self._dev is None and self.vm.get_connection().is_qemu_session():
            self._dev = virtinst.VirtualNetworkInterface(type="user")
        self._dev.setup(self.vm.get_connection().vmm)
        self.add_device(self._dev.get_xml_config())

    def add_input(self):
        inp = self.get_config_input()
        xml = "<input type='%s' bus='%s'/>\n" % (inp[1], inp[2])
        self.add_device(xml)

    def add_graphics(self):
        self.add_device(self._dev.get_xml_config())

    def add_storage(self):
        used = []
        for d in self.vm.get_disk_devices():
            used.append(d[3])

        try:
            self._dev.generate_target(used)
        except Exception, e:
            details = _("Unable to complete install: ") + \
                      "".join(traceback.format_exc())
            self.install_error = _("Unable to complete install: '%s'") % str(e)
            self.install_details = details
            return

        progWin = vmmAsyncJob(self.config, self.do_file_allocate, [self._dev],
                              title=_("Creating Storage File"),
                              text=_("Allocation of disk storage may take a few minutes " + \
                                     "to complete."))
        progWin.run()

        if self.install_error == None:
            self.add_device(self._dev.get_xml_config())

    def add_device(self, xml):
        logging.debug("Adding device:\n" + xml)

        attach_err = False
        try:
            self.vm.attach_device(xml)
        except Exception, e:
            logging.debug("Device could not be hotplugged: %s" % str(e))
            attach_err = True

        if attach_err:
            if not self.err.yes_no(_("Are you sure you want to add this "
                                     "device?"),
                                   _("This device could not be attached to "
                                     "the running machine. Would you like to "
                                     "make the device available after the "
                                     "next VM shutdown?\n\n"
                                     "Warning: this will overwrite any "
                                     "other changes that require a VM "
                                     "reboot.")):
                return

        if self.vm.is_active() and not attach_err:
            # Attach device should alter xml for us
            return

        try:
            self.vm.add_device(xml)
        except Exception, e:
            details = _("Unable to complete install: '%s'") % \
                        "".join(traceback.format_exc())
            self.install_error = _("Unable to complete install: '%s'") % str(e)
            self.install_details = details
            logging.error(details)

    def do_file_allocate(self, disk, asyncjob):
        meter = vmmCreateMeter(asyncjob)
        newconn = None
        try:
            # If creating disk via storage API, we need to thread
            # off a new connection
            if disk.vol_install:
                newconn = libvirt.open(disk.conn.getURI())
                disk.conn = newconn
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
        filename = self._browse_file(_("Locate or Create New Storage File"), \
                                       folder=folder, confirm_overwrite=True)
        if filename != None:
            self.window.get_widget("storage-file-address").set_text(filename)

    def _browse_file(self, dialog_name, folder=None, _type=None,
                     confirm_overwrite=False):
        # user wants to browse for an ISO
        fcdialog = gtk.FileChooserDialog(dialog_name,
                                         self.window.get_widget("vmm-add-hardware"),
                                         gtk.FILE_CHOOSER_ACTION_OPEN,
                                         (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                          gtk.STOCK_OPEN, gtk.RESPONSE_ACCEPT),
                                         None)
        fcdialog.set_default_response(gtk.RESPONSE_ACCEPT)
        if _type != None:
            f = gtk.FileFilter()
            f.add_pattern("*." + _type)
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
        filename = self.get_config_disk_image()
        if filename != None and len(filename) > 0 and \
           (self.vm.get_connection().is_remote() or
            not os.path.exists(filename)):
            self.window.get_widget("storage-file-size").set_sensitive(True)
            self.window.get_widget("non-sparse").set_sensitive(True)
            size = self.get_config_disk_size()
            if size == None:
                size = 4000
            self.window.get_widget("storage-file-size").set_value(size)
        else:
            self.window.get_widget("storage-file-size").set_sensitive(False)
            self.window.get_widget("non-sparse").set_sensitive(False)
            if os.path.isfile(filename):
                size = os.path.getsize(filename)/(1024*1024)
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
            self.window.get_widget("graphics-keymap-chk").set_sensitive(True)
            self.change_port_auto()
        else:
            self.window.get_widget("graphics-port").set_sensitive(False)
            self.window.get_widget("graphics-port-auto").set_sensitive(False)
            self.window.get_widget("graphics-address").set_sensitive(False)
            self.window.get_widget("graphics-password").set_sensitive(False)
            self.window.get_widget("graphics-keymap-chk").set_sensitive(False)
            self.window.get_widget("graphics-keymap").set_sensitive(False)

    def change_port_auto(self,ignore=None):
        if self.window.get_widget("graphics-port-auto").get_active():
            self.window.get_widget("graphics-port").set_sensitive(False)
        else:
            self.window.get_widget("graphics-port").set_sensitive(True)

    def change_keymap(self, ignore=None):
        if self.window.get_widget("graphics-keymap-chk").get_active():
            self.window.get_widget("graphics-keymap").set_sensitive(False)
        else:
            self.window.get_widget("graphics-keymap").set_sensitive(True)

    def validate(self, page_num):
        if page_num == PAGE_INTRO:
            if self.get_config_hardware_type() == None:
                return self.err.val_err(_("Hardware Type Required"), \
                                        _("You must specify what type of hardware to add"))
            self._dev = None
        elif page_num == PAGE_DISK:
            path = self.get_config_disk_image()
            if path == None or len(path) == 0:
                return self.err.val_err(_("Storage Path Required"), \
                                        _("You must specify a partition or a file for disk storage."))

            if self.window.get_widget("target-device").get_active() == -1:
                return self.err.val_err(_("Target Device Required"),
                                        _("You must select a target device for the disk"))

            bus, device = self.get_config_disk_target()
            if self.window.get_widget("storage-partition").get_active():
                _type = virtinst.VirtualDisk.TYPE_BLOCK
            else:
                _type = virtinst.VirtualDisk.TYPE_FILE

            # Build disk object
            filesize = self.get_config_disk_size()
            if self.get_config_disk_size() != None:
                filesize = self.get_config_disk_size() / 1024.0
            readonly = False
            if device == virtinst.VirtualDisk.DEVICE_CDROM:
                readonly=True

            try:
                if os.path.dirname(os.path.abspath(path)) == \
                   vmmutil.DEFAULT_POOL_PATH:
                    vmmutil.build_default_pool(self.vm.get_connection().vmm)
                self._dev = virtinst.VirtualDisk(self.get_config_disk_image(),
                                                 filesize,
                                                 type = _type,
                                                 sparse=self.is_sparse_file(),
                                                 readOnly=readonly,
                                                 device=device,
                                                 bus=bus,
                                                 conn=self.vm.get_connection().vmm)
                if self._dev.type == virtinst.VirtualDisk.TYPE_FILE and \
                   not self.vm.is_hvm() and virtinst.util.is_blktap_capable():
                    self._dev.driver_name = virtinst.VirtualDisk.DRIVER_TAP
            except ValueError, e:
                return self.err.val_err(_("Invalid Storage Parameters"), str(e))

            ret = self._dev.is_size_conflict()
            if not ret[0] and ret[1]:
                res = self.err.yes_no(_("Not Enough Free Space"), ret[1])
                if not res:
                    return False

            if self._dev.is_conflict_disk(self.vm.get_connection().vmm) is True:
                res = self.err.yes_no(_('Disk "%s" is already in use by another guest!' % self._dev), \
                                      _("Do you really want to use the disk ?"))
                return res

        elif page_num == PAGE_NETWORK:
            net = self.get_config_network()
            if self.window.get_widget("net-type-network").get_active():
                if self.window.get_widget("net-network").get_active() == -1:
                    return self.err.val_err(_("Virtual Network Required"),
                                            _("You must select one of the virtual networks"))
            else:
                if self.window.get_widget("net-device").get_active() == -1:
                    return self.err.val_err(_("Physical Device Required"),
                                            _("You must select one of the physical devices"))

            mac = self.get_config_macaddr()
            if self.window.get_widget("mac-address").get_active():

                if mac is None or len(mac) == 0:
                    return self.err.val_err(_("Invalid MAC address"), \
                                            _("No MAC address was entered. Please enter a valid MAC address."))

                try:
                    self._dev = virtinst.VirtualNetworkInterface(macaddr=mac)
                except ValueError, e:
                    return self.err.val_err(_("Invalid MAC address"), str(e))

            model = self.get_config_net_model()[0]
            try:
                if net[0] == "bridge":
                    self._dev = virtinst.VirtualNetworkInterface(macaddr=mac,
                                                                 type=net[0],
                                                                 bridge=net[1])
                elif net[0] == "network":
                    self._dev = virtinst.VirtualNetworkInterface(macaddr=mac,
                                                                 type=net[0],
                                                                 network=net[1])
                else:
                    raise ValueError, _("Unsupported networking type") + net[0]

                self._dev.model = model
            except ValueError, e:
                return self.err.val_err(_("Invalid Network Parameter"), \
                                        str(e))

            conflict = self._dev.is_conflict_net(self.vm.get_connection().vmm)
            if conflict[0]:
                return self.err.val_err(_("Mac address collision"),\
                                        conflict[1])
            elif conflict[1] is not None:
                return self.err.yes_no(_("Mac address collision"),\
                                       conflict[1] + " " + _("Are you sure you want to use this address?"))

        elif page_num == PAGE_GRAPHICS:
            graphics = self.get_config_graphics()
            if graphics == "vnc":
                _type = virtinst.VirtualGraphics.TYPE_VNC
            else:
                _type = virtinst.VirtualGraphics.TYPE_SDL
            self._dev = virtinst.VirtualGraphics(type=_type)
            try:
                self._dev.port   = self.get_config_vnc_port()
                self._dev.passwd = self.get_config_vnc_password()
                self._dev.listen = self.get_config_vnc_address()
                self._dev.keymap = self.get_config_keymap()
            except ValueError, e:
                self.err.val_err(_("Graphics device parameter error"), str(e))

        return True

    def populate_network_model(self, model):
        model.clear()
        for uuid in self.vm.get_connection().list_net_uuids():
            net = self.vm.get_connection().get_net(uuid)
            model.append([net.get_label(), net.get_name()])

    def populate_device_model(self, model):
        model.clear()
        hasShared = False
        brIndex = -1
        for name in self.vm.get_connection().list_net_device_paths():
            net = self.vm.get_connection().get_net_device(name)
            if net.is_shared():
                hasShared = True
                if brIndex < 0:
                    brIndex = len(model)
                model.append([net.get_bridge(), "%s (%s %s)" % (net.get_name(), _("Bridge"), net.get_bridge()), True])
            else:
                model.append([net.get_bridge(), "%s (%s)" % (net.get_name(), _("Not bridged")), False])
        return (hasShared, brIndex)

    def populate_network_model_model(self, model):
        model.clear()

        # [xml value, label]
        model.append([None, _("Hypervisor default")])
        if self.vm.is_hvm():
            mod_list = [ "rtl8139", "ne2k_pci", "pcnet" ]
            if self.vm.get_type().lower() == "kvm":
                mod_list.append("e1000")
                mod_list.append("virtio")
            mod_list.sort()

            for m in mod_list:
                model.append([m, m])

    def populate_target_device_model(self, model):
        model.clear()
        #[bus, device, icon, desc]
        if self.vm.is_hvm():
            model.append(["ide", virtinst.VirtualDisk.DEVICE_DISK,
                          gtk.STOCK_HARDDISK, "IDE disk"])
            model.append(["ide", virtinst.VirtualDisk.DEVICE_CDROM,
                          gtk.STOCK_CDROM, "IDE cdrom"])
            model.append(["fdc", virtinst.VirtualDisk.DEVICE_FLOPPY,
                          gtk.STOCK_FLOPPY, "Floppy disk"])
            model.append(["scsi",virtinst.VirtualDisk.DEVICE_DISK,
                          gtk.STOCK_HARDDISK, "SCSI disk"])
            model.append(["usb", virtinst.VirtualDisk.DEVICE_DISK,
                          gtk.STOCK_HARDDISK, "USB disk"])
        if self.vm.get_type().lower() == "kvm":
            model.append(["virtio", virtinst.VirtualDisk.DEVICE_DISK,
                          gtk.STOCK_HARDDISK, "Virtio Disk"])
        if self.vm.get_connection().get_type().lower() == "xen":
            model.append(["xen", virtinst.VirtualDisk.DEVICE_DISK,
                          gtk.STOCK_HARDDISK, "Virtual disk"])

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

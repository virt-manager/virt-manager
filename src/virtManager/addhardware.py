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

import logging
import traceback

import gobject
import gtk
import gtk.gdk
import gtk.glade

import virtinst
from virtinst import (VirtualCharDevice, VirtualDevice, VirtualVideoDevice,
                      VirtualWatchdog)

import virtManager.util as util
import virtManager.uihelpers as uihelpers
from virtManager.asyncjob import vmmAsyncJob
from virtManager.error import vmmErrorDialog
from virtManager.createmeter import vmmCreateMeter
from virtManager.storagebrowse import vmmStorageBrowser

VM_STORAGE_PARTITION = 1
VM_STORAGE_FILE = 2

DEFAULT_STORAGE_FILE_SIZE = 500

PAGE_INTRO = 0
PAGE_DISK = 1
PAGE_NETWORK = 2
PAGE_INPUT = 3
PAGE_GRAPHICS = 4
PAGE_SOUND = 5
PAGE_HOSTDEV = 6
PAGE_CHAR = 7
PAGE_VIDEO = 8
PAGE_WATCHDOG = 9
PAGE_SUMMARY = 10

char_widget_mappings = {
    "source_path" : "char-path",
    "source_mode" : "char-mode",
    "source_host" : "char-host",
    "source_port" : "char-port",
    "bind_port": "char-bind-port",
    "bind_host": "char-bind-host",
    "protocol" : "char-use-telnet",
}

class vmmAddHardware(gobject.GObject):
    __gsignals__ = {
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, [str]),
        }
    def __init__(self, config, vm):
        self.__gobject_init__()
        self.config = config
        self.vm = vm
        self.conn = vm.get_connection()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-add-hardware.glade", "vmm-add-hardware", domain="virt-manager")
        self.topwin = self.window.get_widget("vmm-add-hardware")
        self.err = vmmErrorDialog(self.topwin,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))

        self.storage_browser = None

        # Host space polling
        self.host_storage_timer = None

        self._dev = None

        self.topwin.hide()
        self.window.signal_autoconnect({
            "on_create_pages_switch_page" : self.page_changed,
            "on_create_cancel_clicked" : self.close,
            "on_vmm_create_delete_event" : self.close,
            "on_create_back_clicked" : self.back,
            "on_create_forward_clicked" : self.forward,
            "on_create_finish_clicked" : self.finish,
            "on_create_help_clicked": self.show_help,

            "on_hardware_type_changed"  : self.hardware_type_changed,

            "on_config_storage_browse_clicked": self.browse_storage,
            "on_config_storage_select_toggled": self.toggle_storage_select,

            "on_mac_address_clicked" : self.change_macaddr_use,

            "on_graphics_type_changed": self.change_graphics_type,
            "on_graphics_port_auto_toggled": self.change_port_auto,
            "on_graphics_keymap_toggled": self.change_keymap,

            "on_host_device_type_changed": self.change_host_device_type,

            "on_char_device_type_changed": self.change_char_device_type,

            # Char dev info signals
            "char_device_type_focus": (self.update_doc, "char_type"),
            "char_path_focus_in": (self.update_doc, "source_path"),
            "char_mode_changed": (self.update_doc_changed, "source_mode"),
            "char_mode_focus"  : (self.update_doc, "source_mode"),
            "char_host_focus_in": (self.update_doc, "source_host"),
            "char_bind_host_focus_in": (self.update_doc, "bind_host"),
            "char_telnet_focus_in": (self.update_doc, "protocol"),
            })
        util.bind_escape_key_close(self)

        # XXX: Help docs useless/out of date
        self.window.get_widget("create-help").hide()

        finish_img = gtk.image_new_from_stock(gtk.STOCK_QUIT,
                                              gtk.ICON_SIZE_BUTTON)
        self.window.get_widget("create-finish").set_image(finish_img)

        self.set_initial_state()

    def update_doc(self, ignore1, ignore2, param):
        doc = self._build_doc_str(param)
        self.window.get_widget("char-info").set_markup(doc)

    def update_doc_changed(self, ignore1, param):
        # Wrapper for update_doc and 'changed' signal
        self.update_doc(None, None, param)

    def _build_doc_str(self, param, docstr=None):
        doc = ""
        doctmpl = "<i>%s</i>"

        if docstr:
            doc = doctmpl % (docstr)
        elif self._dev:
            devclass = self._dev.__class__
            if hasattr(devclass, param):
                doc = doctmpl % (getattr(devclass, param).__doc__)

        return doc

    def show(self):
        self.reset_state()
        self.topwin.present()

    def close(self, ignore1=None,ignore2=None):
        self.topwin.hide()
        self.remove_timers()
        return 1

    def remove_timers(self):
        try:
            if self.host_storage_timer:
                gobject.source_remove(self.host_storage_timer)
                self.host_storage_timer = None
        except:
            pass

    def is_visible(self):
        if self.topwin.flags() & gtk.VISIBLE:
            return 1
        return 0


    ##########################
    # Initialization methods #
    ##########################

    def set_initial_state(self):
        notebook = self.window.get_widget("create-pages")
        notebook.set_show_tabs(False)

        black = gtk.gdk.color_parse("#000")
        for num in range(PAGE_SUMMARY+1):
            name = "page" + str(num) + "-title"
            self.window.get_widget(name).modify_bg(gtk.STATE_NORMAL,black)

        # Main HW list
        hw_list = self.window.get_widget("hardware-type")
        # Name, icon name, page number, is sensitive, tooltip, icon size
        model = gtk.ListStore(str, str, int, bool, str)
        hw_list.set_model(model)
        icon = gtk.CellRendererPixbuf()
        icon.set_property("stock-size", gtk.ICON_SIZE_BUTTON)
        hw_list.pack_start(icon, False)
        hw_list.add_attribute(icon, 'icon-name', 1)
        text = gtk.CellRendererText()
        text.set_property("xpad", 6)
        hw_list.pack_start(text, True)
        hw_list.add_attribute(text, 'text', 0)
        hw_list.add_attribute(text, 'sensitive', 3)

        # Virtual network list
        net_list = self.window.get_widget("net-list")
        bridge_box = self.window.get_widget("net-bridge-box")
        uihelpers.init_network_list(net_list, bridge_box)

        # Network model list
        netmodel_list  = self.window.get_widget("net-model")
        uihelpers.build_netmodel_combo(self.vm, netmodel_list)

        # Disk device type / bus
        target_list = self.window.get_widget("config-storage-devtype")
        target_model = gtk.ListStore(str, str, str, str, int)
        target_list.set_model(target_model)
        icon = gtk.CellRendererPixbuf()
        icon.set_property("stock-size", gtk.ICON_SIZE_BUTTON)
        target_list.pack_start(icon, False)
        target_list.add_attribute(icon, 'icon-name', 2)
        text = gtk.CellRendererText()
        text.set_property("xpad", 6)
        target_list.pack_start(text, True)
        target_list.add_attribute(text, 'text', 3)

        # Sparse tooltip
        sparse_info = self.window.get_widget("config-storage-nosparse-info")
        uihelpers.set_sparse_tooltip(sparse_info)

        # Input device type
        input_list = self.window.get_widget("input-type")
        input_model = gtk.ListStore(str, str, str, bool)
        input_list.set_model(input_model)
        text = gtk.CellRendererText()
        input_list.pack_start(text, True)
        input_list.add_attribute(text, 'text', 0)
        input_list.add_attribute(text, 'sensitive', 3)

        # Graphics type
        graphics_list = self.window.get_widget("graphics-type")
        graphics_model = gtk.ListStore(str,str)
        graphics_list.set_model(graphics_model)
        text = gtk.CellRendererText()
        graphics_list.pack_start(text, True)
        graphics_list.add_attribute(text, 'text', 0)

        # Sound model list
        sound_list = self.window.get_widget("sound-model")
        uihelpers.build_sound_combo(self.vm, sound_list)

        host_devtype = self.window.get_widget("host-device-type")
        # Description, nodedev type, specific type capability, sub type,
        # sub cap
        host_devtype_model = gtk.ListStore(str, str, str, str, str)
        host_devtype.set_model(host_devtype_model)
        text = gtk.CellRendererText()
        host_devtype.pack_start(text, True)
        host_devtype.add_attribute(text, 'text', 0)

        host_dev = self.window.get_widget("host-device")
        # Description, nodedev name
        host_dev_model = gtk.ListStore(str, str)
        host_dev.set_model(host_dev_model)
        text = gtk.CellRendererText()
        host_dev.pack_start(text, True)
        host_dev.add_attribute(text, 'text', 0)
        host_dev_model.set_sort_column_id(0, gtk.SORT_ASCENDING)

        # Video device
        video_dev = self.window.get_widget("video-model")
        uihelpers.build_video_combo(self.vm, video_dev)

        char_devtype = self.window.get_widget("char-device-type")
        # Type name, desc
        char_devtype_model = gtk.ListStore(str, str)
        char_devtype.set_model(char_devtype_model)
        text = gtk.CellRendererText()
        char_devtype.pack_start(text, True)
        char_devtype.add_attribute(text, 'text', 1)
        char_devtype_model.set_sort_column_id(0, gtk.SORT_ASCENDING)
        for t in VirtualCharDevice.char_types:
            desc = VirtualCharDevice.get_char_type_desc(t)
            char_devtype_model.append([t, desc + " (%s)" % t])

        char_mode = self.window.get_widget("char-mode")
        # Mode name, desc
        char_mode_model = gtk.ListStore(str, str)
        char_mode.set_model(char_mode_model)
        text = gtk.CellRendererText()
        char_mode.pack_start(text, True)
        char_mode.add_attribute(text, 'text', 1)
        char_mode_model.set_sort_column_id(0, gtk.SORT_ASCENDING)
        for t in VirtualCharDevice.char_modes:
            desc = VirtualCharDevice.get_char_mode_desc(t)
            char_mode_model.append([t, desc + " (%s)" % t])

        self.window.get_widget("char-info-box").modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse("grey"))

        # Watchdog widgets
        combo = self.window.get_widget("watchdog-model")
        uihelpers.build_watchdogmodel_combo(self.vm, combo)

        combo = self.window.get_widget("watchdog-action")
        uihelpers.build_watchdogaction_combo(self.vm, combo)


    def reset_state(self):
        is_local = not self.conn.is_remote()
        is_storage_capable = self.conn.is_storage_capable()

        notebook = self.window.get_widget("create-pages")
        notebook.set_current_page(0)

        # Hide the "finish" button until the appropriate time
        self.window.get_widget("create-finish").hide()
        self.window.get_widget("create-forward").show()
        self.window.get_widget("create-forward").grab_focus()
        self.window.get_widget("create-back").set_sensitive(False)
        self.window.get_widget("create-help").hide()

        # Storage init
        label_widget = self.window.get_widget("phys-hd-label")
        if not self.host_storage_timer:
            self.host_storage_timer = util.safe_timeout_add(3 * 1000,
                                                uihelpers.host_space_tick,
                                                self.conn, self.config,
                                                label_widget)
        self.window.get_widget("config-storage-create").set_active(True)
        self.window.get_widget("config-storage-size").set_value(8)
        self.window.get_widget("config-storage-entry").set_text("")
        self.window.get_widget("config-storage-nosparse").set_active(True)
        target_list = self.window.get_widget("config-storage-devtype")
        self.populate_target_device_model(target_list.get_model())
        if len(target_list.get_model()) > 0:
            target_list.set_active(0)

        have_storage = (is_local or is_storage_capable)
        storage_tooltip = None
        if not have_storage:
            storage_tooltip = _("Connection does not support storage"
                                " management.")

        # Network init
        newmac = uihelpers.generate_macaddr(self.vm.get_connection())
        self.window.get_widget("mac-address").set_active(bool(newmac))
        self.window.get_widget("create-mac-address").set_text(newmac)
        self.change_macaddr_use()

        net_list = self.window.get_widget("net-list")
        net_warn = self.window.get_widget("net-list-warn")
        uihelpers.populate_network_list(net_list, self.vm.get_connection())

        error = self.vm.get_connection().netdev_error
        if error:
            net_warn.show()
            util.tooltip_wrapper(net_warn, error)
        else:
            net_warn.hide()

        netmodel = self.window.get_widget("net-model")
        uihelpers.populate_netmodel_combo(self.vm, netmodel)
        netmodel.set_active(0)

        # Input device init
        input_box = self.window.get_widget("input-type")
        self.populate_input_model(input_box.get_model())
        input_box.set_active(0)

        # Graphics init
        self.change_port_auto()
        graphics_box = self.window.get_widget("graphics-type")
        self.populate_graphics_model(graphics_box.get_model())
        graphics_box.set_active(0)
        self.window.get_widget("graphics-address").set_active(False)
        self.window.get_widget("graphics-port-auto").set_active(True)
        self.window.get_widget("graphics-password").set_text("")
        self.window.get_widget("graphics-keymap").set_text("")
        self.window.get_widget("graphics-keymap-chk").set_active(True)

        # Sound init
        sound_box = self.window.get_widget("sound-model")
        sound_box.set_active(0)
                
        # Hostdev init
        host_devtype = self.window.get_widget("host-device-type")
        self.populate_host_device_type_model(host_devtype.get_model())
        host_devtype.set_active(0)

        # Set available HW options

        # Char parameters
        self.window.get_widget("char-device-type").set_active(0)
        self.window.get_widget("char-path").set_text("")
        self.window.get_widget("char-host").set_text("127.0.0.1")
        self.window.get_widget("char-port").get_adjustment().value = 4555
        self.window.get_widget("char-bind-host").set_text("127.0.0.1")
        self.window.get_widget("char-bind-port").get_adjustment().value = 4556
        self.window.get_widget("char-use-telnet").set_active(False)

        # Available HW options
        model = self.window.get_widget("hardware-type").get_model()
        model.clear()

        def add_hw_option(name, icon, page, sensitive, tooltip):
            model.append([name, icon, page, sensitive, tooltip])

        add_hw_option("Storage", "drive-harddisk", PAGE_DISK, have_storage,
                      have_storage and storage_tooltip or None)
        add_hw_option("Network", "network-idle", PAGE_NETWORK, True, None)
        add_hw_option("Input", "input-mouse", PAGE_INPUT, self.vm.is_hvm(),
                      _("Not supported for this guest type."))
        add_hw_option("Graphics", "video-display", PAGE_GRAPHICS,
                      True, None)
        add_hw_option("Sound", "audio-card", PAGE_SOUND,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."))
        add_hw_option("Serial", gtk.STOCK_CONNECT, PAGE_CHAR,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."))
        add_hw_option("Parallel", gtk.STOCK_CONNECT, PAGE_CHAR,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."))
        add_hw_option("Physical Host Device", "system-run", PAGE_HOSTDEV,
                      self.vm.get_connection().is_nodedev_capable(),
                      _("Connection does not support host device "
                      "enumeration"))
        add_hw_option("Video", "video-display", PAGE_VIDEO,
                      virtinst.support.check_conn_support(
                            self.vm.get_connection().vmm,
                            virtinst.support.SUPPORT_CONN_DOMAIN_VIDEO),
                      _("Libvirt version does not support video devices."))
        add_hw_option("Watchdog", "device_pci", PAGE_WATCHDOG,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."))

        self.window.get_widget("hardware-type").set_active(0)

    #########################
    # UI population methods #
    #########################

    def populate_target_device_model(self, model):
        model.clear()
        #[bus, device, icon, desc, iconsize]
        def add_dev(bus, device, desc):
            if device == virtinst.VirtualDisk.DEVICE_FLOPPY:
                icon = "media-floppy"
            elif device == virtinst.VirtualDisk.DEVICE_CDROM:
                icon = "media-optical"
            else:
                icon = "drive-harddisk"
            model.append([bus, device, icon, desc, gtk.ICON_SIZE_BUTTON])

        if self.vm.is_hvm():
            add_dev("ide", virtinst.VirtualDisk.DEVICE_DISK, "IDE disk")
            add_dev("ide", virtinst.VirtualDisk.DEVICE_CDROM, "IDE cdrom")
            add_dev("fdc", virtinst.VirtualDisk.DEVICE_FLOPPY, "Floppy disk")
            add_dev("scsi",virtinst.VirtualDisk.DEVICE_DISK, "SCSI disk")
            add_dev("usb", virtinst.VirtualDisk.DEVICE_DISK, "USB disk")
        if self.vm.get_hv_type() == "kvm":
            add_dev("virtio", virtinst.VirtualDisk.DEVICE_DISK, "Virtio Disk")
        if self.vm.get_connection().is_xen():
            add_dev("xen", virtinst.VirtualDisk.DEVICE_DISK, "Virtual disk")

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
        model.append([_("Local SDL window"), "sdl"])

    def populate_host_device_type_model(self, model):
        model.clear()
        for m in [ ["PCI Device", "pci", None, "net", "80203"],
                   ["USB Device", "usb_device", None, None, None]]:
            model.append(m)

    def populate_host_device_model(self, model, devtype, devcap, subtype,
                                   subcap):
        model.clear()
        subdevs = []

        if subtype:
            subdevs = self.vm.get_connection().get_devices(subtype, subcap)

        devs = self.vm.get_connection().get_devices(devtype, devcap)
        for dev in devs:
            prettyname = dev.pretty_name()

            for subdev in subdevs:
                if dev.name == subdev.parent:
                    prettyname = dev.pretty_name(subdev)

            model.append([prettyname, dev.name])

        if len(model) == 0:
            model.append([_("No Devices Available"), None])


    ########################
    # get_config_* methods #
    ########################

    def get_config_hardware_type(self):
        _type = self.window.get_widget("hardware-type")
        if _type.get_active_iter() == None:
            return None
        return _type.get_model().get_value(_type.get_active_iter(), 2)

    # Disk getters
    def is_default_storage(self):
        return self.window.get_widget("config-storage-create").get_active()

    def get_storage_info(self):
        path = None
        size = self.window.get_widget("config-storage-size").get_value()
        sparse = not self.window.get_widget("config-storage-nosparse").get_active()

        if self.is_default_storage():
            path = util.get_default_path(self.conn, self.config,
                                         self.vm.get_name())
            logging.debug("Default storage path is: %s" % path)
        else:
            path = self.window.get_widget("config-storage-entry").get_text()

        return (path, size, sparse)

    def get_config_disk_target(self):
        target = self.window.get_widget("config-storage-devtype")
        model = target.get_model()
        idx = target.get_active()
        if idx == -1:
            return None, None

        bus = model[idx][0]
        device = model[idx][1]
        return bus, device

    # Input getters
    def get_config_input(self):
        target = self.window.get_widget("input-type")
        label = target.get_model().get_value(target.get_active_iter(), 0)
        _type = target.get_model().get_value(target.get_active_iter(), 1)
        bus = target.get_model().get_value(target.get_active_iter(), 2)
        return label, _type, bus

    # Graphics getters
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

    # Network getters
    def get_config_network(self):
        net_list = self.window.get_widget("net-list")
        bridge_ent = self.window.get_widget("net-bridge")

        net_type, net_src = uihelpers.get_network_selection(net_list,
                                                            bridge_ent)

        return net_type, net_src

    def get_config_net_model(self):
        model = self.window.get_widget("net-model")
        if model.get_active_iter():
            modelxml = model.get_model().get_value(model.get_active_iter(), 0)
            modelstr = model.get_model().get_value(model.get_active_iter(), 1)
        else:
            modelxml = modelstr = None
        return modelxml, modelstr

    def get_config_macaddr(self):
        macaddr = None
        if self.window.get_widget("mac-address").get_active():
            macaddr = self.window.get_widget("create-mac-address").get_text()
        return macaddr

    # Sound getters
    def get_config_sound_model(self):
        model = self.window.get_widget("sound-model")
        modelstr = model.get_model().get_value(model.get_active_iter(), 0)
        return modelstr

    # Host device getters
    def get_config_host_device_type_info(self):
        devbox = self.window.get_widget("host-device-type")
        return devbox.get_model()[devbox.get_active()]

    def get_config_host_device_info(self):
        devbox = self.window.get_widget("host-device")
        return devbox.get_model()[devbox.get_active()]

    # Video Getters
    def get_config_video_model(self):
        modbox = self.window.get_widget("video-model")
        return modbox.get_model()[modbox.get_active()][0]

    # Watchdog getters
    def get_config_watchdog_model(self):
        modbox = self.window.get_widget("watchdog-model")
        return modbox.get_model()[modbox.get_active()][0]
    def get_config_watchdog_action(self):
        modbox = self.window.get_widget("watchdog-action")
        return modbox.get_model()[modbox.get_active()][0]

    ################
    # UI listeners #
    ################

    def hardware_type_changed(self, src):
        if src.get_active() < 0:
            return

        row = src.get_model()[src.get_active()]

        sens = row[3]
        msg = row[4] or ""

        self.window.get_widget("create-forward").set_sensitive(sens)
        self.window.get_widget("hardware-info-box").set_property("visible",
                                                                 (not sens))
        self.window.get_widget("hardware-info").set_text(msg)

    def forward(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        try:
            if self.validate(notebook.get_current_page()) == False:
                return
        except Exception, e:
            self.err.show_err(_("Uncaught error validating hardware "
                                "input: %s") % str(e),
                              "".join(traceback.format_exc()))
            return

        hwtype = self.get_config_hardware_type()
        if notebook.get_current_page() == PAGE_INTRO:
            notebook.set_current_page(hwtype)
        else:
            notebook.set_current_page(PAGE_SUMMARY)
            self.window.get_widget("create-finish").show()
            self.window.get_widget("create-finish").grab_focus()
            self.window.get_widget("create-forward").hide()
        self.window.get_widget("create-back").set_sensitive(True)

    def back(self, ignore=None):
        notebook = self.window.get_widget("create-pages")

        if notebook.get_current_page() == PAGE_SUMMARY:
            hwtype = self.get_config_hardware_type()
            notebook.set_current_page(hwtype)
            self.window.get_widget("create-finish").hide()
        else:
            notebook.set_current_page(PAGE_INTRO)
            self.window.get_widget("create-back").set_sensitive(False)

        self.window.get_widget("create-forward").show()

    def page_changed(self, notebook, page, page_number):
        devbox = self.window.get_widget("host-device")
        devbox.hide()

        if page_number == PAGE_CHAR:
            devtype = self.window.get_widget("char-device-type")
            self.change_char_device_type(devtype)
            self.set_page_char_type()

        elif page_number == PAGE_SUMMARY:
            self.populate_summary()

        elif page_number == PAGE_HOSTDEV:
            devbox.show()

        return

    def populate_summary(self):
        hwpage = self.get_config_hardware_type()

        summary_table = self.window.get_widget("summary-table")
        for c in summary_table.get_children():
            summary_table.remove(c)

        def set_table(title, info_list):
            self.window.get_widget("summary-title").set_markup("<b>%s</b>" %
                                                               title)
            row = 0
            for label, value in info_list:
                label = gtk.Label(label)
                label.set_alignment(1, .5)
                value = gtk.Label(value)
                value.set_alignment(0, .5)

                summary_table.attach(label, 0, 1, row, row+1, gtk.FILL, 0)
                summary_table.attach(value, 1, 2, row, row+1, gtk.FILL, 0)

                row += 1
                if row == 10:
                    return

            summary_table.show_all()

        if hwpage == PAGE_DISK:
            size_str = (self._dev.size and ("%2.2f GB" % self._dev.size)
                                       or "-")

            info_list = [
                (_("Disk image:"),  self._dev.path),
                (_("Disk size:"),   size_str),
                (_("Device type:"), self._dev.device),
                (_("Bus type:"),    self._dev.bus),
            ]
            title = _("Storage")

        elif hwpage == PAGE_NETWORK:
            net_type, net_target = self.get_config_network()
            macaddr = self.get_config_macaddr()
            model = self.get_config_net_model()[1]
            net_label = virtinst.VirtualNetworkInterface.get_network_type_desc(net_type)
            net_target = net_target or "-"

            info_list = [
                (_("Network type:"),     net_label),
                (_("Target:"),          net_target),
                (_("MAC address:"),     macaddr or "-"),
                (_("Model:"),           model or "-"),
            ]
            title = _("Network")

        elif hwpage == PAGE_INPUT:
            ignore, typ, model = self.get_config_input()
            if typ == virtinst.VirtualInputDevice.INPUT_TYPE_TABLET:
                mode_label = _("Absolute movement")
            else:
                mode_label = _("Relative movement")

            info_list = [
                (_("Type:"), typ),
                (_("Mode:"), mode_label),
            ]
            title = _("Pointer")

        elif hwpage == PAGE_GRAPHICS:
            graphics = self.get_config_graphics()
            is_vnc = (graphics == virtinst.VirtualGraphics.TYPE_VNC)

            type_label = is_vnc and _("VNC server") or _("Local SDL window")
            addr = is_vnc and self.get_config_vnc_address() or _("N/A")
            port_label = _("N/A")
            passwd_label = _("N/A")
            keymap_label = _("N/A")

            if is_vnc:
                port = self.get_config_vnc_port()
                passwd = self.get_config_vnc_password()
                keymap = self.get_config_keymap()

                port_label = ((port == -1) and ("Automatically allocated")
                                           or port)
                passwd_label = passwd and _("Yes") or _("No")
                keymap_label = keymap and keymap or _("Same as host")

            info_list = [
                (_("Type:"),    type_label),
                (_("Address:"), addr),
                (_("Port:"),    port_label),
                (_("Password:"), passwd_label),
                (_("Keymap:"),  keymap_label),
            ]
            title = _("Graphics")

        elif hwpage == PAGE_SOUND:
            info_list = [
                (_("Model:"),   self._dev.model),
            ]
            title = _("Sound")

        elif hwpage == PAGE_CHAR:
            mode = None

            info_list = [
                (_("Type:"), VirtualCharDevice.get_char_type_desc(self._dev.char_type)),
            ]

            if hasattr(self._dev, "source_mode"):
                mode = self._dev.source_mode.capitalize()
            if hasattr(self._dev, "source_path"):
                path = self._dev.source_path
                label = "%sPath:" % (mode and mode + " " or "")
                info_list.append((label, path))

            if hasattr(self._dev, "source_host"):
                host = "%s:%s" % (self._dev.source_host, self._dev.source_port)
                label = "%sHost:" % (mode and mode + " " or "")
                info_list.append((label, host))

            if hasattr(self._dev, "bind_host"):
                bind_host = "%s:%s" % (self._dev.bind_host,
                                       self._dev.bind_port)
                info_list.append(("Bind Host:", bind_host))
            if hasattr(self._dev, "protocol"):
                proto = self._dev.protocol
                info_list.append((_("Protocol:"), proto))

            title = self.get_char_type().capitalize()

        elif hwpage == PAGE_HOSTDEV:
            info_list = [
                (_("Type:"),    self.get_config_host_device_type_info()[0]),
                (_("Device:"),  self.get_config_host_device_info()[0]),
            ]
            title = _("Physical Host Device")

        elif hwpage == PAGE_VIDEO:
            info_list = [
                (_("Model:"), self._dev.model_type),
            ]
            title = _("Video")

        elif hwpage == PAGE_WATCHDOG:
            title = _("Watchdog")
            info_list = [
                (_("Model:"), self._dev.model),
                (_("Action:"), self._dev.get_action_desc(self._dev.action))
            ]

        set_table(title, info_list)


    def finish(self, ignore=None):
        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        try:
            failure, errinfo = self.add_device()
            error, details = errinfo or (None, None)
        except Exception, e:
            failure = True
            error = _("Unable to add device: %s") % str(e)
            details = "".join(traceback.format_exc())

        if error is not None:
            self.err.show_err(error, details)

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))

        if not failure:
            self.close()

    # Storage listeners
    def browse_storage(self, ignore1):
        self._browse_file(self.window.get_widget("config-storage-entry"))

    def toggle_storage_select(self, src):
        act = src.get_active()
        self.window.get_widget("config-storage-browse-box").set_sensitive(act)

    def set_disk_storage_path(self, ignore, path):
        self.window.get_widget("config-storage-entry").set_text(path)

    # Network listeners
    def change_macaddr_use(self, ignore=None):
        if self.window.get_widget("mac-address").get_active():
            self.window.get_widget("create-mac-address").set_sensitive(True)
        else:
            self.window.get_widget("create-mac-address").set_sensitive(False)

    # Graphics listeners
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

    # Hostdevice listeners
    def change_host_device_type(self, src):
        devbox = self.window.get_widget("host-device")
        if src.get_active() < 0:
            devbox.get_model().clear()
            return

        (ignore, devtype, devcap,
         subtype, subcap) = src.get_model()[src.get_active()]
        self.populate_host_device_model(devbox.get_model(), devtype, devcap,
                                        subtype, subcap)
        devbox.set_active(0)

    # Char device listeners
    def get_char_type(self):
        hw_list = self.window.get_widget("hardware-type")
        if hw_list.get_active() < 0:
            label = "serial"
        else:
            label = hw_list.get_model()[hw_list.get_active()][0]

        if label.lower() == "parallel":
            return VirtualDevice.VIRTUAL_DEV_PARALLEL
        return VirtualDevice.VIRTUAL_DEV_SERIAL

    def set_page_char_type(self):
        char_type = self.get_char_type().capitalize()
        self.window.get_widget("char-title-label").set_markup(
            """<span weight="heavy" size="xx-large" foreground="#FFF">%s Device</span>""" % char_type)

    def change_char_device_type(self, src):
        self.update_doc(None, None, "char_type")

        chartype = self.get_char_type()
        devtype = src.get_model()[src.get_active()][0]
        conn = self.vm.get_connection().vmm

        self._dev = VirtualCharDevice.get_dev_instance(conn,
                                                       chartype,
                                                       devtype)

        for param_name, widget_name in char_widget_mappings.items():
            make_visible = hasattr(self._dev, param_name)
            self.window.get_widget(widget_name).set_sensitive(make_visible)

        has_mode = hasattr(self._dev, "source_mode")

        if has_mode and self.window.get_widget("char-mode").get_active() == -1:
            self.window.get_widget("char-mode").set_active(0)


    ######################
    # Add device methods #
    ######################

    def setup_device(self):
        if (self._dev.virtual_device_type ==
            virtinst.VirtualDevice.VIRTUAL_DEV_DISK):
            progWin = vmmAsyncJob(self.config, self.do_file_allocate,
                                  [self._dev],
                                  title=_("Creating Storage File"),
                                  text=_("Allocation of disk storage may take "
                                         "a few minutes to complete."))
            progWin.run()

            error, details = progWin.get_error()
            if error:
                return (error, details)

        else:
            self._dev.setup_dev(self.conn.vmm)

    def add_device(self):
        ret = self.setup_device()
        if ret:
            # Encountered an error
            return (True, ret)

        self._dev.get_xml_config()
        logging.debug("Adding device:\n" + self._dev.get_xml_config())

        # Hotplug device
        attach_err = False
        try:
            self.vm.attach_device(self._dev)
        except Exception, e:
            logging.debug("Device could not be hotplugged: %s" % str(e))
            attach_err = True

        if attach_err:
            if not self.err.yes_no(_("Are you sure you want to add this "
                                     "device?"),
                                   _("This device could not be attached to "
                                     "the running machine. Would you like to "
                                     "make the device available after the "
                                     "next VM shutdown?")):
                return (False, None)

        # Alter persistent config
        try:
            self.vm.add_device(self._dev)
        except Exception, e:
            self.err.show_err(_("Error adding device: %s" % str(e)),
                              "".join(traceback.format_exc()))
            return (True, None)

        return (False, None)

    def do_file_allocate(self, disk, asyncjob):
        meter = vmmCreateMeter(asyncjob)
        newconn = None
        try:
            # If creating disk via storage API, we need to thread
            # off a new connection
            if disk.vol_install:
                newconn = util.dup_lib_conn(self.config, disk.conn)
                disk.conn = newconn
            logging.debug("Starting background file allocate process")
            disk.setup_dev(self.conn.vmm, meter=meter)
            logging.debug("Allocation completed")
        except Exception, e:
            details = (_("Unable to complete install: '%s'") %
                         "".join(traceback.format_exc()))
            error = _("Unable to complete install: '%s'") % str(e)
            asyncjob.set_error(error, details)


    ###########################
    # Page validation methods #
    ###########################

    def validate(self, page_num):
        if page_num == PAGE_INTRO:
            return self.validate_page_intro()
        elif page_num == PAGE_DISK:
            return self.validate_page_storage()
        elif page_num == PAGE_NETWORK:
            return self.validate_page_network()
        elif page_num == PAGE_INPUT:
            return self.validate_page_input()
        elif page_num == PAGE_GRAPHICS:
            return self.validate_page_graphics()
        elif page_num == PAGE_SOUND:
            return self.validate_page_sound()
        elif page_num == PAGE_HOSTDEV:
            return self.validate_page_hostdev()
        elif page_num == PAGE_CHAR:
            return self.validate_page_char()
        elif page_num == PAGE_VIDEO:
            return self.validate_page_video()
        elif page_num == PAGE_WATCHDOG:
            return self.validate_page_watchdog()

    def validate_page_intro(self):
        if self.get_config_hardware_type() == None:
            return self.err.val_err(_("Hardware Type Required"),
                    _("You must specify what type of hardware to add."))
        self._dev = None

    def validate_page_storage(self):
        bus, device = self.get_config_disk_target()

        # Make sure default pool is running
        if self.is_default_storage():
            ret = uihelpers.check_default_pool_active(self.topwin, self.conn)
            if not ret:
                return False

        readonly = False
        if device == virtinst.VirtualDisk.DEVICE_CDROM:
            readonly=True

        try:
            # This can error out
            diskpath, disksize, sparse = self.get_storage_info()

            if self.is_default_storage():
                # See if the ideal disk path (/default/pool/vmname.img)
                # exists, and if unused, prompt the use for using it
                ideal = util.get_ideal_path(self.conn, self.config,
                                            self.vm.get_name())
                do_exist = False
                ret = True

                try:
                    do_exist = virtinst.VirtualDisk.path_exists(
                                                        self.conn.vmm, ideal)

                    ret = virtinst.VirtualDisk.path_in_use_by(self.conn.vmm,
                                                              ideal)
                except:
                    logging.exception("Error checking default path usage")

                if do_exist and not ret:
                    do_use = self.err.yes_no(
                        _("The following path already exists, but is not\n"
                          "in use by any virtual machine:\n\n%s\n\n"
                          "Would you like to use this path?") % ideal)

                    if do_use:
                        diskpath = ideal

            if not diskpath:
                return self.err.val_err(_("A storage path must be specified."))

            disk = virtinst.VirtualDisk(conn = self.conn.vmm,
                                        path = diskpath,
                                        size = disksize,
                                        sparse = sparse,
                                        readOnly = readonly,
                                        device = device,
                                        bus = bus)

            if (disk.type == virtinst.VirtualDisk.TYPE_FILE and
                not self.vm.is_hvm() and
                virtinst.util.is_blktap_capable()):
                disk.driver_name = virtinst.VirtualDisk.DRIVER_TAP

        except Exception, e:
            return self.err.val_err(_("Storage parameter error."), str(e))

        # Generate target
        used = []
        disks = (self.vm.get_disk_devices() +
                 self.vm.get_disk_devices(inactive=True))
        for d in disks:
            used.append(d[2])

        disk.generate_target(used)

        isfatal, errmsg = disk.is_size_conflict()
        if not isfatal and errmsg:
            # Fatal errors are reported when setting 'size'
            res = self.err.ok_cancel(_("Not Enough Free Space"), errmsg)
            if not res:
                return False

        # Disk collision
        if disk.is_conflict_disk(self.conn.vmm):
            res = self.err.yes_no(_('Disk "%s" is already in use by another '
                                    'guest!' %  disk.path),
                                  _("Do you really want to use the disk?"))
            if not res:
                return False

        uihelpers.check_path_search_for_qemu(self.topwin, self.config,
                                             self.conn, disk.path)

        self._dev = disk
        return True


    def validate_page_network(self):
        nettype, devname = self.get_config_network()
        mac = self.get_config_macaddr()
        model = self.get_config_net_model()[0]

        if not nettype:
            return self.err.val_err(_("Network selection error."),
                                    _("A network source must be selected."))

        if not mac:
            return self.err.val_err(_("Invalid MAC address"),
                                    _("A MAC address must be entered."))

        ret = uihelpers.validate_network(self.topwin, self.vm.get_connection(),
                                         nettype, devname, mac, model)
        if ret == False:
            return False

        self._dev = ret

    def validate_page_input(self):
        ignore, inp_type, inp_bus = self.get_config_input()
        dev = virtinst.VirtualInputDevice(self.conn.vmm)
        dev.type = inp_type
        dev.bus = inp_bus

        self._dev = dev

    def validate_page_graphics(self):
        graphics = self.get_config_graphics()
        if graphics == "vnc":
            _type = virtinst.VirtualGraphics.TYPE_VNC
        else:
            _type = virtinst.VirtualGraphics.TYPE_SDL

        self._dev = virtinst.VirtualGraphics(type=_type,
                                             conn=self.vm.get_connection().vmm)
        try:
            self._dev.port   = self.get_config_vnc_port()
            self._dev.passwd = self.get_config_vnc_password()
            self._dev.listen = self.get_config_vnc_address()
            self._dev.keymap = self.get_config_keymap()
        except ValueError, e:
            self.err.val_err(_("Graphics device parameter error"), str(e))

    def validate_page_sound(self):
        smodel = self.get_config_sound_model()
        try:
            self._dev = virtinst.VirtualAudio(conn=self.conn.vmm,
                                              model=smodel)
        except Exception, e:
            return self.err.val_err(_("Sound device parameter error"), str(e))

    def validate_page_hostdev(self):
        ignore, nodedev_name = self.get_config_host_device_info()

        if nodedev_name == None:
            return self.err.val_err(_("Physical Device Required"),
                                    _("A device must be selected."))

        try:
            self._dev = virtinst.VirtualHostDevice.device_from_node(
                            conn = self.vm.get_connection().vmm,
                            name = nodedev_name)
        except Exception, e:
            return self.err.val_err(_("Host device parameter error"), str(e))

    def validate_page_char(self):
        chartype = self.get_char_type()
        devbox = self.window.get_widget("char-device-type")
        devtype = devbox.get_model()[devbox.get_active()][0]
        conn = self.vm.get_connection().vmm

        devclass = VirtualCharDevice.get_dev_instance(conn, chartype, devtype)

        source_path = self.window.get_widget("char-path").get_text()
        source_host = self.window.get_widget("char-host").get_text()
        bind_host = self.window.get_widget("char-bind-host").get_text()
        source_port = self.window.get_widget("char-port").get_adjustment().value
        bind_port = self.window.get_widget("char-bind-port").get_adjustment().value

        if self.window.get_widget("char-use-telnet").get_active():
            protocol = VirtualCharDevice.CHAR_PROTOCOL_TELNET
        else:
            protocol = VirtualCharDevice.CHAR_PROTOCOL_RAW

        value_mappings = {
            "source_path" : source_path,
            "source_host" : source_host,
            "source_port" : source_port,
            "bind_port": bind_port,
            "bind_host": bind_host,
            "protocol": protocol,
        }

        try:
            self._dev = devclass

            for param_name, val in value_mappings.items():
                if hasattr(self._dev, param_name):
                    setattr(self._dev, param_name, val)

            # Dump XML for sanity checking
            self._dev.get_xml_config()
        except Exception, e:
            return self.err.val_err(_("%s device parameter error") %
                                    chartype.capitalize(), str(e))

    def validate_page_video(self):
        conn = self.vm.get_connection().vmm
        model = self.get_config_video_model()

        try:
            self._dev = VirtualVideoDevice(conn=conn)
            self._dev.model_type = model
        except Exception, e:
            return self.err.val_err(_("Video device parameter error"),
                                    str(e))

    def validate_page_watchdog(self):
        conn = self.vm.get_connection().vmm
        model = self.get_config_watchdog_model()
        action = self.get_config_watchdog_action()

        try:
            self._dev = VirtualWatchdog(conn=conn)
            self._dev.model = model
            self._dev.action = action
        except Exception, e:
            return self.err.val_err(_("Watchdog parameter error"),
                                    str(e))



    ####################
    # Unsorted helpers #
    ####################

    def _browse_file(self, textent):
        def set_storage_cb(src, path):
            if path:
                textent.set_text(path)

        conn = self.vm.get_connection()
        if self.storage_browser == None:
            self.storage_browser = vmmStorageBrowser(self.config, conn)

        self.storage_browser.set_finish_cb(set_storage_cb)
        self.storage_browser.set_browse_reason(self.config.CONFIG_DIR_IMAGE)

        self.storage_browser.show(conn)

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

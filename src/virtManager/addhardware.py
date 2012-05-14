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

import gtk

import virtinst
from virtinst import (VirtualCharDevice, VirtualDevice,
                      VirtualVideoDevice, VirtualWatchdog,
                      VirtualFilesystem, VirtualSmartCardDevice,
                      VirtualRedirDevice)

import virtManager.util as util
import virtManager.uihelpers as uihelpers
from virtManager.asyncjob import vmmAsyncJob
from virtManager.storagebrowse import vmmStorageBrowser
from virtManager.baseclass import vmmGObjectUI

PAGE_ERROR = 0
PAGE_DISK = 1
PAGE_NETWORK = 2
PAGE_INPUT = 3
PAGE_GRAPHICS = 4
PAGE_SOUND = 5
PAGE_HOSTDEV = 6
PAGE_CHAR = 7
PAGE_VIDEO = 8
PAGE_WATCHDOG = 9
PAGE_FILESYSTEM = 10
PAGE_SMARTCARD = 11
PAGE_USBREDIR = 12

char_widget_mappings = {
    "source_path" : "char-path",
    "source_mode" : "char-mode",
    "source_host" : "char-host",
    "source_port" : "char-port",
    "bind_port" : "char-bind-port",
    "bind_host" : "char-bind-host",
    "protocol"  : "char-use-telnet",
    "target_name" : "char-target-name",
}

_comboentry_xml = """
<interface>
    <object class="GtkComboBoxEntry" id="config-storage-format">
      <property name="visible">True</property>
    </object>
</interface>
"""

class vmmAddHardware(vmmGObjectUI):
    def __init__(self, vm):
        vmmGObjectUI.__init__(self,
                              "vmm-add-hardware.ui", "vmm-add-hardware")

        self.vm = vm
        self.conn = vm.conn

        self.storage_browser = None

        # Host space polling
        self.host_storage_timer = None

        self._dev = None

        self.window.add_from_string(_comboentry_xml)
        self.widget("table7").attach(self.widget("config-storage-format"),
                                     1, 2, 2, 3, xoptions=gtk.FILL)

        self.window.connect_signals({
            "on_create_cancel_clicked" : self.close,
            "on_vmm_create_delete_event" : self.close,
            "on_create_finish_clicked" : self.finish,
            "on_create_help_clicked": self.show_help,

            "on_config_storage_browse_clicked": self.browse_storage,
            "on_config_storage_select_toggled": self.toggle_storage_select,

            "on_mac_address_clicked" : self.change_macaddr_use,

            "on_graphics_type_changed": self.change_graphics_type,
            "on_graphics_port_auto_toggled": self.change_port_auto,
            "on_graphics_keymap_toggled": self.change_keymap,

            "on_char_device_type_changed": self.change_char_device_type,

            "on_fs_type_combo_changed": self.change_fs_type,
            "on_fs_driver_combo_changed": self.change_fs_driver,
            "on_fs_source_browse_clicked": self.browse_fs_source,

            "on_usbredir_type_changed": self.change_usbredir_type,

            # Char dev info signals
            "char_device_type_focus": (self.update_doc, "char_type"),
            "char_path_focus_in": (self.update_doc, "source_path"),
            "char_mode_changed": (self.update_doc_changed, "source_mode"),
            "char_mode_focus"  : (self.update_doc, "source_mode"),
            "char_host_focus_in": (self.update_doc, "source_host"),
            "char_bind_host_focus_in": (self.update_doc, "bind_host"),
            "char_telnet_focus_in": (self.update_doc, "protocol"),
            "char_name_focus_in": (self.update_doc, "target_name"),
            })
        self.bind_escape_key_close()

        # XXX: Help docs useless/out of date
        self.widget("create-help").hide()


        finish_img = gtk.image_new_from_stock(gtk.STOCK_QUIT,
                                              gtk.ICON_SIZE_BUTTON)
        self.widget("create-finish").set_image(finish_img)

        self.set_initial_state()

        hwlist = self.widget("hardware-list")
        hwlist.get_selection().connect("changed", self.hw_selected)

    def update_doc(self, ignore1, ignore2, param):
        doc = self._build_doc_str(param)
        self.widget("char-info").set_markup(doc)

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
            paramdoc = getattr(devclass, param).__doc__
            if paramdoc:
                doc = doctmpl % paramdoc

        return doc

    def show(self, parent):
        logging.debug("Showing addhw")
        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing addhw")
        self.topwin.hide()
        self.remove_timers()
        if self.storage_browser:
            self.storage_browser.close()

        return 1

    def _cleanup(self):
        self.close()

        self.vm = None
        self.conn = None
        self._dev = None

        if self.storage_browser:
            self.storage_browser.cleanup()
            self.storage_browser = None

    def remove_timers(self):
        try:
            if self.host_storage_timer:
                self.remove_gobject_timeout(self.host_storage_timer)
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
        notebook = self.widget("create-pages")
        notebook.set_show_tabs(False)

        black = gtk.gdk.color_parse("#000")
        self.widget("page-title-box").modify_bg(gtk.STATE_NORMAL, black)

        # Name, icon name, page number, is sensitive, tooltip, icon size,
        # device type (serial/parallel)...
        model = gtk.ListStore(str, str, int, bool, str, str)
        hw_list = self.widget("hardware-list")
        hw_list.set_model(model)

        hw_col = gtk.TreeViewColumn("Hardware")
        hw_col.set_spacing(6)
        hw_col.set_min_width(165)

        icon = gtk.CellRendererPixbuf()
        icon.set_property("stock-size", gtk.ICON_SIZE_BUTTON)
        text = gtk.CellRendererText()
        text.set_property("xpad", 6)

        hw_col.pack_start(icon, False)
        hw_col.pack_start(text, True)
        hw_col.add_attribute(icon, 'icon-name', 1)
        hw_col.add_attribute(text, 'text', 0)
        hw_col.add_attribute(text, 'sensitive', 3)
        hw_list.append_column(hw_col)

        # Virtual network list
        net_list = self.widget("net-list")
        bridge_box = self.widget("net-bridge-box")
        uihelpers.init_network_list(net_list, bridge_box)

        # Network model list
        netmodel_list  = self.widget("net-model")
        uihelpers.build_netmodel_combo(self.vm, netmodel_list)

        # Disk device type / bus
        target_list = self.widget("config-storage-devtype")
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

        # Disk cache mode
        cache_list = self.widget("config-storage-cache")
        uihelpers.build_cache_combo(self.vm, cache_list)

        # Disk format mode
        format_list = self.widget("config-storage-format")
        uihelpers.build_storage_format_combo(self.vm, format_list)

        # Sparse tooltip
        sparse_info = self.widget("config-storage-nosparse-info")
        uihelpers.set_sparse_tooltip(sparse_info)

        # Input device type
        input_list = self.widget("input-type")
        input_model = gtk.ListStore(str, str, str, bool)
        input_list.set_model(input_model)
        text = gtk.CellRendererText()
        input_list.pack_start(text, True)
        input_list.add_attribute(text, 'text', 0)
        input_list.add_attribute(text, 'sensitive', 3)

        # Graphics type
        graphics_list = self.widget("graphics-type")
        graphics_model = gtk.ListStore(str, str)
        graphics_list.set_model(graphics_model)
        text = gtk.CellRendererText()
        graphics_list.pack_start(text, True)
        graphics_list.add_attribute(text, 'text', 0)

        # Sound model list
        sound_list = self.widget("sound-model")
        uihelpers.build_sound_combo(self.vm, sound_list)

        # Host device list
        # model = [ Description, nodedev name ]
        host_dev = self.widget("host-device")
        host_dev_model = gtk.ListStore(str, str)
        host_dev.set_model(host_dev_model)

        host_col = gtk.TreeViewColumn()
        text = gtk.CellRendererText()
        host_col.pack_start(text, True)
        host_col.add_attribute(text, 'text', 0)
        host_dev_model.set_sort_column_id(0, gtk.SORT_ASCENDING)
        host_dev.append_column(host_col)

        # Video device
        video_dev = self.widget("video-model")
        uihelpers.build_video_combo(self.vm, video_dev)

        # Character dev mode
        char_mode = self.widget("char-mode")
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

        self.widget("char-info-box").modify_bg(gtk.STATE_NORMAL,
                                               gtk.gdk.color_parse("grey"))

        # Watchdog widgets
        combo = self.widget("watchdog-model")
        uihelpers.build_watchdogmodel_combo(self.vm, combo)

        combo = self.widget("watchdog-action")
        uihelpers.build_watchdogaction_combo(self.vm, combo)

        def simple_store_set(comboname, values):
            combo = self.widget(comboname)
            model = gtk.ListStore(str, str)
            combo.set_model(model)
            text = gtk.CellRendererText()
            combo.pack_start(text, True)
            combo.add_attribute(text, 'text', 1)
            model.set_sort_column_id(0, gtk.SORT_ASCENDING)
            for val in values:
                model.append([val, val.capitalize()])

        # Filesystem widgets
        simple_store_set("fs-type-combo",
                         [VirtualFilesystem.TYPE_MOUNT,
                          VirtualFilesystem.TYPE_TEMPLATE])
        simple_store_set("fs-mode-combo", VirtualFilesystem.MOUNT_MODES)
        simple_store_set("fs-driver-combo", VirtualFilesystem.DRIVER_TYPES)
        simple_store_set("fs-wrpolicy-combo", VirtualFilesystem.WRPOLICIES)
        self.show_pair_combo("fs-type", self.conn.is_openvz())
        self.show_check_button("fs-readonly", self.conn.is_qemu())

        # Smartcard widgets
        combo = self.widget("smartcard-mode")
        uihelpers.build_smartcard_mode_combo(self.vm, combo)

        # Usbredir widgets
        combo = self.widget("usbredir-list")
        uihelpers.build_redir_type_combo(self.vm, combo)

        # Available HW options
        is_local = not self.conn.is_remote()
        is_storage_capable = self.conn.is_storage_capable()

        have_storage = (is_local or is_storage_capable)
        storage_tooltip = None
        if not have_storage:
            storage_tooltip = _("Connection does not support storage"
                                " management.")

        hwlist = self.widget("hardware-list")
        model = hwlist.get_model()
        model.clear()

        def add_hw_option(name, icon, page, sensitive, errortxt, devtype=None):
            model.append([name, icon, page, sensitive, errortxt, devtype])

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
                      _("Not supported for this guest type."),
                      "serial")
        add_hw_option("Parallel", gtk.STOCK_CONNECT, PAGE_CHAR,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."),
                      "parallel")
        add_hw_option("Channel", gtk.STOCK_CONNECT, PAGE_CHAR,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."),
                      "channel")
        add_hw_option("USB Host Device", "system-run", PAGE_HOSTDEV,
                      self.conn.is_nodedev_capable(),
                      _("Connection does not support host device enumeration"),
                      "usb")
        add_hw_option("PCI Host Device", "system-run", PAGE_HOSTDEV,
                      self.conn.is_nodedev_capable(),
                      _("Connection does not support host device enumeration"),
                      "pci")
        add_hw_option("Video", "video-display", PAGE_VIDEO,
                      virtinst.support.check_conn_support(
                            self.conn.vmm,
                            virtinst.support.SUPPORT_CONN_DOMAIN_VIDEO),
                      _("Libvirt version does not support video devices."))
        add_hw_option("Watchdog", "device_pci", PAGE_WATCHDOG,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."))
        add_hw_option("Filesystem", gtk.STOCK_DIRECTORY, PAGE_FILESYSTEM,
                      virtinst.support.check_conn_hv_support(
                        self.conn.vmm,
                        virtinst.support.SUPPORT_CONN_HV_FILESYSTEM,
                        self.vm.get_hv_type()),
                      _("Not supported for this hypervisor/libvirt "
                        "combination."))
        add_hw_option("Smartcard", "device_serial", PAGE_SMARTCARD,
                      True, None)
        add_hw_option("USB Redirection", "device_usb", PAGE_USBREDIR,
                      True, None)

    def reset_state(self):
        # Storage init
        label_widget = self.widget("phys-hd-label")
        label_widget.set_markup("")
        if not self.host_storage_timer:
            self.host_storage_timer = self.timeout_add(3 * 1000,
                                                uihelpers.host_space_tick,
                                                self.conn,
                                                label_widget)
        self.widget("config-storage-create").set_active(True)
        self.widget("config-storage-size").set_value(8)
        self.widget("config-storage-entry").set_text("")
        self.widget("config-storage-nosparse").set_active(True)
        # Don't specify by default, so we don't overwrite possibly working
        # libvirt detection
        self.widget("config-storage-format").child.set_text("")
        target_list = self.widget("config-storage-devtype")
        self.populate_target_device_model(target_list.get_model())
        if len(target_list.get_model()) > 0:
            target_list.set_active(0)

        # Network init
        newmac = uihelpers.generate_macaddr(self.conn)
        self.widget("mac-address").set_active(bool(newmac))
        self.widget("create-mac-address").set_text(newmac)
        self.change_macaddr_use()

        net_list = self.widget("net-list")
        net_warn = self.widget("net-list-warn")
        uihelpers.populate_network_list(net_list, self.conn)

        error = self.conn.netdev_error
        if error:
            net_warn.show()
            util.tooltip_wrapper(net_warn, error)
        else:
            net_warn.hide()

        netmodel = self.widget("net-model")
        uihelpers.populate_netmodel_combo(self.vm, netmodel)
        netmodel.set_active(0)

        # Input device init
        input_box = self.widget("input-type")
        self.populate_input_model(input_box.get_model())
        input_box.set_active(0)

        # Graphics init
        self.change_port_auto()
        graphics_box = self.widget("graphics-type")
        self.populate_graphics_model(graphics_box.get_model())
        graphics_box.set_active(0)
        self.widget("graphics-address").set_active(False)
        self.widget("graphics-port-auto").set_active(True)
        self.widget("graphics-password").set_text("")
        self.widget("graphics-keymap").set_text("")
        self.widget("graphics-keymap-chk").set_active(True)

        # Sound init
        sound_box = self.widget("sound-model")
        sound_box.set_active(0)

        # Char parameters
        self.widget("char-device-type").set_active(0)
        self.widget("char-path").set_text("")
        self.widget("char-host").set_text("127.0.0.1")
        self.widget("char-port").get_adjustment().value = 4555
        self.widget("char-bind-host").set_text("127.0.0.1")
        self.widget("char-bind-port").get_adjustment().value = 4556
        self.widget("char-use-telnet").set_active(False)
        self.widget("char-target-name").set_text("com.redhat.spice.0")

        # FS params
        self.widget("fs-type-combo").set_active(0)
        self.widget("fs-mode-combo").set_active(0)
        self.widget("fs-driver-combo").set_active(0)
        self.widget("fs-wrpolicy-combo").set_active(0)
        self.widget("fs-source").set_text("")
        self.widget("fs-target").set_text("")
        self.widget("fs-readonly").set_active(False)

        # Video params
        uihelpers.populate_video_combo(self.vm, self.widget("video-model"))

        # Hide all notebook pages, so the wizard isn't as big as the largest
        # page
        notebook = self.widget("create-pages")
        for page in range(notebook.get_n_pages()):
            widget = notebook.get_nth_page(page)
            widget.hide()

        self.set_hw_selection(0)

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

            if self.vm.rhel6_defaults():
                add_dev("scsi", virtinst.VirtualDisk.DEVICE_DISK, "SCSI disk")
                add_dev("usb", virtinst.VirtualDisk.DEVICE_DISK, "USB disk")
        if self.vm.get_hv_type() == "kvm":
            add_dev("sata", virtinst.VirtualDisk.DEVICE_DISK, "SATA disk")
            add_dev("virtio", virtinst.VirtualDisk.DEVICE_DISK, "Virtio disk")
        if self.conn.is_xen():
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
        model.append([_("Spice server"), "spice"])
        model.append([_("Local SDL window"), "sdl"])

    def populate_host_device_model(self, devtype, devcap, subtype, subcap):
        devlist = self.widget("host-device")
        model = devlist.get_model()
        model.clear()
        subdevs = []

        if subtype:
            subdevs = self.conn.get_nodedevs(subtype, subcap)

        devs = self.conn.get_nodedevs(devtype, devcap)
        for dev in devs:
            prettyname = dev.pretty_name()

            for subdev in subdevs:
                if dev.name == subdev.parent:
                    prettyname = dev.pretty_name(subdev)

            model.append([prettyname, dev.name])

        if len(model) == 0:
            model.append([_("No Devices Available"), None])
        util.set_list_selection(devlist, 0)

    ########################
    # get_config_* methods #
    ########################

    def get_config_hardware_type(self):
        row = self.get_hw_selection()
        if not row:
            return None
        return row[2]

    # Disk getters
    def is_default_storage(self):
        return self.widget("config-storage-create").get_active()

    def get_storage_info(self):
        path = None
        size = self.widget("config-storage-size").get_value()
        sparse = not self.widget("config-storage-nosparse").get_active()

        if self.is_default_storage():
            pathlist = map(lambda d: d.path, self.vm.get_disk_devices())
            path = util.get_default_path(self.conn,
                                         self.vm.get_name(),
                                         collidelist=pathlist)
            logging.debug("Default storage path is: %s", path)
        else:
            path = self.widget("config-storage-entry").get_text()

        return (path or None, size, sparse)

    def get_config_disk_target(self):
        target = self.widget("config-storage-devtype")
        model = target.get_model()
        idx = target.get_active()
        if idx == -1:
            return None, None

        bus = model[idx][0]
        device = model[idx][1]
        return bus, device

    def get_config_disk_cache(self, label=False):
        cache = self.widget("config-storage-cache")
        idx = 0
        if label:
            idx = 1
        return cache.get_model()[cache.get_active()][idx]

    def get_config_disk_format(self):
        fmt = self.widget("config-storage-format")
        return fmt.child.get_text()

    # Input getters
    def get_config_input(self):
        target = self.widget("input-type")
        label = target.get_model().get_value(target.get_active_iter(), 0)
        _type = target.get_model().get_value(target.get_active_iter(), 1)
        bus = target.get_model().get_value(target.get_active_iter(), 2)
        return label, _type, bus

    # Graphics getters
    def get_config_graphics(self):
        _type = self.widget("graphics-type")
        if _type.get_active_iter() is None:
            return None
        return _type.get_model().get_value(_type.get_active_iter(), 1)

    def get_config_graphics_port(self):
        port = self.widget("graphics-port")
        portAuto = self.widget("graphics-port-auto")
        if portAuto.get_active():
            return -1
        return int(port.get_value())

    def get_config_graphics_tls_port(self):
        port = self.widget("graphics-tls-port")
        portAuto = self.widget("graphics-port-auto")
        if portAuto.get_active():
            return -1
        return int(port.get_value())

    def get_config_graphics_address(self):
        addr = self.widget("graphics-address")
        if addr.get_active():
            return "0.0.0.0"
        return "127.0.0.1"

    def get_config_graphics_password(self):
        pw = self.widget("graphics-password")
        return pw.get_text()

    def get_config_keymap(self):
        g = self.widget("graphics-keymap")
        if g.get_property("sensitive") and g.get_text() != "":
            return g.get_text()
        else:
            return None

    # Network getters
    def get_config_network(self):
        net_list = self.widget("net-list")
        bridge_ent = self.widget("net-bridge")

        net_type, net_src = uihelpers.get_network_selection(net_list,
                                                            bridge_ent)

        return net_type, net_src

    def get_config_net_model(self):
        model = self.widget("net-model")
        if model.get_active_iter():
            modelxml = model.get_model().get_value(model.get_active_iter(), 0)
            modelstr = model.get_model().get_value(model.get_active_iter(), 1)
        else:
            modelxml = modelstr = None
        return modelxml, modelstr

    def get_config_macaddr(self):
        macaddr = None
        if self.widget("mac-address").get_active():
            macaddr = self.widget("create-mac-address").get_text()
        return macaddr

    # Sound getters
    def get_config_sound_model(self):
        model = self.widget("sound-model")
        modelstr = model.get_model().get_value(model.get_active_iter(), 0)
        return modelstr

    # Host device getters
    def get_config_host_device_type_info(self):
        pci_info = ["PCI Device", "pci", None, "net", "80203"]
        usb_info = ["USB Device", "usb_device", None, None, None]
        row = self.get_hw_selection()

        if row and row[5] == "pci":
            return pci_info
        return usb_info

    def get_config_host_device_info(self):
        devrow = util.get_list_selection(self.widget("host-device"))
        if not devrow:
            return []
        return devrow

    # Video Getters
    def get_config_video_model(self):
        modbox = self.widget("video-model")
        return modbox.get_model()[modbox.get_active()][0]

    # Watchdog getters
    def get_config_watchdog_model(self):
        modbox = self.widget("watchdog-model")
        return modbox.get_model()[modbox.get_active()][0]
    def get_config_watchdog_action(self):
        modbox = self.widget("watchdog-action")
        return modbox.get_model()[modbox.get_active()][0]

    # FS getters
    def get_config_fs_mode(self):
        name = "fs-mode-combo"
        combo = self.widget(name)
        if not combo.get_property("visible"):
            return None

        return combo.get_model()[combo.get_active()][0]

    def get_config_fs_wrpolicy(self):
        name = "fs-wrpolicy-combo"
        combo = self.widget(name)
        if not combo.get_property("visible"):
            return None

        return combo.get_model()[combo.get_active()][0]

    def get_config_fs_type(self):
        name = "fs-type-combo"
        combo = self.widget(name)
        if not combo.get_property("visible"):
            return None

        return combo.get_model()[combo.get_active()][0]

    def get_config_fs_readonly(self):
        name = "fs-readonly"
        check = self.widget(name)
        if not check.get_property("visible"):
            return None

        return check.get_active()

    def get_config_fs_driver(self):
        name = "fs-driver-combo"
        combo = self.widget(name)
        if not combo.get_property("visible"):
            return None

        return combo.get_model()[combo.get_active()][0]

    # Smartcard getters
    def get_config_smartcard_mode(self):
        mode = self.widget("smartcard-mode")
        modestr = mode.get_model().get_value(mode.get_active_iter(), 0)
        return modestr

    # USB redir getters
    def get_config_usbredir_host(self):
        host = self.widget("usbredir-host")
        if not host.props.sensitive:
            return None

        hoststr = host.get_text()
        return hoststr

    def get_config_usbredir_service(self):
        service = self.widget("usbredir-service")
        if not service.props.sensitive:
            return None

        return int(service.get_value())

    def get_config_usbredir_type(self):
        typebox = self.widget("usbredir-list")
        return typebox.get_model()[typebox.get_active()][0]

    ################
    # UI listeners #
    ################

    def set_hw_selection(self, page):
        util.set_list_selection(self.widget("hardware-list"), page)

    def get_hw_selection(self):
        return util.get_list_selection(self.widget("hardware-list"))

    def update_char_device_type_model(self):
        rhel6_blacklist = ["pipe", "udp"]

        # Char device type
        char_devtype = self.widget("char-device-type")
        dev_type = self.get_char_type()
        # Type name, desc
        char_devtype_model = gtk.ListStore(str, str)
        char_devtype.clear()
        char_devtype.set_model(char_devtype_model)
        text = gtk.CellRendererText()
        char_devtype.pack_start(text, True)
        char_devtype.add_attribute(text, 'text', 1)

        for t in VirtualCharDevice.char_types_for_dev_type[dev_type]:
            if (t in rhel6_blacklist and
                not self.vm.rhel6_defaults()):
                continue

            desc = VirtualCharDevice.get_char_type_desc(t)
            row = [t, desc + " (%s)" % t]
            char_devtype_model.append(row)
        char_devtype.set_active(0)

    def hw_selected(self, src=None):
        ignore = src
        self._dev = None
        notebook = self.widget("create-pages")

        row = self.get_hw_selection()
        if not row:
            self.set_hw_selection(0)
            return

        page = row[2]
        sens = row[3]
        msg = row[4] or ""

        if not sens:
            page = PAGE_ERROR
            self.widget("hardware-info").set_text(msg)

        if page == PAGE_CHAR:
            self.update_char_device_type_model()
            devtype = self.widget("char-device-type")
            self.change_char_device_type(devtype)

        if page == PAGE_HOSTDEV:
            (ignore, devtype, devcap,
             subtype, subcap) = self.get_config_host_device_type_info()
            self.populate_host_device_model(devtype, devcap,
                                            subtype, subcap)

        self.set_page_title(page)
        notebook.get_nth_page(page).show()
        notebook.set_current_page(page)

    def finish(self, ignore=None):
        notebook = self.widget("create-pages")
        try:
            if self.validate(notebook.get_current_page()) == False:
                return
        except Exception, e:
            self.err.show_err(_("Uncaught error validating hardware "
                                "input: %s") % str(e))
            return

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
            self.err.show_err(error, details=details)

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))

        self._dev = None
        if not failure:
            self.close()

    def show_pair_combo(self, basename, show_combo):
        combo = self.widget(basename + "-combo")
        label = self.widget(basename + "-label")

        combo.set_property("visible", show_combo)
        label.set_property("visible", not show_combo)

    def show_check_button(self, basename, show):
        check = self.widget(basename)
        check.set_property("visible", show)

    # Storage listeners
    def browse_storage(self, ignore1):
        self._browse_file(self.widget("config-storage-entry"))

    def toggle_storage_select(self, src):
        act = src.get_active()
        self.widget("config-storage-browse-box").set_sensitive(act)

    def set_disk_storage_path(self, ignore, path):
        self.widget("config-storage-entry").set_text(path)

    # Network listeners
    def change_macaddr_use(self, ignore=None):
        if self.widget("mac-address").get_active():
            self.widget("create-mac-address").set_sensitive(True)
        else:
            self.widget("create-mac-address").set_sensitive(False)

    # Graphics listeners
    def change_graphics_type(self, ignore=None):
        graphics = self.get_config_graphics()
        if graphics in ["vnc", "spice"]:
            self.widget("graphics-port-auto").set_sensitive(True)
            self.widget("graphics-address").set_sensitive(True)
            self.widget("graphics-password").set_sensitive(True)
            self.widget("graphics-keymap-chk").set_sensitive(True)
            self.change_port_auto()
        else:
            self.widget("graphics-port").set_sensitive(False)
            self.widget("graphics-tls-port").set_sensitive(False)
            self.widget("graphics-port-auto").set_sensitive(False)
            self.widget("graphics-address").set_sensitive(False)
            self.widget("graphics-password").set_sensitive(False)
            self.widget("graphics-keymap-chk").set_sensitive(False)
            self.widget("graphics-keymap").set_sensitive(False)

    def change_port_auto(self, ignore=None):
        graphics = self.get_config_graphics()
        tls_enable = graphics == "spice"
        if self.widget("graphics-port-auto").get_active():
            self.widget("graphics-port").set_sensitive(False)
            self.widget("graphics-tls-port").set_sensitive(False)
        else:
            self.widget("graphics-port").set_sensitive(True)
            self.widget("graphics-tls-port").set_sensitive(tls_enable)

    def change_keymap(self, ignore=None):
        if self.widget("graphics-keymap-chk").get_active():
            self.widget("graphics-keymap").set_sensitive(False)
        else:
            self.widget("graphics-keymap").set_sensitive(True)

    # Char device listeners
    def get_char_type(self):
        row = self.get_hw_selection()
        label = "serial"

        if row:
            label = row[5]

        if label == "parallel":
            return VirtualDevice.VIRTUAL_DEV_PARALLEL
        elif label == "channel":
            return VirtualDevice.VIRTUAL_DEV_CHANNEL
        return VirtualDevice.VIRTUAL_DEV_SERIAL

    def dev_to_title(self, page):
        if page == PAGE_ERROR:
            return _("Error")
        if page == PAGE_DISK:
            return _("Storage")
        if page == PAGE_NETWORK:
            return _("Network")
        if page == PAGE_INPUT:
            return _("Input")
        if page == PAGE_GRAPHICS:
            return _("Graphics")
        if page == PAGE_SOUND:
            return _("Sound")
        if page == PAGE_VIDEO:
            return _("Video Device")
        if page == PAGE_WATCHDOG:
            return _("Watchdog Device")
        if page == PAGE_FILESYSTEM:
            return _("Filesystem Passthrough")
        if page == PAGE_SMARTCARD:
            return _("Smartcard")
        if page == PAGE_USBREDIR:
            return _("USB Redirection")

        if page == PAGE_CHAR:
            return self.get_char_type().capitalize() + " Device"
        if page == PAGE_HOSTDEV:
            return self.get_config_host_device_type_info()[0]

        raise RuntimeError("Unknown page %s" % page)

    def set_page_title(self, page):
        title = self.dev_to_title(page)
        markup = ("""<span weight="heavy" size="xx-large" """
                  """foreground="#FFF">%s</span>""") % title
        self.widget("page-title-label").set_markup(markup)

    def change_char_device_type(self, src):
        self.update_doc(None, None, "char_type")
        idx = src.get_active()
        if idx < 0:
            return

        chartype = self.get_char_type()
        devtype = src.get_model()[src.get_active()][0]
        conn = self.conn.vmm

        self._dev = VirtualCharDevice.get_dev_instance(conn,
                                                       chartype,
                                                       devtype)

        show_something = False
        for param_name, widget_name in char_widget_mappings.items():
            make_visible = self._dev.supports_property(param_name)
            if make_visible:
                show_something = True

            self.widget(widget_name).set_property("visible", make_visible)
            self.widget(widget_name + "-label").set_property("visible",
                                                             make_visible)

        self.widget("char-param-box").set_property("visible", show_something)

        has_mode = self._dev.supports_property("source_mode")
        if has_mode and self.widget("char-mode").get_active() == -1:
            self.widget("char-mode").set_active(0)

    def change_usbredir_type(self, src):
        idx = src.get_active()
        if idx < 0:
            return

        hostdetails = src.get_model()[src.get_active()][2]
        self.widget("usbredir-host").set_sensitive(hostdetails)
        self.widget("usbredir-service").set_sensitive(hostdetails)

    # FS listeners
    def browse_fs_source(self, ignore1):
        self._browse_file(self.widget("fs-source"), isdir=True)

    def change_fs_type(self, src):
        idx = src.get_active()
        fstype = None
        show_mode_combo = False
        show_driver_combo = False
        show_wrpolicy_combo = self.conn.is_qemu()

        if idx >= 0 and src.get_property("visible"):
            fstype = src.get_model()[idx][0]

        if fstype == virtinst.VirtualFilesystem.TYPE_TEMPLATE:
            source_text = _("Te_mplate:")
        else:
            source_text = _("_Source path:")
            show_mode_combo = self.conn.is_qemu()
            show_driver_combo = self.conn.is_qemu()

        self.widget("fs-source-title").set_text(source_text)
        self.widget("fs-source-title").set_use_underline(True)
        self.show_pair_combo("fs-mode", show_mode_combo)
        self.show_pair_combo("fs-driver", show_driver_combo)
        self.show_pair_combo("fs-wrpolicy", show_wrpolicy_combo)

    def change_fs_driver(self, src):
        idx = src.get_active()
        fsdriver = None
        modecombo = self.widget("fs-mode-combo")
        modelabel1 = self.widget("fs-mode-title")
        wrpcombo = self.widget("fs-wrpolicy-combo")
        wrplabel1 = self.widget("fs-wrpolicy-title")

        if idx >= 0 and src.get_property("visible"):
            fsdriver = src.get_model()[idx][0]

        if (fsdriver == virtinst.VirtualFilesystem.DRIVER_PATH or
            fsdriver == virtinst.VirtualFilesystem.DRIVER_DEFAULT):
            modecombo.set_property("visible", True)
            modelabel1.set_property("visible", True)
        else:
            modecombo.set_property("visible", False)
            modelabel1.set_property("visible", False)

        if (fsdriver == virtinst.VirtualFilesystem.DRIVER_DEFAULT):
            wrpcombo.set_property("visible", False)
            wrplabel1.set_property("visible", False)
        else:
            wrpcombo.set_property("visible", True)
            wrplabel1.set_property("visible", True)



    ######################
    # Add device methods #
    ######################

    def setup_device(self):
        if (self._dev.virtual_device_type !=
            virtinst.VirtualDevice.VIRTUAL_DEV_DISK):
            self._dev.setup_dev(self.conn.vmm)
            return

        def do_file_allocate(asyncjob, disk):
            meter = asyncjob.get_meter()

            # If creating disk via storage API, we need to thread
            # off a new connection
            if disk.vol_install:
                newconn = util.dup_lib_conn(disk.conn)
                disk.conn = newconn
            logging.debug("Starting background file allocate process")
            disk.setup_dev(self.conn.vmm, meter=meter)
            logging.debug("Allocation completed")

        progWin = vmmAsyncJob(do_file_allocate,
                              [self._dev],
                              _("Creating Storage File"),
                              _("Allocation of disk storage may take "
                                "a few minutes to complete."),
                              self.topwin)

        return progWin.run()


    def add_device(self):
        ret = self.setup_device()
        if ret and ret[0]:
            # Encountered an error
            return (True, ret)

        self._dev.get_xml_config()
        logging.debug("Adding device:\n" + self._dev.get_xml_config())

        # Hotplug device
        attach_err = False
        try:
            self.vm.attach_device(self._dev)
        except Exception, e:
            logging.debug("Device could not be hotplugged: %s", str(e))
            attach_err = (str(e), "".join(traceback.format_exc()))

        if attach_err:
            res = self.err.show_err(
                _("Are you sure you want to add this device?"),
                details=(attach_err[0] + "\n\n" + attach_err[1]),
                text2=(
                _("This device could not be attached to the running machine. "
                  "Would you like to make the device available after the "
                  "next guest shutdown?")),
                dialog_type=gtk.MESSAGE_WARNING,
                buttons=gtk.BUTTONS_YES_NO,
                async=False)

            if not res:
                return (False, None)

        # Alter persistent config
        try:
            self.vm.add_device(self._dev)
        except Exception, e:
            self.err.show_err(_("Error adding device: %s" % str(e)))
            return (True, None)

        return (False, None)


    ###########################
    # Page validation methods #
    ###########################

    def validate(self, page_num):
        if page_num == PAGE_ERROR:
            self._dev = None
            return True
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
        elif page_num == PAGE_FILESYSTEM:
            return self.validate_page_filesystem()
        elif page_num == PAGE_SMARTCARD:
            return self.validate_page_smartcard()
        elif page_num == PAGE_USBREDIR:
            return self.validate_page_usbredir()

    def validate_page_storage(self):
        bus, device = self.get_config_disk_target()
        cache = self.get_config_disk_cache()
        fmt = self.get_config_disk_format()

        # Make sure default pool is running
        if self.is_default_storage():
            ret = uihelpers.check_default_pool_active(self.topwin, self.conn)
            if not ret:
                return False

        readonly = False
        if device == virtinst.VirtualDisk.DEVICE_CDROM:
            readonly = True

        try:
            # This can error out
            diskpath, disksize, sparse = self.get_storage_info()

            if self.is_default_storage():
                # See if the ideal disk path (/default/pool/vmname.img)
                # exists, and if unused, prompt the use for using it
                ideal = util.get_ideal_path(self.conn,
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
                        _("The following storage already exists, but is not\n"
                          "in use by any virtual machine:\n\n%s\n\n"
                          "Would you like to reuse this storage?") % ideal)

                    if do_use:
                        diskpath = ideal

            disk = virtinst.VirtualDisk(conn=self.conn.vmm,
                                        path=diskpath,
                                        size=disksize,
                                        sparse=sparse,
                                        readOnly=readonly,
                                        device=device,
                                        bus=bus,
                                        driverCache=cache,
                                        format=fmt)

            if not fmt:
                fmt = self.config.get_storage_format()
                if (self.is_default_storage() and
                    disk.vol_install and
                    fmt in disk.vol_install.formats):
                    logging.debug("Setting disk format from prefs: %s", fmt)
                    disk.vol_install.format = fmt

            if (disk.type == virtinst.VirtualDisk.TYPE_FILE and
                not self.vm.is_hvm() and
                virtinst.util.is_blktap_capable()):
                disk.driver_name = virtinst.VirtualDisk.DRIVER_TAP

        except Exception, e:
            return self.err.val_err(_("Storage parameter error."), e)

        # Generate target
        used = []
        disks = (self.vm.get_disk_devices() +
                 self.vm.get_disk_devices(inactive=True))
        for d in disks:
            used.append(d.target)

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
                                    'guest!' % disk.path),
                                  _("Do you really want to use the disk?"))
            if not res:
                return False

        uihelpers.check_path_search_for_qemu(self.topwin,
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

        ret = uihelpers.validate_network(self.topwin, self.conn,
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
        _type = {"vnc": virtinst.VirtualGraphics.TYPE_VNC,
                 "spice": virtinst.VirtualGraphics.TYPE_SPICE,
                 "sdl": virtinst.VirtualGraphics.TYPE_SDL}[graphics]

        self._dev = virtinst.VirtualGraphics(type=_type,
                                             conn=self.conn.vmm)
        try:
            self._dev.port   = self.get_config_graphics_port()
            self._dev.tlsPort = self.get_config_graphics_tls_port()
            self._dev.passwd = self.get_config_graphics_password()
            self._dev.listen = self.get_config_graphics_address()
            self._dev.keymap = self.get_config_keymap()
        except ValueError, e:
            self.err.val_err(_("Graphics device parameter error"), e)

    def validate_page_sound(self):
        smodel = self.get_config_sound_model()
        try:
            self._dev = virtinst.VirtualAudio(conn=self.conn.vmm,
                                              model=smodel)
        except Exception, e:
            return self.err.val_err(_("Sound device parameter error"), e)

    def validate_page_hostdev(self):
        ret = self.get_config_host_device_info()
        nodedev_name = ret and ret[1] or None

        if nodedev_name == None:
            return self.err.val_err(_("Physical Device Required"),
                                    _("A device must be selected."))

        try:
            self._dev = virtinst.VirtualHostDevice.device_from_node(
                            conn=self.conn.vmm,
                            name=nodedev_name)
        except Exception, e:
            return self.err.val_err(_("Host device parameter error"), e)

    def validate_page_char(self):
        chartype = self.get_char_type()
        modebox = self.widget("char-mode")
        devbox = self.widget("char-device-type")
        devtype = devbox.get_model()[devbox.get_active()][0]
        conn = self.conn.vmm

        devclass = VirtualCharDevice.get_dev_instance(conn, chartype, devtype)

        source_path = self.widget("char-path").get_text()
        source_mode = modebox.get_model()[modebox.get_active()][0]
        source_host = self.widget("char-host").get_text()
        bind_host = self.widget("char-bind-host").get_text()
        source_port = self.widget("char-port").get_adjustment().value
        bind_port = self.widget("char-bind-port").get_adjustment().value
        target_name = self.widget("char-target-name").get_text()

        if self.widget("char-use-telnet").get_active():
            protocol = VirtualCharDevice.CHAR_PROTOCOL_TELNET
        else:
            protocol = VirtualCharDevice.CHAR_PROTOCOL_RAW

        value_mappings = {
            "source_path" : source_path,
            "source_mode" : source_mode,
            "source_host" : source_host,
            "source_port" : source_port,
            "bind_port": bind_port,
            "bind_host": bind_host,
            "protocol": protocol,
            "target_name": target_name,
        }

        try:
            self._dev = devclass

            for param_name, val in value_mappings.items():
                if self._dev.supports_property(param_name):
                    setattr(self._dev, param_name, val)

            # Dump XML for sanity checking
            self._dev.get_xml_config()
        except Exception, e:
            return self.err.val_err(_("%s device parameter error") %
                                    chartype.capitalize(), e)

    def validate_page_video(self):
        conn = self.conn.vmm
        model = self.get_config_video_model()

        try:
            self._dev = VirtualVideoDevice(conn=conn)
            self._dev.model_type = model
        except Exception, e:
            return self.err.val_err(_("Video device parameter error"), e)

    def validate_page_watchdog(self):
        conn = self.conn.vmm
        model = self.get_config_watchdog_model()
        action = self.get_config_watchdog_action()

        try:
            self._dev = VirtualWatchdog(conn=conn)
            self._dev.model = model
            self._dev.action = action
        except Exception, e:
            return self.err.val_err(_("Watchdog parameter error"), e)

    def validate_page_filesystem(self):
        conn = self.conn.vmm
        source = self.widget("fs-source").get_text()
        target = self.widget("fs-target").get_text()
        mode = self.get_config_fs_mode()
        fstype = self.get_config_fs_type()
        readonly = self.get_config_fs_readonly()
        driver = self.get_config_fs_driver()
        wrpolicy = self.get_config_fs_wrpolicy()

        if not source:
            return self.err.val_err(_("A filesystem source must be specified"))
        if not target:
            return self.err.val_err(_("A filesystem target must be specified"))

        if self.conn.is_qemu() and self.filesystem_target_present(target):
            return self.err.val_err(_('Invalid target path. A filesystem with'
                                       ' that target already exists'))

        try:
            self._dev = virtinst.VirtualFilesystem(conn=conn)
            self._dev.source = source
            self._dev.target = target
            if mode:
                self._dev.mode = mode
            if fstype:
                self._dev.type = fstype
            if readonly:
                self._dev.readonly = readonly
            if driver:
                self._dev.driver = driver
            if wrpolicy:
                self._dev.wrpolicy = wrpolicy
        except Exception, e:
            return self.err.val_err(_("Filesystem parameter error"), e)

    def filesystem_target_present(self, target):
        fsdevs = self.vm.get_filesystem_devices()

        for fs in fsdevs:
            if (fs.target == target):
                return True

        return False

    def validate_page_smartcard(self):
        conn = self.conn.vmm
        mode = self.get_config_smartcard_mode()

        try:
            self._dev = VirtualSmartCardDevice(conn, mode)
        except Exception, e:
            return self.err.val_err(_("Smartcard device parameter error"), e)

    def validate_page_usbredir(self):
        conn = self.conn.vmm
        stype = self.get_config_usbredir_type()
        host = self.get_config_usbredir_host()
        service = self.get_config_usbredir_service()

        try:
            self._dev = VirtualRedirDevice(conn=conn, bus="usb", stype=stype)
            if host:
                self._dev.host = host
            if service:
                self._dev.service = service
        except Exception, e:
            return self.err.val_err(_("USB redirected device parameter error"),
                                    str(e))


    ####################
    # Unsorted helpers #
    ####################

    def _browse_file(self, textent, isdir=False):
        def set_storage_cb(src, path):
            if path:
                textent.set_text(path)

        conn = self.conn
        reason = (isdir and
                  self.config.CONFIG_DIR_FS or
                  self.config.CONFIG_DIR_IMAGE)
        if self.storage_browser == None:
            self.storage_browser = vmmStorageBrowser(conn)

        rhel6 = self.vm.rhel6_defaults()
        self.storage_browser.rhel6_defaults = rhel6

        self.storage_browser.set_finish_cb(set_storage_cb)
        self.storage_browser.set_browse_reason(reason)

        self.storage_browser.show(self.topwin, conn)

    def show_help(self, src_ignore):
        # help to show depends on the notebook page, yahoo
        page = self.widget("create-pages").get_current_page()
        if page == PAGE_ERROR:
            self.emit("action-show-help", "virt-manager-create-wizard")
        elif page == PAGE_DISK:
            self.emit("action-show-help", "virt-manager-storage-space")
        elif page == PAGE_NETWORK:
            self.emit("action-show-help", "virt-manager-network")

vmmAddHardware.type_register(vmmAddHardware)
vmmAddHardware.signal_new(vmmAddHardware, "action-show-help", [str])

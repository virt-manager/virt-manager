#
# Copyright (C) 2006-2007, 2013 Red Hat, Inc.
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

# pylint: disable=E0611
from gi.repository import Gtk
from gi.repository import Gdk
# pylint: enable=E0611

import virtinst
from virtinst import util
from virtinst import (VirtualChannelDevice, VirtualParallelDevice,
                      VirtualSerialDevice, VirtualConsoleDevice,
                      VirtualVideoDevice, VirtualWatchdog,
                      VirtualFilesystem, VirtualSmartCardDevice,
                      VirtualRedirDevice, VirtualTPMDevice)
from virtinst import VirtualController

from virtManager import uihelpers
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
PAGE_TPM = 13
PAGE_RNG = 14


class vmmAddHardware(vmmGObjectUI):
    def __init__(self, vm, is_customize_dialog):
        vmmGObjectUI.__init__(self, "addhardware.ui", "vmm-add-hardware")

        self.vm = vm
        self.conn = vm.conn
        self.is_customize_dialog = is_customize_dialog

        self.storage_browser = None

        self._dev = None

        self.builder.connect_signals({
            "on_create_cancel_clicked" : self.close,
            "on_vmm_create_delete_event" : self.close,
            "on_create_finish_clicked" : self.finish,
            "on_hw_list_changed": self.hw_selected,

            "on_config_storage_browse_clicked": self.browse_storage,
            "on_config_storage_select_toggled": self.toggle_storage_select,

            "on_mac_address_clicked" : self.change_macaddr_use,

            "on_graphics_type_changed": self.change_graphics_type,
            "on_graphics_port_auto_toggled": self.change_port_auto,
            "on_graphics_use_password": self.change_password_chk,

            "on_char_device_type_changed": self.change_char_device_type,
            "on_char_target_name_changed": self.change_char_target_name,

            "on_tpm_device_type_changed": self.change_tpm_device_type,

            "on_fs_type_combo_changed": self.change_fs_type,
            "on_fs_driver_combo_changed": self.change_fs_driver,
            "on_fs_source_browse_clicked": self.browse_fs_source,

            "on_usbredir_type_changed": self.change_usbredir_type,

            "on_rng_type_changed": self.change_rng_type,
        })
        self.bind_escape_key_close()

        self.set_initial_state()

    def show(self, parent):
        logging.debug("Showing addhw")
        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()
        self.conn.schedule_priority_tick(pollnet=True,
                                         pollpool=True, polliface=True,
                                         pollnodedev=True, pollmedia=True)

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing addhw")
        self.topwin.hide()
        if self.storage_browser:
            self.storage_browser.close()

        return 1

    def _cleanup(self):
        self.vm = None
        self.conn = None
        self._dev = None

        if self.storage_browser:
            self.storage_browser.cleanup()
            self.storage_browser = None

    def is_visible(self):
        return self.topwin.get_visible()


    ##########################
    # Initialization methods #
    ##########################

    def set_initial_state(self):
        notebook = self.widget("create-pages")
        notebook.set_show_tabs(False)

        blue = Gdk.color_parse("#0072A8")
        self.widget("page-title-box").modify_bg(Gtk.StateType.NORMAL, blue)

        # Name, icon name, page number, is sensitive, tooltip, icon size,
        # device type (serial/parallel)...
        model = Gtk.ListStore(str, str, int, bool, str, str)
        hw_list = self.widget("hw-list")
        hw_list.set_model(model)

        hw_col = Gtk.TreeViewColumn("Hardware")
        hw_col.set_spacing(6)
        hw_col.set_min_width(165)

        icon = Gtk.CellRendererPixbuf()
        icon.set_property("stock-size", Gtk.IconSize.BUTTON)
        text = Gtk.CellRendererText()
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
        target_model = Gtk.ListStore(str, str, str, str, int)
        target_list.set_model(target_model)
        icon = Gtk.CellRendererPixbuf()
        icon.set_property("stock-size", Gtk.IconSize.BUTTON)
        target_list.pack_start(icon, False)
        target_list.add_attribute(icon, 'icon-name', 2)
        text = Gtk.CellRendererText()
        text.set_property("xpad", 6)
        target_list.pack_start(text, True)
        target_list.add_attribute(text, 'text', 3)

        # Disk cache mode
        cache_list = self.widget("config-storage-cache")
        uihelpers.build_cache_combo(self.vm, cache_list)

        # Disk format mode
        self.populate_disk_format_combo(True)

        # Sparse tooltip
        sparse_info = self.widget("config-storage-nosparse-info")
        uihelpers.set_sparse_tooltip(sparse_info)

        # Input device type
        input_list = self.widget("input-type")
        input_model = Gtk.ListStore(str, str, str)
        input_list.set_model(input_model)
        text = Gtk.CellRendererText()
        input_list.pack_start(text, True)
        input_list.add_attribute(text, 'text', 0)

        # Graphics type
        graphics_list = self.widget("graphics-type")
        graphics_model = Gtk.ListStore(str, str)
        graphics_list.set_model(graphics_model)
        text = Gtk.CellRendererText()
        graphics_list.pack_start(text, True)
        graphics_list.add_attribute(text, 'text', 0)

        # Graphics address
        # [label, value]
        self.widget("graphics-address").set_model(Gtk.ListStore(str, str))
        text = Gtk.CellRendererText()
        self.widget("graphics-address").pack_start(text, True)
        self.widget("graphics-address").add_attribute(text, 'text', 0)

        # Sound model list
        sound_list = self.widget("sound-model")
        uihelpers.build_sound_combo(self.vm, sound_list)

        # Host device list
        # model = [ Description, nodedev name ]
        host_dev = self.widget("host-device")
        host_dev_model = Gtk.ListStore(str, str, str, object)
        host_dev.set_model(host_dev_model)

        host_col = Gtk.TreeViewColumn()
        text = Gtk.CellRendererText()
        host_col.pack_start(text, True)
        host_col.add_attribute(text, 'text', 0)
        host_dev_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        host_dev.append_column(host_col)

        # Video device
        video_dev = self.widget("video-model")
        uihelpers.build_video_combo(self.vm, video_dev)

        # Character dev mode
        char_mode = self.widget("char-mode")
        # Mode name, desc
        char_mode_model = Gtk.ListStore(str, str)
        char_mode.set_model(char_mode_model)
        text = Gtk.CellRendererText()
        char_mode.pack_start(text, True)
        char_mode.add_attribute(text, 'text', 1)
        char_mode_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        for t in VirtualSerialDevice.MODES:
            desc = VirtualSerialDevice.pretty_mode(t)
            char_mode_model.append([t, desc + " (%s)" % t])

        # Char target type
        lst = self.widget("char-target-type")
        model = Gtk.ListStore(str, str)
        lst.set_model(model)
        uihelpers.set_combo_text_column(lst, 1)
        if self.conn.is_qemu():
            model.append(["virtio", "virtio"])
        else:
            model.append([None, "default"])

        # Char target name
        lst = self.widget("char-target-name")
        model = Gtk.ListStore(str)
        lst.set_model(model)
        uihelpers.set_combo_text_column(lst, 0)
        for n in VirtualChannelDevice.CHANNEL_NAMES:
            model.append([n])

        # Char device type
        lst = self.widget("char-device-type")
        model = Gtk.ListStore(str, str)
        lst.set_model(model)
        uihelpers.set_combo_text_column(lst, 1)

        # Watchdog widgets
        combo = self.widget("watchdog-model")
        uihelpers.build_watchdogmodel_combo(self.vm, combo)

        combo = self.widget("watchdog-action")
        uihelpers.build_watchdogaction_combo(self.vm, combo)

        def simple_store_set(comboname, values):
            combo = self.widget(comboname)
            model = Gtk.ListStore(str, str)
            combo.set_model(model)
            text = Gtk.CellRendererText()
            combo.pack_start(text, True)
            combo.add_attribute(text, 'text', 1)
            model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
            for val in values:
                model.append([val, val.capitalize()])

        # Filesystem widgets
        simple_store_set("fs-type-combo",
                         [VirtualFilesystem.TYPE_MOUNT,
                          VirtualFilesystem.TYPE_TEMPLATE])
        simple_store_set("fs-mode-combo", VirtualFilesystem.MODES)
        simple_store_set("fs-driver-combo", VirtualFilesystem.DRIVERS)
        simple_store_set("fs-wrpolicy-combo", VirtualFilesystem.WRPOLICIES)
        self.show_pair_combo("fs-type", self.conn.is_openvz())
        self.show_check_button("fs-readonly", self.conn.is_qemu())

        # Smartcard widgets
        combo = self.widget("smartcard-mode")
        uihelpers.build_smartcard_mode_combo(self.vm, combo)

        # Usbredir widgets
        combo = self.widget("usbredir-list")
        uihelpers.build_redir_type_combo(self.vm, combo)

        # TPM widgets
        combo = self.widget("tpm-type")
        uihelpers.build_tpm_type_combo(self.vm, combo)

        # RNG widgets
        combo = self.widget("rng-type")
        self.build_rng_type_combo(combo)
        combo = self.widget("rng-backend-type")
        self.build_rng_backend_type_combo(combo)
        combo = self.widget("rng-backend-mode")
        self.build_rng_backend_mode_combo(combo)

        # Available HW options
        is_local = not self.conn.is_remote()
        is_storage_capable = self.conn.is_storage_capable()

        have_storage = (is_local or is_storage_capable)
        storage_tooltip = None
        if not have_storage:
            storage_tooltip = _("Connection does not support storage"
                                " management.")

        hwlist = self.widget("hw-list")
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
        add_hw_option("Serial", Gtk.STOCK_CONNECT, PAGE_CHAR,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."),
                      "serial")
        add_hw_option("Parallel", Gtk.STOCK_CONNECT, PAGE_CHAR,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."),
                      "parallel")
        add_hw_option("Console", Gtk.STOCK_CONNECT, PAGE_CHAR,
                      True, None, "console")
        add_hw_option("Channel", Gtk.STOCK_CONNECT, PAGE_CHAR,
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
                      self.conn.check_conn_support(
                            self.conn.SUPPORT_CONN_DOMAIN_VIDEO),
                      _("Libvirt version does not support video devices."))
        add_hw_option("Watchdog", "device_pci", PAGE_WATCHDOG,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."))
        add_hw_option("Filesystem", Gtk.STOCK_DIRECTORY, PAGE_FILESYSTEM,
                      self.conn.check_conn_support(
                        self.conn.SUPPORT_CONN_FILESYSTEM),
                      _("Not supported for this hypervisor/libvirt "
                        "combination."))
        add_hw_option("Smartcard", "device_serial", PAGE_SMARTCARD,
                      True, None)
        add_hw_option("USB Redirection", "device_usb", PAGE_USBREDIR,
                      True, None)
        add_hw_option("TPM", "device_cpu", PAGE_TPM,
                      True, None)
        add_hw_option("RNG", "system-run", PAGE_RNG, True, None)

    def reset_state(self):
        # Storage init
        label_widget = self.widget("phys-hd-label")
        label_widget.set_markup("")
        uihelpers.update_host_space(self.conn, label_widget)

        self.widget("config-storage-create").set_active(True)
        self.widget("config-storage-size").set_value(8)
        self.widget("config-storage-entry").set_text("")
        self.widget("config-storage-nosparse").set_active(True)
        self.populate_disk_format_combo(True)
        target_list = self.widget("config-storage-devtype")
        self.populate_target_device_model(target_list.get_model())
        if len(target_list.get_model()) > 0:
            target_list.set_active(0)

        # Network init
        newmac = virtinst.VirtualNetworkInterface.generate_mac(
                self.conn.get_backend())
        self.widget("mac-address").set_active(bool(newmac))
        self.widget("create-mac-address").set_text(newmac)
        self.change_macaddr_use()

        net_list = self.widget("net-list")
        net_warn = self.widget("net-list-warn")
        uihelpers.populate_network_list(net_list, self.conn)

        error = self.conn.netdev_error
        if error:
            net_warn.show()
            net_warn.set_tooltip_text(error)
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
        graphics_box = self.widget("graphics-type")
        self.populate_graphics_model(graphics_box.get_model())
        graphics_box.set_active(0)

        model = self.widget("graphics-address").get_model()
        model.clear()
        model.append([_("Hypervisor default"), None])
        model.append([_("Localhost only"), "127.0.0.1"])
        model.append([_("All interfaces"), "0.0.0.0"])
        self.widget("graphics-address").set_active(0)

        self.change_port_auto()
        self.widget("graphics-port-auto").set_active(True)
        self.widget("graphics-password").set_text("")
        self.widget("graphics-password").set_sensitive(False)
        self.widget("graphics-password-chk").set_active(False)

        # Sound init
        sound_box = self.widget("sound-model")
        sound_box.set_active(0)

        # Char parameters
        self.widget("char-device-type").set_active(0)
        self.widget("char-target-type").set_active(0)
        self.widget("char-target-name").set_active(0)
        self.widget("char-path").set_text("")
        self.widget("char-host").set_text("127.0.0.1")
        self.widget("char-port").set_value(4555)
        self.widget("char-bind-host").set_text("127.0.0.1")
        self.widget("char-bind-port").set_value(4556)
        self.widget("char-use-telnet").set_active(False)

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

        # TPM paams
        self.widget("tpm-device-path").set_text("/dev/tpm0")

        # Hide all notebook pages, so the wizard isn't as big as the largest
        # page
        notebook = self.widget("create-pages")
        for page in range(notebook.get_n_pages()):
            widget = notebook.get_nth_page(page)
            widget.hide()

        # RNG params
        self.widget("rng-device").set_text("/dev/random")
        self.widget("rng-host").set_text("localhost")
        self.widget("rng-service").set_text("708")

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
            model.append([bus, device, icon, desc, Gtk.IconSize.BUTTON])

        if self.vm.is_hvm():
            add_dev("ide", virtinst.VirtualDisk.DEVICE_DISK, _("IDE disk"))
            add_dev("ide", virtinst.VirtualDisk.DEVICE_CDROM, _("IDE CDROM"))
            add_dev("fdc", virtinst.VirtualDisk.DEVICE_FLOPPY,
                    _("Floppy disk"))

            if self.vm.rhel6_defaults():
                add_dev("scsi", virtinst.VirtualDisk.DEVICE_DISK,
                        _("SCSI disk"))
                add_dev("usb", virtinst.VirtualDisk.DEVICE_DISK,
                        _("USB disk"))
        if self.vm.get_hv_type() in ["qemu", "kvm", "test"]:
            add_dev("sata", virtinst.VirtualDisk.DEVICE_DISK,
                    _("SATA disk"))
            add_dev("sd", virtinst.VirtualDisk.DEVICE_DISK,
                    _("SD disk"))
            add_dev("virtio", virtinst.VirtualDisk.DEVICE_DISK,
                    _("Virtio disk"))
            add_dev("virtio", virtinst.VirtualDisk.DEVICE_LUN,
                    _("Virtio lun"))
            add_dev("virtio-scsi", virtinst.VirtualDisk.DEVICE_DISK,
                    _("Virtio SCSI disk"))
            add_dev("virtio-scsi", virtinst.VirtualDisk.DEVICE_LUN,
                    _("Virtio SCSI lun"))
        if self.conn.is_xen() or self.conn.is_test_conn():
            add_dev("xen", virtinst.VirtualDisk.DEVICE_DISK,
                    _("Xen virtual disk"))

    def populate_input_model(self, model):
        model.clear()
        model.append([_("EvTouch USB Graphics Tablet"), "tablet", "usb"])
        model.append([_("Generic USB Mouse"), "mouse", "usb"])

    def populate_graphics_model(self, model):
        model.clear()
        model.append([_("Spice server"), "spice"])
        model.append([_("VNC server"), "vnc"])

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

            model.append([prettyname, dev.name, devtype, dev])

        if len(model) == 0:
            model.append([_("No Devices Available"), None, None, None])
        uihelpers.set_list_selection(devlist, 0)

    def populate_disk_format_combo(self, create):
        format_list = self.widget("config-storage-format")
        uihelpers.update_storage_format_combo(self.vm, format_list, create)
        if not create:
            format_list.get_child().set_text("")

    ########################
    # get_config_* methods #
    ########################

    def build_combo_with_values(self, combo, values, default=None):
        dev_model = Gtk.ListStore(str, str)
        combo.set_model(dev_model)
        text = Gtk.CellRendererText()
        combo.pack_start(text, True)
        combo.add_attribute(text, 'text', 1)
        dev_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        types = combo.get_model()
        types.clear()

        # [xml value, label]
        for t in values:
            types.append(t[0:2])

        if default:
            idx = -1
            for rowid in range(len(combo.get_model())):
                idx = 0
                row = combo.get_model()[rowid]
                if row[0] == default:
                    idx = rowid
                    break
            combo.set_active(idx)


    def build_rng_type_combo(self, combo):
        types = []
        for t in virtinst.VirtualRNGDevice.TYPES:
            types.append([t, virtinst.VirtualRNGDevice.get_pretty_type(t)])

        self.build_combo_with_values(combo, types,
                                virtinst.VirtualRNGDevice.TYPE_RANDOM)


    def build_rng_backend_type_combo(self, combo):
        default = virtinst.VirtualRNGDevice.BACKEND_TYPE_TCP

        types = []
        for t in virtinst.VirtualRNGDevice.BACKEND_TYPES:
            pprint = virtinst.VirtualRNGDevice.get_pretty_backend_type(t)
            types.append([t, pprint])

        self.build_combo_with_values(combo, types, default)


    def build_rng_backend_mode_combo(self, combo):
        default = virtinst.VirtualRNGDevice.BACKEND_MODE_CONNECT

        types = []
        for t in virtinst.VirtualRNGDevice.BACKEND_MODES:
            pprint = virtinst.VirtualRNGDevice.get_pretty_backend_type(t)
            types.append([t, pprint])

        self.build_combo_with_values(combo, types, default)

    def get_config_hardware_type(self):
        row = self.get_hw_selection()
        if not row:
            return None
        return row[2]

    # Disk getters
    def is_default_storage(self):
        return self.widget("config-storage-create").get_active()

    def get_storage_info(self, collidelist):
        path = None
        size = self.widget("config-storage-size").get_value()
        sparse = not self.widget("config-storage-nosparse").get_active()

        if self.is_default_storage():
            path = uihelpers.get_default_path(self.conn,
                                         self.vm.get_name(),
                                         collidelist=collidelist)
            logging.debug("Default storage path is: %s", path)
        else:
            path = self.widget("config-storage-entry").get_text()

        return (path or None, size, sparse)

    def check_ideal_path(self, diskpath, collidelist):
        # See if the ideal disk path (/default/pool/vmname.img)
        # exists, and if unused, prompt the use for using it
        conn = self.conn.get_backend()
        ideal = uihelpers.get_ideal_path(self.conn, self.vm.get_name())
        if ideal in collidelist:
            return diskpath
        do_exist = False
        ret = True

        try:
            do_exist = virtinst.VirtualDisk.path_exists(conn, ideal)
            ret = virtinst.VirtualDisk.path_in_use_by(conn, ideal)
        except:
            logging.exception("Error checking default path usage")

        if not do_exist or ret:
            return diskpath

        do_use = self.err.yes_no(
            _("The following storage already exists, but is not\n"
              "in use by any virtual machine:\n\n%s\n\n"
              "Would you like to reuse this storage?") % ideal)

        if do_use:
            return ideal
        return diskpath

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
        return fmt.get_child().get_text()

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

    def get_config_graphics_ports(self):
        if self.widget("graphics-port-auto").get_active():
            return -1, -1

        port = self.widget("graphics-port").get_value()
        tlsport = self.widget("graphics-tls-port").get_value()
        if not self.widget("graphics-tls-port").get_visible():
            tlsport = -1
        return int(port), int(tlsport)

    def get_config_graphics_address(self):
        addr = self.widget("graphics-address")
        return addr.get_model()[addr.get_active()][1]

    def get_config_graphics_password(self):
        if not self.widget("graphics-password-chk").get_active():
            return None
        return self.widget("graphics-password").get_text()

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
        devrow = uihelpers.get_list_selection(self.widget("host-device"))
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
        if not combo.get_visible():
            return None

        return combo.get_model()[combo.get_active()][0]

    def get_config_fs_wrpolicy(self):
        name = "fs-wrpolicy-combo"
        combo = self.widget(name)
        if not combo.get_visible():
            return None

        return combo.get_model()[combo.get_active()][0]

    def get_config_fs_type(self):
        name = "fs-type-combo"
        combo = self.widget(name)
        if not combo.get_visible():
            return None

        return combo.get_model()[combo.get_active()][0]

    def get_config_fs_readonly(self):
        name = "fs-readonly"
        check = self.widget(name)
        if not check.get_visible():
            return None

        return check.get_active()

    def get_config_fs_driver(self):
        name = "fs-driver-combo"
        combo = self.widget(name)
        if not combo.get_visible():
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
        service = self.widget("usbredir-service")
        if not host.get_visible():
            return None, None

        return host.get_text(), int(service.get_value())

    def get_config_usbredir_type(self):
        typebox = self.widget("usbredir-list")
        return typebox.get_model()[typebox.get_active()][0]

    # TPM getters
    def get_config_tpm_type(self):
        typ = self.widget("tpm-type")
        typestr = typ.get_model().get_value(typ.get_active_iter(), 0)
        return typestr

    # RNG getters
    def get_config_rng_type(self):
        src = self.widget("rng-type")
        idx = src.get_active()
        if idx < 0:
            return None

        selected_type = src.get_model()[idx][0]
        return selected_type

    def get_config_rng_device(self):
        if self.get_config_rng_type() == virtinst.VirtualRNGDevice.TYPE_RANDOM:
            return self.widget("rng-device").get_text()

        return None

    def get_config_rng_host(self):
        if self.get_config_rng_type() == virtinst.VirtualRNGDevice.TYPE_EGD:
            return self.widget("rng-host").get_text()

        return None

    def get_config_rng_service(self):
        if self.get_config_rng_type() == virtinst.VirtualRNGDevice.TYPE_EGD:
            return self.widget("rng-service").get_text()

        return None

    def get_config_rng_backend_type(self):
        active = self.widget("rng-backend-type").get_active()
        model = self.widget("rng-backend-type").get_model()
        return model[active][0]

    def get_config_rng_backend_mode(self):
        active = self.widget("rng-backend-mode").get_active()
        model = self.widget("rng-backend-mode").get_model()
        return model[active][0]

    ################
    # UI listeners #
    ################

    def set_hw_selection(self, page):
        uihelpers.set_list_selection(self.widget("hw-list"), page)

    def get_hw_selection(self):
        return uihelpers.get_list_selection(self.widget("hw-list"))

    def update_char_device_type_model(self):
        rhel6_blacklist = ["pipe", "udp"]

        # Char device type
        char_devtype = self.widget("char-device-type")
        char_devtype_model = char_devtype.get_model()
        char_devtype_model.clear()
        char_class = self.get_char_type()

        # Type name, desc
        for t in char_class.TYPES:
            if (t in rhel6_blacklist and
                not self.vm.rhel6_defaults()):
                continue

            desc = char_class.pretty_type(t)
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
            self.widget("char-device-type").emit("changed")
            self.widget("char-target-name").emit("changed")

        if page == PAGE_HOSTDEV:
            (ignore, devtype, devcap,
             subtype, subcap) = self.get_config_host_device_type_info()
            self.populate_host_device_model(devtype, devcap,
                                            subtype, subcap)

        self.set_page_title(page)
        notebook.get_nth_page(page).show()
        notebook.set_current_page(page)

    def show_pair_combo(self, basename, show_combo):
        combo = self.widget(basename + "-combo")
        label = self.widget(basename + "-label")

        combo.set_visible(show_combo)
        label.set_visible(not show_combo)

    def show_check_button(self, basename, show):
        check = self.widget(basename)
        check.set_visible(show)

    # Storage listeners
    def browse_storage(self, ignore1):
        self._browse_file(self.widget("config-storage-entry"))

    def toggle_storage_select(self, src):
        act = src.get_active()
        self.widget("config-storage-browse-box").set_sensitive(act)
        self.populate_disk_format_combo(not act)

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
        self.change_port_auto()

    def change_port_auto(self, ignore=None):
        gtype = self.get_config_graphics()
        is_auto = self.widget("graphics-port-auto").get_active()
        is_spice = (gtype == "spice")

        uihelpers.set_grid_row_visible(self.widget("graphics-port-box"),
                                       not is_auto)
        self.widget("graphics-port-box").set_visible(not is_auto)
        self.widget("graphics-tlsport-box").set_visible(is_spice)

    def change_password_chk(self, ignore=None):
        if self.widget("graphics-password-chk").get_active():
            self.widget("graphics-password").set_sensitive(True)
        else:
            self.widget("graphics-password").set_text("")
            self.widget("graphics-password").set_sensitive(False)

    # Char device listeners
    def get_char_type(self):
        row = self.get_hw_selection()
        label = "serial"

        if row:
            label = row[5]

        if label == "parallel":
            return VirtualParallelDevice
        elif label == "channel":
            return VirtualChannelDevice
        elif label == "console":
            return VirtualConsoleDevice
        return VirtualSerialDevice

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
        if page == PAGE_TPM:
            return _("TPM")
        if page == PAGE_RNG:
            return _("Random Number Generator")

        if page == PAGE_CHAR:
            char_class = self.get_char_type()
            return char_class.virtual_device_type.capitalize() + " Device"
        if page == PAGE_HOSTDEV:
            return self.get_config_host_device_type_info()[0]

        raise RuntimeError("Unknown page %s" % page)

    def set_page_title(self, page):
        title = self.dev_to_title(page)
        markup = "<span size='large' color='white'>%s</span>" % title
        self.widget("page-title-label").set_markup(markup)

    def change_tpm_device_type(self, src):
        idx = src.get_active()
        if idx < 0:
            return

        tpm_widget_mappings = {
            "device_path" : "tpm-device-path",
        }

        devtype = src.get_model()[src.get_active()][0]
        conn = self.conn.get_backend()

        self._dev = VirtualTPMDevice(conn)
        self._dev.type = devtype

        for param_name, widget_name in tpm_widget_mappings.items():
            make_visible = self._dev.supports_property(param_name)
            uihelpers.set_grid_row_visible(self.widget(widget_name + "-label"),
                                           make_visible)

    def change_char_target_name(self, src):
        if not src.get_visible():
            return

        text = src.get_child().get_text()
        settype = None
        if text == VirtualChannelDevice.CHANNEL_NAME_SPICE:
            settype = "spicevmc"
        elif (text == VirtualChannelDevice.CHANNEL_NAME_QEMUGA or
              text == VirtualChannelDevice.CHANNEL_NAME_LIBGUESTFS):
            settype = "unix"
        uihelpers.set_row_selection(self.widget("char-device-type"), settype)

    def change_char_device_type(self, src):
        idx = src.get_active()
        if idx < 0:
            return

        char_widget_mappings = {
            "source_path" : "char-path",
            "source_mode" : "char-mode",
            "source_host" : "char-host",
            "bind_host" : "char-bind-host",
            "protocol"  : "char-use-telnet",
        }

        char_class = self.get_char_type()
        devtype = src.get_model()[src.get_active()][0]
        conn = self.conn.get_backend()
        ischan = char_class.virtual_device_type == "channel"
        iscon = char_class.virtual_device_type == "console"

        self._dev = char_class(conn)
        self._dev.type = devtype

        for param_name, widget_name in char_widget_mappings.items():
            make_visible = self._dev.supports_property(param_name)
            uihelpers.set_grid_row_visible(self.widget(widget_name + "-label"),
                                           make_visible)

        uihelpers.set_grid_row_visible(
            self.widget("char-target-name-label"), ischan)
        uihelpers.set_grid_row_visible(
            self.widget("char-target-type-label"), iscon)

        has_mode = self._dev.supports_property("source_mode")
        if has_mode and self.widget("char-mode").get_active() == -1:
            self.widget("char-mode").set_active(0)

    def change_usbredir_type(self, src):
        idx = src.get_active()
        if idx < 0:
            return

        showhost = src.get_model()[src.get_active()][2]
        uihelpers.set_grid_row_visible(self.widget("usbredir-host-box"),
                                       showhost)

    def change_rng_type(self, ignore1):
        model = self.get_config_rng_type()
        if model is None:
            return

        is_egd = model == virtinst.VirtualRNGDevice.TYPE_EGD
        uihelpers.set_grid_row_visible(self.widget("rng-device"), not is_egd)
        uihelpers.set_grid_row_visible(self.widget("rng-host"), is_egd)
        uihelpers.set_grid_row_visible(self.widget("rng-service"), is_egd)
        uihelpers.set_grid_row_visible(self.widget("rng-backend-mode"), is_egd)
        uihelpers.set_grid_row_visible(self.widget("rng-backend-type"), is_egd)

    # FS listeners
    def browse_fs_source(self, ignore1):
        self._browse_file(self.widget("fs-source"), isdir=True)

    def change_fs_type(self, src):
        idx = src.get_active()
        fstype = None
        show_mode_combo = False
        show_driver_combo = False
        show_wrpolicy_combo = self.conn.is_qemu()

        if idx >= 0 and src.get_visible():
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
        fsdriver = None
        idx = src.get_active()
        if idx >= 0 and src.get_visible():
            fsdriver = src.get_model()[idx][0]

        show_mode = bool(
            fsdriver == virtinst.VirtualFilesystem.DRIVER_PATH or
            fsdriver == virtinst.VirtualFilesystem.DRIVER_DEFAULT)
        uihelpers.set_grid_row_visible(self.widget("fs-mode-box"), show_mode)

        show_wrpol = bool(
            fsdriver and fsdriver != virtinst.VirtualFilesystem.DRIVER_DEFAULT)
        uihelpers.set_grid_row_visible(self.widget("fs-wrpolicy-box"),
                                       show_wrpol)



    ######################
    # Add device methods #
    ######################

    def setup_device(self, asyncjob):
        logging.debug("Running setup for device=%s", self._dev)
        self._dev.setup(meter=asyncjob.get_meter())
        logging.debug("Setup complete")

    def add_device(self):
        self._dev.get_xml_config()
        logging.debug("Adding device:\n" + self._dev.get_xml_config())

        controller = getattr(self._dev, "vmm_controller", None)
        if controller is not None:
            logging.debug("Adding controller:\n%s",
                          self._dev.vmm_controller.get_xml_config())
        # Hotplug device
        attach_err = False
        try:
            if controller is not None:
                self.vm.attach_device(self._dev.vmm_controller)
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
                dialog_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.YES_NO,
                modal=True)

            if not res:
                return False

        # Alter persistent config
        try:
            if controller is not None:
                self.vm.add_device(self._dev.vmm_controller)
            self.vm.add_device(self._dev)
        except Exception, e:
            self.err.show_err(_("Error adding device: %s" % str(e)))
            return True

        return False

    def _finish_cb(self, error, details):
        failure = True
        if not error:
            try:
                failure = self.add_device()
            except Exception, e:
                failure = True
                error = _("Unable to add device: %s") % str(e)
                details = "".join(traceback.format_exc())

        if error is not None:
            self.err.show_err(error, details=details)

        self.topwin.set_sensitive(True)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.TOP_LEFT_ARROW))

        self._dev = None
        if not failure:
            self.close()

    def finish(self, ignore=None):
        notebook = self.widget("create-pages")
        try:
            if self.validate(notebook.get_current_page()) is False:
                return
        except Exception, e:
            self.err.show_err(_("Uncaught error validating hardware "
                                "input: %s") % str(e))
            return

        self.topwin.set_sensitive(False)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.WATCH))

        progWin = vmmAsyncJob(self.setup_device, [],
                              self._finish_cb, [],
                              _("Creating device"),
                              _("Depending on the device, this may take "
                                "a few minutes to complete."),
                              self.topwin)
        progWin.run()


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
        elif page_num == PAGE_TPM:
            return self.validate_page_tpm()
        elif page_num == PAGE_RNG:
            return self.validate_page_rng()

    def validate_page_storage(self):
        bus, device = self.get_config_disk_target()
        cache = self.get_config_disk_cache()
        fmt = self.get_config_disk_format()
        controller_model = None
        conn = self.conn.get_backend()

        if bus == "virtio-scsi":
            bus = "scsi"
            controller_model = "virtio-scsi"

        # Make sure default pool is running
        if self.is_default_storage():
            ret = uihelpers.check_default_pool_active(self.err, self.conn)
            if not ret:
                return False

        readonly = False
        if device == virtinst.VirtualDisk.DEVICE_CDROM:
            readonly = True

        try:
            # This can error out
            collidelist = [d.path for d in self.vm.get_disk_devices()]
            diskpath, disksize, sparse = self.get_storage_info(collidelist)
            if self.is_default_storage():
                diskpath = self.check_ideal_path(diskpath, collidelist)

            disk = virtinst.VirtualDisk(conn)
            disk.path = diskpath
            disk.read_only = readonly
            disk.device = device
            disk.bus = bus
            disk.set_create_storage(size=disksize, sparse=sparse,
                                    fmt=fmt or None)
            disk.driver_cache = cache

            if not fmt:
                fmt = self.conn.get_default_storage_format()
                if (self.is_default_storage() and
                    disk.get_vol_install() and
                    fmt in disk.get_vol_install().list_formats()):
                    logging.debug("Setting disk format from prefs: %s", fmt)
                    disk.get_vol_install().format = fmt

            if (disk.type == virtinst.VirtualDisk.TYPE_FILE and
                not self.vm.is_hvm() and
                util.is_blktap_capable(self.conn.get_backend())):
                disk.driver_name = virtinst.VirtualDisk.DRIVER_TAP

            disk.validate()

        except Exception, e:
            return self.err.val_err(_("Storage parameter error."), e)

        # Generate target
        if not self.is_customize_dialog:
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
        names = disk.is_conflict_disk(conn)
        if names:
            res = self.err.yes_no(
                    _('Disk "%s" is already in use by other guests %s') %
                     (disk.path, names),
                    _("Do you really want to use the disk?"))
            if not res:
                return False

        uihelpers.check_path_search_for_qemu(self.err, self.conn, disk.path)

        # Add a SCSI controller with model virtio-scsi if needed
        disk.vmm_controller = None
        if (controller_model == "virtio-scsi") and (bus == "scsi"):
            controllers = self.vm.get_controller_devices()
            controller = VirtualController(conn)
            controller.type = "scsi"
            controller.model = controller_model
            disk.vmm_controller = controller
            for d in controllers:
                if controller.type == d.type:
                    controller.index += 1
                if controller_model == d.model:
                    disk.vmm_controller = None
                    controller = d
                    break

            disk.address.type = disk.address.ADDRESS_TYPE_DRIVE
            disk.address.controller = controller.index

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

        ret = uihelpers.validate_network(self.err, self.conn,
                                         nettype, devname, mac, model)
        if ret is False:
            return False

        self._dev = ret

    def validate_page_input(self):
        ignore, inp_type, inp_bus = self.get_config_input()
        dev = virtinst.VirtualInputDevice(self.conn.get_backend())
        dev.type = inp_type
        dev.bus = inp_bus

        self._dev = dev

    def validate_page_graphics(self):
        gtype = self.get_config_graphics()

        try:
            port, tlsport = self.get_config_graphics_ports()
            self._dev = virtinst.VirtualGraphics(self.conn.get_backend())
            self._dev.type = gtype
            self._dev.port = port
            self._dev.passwd = self.get_config_graphics_password()
            self._dev.listen = self.get_config_graphics_address()
            if gtype == "spice":
                self._dev.tlsPort = tlsport
        except ValueError, e:
            self.err.val_err(_("Graphics device parameter error"), e)

    def validate_page_sound(self):
        smodel = self.get_config_sound_model()
        try:
            self._dev = virtinst.VirtualAudio(self.conn.get_backend())
            self._dev.model = smodel
        except Exception, e:
            return self.err.val_err(_("Sound device parameter error"), e)

    def validate_page_hostdev(self):
        ret = self.get_config_host_device_info()
        nodedev_name = ret and ret[1] or None
        is_dup = False

        if nodedev_name is None:
            return self.err.val_err(_("Physical Device Required"),
                                    _("A device must be selected."))

        devtype = ret[2]
        nodedev = ret[3]
        if devtype == "usb_device":
            vendor = nodedev.vendor_id
            product = nodedev.product_id
            count = self.conn.get_nodedevs_number(devtype, vendor, product)
            if not count:
                raise RuntimeError(_("Could not find USB device "
                                     "(vendorId: %s, productId: %s) "
                                     % (vendor, product)))
            if count > 1:
                is_dup = True

        try:
            dev = virtinst.VirtualHostDevice(self.conn.get_backend())
            dev.set_from_nodedev(nodedev, use_full_usb=is_dup)
            self._dev = dev
        except Exception, e:
            return self.err.val_err(_("Host device parameter error"), e)

    def validate_page_char(self):
        charclass = self.get_char_type()
        modebox = self.widget("char-mode")
        devbox = self.widget("char-device-type")
        typebox = self.widget("char-target-type")
        devtype = devbox.get_model()[devbox.get_active()][0]
        conn = self.conn.get_backend()

        devclass = charclass(conn)
        devclass.type = devtype

        source_path = self.widget("char-path").get_text()
        source_mode = modebox.get_model()[modebox.get_active()][0]
        source_host = self.widget("char-host").get_text()
        bind_host = self.widget("char-bind-host").get_text()
        source_port = self.widget("char-port").get_value()
        bind_port = self.widget("char-bind-port").get_value()
        target_name = self.widget("char-target-name").get_child().get_text()
        target_type = typebox.get_model()[typebox.get_active()][0]

        if self.widget("char-use-telnet").get_active():
            protocol = VirtualSerialDevice.PROTOCOL_TELNET
        else:
            protocol = VirtualSerialDevice.PROTOCOL_RAW

        value_mappings = {
            "source_path" : source_path,
            "source_mode" : source_mode,
            "source_host" : source_host,
            "source_port" : source_port,
            "bind_port": bind_port,
            "bind_host": bind_host,
            "protocol": protocol,
            "target_name": target_name,
            "target_type": target_type,
        }

        try:
            self._dev = devclass

            for param_name, val in value_mappings.items():
                if self._dev.supports_property(param_name):
                    setattr(self._dev, param_name, val)

            # Dump XML for sanity checking
            self._dev.get_xml_config()
        except Exception, e:
            return self.err.val_err(
                    _("%s device parameter error") %
                    charclass.virtual_device_type.capitalize(), e)

    def validate_page_video(self):
        conn = self.conn.get_backend()
        model = self.get_config_video_model()

        try:
            self._dev = VirtualVideoDevice(conn)
            self._dev.model = model
        except Exception, e:
            return self.err.val_err(_("Video device parameter error"), e)

    def validate_page_watchdog(self):
        conn = self.conn.get_backend()
        model = self.get_config_watchdog_model()
        action = self.get_config_watchdog_action()

        try:
            self._dev = VirtualWatchdog(conn)
            self._dev.model = model
            self._dev.action = action
        except Exception, e:
            return self.err.val_err(_("Watchdog parameter error"), e)

    def validate_page_filesystem(self):
        conn = self.conn.get_backend()
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
            self._dev = virtinst.VirtualFilesystem(conn)
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
        conn = self.conn.get_backend()
        mode = self.get_config_smartcard_mode()

        try:
            self._dev = VirtualSmartCardDevice(conn)
            self._dev.mode = mode
            self._dev.validate()
        except Exception, e:
            return self.err.val_err(_("Smartcard device parameter error"), e)

    def validate_page_usbredir(self):
        conn = self.conn.get_backend()
        stype = self.get_config_usbredir_type()
        host, service = self.get_config_usbredir_host()

        try:
            self._dev = VirtualRedirDevice(conn)
            self._dev.type = stype
            if host:
                self._dev.host = host
            if service:
                self._dev.service = service
        except Exception, e:
            return self.err.val_err(_("USB redirected device parameter error"),
                                    str(e))

    def validate_page_tpm(self):
        conn = self.conn.get_backend()
        typ = self.get_config_tpm_type()

        device_path = self.widget("tpm-device-path").get_text()

        value_mappings = {
            "device_path" : device_path,
        }

        try:
            self._dev = VirtualTPMDevice(conn)
            self._dev.type = typ
            for param_name, val in value_mappings.items():
                if self._dev.supports_property(param_name):
                    setattr(self._dev, param_name, val)
        except Exception, e:
            return self.err.val_err(_("TPM device parameter error"), e)

    def validate_page_rng(self):
        conn = self.conn.get_backend()
        model = self.get_config_rng_type()

        if model == virtinst.VirtualRNGDevice.TYPE_RANDOM:
            if not self.get_config_rng_device():
                return self.err.val_err(_("RNG selection error."),
                                    _("A device must be specified."))
        elif model == virtinst.VirtualRNGDevice.TYPE_EGD:
            if not self.get_config_rng_host():
                return self.err.val_err(_("RNG selection error."),
                                    _("The EGD host must be specified."))

            if not self.get_config_rng_service():
                return self.err.val_err(_("RNG selection error."),
                                    _("The EGD service must be specified."))
        else:
            return self.err.val_err(_("RNG selection error."),
                                    _("Invalid RNG type."))

        value_mappings = {
            "backend_mode" : "connect",
            "backend_type" : self.get_config_rng_backend_type(),
            "backend_source_mode" : self.get_config_rng_backend_mode(),
            "backend_source_host" : self.get_config_rng_host(),
            "backend_source_service" : self.get_config_rng_service(),
            "device" : self.get_config_rng_device(),
        }

        try:
            self._dev = virtinst.VirtualRNGDevice(conn)
            self._dev.type = self.get_config_rng_type()
            for param_name, val in value_mappings.items():
                if self._dev.supports_property(param_name):
                    setattr(self._dev, param_name, val)
        except Exception, e:
            return self.err.val_err(_("RNG device parameter error"), e)


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
        if self.storage_browser is None:
            self.storage_browser = vmmStorageBrowser(conn)

        rhel6 = self.vm.rhel6_defaults()
        self.storage_browser.rhel6_defaults = rhel6

        self.storage_browser.set_finish_cb(set_storage_cb)
        self.storage_browser.set_browse_reason(reason)

        self.storage_browser.show(self.topwin, conn)

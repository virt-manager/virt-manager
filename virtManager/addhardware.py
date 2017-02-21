#
# Copyright (C) 2006-2007, 2012-2015 Red Hat, Inc.
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
import collections

from gi.repository import Gtk
from gi.repository import Gdk

import virtinst
from virtinst import (VirtualChannelDevice, VirtualParallelDevice,
                      VirtualSerialDevice, VirtualConsoleDevice,
                      VirtualVideoDevice, VirtualWatchdog,
                      VirtualSmartCardDevice, VirtualRedirDevice,
                      VirtualTPMDevice, VirtualPanicDevice)
from virtinst import VirtualController

from . import uiutil
from .fsdetails import vmmFSDetails
from .gfxdetails import vmmGraphicsDetails
from .netlist import vmmNetworkList
from .asyncjob import vmmAsyncJob
from .storagebrowse import vmmStorageBrowser
from .baseclass import vmmGObjectUI
from .addstorage import vmmAddStorage

(PAGE_ERROR,
PAGE_DISK,
PAGE_CONTROLLER,
PAGE_NETWORK,
PAGE_INPUT,
PAGE_GRAPHICS,
PAGE_SOUND,
PAGE_HOSTDEV,
PAGE_CHAR,
PAGE_VIDEO,
PAGE_WATCHDOG,
PAGE_FILESYSTEM,
PAGE_SMARTCARD,
PAGE_USBREDIR,
PAGE_TPM,
PAGE_RNG,
PAGE_PANIC,
) = range(0, 17)


class vmmAddHardware(vmmGObjectUI):
    def __init__(self, vm, is_customize_dialog):
        vmmGObjectUI.__init__(self, "addhardware.ui", "vmm-add-hardware")

        self.vm = vm
        self.conn = vm.conn
        self.is_customize_dialog = is_customize_dialog

        self._storagebrowser = None

        self._dev = None
        self._remove_usb_controller = None
        self._selected_model = None

        self._gfxdetails = vmmGraphicsDetails(
            self.vm, self.builder, self.topwin)
        self.widget("graphics-align").add(self._gfxdetails.top_box)

        self._fsdetails = vmmFSDetails(self.vm, self.builder, self.topwin)
        self.widget("fs-box").add(self._fsdetails.top_box)

        self._netlist = vmmNetworkList(self.conn, self.builder, self.topwin)
        self.widget("network-source-label-align").add(self._netlist.top_label)
        self.widget("network-source-ui-align").add(self._netlist.top_box)
        self.widget("network-vport-align").add(self._netlist.top_vport)

        self.addstorage = vmmAddStorage(self.conn, self.builder, self.topwin)
        self.widget("storage-align").add(self.addstorage.top_box)
        self.addstorage.connect("browse-clicked", self._browse_storage_cb)

        self.builder.connect_signals({
            "on_create_cancel_clicked" : self.close,
            "on_vmm_create_delete_event" : self.close,
            "on_create_finish_clicked" : self._finish,
            "on_hw_list_changed": self._hw_selected,

            "on_storage_devtype_changed": self._change_storage_devtype,

            "on_mac_address_clicked" : self._change_macaddr_use,

            "on_char_device_type_changed": self._change_char_device_type,
            "on_char_target_name_changed": self._change_char_target_name,
            "on_char_auto_socket_toggled": self._change_char_auto_socket,

            "on_tpm_device_type_changed": self._change_tpm_device_type,

            "on_usbredir_type_changed": self._change_usbredir_type,

            "on_rng_type_changed": self._change_rng,
            "on_rng_backend_mode_changed": self._change_rng,
            "on_rng_backend_type_changed": self._change_rng,

            "on_controller_type_changed": self._populate_controller_model,
        })
        self.bind_escape_key_close()

        self._set_initial_state()

    def show(self, parent):
        logging.debug("Showing addhw")
        self._reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()
        self.conn.schedule_priority_tick(pollnet=True,
                                         pollpool=True, polliface=True,
                                         pollnodedev=True)

    def close(self, ignore1=None, ignore2=None):
        if self.topwin.is_visible():
            logging.debug("Closing addhw")
            self.topwin.hide()
        if self._storagebrowser:
            self._storagebrowser.close()

        return 1

    def _cleanup(self):
        self.vm = None
        self.conn = None
        self._dev = None

        if self._storagebrowser:
            self._storagebrowser.cleanup()
            self._storagebrowser = None

        self._gfxdetails.cleanup()
        self._gfxdetails = None
        self._fsdetails.cleanup()
        self._fsdetails = None
        self._netlist.cleanup()
        self._netlist = None
        self.addstorage.cleanup()
        self.addstorage = None

    def is_visible(self):
        return self.topwin.get_visible()


    ##########################
    # Initialization methods #
    ##########################

    def _set_initial_state(self):
        notebook = self.widget("create-pages")
        notebook.set_show_tabs(False)

        blue = Gdk.color_parse("#0072A8")
        self.widget("page-title-box").modify_bg(Gtk.StateType.NORMAL, blue)

        # Name, icon name, page number, is sensitive, tooltip, icon size,
        # device type (serial/parallel)...
        model = Gtk.ListStore(str, str, int, bool, str, str)
        hw_list = self.widget("hw-list")
        hw_list.set_model(model)

        hw_col = Gtk.TreeViewColumn(_("Hardware"))
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

        # Network model list
        netmodel_list = self.widget("net-model")
        self.build_network_model_combo(self.vm, netmodel_list)

        # Disk bus type
        self.build_disk_bus_combo(self.vm,
            self.widget("storage-bustype"))

        # Disk device type
        target_list = self.widget("storage-devtype")
        # [device, icon, label]
        target_model = Gtk.ListStore(str, str, str)
        target_list.set_model(target_model)
        icon = Gtk.CellRendererPixbuf()
        icon.set_property("stock-size", Gtk.IconSize.BUTTON)
        target_list.pack_start(icon, False)
        target_list.add_attribute(icon, 'icon-name', 1)
        text = Gtk.CellRendererText()
        text.set_property("xpad", 6)
        target_list.pack_start(text, True)
        target_list.add_attribute(text, 'text', 2)
        target_model.append([virtinst.VirtualDisk.DEVICE_DISK,
                      "drive-harddisk", _("Disk device")])
        target_model.append([virtinst.VirtualDisk.DEVICE_CDROM,
                      "media-cdrom", _("CDROM device")])
        target_model.append([virtinst.VirtualDisk.DEVICE_FLOPPY,
                      "media-floppy", _("Floppy device")])
        if self.conn.is_qemu() or self.conn.is_test_conn():
            target_model.append([virtinst.VirtualDisk.DEVICE_LUN,
                          "drive-harddisk", _("LUN Passthrough")])
        target_list.set_active(0)

        # Disk cache mode
        cache_list = self.widget("storage-cache")
        self.build_disk_cache_combo(self.vm, cache_list)

        # Input device type
        input_list = self.widget("input-type")
        input_model = Gtk.ListStore(str, str, str)
        input_list.set_model(input_model)
        uiutil.init_combo_text_column(input_list, 0)

        # Sound model list
        sound_list = self.widget("sound-model")
        self.build_sound_combo(self.vm, sound_list)

        # Host device list
        host_dev = self.widget("host-device")
        # [ prettyname, xmlobj ]
        host_dev_model = Gtk.ListStore(str, object)
        host_dev.set_model(host_dev_model)
        host_col = Gtk.TreeViewColumn()
        text = Gtk.CellRendererText()
        host_col.pack_start(text, True)
        host_col.add_attribute(text, 'text', 0)
        host_dev_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        host_dev.append_column(host_col)

        # Video device
        video_dev = self.widget("video-model")
        self.build_video_combo(self.vm, video_dev)

        # Character dev mode
        char_mode = self.widget("char-mode")
        # Mode name, desc
        char_mode_model = Gtk.ListStore(str, str)
        char_mode.set_model(char_mode_model)
        uiutil.init_combo_text_column(char_mode, 1)
        char_mode_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        for t in VirtualSerialDevice.MODES:
            desc = VirtualSerialDevice.pretty_mode(t)
            char_mode_model.append([t, desc + " (%s)" % t])

        # Char target type
        lst = self.widget("char-target-type")
        model = Gtk.ListStore(str, str)
        lst.set_model(model)
        uiutil.init_combo_text_column(lst, 1)
        if self.conn.is_qemu():
            model.append(["virtio", "VirtIO"])
        else:
            model.append([None, _("Hypervisor default")])

        # Char target name
        lst = self.widget("char-target-name")
        model = Gtk.ListStore(str)
        lst.set_model(model)
        uiutil.init_combo_text_column(lst, 0)
        for n in VirtualChannelDevice.CHANNEL_NAMES:
            model.append([n])

        # Char device type
        lst = self.widget("char-device-type")
        model = Gtk.ListStore(str, str)
        lst.set_model(model)
        uiutil.init_combo_text_column(lst, 1)

        # Watchdog widgets
        combo = self.widget("watchdog-model")
        self.build_watchdogmodel_combo(self.vm, combo)
        combo = self.widget("watchdog-action")
        self.build_watchdogaction_combo(self.vm, combo)

        # Smartcard widgets
        combo = self.widget("smartcard-mode")
        self.build_smartcard_mode_combo(self.vm, combo)

        # Usbredir widgets
        combo = self.widget("usbredir-list")
        self.build_redir_type_combo(self.vm, combo)

        # TPM widgets
        combo = self.widget("tpm-type")
        self.build_tpm_type_combo(self.vm, combo)

        # RNG widgets
        combo = self.widget("rng-type")
        self._build_rng_type_combo(combo)
        combo = self.widget("rng-backend-type")
        self._build_rng_backend_type_combo(combo)
        combo = self.widget("rng-backend-mode")
        self._build_rng_backend_mode_combo(combo)

        # Panic widgets
        combo = self.widget("panic-type")
        self._build_panic_address_type(combo)

        # Controller widgets
        combo = self.widget("controller-type")
        target_model = Gtk.ListStore(str, str)
        combo.set_model(target_model)
        uiutil.init_combo_text_column(combo, 1)
        combo = self.widget("controller-model")
        target_model = Gtk.ListStore(str, str)
        combo.set_model(target_model)
        uiutil.init_combo_text_column(combo, 1)

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

        add_hw_option(_("Storage"), "drive-harddisk", PAGE_DISK, have_storage,
                      have_storage and storage_tooltip or None)
        add_hw_option(_("Controller"), "device_pci", PAGE_CONTROLLER, True, None)
        add_hw_option(_("Network"), "network-idle", PAGE_NETWORK, True, None)
        add_hw_option(_("Input"), "input-mouse", PAGE_INPUT, self.vm.is_hvm(),
                      _("Not supported for this guest type."))
        add_hw_option(_("Graphics"), "video-display", PAGE_GRAPHICS,
                      True, None)
        add_hw_option(_("Sound"), "audio-card", PAGE_SOUND,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."))
        add_hw_option(_("Serial"), Gtk.STOCK_CONNECT, PAGE_CHAR,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."),
                      "serial")
        add_hw_option(_("Parallel"), Gtk.STOCK_CONNECT, PAGE_CHAR,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."),
                      "parallel")
        add_hw_option(_("Console"), Gtk.STOCK_CONNECT, PAGE_CHAR,
                      True, None, "console")
        add_hw_option(_("Channel"), Gtk.STOCK_CONNECT, PAGE_CHAR,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."),
                      "channel")
        add_hw_option(_("USB Host Device"), "system-run", PAGE_HOSTDEV,
                      self.conn.is_nodedev_capable(),
                      _("Connection does not support host device enumeration"),
                      "usb")

        nodedev_enabled = self.conn.is_nodedev_capable()
        nodedev_errstr = _("Connection does not support "
            "host device enumeration")
        if self.vm.is_container():
            nodedev_enabled = False
            nodedev_errstr = _("Not supported for containers")
        add_hw_option(_("PCI Host Device"), "system-run", PAGE_HOSTDEV,
                      nodedev_enabled, nodedev_errstr, "pci")

        add_hw_option(_("Video"), "video-display", PAGE_VIDEO, True,
                      _("Libvirt version does not support video devices."))
        add_hw_option(_("Watchdog"), "device_pci", PAGE_WATCHDOG,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."))
        add_hw_option(_("Filesystem"), "folder", PAGE_FILESYSTEM,
                      self.conn.check_support(
                        self.conn.SUPPORT_CONN_FILESYSTEM) and
                      not self.vm.stable_defaults(),
                      _("Not supported for this hypervisor/libvirt "
                        "combination."))
        add_hw_option(_("Smartcard"), "device_serial", PAGE_SMARTCARD,
                      True, None)
        add_hw_option(_("USB Redirection"), "device_usb", PAGE_USBREDIR,
                      True, None)
        add_hw_option(_("TPM"), "device_cpu", PAGE_TPM,
                      True, None)
        add_hw_option(_("RNG"), "system-run", PAGE_RNG, True, None)
        add_hw_option(_("Panic Notifier"), "system-run", PAGE_PANIC,
            self.conn.check_support(self.conn.SUPPORT_CONN_PANIC_DEVICE),
            _("Not supported for this hypervisor/libvirt combination."))

    def _reset_state(self):
        # Storage init
        self.widget("storage-devtype").set_active(0)
        self.widget("storage-devtype").emit("changed")
        self.addstorage.reset_state()

        # Network init
        newmac = virtinst.VirtualNetworkInterface.generate_mac(
                self.conn.get_backend())
        self.widget("mac-address").set_active(bool(newmac))
        self.widget("create-mac-address").set_text(newmac)
        self._change_macaddr_use()

        self._netlist.reset_state()

        netmodel = self.widget("net-model")
        self.populate_network_model_combo(self.vm, netmodel)
        netmodel.set_active(0)

        # Input device init
        input_box = self.widget("input-type")
        self._populate_input_model(input_box.get_model())
        input_box.set_active(0)

        # Graphics init
        self._gfxdetails.reset_state()

        # Sound init
        sound_box = self.widget("sound-model")
        sound_box.set_active(0)

        # Char parameters
        self.widget("char-device-type").set_active(0)
        self.widget("char-target-type").set_active(0)
        self.widget("char-target-name").set_active(0)
        self.widget("char-path").set_text("")
        self.widget("char-channel").set_text("")
        self.widget("char-host").set_text("127.0.0.1")
        self.widget("char-port").set_value(4555)
        self.widget("char-bind-host").set_text("127.0.0.1")
        self.widget("char-bind-port").set_value(4556)
        self.widget("char-use-telnet").set_active(False)
        self.widget("char-auto-socket").set_active(True)

        # FS params
        self._fsdetails.reset_state()

        # TPM params
        self.widget("tpm-device-path").set_text("/dev/tpm0")

        # Hide all notebook pages, so the wizard isn't as big as the largest
        # page
        notebook = self.widget("create-pages")
        for page in range(notebook.get_n_pages()):
            widget = notebook.get_nth_page(page)
            widget.hide()

        # RNG params
        self.widget("rng-device").set_text("/dev/random")
        for i in ["rng-bind-host", "rng-connect-host"]:
            self.widget(i).set_text("localhost")

        for i in ["rng-bind-service", "rng-connect-service"]:
            self.widget(i).set_text("708")

        # Panic device params
        self.widget("panic-iobase").set_text("0x505")

        # Controller device params
        self._populate_controller_type()

        self._set_hw_selection(0)


    #####################
    # Shared UI helpers #
    #####################

    @staticmethod
    def build_video_combo(vm, combo):
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        combo.get_model().set_sort_column_id(1, Gtk.SortType.ASCENDING)

        tmpdev = virtinst.VirtualVideoDevice(vm.conn.get_backend())
        for m in tmpdev.MODELS:
            model.append([m, tmpdev.pretty_model(m)])

        if len(model) > 0:
            combo.set_active(0)

    @staticmethod
    def build_sound_combo(vm, combo):
        model = Gtk.ListStore(str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 0)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        stable_defaults = vm.stable_defaults()
        stable_soundmodels = ["ich6", "ich9", "ac97"]

        for m in virtinst.VirtualAudio.MODELS:
            if (stable_defaults and m not in stable_soundmodels):
                continue

            model.append([m])
        if len(model) > 0:
            combo.set_active(0)

    @staticmethod
    def build_watchdogmodel_combo(vm, combo):
        ignore = vm
        model = Gtk.ListStore(str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 0)

        for m in virtinst.VirtualWatchdog.MODELS:
            model.append([m])
        if len(model) > 0:
            combo.set_active(0)

    @staticmethod
    def build_watchdogaction_combo(vm, combo):
        ignore = vm
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)

        for m in virtinst.VirtualWatchdog.ACTIONS:
            model.append([m, virtinst.VirtualWatchdog.get_action_desc(m)])
        if len(model) > 0:
            combo.set_active(0)

    @staticmethod
    def populate_network_model_combo(vm, combo):
        model = combo.get_model()
        model.clear()

        # [xml value, label]
        model.append([None, _("Hypervisor default")])
        if vm.is_hvm():
            mod_list = []
            if vm.get_hv_type() in ["kvm", "qemu", "test"]:
                mod_list.append("virtio")
            mod_list.append("rtl8139")
            mod_list.append("e1000")
            if vm.xmlobj.os.is_pseries():
                mod_list.append("spapr-vlan")
            if vm.get_hv_type() in ["xen", "test"]:
                mod_list.append("netfront")
            mod_list.sort()

            for m in mod_list:
                model.append([m, m])

    @staticmethod
    def build_network_model_combo(vm, combo):
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        vmmAddHardware.populate_network_model_combo(vm, combo)
        combo.set_active(0)

    @staticmethod
    def populate_smartcard_mode_combo(vm, combo):
        ignore = vm
        model = combo.get_model()
        model.clear()

        # [xml value, label]
        model.append(["passthrough", _("Passthrough")])
        model.append(["host", _("Host")])

    @staticmethod
    def build_smartcard_mode_combo(vm, combo):
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        vmmAddHardware.populate_smartcard_mode_combo(vm, combo)

        idx = -1
        for rowid in range(len(combo.get_model())):
            idx = 0
            row = combo.get_model()[rowid]
            if row[0] == virtinst.VirtualSmartCardDevice.MODE_DEFAULT:
                idx = rowid
                break
        combo.set_active(idx)

    @staticmethod
    def populate_redir_type_combo(vm, combo):
        ignore = vm
        model = combo.get_model()
        model.clear()

        # [xml value, label, conn details]
        model.append(["spicevmc", _("Spice channel"), False])
        model.append(["tcp", "TCP", True])

    @staticmethod
    def build_redir_type_combo(vm, combo):
        model = Gtk.ListStore(str, str, bool)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)

        vmmAddHardware.populate_redir_type_combo(vm, combo)
        combo.set_active(0)

    @staticmethod
    def populate_tpm_type_combo(vm, combo):
        ignore = vm
        types = combo.get_model()
        types.clear()

        # [xml value, label]
        for t in virtinst.VirtualTPMDevice.TYPES:
            types.append([t, virtinst.VirtualTPMDevice.get_pretty_type(t)])

    @staticmethod
    def build_tpm_type_combo(vm, combo):
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        vmmAddHardware.populate_tpm_type_combo(vm, combo)

        idx = -1
        for rowid in range(len(combo.get_model())):
            idx = 0
            row = combo.get_model()[rowid]
            if row[0] == virtinst.VirtualTPMDevice.TYPE_DEFAULT:
                idx = rowid
                break
        combo.set_active(idx)

    @staticmethod
    def build_disk_cache_combo(vm, combo):
        ignore = vm
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)

        combo.set_active(-1)
        for m in virtinst.VirtualDisk.cache_types:
            model.append([m, m])

        _iter = model.insert(0, [None, _("Hypervisor default")])
        combo.set_active_iter(_iter)

    @staticmethod
    def build_disk_io_combo(vm, combo, no_default=False):
        ignore = vm
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        combo.set_active(-1)
        for m in virtinst.VirtualDisk.io_modes:
            model.append([m, m])

        if not no_default:
            model.append([None, _("Hypervisor default")])
        combo.set_active(0)

    @staticmethod
    def build_disk_bus_combo(vm, combo):
        ignore = vm
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        model.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        combo.set_active(-1)

    @staticmethod
    def populate_disk_bus_combo(vm, devtype, model):
        # try to get supported disk bus types from domain capabilities
        domcaps = vm.get_domain_capabilities()
        disk_bus_types = None
        if "bus" in domcaps.devices.disk.enum_names():
            disk_bus_types = domcaps.devices.disk.get_enum("bus").get_values()

        # if there are no disk bus types in domain capabilities fallback to
        # old code
        if not disk_bus_types:
            disk_bus_types = []
            if vm.is_hvm():
                if not vm.get_xmlobj().os.is_q35():
                    disk_bus_types.append("ide")
                disk_bus_types.append("sata")
                disk_bus_types.append("fdc")

                if not vm.stable_defaults():
                    disk_bus_types.append("scsi")
                    disk_bus_types.append("usb")

            if vm.get_hv_type() in ["qemu", "kvm", "test"]:
                disk_bus_types.append("sd")
                disk_bus_types.append("virtio")
                if "scsi" not in disk_bus_types:
                    disk_bus_types.append("scsi")

            if vm.conn.is_xen() or vm.conn.is_test_conn():
                disk_bus_types.append("xen")

        rows = []
        for bus in disk_bus_types:
            rows.append([bus, virtinst.VirtualDisk.pretty_disk_bus(bus)])

        model.clear()

        bus_map = {
            "disk": ["ide", "sata", "scsi", "sd", "usb", "virtio", "xen"],
            "floppy": ["fdc"],
            "cdrom": ["ide", "sata", "scsi"],
            "lun": ["scsi"],
        }
        for row in rows:
            if row[0] in bus_map[devtype]:
                model.append(row)

    @staticmethod
    def populate_controller_model_combo(combo, controller_type):
        model = combo.get_model()
        model.clear()

        model.append([None, _("Hypervisor default")])
        if controller_type == virtinst.VirtualController.TYPE_USB:
            model.append(["ich9-ehci1", "USB 2"])
            model.append(["nec-xhci", "USB 3"])
        elif controller_type == virtinst.VirtualController.TYPE_SCSI:
            model.append(["virtio-scsi", "VirtIO SCSI"])

        combo.set_active(0)


    @staticmethod
    def label_for_input_device(typ, bus):
        if typ == "tablet" and bus == "usb":
            return _("EvTouch USB Graphics Tablet")

        if bus in ["usb", "ps2"]:
            return _("Generic") + (" %s %s" %
                (bus.upper(), str(typ).capitalize()))
        return "%s %s" % (str(bus).capitalize(), str(typ).capitalize())

    @staticmethod
    def change_config_helper(define_func, define_args, vm, err,
            devobj=None, hotplug_args=None):
        """
        UI helper that handles the logic and reports errors for the
        requested VM define and hotplug changes

        Used here and in details.py
        """
        hotplug_args = hotplug_args or {}

        # Persistent config change
        try:
            if devobj:
                # Device XML editing
                define_func(devobj=devobj, do_hotplug=False, **define_args)
            else:
                # Guest XML editing
                define_func(**define_args)
        except Exception, e:
            err.show_err((_("Error changing VM configuration: %s") %
                              str(e)))
            return False

        if not vm.is_active():
            return True

        # Hotplug change
        hotplug_err = None
        did_hotplug = False
        try:
            if devobj:
                define_func(devobj=devobj, do_hotplug=True, **define_args)
                did_hotplug = True
            elif hotplug_args:
                did_hotplug = True
                vm.hotplug(**hotplug_args)
        except Exception, e:
            did_hotplug = True
            logging.debug("Hotplug failed: %s", str(e))
            hotplug_err = ((str(e), "".join(traceback.format_exc())))

        if did_hotplug and not hotplug_err:
            return True

        if len(define_args) > 1:
            msg = _("Some changes may require a guest shutdown "
                    "to take effect.")
        else:
            msg = _("These changes will take effect after "
                    "the next guest shutdown.")

        dtype = (hotplug_err and
                 Gtk.MessageType.WARNING or Gtk.MessageType.INFO)
        hotplug_msg = ""
        if hotplug_err:
            hotplug_msg += (hotplug_err[0] + "\n\n" +
                            hotplug_err[1] + "\n")

        err.show_err(msg,
                details=hotplug_msg,
                buttons=Gtk.ButtonsType.OK,
                dialog_type=dtype)

        return True


    #########################
    # UI population methods #
    #########################

    def _refresh_disk_bus(self, devtype):
        widget = self.widget("storage-bustype")
        model = widget.get_model()
        self.populate_disk_bus_combo(self.vm, devtype, model)

        # By default, select bus of the first disk assigned to the VM
        default_bus = None
        for i in self.vm.get_disk_devices():
            if i.device == devtype:
                default_bus = i.bus
                break

        if default_bus:
            uiutil.set_list_selection(widget, default_bus)
        elif len(model) > 0:
            widget.set_active(0)

    def _populate_input_model(self, model):
        model.clear()
        def _add_row(typ, bus):
            model.append([self.label_for_input_device(typ, bus), typ, bus])

        _add_row("tablet", "usb")
        _add_row("mouse", "usb")
        _add_row("keyboard", "usb")

    def _populate_host_device_model(self, devtype, devcap, subtype, subcap):
        devlist = self.widget("host-device")
        model = devlist.get_model()
        model.clear()
        subdevs = []

        if subtype:
            subdevs = self.conn.filter_nodedevs(subtype, subcap)

        devs = self.conn.filter_nodedevs(devtype, devcap)
        for dev in devs:
            prettyname = dev.xmlobj.pretty_name()

            for subdev in subdevs:
                if dev.xmlobj.name == subdev.xmlobj.parent:
                    prettyname += " (%s)" % subdev.xmlobj.pretty_name()

            model.append([prettyname, dev.xmlobj])

        if len(model) == 0:
            model.append([_("No Devices Available"), None])
        uiutil.set_list_selection_by_number(devlist, 0)

    def _populate_controller_type(self):
        widget = self.widget("controller-type")
        model = widget.get_model()
        model.clear()

        for t in VirtualController.TYPES:
            if t == VirtualController.TYPE_PCI:
                continue
            model.append([t, VirtualController.pretty_type(t)])

        if len(model) > 0:
            widget.set_active(0)

    def _populate_controller_model(self, src):
        ignore = src

        def show_tooltip(model_tooltip, show):
            vmname = self.vm.get_name()
            tooltip = (_("%s already has a USB controller attached.\n"
            "Adding more than one USB controller is not supported.\n"
            "You can change the USB controller type in the VM details screen.")
            % vmname)
            model_tooltip.set_visible(show)
            model_tooltip.set_tooltip_text(tooltip)

        controller_type = uiutil.get_list_selection(
            self.widget("controller-type"))
        combo = self.widget("controller-model")
        combo.set_sensitive(True)
        model_tooltip = self.widget("controller-tooltip")
        show_tooltip(model_tooltip, False)

        controllers = self.vm.get_controller_devices()
        if controller_type == VirtualController.TYPE_USB:
            usb_controllers = [x for x in controllers if
                    (x.type == VirtualController.TYPE_USB)]
            if (len(usb_controllers) == 0):
                self.widget("create-finish").set_sensitive(True)
            elif (len(usb_controllers) == 1 and
                  usb_controllers[0].model == "none"):
                self._remove_usb_controller = usb_controllers[0]
                self.widget("create-finish").set_sensitive(True)
            else:
                show_tooltip(model_tooltip, True)
                self.widget("create-finish").set_sensitive(False)
        else:
            self.widget("create-finish").set_sensitive(True)

        self.populate_controller_model_combo(combo, controller_type)
        uiutil.set_grid_row_visible(combo, len(combo.get_model()) > 1)


    def _build_combo_with_values(self, combo, values, default=None):
        # [xml value, label]
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        for xmlval, label in values:
            model.append([xmlval, label])
        if default:
            uiutil.set_list_selection(combo, default)

    def _build_rng_type_combo(self, combo):
        types = []
        for t in virtinst.VirtualRNGDevice.TYPES:
            types.append([t, virtinst.VirtualRNGDevice.get_pretty_type(t)])

        self._build_combo_with_values(combo, types,
                                virtinst.VirtualRNGDevice.TYPE_RANDOM)

    def _build_rng_backend_type_combo(self, combo):
        default = virtinst.VirtualRNGDevice.BACKEND_TYPE_TCP

        types = []
        for t in virtinst.VirtualRNGDevice.BACKEND_TYPES:
            pprint = virtinst.VirtualRNGDevice.get_pretty_backend_type(t)
            types.append([t, pprint])

        self._build_combo_with_values(combo, types, default)

    def _build_rng_backend_mode_combo(self, combo):
        default = virtinst.VirtualRNGDevice.BACKEND_MODE_CONNECT

        types = []
        for t in virtinst.VirtualRNGDevice.BACKEND_MODES:
            pprint = virtinst.VirtualRNGDevice.get_pretty_backend_type(t)
            types.append([t, pprint])

        self._build_combo_with_values(combo, types, default)


    def _build_panic_address_type(self, combo):
        types = []
        for t in virtinst.VirtualPanicDevice.TYPES:
            types.append([t, virtinst.VirtualPanicDevice.get_pretty_type(t)])

        self._build_combo_with_values(combo, types,
                virtinst.VirtualPanicDevice.ADDRESS_TYPE_ISA)


    #########################
    # Internal misc helpers #
    #########################

    def _get_char_class(self):
        row = self._get_hw_selection()
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

    def _set_hw_selection(self, page):
        uiutil.set_list_selection_by_number(self.widget("hw-list"), page)

    def _get_hw_selection(self):
        return uiutil.get_list_selected_row(self.widget("hw-list"))


    ################
    # UI listeners #
    ################

    def _update_char_device_type_model(self):
        stable_blacklist = ["pipe", "udp"]

        # Char device type
        char_devtype = self.widget("char-device-type")
        char_devtype_model = char_devtype.get_model()
        char_devtype_model.clear()
        char_class = self._get_char_class()

        # Type name, desc
        for t in char_class.TYPES:
            if (t in stable_blacklist and
                self.vm.stable_defaults()):
                continue

            desc = char_class.pretty_type(t)
            row = [t, desc + " (%s)" % t]
            char_devtype_model.append(row)
        char_devtype.set_active(0)

    def _hw_selected(self, src=None):
        ignore = src
        self._dev = None
        notebook = self.widget("create-pages")

        row = self._get_hw_selection()
        if not row:
            self._set_hw_selection(0)
            return

        page = row[2]
        sens = row[3]
        msg = row[4] or ""

        self.widget("create-finish").set_sensitive(sens)

        if not sens:
            page = PAGE_ERROR
            self.widget("hardware-info").set_text(msg)

        if page == PAGE_CHAR:
            # Need to do this here, since we share the char page between
            # multiple different HW options
            self._update_char_device_type_model()
            self.widget("char-device-type").emit("changed")
            self.widget("char-target-name").emit("changed")

        if page == PAGE_HOSTDEV:
            # Need to do this here, since we share the hostdev page
            # between two different HW options
            pci_info = ["pci", None, "net", "80203"]
            usb_info = ["usb_device", None, None, None]
            row = self._get_hw_selection()
            if row and row[5] == "pci":
                info = pci_info
            else:
                info = usb_info

            (devtype, devcap, subtype, subcap) = info
            self._populate_host_device_model(devtype, devcap, subtype, subcap)

        self._set_page_title(page)
        notebook.get_nth_page(page).show()
        notebook.set_current_page(page)

    def _dev_to_title(self, page):
        if page == PAGE_ERROR:
            return _("Error")
        if page == PAGE_DISK:
            return _("Storage")
        if page == PAGE_CONTROLLER:
            return _("Controller")
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
        if page == PAGE_PANIC:
            return _("Panic Notifier")

        if page == PAGE_CHAR:
            char_class = self._get_char_class()
            return _("%s Device") % char_class.virtual_device_type.capitalize()
        if page == PAGE_HOSTDEV:
            row = self._get_hw_selection()
            if row and row[5] == "pci":
                return _("PCI Device")
            return _("USB Device")

        raise RuntimeError("Unknown page %s" % page)

    def _set_page_title(self, page):
        title = self._dev_to_title(page)
        markup = "<span size='large' color='white'>%s</span>" % title
        self.widget("page-title-label").set_markup(markup)


    #########################
    # Device page listeners #
    #########################

    def _change_storage_devtype(self, ignore):
        devtype = uiutil.get_list_selection(
            self.widget("storage-devtype"))
        self._refresh_disk_bus(devtype)

        allow_create = devtype not in ["cdrom", "floppy"]
        self.addstorage.widget("storage-create-box").set_sensitive(
            allow_create)
        if not allow_create:
            self.addstorage.widget("storage-select").set_active(True)

    def _change_macaddr_use(self, ignore=None):
        if self.widget("mac-address").get_active():
            self.widget("create-mac-address").set_sensitive(True)
        else:
            self.widget("create-mac-address").set_sensitive(False)

    def _change_tpm_device_type(self, src):
        devtype = uiutil.get_list_selection(src)
        if devtype is None:
            return

        tpm_widget_mappings = {
            "device_path" : "tpm-device-path",
        }

        self._dev = VirtualTPMDevice(self.conn.get_backend())
        self._dev.type = devtype

        for param_name, widget_name in tpm_widget_mappings.items():
            make_visible = self._dev.supports_property(param_name)
            uiutil.set_grid_row_visible(self.widget(widget_name + "-label"),
                                           make_visible)

    def _change_char_auto_socket(self, src):
        if not src.get_visible():
            return

        doshow = not src.get_active()
        uiutil.set_grid_row_visible(self.widget("char-path-label"), doshow)
        uiutil.set_grid_row_visible(self.widget("char-mode-label"), doshow)

    def _change_char_target_name(self, src):
        if not src.get_visible():
            return

        text = src.get_child().get_text()
        settype = None
        if text == VirtualChannelDevice.CHANNEL_NAME_SPICE:
            settype = "spicevmc"
        elif text == VirtualChannelDevice.CHANNEL_NAME_SPICE_WEBDAV:
            settype = "spiceport"
            self.widget("char-channel").set_text(text)
        elif (text == VirtualChannelDevice.CHANNEL_NAME_QEMUGA or
              text == VirtualChannelDevice.CHANNEL_NAME_LIBGUESTFS):
            settype = "unix"
        if settype:
            uiutil.set_list_selection(
                self.widget("char-device-type"), settype)

    def _change_char_device_type(self, src):
        devtype = uiutil.get_list_selection(src)
        if devtype is None:
            return

        char_widget_mappings = {
            "source_path" : "char-path",
            "source_channel" : "char-channel",
            "source_mode" : "char-mode",
            "source_host" : "char-host",
            "bind_host" : "char-bind-host",
            "protocol"  : "char-use-telnet",
        }

        char_class = self._get_char_class()
        ischan = char_class.virtual_device_type == "channel"
        iscon = char_class.virtual_device_type == "console"
        show_auto = (devtype == "unix" and ischan and
            self.conn.check_support(self.conn.SUPPORT_CONN_AUTOSOCKET))

        self._dev = char_class(self.conn.get_backend())
        self._dev.type = devtype

        for param_name, widget_name in char_widget_mappings.items():
            make_visible = self._dev.supports_property(param_name)
            uiutil.set_grid_row_visible(self.widget(widget_name + "-label"),
                                           make_visible)

        uiutil.set_grid_row_visible(
            self.widget("char-target-name-label"), ischan)
        uiutil.set_grid_row_visible(
            self.widget("char-target-type-label"), iscon)
        uiutil.set_grid_row_visible(
            self.widget("char-auto-socket-label"), show_auto)
        self.widget("char-auto-socket").emit("toggled")

        has_mode = self._dev.supports_property("source_mode")
        if has_mode and self.widget("char-mode").get_active() == -1:
            self.widget("char-mode").set_active(0)

    def _change_usbredir_type(self, src):
        showhost = uiutil.get_list_selection(src, column=2)
        if showhost is None:
            return
        uiutil.set_grid_row_visible(self.widget("usbredir-host-box"),
                                       showhost)

    def _change_rng(self, ignore1):
        rtype = uiutil.get_list_selection(self.widget("rng-type"))
        is_egd = rtype == virtinst.VirtualRNGDevice.TYPE_EGD
        uiutil.set_grid_row_visible(self.widget("rng-device"), not is_egd)
        uiutil.set_grid_row_visible(self.widget("rng-backend-type"), is_egd)

        backend_type = uiutil.get_list_selection(
            self.widget("rng-backend-type"))
        backend_mode = uiutil.get_list_selection(
            self.widget("rng-backend-mode"))
        udp = backend_type == virtinst.VirtualRNGDevice.BACKEND_TYPE_UDP
        bind = backend_mode == virtinst.VirtualRNGDevice.BACKEND_MODE_BIND

        v = is_egd and (udp or bind)
        uiutil.set_grid_row_visible(self.widget("rng-bind-host-box"), v)

        v = is_egd and (udp or not bind)
        uiutil.set_grid_row_visible(self.widget("rng-connect-host-box"), v)

        v = is_egd and not udp
        uiutil.set_grid_row_visible(self.widget("rng-backend-mode"), v)


    ######################
    # Add device methods #
    ######################

    def _setup_device(self, asyncjob):
        poolname = None
        if (self._dev.virtual_device_type == "disk" and
            self._dev.wants_storage_creation() and
            self._dev.get_parent_pool()):
            poolname = self._dev.get_parent_pool().name()

        logging.debug("Running setup() for device=%s", self._dev)
        self._dev.setup(meter=asyncjob.get_meter())
        logging.debug("Device setup() complete")

        if poolname:
            try:
                pool = self.conn.get_pool(poolname)
                self.idle_add(pool.refresh)
            except:
                logging.debug("Error looking up pool=%s for refresh after "
                    "storage creation.", poolname, exc_info=True)


    def _add_device(self):
        self._dev.get_xml_config()
        logging.debug("Adding device:\n" + self._dev.get_xml_config())

        if self._remove_usb_controller:
            kwargs = {}
            kwargs["model"] = self._selected_model

            self.change_config_helper(self.vm.define_controller,
                    kwargs, self.vm, self.err,
                    devobj=self._remove_usb_controller)

            self._remove_usb_controller = None
            self._selected_model = None

            return

        controller = getattr(self._dev, "vmm_controller", None)
        if controller is not None:
            logging.debug("Adding controller:\n%s",
                          controller.get_xml_config())
        # Hotplug device
        attach_err = False
        try:
            if controller is not None:
                self.vm.attach_device(controller)
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
                self.vm.add_device(controller)
            self.vm.add_device(self._dev)
        except Exception, e:
            self.err.show_err(_("Error adding device: %s") % str(e))
            return True

        return False

    def _finish_cb(self, error, details):
        failure = True
        if not error:
            try:
                failure = self._add_device()
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

    def _finish(self, ignore=None):
        try:
            if self._validate() is False:
                return
        except Exception, e:
            self.err.show_err(_("Uncaught error validating hardware "
                                "input: %s") % str(e))
            return

        self.topwin.set_sensitive(False)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.WATCH))

        progWin = vmmAsyncJob(self._setup_device, [],
                              self._finish_cb, [],
                              _("Creating device"),
                              _("Depending on the device, this may take "
                                "a few minutes to complete."),
                              self.topwin)
        progWin.run()


    ###########################
    # Page validation methods #
    ###########################

    def _validate(self):
        page_num = self.widget("create-pages").get_current_page()

        if page_num == PAGE_ERROR:
            self._dev = None
            ret = True
        elif page_num == PAGE_DISK:
            ret = self._validate_page_storage()
        elif page_num == PAGE_CONTROLLER:
            ret = self._validate_page_controller()
        elif page_num == PAGE_NETWORK:
            ret = self._validate_page_network()
        elif page_num == PAGE_INPUT:
            ret = self._validate_page_input()
        elif page_num == PAGE_GRAPHICS:
            ret = self._validate_page_graphics()
        elif page_num == PAGE_SOUND:
            ret = self._validate_page_sound()
        elif page_num == PAGE_HOSTDEV:
            ret = self._validate_page_hostdev()
        elif page_num == PAGE_CHAR:
            ret = self._validate_page_char()
        elif page_num == PAGE_VIDEO:
            ret = self._validate_page_video()
        elif page_num == PAGE_WATCHDOG:
            ret = self._validate_page_watchdog()
        elif page_num == PAGE_FILESYSTEM:
            ret = self._validate_page_filesystem()
        elif page_num == PAGE_SMARTCARD:
            ret = self._validate_page_smartcard()
        elif page_num == PAGE_USBREDIR:
            ret = self._validate_page_usbredir()
        elif page_num == PAGE_TPM:
            ret = self._validate_page_tpm()
        elif page_num == PAGE_RNG:
            ret = self._validate_page_rng()
        elif page_num == PAGE_PANIC:
            ret = self._validate_page_panic()

        if ret is not False and self._dev:
            self._dev.set_defaults(self.vm.get_xmlobj())
            self._dev.validate()
        return ret

    def _set_disk_controller(self, disk, controller_model, used_disks):
        # Add a SCSI controller with model virtio-scsi if needed
        disk.vmm_controller = None
        if controller_model != "virtio-scsi":
            return None

        # Get SCSI controllers
        controllers = self.vm.get_controller_devices()
        ctrls_scsi = [x for x in controllers if
                (x.type == VirtualController.TYPE_SCSI)]

        # Create possible new controller
        controller = VirtualController(self.conn.get_backend())
        controller.type = "scsi"
        controller.model = controller_model

        # And set its index
        controller.index = 0
        if ctrls_scsi:
            controller.index = max([x.index for x in ctrls_scsi]) + 1

        # Take only virtio-scsi ones
        ctrls_scsi = [x for x in ctrls_scsi
                      if x.model == controller_model]

        # Save occupied places per controller
        occupied = collections.defaultdict(int)
        for d in used_disks:
            if d.get_target_prefix() == disk.get_target_prefix():
                num = virtinst.VirtualDisk.target_to_num(d.target)
                occupied[num / 7] += 1
        for c in ctrls_scsi:
            if occupied[c.index] < 7:
                controller = c
                break
        else:
            disk.vmm_controller = controller

        return controller.index

    def _validate_page_storage(self):
        bus = uiutil.get_list_selection(
            self.widget("storage-bustype"))
        device = uiutil.get_list_selection(
            self.widget("storage-devtype"))
        cache = uiutil.get_list_selection(
            self.widget("storage-cache"))

        controller_model = None
        if (bus == "scsi" and
            self.vm.get_hv_type() in ["qemu", "kvm", "test"] and
            not self.vm.xmlobj.os.is_pseries()):
            controller_model = "virtio-scsi"

        collidelist = [d.path for d in self.vm.get_disk_devices()]
        try:
            disk = self.addstorage.validate_storage(self.vm.get_name(),
                collidelist=collidelist, device=device)
        except Exception, e:
            return self.err.val_err(_("Storage parameter error."), e)

        if disk is False:
            return False

        try:
            used = []
            disk.bus = bus
            if cache:
                disk.driver_cache = cache

            # Generate target
            disks = (self.vm.get_disk_devices() +
                     self.vm.get_disk_devices(inactive=True))
            for d in disks:
                if d.target not in used:
                    used.append(d.target)

            prefer_ctrl = self._set_disk_controller(
                disk, controller_model, disks)

            disk.generate_target(used, prefer_ctrl)
        except Exception, e:
            return self.err.val_err(_("Storage parameter error."), e)

        if self.addstorage.validate_disk_object(disk) is False:
            return False

        self._dev = disk
        return True


    def _validate_page_network(self):
        nettype = self._netlist.get_network_selection()[0]
        model = uiutil.get_list_selection(self.widget("net-model"))
        mac = None
        if self.widget("mac-address").get_active():
            mac = self.widget("create-mac-address").get_text()

        if not nettype:
            return self.err.val_err(_("Network selection error."),
                                    _("A network source must be selected."))

        if not mac:
            return self.err.val_err(_("Invalid MAC address"),
                                    _("A MAC address must be entered."))

        ret = self._netlist.validate_network(mac, model)
        if ret is False:
            return False

        self._dev = ret

    def _validate_page_input(self):
        row = uiutil.get_list_selected_row(self.widget("input-type"))
        dev = virtinst.VirtualInputDevice(self.conn.get_backend())
        dev.type = row[1]
        dev.bus = row[2]

        self._dev = dev

    def _validate_page_graphics(self):
        try:
            (gtype, port, tlsport, listen,
             addr, passwd, keymap, gl, rendernode) = self._gfxdetails.get_values()

            self._dev = virtinst.VirtualGraphics(self.conn.get_backend())
            self._dev.type = gtype
            self._dev.passwd = passwd
            self._dev.gl = gl
            self._dev.rendernode = rendernode

            if not listen or listen == "none":
                self._dev.set_listen_none()
            elif listen == "address":
                self._dev.listen = addr
                self._dev.port = port
                self._dev.tlsPort = tlsport
            else:
                raise ValueError(_("invalid listen type"))
            if keymap:
                self._dev.keymap = keymap
        except ValueError, e:
            self.err.val_err(_("Graphics device parameter error"), e)

    def _validate_page_sound(self):
        smodel = uiutil.get_list_selection(self.widget("sound-model"))

        try:
            self._dev = virtinst.VirtualAudio(self.conn.get_backend())
            self._dev.model = smodel
        except Exception, e:
            return self.err.val_err(_("Sound device parameter error"), e)

    def _validate_page_hostdev(self):
        nodedev = uiutil.get_list_selection(self.widget("host-device"), 1)
        if nodedev is None:
            return self.err.val_err(_("Physical Device Required"),
                                    _("A device must be selected."))

        try:
            dev = virtinst.VirtualHostDevice(self.conn.get_backend())
            # Hostdev collision
            names  = []
            for vm in self.conn.list_vms():
                for hostdev in vm.get_hostdev_devices():
                    if nodedev.compare_to_hostdev(hostdev):
                        names.append(vm.get_name())
            if names:
                res = self.err.yes_no(
                        _('The device is already in use by other guests %s') %
                         (names),
                        _("Do you really want to use the device?"))
                if not res:
                    return False
            dev.set_from_nodedev(nodedev)
            self._dev = dev
        except Exception, e:
            return self.err.val_err(_("Host device parameter error"), e)

    def _validate_page_char(self):
        char_class = self._get_char_class()
        modebox = self.widget("char-mode")
        devbox = self.widget("char-device-type")
        typebox = self.widget("char-target-type")
        devtype = uiutil.get_list_selection(devbox)
        conn = self.conn.get_backend()

        devclass = char_class(conn)
        devclass.type = devtype

        source_path = self.widget("char-path").get_text()
        source_channel = self.widget("char-channel").get_text()
        source_mode = uiutil.get_list_selection(modebox)
        source_host = self.widget("char-host").get_text()
        bind_host = self.widget("char-bind-host").get_text()
        source_port = self.widget("char-port").get_value()
        bind_port = self.widget("char-bind-port").get_value()
        target_name = self.widget("char-target-name").get_child().get_text()
        target_type = uiutil.get_list_selection(typebox)

        if self.widget("char-use-telnet").get_active():
            protocol = VirtualSerialDevice.PROTOCOL_TELNET
        else:
            protocol = VirtualSerialDevice.PROTOCOL_RAW

        if not self.widget("char-target-name").get_visible():
            target_name = None
        if not typebox.get_visible():
            target_type = None
        if (self.widget("char-auto-socket").get_visible() and
            self.widget("char-auto-socket").get_active()):
            source_path = None
            source_mode = "bind"

        if (devclass.type == "tcp" and source_mode == "bind"):
            devclass.bind_host = source_host
            devclass.bind_port = source_port
            source_host = source_port = source_mode = None

        value_mappings = {
            "source_path" : source_path,
            "source_channel" : source_channel,
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
                if self._dev.supports_property(param_name) and val is not None:
                    setattr(self._dev, param_name, val)

            # Dump XML for sanity checking
            self._dev.get_xml_config()
        except Exception, e:
            return self.err.val_err(
                    _("%s device parameter error") %
                    char_class.virtual_device_type.capitalize(), e)

    def _validate_page_video(self):
        conn = self.conn.get_backend()
        model = uiutil.get_list_selection(self.widget("video-model"))

        try:
            self._dev = VirtualVideoDevice(conn)
            self._dev.model = model
        except Exception, e:
            return self.err.val_err(_("Video device parameter error"), e)

    def _validate_page_watchdog(self):
        conn = self.conn.get_backend()
        model = uiutil.get_list_selection(self.widget("watchdog-model"))
        action = uiutil.get_list_selection(self.widget("watchdog-action"))

        try:
            self._dev = VirtualWatchdog(conn)
            self._dev.model = model
            self._dev.action = action
        except Exception, e:
            return self.err.val_err(_("Watchdog parameter error"), e)

    def _validate_page_filesystem(self):
        if self._fsdetails.validate_page_filesystem() is False:
            return False
        self._dev = self._fsdetails.get_dev()

    def _validate_page_smartcard(self):
        conn = self.conn.get_backend()
        mode = uiutil.get_list_selection(self.widget("smartcard-mode"))

        try:
            self._dev = VirtualSmartCardDevice(conn)
            self._dev.mode = mode
        except Exception, e:
            return self.err.val_err(_("Smartcard device parameter error"), e)

    def _validate_page_usbredir(self):
        conn = self.conn.get_backend()
        stype = uiutil.get_list_selection(self.widget("usbredir-list"))
        host = None
        service = None
        if self.widget("usbredir-host").is_visible():
            host = self.widget("usbredir-host").get_text()
            service = uiutil.spin_get_helper(self.widget("usbredir-service"))

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

    def _validate_page_tpm(self):
        conn = self.conn.get_backend()
        typ = uiutil.get_list_selection(self.widget("tpm-type"))

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

    def _validate_page_panic(self):
        conn = self.conn.get_backend()

        iobase = self.widget("panic-iobase").get_text()

        value_mappings = {
            "iobase" : iobase,
        }

        try:
            self._dev = VirtualPanicDevice(conn)
            if not iobase:
                iobase = self._dev.IOBASE_DEFAULT
            for param_name, val in value_mappings.items():
                setattr(self._dev, param_name, val)
        except Exception, e:
            return self.err.val_err(_("Panic device parameter error"), e)

    def _validate_page_controller(self):
        conn = self.conn.get_backend()
        controller_type = uiutil.get_list_selection(
            self.widget("controller-type"))
        model = uiutil.get_list_selection(self.widget("controller-model"))

        self._dev = VirtualController(conn)
        self._selected_model = model

        controllers = self.vm.get_controller_devices()
        controller_num = [x for x in controllers if
                (x.type == controller_type)]
        if len(controller_num) > 0:
            index_new = max([x.index for x in controller_num]) + 1
            self._dev.index = index_new

        self._dev.type = controller_type

        if model != "none":
            if model == "default":
                model = None
            self._dev.model = model

    def _validate_page_rng(self):
        rtype = uiutil.get_list_selection(self.widget("rng-type"))
        backend_type = uiutil.get_list_selection(
            self.widget("rng-backend-type"))
        backend_mode = uiutil.get_list_selection(
            self.widget("rng-backend-mode"))

        connect_host = self.widget("rng-connect-host").get_text()
        connect_service = uiutil.spin_get_helper(
            self.widget("rng-connect-service"))
        bind_host = self.widget("rng-bind-host").get_text()
        bind_service = uiutil.spin_get_helper(
            self.widget("rng-bind-service"))


        device = self.widget("rng-device").get_text()
        if rtype == virtinst.VirtualRNGDevice.TYPE_RANDOM:
            if not device:
                return self.err.val_err(_("RNG selection error."),
                                    _("A device must be specified."))
            connect_host = None
            connect_service = None
            bind_host = None
            bind_service = None
        else:
            device = None

        if rtype == virtinst.VirtualRNGDevice.TYPE_EGD:
            if (backend_type == virtinst.VirtualRNGDevice.BACKEND_TYPE_UDP):
                if not connect_host or not bind_host:
                    return self.err.val_err(_("RNG selection error."),
                             _("Please specify both bind and connect host"))
                if not connect_service or not bind_service:
                    return self.err.val_err(_("RNG selection error."),
                          _("Please specify both bind and connect service"))
            else:
                if (backend_mode ==
                    virtinst.VirtualRNGDevice.BACKEND_MODE_CONNECT):
                    bind_host = None
                    bind_service = None
                else:
                    connect_host = None
                    connect_service = None

                if not connect_host and not bind_host:
                    return self.err.val_err(_("RNG selection error."),
                                        _("The EGD host must be specified."))
                if not connect_service and not bind_service:
                    return self.err.val_err(_("RNG selection error."),
                                     _("The EGD service must be specified."))

        value_mappings = {
            "backend_type" : backend_type,
            "backend_source_mode" : backend_mode,
            "connect_host" : connect_host,
            "connect_service" : connect_service,
            "bind_host" : bind_host,
            "bind_service" : bind_service,
            "device" : device,
        }

        try:
            self._dev = virtinst.VirtualRNGDevice(self.conn.get_backend())
            self._dev.type = rtype
            for param_name, val in value_mappings.items():
                if self._dev.supports_property(param_name):
                    setattr(self._dev, param_name, val)
        except Exception, e:
            return self.err.val_err(_("RNG device parameter error"), e)


    ####################
    # Unsorted helpers #
    ####################

    def _browse_storage_cb(self, ignore, widget):
        self._browse_file(widget)

    def _browse_file(self, textent, isdir=False):
        def set_storage_cb(src, path):
            if path:
                textent.set_text(path)

        reason = (isdir and
                  self.config.CONFIG_DIR_FS or
                  self.config.CONFIG_DIR_IMAGE)
        if self._storagebrowser is None:
            self._storagebrowser = vmmStorageBrowser(self.conn)

        self._storagebrowser.set_stable_defaults(self.vm.stable_defaults())
        self._storagebrowser.set_finish_cb(set_storage_cb)
        self._storagebrowser.set_browse_reason(reason)

        self._storagebrowser.show(self.topwin)

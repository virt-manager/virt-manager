#
# Copyright (C) 2006-2007, 2012-2014 Red Hat, Inc.
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

        self.storage_browser = None

        self._dev = None
        self._remove_usb_controller = None
        self._selected_model = None

        self.gfxdetails = vmmGraphicsDetails(
            self.vm, self.builder, self.topwin)
        self.widget("graphics-align").add(self.gfxdetails.top_box)

        self.fsDetails = vmmFSDetails(self.vm, self.builder, self.topwin)
        self.widget("fs-box").add(self.fsDetails.top_box)

        self.netlist = vmmNetworkList(self.conn, self.builder, self.topwin)
        self.widget("network-source-label-align").add(self.netlist.top_label)
        self.widget("network-source-ui-align").add(self.netlist.top_box)
        self.widget("network-vport-align").add(self.netlist.top_vport)

        self.addstorage = vmmAddStorage(self.conn, self.builder, self.topwin)
        self.widget("config-storage-align").add(self.addstorage.top_box)
        self.addstorage.connect("browse-clicked", self._browse_storage_cb)
        self.addstorage.connect("storage-toggled", self.toggle_storage_select)

        self.builder.connect_signals({
            "on_create_cancel_clicked" : self.close,
            "on_vmm_create_delete_event" : self.close,
            "on_create_finish_clicked" : self.finish,
            "on_hw_list_changed": self.hw_selected,

            "on_config_storage_bustype_changed": self.populate_disk_device,
            "on_config_storage_devtype_changed": self.change_storage_devtype,

            "on_mac_address_clicked" : self.change_macaddr_use,

            "on_char_device_type_changed": self.change_char_device_type,
            "on_char_target_name_changed": self.change_char_target_name,
            "on_char_auto_socket_toggled": self.change_char_auto_socket,

            "on_tpm_device_type_changed": self.change_tpm_device_type,

            "on_usbredir_type_changed": self.change_usbredir_type,

            "on_rng_type_changed": self.change_rng,
            "on_rng_backend_mode_changed": self.change_rng,
            "on_rng_backend_type_changed": self.change_rng,

            "on_controller_type_changed": self.populate_controller_model,
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

        self.gfxdetails.cleanup()
        self.gfxdetails = None
        self.fsDetails.cleanup()
        self.fsDetails = None
        self.netlist.cleanup()
        self.netlist = None
        self.addstorage.cleanup()
        self.addstorage = None

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

        # Network model list
        netmodel_list = self.widget("net-model")
        self.build_network_model_combo(self.vm, netmodel_list)

        # Disk bus type
        widget = self.widget("config-storage-bustype")
        # [bus, label]
        model = Gtk.ListStore(str, str)
        widget.set_model(model)
        uiutil.set_combo_text_column(widget, 1)

        # Disk device type
        target_list = self.widget("config-storage-devtype")
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

        # Disk cache mode
        cache_list = self.widget("config-storage-cache")
        self.build_disk_cache_combo(self.vm, cache_list)

        # Disk format mode
        self.populate_disk_format_combo_wrapper(True)

        # Input device type
        input_list = self.widget("input-type")
        input_model = Gtk.ListStore(str, str, str)
        input_list.set_model(input_model)
        uiutil.set_combo_text_column(input_list, 0)

        # Sound model list
        sound_list = self.widget("sound-model")
        self.build_sound_combo(self.vm, sound_list)

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
        self.build_video_combo(self.vm, video_dev)

        # Character dev mode
        char_mode = self.widget("char-mode")
        # Mode name, desc
        char_mode_model = Gtk.ListStore(str, str)
        char_mode.set_model(char_mode_model)
        uiutil.set_combo_text_column(char_mode, 1)
        char_mode_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        for t in VirtualSerialDevice.MODES:
            desc = VirtualSerialDevice.pretty_mode(t)
            char_mode_model.append([t, desc + " (%s)" % t])

        # Char target type
        lst = self.widget("char-target-type")
        model = Gtk.ListStore(str, str)
        lst.set_model(model)
        uiutil.set_combo_text_column(lst, 1)
        if self.conn.is_qemu():
            model.append(["virtio", "virtio"])
        else:
            model.append([None, "default"])

        # Char target name
        lst = self.widget("char-target-name")
        model = Gtk.ListStore(str)
        lst.set_model(model)
        uiutil.set_combo_text_column(lst, 0)
        for n in VirtualChannelDevice.CHANNEL_NAMES:
            model.append([n])

        # Char device type
        lst = self.widget("char-device-type")
        model = Gtk.ListStore(str, str)
        lst.set_model(model)
        uiutil.set_combo_text_column(lst, 1)

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
        self.build_rng_type_combo(combo)
        combo = self.widget("rng-backend-type")
        self.build_rng_backend_type_combo(combo)
        combo = self.widget("rng-backend-mode")
        self.build_rng_backend_mode_combo(combo)

        # Panic widgets
        combo = self.widget("panic-type")
        self.build_panic_address_type(combo)

        # Controller widgets
        combo = self.widget("controller-type")
        target_model = Gtk.ListStore(str, str)
        combo.set_model(target_model)
        uiutil.set_combo_text_column(combo, 1)
        combo = self.widget("controller-model")
        target_model = Gtk.ListStore(str, str)
        combo.set_model(target_model)
        uiutil.set_combo_text_column(combo, 1)

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
        add_hw_option("Controller", "device_pci", PAGE_CONTROLLER, True, None)
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
        add_hw_option("Video", "video-display", PAGE_VIDEO, True,
                      _("Libvirt version does not support video devices."))
        add_hw_option("Watchdog", "device_pci", PAGE_WATCHDOG,
                      self.vm.is_hvm(),
                      _("Not supported for this guest type."))
        add_hw_option("Filesystem", "folder", PAGE_FILESYSTEM,
                      self.conn.check_support(
                        self.conn.SUPPORT_CONN_FILESYSTEM) and
                      not self.vm.stable_defaults(),
                      _("Not supported for this hypervisor/libvirt "
                        "combination."))
        add_hw_option("Smartcard", "device_serial", PAGE_SMARTCARD,
                      True, None)
        add_hw_option("USB Redirection", "device_usb", PAGE_USBREDIR,
                      True, None)
        add_hw_option("TPM", "device_cpu", PAGE_TPM,
                      True, None)
        add_hw_option("RNG", "system-run", PAGE_RNG, True, None)
        add_hw_option("Panic Notifier", "system-run", PAGE_PANIC,
            self.conn.check_support(self.conn.SUPPORT_CONN_PANIC_DEVICE),
            _("Not supported for this hypervisor/libvirt combination."))

    def reset_state(self):
        # Storage init
        self.populate_disk_format_combo_wrapper(True)
        self.populate_disk_bus()
        self.addstorage.reset_state()

        # Network init
        newmac = virtinst.VirtualNetworkInterface.generate_mac(
                self.conn.get_backend())
        self.widget("mac-address").set_active(bool(newmac))
        self.widget("create-mac-address").set_text(newmac)
        self.change_macaddr_use()

        self.netlist.reset_state()

        netmodel = self.widget("net-model")
        self.populate_network_model_combo(self.vm, netmodel)
        netmodel.set_active(0)

        # Input device init
        input_box = self.widget("input-type")
        self.populate_input_model(input_box.get_model())
        input_box.set_active(0)

        # Graphics init
        self.gfxdetails.reset_state()

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
        self.fsDetails.reset_state()

        # Video params
        self.populate_video_combo(self.vm, self.widget("video-model"))

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
        self.populate_controller_type()

        self.set_hw_selection(0)


    #####################
    # Shared UI helpers #
    #####################

    @staticmethod
    def populate_video_combo(vm, combo, no_default=None):
        model = combo.get_model()
        has_spice = bool([g for g in vm.get_graphics_devices()
                          if g.type == g.TYPE_SPICE])
        has_qxl = bool([v for v in vm.get_video_devices()
                        if v.model == "qxl"])

        model.clear()
        tmpdev = virtinst.VirtualVideoDevice(vm.conn.get_backend())
        for m in tmpdev.MODELS:
            if vm.stable_defaults():
                if m == "qxl" and not has_spice and not has_qxl:
                    # Only list QXL video option when VM has SPICE video
                    continue

            if m == tmpdev.MODEL_DEFAULT and no_default:
                continue
            model.append([m, tmpdev.pretty_model(m)])

        if len(model) > 0:
            combo.set_active(0)

    @staticmethod
    def build_video_combo(vm, combo, no_default=None):
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.set_combo_text_column(combo, 1)
        combo.get_model().set_sort_column_id(1, Gtk.SortType.ASCENDING)

        vmmAddHardware.populate_video_combo(vm, combo, no_default)

    @staticmethod
    def build_sound_combo(vm, combo, no_default=False):
        model = Gtk.ListStore(str)
        combo.set_model(model)
        uiutil.set_combo_text_column(combo, 0)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        stable_defaults = vm.stable_defaults()
        stable_soundmodels = ["ich6", "ich9", "ac97"]

        for m in virtinst.VirtualAudio.MODELS:
            if m == virtinst.VirtualAudio.MODEL_DEFAULT and no_default:
                continue

            if (stable_defaults and m not in stable_soundmodels):
                continue

            model.append([m])
        if len(model) > 0:
            combo.set_active(0)

    @staticmethod
    def build_watchdogmodel_combo(vm, combo, no_default=False):
        ignore = vm
        model = Gtk.ListStore(str)
        combo.set_model(model)
        uiutil.set_combo_text_column(combo, 0)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        for m in virtinst.VirtualWatchdog.MODELS:
            if m == virtinst.VirtualAudio.MODEL_DEFAULT and no_default:
                continue
            model.append([m])
        if len(model) > 0:
            combo.set_active(0)

    @staticmethod
    def build_watchdogaction_combo(vm, combo, no_default=False):
        ignore = vm
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.set_combo_text_column(combo, 1)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        for m in virtinst.VirtualWatchdog.ACTIONS:
            if m == virtinst.VirtualWatchdog.ACTION_DEFAULT and no_default:
                continue
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
            mod_list = ["rtl8139", "ne2k_pci", "pcnet", "e1000"]
            if vm.get_hv_type() in ["kvm", "qemu", "test"]:
                mod_list.append("virtio")
            if (vm.get_hv_type() == "kvm" and
                  vm.get_machtype() == "pseries"):
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
        uiutil.set_combo_text_column(combo, 1)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        vmmAddHardware.populate_network_model_combo(vm, combo)
        combo.set_active(0)

    @staticmethod
    def populate_smartcard_mode_combo(vm, combo):
        ignore = vm
        model = combo.get_model()
        model.clear()

        # [xml value, label]
        model.append(["passthrough", "Passthrough"])
        model.append(["host", "Host"])

    @staticmethod
    def build_smartcard_mode_combo(vm, combo):
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.set_combo_text_column(combo, 1)
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
        model.append(["spicevmc", "Spice channel", False])
        model.append(["tcp", "TCP", True])

    @staticmethod
    def build_redir_type_combo(vm, combo):
        model = Gtk.ListStore(str, str, bool)
        combo.set_model(model)
        uiutil.set_combo_text_column(combo, 1)

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
        uiutil.set_combo_text_column(combo, 1)
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
        uiutil.set_combo_text_column(combo, 1)

        combo.set_active(-1)
        for m in virtinst.VirtualDisk.cache_types:
            model.append([m, m])

        _iter = model.insert(0, [None, "default"])
        combo.set_active_iter(_iter)

    @staticmethod
    def build_disk_io_combo(vm, combo, no_default=False):
        ignore = vm
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.set_combo_text_column(combo, 1)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        combo.set_active(-1)
        for m in virtinst.VirtualDisk.io_modes:
            model.append([m, m])

        if not no_default:
            model.append([None, "default"])
        combo.set_active(0)

    @staticmethod
    def build_disk_bus_combo(vm, combo, no_default=False):
        ignore = vm
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.set_combo_text_column(combo, 1)
        model.set_sort_column_id(1, Gtk.SortType.ASCENDING)

        if not no_default:
            model.append([None, "default"])
        combo.set_active(-1)

    @staticmethod
    def populate_disk_format_combo(vm, combo, create):
        model = Gtk.ListStore(str)
        combo.set_model(model)
        uiutil.set_combo_text_column(combo, 0)

        formats = ["raw", "qcow2", "qed"]
        no_create_formats = []
        if not vm.stable_defaults():
            formats.append("vmdk")
            no_create_formats.append("vdi")

        for m in formats:
            model.append([m])
        if not create:
            for m in no_create_formats:
                model.append([m])

        if create:
            fmt = vm.conn.get_default_storage_format()
            combo.set_active(0)
            for row in model:
                if row[0] == fmt:
                    combo.set_active_iter(row.iter)
                    break

    @staticmethod
    def populate_controller_model_combo(combo, controller_type, widget_name, add_default=False):
        model = combo.get_model()
        model.clear()

        if controller_type == virtinst.VirtualController.TYPE_USB:
            model.append(["default", "Default"])
            model.append(["ich9-ehci1", "USB 2"])
            model.append(["nec-xhci", "USB 3"])
            if widget_name is not None:
                widget_name.set_sensitive(False)
        elif controller_type == virtinst.VirtualController.TYPE_SCSI:
            model.append(["default", "Default"])
            model.append(["virtio-scsi", "VirtIO SCSI"])
        else:
            if add_default:
                model.append([None, "Default"])
                uiutil.set_grid_row_visible(combo, False)
            if widget_name is not None:
                widget_name.set_sensitive(True)


    #########################
    # UI population methods #
    #########################

    def populate_disk_bus(self):
        widget = self.widget("config-storage-bustype")
        model = widget.get_model()
        model.clear()

        if self.vm.is_hvm():
            model.append(["ide", "IDE"])
            model.append(["fdc", "Floppy"])

            if not self.vm.stable_defaults():
                model.append(["scsi", "SCSI"])
                model.append(["usb", "USB"])

        if self.vm.get_hv_type() in ["qemu", "kvm", "test"]:
            model.append(["sata", "SATA"])
            model.append(["sd", "SD"])
            model.append(["virtio", "VirtIO"])
            model.append(["virtio-scsi", "VirtIO SCSI"])

        if self.conn.is_xen() or self.conn.is_test_conn():
            model.append(["xen", "Xen"])

        if len(model) > 0:
            widget.set_active(0)

    def populate_disk_device(self, src):
        ignore = src

        bus = self.get_config_disk_bus()
        devlist = self.widget("config-storage-devtype")
        model = devlist.get_model()
        model.clear()

        disk_buses = ["ide", "sata", "scsi", "sd",
                      "usb", "virtio", "virtio-scsi", "xen"]
        floppy_buses = ["fdc"]
        cdrom_buses = ["ide", "scsi"]
        lun_buses = ["virtio-scsi"]

        if bus in disk_buses:
            model.append([virtinst.VirtualDisk.DEVICE_DISK,
                          "drive-harddisk", _("Disk device")])
        if bus in floppy_buses:
            model.append([virtinst.VirtualDisk.DEVICE_FLOPPY,
                          "media-floppy", _("Floppy device")])
        if bus in cdrom_buses:
            model.append([virtinst.VirtualDisk.DEVICE_CDROM,
                          "media-cdrom", _("CDROM device")])
        if bus in lun_buses:
            model.append([virtinst.VirtualDisk.DEVICE_LUN,
                          "drive-harddisk", _("LUN device")])

        if len(model) > 0:
            devlist.set_active(0)

    def populate_input_model(self, model):
        model.clear()
        model.append([_("EvTouch USB Graphics Tablet"), "tablet", "usb"])
        model.append([_("Generic USB Mouse"), "mouse", "usb"])

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
                    prettyname += " (%s)" % subdev.pretty_name()

            model.append([prettyname, dev.name, devtype, dev])

        if len(model) == 0:
            model.append([_("No Devices Available"), None, None, None])
        uiutil.set_list_selection(devlist, 0)

    def populate_disk_format_combo_wrapper(self, create):
        format_list = self.widget("config-storage-format")
        self.populate_disk_format_combo(self.vm, format_list, create)
        if not create:
            format_list.get_child().set_text("")

    def populate_controller_type(self):
        widget = self.widget("controller-type")
        model = widget.get_model()
        model.clear()

        for t in VirtualController.TYPES:
            if t == VirtualController.TYPE_PCI:
                continue
            model.append([t, VirtualController.pretty_type(t)])

        if len(model) > 0:
            widget.set_active(0)

    def populate_controller_model(self, src):
        ignore = src

        def show_tooltip(model_tooltip, show):
            vmname = self.vm.get_name()
            tooltip = (_("%s already has a USB controller attached.\n"
            "Adding more than one USB controller is not supported.\n"
            "You can change the USB controller type in the VM details screen.")
            % vmname)
            model_tooltip.set_visible(show)
            model_tooltip.set_tooltip_text(tooltip)

        controller_type = self.get_config_controller_type()
        modellist = self.widget("controller-model")
        modellist.set_sensitive(True)
        model_tooltip = self.widget("controller-tooltip")
        show_tooltip(model_tooltip, False)

        controllers = self.vm.get_controller_devices()
        if controller_type == VirtualController.TYPE_USB:
            usb_controllers = [x for x in controllers if
                    (x.type == VirtualController.TYPE_USB)]
            if (len(usb_controllers) == 0):
                self.widget("create-finish").set_sensitive(True)
            elif (len(usb_controllers) == 1 and usb_controllers[0].model == "none"):
                self._remove_usb_controller = usb_controllers[0]
                self.widget("create-finish").set_sensitive(True)
            else:
                show_tooltip(model_tooltip, True)
                self.widget("create-finish").set_sensitive(False)
        else:
            self.widget("create-finish").set_sensitive(True)
        uiutil.set_grid_row_visible(modellist, True)
        self.populate_controller_model_combo(modellist, controller_type, None, True)

        if len(modellist.get_model()) > 0:
            modellist.set_active(0)


    ########################
    # get_config_* methods #
    ########################

    def build_combo_with_values(self, combo, values, default=None):
        dev_model = Gtk.ListStore(str, str)
        combo.set_model(dev_model)
        uiutil.set_combo_text_column(combo, 1)
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

    def build_panic_address_type(self, combo):
        types = []
        for t in virtinst.VirtualPanicDevice.TYPES:
            types.append([t, virtinst.VirtualPanicDevice.get_pretty_type(t)])

        self.build_combo_with_values(combo, types,
                virtinst.VirtualPanicDevice.ADDRESS_TYPE_ISA)

    def get_config_hardware_type(self):
        row = self.get_hw_selection()
        if not row:
            return None
        return row[2]

    # Disk getters
    def get_config_disk_bus(self):
        return uiutil.get_list_selection(
            self.widget("config-storage-bustype"), 0)

    def get_config_disk_device(self):
        return uiutil.get_list_selection(
            self.widget("config-storage-devtype"), 0)

    def get_config_disk_cache(self):
        return uiutil.get_list_selection(
            self.widget("config-storage-cache"), 0)

    def get_config_disk_format(self):
        fmt = self.widget("config-storage-format")
        return fmt.get_child().get_text()

    # Input getters
    def get_config_input(self):
        row = uiutil.get_list_selection(self.widget("input-type"), None)
        return row[1], row[2]

    # Network getters
    def get_config_net_model(self):
        return uiutil.get_list_selection(self.widget("net-model"), 0)

    def get_config_macaddr(self):
        macaddr = None
        if self.widget("mac-address").get_active():
            macaddr = self.widget("create-mac-address").get_text()
        return macaddr

    # Sound getters
    def get_config_sound_model(self):
        return uiutil.get_list_selection(self.widget("sound-model"), 0)

    # Host device getters
    def get_config_host_device_type_info(self):
        pci_info = ["PCI Device", "pci", None, "net", "80203"]
        usb_info = ["USB Device", "usb_device", None, None, None]
        row = self.get_hw_selection()

        if row and row[5] == "pci":
            return pci_info
        return usb_info

    def get_config_host_device_info(self):
        return uiutil.get_list_selection(self.widget("host-device"), None)

    # Video Getters
    def get_config_video_model(self):
        return uiutil.get_list_selection(self.widget("video-model"), 0)

    # Watchdog getters
    def get_config_watchdog_model(self):
        return uiutil.get_list_selection(self.widget("watchdog-model"), 0)
    def get_config_watchdog_action(self):
        return uiutil.get_list_selection(self.widget("watchdog-action"), 0)

    # Smartcard getters
    def get_config_smartcard_mode(self):
        return uiutil.get_list_selection(self.widget("smartcard-mode"), 0)

    # USB redir getters
    def get_config_usbredir_host(self):
        host = self.widget("usbredir-host")
        service = self.widget("usbredir-service")
        if not host.get_visible():
            return None, None

        return host.get_text(), int(service.get_value())

    def get_config_usbredir_type(self):
        return uiutil.get_list_selection(self.widget("usbredir-list"), 0)

    # TPM getters
    def get_config_tpm_type(self):
        return uiutil.get_list_selection(self.widget("tpm-type"), 0)

    # RNG getters
    def get_config_rng_type(self):
        return uiutil.get_list_selection(self.widget("rng-type"), 0)

    def get_config_rng_device(self):
        if self.get_config_rng_type() == virtinst.VirtualRNGDevice.TYPE_RANDOM:
            return self.widget("rng-device").get_text()

        return None

    def get_config_rng_host(self, is_connect=False):
        connect_mode = virtinst.VirtualRNGDevice.BACKEND_MODE_CONNECT in \
                       self.get_config_rng_backend_mode()
        is_udp = self.get_config_rng_backend_type() == \
                 virtinst.VirtualRNGDevice.BACKEND_TYPE_UDP

        if connect_mode == is_connect or is_udp:
            widget_name = "rng-connect-host" if is_connect else "rng-bind-host"
            return self.widget(widget_name).get_text()

        return None

    def get_config_rng_service(self, is_connect=False):
        connect_mode = virtinst.VirtualRNGDevice.BACKEND_MODE_CONNECT in \
                       self.get_config_rng_backend_mode()
        is_udp = self.get_config_rng_backend_type() == \
                 virtinst.VirtualRNGDevice.BACKEND_TYPE_UDP

        if connect_mode == is_connect or is_udp:
            if is_connect:
                widget_name = "rng-connect-service"
            else:
                widget_name = "rng-bind-service"
            return self.widget(widget_name).get_text()

        return None

    def get_config_rng_backend_type(self):
        return uiutil.get_list_selection(self.widget("rng-backend-type"), 0)

    def get_config_rng_backend_mode(self):
        return uiutil.get_list_selection(self.widget("rng-backend-mode"), 0)

    # CONTROLLER getters
    def get_config_controller_type(self):
        return uiutil.get_list_selection(self.widget("controller-type"), 0)

    def get_config_controller_model(self):
        return uiutil.get_list_selection(self.widget("controller-model"), 0)

    ################
    # UI listeners #
    ################

    def set_hw_selection(self, page):
        uiutil.set_list_selection(self.widget("hw-list"), page)

    def get_hw_selection(self):
        return uiutil.get_list_selection(self.widget("hw-list"), None)

    def update_char_device_type_model(self):
        stable_blacklist = ["pipe", "udp"]

        # Char device type
        char_devtype = self.widget("char-device-type")
        char_devtype_model = char_devtype.get_model()
        char_devtype_model.clear()
        char_class = self.get_char_type()

        # Type name, desc
        for t in char_class.TYPES:
            if (t in stable_blacklist and
                self.vm.stable_defaults()):
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

        self.widget("create-finish").set_sensitive(sens)

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


    # Storage listeners
    def toggle_storage_select(self, ignore, src):
        act = src.get_active()
        self.populate_disk_format_combo_wrapper(not act)

    def change_storage_devtype(self, ignore):
        devtype = self.get_config_disk_device()
        allow_create = devtype not in ["cdrom", "floppy"]
        self.addstorage.widget("config-storage-create-box").set_sensitive(
            allow_create)
        if not allow_create:
            self.addstorage.widget("config-storage-select").set_active(True)

    # Network listeners
    def change_macaddr_use(self, ignore=None):
        if self.widget("mac-address").get_active():
            self.widget("create-mac-address").set_sensitive(True)
        else:
            self.widget("create-mac-address").set_sensitive(False)

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
        devtype = uiutil.get_list_selection(src, 0)
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

    def change_char_auto_socket(self, src):
        if not src.get_visible():
            return

        doshow = not src.get_active()
        uiutil.set_grid_row_visible(self.widget("char-path-label"), doshow)
        uiutil.set_grid_row_visible(self.widget("char-mode-label"), doshow)

    def change_char_target_name(self, src):
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
        uiutil.set_row_selection(self.widget("char-device-type"), settype)

    def change_char_device_type(self, src):
        devtype = uiutil.get_list_selection(src, 0)
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

        char_class = self.get_char_type()
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

    def change_usbredir_type(self, src):
        showhost = uiutil.get_list_selection(src, 2)
        if showhost is None:
            return
        uiutil.set_grid_row_visible(self.widget("usbredir-host-box"),
                                       showhost)

    def change_rng(self, ignore1):
        model = self.get_config_rng_type()
        if model is None:
            return

        is_egd = model == virtinst.VirtualRNGDevice.TYPE_EGD
        uiutil.set_grid_row_visible(self.widget("rng-device"), not is_egd)
        uiutil.set_grid_row_visible(self.widget("rng-backend-type"), is_egd)

        backend_type = self.get_config_rng_backend_type()
        backend_mode = self.get_config_rng_backend_mode()
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

    @staticmethod
    def change_config_helper(define_func, define_args, vm, err,
                              devobj=None,
                              hotplug_args=None):
        hotplug_args = hotplug_args or {}

        # Persistent config change
        try:
            if devobj:
                define_func(devobj, False, **define_args)
            else:
                define_func(**define_args)
            vm.redefine_cached()
        except Exception, e:
            err.show_err((_("Error changing VM configuration: %s") %
                              str(e)))
            # If we fail, make sure we flush the cache
            vm.refresh_xml()
            return False

        # Hotplug change
        hotplug_err = None
        if vm.is_active():
            try:
                if devobj:
                    hotplug_args["device"] = define_func(
                        devobj, True, **define_args)
                if hotplug_args:
                    vm.hotplug(**hotplug_args)
            except Exception, e:
                logging.debug("Hotplug failed: %s", str(e))
                hotplug_err = ((str(e), "".join(traceback.format_exc())))

        if (hotplug_err or (vm.is_active() and not hotplug_args)):
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

    def setup_device(self, asyncjob):
        logging.debug("Running setup for device=%s", self._dev)
        self._dev.setup(meter=asyncjob.get_meter())
        logging.debug("Setup complete")

    def add_device(self):
        self._dev.get_xml_config()
        logging.debug("Adding device:\n" + self._dev.get_xml_config())

        if self._remove_usb_controller:
            kwargs = {}
            kwargs["model"] = self._selected_model

            self.change_config_helper(self.vm.define_controller,
                    kwargs, self.vm, self.err, self._remove_usb_controller)

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

    def _validate(self, page_num):
        if page_num == PAGE_ERROR:
            self._dev = None
            return True
        elif page_num == PAGE_DISK:
            return self.validate_page_storage()
        elif page_num == PAGE_CONTROLLER:
            return self.validate_page_controller()
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
        elif page_num == PAGE_PANIC:
            return self.validate_page_panic()

    def validate(self, page_num):
        ret = self._validate(page_num)
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

    def validate_page_storage(self):
        bus = self.get_config_disk_bus()
        device = self.get_config_disk_device()
        cache = self.get_config_disk_cache()
        fmt = self.get_config_disk_format()

        controller_model = None
        if bus == "virtio-scsi":
            bus = "scsi"
            controller_model = "virtio-scsi"

        collidelist = [d.path for d in self.vm.get_disk_devices()]
        disk = self.addstorage.validate_storage(self.vm.get_name(),
            collidelist=collidelist, device=device, fmt=fmt)
        if disk in [True, False]:
            return disk

        try:
            used = []
            disk.bus = bus
            if cache:
                disk.driver_cache = cache

            # Generate target
            disks = []
            if not self.is_customize_dialog:
                disks = (self.vm.get_disk_devices() +
                         self.vm.get_disk_devices(inactive=True))
                for d in disks:
                    if d.target not in used:
                        used.append(d.target)

            prefer_ctrl = self._set_disk_controller(
                disk, controller_model, disks)

            if not self.is_customize_dialog:
                disk.generate_target(used, prefer_ctrl)

        except Exception, e:
            return self.err.val_err(_("Storage parameter error."), e)

        if self.addstorage.validate_disk_object(disk) is False:
            return False

        self._dev = disk
        return True


    def validate_page_network(self):
        nettype = self.netlist.get_network_selection()[0]
        mac = self.get_config_macaddr()
        model = self.get_config_net_model()

        if not nettype:
            return self.err.val_err(_("Network selection error."),
                                    _("A network source must be selected."))

        if not mac:
            return self.err.val_err(_("Invalid MAC address"),
                                    _("A MAC address must be entered."))

        ret = self.netlist.validate_network(mac, model)
        if ret is False:
            return False

        self._dev = ret

    def validate_page_input(self):
        inp_type, inp_bus = self.get_config_input()
        dev = virtinst.VirtualInputDevice(self.conn.get_backend())
        dev.type = inp_type
        dev.bus = inp_bus

        self._dev = dev

    def validate_page_graphics(self):
        try:
            (gtype, port,
             tlsport, addr, passwd, keymap) = self.gfxdetails.get_values()

            self._dev = virtinst.VirtualGraphics(self.conn.get_backend())
            self._dev.type = gtype
            self._dev.port = port
            self._dev.passwd = passwd
            self._dev.listen = addr
            self._dev.tlsPort = tlsport
            if keymap:
                self._dev.keymap = keymap
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
        row = self.get_config_host_device_info()
        is_dup = False

        if row is None:
            return self.err.val_err(_("Physical Device Required"),
                                    _("A device must be selected."))

        devtype = row[2]
        nodedev = row[3]
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
            dev.set_from_nodedev(nodedev, use_full_usb=is_dup)
            self._dev = dev
        except Exception, e:
            return self.err.val_err(_("Host device parameter error"), e)

    def validate_page_char(self):
        charclass = self.get_char_type()
        modebox = self.widget("char-mode")
        devbox = self.widget("char-device-type")
        typebox = self.widget("char-target-type")
        devtype = uiutil.get_list_selection(devbox, 0)
        conn = self.conn.get_backend()

        devclass = charclass(conn)
        devclass.type = devtype

        source_path = self.widget("char-path").get_text()
        source_channel = self.widget("char-channel").get_text()
        source_mode = uiutil.get_list_selection(modebox, 0)
        source_host = self.widget("char-host").get_text()
        bind_host = self.widget("char-bind-host").get_text()
        source_port = self.widget("char-port").get_value()
        bind_port = self.widget("char-bind-port").get_value()
        target_name = self.widget("char-target-name").get_child().get_text()
        target_type = uiutil.get_list_selection(typebox, 0)

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
        if self.fsDetails.validate_page_filesystem() is False:
            return False
        self._dev = self.fsDetails.get_dev()

    def validate_page_smartcard(self):
        conn = self.conn.get_backend()
        mode = self.get_config_smartcard_mode()

        try:
            self._dev = VirtualSmartCardDevice(conn)
            self._dev.mode = mode
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

    def validate_page_panic(self):
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

    def validate_page_controller(self):
        conn = self.conn.get_backend()
        controller_type = self.get_config_controller_type()
        model = self.get_config_controller_model()
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

    def validate_page_rng(self):
        conn = virtinst.VirtualRNGDevice.BACKEND_MODE_CONNECT in \
               self.get_config_rng_backend_mode()
        model = self.get_config_rng_type()
        is_udp = self.get_config_rng_backend_type() == \
                 virtinst.VirtualRNGDevice.BACKEND_TYPE_UDP

        if model == virtinst.VirtualRNGDevice.TYPE_RANDOM:
            if not self.get_config_rng_device():
                return self.err.val_err(_("RNG selection error."),
                                    _("A device must be specified."))
        elif model == virtinst.VirtualRNGDevice.TYPE_EGD:
            conn = self.get_config_rng_backend_mode() == \
                   virtinst.VirtualRNGDevice.BACKEND_MODE_CONNECT

            if is_udp:
                if not self.get_config_rng_host(is_connect=conn) or \
                   not self.get_config_rng_host(is_connect=not conn):
                    return self.err.val_err(_("RNG selection error."),
                             _("Please specify both bind and connect host"))
                if not int(self.get_config_rng_service(is_connect=conn)) or \
                   not int(self.get_config_rng_service(is_connect=not conn)):
                    return self.err.val_err(_("RNG selection error."),
                          _("Please specify both bind and connect service"))
            else:
                if not self.get_config_rng_host(is_connect=conn):
                    return self.err.val_err(_("RNG selection error."),
                                        _("The EGD host must be specified."))
                if not int(self.get_config_rng_service(is_connect=conn)):
                    return self.err.val_err(_("RNG selection error."),
                                     _("The EGD service must be specified."))
        else:
            return self.err.val_err(_("RNG selection error."),
                                    _("Invalid RNG type."))

        value_mappings = {
            "backend_type" : self.get_config_rng_backend_type(),
            "backend_source_mode" : self.get_config_rng_backend_mode(),
            "connect_host" : self.get_config_rng_host(is_connect=True),
            "connect_service" : self.get_config_rng_service(is_connect=True),
            "bind_host" : self.get_config_rng_host(),
            "bind_service" : self.get_config_rng_service(),
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

    def _browse_storage_cb(self, ignore, widget):
        self._browse_file(widget)

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

        self.storage_browser.stable_defaults = self.vm.stable_defaults()

        self.storage_browser.set_finish_cb(set_storage_cb)
        self.storage_browser.set_browse_reason(reason)

        self.storage_browser.show(self.topwin, conn)

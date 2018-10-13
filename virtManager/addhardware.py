# Copyright (C) 2006-2007, 2012-2015 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import traceback

from gi.repository import Gtk
from gi.repository import Gdk

from virtinst import (DeviceChannel, DeviceConsole,
        DeviceController, DeviceDisk, DeviceGraphics, DeviceHostdev,
        DeviceInput, DeviceInterface, DevicePanic, DeviceParallel,
        DeviceRedirdev, DeviceRng, DeviceSerial, DeviceSmartcard,
        DeviceSound, DeviceTpm, DeviceVideo, DeviceWatchdog)

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
 PAGE_PANIC) = range(0, 17)


def _build_combo(combo, values, default_value=None, sort=True):
    """
    Helper to build a combo with model schema [xml value, label]
    """
    model = Gtk.ListStore(object, str)
    combo.set_model(model)
    uiutil.init_combo_text_column(combo, 1)
    if sort:
        model.set_sort_column_id(1, Gtk.SortType.ASCENDING)

    for xmlval, label in values:
        model.append([xmlval, label])
    if default_value:
        uiutil.set_list_selection(combo, default_value)
    elif len(model):
        combo.set_active(0)


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
            "on_create_cancel_clicked": self.close,
            "on_vmm_create_delete_event": self.close,
            "on_create_finish_clicked": self._finish,
            "on_hw_list_changed": self._hw_selected,

            "on_storage_devtype_changed": self._change_storage_devtype,

            "on_mac_address_clicked": self._change_macaddr_use,

            "on_char_device_type_changed": self._change_char_device_type,
            "on_char_target_name_changed": self._change_char_target_name,
            "on_char_auto_socket_toggled": self._change_char_auto_socket,

            "on_tpm_device_type_changed": self._change_tpm_device_type,

            "on_usbredir_type_changed": self._change_usbredir_type,

            "on_controller_type_changed": self._change_controller_type,
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

        # Individual HW page UI
        self.build_disk_bus_combo(self.vm, self.widget("storage-bustype"))
        self._build_disk_device_combo()
        self.build_disk_cache_combo(self.vm, self.widget("storage-cache"))
        self.build_disk_io_combo(self.vm, self.widget("storage-io"))
        self.build_disk_discard_combo(self.vm, self.widget("storage-discard"))
        self.build_disk_detect_zeroes_combo(self.vm,
            self.widget("storage-detect-zeroes"))
        self.build_network_model_combo(self.vm, self.widget("net-model"))
        self._build_input_combo()
        self.build_sound_combo(self.vm, self.widget("sound-model"))
        self._build_hostdev_treeview()
        self.build_video_combo(self.vm, self.widget("video-model"))
        _build_combo(self.widget("char-device-type"), [])
        self._build_char_target_type_combo()
        self._build_char_target_name_combo()
        self.build_watchdogmodel_combo(self.vm, self.widget("watchdog-model"))
        self.build_watchdogaction_combo(self.vm, self.widget("watchdog-action"))
        self.build_smartcard_mode_combo(self.vm, self.widget("smartcard-mode"))
        self._build_redir_type_combo()
        self._build_tpm_type_combo()
        self._build_panic_model_combo()
        _build_combo(self.widget("controller-model"), [])
        self._build_controller_type_combo()


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
        add_hw_option(_("Filesystem"), "folder", PAGE_FILESYSTEM, True, None)
        add_hw_option(_("Smartcard"), "device_serial", PAGE_SMARTCARD,
                      True, None)
        add_hw_option(_("USB Redirection"), "device_usb", PAGE_USBREDIR,
                      True, None)
        add_hw_option(_("TPM"), "device_cpu", PAGE_TPM,
                      True, None)
        add_hw_option(_("RNG"), "system-run", PAGE_RNG, True, None)
        add_hw_option(_("Panic Notifier"), "system-run", PAGE_PANIC,
            bool(DevicePanic.get_models(self.vm.get_xmlobj().os)),
            _("Not supported for this hypervisor/libvirt/arch combination."))


    def _reset_state(self):
        # Hide all notebook pages, otherwise the wizard window is as large
        # as the largest page
        notebook = self.widget("create-pages")
        for page in range(notebook.get_n_pages()):
            widget = notebook.get_nth_page(page)
            widget.hide()
        self._set_hw_selection(0)


        # Storage params
        self.widget("storage-devtype").set_active(0)
        self.widget("storage-devtype").emit("changed")
        self.widget("storage-cache").set_active(0)
        self.widget("disk-advanced-expander").set_expanded(False)
        self.addstorage.reset_state()


        # Network init
        newmac = DeviceInterface.generate_mac(self.conn.get_backend())
        self.widget("mac-address").set_active(bool(newmac))
        self.widget("create-mac-address").set_text(newmac)
        self._change_macaddr_use()

        self._netlist.reset_state()

        netmodel = self.widget("net-model")
        self.populate_network_model_combo(self.vm, netmodel)
        netmodel.set_active(0)


        # Char parameters
        self.widget("char-path").set_text("")
        self.widget("char-channel").set_text("")
        self.widget("char-auto-socket").set_active(True)


        # RNG params
        default_rng = "/dev/random"
        if self.conn.check_support(self.conn.SUPPORT_CONN_RNG_URANDOM):
            default_rng = "/dev/urandom"
        self.widget("rng-device").set_text(default_rng)


        # Remaining devices
        self._fsdetails.reset_state()
        self.widget("tpm-device-path").set_text("/dev/tpm0")
        self._gfxdetails.reset_state()


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
        except Exception as e:
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
        except Exception as e:
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
    # UI init/reset helpers #
    #########################

    def _build_disk_device_combo(self):
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
        target_model.append([DeviceDisk.DEVICE_DISK,
                      "drive-harddisk", _("Disk device")])
        target_model.append([DeviceDisk.DEVICE_CDROM,
                      "media-optical", _("CDROM device")])
        target_model.append([DeviceDisk.DEVICE_FLOPPY,
                      "media-floppy", _("Floppy device")])
        if self.conn.is_qemu() or self.conn.is_test():
            target_model.append([DeviceDisk.DEVICE_LUN,
                          "drive-harddisk", _("LUN Passthrough")])
        target_list.set_active(0)

    @staticmethod
    def build_disk_cache_combo(_vm, combo):
        values = [[None, _("Hypervisor default")]]
        for m in DeviceDisk.CACHE_MODES:
            values.append([m, m])
        _build_combo(combo, values, sort=False)

    @staticmethod
    def build_disk_io_combo(_vm, combo):
        values = [[None, _("Hypervisor default")]]
        for m in DeviceDisk.IO_MODES:
            values.append([m, m])
        _build_combo(combo, values, sort=False)

    @staticmethod
    def build_disk_discard_combo(_vm, combo):
        values = [[None, _("Hypervisor default")]]
        for m in DeviceDisk.DISCARD_MODES:
            values.append([m, m])
        _build_combo(combo, values, sort=False)

    @staticmethod
    def build_disk_detect_zeroes_combo(_vm, combo):
        values = [[None, _("Hypervisor default")]]
        for m in DeviceDisk.DETECT_ZEROES_MODES:
            values.append([m, m])
        _build_combo(combo, values, sort=False)

    @staticmethod
    def build_disk_bus_combo(_vm, combo):
        _build_combo(combo, [])

    @staticmethod
    def populate_disk_bus_combo(vm, devtype, model):
        domcaps = vm.get_domain_capabilities()
        buses = DeviceDisk.get_recommended_buses(vm.xmlobj, domcaps, devtype)

        model.clear()
        for bus in buses:
            model.append([bus, DeviceDisk.pretty_disk_bus(bus)])


    @staticmethod
    def populate_network_model_combo(vm, combo):
        model = combo.get_model()
        model.clear()

        # [xml value, label]
        model.append([None, _("Hypervisor default")])
        for netmodel in DeviceInterface.get_models(vm.xmlobj):
            model.append([netmodel, netmodel])

        uiutil.set_list_selection(
                combo, DeviceInterface.default_model(vm.xmlobj))

    @staticmethod
    def build_network_model_combo(vm, combo):
        _build_combo(combo, [])
        vmmAddHardware.populate_network_model_combo(vm, combo)


    def _build_input_combo(self):
        devices = [
            (DeviceInput.TYPE_TABLET, DeviceInput.BUS_USB),
            (DeviceInput.TYPE_MOUSE, DeviceInput.BUS_USB),
            (DeviceInput.TYPE_KEYBOARD, DeviceInput.BUS_USB),
            (DeviceInput.TYPE_KEYBOARD, DeviceInput.BUS_VIRTIO),
            (DeviceInput.TYPE_TABLET, DeviceInput.BUS_VIRTIO),
        ]

        cvals = [((t, b), DeviceInput.pretty_name(t, b)) for t, b in devices]
        _build_combo(self.widget("input-type"), cvals)


    @staticmethod
    def build_sound_combo(vm, combo):
        values = []
        for m in DeviceSound.get_recommended_models(vm.xmlobj):
            values.append([m, DeviceSound.pretty_model(m)])

        default = DeviceSound.default_model(vm.xmlobj)
        _build_combo(combo, values, default_value=default)


    def _build_hostdev_treeview(self):
        host_dev = self.widget("host-device")
        # [ xmlobj, label]
        host_dev_model = Gtk.ListStore(object, str)
        host_dev.set_model(host_dev_model)
        host_col = Gtk.TreeViewColumn()
        text = Gtk.CellRendererText()
        host_col.pack_start(text, True)
        host_col.add_attribute(text, 'text', 1)
        host_dev_model.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        host_dev.append_column(host_col)

    def _populate_hostdev_model(self, devtype):
        devlist = self.widget("host-device")
        model = devlist.get_model()
        model.clear()

        devs = self.conn.filter_nodedevs(devtype)
        netdevs = self.conn.filter_nodedevs("net")
        for dev in devs:
            if devtype == "usb_device" and dev.xmlobj.is_linux_root_hub():
                continue
            if (devtype == "pci" and
                dev.xmlobj.capability_type == "pci-bridge"):
                continue
            prettyname = dev.xmlobj.pretty_name()

            if devtype == "pci":
                for subdev in netdevs:
                    if dev.xmlobj.name == subdev.xmlobj.parent:
                        prettyname += " (%s)" % subdev.xmlobj.pretty_name()

            model.append([dev.xmlobj, prettyname])

        if len(model) == 0:
            model.append([None, _("No Devices Available")])
        uiutil.set_list_selection_by_number(devlist, 0)


    @staticmethod
    def build_video_combo(vm, combo):
        values = []
        for m in DeviceVideo.get_recommended_models(vm.xmlobj):
            values.append([m, DeviceVideo.pretty_model(m)])
        if not values:
            values.append([None, _("Hypervisor default")])
        default = DeviceVideo.default_model(vm.xmlobj)
        _build_combo(combo, values, default_value=default)


    def _build_char_target_type_combo(self):
        values = []
        if self.conn.is_qemu():
            values.append(["virtio", "VirtIO"])
        else:
            values.append([None, _("Hypervisor default")])
        _build_combo(self.widget("char-target-type"), values)

    def _build_char_target_name_combo(self):
        values = []
        for n in DeviceChannel.CHANNEL_NAMES:
            values.append([n, n])
        _build_combo(self.widget("char-target-name"), values)

    def _populate_char_device_type_combo(self):
        char_class = self._get_char_class()
        model = self.widget("char-device-type").get_model()
        model.clear()

        for t in char_class.get_recommended_types(self.vm.xmlobj):
            model.append([t, char_class.pretty_type(t) + " (%s)" % t])
        uiutil.set_list_selection(self.widget("char-device-type"), "pty")


    @staticmethod
    def build_watchdogmodel_combo(_vm, combo):
        values = []
        for m in DeviceWatchdog.MODELS:
            values.append([m, m.upper()])
        _build_combo(combo, values, default_value=DeviceWatchdog.MODEL_I6300)

    @staticmethod
    def build_watchdogaction_combo(_vm, combo):
        values = []
        for m in DeviceWatchdog.ACTIONS:
            values.append([m, DeviceWatchdog.get_action_desc(m)])
        _build_combo(combo, values, default_value=DeviceWatchdog.ACTION_RESET)


    @staticmethod
    def build_smartcard_mode_combo(_vm, combo):
        values = [
            ["passthrough", _("Passthrough")],
            ["host", _("Host")],
        ]
        _build_combo(combo, values)


    def _build_redir_type_combo(self):
        values = [["spicevmc", _("Spice channel")]]
        _build_combo(self.widget("usbredir-list"), values)


    def _build_tpm_type_combo(self):
        values = []
        for t in DeviceTpm.TYPES:
            values.append([t, DeviceTpm.get_pretty_type(t)])
        _build_combo(self.widget("tpm-type"), values)
        values = []
        for t in DeviceTpm.MODELS:
            values.append([t, DeviceTpm.get_pretty_model(t)])
        _build_combo(self.widget("tpm-model"), values)
        values = []
        for t in DeviceTpm.VERSIONS:
            values.append([t, t])
        _build_combo(self.widget("tpm-version"), values)

    @staticmethod
    def _get_tpm_model_list(vm, tpmversion):
        mod_list = []
        if vm.is_hvm():
            mod_list.append("tpm-tis")
            if tpmversion != '1.2':
                mod_list.append("tpm-crb")
            mod_list.sort()
        return mod_list

    @staticmethod
    def populate_tpm_model_combo(vm, combo, tpmversion):
        model = combo.get_model()
        model.clear()

        mod_list = vmmAddHardware._get_tpm_model_list(vm, tpmversion)
        for m in mod_list:
            model.append([m, DeviceTpm.get_pretty_model(m)])
        combo.set_active(0)

    @staticmethod
    def build_tpm_model_combo(vm, combo, tpmversion):
        _build_combo(combo, [])
        vmmAddHardware.populate_tpm_model_combo(vm, combo, tpmversion)


    def _build_panic_model_combo(self):
        values = []
        for m in DevicePanic.get_models(self.vm.get_xmlobj().os):
            values.append([m, DevicePanic.get_pretty_model(m)])

        default = DevicePanic.get_default_model(self.vm.get_xmlobj())
        _build_combo(self.widget("panic-model"), values, default_value=default)


    def _build_controller_type_combo(self):
        values = []
        for t in DeviceController.get_recommended_types(self.vm.xmlobj):
            values.append([t, DeviceController.pretty_type(t)])

        _build_combo(self.widget("controller-type"), values,
                default_value=DeviceController.TYPE_SCSI)

    @staticmethod
    def populate_controller_model_combo(combo, controller_type):
        model = combo.get_model()
        model.clear()

        rows = []
        if controller_type == DeviceController.TYPE_USB:
            rows.append(["usb3", "USB 3"])
            rows.append(["ich9-ehci1", "USB 2"])
        elif controller_type == DeviceController.TYPE_SCSI:
            rows.append(["virtio-scsi", "VirtIO SCSI"])
        rows.append([None, _("Hypervisor default")])

        for row in rows:
            model.append(row)
        uiutil.set_list_selection(combo, rows[0][0])



    #########################
    # Internal misc helpers #
    #########################

    def _get_char_class(self):
        row = self._get_hw_selection()
        label = "serial"

        if row:
            label = row[5]

        if label == "parallel":
            return DeviceParallel
        elif label == "channel":
            return DeviceChannel
        elif label == "console":
            return DeviceConsole
        return DeviceSerial

    def _set_hw_selection(self, page):
        uiutil.set_list_selection_by_number(self.widget("hw-list"), page)

    def _get_hw_selection(self):
        return uiutil.get_list_selected_row(self.widget("hw-list"))


    ################
    # UI listeners #
    ################

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
            self._populate_char_device_type_combo()
            self.widget("char-device-type").emit("changed")
            self.widget("char-target-name").emit("changed")

        if page == PAGE_HOSTDEV:
            # Need to do this here, since we share the hostdev page
            # between two different HW options
            row = self._get_hw_selection()
            devtype = "usb_device"
            if row and row[5] == "pci":
                devtype = "pci"
            self._populate_hostdev_model(devtype)

        if page == PAGE_CONTROLLER:
            # We need to trigger this as it can desensitive 'finish'
            self.widget("controller-type").emit("changed")

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
            devclass = self._get_char_class()(self.conn.get_backend())
            return _("%s Device") % devclass.DEVICE_TYPE.capitalize()
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

    def _refresh_disk_bus(self, devtype):
        widget = self.widget("storage-bustype")
        model = widget.get_model()
        self.populate_disk_bus_combo(self.vm, devtype, model)

        # By default, select bus of the first disk assigned to the VM
        default_bus = None
        for i in self.vm.xmlobj.devices.disk:
            if i.device == devtype:
                default_bus = i.bus
                break

        if default_bus:
            uiutil.set_list_selection(widget, default_bus)
        elif len(model) > 0:
            widget.set_active(0)

    def _change_storage_devtype(self, ignore):
        devtype = uiutil.get_list_selection(
            self.widget("storage-devtype"))
        self._refresh_disk_bus(devtype)

        # Reset the status of disk-pr-checkbox to inactive
        self.widget("disk-pr-checkbox").set_active(False)
        is_lun = devtype == "lun"
        uiutil.set_grid_row_visible(self.widget("disk-pr-checkbox"), is_lun)

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
            "device_path": "tpm-device-path",
            "version": "tpm-version",
        }

        self._dev = DeviceTpm(self.conn.get_backend())
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

    def _change_char_target_name(self, src):
        if not src.get_visible():
            return

        text = src.get_child().get_text()
        settype = None
        if text == DeviceChannel.CHANNEL_NAME_SPICE:
            settype = "spicevmc"
        elif text == DeviceChannel.CHANNEL_NAME_SPICE_WEBDAV:
            settype = "spiceport"
            self.widget("char-channel").set_text(text)
        elif (text == DeviceChannel.CHANNEL_NAME_QEMUGA or
              text == DeviceChannel.CHANNEL_NAME_LIBGUESTFS):
            settype = "unix"
        if settype:
            uiutil.set_list_selection(
                self.widget("char-device-type"), settype)

    def _change_char_device_type(self, src):
        devtype = uiutil.get_list_selection(src)
        if devtype is None:
            return

        char_class = self._get_char_class()
        dev = char_class(self.conn.get_backend())
        dev.type = devtype

        ischan = dev.DEVICE_TYPE == "channel"
        iscon = dev.DEVICE_TYPE == "console"
        show_auto = devtype == "unix" and ischan

        uiutil.set_grid_row_visible(self.widget("char-path-label"),
                dev.supports_property("source_path"))
        uiutil.set_grid_row_visible(self.widget("char-channel-label"),
                dev.supports_property("source_channel"))

        uiutil.set_grid_row_visible(
            self.widget("char-target-name-label"), ischan)
        uiutil.set_grid_row_visible(
            self.widget("char-target-type-label"), iscon)
        uiutil.set_grid_row_visible(
            self.widget("char-auto-socket-label"), show_auto)
        self.widget("char-auto-socket").emit("toggled")

    def _change_usbredir_type(self, src):
        pass

    def _change_controller_type(self, src):
        ignore = src
        combo = self.widget("controller-model")

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
        combo.set_sensitive(True)
        model_tooltip = self.widget("controller-tooltip")
        show_tooltip(model_tooltip, False)

        controllers = self.vm.xmlobj.devices.controller
        if controller_type == DeviceController.TYPE_USB:
            usb_controllers = [x for x in controllers if
                    (x.type == DeviceController.TYPE_USB)]
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


    ######################
    # Add device methods #
    ######################

    def _setup_device(self, asyncjob):
        if self._dev.DEVICE_TYPE != "disk":
            return

        poolname = None
        if (self._dev.wants_storage_creation() and
            self._dev.get_parent_pool()):
            poolname = self._dev.get_parent_pool().name()

        logging.debug("Running build_storage() for device=%s", self._dev)
        self._dev.build_storage(meter=asyncjob.get_meter())
        logging.debug("build_storage() complete")

        if poolname:
            try:
                pool = self.conn.get_pool(poolname)
                self.idle_add(pool.refresh)
            except Exception:
                logging.debug("Error looking up pool=%s for refresh after "
                    "storage creation.", poolname, exc_info=True)


    def _add_device(self):
        xml = self._dev.get_xml()
        logging.debug("Adding device:\n%s", xml)

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
                          controller.get_xml())
        # Hotplug device
        attach_err = False
        try:
            if controller is not None:
                self.vm.attach_device(controller)
            self.vm.attach_device(self._dev)
        except Exception as e:
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
        except Exception as e:
            self.err.show_err(_("Error adding device: %s") % str(e))
            return True

        return False

    def _finish_cb(self, error, details):
        failure = True
        if not error:
            try:
                failure = self._add_device()
            except Exception as e:
                failure = True
                error = _("Unable to add device: %s") % str(e)
                details = "".join(traceback.format_exc())

        if error is not None:
            self.err.show_err(error, details=details)

        self.reset_finish_cursor()

        self._dev = None
        if not failure:
            self.close()

    def _finish(self, ignore=None):
        try:
            if self._validate() is False:
                return
        except Exception as e:
            self.err.show_err(
                    _("Error validating device parameters: %s") % str(e))
            return

        self.set_finish_cursor()
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
        # Any uncaught errors in this function are reported via _finish()
        page_num = self.widget("create-pages").get_current_page()

        # pylint: disable=assignment-from-no-return
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
        controllers = self.vm.xmlobj.devices.controller
        ctrls_scsi = [x for x in controllers if
                (x.type == DeviceController.TYPE_SCSI)]

        # Create possible new controller
        controller = DeviceController(self.conn.get_backend())
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
        occupied = {}
        for d in used_disks:
            if (d.get_target_prefix() == disk.get_target_prefix() and
                d.bus == "scsi"):
                num = DeviceDisk.target_to_num(d.target)
                idx = num // 7
                if idx not in occupied:
                    occupied[idx] = []
                if d.target not in occupied[idx]:
                    occupied[idx].append(d.target)

        for c in ctrls_scsi:
            if c.index not in occupied or len(occupied[c.index]) < 7:
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
        io = uiutil.get_list_selection(
            self.widget("storage-io"))
        discard = uiutil.get_list_selection(
            self.widget("storage-discard"))
        detect_zeroes = uiutil.get_list_selection(
            self.widget("storage-detect-zeroes"))
        if device == "lun":
            reservations_managed = self.widget("disk-pr-checkbox").get_active()

        controller_model = None
        if (bus == "scsi" and
            self.vm.get_hv_type() in ["qemu", "kvm", "test"] and
            not self.vm.xmlobj.os.is_pseries() and not
            any([c.type == "scsi"
                 for c in self.vm.xmlobj.devices.controller])):
            controller_model = "virtio-scsi"

        collidelist = [d.path for d in self.vm.xmlobj.devices.disk]
        try:
            disk = self.addstorage.validate_storage(self.vm.get_name(),
                collidelist=collidelist, device=device)
        except Exception as e:
            return self.err.val_err(_("Storage parameter error."), e)

        if disk is False:
            return False

        try:
            used = []
            disk.bus = bus
            if cache:
                disk.driver_cache = cache
            if io:
                disk.driver_io = io
            if discard:
                disk.driver_discard = discard
            if detect_zeroes:
                disk.driver_detect_zeroes = detect_zeroes
            if device == "lun" and reservations_managed:
                disk.reservations_managed = "yes"

            # Generate target
            disks = (self.vm.xmlobj.devices.disk +
                     self.vm.get_xmlobj(inactive=True).devices.disk)
            for d in disks:
                if d.target not in used:
                    used.append(d.target)

            prefer_ctrl = self._set_disk_controller(
                disk, controller_model, disks)

            disk.generate_target(used, prefer_ctrl)
        except Exception as e:
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

        ret = self._netlist.validate_network(mac, model)
        if ret is False:
            return False

        self._dev = ret

    def _validate_page_input(self):
        typ, bus = uiutil.get_list_selection(self.widget("input-type"))
        self._dev = DeviceInput(self.conn.get_backend())
        self._dev.type = typ
        self._dev.bus = bus

    def _validate_page_graphics(self):
        (gtype, port, tlsport, listen,
         addr, passwd, keymap, gl, rendernode) = self._gfxdetails.get_values()
        self._dev = DeviceGraphics(self.conn.get_backend())
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

    def _validate_page_sound(self):
        smodel = uiutil.get_list_selection(self.widget("sound-model"))
        self._dev = DeviceSound(self.conn.get_backend())
        self._dev.model = smodel

    def _validate_page_hostdev(self):
        nodedev = uiutil.get_list_selection(self.widget("host-device"))
        if nodedev is None:
            return self.err.val_err(_("Physical Device Required"),
                                    _("A device must be selected."))

        dev = DeviceHostdev(self.conn.get_backend())
        # Hostdev collision
        names  = []
        for vm in self.conn.list_vms():
            for hostdev in vm.xmlobj.devices.hostdev:
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

    def _validate_page_char(self):
        char_class = self._get_char_class()
        devtype = uiutil.get_list_selection(self.widget("char-device-type"))

        typebox = self.widget("char-target-type")
        source_path = self.widget("char-path").get_text()
        source_channel = self.widget("char-channel").get_text()
        target_name = self.widget("char-target-name").get_child().get_text()
        target_type = uiutil.get_list_selection(typebox)

        if not self.widget("char-target-name").get_visible():
            target_name = None
        if not typebox.get_visible():
            target_type = None
        if (self.widget("char-auto-socket").get_visible() and
            self.widget("char-auto-socket").get_active()):
            source_path = None

        self._dev = char_class(self.conn.get_backend())
        self._dev.type = devtype
        if self._dev.supports_property("source_path"):
            self._dev.source_path = source_path
        if self._dev.supports_property("source_channel"):
            self._dev.source_channel = source_channel
        if self._dev.supports_property("target_name"):
            self._dev.target_name = target_name
        if self._dev.supports_property("target_type"):
            self._dev.target_type = target_type

    def _validate_page_video(self):
        model = uiutil.get_list_selection(self.widget("video-model"))
        self._dev = DeviceVideo(self.conn.get_backend())
        self._dev.model = model

    def _validate_page_watchdog(self):
        model = uiutil.get_list_selection(self.widget("watchdog-model"))
        action = uiutil.get_list_selection(self.widget("watchdog-action"))
        self._dev = DeviceWatchdog(self.conn.get_backend())
        self._dev.model = model
        self._dev.action = action

    def _validate_page_filesystem(self):
        if self._fsdetails.validate_page_filesystem() is False:
            return False
        self._dev = self._fsdetails.get_dev()

    def _validate_page_smartcard(self):
        mode = uiutil.get_list_selection(self.widget("smartcard-mode"))
        self._dev = DeviceSmartcard(self.conn.get_backend())
        self._dev.mode = mode

    def _validate_page_usbredir(self):
        stype = uiutil.get_list_selection(self.widget("usbredir-list"))
        self._dev = DeviceRedirdev(self.conn.get_backend())
        self._dev.type = stype

    def _validate_page_tpm(self):
        typ = uiutil.get_list_selection(self.widget("tpm-type"))
        model = uiutil.get_list_selection(self.widget("tpm-model"))
        device_path = self.widget("tpm-device-path").get_text()
        version = uiutil.get_list_selection(self.widget("tpm-version"))

        value_mappings = {
            "type": typ,
            "model": model,
            "device_path": device_path,
            "version": version,
        }

        self._dev = DeviceTpm(self.conn.get_backend())
        for param_name, val in value_mappings.items():
            if self._dev.supports_property(param_name) and val is not None:
                setattr(self._dev, param_name, val)

    def _validate_page_panic(self):
        model = uiutil.get_list_selection(self.widget("panic-model"))
        self._dev = DevicePanic(self.conn.get_backend())
        self._dev.model = model

    def _validate_page_controller(self):
        controller_type = uiutil.get_list_selection(
            self.widget("controller-type"))
        model = uiutil.get_list_selection(self.widget("controller-model"))

        self._selected_model = model
        if model == "usb3":
            self._dev = DeviceController.get_usb3_controller(
                    self.conn.get_backend(), self.vm.xmlobj)
            model = None
        else:
            self._dev = DeviceController(self.conn.get_backend())

        controllers = self.vm.xmlobj.devices.controller
        controller_num = [x for x in controllers if
                (x.type == controller_type)]
        if len(controller_num) > 0:
            index_new = max([x.index for x in controller_num]) + 1
            self._dev.index = index_new

        self._dev.type = controller_type

        if model and model != "none":
            self._dev.model = model

    def _validate_page_rng(self):
        device = self.widget("rng-device").get_text()
        if not device:
            return self.err.val_err(_("RNG selection error."),
                                _("A device must be specified."))

        self._dev = DeviceRng(self.conn.get_backend())
        self._dev.type = DeviceRng.TYPE_RANDOM
        self._dev.device = device


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

        self._storagebrowser.set_finish_cb(set_storage_cb)
        self._storagebrowser.set_browse_reason(reason)

        self._storagebrowser.show(self.topwin)

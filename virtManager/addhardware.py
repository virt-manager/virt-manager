# Copyright (C) 2006-2007, 2012-2015 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import traceback

from gi.repository import Gtk
from gi.repository import Gdk

from virtinst import (DeviceChannel, DeviceConsole,
        DeviceController, DeviceDisk, DeviceGraphics, DeviceHostdev,
        DeviceInput, DeviceInterface, DevicePanic, DeviceParallel,
        DeviceRedirdev, DeviceRng, DeviceSerial, DeviceSmartcard,
        DeviceSound, DeviceTpm, DeviceVideo, DeviceVsock, DeviceWatchdog)
from virtinst import log

from .lib import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI
from .device.addstorage import vmmAddStorage
from .device.fsdetails import vmmFSDetails
from .device.gfxdetails import vmmGraphicsDetails
from .device.netlist import vmmNetworkList
from .device.vsockdetails import vmmVsockDetails
from .storagebrowse import vmmStorageBrowser
from .xmleditor import vmmXMLEditor


(PAGE_DISK,
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
 PAGE_VSOCK) = range(17)


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
    def __init__(self, vm):
        vmmGObjectUI.__init__(self, "addhardware.ui", "vmm-add-hardware")

        self.vm = vm
        self.conn = vm.conn

        self._storagebrowser = None

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

        self._vsockdetails = vmmVsockDetails(self.vm, self.builder, self.topwin)
        self.widget("vsock-align").add(self._vsockdetails.top_box)

        self._xmleditor = vmmXMLEditor(self.builder, self.topwin,
                self.widget("create-pages-align"),
                self.widget("create-pages"))
        self._xmleditor.connect("xml-requested",
                self._xmleditor_xml_requested_cb)

        self.builder.connect_signals({
            "on_create_cancel_clicked": self.close,
            "on_vmm_create_delete_event": self.close,
            "on_create_finish_clicked": self._finish,
            "on_hw_list_changed": self._hw_selected_cb,

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
        log.debug("Showing addhw")
        self._reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()
        self.conn.schedule_priority_tick(pollnet=True,
                                         pollpool=True, polliface=True,
                                         pollnodedev=True)

    def close(self, ignore1=None, ignore2=None):
        if self.is_visible():
            log.debug("Closing addhw")
            self.topwin.hide()
        if self._storagebrowser:
            self._storagebrowser.close()

        return 1

    def _cleanup(self):
        self.vm = None
        self.conn = None

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
        self._vsockdetails.cleanup()
        self._vsockdetails = None
        self._xmleditor.cleanup()
        self._xmleditor = None


    ##########################
    # Initialization methods #
    ##########################

    def _set_initial_state(self):
        self.widget("create-pages").set_show_tabs(False)
        self.widget("top-pages").set_show_tabs(False)

        blue = Gdk.color_parse("#0072A8")
        self.widget("page-title-box").modify_bg(Gtk.StateType.NORMAL, blue)

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
        self.widget("hw-list").append_column(hw_col)

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

        # Name, icon name, page number, is sensitive, tooltip, icon size,
        # device type (serial/parallel)...
        model = Gtk.ListStore(str, str, int, bool, str, str)
        self.widget("hw-list").set_model(model)

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
            bool(DevicePanic.get_models(self.vm.get_xmlobj())),
            _("Not supported for this hypervisor/libvirt/arch combination."))
        add_hw_option(_("Virtio VSOCK"), "network-idle", PAGE_VSOCK,
            self.vm.is_hvm(),
            _("Not supported for this hypervisor/libvirt/arch combination."))


    def _reset_state(self):
        # Hide all notebook pages, otherwise the wizard window is as large
        # as the largest page
        for page in range(self.widget("create-pages").get_n_pages()):
            widget = self.widget("create-pages").get_nth_page(page)
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


        # Char parameters
        self.widget("char-path").set_text("")
        self.widget("char-channel").set_text("")
        self.widget("char-auto-socket").set_active(True)


        # RNG params
        default_rng = "/dev/random"
        if self.conn.support.conn_rng_urandom():
            default_rng = "/dev/urandom"
        self.widget("rng-device").set_text(default_rng)


        # Remaining devices
        self._fsdetails.reset_state()
        self.widget("tpm-device-path").set_text("/dev/tpm0")
        self._gfxdetails.reset_state()
        self._vsockdetails.reset_state()


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
            log.debug("Hotplug failed: %s", str(e))
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


    #####################
    # Pretty UI helpers #
    #####################

    @staticmethod
    def char_recommended_types(char_class):
        if char_class.XML_NAME == "console":
            return [DeviceSerial.TYPE_PTY]

        ret = [DeviceSerial.TYPE_PTY,
               DeviceSerial.TYPE_FILE,
               DeviceSerial.TYPE_UNIX]
        if char_class.XML_NAME == "channel":
            ret = [DeviceSerial.TYPE_SPICEVMC,
                   DeviceSerial.TYPE_SPICEPORT] + ret
        return ret

    @staticmethod
    def char_pretty_channel_name(val):
        if val == DeviceChannel.CHANNEL_NAME_SPICE:
            return "spice"
        if val == DeviceChannel.CHANNEL_NAME_QEMUGA:
            return "qemu-ga"
        if val == DeviceChannel.CHANNEL_NAME_LIBGUESTFS:
            return "libguestfs"
        if val == DeviceChannel.CHANNEL_NAME_SPICE_WEBDAV:
            return "spice-webdav"
        return None

    @staticmethod
    def char_pretty_type(ctype):
        """
        Return a human readable description of the passed char type
        """
        if ctype == DeviceSerial.TYPE_PTY:
            return _("Pseudo TTY")
        elif ctype == DeviceSerial.TYPE_FILE:
            return _("Output to a file")
        elif ctype == DeviceSerial.TYPE_TCP:
            return _("TCP net console")
        elif ctype == DeviceSerial.TYPE_UDP:
            return _("UDP net console")
        elif ctype == DeviceSerial.TYPE_UNIX:
            return _("Unix socket")
        elif ctype == DeviceSerial.TYPE_SPICEVMC:
            return _("Spice agent")
        elif ctype == DeviceSerial.TYPE_SPICEPORT:
            return _("Spice port")
        return ctype

    @staticmethod
    def controller_recommended_types():
        return [DeviceController.TYPE_SCSI,
                DeviceController.TYPE_USB,
                DeviceController.TYPE_VIRTIOSERIAL,
                DeviceController.TYPE_CCID]

    @staticmethod
    def controller_pretty_type(ctype):
        pretty_mappings = {
            DeviceController.TYPE_IDE:             "IDE",
            DeviceController.TYPE_FDC:              _("Floppy"),
            DeviceController.TYPE_SCSI:            "SCSI",
            DeviceController.TYPE_SATA:            "SATA",
            DeviceController.TYPE_VIRTIOSERIAL:    "VirtIO Serial",
            DeviceController.TYPE_USB:             "USB",
            DeviceController.TYPE_PCI:             "PCI",
            DeviceController.TYPE_CCID:            "CCID",
            DeviceController.TYPE_XENBUS:          "xenbus",
        }
        if ctype not in pretty_mappings:
            return ctype
        return pretty_mappings[ctype]

    @staticmethod
    def controller_pretty_desc(dev):
        ret = vmmAddHardware.controller_pretty_type(dev.type)
        if dev.type == "scsi":
            if dev.model == "virtio-scsi":
                ret = "Virtio " + ret
            elif dev.address.type == "spapr-vio":
                ret = "sPAPR " + ret
        if dev.type == "pci" and dev.model == "pcie-root":
            ret = "PCIe"
        return ret

    @staticmethod
    def disk_old_recommended_buses(guest):
        ret = []
        if guest.os.is_hvm() or guest.conn.is_test():
            if not guest.os.is_q35():
                ret.append("ide")
            ret.append("sata")
            ret.append("fdc")
            ret.append("scsi")
            ret.append("usb")

            if guest.type in ["qemu", "kvm", "test"]:
                ret.append("sd")
                ret.append("virtio")
                if "scsi" not in ret:
                    ret.append("scsi")

        if guest.conn.is_xen() or guest.conn.is_test():
            ret.append("xen")

        return ret

    @staticmethod
    def disk_recommended_buses(guest, domcaps, devtype):
        # try to get supported disk bus types from domain capabilities
        if "bus" in domcaps.devices.disk.enum_names():
            buses = domcaps.devices.disk.get_enum("bus").get_values()
        else:
            buses = vmmAddHardware.disk_old_recommended_buses(guest)

        bus_map = {
            "disk": ["ide", "sata", "scsi", "sd", "usb", "virtio", "xen"],
            "floppy": ["fdc"],
            "cdrom": ["ide", "sata", "scsi"],
            "lun": ["scsi"],
        }
        return [bus for bus in buses if bus in bus_map.get(devtype, [])]

    @staticmethod
    def disk_pretty_bus(bus):
        if bus in ["ide", "sata", "scsi", "usb", "sd"]:
            return bus.upper()
        if bus in ["xen"]:
            return bus.capitalize()
        if bus == "virtio":
            return "VirtIO"
        return bus

    @staticmethod
    def tpm_pretty_type(tpm_type):
        if tpm_type == DeviceTpm.TYPE_PASSTHROUGH:
            return _("Passthrough device")
        if tpm_type == DeviceTpm.TYPE_EMULATOR:
            return _("Emulated device")
        return tpm_type

    @staticmethod
    def tpm_pretty_model(tpm_model):
        if tpm_model == DeviceTpm.MODEL_TIS:
            return _("TIS")
        if tpm_model == DeviceTpm.MODEL_CRB:
            return _("CRB")
        return tpm_model

    @staticmethod
    def panic_pretty_model(panic_model):
        if panic_model == DevicePanic.MODEL_ISA:
            return _("ISA")
        elif panic_model == DevicePanic.MODEL_PSERIES:
            return _("pSeries")
        elif panic_model == DevicePanic.MODEL_HYPERV:
            return _("Hyper-V")
        elif panic_model == DevicePanic.MODEL_S390:
            return _("s390")
        return panic_model

    @staticmethod
    def rng_pretty_type(rng_type):
        if rng_type == DeviceRng.TYPE_RANDOM:
            return _("Random")
        if rng_type == DeviceRng.TYPE_EGD:
            return _("Entropy Gathering Daemon")
        return rng_type

    @staticmethod
    def rng_pretty_backend_type(backend_type):
        return {"udp": "UDP",
                "tcp": "TCP"}.get(backend_type) or backend_type

    @staticmethod
    def rng_pretty_mode(mode):
        return {"bind": _("Bind"),
                "connect": _("Connect")}.get(mode) or mode

    @staticmethod
    def sound_recommended_models(_guest):
        return ["ich6", "ich9", "ac97"]

    @staticmethod
    def sound_pretty_model(model):
        ret = model.upper()
        if model in ["ich6", "ich9"]:
            ret = "HDA (%s)" % model.upper()
        return ret

    @staticmethod
    def watchdog_pretty_action(action):
        if action == DeviceWatchdog.ACTION_RESET:
            return _("Forcefully reset the guest")
        if action == DeviceWatchdog.ACTION_SHUTDOWN:
            return _("Gracefully shutdown the guest")
        if action == DeviceWatchdog.ACTION_POWEROFF:
            return _("Forcefully power off the guest")
        if action == DeviceWatchdog.ACTION_PAUSE:
            return _("Pause the guest")
        if action == DeviceWatchdog.ACTION_NONE:
            return _("No action")
        if action == DeviceWatchdog.ACTION_DUMP:
            return _("Dump guest memory core")
        return action

    @staticmethod
    def input_pretty_name(typ, bus):
        if typ == "tablet" and bus == "usb":
            return _("EvTouch USB Graphics Tablet")

        if bus in ["usb", "ps2"]:
            return _("Generic") + (" %s %s" %
                (bus.upper(), str(typ).capitalize()))
        return "%s %s" % (str(bus).capitalize(), str(typ).capitalize())

    @staticmethod
    def interface_recommended_models(guest):
        if not guest.os.is_hvm():
            return []

        ret = []
        if guest.type in ["kvm", "qemu", "vz", "test"]:
            ret.append("virtio")
        if guest.os.is_x86():
            if guest.os.is_q35():
                ret.append("e1000e")
            else:
                ret.append("rtl8139")
                ret.append("e1000")
        if guest.type in ["xen", "test"]:
            ret.append("netfront")

        ret.sort()
        return ret

    @staticmethod
    def redirdev_pretty_type(typ):
        if typ == "tcp":
            return "TCP"
        if typ == "spicevmc":
            return "SpiceVMC"
        return typ and typ.capitalize()

    @staticmethod
    def video_recommended_models(guest):
        if guest.conn.is_xen():
            return ["xen", "vga"]
        if guest.conn.is_qemu() or guest.conn.is_test():
            return ["vga", "qxl", "virtio"]
        return []

    @staticmethod
    def video_pretty_model(model):
        if model in ["qxl", "vmvga", "vga"]:
            return model.upper()
        return model.capitalize()

    @staticmethod
    def hostdev_pretty_name(hostdev):
        def dehex(val):
            if val.startswith("0x"):
                val = val[2:]
            return val

        def safeint(val, fmt="%.3d"):
            try:
                int(val)
            except Exception:
                return str(val)
            return fmt % int(val)

        label = hostdev.type.upper()

        if hostdev.vendor and hostdev.product:
            label += " %s:%s" % (dehex(hostdev.vendor), dehex(hostdev.product))

        elif hostdev.bus and hostdev.device:
            label += " %s:%s" % (safeint(hostdev.bus), safeint(hostdev.device))

        elif (hostdev.bus and hostdev.slot and
              hostdev.function and hostdev.domain):
            label += (" %s:%s:%s.%s" %
                      (dehex(hostdev.domain), dehex(hostdev.bus),
                       dehex(hostdev.slot), dehex(hostdev.function)))

        return label


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
        buses = vmmAddHardware.disk_recommended_buses(vm.xmlobj, domcaps, devtype)

        model.clear()
        for bus in buses:
            model.append([bus, vmmAddHardware.disk_pretty_bus(bus)])


    @staticmethod
    def populate_network_model_combo(vm, combo):
        model = combo.get_model()
        model.clear()

        # [xml value, label]
        model.append([None, _("Hypervisor default")])
        for netmodel in vmmAddHardware.interface_recommended_models(vm.xmlobj):
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

        cvals = [((t, b), vmmAddHardware.input_pretty_name(t, b))
                 for t, b in devices]
        _build_combo(self.widget("input-type"), cvals)


    @staticmethod
    def build_sound_combo(vm, combo):
        values = []
        for m in vmmAddHardware.sound_recommended_models(vm.xmlobj):
            values.append([m, vmmAddHardware.sound_pretty_model(m)])

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
            if dev.xmlobj.is_usb_linux_root_hub():
                continue
            if dev.xmlobj.is_pci_bridge():
                continue
            prettyname = dev.pretty_name()

            if devtype == "pci":
                for subdev in netdevs:
                    if dev.xmlobj.name == subdev.xmlobj.parent:
                        prettyname += " (%s)" % subdev.pretty_name()

            model.append([dev.xmlobj, prettyname])

        if len(model) == 0:
            model.append([None, _("No Devices Available")])
        uiutil.set_list_selection_by_number(devlist, 0)


    @staticmethod
    def build_video_combo(vm, combo):
        values = []
        for m in vmmAddHardware.video_recommended_models(vm.xmlobj):
            values.append([m, vmmAddHardware.video_pretty_model(m)])
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

        for t in vmmAddHardware.char_recommended_types(char_class):
            model.append([t, vmmAddHardware.char_pretty_type(t) + " (%s)" % t])
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
            values.append([m, vmmAddHardware.watchdog_pretty_action(m)])
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
            values.append([t, vmmAddHardware.tpm_pretty_type(t)])
        _build_combo(self.widget("tpm-type"), values)
        values = []
        for t in DeviceTpm.MODELS:
            values.append([t, vmmAddHardware.tpm_pretty_model(t)])
        _build_combo(self.widget("tpm-model"), values)
        values = []
        for t in DeviceTpm.VERSIONS:
            values.append([t, t])
        _build_combo(self.widget("tpm-version"), values,
                default_value=DeviceTpm.VERSION_2_0)

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
            model.append([m, vmmAddHardware.tpm_pretty_model(m)])
        combo.set_active(0)

    @staticmethod
    def build_tpm_model_combo(vm, combo, tpmversion):
        _build_combo(combo, [])
        vmmAddHardware.populate_tpm_model_combo(vm, combo, tpmversion)


    def _build_panic_model_combo(self):
        values = []
        for m in DevicePanic.get_models(self.vm.get_xmlobj()):
            values.append([m, vmmAddHardware.panic_pretty_model(m)])

        default = DevicePanic.get_default_model(self.vm.get_xmlobj())
        _build_combo(self.widget("panic-model"), values, default_value=default)


    def _build_controller_type_combo(self):
        values = []
        for t in vmmAddHardware.controller_recommended_types():
            values.append([t, vmmAddHardware.controller_pretty_type(t)])

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

    def _set_error_page(self, msg=None):
        self.widget("top-pages").set_current_page(1)
        self.widget("error-label").set_text(msg or "Hardware selection error.")
        self.widget("create-finish").set_sensitive(False)


    ################
    # UI listeners #
    ################

    def _hw_selected_cb(self, src):
        self.widget("create-finish").set_sensitive(True)
        self._xmleditor.reset_state()

        row = self._get_hw_selection()
        if not row or not row[3]:
            self._set_error_page(row and row[4] or None)
            return

        page = row[2]

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
        self.widget("create-pages").get_nth_page(page).show()
        self.widget("create-pages").set_current_page(page)
        self.widget("top-pages").set_current_page(0)

    def _dev_to_title(self, page):
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
        if page == PAGE_VSOCK:
            return _("VM Sockets")

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

    def _xmleditor_xml_requested_cb(self, src):
        dev = self._build_device(check_xmleditor=False)
        self._xmleditor.set_xml(dev and dev.get_xml() or "")


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

        dev = DeviceTpm(self.conn.get_backend())
        dev.type = devtype

        uiutil.set_grid_row_visible(self.widget("tpm-device-path-label"),
                devtype == dev.TYPE_PASSTHROUGH)
        uiutil.set_grid_row_visible(self.widget("tpm-version-label"),
                devtype == dev.TYPE_EMULATOR)

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

        supports_path = [dev.TYPE_FILE, dev.TYPE_UNIX,
                         dev.TYPE_DEV, dev.TYPE_PIPE]
        supports_channel = [dev.TYPE_SPICEPORT]

        uiutil.set_grid_row_visible(self.widget("char-path-label"),
                devtype in supports_path)
        uiutil.set_grid_row_visible(self.widget("char-channel-label"),
                devtype in supports_channel)

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

    def _setup_device(self, asyncjob, dev):
        if dev.DEVICE_TYPE != "disk":
            return

        poolname = None
        if (dev.wants_storage_creation() and
            dev.get_parent_pool()):
            poolname = dev.get_parent_pool().name()

        log.debug("Running build_storage() for device=%s", dev)
        dev.build_storage(meter=asyncjob.get_meter())
        log.debug("build_storage() complete")

        if poolname:
            try:
                pool = self.conn.get_pool(poolname)
                self.idle_add(pool.refresh)
            except Exception:
                log.debug("Error looking up pool=%s for refresh after "
                    "storage creation.", poolname, exc_info=True)


    def _add_device(self, dev):
        xml = dev.get_xml()
        log.debug("Adding device:\n%s", xml)

        if self._remove_usb_controller:
            kwargs = {}
            kwargs["model"] = self._selected_model

            self.change_config_helper(self.vm.define_controller,
                    kwargs, self.vm, self.err,
                    devobj=self._remove_usb_controller)

            self._remove_usb_controller = None
            self._selected_model = None

            return

        controller = getattr(dev, "vmm_controller", None)
        if controller is not None:
            log.debug("Adding controller:\n%s",
                          controller.get_xml())
        # Hotplug device
        attach_err = False
        try:
            if controller is not None:
                self.vm.attach_device(controller)
            self.vm.attach_device(dev)
        except Exception as e:
            log.debug("Device could not be hotplugged: %s", str(e))
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
            self.vm.add_device(dev)
        except Exception as e:
            self.err.show_err(_("Error adding device: %s") % str(e))
            return True

        return False

    def _finish_cb(self, error, details, dev):
        failure = True
        if not error:
            try:
                failure = self._add_device(dev)
            except Exception as e:
                failure = True
                error = _("Unable to add device: %s") % str(e)
                details = "".join(traceback.format_exc())

        if error is not None:
            self.err.show_err(error, details=details)

        self.reset_finish_cursor()

        if not failure:
            self.close()

    def _finish(self, ignore=None):
        dev = self._build_device(check_xmleditor=True)
        if not dev:
            return

        try:
            if self._validate_device(dev) is False:
                return
        except Exception as e:
            self.err.show_err(
                    _("Error validating device parameters: %s") % str(e))
            return

        self.set_finish_cursor()
        progWin = vmmAsyncJob(self._setup_device, [dev],
                              self._finish_cb, [dev],
                              _("Creating device"),
                              _("Depending on the device, this may take "
                                "a few minutes to complete."),
                              self.topwin)
        progWin.run()


    ###########################
    # Device build/validation #
    ###########################

    def _validate_hostdev_collision(self, dev):
        names = []
        nodedev = getattr(dev, "vmm_nodedev", None)
        if not nodedev:
            return

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

    def _validate_device(self, dev):
        dev.validate()

        if dev.DEVICE_TYPE == "disk":
            if self.addstorage.validate_device(dev) is False:
                return False

        if dev.DEVICE_TYPE == "network":
            self._netlist.validate_device(dev)

        if dev.DEVICE_TYPE == "hostdev":
            self._validate_hostdev_collision(dev)

    def _build_xmleditor_device(self, srcdev):
        xml = self._xmleditor.get_xml()
        log.debug("Using XML from xmleditor:\n%s", xml)
        devclass = srcdev.__class__
        dev = devclass(srcdev.conn, parsexml=xml)

        if srcdev.DEVICE_TYPE == "disk":
            if (srcdev.path == dev.path and
                srcdev.get_vol_install()):
                dev.set_vol_install(srcdev.get_vol_install())
            elif dev.path:
                # Needed to convince disk.validate() to validate a passed path
                dev.set_backend_for_existing_path()

        return dev

    def _build_device(self, check_xmleditor):
        page_num = self.widget("create-pages").get_current_page()
        try:
            dev = self._build_device_page(page_num)

            if check_xmleditor and self._xmleditor.is_xml_selected():
                dev = self._build_xmleditor_device(dev)

            return dev
        except Exception as e:
            self.err.show_err(
                    _("Error building device XML: %s") % str(e))
            return

    def _build_device_page(self, page_num):
        # pylint: disable=assignment-from-no-return
        if page_num == PAGE_DISK:
            dev = self._build_storage()
        elif page_num == PAGE_CONTROLLER:
            dev = self._build_controller()
        elif page_num == PAGE_NETWORK:
            dev = self._build_network()
        elif page_num == PAGE_INPUT:
            dev = self._build_input()
        elif page_num == PAGE_GRAPHICS:
            dev = self._build_graphics()
        elif page_num == PAGE_SOUND:
            dev = self._build_sound()
        elif page_num == PAGE_HOSTDEV:
            dev = self._build_hostdev()
        elif page_num == PAGE_CHAR:
            dev = self._build_char()
        elif page_num == PAGE_VIDEO:
            dev = self._build_video()
        elif page_num == PAGE_WATCHDOG:
            dev = self._build_watchdog()
        elif page_num == PAGE_FILESYSTEM:
            dev = self._build_filesystem()
        elif page_num == PAGE_SMARTCARD:
            dev = self._build_smartcard()
        elif page_num == PAGE_USBREDIR:
            dev = self._build_usbredir()
        elif page_num == PAGE_TPM:
            dev = self._build_tpm()
        elif page_num == PAGE_RNG:
            dev = self._build_rng()
        elif page_num == PAGE_PANIC:
            dev = self._build_panic()
        elif page_num == PAGE_VSOCK:
            dev = self._build_vsock()

        dev.set_defaults(self.vm.get_xmlobj())
        return dev

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

    def _build_storage(self):
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
            not any([c.type == "scsi"
                 for c in self.vm.xmlobj.devices.controller])):
            controller_model = "virtio-scsi"

        disk = self.addstorage.build_device(self.vm.get_name(),
            collideguest=self.vm.xmlobj, device=device)

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
        return disk

    def _build_network(self):
        model = uiutil.get_list_selection(self.widget("net-model"))
        mac = None
        if self.widget("mac-address").get_active():
            mac = self.widget("create-mac-address").get_text()

        dev = self._netlist.build_device(mac, model)
        return dev

    def _build_input(self):
        typ, bus = uiutil.get_list_selection(self.widget("input-type"))
        dev = DeviceInput(self.conn.get_backend())
        dev.type = typ
        dev.bus = bus
        return dev

    def _build_graphics(self):
        (gtype, port, tlsport, listen,
         addr, passwd, keymap, gl, rendernode) = self._gfxdetails.get_values()
        dev = DeviceGraphics(self.conn.get_backend())
        dev.type = gtype
        dev.passwd = passwd
        dev.gl = gl
        dev.rendernode = rendernode

        if not listen or listen == "none":
            dev.listen = "none"
        elif listen == "address":
            dev.listen = addr
            dev.port = port
            dev.tlsPort = tlsport
        else:
            raise ValueError(_("invalid listen type"))
        if keymap:
            dev.keymap = keymap

        return dev

    def _build_sound(self):
        smodel = uiutil.get_list_selection(self.widget("sound-model"))
        dev = DeviceSound(self.conn.get_backend())
        dev.model = smodel
        return dev

    def _build_hostdev(self):
        nodedev = uiutil.get_list_selection(self.widget("host-device"))
        dev = DeviceHostdev(self.conn.get_backend())
        dev.set_from_nodedev(nodedev)
        setattr(dev, "vmm_nodedev", nodedev)
        return dev

    def _build_char(self):
        char_class = self._get_char_class()
        devtype = uiutil.get_list_selection(self.widget("char-device-type"))

        typebox = self.widget("char-target-type")
        source_path = self.widget("char-path").get_text()
        source_channel = self.widget("char-channel").get_text()
        target_name = self.widget("char-target-name").get_child().get_text()
        target_type = uiutil.get_list_selection(typebox)

        if not self.widget("char-path").get_visible():
            source_path = None
        if not self.widget("char-channel").get_visible():
            source_channel = None
        if not self.widget("char-target-name").get_visible():
            target_name = None
        if not typebox.get_visible():
            target_type = None

        dev = char_class(self.conn.get_backend())
        dev.type = devtype
        dev.source.path = source_path
        dev.source.channel = source_channel
        dev.target_name = target_name
        dev.target_type = target_type
        return dev

    def _build_video(self):
        model = uiutil.get_list_selection(self.widget("video-model"))
        dev = DeviceVideo(self.conn.get_backend())
        dev.model = model
        return dev

    def _build_watchdog(self):
        model = uiutil.get_list_selection(self.widget("watchdog-model"))
        action = uiutil.get_list_selection(self.widget("watchdog-action"))
        dev = DeviceWatchdog(self.conn.get_backend())
        dev.model = model
        dev.action = action
        return dev

    def _build_filesystem(self):
        if self._fsdetails.validate_page_filesystem() is False:
            return False
        return self._fsdetails.get_dev()

    def _build_smartcard(self):
        mode = uiutil.get_list_selection(self.widget("smartcard-mode"))
        dev = DeviceSmartcard(self.conn.get_backend())
        dev.mode = mode
        return dev

    def _build_usbredir(self):
        stype = uiutil.get_list_selection(self.widget("usbredir-list"))
        dev = DeviceRedirdev(self.conn.get_backend())
        dev.type = stype
        return dev

    def _build_tpm(self):
        typ = uiutil.get_list_selection(self.widget("tpm-type"))
        model = uiutil.get_list_selection(self.widget("tpm-model"))
        device_path = self.widget("tpm-device-path").get_text()
        version = uiutil.get_list_selection(self.widget("tpm-version"))

        if not self.widget("tpm-device-path").get_visible():
            device_path = None
        if not self.widget("tpm-version").get_visible():
            version = None

        dev = DeviceTpm(self.conn.get_backend())
        dev.type = typ
        dev.model = model
        dev.device_path = device_path
        dev.version = version
        return dev

    def _build_panic(self):
        model = uiutil.get_list_selection(self.widget("panic-model"))
        dev = DevicePanic(self.conn.get_backend())
        dev.model = model
        return dev

    def _build_vsock(self):
        auto_cid, cid = self._vsockdetails.get_values()
        dev = DeviceVsock(self.conn.get_backend())
        dev.auto_cid = auto_cid
        dev.cid = cid
        return dev

    def _build_controller(self):
        controller_type = uiutil.get_list_selection(
            self.widget("controller-type"))
        model = uiutil.get_list_selection(self.widget("controller-model"))

        self._selected_model = model
        if model == "usb3":
            dev = DeviceController.get_usb3_controller(
                    self.conn.get_backend(), self.vm.xmlobj)
            model = None
        else:
            dev = DeviceController(self.conn.get_backend())

        controllers = self.vm.xmlobj.devices.controller
        controller_num = [x for x in controllers if
                (x.type == controller_type)]
        if len(controller_num) > 0:
            index_new = max([x.index for x in controller_num]) + 1
            dev.index = index_new

        dev.type = controller_type

        if model and model != "none":
            dev.model = model
        return dev

    def _build_rng(self):
        device = self.widget("rng-device").get_text()
        dev = DeviceRng(self.conn.get_backend())
        dev.backend_model = DeviceRng.TYPE_RANDOM
        dev.device = device
        return dev


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

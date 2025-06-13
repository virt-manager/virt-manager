# Copyright (C) 2006-2008, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gtk

import libvirt

import virtinst
from virtinst import log

from ..lib import uiutil
from ..addhardware import vmmAddHardware
from ..baseclass import vmmGObjectUI
from ..device.addstorage import vmmAddStorage
from ..device.fsdetails import vmmFSDetails
from ..device.gfxdetails import vmmGraphicsDetails
from ..device.mediacombo import vmmMediaCombo
from ..device.netlist import vmmNetworkList
from ..device.tpmdetails import vmmTPMDetails
from ..device.vsockdetails import vmmVsockDetails
from ..lib.graphwidgets import Sparkline
from ..oslist import vmmOSList
from ..storagebrowse import vmmStorageBrowser
from ..xmleditor import vmmXMLEditor
from ..delete import vmmDeleteStorage


# Parameters that can be edited in the details window
(
    EDIT_XML,
    EDIT_NAME,
    EDIT_TITLE,
    EDIT_MACHTYPE,
    EDIT_FIRMWARE,
    EDIT_DESC,
    EDIT_OS_NAME,
    EDIT_VCPUS,
    EDIT_CPU,
    EDIT_TOPOLOGY,
    EDIT_MEM,
    EDIT_MEM_SHARED,
    EDIT_AUTOSTART,
    EDIT_BOOTORDER,
    EDIT_BOOTMENU,
    EDIT_KERNEL,
    EDIT_INIT,
    EDIT_DISK_BUS,
    EDIT_DISK_PATH,
    EDIT_DISK,
    EDIT_SOUND_MODEL,
    EDIT_SMARTCARD_MODE,
    EDIT_NET_MODEL,
    EDIT_NET_SOURCE,
    EDIT_NET_MAC,
    EDIT_NET_LINKSTATE,
    EDIT_GFX,
    EDIT_VIDEO_MODEL,
    EDIT_VIDEO_3D,
    EDIT_WATCHDOG_MODEL,
    EDIT_WATCHDOG_ACTION,
    EDIT_CONTROLLER_MODEL,
    EDIT_TPM,
    EDIT_VSOCK_AUTO,
    EDIT_VSOCK_CID,
    EDIT_FS,
    EDIT_HOSTDEV_ROMBAR,
    EDIT_HOSTDEV_USB_STARTUPPOLICY,
) = range(1, 39)


# Columns in hw list model
(
    HW_LIST_COL_LABEL,
    HW_LIST_COL_ICON_NAME,
    HW_LIST_COL_TYPE,
    HW_LIST_COL_DEVICE,
    HW_LIST_COL_KEY,
) = range(5)

# Types for the hw list model: numbers specify what order they will be listed
(
    HW_LIST_TYPE_GENERAL,
    HW_LIST_TYPE_OS,
    HW_LIST_TYPE_STATS,
    HW_LIST_TYPE_CPU,
    HW_LIST_TYPE_MEMORY,
    HW_LIST_TYPE_BOOT,
    HW_LIST_TYPE_DISK,
    HW_LIST_TYPE_NIC,
    HW_LIST_TYPE_INPUT,
    HW_LIST_TYPE_GRAPHICS,
    HW_LIST_TYPE_SOUND,
    HW_LIST_TYPE_CHAR,
    HW_LIST_TYPE_HOSTDEV,
    HW_LIST_TYPE_VIDEO,
    HW_LIST_TYPE_WATCHDOG,
    HW_LIST_TYPE_CONTROLLER,
    HW_LIST_TYPE_FILESYSTEM,
    HW_LIST_TYPE_SMARTCARD,
    HW_LIST_TYPE_REDIRDEV,
    HW_LIST_TYPE_TPM,
    HW_LIST_TYPE_RNG,
    HW_LIST_TYPE_PANIC,
    HW_LIST_TYPE_VSOCK,
) = range(23)

remove_pages = [
    HW_LIST_TYPE_NIC,
    HW_LIST_TYPE_INPUT,
    HW_LIST_TYPE_GRAPHICS,
    HW_LIST_TYPE_SOUND,
    HW_LIST_TYPE_CHAR,
    HW_LIST_TYPE_HOSTDEV,
    HW_LIST_TYPE_DISK,
    HW_LIST_TYPE_VIDEO,
    HW_LIST_TYPE_WATCHDOG,
    HW_LIST_TYPE_CONTROLLER,
    HW_LIST_TYPE_FILESYSTEM,
    HW_LIST_TYPE_SMARTCARD,
    HW_LIST_TYPE_REDIRDEV,
    HW_LIST_TYPE_TPM,
    HW_LIST_TYPE_RNG,
    HW_LIST_TYPE_PANIC,
    HW_LIST_TYPE_VSOCK,
]

# Boot device columns
(BOOT_KEY, BOOT_LABEL, BOOT_ICON, BOOT_ACTIVE, BOOT_CAN_SELECT) = range(5)


def _calculate_disk_bus_index(disklist):
    # Iterate through all disks and calculate what number they are
    # This sets disk.disk_bus_index which is not a standard property
    idx_mapping = {}
    ret = []
    for dev in disklist:
        devtype = dev.device
        bus = dev.bus
        key = devtype + (bus or "")

        if key not in idx_mapping:
            idx_mapping[key] = 1

        disk_bus_index = idx_mapping[key]
        idx_mapping[key] += 1
        ret.append((dev, disk_bus_index))

    return ret


def _label_for_device(dev, disk_bus_index):
    devtype = dev.DEVICE_TYPE

    if devtype == "disk":
        if dev.device == "floppy":
            return _("Floppy %(index)d") % {"index": disk_bus_index}

        busstr = ""
        if dev.bus:
            busstr = vmmAddHardware.disk_pretty_bus(dev.bus)
        if dev.device == "cdrom":
            return _("%(bus)s CDROM %(index)d") % {
                "bus": busstr,
                "index": disk_bus_index,
            }
        elif dev.device == "disk":
            return _("%(bus)s Disk %(index)d") % {
                "bus": busstr,
                "index": disk_bus_index,
            }
        return _("%(bus)s %(device)s %(index)d") % {
            "bus": busstr,
            "device": dev.device.capitalize(),
            "index": disk_bus_index,
        }

    if devtype == "interface":
        mac = dev.macaddr[-9:] or ""
        return _("NIC %(mac)s") % {"mac": mac}

    if devtype == "input":
        if dev.type == "tablet":
            return _("Tablet")
        elif dev.type == "mouse":
            return _("Mouse")
        elif dev.type == "keyboard":
            return _("Keyboard")
        return _("Input")  # pragma: no cover

    if devtype == "serial":
        port = dev.target_port or 0
        return _("Serial %(num)d") % {"num": port + 1}

    if devtype == "parallel":
        port = dev.target_port or 0
        return _("Parallel %(num)d") % {"num": port + 1}

    if devtype == "console":
        port = dev.target_port or 0
        return _("Console %(num)d") % {"num": port + 1}

    if devtype == "channel":
        pretty_type = vmmAddHardware.char_pretty_type(dev.type)
        name = vmmAddHardware.char_pretty_channel_name(dev.target_name)
        # Don't print channel name with qemu-vdagent, to avoid ambiguity
        # with the typical spice agent channel
        if name and dev.type != "qemu-vdagent":
            return _("Channel (%(name)s)") % {"type": pretty_type, "name": name}
        return _("Channel %(type)s") % {"type": pretty_type}

    if devtype == "graphics":
        pretty = vmmGraphicsDetails.graphics_pretty_type_simple(dev.type)
        return _("Display %s") % pretty
    if devtype == "redirdev":
        return _("%(bus)s Redirector %(index)d") % {
            "bus": vmmAddHardware.disk_pretty_bus(dev.bus),
            "index": dev.get_xml_idx() + 1,
        }
    if devtype == "hostdev":
        return vmmAddHardware.hostdev_pretty_name(dev)
    if devtype == "sound":
        return _("Sound %s") % dev.model
    if devtype == "video":
        return _("Video %s") % vmmAddHardware.video_pretty_model(dev.model)
    if devtype == "filesystem":
        return _("Filesystem %(path)s") % {"path": dev.target[:8]}
    if devtype == "controller":
        idx = dev.index
        if idx is not None:
            return _("Controller %(controller)s %(index)s") % {
                "controller": vmmAddHardware.controller_pretty_desc(dev),
                "index": idx,
            }
        return _("Controller %(controller)s") % {
            "controller": vmmAddHardware.controller_pretty_desc(dev),
        }
    if devtype == "rng":
        if dev.device:
            return _("RNG %(device)s") % {"device": dev.device}
        return _("RNG")
    if devtype == "tpm":
        if dev.device_path:
            return _("TPM %(device)s") % {"device": dev.device_path}
        return _("TPM v%(version)s") % {"version": dev.version}

    devmap = {
        "panic": _("Panic Notifier"),
        "smartcard": _("Smartcard"),
        "vsock": _("VirtIO VSOCK"),
        "watchdog": _("Watchdog"),
    }
    return devmap[devtype]


def _icon_for_device(dev):
    devtype = dev.DEVICE_TYPE

    if devtype == "disk":
        if dev.device == "cdrom":
            return "media-optical"
        elif dev.device == "floppy":
            return "media-floppy"
        return "drive-harddisk"

    if devtype == "input":
        if dev.type == "keyboard":
            return "input-keyboard"
        if dev.type == "tablet":
            return "input-tablet"
        return "input-mouse"

    if devtype == "redirdev":
        return "device_usb"

    if devtype == "hostdev":
        if dev.type == "usb":
            return "device_usb"
        return "device_pci"

    typemap = {
        "interface": "network-idle",
        "graphics": "video-display",
        "serial": "device_serial",
        "parallel": "device_serial",
        "console": "device_serial",
        "channel": "device_serial",
        "video": "video-display",
        "watchdog": "device_pci",
        "sound": "audio-card",
        "rng": "system-run",
        "tpm": "device_cpu",
        "smartcard": "device_serial",
        "filesystem": "folder",
        "controller": "device_pci",
        "panic": "system-run",
        "vsock": "network-idle",
    }
    return typemap[devtype]


def _chipset_label_from_machine(machine):
    if machine and "q35" in machine:
        return "Q35"
    return "i440FX"


def _get_performance_icon_name():
    # This icon isn't in standard adwaita-icon-theme, so
    # fallback to system-run if it is missing
    icon = "utilities-system-monitor"
    if not Gtk.IconTheme.get_default().has_icon(icon):
        icon = "system-run"  # pragma: no cover
    return icon


class vmmDetails(vmmGObjectUI):
    def __init__(self, vm, builder, topwin, is_customize_dialog):
        vmmGObjectUI.__init__(self, "details.ui", None, builder=builder, topwin=topwin)

        self.vm = vm
        self._active_edits = []
        self.top_box = self.widget("details-top-box")

        self.addhw = None
        self.storage_browser = None
        self._mediacombo = None
        self.is_customize_dialog = is_customize_dialog

        def _e(edittype):
            def signal_cb(*args):
                self._enable_apply(edittype)

            return signal_cb

        self._mediacombo = vmmMediaCombo(self.conn, self.builder, self.topwin)
        self.widget("disk-source-align").add(self._mediacombo.top_box)
        self._mediacombo.set_mnemonic_label(self.widget("disk-source-mnemonic"))
        self._mediacombo.connect("changed", _e(EDIT_DISK_PATH))
        self._mediacombo.show_clear_icon()

        self.fsDetails = vmmFSDetails(self.vm, self.builder, self.topwin)
        self.widget("fs-alignment").add(self.fsDetails.top_box)
        self.fsDetails.connect("changed", _e(EDIT_FS))

        self.gfxdetails = vmmGraphicsDetails(self.vm, self.builder, self.topwin)
        self.widget("graphics-align").add(self.gfxdetails.top_box)
        self.gfxdetails.connect("changed", _e(EDIT_GFX))

        self.netlist = vmmNetworkList(self.conn, self.builder, self.topwin)
        self.widget("network-source-label-align").add(self.netlist.top_label)
        self.widget("network-source-ui-align").add(self.netlist.top_box)
        self.netlist.connect("changed", _e(EDIT_NET_SOURCE))

        self.tpmdetails = vmmTPMDetails(self.vm, self.builder, self.topwin)
        self.widget("tpm-align").add(self.tpmdetails.top_box)
        self.tpmdetails.connect("changed", _e(EDIT_TPM))

        self.vsockdetails = vmmVsockDetails(self.vm, self.builder, self.topwin)
        self.widget("vsock-align").add(self.vsockdetails.top_box)
        self.vsockdetails.connect("changed-auto-cid", _e(EDIT_VSOCK_AUTO))
        self.vsockdetails.connect("changed-cid", _e(EDIT_VSOCK_CID))

        self._addstorage = vmmAddStorage(self.conn, self.builder, self.topwin)
        self.widget("storage-advanced-align").add(self._addstorage.advanced_top_box)
        self._addstorage.connect("changed", _e(EDIT_DISK))

        self._xmleditor = vmmXMLEditor(
            self.builder, self.topwin, self.widget("hw-panel-align"), self.widget("hw-panel")
        )
        self._xmleditor.connect("changed", _e(EDIT_XML))
        self._xmleditor.connect("xml-requested", self._xmleditor_xml_requested_cb)
        self._xmleditor.connect("xml-reset", self._xmleditor_xml_reset_cb)

        self._oldhwkey = None
        self._popupmenu = None
        self._popupmenuitems = None
        self._os_list = None
        self._init_menus()
        self._init_details()

        self._graph_cpu = None
        self._graph_memory = None
        self._graph_disk = None
        self._graph_network = None
        self._init_graphs()

        self.vm.connect("inspection-changed", self._vm_inspection_changed_cb)

        self.builder.connect_signals(
            {
                "on_hw_list_changed": self._hw_changed_cb,
                "on_overview_name_changed": _e(EDIT_NAME),
                "on_overview_title_changed": _e(EDIT_TITLE),
                "on_machine_type_changed": _e(EDIT_MACHTYPE),
                "on_overview_firmware_changed": _e(EDIT_FIRMWARE),
                "on_overview_chipset_changed": _e(EDIT_MACHTYPE),
                "on_details_inspection_refresh_clicked": self._inspection_refresh_clicked_cb,
                "on_cpu_vcpus_changed": self._config_vcpus_changed_cb,
                "on_cpu_model_changed": _e(EDIT_CPU),
                "on_cpu_copy_host_clicked": self._cpu_copy_host_clicked_cb,
                "on_cpu_secure_toggled": _e(EDIT_CPU),
                "on_cpu_cores_changed": self._cpu_topology_changed_cb,
                "on_cpu_sockets_changed": self._cpu_topology_changed_cb,
                "on_cpu_threads_changed": self._cpu_topology_changed_cb,
                "on_cpu_topology_enable_toggled": self._cpu_topology_enable_cb,
                "on_mem_maxmem_changed": _e(EDIT_MEM),
                "on_mem_memory_changed": self._curmem_changed_cb,
                "on_mem_shared_access_toggled": _e(EDIT_MEM_SHARED),
                "on_boot_list_changed": self._boot_list_changed_cb,
                "on_boot_moveup_clicked": self._boot_moveup_clicked_cb,
                "on_boot_movedown_clicked": self._boot_movedown_clicked_cb,
                "on_boot_autostart_changed": _e(EDIT_AUTOSTART),
                "on_boot_menu_changed": _e(EDIT_BOOTMENU),
                "on_boot_kernel_enable_toggled": self._boot_kernel_toggled_cb,
                "on_boot_kernel_changed": _e(EDIT_KERNEL),
                "on_boot_initrd_changed": _e(EDIT_KERNEL),
                "on_boot_dtb_changed": _e(EDIT_KERNEL),
                "on_boot_kernel_args_changed": _e(EDIT_KERNEL),
                "on_boot_kernel_browse_clicked": self._browse_kernel_clicked_cb,
                "on_boot_initrd_browse_clicked": self._browse_initrd_clicked_cb,
                "on_boot_dtb_browse_clicked": self._browse_dtb_clicked_cb,
                "on_boot_init_path_changed": _e(EDIT_INIT),
                "on_boot_init_args_changed": _e(EDIT_INIT),
                "on_disk_source_browse_clicked": self._disk_source_browse_clicked_cb,
                "on_disk_bus_combo_changed": _e(EDIT_DISK_BUS),
                "on_network_model_combo_changed": _e(EDIT_NET_MODEL),
                "on_network_mac_entry_changed": _e(EDIT_NET_MAC),
                "on_network_link_state_checkbox_toggled": _e(EDIT_NET_LINKSTATE),
                "on_network_refresh_ip_clicked": self._refresh_ip_clicked_cb,
                "on_sound_model_combo_changed": _e(EDIT_SOUND_MODEL),
                "on_video_model_combo_changed": self._video_model_changed_cb,
                "on_video_3d_toggled": self._video_3d_toggled_cb,
                "on_watchdog_model_combo_changed": _e(EDIT_WATCHDOG_MODEL),
                "on_watchdog_action_combo_changed": _e(EDIT_WATCHDOG_ACTION),
                "on_smartcard_mode_combo_changed": _e(EDIT_SMARTCARD_MODE),
                "on_hostdev_rombar_toggled": _e(EDIT_HOSTDEV_ROMBAR),
                "on_hostdev_usb_startup_policy_changed": _e(EDIT_HOSTDEV_USB_STARTUPPOLICY),
                "on_controller_model_combo_changed": _e(EDIT_CONTROLLER_MODEL),
                "on_config_apply_clicked": self._config_apply_clicked_cb,
                "on_config_cancel_clicked": self._config_cancel_clicked_cb,
                "on_config_remove_clicked": self._config_remove_clicked_cb,
                "on_add_hardware_button_clicked": self._addhw_clicked_cb,
                "on_hw_list_button_press_event": self._popup_addhw_menu_cb,
            }
        )

        self._init_hw_list()
        self._refresh_page()

    @property
    def conn(self):
        return self.vm.conn

    def _cleanup(self):
        self._oldhwkey = None

        if self.addhw:
            self.addhw.cleanup()
            self.addhw = None
        if self.storage_browser:
            self.storage_browser.cleanup()
            self.storage_browser = None

        self._mediacombo.cleanup()
        self._mediacombo = None

        self.conn.disconnect_by_obj(self)
        self.vm = None
        self._popupmenu = None
        self._popupmenuitems = None

        self.gfxdetails.cleanup()
        self.gfxdetails = None
        self.fsDetails.cleanup()
        self.fsDetails = None
        self.netlist.cleanup()
        self.netlist = None
        self.vsockdetails.cleanup()
        self.vsockdetails = None
        self._xmleditor.cleanup()
        self._xmleditor = None
        self._addstorage.cleanup()
        self._addstorage = None
        self._os_list.cleanup()
        self._os_list = None

    ##########################
    # Initialization helpers #
    ##########################

    def _init_menus(self):
        # Add HW popup menu
        self._popupmenu = Gtk.Menu()

        addHW = Gtk.MenuItem.new_with_mnemonic(_("_Add Hardware"))
        addHW.show()

        def _addhw_clicked_cb(*args, **kwargs):
            self._show_addhw()

        addHW.connect("activate", _addhw_clicked_cb)

        rmHW = Gtk.MenuItem.new_with_mnemonic(_("_Remove Hardware"))
        rmHW.show()

        def _remove_clicked_cb(*args, **kwargs):
            self._config_remove()

        rmHW.connect("activate", _remove_clicked_cb)

        self._popupmenuitems = {"add": addHW, "remove": rmHW}
        for i in list(self._popupmenuitems.values()):
            self._popupmenu.add(i)

        self.widget("hw-panel").set_show_tabs(False)

    def _init_graphs(self):
        def _make_graph():
            g = Sparkline()
            g.set_hexpand(True)
            g.set_property("reversed", True)
            g.show()
            return g

        self._graph_cpu = _make_graph()
        self.widget("overview-cpu-usage-align").add(self._graph_cpu)

        self._graph_memory = _make_graph()
        self.widget("overview-memory-usage-align").add(self._graph_memory)

        self._graph_disk = _make_graph()
        self._graph_disk.set_property("filled", False)
        self._graph_disk.set_property("num_sets", 2)
        self._graph_disk.set_property(
            "rgb", [x / 255.0 for x in [0x82, 0x00, 0x3B, 0x29, 0x5C, 0x45]]
        )
        self.widget("overview-disk-usage-align").add(self._graph_disk)

        self._graph_network = _make_graph()
        self._graph_network.set_property("filled", False)
        self._graph_network.set_property("num_sets", 2)
        self._graph_network.set_property(
            "rgb", [x / 255.0 for x in [0x82, 0x00, 0x3B, 0x29, 0x5C, 0x45]]
        )
        self.widget("overview-network-traffic-align").add(self._graph_network)

    def _init_details(self):
        # Hardware list
        # [ label, icon name, hw type, dev xmlobj, unique key (dev or title)]
        hw_list_model = Gtk.ListStore(str, str, int, object, object)
        self.widget("hw-list").set_model(hw_list_model)

        hwCol = Gtk.TreeViewColumn(_("Hardware"))
        hwCol.set_spacing(6)
        hwCol.set_min_width(165)
        hw_txt = Gtk.CellRendererText()
        hw_img = Gtk.CellRendererPixbuf()
        hw_img.set_property("stock-size", Gtk.IconSize.LARGE_TOOLBAR)
        hwCol.pack_start(hw_img, False)
        hwCol.pack_start(hw_txt, True)
        hwCol.add_attribute(hw_txt, "text", HW_LIST_COL_LABEL)
        hwCol.add_attribute(hw_img, "icon-name", HW_LIST_COL_ICON_NAME)
        self.widget("hw-list").append_column(hwCol)

        # Description text view
        desc = self.widget("overview-description")
        buf = Gtk.TextBuffer()

        def _buf_changed_cb(*args):
            self._enable_apply(EDIT_DESC)

        buf.connect("changed", _buf_changed_cb)
        desc.set_buffer(buf)

        arch = self.vm.get_arch()
        caps = self.vm.conn.caps

        # Machine type
        machtype_combo = self.widget("machine-type")
        machtype_model = Gtk.ListStore(str)
        machtype_combo.set_model(machtype_model)
        uiutil.init_combo_text_column(machtype_combo, 0)
        machtype_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        machines = []
        try:
            capsinfo = caps.guest_lookup(
                os_type=self.vm.get_abi_type(),
                arch=self.vm.get_arch(),
                typ=self.vm.get_hv_type(),
                machine=self.vm.get_machtype(),
            )

            machines = capsinfo.machines[:]
        except Exception:
            log.exception("Error determining machine list")

        show_machine = arch not in ["i686", "x86_64"]
        uiutil.set_grid_row_visible(self.widget("machine-type-title"), show_machine)

        if show_machine:
            for machine in machines:
                machtype_model.append([machine])

        self.widget("machine-type").set_visible(self.is_customize_dialog)
        self.widget("machine-type-label").set_visible(not self.is_customize_dialog)

        # Firmware
        combo = self.widget("overview-firmware")
        # [label, loader path, is_sensitive, ./os/@firmware value]
        model = Gtk.ListStore(str, str, bool, str)
        combo.set_model(model)
        text = Gtk.CellRendererText()
        combo.pack_start(text, True)
        combo.add_attribute(text, "text", 0)
        combo.add_attribute(text, "sensitive", 2)

        domcaps = self.vm.get_domain_capabilities()
        uefipaths = [v.value for v in domcaps.os.loader.values]

        uefirows = []
        if domcaps.supports_firmware_efi():
            uefirows.append([_("UEFI"), None, True, "efi"])
        for path in uefipaths:
            uefirows.append([domcaps.label_for_firmware_path(path), path, True, None])

        hv_supports_uefi = domcaps.supports_uefi_loader() or domcaps.supports_firmware_efi()

        firmware_warn = None
        if not hv_supports_uefi:
            firmware_warn = _("Libvirt or hypervisor does not support UEFI.")
        elif not uefirows:
            firmware_warn = _(  # pragma: no cover
                "Libvirt did not detect any UEFI/OVMF firmware image installed on the host."
            )

        # Put the default entry first in the list
        model.append([domcaps.label_for_firmware_path(None), None, True, None])
        for row in uefirows:
            model.append(row)
        combo.set_active(0)

        self.widget("overview-firmware-warn").set_visible(
            self.is_customize_dialog and firmware_warn
        )
        self.widget("overview-firmware-warn").set_tooltip_text(firmware_warn)
        self.widget("overview-firmware").set_visible(self.is_customize_dialog)
        self.widget("overview-firmware-label").set_visible(not self.is_customize_dialog)
        uiutil.set_grid_row_visible(
            self.widget("overview-firmware-title"),
            self.vm.xmlobj.os.is_hvm()
            and (domcaps.supports_firmware_efi() or domcaps.arch_can_uefi()),
        )

        # Chipset
        combo = self.widget("overview-chipset")
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        model.append([_chipset_label_from_machine("pc"), "pc"])
        if "q35" in machines:
            model.append([_chipset_label_from_machine("q35"), "q35"])
        combo.set_active(0)

        self.widget("overview-chipset").set_visible(self.is_customize_dialog)
        self.widget("overview-chipset-label").set_visible(not self.is_customize_dialog)
        show_chipset = (self.conn.is_qemu() or self.conn.is_test()) and arch in ["i686", "x86_64"]
        uiutil.set_grid_row_visible(self.widget("overview-chipset-title"), show_chipset)

        # OS/Inspection page
        self._os_list = vmmOSList()
        self.widget("details-os-align").add(self._os_list.search_entry)
        self.widget("details-os-label").set_mnemonic_widget(self._os_list.search_entry)
        self._os_list.connect("os-selected", self._os_list_name_selected_cb)

        apps_list = self.widget("inspection-apps")
        apps_model = Gtk.ListStore(str, str, str)
        apps_list.set_model(apps_model)

        name_col = Gtk.TreeViewColumn(_("Name"))
        version_col = Gtk.TreeViewColumn(_("Version"))
        summary_col = Gtk.TreeViewColumn()

        apps_list.append_column(name_col)
        apps_list.append_column(version_col)
        apps_list.append_column(summary_col)

        name_text = Gtk.CellRendererText()
        name_col.pack_start(name_text, True)
        name_col.add_attribute(name_text, "text", 0)
        name_col.set_sort_column_id(0)

        version_text = Gtk.CellRendererText()
        version_col.pack_start(version_text, True)
        version_col.add_attribute(version_text, "text", 1)
        version_col.set_sort_column_id(1)

        summary_text = Gtk.CellRendererText()
        summary_col.pack_start(summary_text, True)
        summary_col.add_attribute(summary_text, "text", 2)
        summary_col.set_sort_column_id(2)

        # Boot device list
        boot_list = self.widget("boot-list")
        # [XML boot type, display name, icon name, enabled, can select]
        boot_list_model = Gtk.ListStore(str, str, str, bool, bool)
        boot_list.set_model(boot_list_model)

        chkCol = Gtk.TreeViewColumn()
        txtCol = Gtk.TreeViewColumn()

        boot_list.append_column(chkCol)
        boot_list.append_column(txtCol)

        chk = Gtk.CellRendererToggle()
        chk.connect("toggled", self._config_boot_toggled_cb)
        chkCol.pack_start(chk, False)
        chkCol.add_attribute(chk, "active", BOOT_ACTIVE)
        chkCol.add_attribute(chk, "visible", BOOT_CAN_SELECT)

        icon = Gtk.CellRendererPixbuf()
        txtCol.pack_start(icon, False)
        txtCol.add_attribute(icon, "icon-name", BOOT_ICON)

        text = Gtk.CellRendererText()
        txtCol.pack_start(text, True)
        txtCol.add_attribute(text, "text", BOOT_LABEL)
        txtCol.add_attribute(text, "sensitive", BOOT_ACTIVE)

        # CPU model combo
        cpu_model = self.widget("cpu-model")

        def sep_func(model, it, ignore):
            return model[it][3]

        # [label, sortkey, idstring, is sep]
        model = Gtk.ListStore(str, str, str, bool)
        cpu_model.set_model(model)
        cpu_model.set_entry_text_column(0)
        cpu_model.set_row_separator_func(sep_func, None)
        model.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        model.append(
            [_("Application Default"), "01", virtinst.DomainCpu.SPECIAL_MODE_APP_DEFAULT, False]
        )
        model.append(
            [_("Hypervisor Default"), "02", virtinst.DomainCpu.SPECIAL_MODE_HV_DEFAULT, False]
        )
        model.append(
            [_("Clear CPU configuration"), "03", virtinst.DomainCpu.SPECIAL_MODE_CLEAR, False]
        )
        model.append(["host-model", "04", virtinst.DomainCpu.SPECIAL_MODE_HOST_MODEL, False])
        model.append(
            ["host-passthrough", "05", virtinst.DomainCpu.SPECIAL_MODE_HOST_PASSTHROUGH, False]
        )
        model.append(["maximum", "06", virtinst.DomainCpu.SPECIAL_MODE_MAXIMUM, False])
        model.append([None, None, None, True])
        for name in domcaps.get_cpu_models():
            model.append([name, name, name, False])

        # Disk bus combo
        disk_bus = self.widget("disk-bus")
        vmmAddHardware.build_disk_bus_combo(self.vm, disk_bus)
        self.widget("disk-bus-label").set_visible(not self.is_customize_dialog)
        self.widget("disk-bus").set_visible(self.is_customize_dialog)
        if not self.is_customize_dialog:
            # Remove the mnemonic
            self.widget("disk-bus-labeller").set_text(_("Disk bus:"))

        # Network model
        net_model = self.widget("network-model")
        vmmAddHardware.build_network_model_combo(self.vm, net_model)

        # Network mac
        self.widget("network-mac-label").set_visible(not self.is_customize_dialog)
        self.widget("network-mac-entry").set_visible(self.is_customize_dialog)

        # Sound model
        sound_dev = self.widget("sound-model")
        vmmAddHardware.build_sound_combo(self.vm, sound_dev)

        # Video model combo
        video_dev = self.widget("video-model")
        vmmAddHardware.build_video_combo(self.vm, video_dev)

        # Watchdog model combo
        combo = self.widget("watchdog-model")
        vmmAddHardware.build_watchdogmodel_combo(self.vm, combo)

        # Watchdog action combo
        combo = self.widget("watchdog-action")
        vmmAddHardware.build_watchdogaction_combo(self.vm, combo)

        # Smartcard mode
        sc_mode = self.widget("smartcard-mode")
        vmmAddHardware.build_smartcard_mode_combo(self.vm, sc_mode)

        # Controller model
        combo = self.widget("controller-model")
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        combo.set_active(-1)

        combo = self.widget("controller-device-list")
        model = Gtk.ListStore(str)
        combo.set_model(model)
        combo.set_headers_visible(False)
        col = Gtk.TreeViewColumn()
        text = Gtk.CellRendererText()
        col.pack_start(text, True)
        col.add_attribute(text, "text", 0)
        combo.append_column(col)

        # Hostdev startup policy combo
        combo = self.widget("hostdev-usb-startup-policy")
        vmmAddHardware.build_hostdev_usb_startup_policy_combo(self.vm, combo)

    ##########################
    # Window state listeners #
    ##########################

    def _popup_addhw_menu_cb(self, widget, event):
        if event.button != 3:
            return

        # force select the list entry before showing popup_menu
        path_tuple = widget.get_path_at_pos(int(event.x), int(event.y))
        if path_tuple is None:
            return False  # pragma: no cover
        path = path_tuple[0]
        _iter = widget.get_model().get_iter(path)
        widget.get_selection().select_iter(_iter)

        rmdev = self._popupmenuitems["remove"]
        rmdev.set_visible(self.widget("config-remove").get_visible())
        rmdev.set_sensitive(self.widget("config-remove").get_sensitive())

        self._popupmenu.popup_at_pointer(event)

    def _set_hw_selection(self, page, _disable_apply=True):
        if _disable_apply:
            self._disable_apply()
        uiutil.set_list_selection_by_number(self.widget("hw-list"), page)

    def _get_hw_row(self):
        return uiutil.get_list_selected_row(self.widget("hw-list"))

    def _get_hw_row_for_device(self, dev):
        for row in self.widget("hw-list").get_model():
            if row[HW_LIST_COL_DEVICE] is dev:
                return row

    def _get_hw_row_label_for_device(self, dev):
        row = self._get_hw_row_for_device(dev)
        return row and row[HW_LIST_COL_LABEL] or ""

    def _has_unapplied_changes(self, row):
        """
        This is a bit confusing.

        * If there are now changes pending, we return False
        * If there are changes pending, we prompt the user whether
          they want to apply them. If they say no, return False
        * If the applying the changes succeeds, return False
        * Return True if applying the changes failed. In this
          case the caller should attempt to abort the action they
          are trying to perform, if possible
        """
        if not row:
            return False

        if not self.widget("config-apply").get_sensitive():
            return False

        log.debug("Unapplied changes active_edits=%s", self._active_edits)
        if not self.err.confirm_unapplied_changes():
            return False

        return not self._config_apply(row=row)

    def _hw_changed_cb(self, src):
        """
        When user changes the hw-list selection
        """
        newrow = self._get_hw_row()
        model = self.widget("hw-list").get_model()

        if not newrow or newrow[HW_LIST_COL_KEY] == self._oldhwkey:
            return

        oldhwrow = None
        for row in model:
            if row[HW_LIST_COL_KEY] == self._oldhwkey:
                oldhwrow = row
                break

        if self._has_unapplied_changes(oldhwrow):
            # Unapplied changes, and syncing them failed
            pageidx = 0
            for idx, row in enumerate(model):
                if row[HW_LIST_COL_KEY] == self._oldhwkey:
                    pageidx = idx
                    break
            self._set_hw_selection(pageidx, _disable_apply=False)
        else:
            self._oldhwkey = newrow[HW_LIST_COL_KEY]
            self._refresh_page()

    def _disable_device_remove(self, tooltip):
        self.widget("config-remove").set_sensitive(False)
        self.widget("config-remove").set_tooltip_text(tooltip)

    #######################
    # vmwindow Public API #
    #######################

    def _refresh_vm_state(self):
        active = self.vm.is_active()
        self.widget("overview-name").set_editable(not active)

        reason = self.vm.run_status_reason()
        if reason:
            status = "%s (%s)" % (self.vm.run_status(), reason)
        else:
            status = self.vm.run_status()
        self.widget("overview-status-text").set_text(status)
        self.widget("overview-status-icon").set_from_icon_name(
            self.vm.run_status_icon_name(), Gtk.IconSize.BUTTON
        )

    def vmwindow_resources_refreshed(self):
        row = self._get_hw_row()
        if row and row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_STATS:
            self._refresh_stats_page()

    def vmwindow_refresh_vm_state(self, is_current_page):
        if not is_current_page:
            self._disable_apply()
            return

        self._refresh_vm_state()
        self._repopulate_hw_list()

        if self.widget("config-apply").get_sensitive():
            # Apply button sensitive means user is making changes, don't
            # erase them
            return

        self._refresh_page()

    def vmwindow_activate_performance_page(self):
        index = 0
        model = self.widget("hw-list").get_model()
        for idx, row in enumerate(model):
            if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_STATS:
                index = idx
                break
        self._set_hw_selection(index)

    def vmwindow_has_unapplied_changes(self):
        return self._has_unapplied_changes(self._get_hw_row())

    def vmwindow_close(self):
        self._disable_apply()

    ##############################
    # Add/remove device handling #
    ##############################

    def _show_addhw(self):
        try:
            if self.addhw is None:
                self.addhw = vmmAddHardware(self.vm)

            self.addhw.show(self.topwin)
        except Exception as e:  # pragma: no cover
            self.err.show_err((_("Error launching hardware dialog: %s") % str(e)))

    def _remove_non_disk(self, devobj):
        if not self.err.chkbox_helper(
            self.config.get_confirm_removedev,
            self.config.set_confirm_removedev,
            text1=(_("Are you sure you want to remove this device?")),
        ):
            return

        success = vmmDeleteStorage.remove_devobj_internal(self.vm, self.err, devobj)
        if not success:
            return

        # This call here means when the vm config changes and triggers
        # refresh event, the UI page will be updated, rather than leaving
        # it untouched because it thinks changes are in progress
        self._disable_apply()

    def _remove_disk(self, disk):
        dialog = vmmDeleteStorage(disk)
        dialog.show(self.topwin, self.vm)

    def _config_remove(self):
        devobj = self._get_hw_row()[HW_LIST_COL_DEVICE]
        if devobj.DEVICE_TYPE == "disk":
            self._remove_disk(devobj)
        else:
            self._remove_non_disk(devobj)

    ############################
    # Details/Hardware getters #
    ############################

    def _get_config_boot_order(self):
        boot_model = self.widget("boot-list").get_model()
        devs = []

        for row in boot_model:
            if row[BOOT_ACTIVE]:
                devs.append(row[BOOT_KEY])

        return devs

    def _get_config_boot_selection(self):
        return uiutil.get_list_selected_row(self.widget("boot-list"))

    def _get_config_cpu_model(self):
        cpu_list = self.widget("cpu-model")
        text = cpu_list.get_child().get_text()

        if self.widget("cpu-copy-host").get_active():
            return virtinst.DomainCpu.SPECIAL_MODE_HOST_PASSTHROUGH

        key = None
        for row in cpu_list.get_model():
            if text == row[0]:
                key = row[2]
                break
        if not key:
            return text

        if key == virtinst.DomainCpu.SPECIAL_MODE_APP_DEFAULT:
            return self.config.get_default_cpu_setting()
        return key

    def _get_config_vcpus(self):
        return uiutil.spin_get_helper(self.widget("cpu-vcpus"))

    def _get_text(self, widgetname, strip=True, checksens=False):
        """
        Helper for reading widget text with a few options
        """
        widget = self.widget(widgetname)
        if checksens and (not widget.is_sensitive() or not widget.is_visible()):
            return ""

        ret = widget.get_text()
        if strip:
            ret = ret.strip()
        return ret

    ##############################
    # Details/Hardware listeners #
    ##############################

    def _browse_file(self, callback, reason=None):
        if not reason:
            reason = vmmStorageBrowser.REASON_IMAGE

        if self.storage_browser is None:
            self.storage_browser = vmmStorageBrowser(self.conn)

        self.storage_browser.set_finish_cb(callback)
        self.storage_browser.set_browse_reason(reason)
        self.storage_browser.show(self.topwin)

    def _inspection_refresh_clicked_cb(self, src):
        from ..lib.inspection import vmmInspection

        inspection = vmmInspection.get_instance()
        if inspection:
            inspection.vm_refresh(self.vm)

    def _os_list_name_selected_cb(self, src, osobj):
        self._enable_apply(EDIT_OS_NAME)

    def _curmem_changed_cb(self, src):
        self._enable_apply(EDIT_MEM)
        maxadj = self.widget("mem-maxmem")
        mem = uiutil.spin_get_helper(self.widget("mem-memory"))

        if maxadj.get_value() < mem:
            maxadj.set_value(mem)

        ignore, upper = maxadj.get_range()
        maxadj.set_range(mem, upper)

    def _config_vcpus_changed_cb(self, src):
        self._enable_apply(EDIT_VCPUS)

        conn = self.vm.conn
        host_active_count = conn.host_active_processor_count()
        cur = self._get_config_vcpus()

        # Warn about overcommit
        warn = bool(cur > host_active_count)
        self.widget("cpu-vcpus-warn-box").set_visible(warn)

    def _cpu_copy_host_clicked_cb(self, src):
        uiutil.set_grid_row_visible(self.widget("cpu-model"), not src.get_active())
        uiutil.set_grid_row_visible(self.widget("cpu-secure"), not src.get_active())
        self._enable_apply(EDIT_CPU)

    def _sync_cpu_topology_ui(self):
        manual_top = self.widget("cpu-topology-table").is_sensitive()
        self.widget("cpu-vcpus").set_sensitive(not manual_top)

        if manual_top:
            cores = uiutil.spin_get_helper(self.widget("cpu-cores")) or 1
            sockets = uiutil.spin_get_helper(self.widget("cpu-sockets")) or 1
            threads = uiutil.spin_get_helper(self.widget("cpu-threads")) or 1
            total = cores * sockets * threads
            if uiutil.spin_get_helper(self.widget("cpu-vcpus")) > total:
                self.widget("cpu-vcpus").set_value(total)
            self.widget("cpu-vcpus").set_value(total)
        else:
            vcpus = uiutil.spin_get_helper(self.widget("cpu-vcpus"))
            self.widget("cpu-sockets").set_value(vcpus or 1)
            self.widget("cpu-cores").set_value(1)
            self.widget("cpu-threads").set_value(1)

        self._enable_apply(EDIT_TOPOLOGY)

    def _cpu_topology_enable_cb(self, src):
        do_enable = src.get_active()
        self.widget("cpu-topology-table").set_sensitive(do_enable)
        self._sync_cpu_topology_ui()

    def _cpu_topology_changed_cb(self, src):
        self._sync_cpu_topology_ui()

    def _video_model_changed_cb(self, src):
        model = uiutil.get_list_selection(self.widget("video-model"))
        uiutil.set_grid_row_visible(self.widget("video-3d"), model == "virtio")
        self._enable_apply(EDIT_VIDEO_MODEL)

    def _video_3d_toggled_cb(self, src):
        self.widget("video-3d").set_inconsistent(False)
        self._enable_apply(EDIT_VIDEO_3D)

    def _config_bootdev_selected(self):
        boot_row = self._get_config_boot_selection()
        boot_selection = boot_row and boot_row[BOOT_KEY]
        boot_devs = self._get_config_boot_order()
        up_widget = self.widget("boot-moveup")
        down_widget = self.widget("boot-movedown")

        down_widget.set_sensitive(
            bool(
                boot_devs
                and boot_selection
                and boot_selection in boot_devs
                and boot_selection != boot_devs[-1]
            )
        )
        up_widget.set_sensitive(
            bool(
                boot_devs
                and boot_selection
                and boot_selection in boot_devs
                and boot_selection != boot_devs[0]
            )
        )

    def _config_boot_toggled_cb(self, src, index):
        model = self.widget("boot-list").get_model()
        row = model[index]

        row[BOOT_ACTIVE] = not row[BOOT_ACTIVE]
        self._config_bootdev_selected()
        self._enable_apply(EDIT_BOOTORDER)

    def _config_boot_move(self, move_up):
        row = self._get_config_boot_selection()
        if not row:
            return  # pragma: no cover

        row_key = row[BOOT_KEY]
        boot_order = self._get_config_boot_order()
        key_idx = boot_order.index(row_key)
        if move_up:
            new_idx = key_idx - 1
        else:
            new_idx = key_idx + 1

        if new_idx < 0 or new_idx >= len(boot_order):
            # Somehow we went out of bounds
            return  # pragma: no cover

        boot_list = self.widget("boot-list")
        model = boot_list.get_model()
        prev_row = None
        for row in model:
            # pylint: disable=unsubscriptable-object
            if prev_row and prev_row[BOOT_KEY] == row_key:
                model.swap(prev_row.iter, row.iter)
                break

            if row[BOOT_KEY] == row_key and prev_row and move_up:
                model.swap(prev_row.iter, row.iter)
                break

            prev_row = row

        boot_list.get_selection().emit("changed")
        self._enable_apply(EDIT_BOOTORDER)

    def _disk_source_browse_clicked_cb(self, src):
        disk = self._get_hw_row()[HW_LIST_COL_DEVICE]
        if disk.is_floppy():
            reason = vmmStorageBrowser.REASON_FLOPPY_MEDIA
        else:
            reason = vmmStorageBrowser.REASON_ISO_MEDIA

        def cb(ignore, path):
            self._mediacombo.set_path(path)

        self._browse_file(cb, reason=reason)

    def _set_network_ip_details(self, net):
        ipv4, ipv6 = self.vm.get_ips(net)
        label = ipv4 or ""
        if ipv6:
            if label:
                label += "\n"
            label += ipv6
        self.widget("network-ip").set_text(label or _("Unknown"))

    def _refresh_ip(self):
        net = self._get_hw_row()[HW_LIST_COL_DEVICE]
        self.vm.refresh_ips(net)
        self._set_network_ip_details(net)

    ##################################################
    # Details/Hardware config changes (apply button) #
    ##################################################

    def _disable_apply(self):
        self._active_edits = []
        self.widget("config-apply").set_sensitive(False)
        self.widget("config-cancel").set_sensitive(False)
        self._xmleditor.details_changed = False

    def _enable_apply(self, edittype):
        self.widget("config-apply").set_sensitive(True)
        self.widget("config-cancel").set_sensitive(True)
        if edittype not in self._active_edits:
            self._active_edits.append(edittype)
        if edittype != EDIT_XML:
            self._xmleditor.details_changed = True

    def _config_cancel(self, ignore=None):
        # Remove current changes and deactivate 'apply' button
        self._refresh_page()

    def _config_apply(self, row=None):
        pagetype = None
        dev = None

        if not row:
            row = self._get_hw_row()
        if row:
            pagetype = row[HW_LIST_COL_TYPE]
            dev = row[HW_LIST_COL_DEVICE]

        success = False
        try:
            if self._edited(EDIT_XML):
                if dev:
                    success = self._apply_xmleditor_device(dev)
                else:
                    success = self._apply_xmleditor_domain()
            elif pagetype is HW_LIST_TYPE_GENERAL:
                success = self._apply_overview()
            elif pagetype is HW_LIST_TYPE_OS:
                success = self._apply_os()
            elif pagetype is HW_LIST_TYPE_CPU:
                success = self._apply_vcpus()
            elif pagetype is HW_LIST_TYPE_MEMORY:
                success = self._apply_memory()
            elif pagetype is HW_LIST_TYPE_BOOT:
                success = self._apply_boot_options()
            elif pagetype is HW_LIST_TYPE_DISK:
                success = self._apply_disk(dev)
            elif pagetype is HW_LIST_TYPE_NIC:
                success = self._apply_network(dev)
            elif pagetype is HW_LIST_TYPE_GRAPHICS:
                success = self._apply_graphics(dev)
            elif pagetype is HW_LIST_TYPE_SOUND:
                success = self._apply_sound(dev)
            elif pagetype is HW_LIST_TYPE_VIDEO:
                success = self._apply_video(dev)
            elif pagetype is HW_LIST_TYPE_WATCHDOG:
                success = self._apply_watchdog(dev)
            elif pagetype is HW_LIST_TYPE_SMARTCARD:
                success = self._apply_smartcard(dev)
            elif pagetype is HW_LIST_TYPE_CONTROLLER:
                success = self._apply_controller(dev)
            elif pagetype is HW_LIST_TYPE_FILESYSTEM:
                success = self._apply_filesystem(dev)
            elif pagetype is HW_LIST_TYPE_HOSTDEV:
                success = self._apply_hostdev(dev)
            elif pagetype is HW_LIST_TYPE_TPM:
                success = self._apply_tpm(dev)
            elif pagetype is HW_LIST_TYPE_VSOCK:
                success = self._apply_vsock(dev)
        except Exception as e:
            self.err.show_err(_("Error applying changes: %s") % e)

        if success is not False:
            self._disable_apply()
            success = True
        return success

    def _edited(self, pagetype):
        return pagetype in self._active_edits

    def _change_config(self, cb, cb_kwargs, hotplug_args=None, devobj=None):
        return vmmAddHardware.change_config_helper(
            cb, cb_kwargs, self.vm, self.err, hotplug_args=hotplug_args, devobj=devobj
        )

    def _apply_xmleditor_domain(self):
        newxml = self._xmleditor.get_xml()

        def change_cb():
            return self.vm.define_xml(newxml)

        return self._change_config(change_cb, {})

    def _apply_xmleditor_device(self, devobj):
        newxml = self._xmleditor.get_xml()

        def change_cb():
            return self.vm.replace_device_xml(devobj, newxml)

        # By not passing devobj to change_config_helper we are
        # explicitly opting out of attempting device hotplug
        return self._change_config(change_cb, {})

    def _apply_overview(self):
        kwargs = {}
        hotplug_args = {}

        if self._edited(EDIT_TITLE):
            kwargs["title"] = self.widget("overview-title").get_text()
            hotplug_args["title"] = kwargs["title"]

        if self._edited(EDIT_FIRMWARE):
            kwargs["loader"] = uiutil.get_list_selection(self.widget("overview-firmware"), column=1)
            kwargs["firmware"] = uiutil.get_list_selection(
                self.widget("overview-firmware"), column=3
            )

        if self._edited(EDIT_MACHTYPE):
            if self.widget("overview-chipset").is_visible():
                kwargs["machine"] = uiutil.get_list_selection(
                    self.widget("overview-chipset"), column=1
                )
            else:
                kwargs["machine"] = uiutil.get_list_selection(self.widget("machine-type"))

        if self._edited(EDIT_DESC):
            desc_widget = self.widget("overview-description")
            kwargs["description"] = desc_widget.get_buffer().get_property("text") or ""
            hotplug_args["description"] = kwargs["description"]

        # This needs to be last
        if self._edited(EDIT_NAME):
            # Renaming is pretty convoluted, so do it here synchronously
            self.vm.rename_domain(self.widget("overview-name").get_text())

            if not kwargs and not hotplug_args:
                # Saves some useless redefine attempts
                return

        return self._change_config(self.vm.define_overview, kwargs, hotplug_args=hotplug_args)

    def _apply_os(self):
        kwargs = {}

        if self._edited(EDIT_OS_NAME):
            osobj = self._os_list.get_selected_os()
            kwargs["os_name"] = osobj and osobj.name or "generic"

        return self._change_config(self.vm.define_os, kwargs)

    def _apply_vcpus(self):
        kwargs = {}

        if self._edited(EDIT_VCPUS):
            kwargs["vcpus"] = self._get_config_vcpus()

        if self._edited(EDIT_CPU):
            kwargs["model"] = self._get_config_cpu_model()
            kwargs["secure"] = self.widget("cpu-secure").get_active()

        if self._edited(EDIT_TOPOLOGY):
            do_top = self.widget("cpu-topology-enable").get_active()
            kwargs["clear_topology"] = not do_top
            kwargs["sockets"] = self.widget("cpu-sockets").get_value()
            kwargs["cores"] = self.widget("cpu-cores").get_value()
            kwargs["threads"] = self.widget("cpu-threads").get_value()

        return self._change_config(self.vm.define_cpu, kwargs)

    def _apply_memory(self):
        kwargs = {}
        hotplug_args = {}

        if self._edited(EDIT_MEM):
            maxmem = uiutil.spin_get_helper(self.widget("mem-maxmem"))
            curmem = uiutil.spin_get_helper(self.widget("mem-memory"))
            curmem = int(curmem) * 1024
            maxmem = int(maxmem) * 1024

            kwargs["memory"] = curmem
            kwargs["maxmem"] = maxmem
            hotplug_args["memory"] = kwargs["memory"]
            hotplug_args["maxmem"] = kwargs["maxmem"]

        if self._edited(EDIT_MEM_SHARED):
            kwargs["mem_shared"] = self.widget("shared-memory").get_active()

        return self._change_config(self.vm.define_memory, kwargs, hotplug_args=hotplug_args)

    def _apply_boot_options(self):
        kwargs = {}

        if self._edited(EDIT_AUTOSTART):
            auto = self.widget("boot-autostart")
            try:
                self.vm.set_autostart(auto.get_active())
            except Exception as e:  # pragma: no cover
                self.err.show_err((_("Error changing autostart value: %s") % str(e)))
                return False

        if self._edited(EDIT_BOOTORDER):
            kwargs["boot_order"] = self._get_config_boot_order()

        if self._edited(EDIT_BOOTMENU):
            kwargs["boot_menu"] = self.widget("boot-menu").get_active()

        if self._edited(EDIT_KERNEL):
            kwargs["kernel"] = self._get_text("boot-kernel", checksens=True)
            kwargs["initrd"] = self._get_text("boot-initrd", checksens=True)
            kwargs["dtb"] = self._get_text("boot-dtb", checksens=True)
            kwargs["kernel_args"] = self._get_text("boot-kernel-args", checksens=True)

            if kwargs["initrd"] and not kwargs["kernel"]:
                msg = _("Cannot set initrd without specifying a kernel path")
                return self.err.val_err(msg)
            if kwargs["kernel_args"] and not kwargs["kernel"]:
                msg = _("Cannot set kernel arguments without specifying a kernel path")
                return self.err.val_err(msg)

        if self._edited(EDIT_INIT):
            kwargs["init"] = self._get_text("boot-init-path")
            kwargs["initargs"] = self._get_text("boot-init-args") or ""
            if not kwargs["init"]:
                return self.err.val_err(_("An init path must be specified"))

        return self._change_config(self.vm.define_boot, kwargs)

    def _apply_disk(self, devobj):
        kwargs = {}

        if self._edited(EDIT_DISK_PATH):
            path = self._mediacombo.get_path()

            names = virtinst.DeviceDisk.path_in_use_by(devobj.conn, path)
            if names:
                msg = _("Disk '%(path)s' is already in use by other guests %(names)s") % {
                    "path": path,
                    "names": names,
                }
                res = self.err.yes_no(msg, _("Do you really want to use the disk?"))
                if not res:
                    return False

            vmmAddStorage.check_path_search(self, self.conn, path)
            kwargs["path"] = path or None

        if self._edited(EDIT_DISK):
            vals = self._addstorage.get_values()
            kwargs.update(vals)

        if self._edited(EDIT_DISK_BUS):
            kwargs["bus"] = uiutil.get_list_selection(self.widget("disk-bus"))

        return self._change_config(self.vm.define_disk, kwargs, devobj=devobj)

    def _apply_sound(self, devobj):
        kwargs = {}

        if self._edited(EDIT_SOUND_MODEL):
            model = uiutil.get_list_selection(self.widget("sound-model"))
            if model:
                kwargs["model"] = model

        return self._change_config(self.vm.define_sound, kwargs, devobj=devobj)

    def _apply_smartcard(self, devobj):
        kwargs = {}

        if self._edited(EDIT_SMARTCARD_MODE):
            model = uiutil.get_list_selection(self.widget("smartcard-mode"))
            if model:
                kwargs["model"] = model

        return self._change_config(self.vm.define_smartcard, kwargs, devobj=devobj)

    def _apply_network(self, devobj):
        kwargs = {}

        if self._edited(EDIT_NET_MODEL):
            model = uiutil.get_list_selection(self.widget("network-model"))
            kwargs["model"] = model

        if self._edited(EDIT_NET_SOURCE):
            (
                kwargs["ntype"],
                kwargs["source"],
                kwargs["mode"],
                kwargs["portgroup"],
            ) = self.netlist.get_network_selection()

        if self._edited(EDIT_NET_MAC):
            kwargs["macaddr"] = self.widget("network-mac-entry").get_text()
            virtinst.DeviceInterface.check_mac_in_use(self.conn.get_backend(), kwargs["macaddr"])

        if self._edited(EDIT_NET_LINKSTATE):
            kwargs["linkstate"] = self.widget("network-link-state-checkbox").get_active()

        return self._change_config(self.vm.define_network, kwargs, devobj=devobj)

    def _apply_graphics(self, devobj):
        kwargs = {}
        if self._edited(EDIT_GFX):
            kwargs = self.gfxdetails.get_values()

        return self._change_config(self.vm.define_graphics, kwargs, devobj=devobj)

    def _apply_video(self, devobj):
        kwargs = {}

        if self._edited(EDIT_VIDEO_MODEL):
            model = uiutil.get_list_selection(self.widget("video-model"))
            if model:
                kwargs["model"] = model

        if self._edited(EDIT_VIDEO_3D):
            kwargs["accel3d"] = self.widget("video-3d").get_active()

        return self._change_config(self.vm.define_video, kwargs, devobj=devobj)

    def _apply_controller(self, devobj):
        kwargs = {}

        if self._edited(EDIT_CONTROLLER_MODEL):
            model = uiutil.get_list_selection(self.widget("controller-model"))
            kwargs["model"] = model

        return self._change_config(self.vm.define_controller, kwargs, devobj=devobj)

    def _apply_watchdog(self, devobj):
        kwargs = {}

        if self._edited(EDIT_WATCHDOG_MODEL):
            kwargs["model"] = uiutil.get_list_selection(self.widget("watchdog-model"))

        if self._edited(EDIT_WATCHDOG_ACTION):
            kwargs["action"] = uiutil.get_list_selection(self.widget("watchdog-action"))

        return self._change_config(self.vm.define_watchdog, kwargs, devobj=devobj)

    def _apply_filesystem(self, devobj):
        kwargs = {}

        if self._edited(EDIT_FS):
            kwargs["newdev"] = self.fsDetails.update_device(devobj)

        return self._change_config(self.vm.define_filesystem, kwargs, devobj=devobj)

    def _apply_hostdev(self, devobj):
        kwargs = {}

        if self._edited(EDIT_HOSTDEV_ROMBAR):
            kwargs["rom_bar"] = self.widget("hostdev-rombar").get_active()

        if self._edited(EDIT_HOSTDEV_USB_STARTUPPOLICY):
            startup_policy = uiutil.get_list_selection(self.widget("hostdev-usb-startup-policy"))
            kwargs["startup_policy"] = startup_policy

        return self._change_config(self.vm.define_hostdev, kwargs, devobj=devobj)

    def _apply_tpm(self, devobj):
        kwargs = {}

        if self._edited(EDIT_TPM):
            kwargs["newdev"] = self.tpmdetails.update_device(devobj)

        return self._change_config(self.vm.define_tpm, kwargs, devobj=devobj)

    def _apply_vsock(self, devobj):
        auto_cid, cid = self.vsockdetails.get_values()

        kwargs = {}

        if self._edited(EDIT_VSOCK_AUTO):
            kwargs["auto_cid"] = auto_cid
        if self._edited(EDIT_VSOCK_CID):
            kwargs["cid"] = cid

        return self._change_config(self.vm.define_vsock, kwargs, devobj=devobj)

    ###########################
    # Details page refreshers #
    ###########################

    def _refresh_page(self):
        row = self._get_hw_row()
        if not row:
            return  # pragma: no cover

        pagetype = row[HW_LIST_COL_TYPE]

        self.widget("config-remove").set_sensitive(True)
        self.widget("config-remove").set_tooltip_text(
            _("Remove this device from the virtual machine")
        )

        try:
            dev = row[HW_LIST_COL_DEVICE]
            if dev:
                self._xmleditor.set_xml(virtinst.xmlutil.unindent_device_xml(dev.get_xml()))
            else:
                self._xmleditor.set_xml_from_libvirtobject(self.vm)

            if pagetype == HW_LIST_TYPE_GENERAL:
                self._refresh_overview_page()
            elif pagetype == HW_LIST_TYPE_OS:
                self._refresh_os_page()
            elif pagetype == HW_LIST_TYPE_STATS:
                self._refresh_stats_page()
            elif pagetype == HW_LIST_TYPE_CPU:
                self._refresh_config_cpu()
            elif pagetype == HW_LIST_TYPE_MEMORY:
                self._refresh_config_memory()
            elif pagetype == HW_LIST_TYPE_BOOT:
                self._refresh_boot_page()
            elif pagetype == HW_LIST_TYPE_DISK:
                self._refresh_disk_page(dev)
            elif pagetype == HW_LIST_TYPE_NIC:
                self._refresh_network_page(dev)
            elif pagetype == HW_LIST_TYPE_INPUT:
                self._refresh_input_page(dev)
            elif pagetype == HW_LIST_TYPE_GRAPHICS:
                self._refresh_graphics_page(dev)
            elif pagetype == HW_LIST_TYPE_SOUND:
                self._refresh_sound_page(dev)
            elif pagetype == HW_LIST_TYPE_CHAR:
                self._refresh_char_page(dev)
            elif pagetype == HW_LIST_TYPE_HOSTDEV:
                self._refresh_hostdev_page(dev)
            elif pagetype == HW_LIST_TYPE_VIDEO:
                self._refresh_video_page(dev)
            elif pagetype == HW_LIST_TYPE_WATCHDOG:
                self._refresh_watchdog_page(dev)
            elif pagetype == HW_LIST_TYPE_CONTROLLER:
                self._refresh_controller_page(dev)
            elif pagetype == HW_LIST_TYPE_FILESYSTEM:
                self._refresh_filesystem_page(dev)
            elif pagetype == HW_LIST_TYPE_SMARTCARD:
                self._refresh_smartcard_page(dev)
            elif pagetype == HW_LIST_TYPE_REDIRDEV:
                self._refresh_redir_page(dev)
            elif pagetype == HW_LIST_TYPE_TPM:
                self._refresh_tpm_page(dev)
            elif pagetype == HW_LIST_TYPE_RNG:
                self._refresh_rng_page(dev)
            elif pagetype == HW_LIST_TYPE_PANIC:
                self._refresh_panic_page(dev)
            elif pagetype == HW_LIST_TYPE_VSOCK:
                self._refresh_vsock_page(dev)
        except Exception as e:  # pragma: no cover
            self.err.show_err(_("Error refreshing hardware page: %s") % str(e))
            # Don't return, we want the rest of the bits to run regardless

        self._disable_apply()
        rem = pagetype in remove_pages
        self.widget("config-remove").set_visible(rem)
        self.widget("hw-panel").set_current_page(pagetype)

    def _refresh_overview_page(self):
        # Basic details
        self.widget("overview-name").set_text(self.vm.get_name())
        self.widget("overview-uuid").set_text(self.vm.get_uuid())
        desc = self.vm.get_description() or ""
        desc_widget = self.widget("overview-description")
        desc_widget.get_buffer().set_text(desc)

        title = self.vm.get_title()
        self.widget("overview-title").set_text(title or "")

        # Hypervisor Details
        self.widget("overview-hv").set_text(self.vm.get_pretty_hv_type())
        arch = self.vm.get_arch() or _("Unknown")
        emu = self.vm.get_emulator() or _("None")
        self.widget("overview-arch").set_text(arch)
        self.widget("overview-emulator").set_text(emu)

        # Firmware
        domcaps = self.vm.get_domain_capabilities()
        if self.vm.get_xmlobj().os.firmware == "efi":
            firmware = _("UEFI")
        else:
            firmware = domcaps.label_for_firmware_path(self.vm.get_xmlobj().os.loader)
        if self.widget("overview-firmware").is_visible():
            uiutil.set_list_selection(self.widget("overview-firmware"), firmware)
        elif self.widget("overview-firmware-label").is_visible():
            self.widget("overview-firmware-label").set_text(firmware)

        # Machine settings
        machtype = self.vm.get_machtype() or _("Unknown")
        self.widget("machine-type-label").set_text(machtype)
        if self.widget("machine-type").is_visible():
            uiutil.set_list_selection(self.widget("machine-type"), machtype)

        # Chipset
        chipset = _chipset_label_from_machine(machtype)
        self.widget("overview-chipset-label").set_text(chipset)
        if self.widget("overview-chipset").is_visible():
            uiutil.set_list_selection(self.widget("overview-chipset"), chipset)

    def _refresh_os_page(self):
        self._os_list.select_os(self.vm.xmlobj.osinfo)

        inspection_supported = self.config.inspection_supported()
        uiutil.set_grid_row_visible(
            self.widget("details-overview-error"), bool(self.vm.inspection.errorstr)
        )
        if self.vm.inspection.errorstr:
            self.widget("details-overview-error").set_text(self.vm.inspection.errorstr)
            inspection_supported = False

        self.widget("details-inspection-apps").set_visible(inspection_supported)
        self.widget("details-inspection-refresh").set_visible(inspection_supported)
        if not inspection_supported:
            return

        # Applications (also inspection data)
        apps = self.vm.inspection.applications or []
        apps_list = self.widget("inspection-apps")
        apps_model = apps_list.get_model()
        apps_model.clear()
        for app in apps:
            name = ""
            if app.display_name:
                name = app.display_name
            elif app.name:
                name = app.name
            version = ""
            if app.epoch > 0:
                version += str(app.epoch) + ":"
            if app.version:
                version += app.version
            if app.release:
                version += "-" + app.release
            summary = ""
            if app.summary:
                summary = app.summary
            elif app.description:
                summary = app.description
                pos = summary.find("\n")
                if pos > -1:
                    summary = _("%(summary)s ...") % {"summary": summary[0:pos]}

            apps_model.append([name, version, summary])

    def _refresh_stats_page(self):
        def _multi_color(text1, text2):
            return '<span color="#82003B">%s</span> ' '<span color="#295C45">%s</span>' % (
                text1,
                text2,
            )

        def _dsk_rx_tx_text(rx, tx, unit):
            opts = {"received": rx, "transferred": tx, "units": unit}
            return _multi_color(
                _("%(received)d %(units)s read") % opts, _("%(transferred)d %(units)s write") % opts
            )

        def _net_rx_tx_text(rx, tx, unit):
            opts = {"received": rx, "transferred": tx, "units": unit}
            return _multi_color(
                _("%(received)d %(units)s in") % opts, _("%(transferred)d %(units)s out") % opts
            )

        cpu_txt = _("Disabled")
        mem_txt = _("Disabled")
        dsk_txt = _("Disabled")
        net_txt = _("Disabled")

        if self.config.get_stats_enable_cpu_poll():
            cpu_txt = "%d %%" % self.vm.guest_cpu_time_percentage()

        if self.config.get_stats_enable_memory_poll():
            cur_vm_memory = self.vm.stats_memory()
            vm_memory = self.vm.xmlobj.memory
            mem_txt = _("%(current-memory)s of %(total-memory)s") % {
                "current-memory": uiutil.pretty_mem(cur_vm_memory),
                "total-memory": uiutil.pretty_mem(vm_memory),
            }

        if self.config.get_stats_enable_disk_poll():
            dsk_txt = _dsk_rx_tx_text(self.vm.disk_read_rate(), self.vm.disk_write_rate(), "KiB/s")

        if self.config.get_stats_enable_net_poll():
            net_txt = _net_rx_tx_text(self.vm.network_rx_rate(), self.vm.network_tx_rate(), "KiB/s")

        self.widget("overview-cpu-usage-text").set_text(cpu_txt)
        self.widget("overview-memory-usage-text").set_text(mem_txt)
        self.widget("overview-network-traffic-text").set_markup(net_txt)
        self.widget("overview-disk-usage-text").set_markup(dsk_txt)

        self._graph_cpu.set_property("data_array", self.vm.guest_cpu_time_vector())
        self._graph_memory.set_property("data_array", self.vm.stats_memory_vector())

        d1, d2 = self.vm.disk_io_vectors()
        self._graph_disk.set_property("data_array", d1 + d2)

        n1, n2 = self.vm.network_traffic_vectors()
        self._graph_network.set_property("data_array", n1 + n2)

    def _cpu_secure_is_available(self):
        domcaps = self.vm.get_domain_capabilities()
        features = domcaps.get_cpu_security_features()
        return self.vm.get_xmlobj().os.is_x86() and len(features) > 0

    def _refresh_config_cpu(self):
        # Set topology first, because it impacts vcpus values
        cpu = self.vm.xmlobj.cpu
        show_top = cpu.has_topology()
        self.widget("cpu-topology-enable").set_active(show_top)

        sockets = cpu.topology.sockets or 1
        cores = cpu.topology.cores or 1
        threads = cpu.topology.threads or 1

        self.widget("cpu-sockets").set_value(sockets)
        self.widget("cpu-cores").set_value(cores)
        self.widget("cpu-threads").set_value(threads)
        if show_top:
            self.widget("cpu-topology-expander").set_expanded(True)

        host_active_count = self.vm.conn.host_active_processor_count()
        vcpus = self.vm.xmlobj.vcpus

        self.widget("cpu-vcpus").set_value(int(vcpus))
        self.widget("state-host-cpus").set_text(str(host_active_count))

        # Trigger this again to make sure vcpus is correct
        self._sync_cpu_topology_ui()

        # Warn about overcommit
        warn = bool(self._get_config_vcpus() > host_active_count)
        self.widget("cpu-vcpus-warn-box").set_visible(warn)

        # CPU model config
        model = cpu.model or None
        is_host = cpu.mode in ["host-model", "host-passthrough"]
        is_special_mode = cpu.mode in virtinst.DomainCpu.SPECIAL_MODES
        if not model and is_special_mode:
            model = cpu.mode

        if model:
            self.widget("cpu-model").get_child().set_text(model)
        else:
            uiutil.set_list_selection(
                self.widget("cpu-model"), virtinst.DomainCpu.SPECIAL_MODE_HV_DEFAULT, column=2
            )

        self.widget("cpu-copy-host").set_active(bool(is_host))
        text = _("Copy host CP_U configuration")
        if is_host:
            text += " (%s)" % cpu.mode
        self.widget("cpu-copy-host").set_label(text)
        self._cpu_copy_host_clicked_cb(self.widget("cpu-copy-host"))

        if not self._cpu_secure_is_available():
            self.widget("cpu-secure").set_sensitive(False)
            self.widget("cpu-secure").set_tooltip_text(
                "No security features to copy, the host is missing "
                "security patches or the host CPU is not vulnerable."
            )

        cpu.check_security_features(self.vm.get_xmlobj())
        self.widget("cpu-secure").set_active(cpu.secure)

    def _refresh_config_memory(self):
        host_mem_widget = self.widget("state-host-memory")
        host_mem = self.vm.conn.host_memory_size() // 1024
        vm_cur_mem = self.vm.xmlobj.currentMemory / 1024.0
        vm_max_mem = self.vm.xmlobj.memory / 1024.0

        host_mem_widget.set_text("%d MiB" % (int(round(host_mem))))

        curmem = self.widget("mem-memory")
        maxmem = self.widget("mem-maxmem")
        curmem.set_value(int(round(vm_cur_mem)))
        maxmem.set_value(int(round(vm_max_mem)))

        shared_mem, shared_mem_err = self.vm.has_shared_mem()
        self.widget("shared-memory").set_active(shared_mem)
        self.widget("shared-memory").set_sensitive(not bool(shared_mem_err))
        self.widget("shared-memory").set_tooltip_text(shared_mem_err)

    def _refresh_disk_page(self, disk):
        path = disk.get_source_path()
        devtype = disk.device
        bus = disk.bus

        size = "-"
        if path:
            size = _("Unknown")
            vol = self.conn.get_vol_by_path(path)
            if vol:
                size = vol.get_pretty_capacity()

        pretty_name = self._get_hw_row_label_for_device(disk)

        self.widget("disk-target-type").set_text(pretty_name)
        self.widget("disk-size").set_text(size)

        vmmAddHardware.populate_disk_bus_combo(
            self.vm, devtype, self.widget("disk-bus").get_model()
        )
        uiutil.set_list_selection(self.widget("disk-bus"), bus)
        self.widget("disk-bus-label").set_text(vmmAddHardware.disk_pretty_bus(bus) or "-")

        is_removable = disk.is_cdrom() or disk.is_floppy()
        self.widget("disk-source-box").set_visible(is_removable)
        self.widget("disk-source-label").set_visible(not is_removable)

        self.widget("disk-source-label").set_text(path or "-")
        if is_removable:
            self._mediacombo.reset_state(is_floppy=disk.is_floppy())
            self._mediacombo.set_path(path or "")

        self._addstorage.set_dev(disk)

    def _refresh_network_page(self, net):
        vmmAddHardware.populate_network_model_combo(self.vm, self.widget("network-model"))
        uiutil.set_list_selection(self.widget("network-model"), net.model)

        macaddr = net.macaddr or ""
        if self.widget("network-mac-label").is_visible():
            self.widget("network-mac-label").set_text(macaddr)
        else:
            self.widget("network-mac-entry").set_text(macaddr)

        state = net.link_state == "up" or net.link_state is None
        self.widget("network-link-state-checkbox").set_active(state)
        self._set_network_ip_details(net)

        self.netlist.set_dev(net)

    def _refresh_input_page(self, inp):
        dev = vmmAddHardware.input_pretty_name(inp.type, inp.bus)

        mode = None
        if inp.type == "tablet":
            mode = _("Absolute Movement")
        elif inp.type == "mouse":
            mode = _("Relative Movement")

        self.widget("input-dev-type").set_text(dev)
        self.widget("input-dev-mode").set_text(mode or "")
        uiutil.set_grid_row_visible(self.widget("input-dev-mode"), bool(mode))

        if (inp.type == "mouse" and inp.bus in ("xen", "ps2")) or (
            inp.type == "keyboard" and inp.bus in ("xen", "ps2")
        ):
            self._disable_device_remove(_("Hypervisor does not support removing this device"))

    def _refresh_graphics_page(self, gfx):
        pretty_type = vmmGraphicsDetails.graphics_pretty_type_simple(gfx.type)
        title = _("%(graphicstype)s Server") % {"graphicstype": pretty_type}
        self.gfxdetails.set_dev(gfx)
        self.widget("graphics-title").set_markup("<b>%s</b>" % title)

    def _refresh_sound_page(self, sound):
        uiutil.set_list_selection(self.widget("sound-model"), sound.model)

    def _refresh_smartcard_page(self, sc):
        uiutil.set_list_selection(self.widget("smartcard-mode"), sc.mode)

    def _refresh_redir_page(self, rd):
        address = None
        if rd.type == "tcp":
            address = "%s:%s" % (rd.source.host, rd.source.service)

        title = self._get_hw_row_label_for_device(rd)
        self.widget("redir-title").set_markup(title)
        self.widget("redir-type").set_text(vmmAddHardware.redirdev_pretty_type(rd.type))

        self.widget("redir-address").set_text(address or "")
        uiutil.set_grid_row_visible(self.widget("redir-address"), bool(address))

    def _refresh_tpm_page(self, tpmdev):
        self.tpmdetails.set_dev(tpmdev)

    def _refresh_panic_page(self, dev):
        self.widget("panic-model").set_text(dev.model or "")

    def _refresh_rng_page(self, dev):
        is_random = dev.backend_model == "random"
        uiutil.set_grid_row_visible(self.widget("rng-device"), is_random)

        self.widget("rng-type").set_text(vmmAddHardware.rng_pretty_type(dev.backend_model))
        self.widget("rng-device").set_text(dev.device or "")

    def _refresh_vsock_page(self, dev):
        self.vsockdetails.set_dev(dev)

    def _refresh_char_page(self, chardev):
        char_type = chardev.DEVICE_TYPE
        target_port = chardev.target_port
        dev_type = chardev.type or "pty"
        primary = self.vm.serial_is_console_dup(chardev)
        show_target_type = not (char_type in ["serial", "parallel"])
        is_qemuga = chardev.target_name == chardev.CHANNEL_NAME_QEMUGA
        show_clipboard = chardev.type == chardev.TYPE_QEMUVDAGENT

        if char_type == "serial":
            typelabel = _("Serial Device")
        elif char_type == "parallel":
            typelabel = _("Parallel Device")
        elif char_type == "console":
            typelabel = _("Console Device")
        elif char_type == "channel":
            typelabel = _("Channel Device")
        else:  # pragma: no cover
            typelabel = _("%s Device") % char_type.capitalize()

        if target_port is not None and chardev.DEVICE_TYPE == "console":
            typelabel += " %s" % (int(target_port) + 1)
        if target_port is not None and not show_target_type:
            typelabel += " %s" % (int(target_port) + 1)
        if primary:
            typelabel += " (%s)" % _("Primary Console")
        typelabel = "<b>%s</b>" % typelabel

        self.widget("char-type").set_markup(typelabel)
        self.widget("char-dev-type").set_text(dev_type)

        def show_ui(widgetname, val, doshow=None):
            if doshow is None:
                doshow = bool(val)
            uiutil.set_grid_row_visible(self.widget(widgetname), doshow)
            self.widget(widgetname).set_text(val or "-")

        def build_host_str(host, port):
            ret = ""
            if host:
                ret += host
            if port:
                ret += ":%s" % str(port)
            return ret

        connect_str = build_host_str(chardev.source.connect_host, chardev.source.connect_service)
        bind_str = build_host_str(chardev.source.bind_host, chardev.source.bind_service)
        target_type = show_target_type and chardev.target_type or None

        # Device type specific properties, only show if apply to the cur dev
        show_ui("char-source-host", connect_str)
        show_ui("char-bind-host", bind_str)
        show_ui("char-source-path", chardev.source.path)
        show_ui("char-target-type", target_type)
        show_ui("char-target-name", chardev.target_name)
        # Only show for the qemu guest agent, which we get async
        # notifications about connection state. For spice this UI field
        # can get out of date
        show_ui("char-target-state", chardev.target_state, doshow=is_qemuga)
        clipboard = _("On") if chardev.source.clipboard_copypaste else _("Off")
        show_ui("char-clipboard-sharing", clipboard, doshow=show_clipboard)

    def _refresh_hostdev_page(self, hostdev):
        rom_bar = hostdev.rom_bar
        if rom_bar is None:
            rom_bar = True

        devtype = hostdev.type
        if hostdev.type == "usb":
            devtype = "usb_device"

        nodedev = None
        for trydev in self.vm.conn.filter_nodedevs(devtype):
            if trydev.xmlobj.compare_to_hostdev(hostdev):
                nodedev = trydev

        pretty_name = None
        if nodedev:
            pretty_name = nodedev.pretty_name()
        if not pretty_name:
            pretty_name = vmmAddHardware.hostdev_pretty_name(hostdev)

        uiutil.set_grid_row_visible(self.widget("hostdev-rombar"), hostdev.type == "pci")
        uiutil.set_grid_row_visible(
            self.widget("hostdev-usb-startup-policy"), hostdev.type == "usb"
        )

        if hostdev.type == "usb":
            combo = self.widget("hostdev-usb-startup-policy")
            uiutil.set_list_selection(combo, hostdev.startup_policy)

        devlabel = "<b>" + _("Physical %s Device") % hostdev.type.upper() + "</b>"
        self.widget("hostdev-title").set_markup(devlabel)
        self.widget("hostdev-source").set_text(pretty_name)
        self.widget("hostdev-rombar").set_active(rom_bar)

    def _refresh_video_page(self, vid):
        model = vid.model
        uiutil.set_list_selection(self.widget("video-model"), model)

        if vid.accel3d is None:
            self.widget("video-3d").set_inconsistent(True)
        else:
            self.widget("video-3d").set_active(vid.accel3d)

        if self.vm.xmlobj.devices.graphics and len(self.vm.xmlobj.devices.video) <= 1:
            self._disable_device_remove(
                _("Cannot remove last video device while Graphics/Display is attached.")
            )

    def _refresh_watchdog_page(self, watch):
        model = watch.model
        action = watch.action

        uiutil.set_list_selection(self.widget("watchdog-model"), model)
        uiutil.set_list_selection(self.widget("watchdog-action"), action)

    def _refresh_controller_page(self, controller):
        uiutil.set_grid_row_visible(self.widget("device-list-label"), False)
        uiutil.set_grid_row_visible(self.widget("controller-device-box"), False)

        if self.vm.get_xmlobj().os.is_x86() and controller.type == "usb":
            self._disable_device_remove(_("Hypervisor does not support removing this device"))
        if controller.type == "pci":
            self._disable_device_remove(_("Hypervisor does not support removing this device"))
        elif controller.type in ["scsi", "sata", "ide", "fdc"]:
            model = self.widget("controller-device-list").get_model()
            model.clear()
            disks = controller.get_attached_devices(self.vm.xmlobj)
            for disk in disks:
                name = self._get_hw_row_label_for_device(disk)
                infoStr = _("%(device)s on %(address)s") % {
                    "device": name,
                    "address": disk.address.pretty_desc(),
                }
                model.append([infoStr])
                self._disable_device_remove(
                    _("Cannot remove controller while devices are attached.")
                )
            uiutil.set_grid_row_visible(self.widget("device-list-label"), True)
            uiutil.set_grid_row_visible(self.widget("controller-device-box"), True)

        elif controller.type == "virtio-serial":
            devs = controller.get_attached_devices(self.vm.xmlobj)
            if devs:
                self._disable_device_remove(
                    _("Cannot remove controller while devices are attached.")
                )

        type_label = vmmAddHardware.controller_pretty_desc(controller)
        self.widget("controller-type").set_text(type_label)

        combo = self.widget("controller-model")
        vmmAddHardware.populate_controller_model_combo(combo, controller.type)
        show_model = controller.model or len(combo.get_model()) > 1
        if controller.type == "pci":
            show_model = False
        uiutil.set_grid_row_visible(combo, show_model)

        model = controller.model
        if controller.type == "usb" and "xhci" in str(model):
            model = "usb3"
        uiutil.set_list_selection(self.widget("controller-model"), model)

    def _refresh_filesystem_page(self, dev):
        self.fsDetails.set_dev(dev)

    def _refresh_boot_page(self):
        # Refresh autostart
        try:
            # Older libvirt versions return None if not supported
            autoval = self.vm.get_autostart()
        except libvirt.libvirtError:  # pragma: no cover
            autoval = None

        # Autostart
        autostart_chk = self.widget("boot-autostart")
        enable_autostart = autoval is not None
        autostart_chk.set_sensitive(enable_autostart)
        autostart_chk.set_active(enable_autostart and autoval or False)

        show_kernel = not self.vm.is_container()
        show_init = self.vm.is_container()
        show_boot = not self.vm.is_container() and not self.vm.is_xenpv()

        uiutil.set_grid_row_visible(self.widget("boot-order-frame"), show_boot)
        uiutil.set_grid_row_visible(self.widget("boot-kernel-expander"), show_kernel)
        uiutil.set_grid_row_visible(self.widget("boot-init-frame"), show_init)

        # Kernel/initrd boot
        kernel, initrd, dtb, args = self.vm.get_boot_kernel_info()
        expand = bool(kernel or dtb or initrd or args)

        def keep_text(wname, guestval):
            # If the user unsets kernel/initrd by unchecking the
            # 'enable kernel boot' box, we keep the previous values cached
            # in the text fields to allow easy switching back and forth.
            guestval = guestval or ""
            if self._get_text(wname) and not guestval:
                return
            self.widget(wname).set_text(guestval)

        keep_text("boot-kernel", kernel)
        keep_text("boot-initrd", initrd)
        keep_text("boot-dtb", dtb)
        keep_text("boot-kernel-args", args)
        if expand:
            # Only 'expand' if requested, so a refresh doesn't
            # magically unexpand the UI the user just touched
            self.widget("boot-kernel-expander").set_expanded(True)
        self.widget("boot-kernel-enable").set_active(expand)
        self.widget("boot-kernel-enable").toggled()

        # Only show dtb if it's supported
        arch = self.vm.get_arch() or ""
        show_dtb = (
            self._get_text("boot-dtb")
            or self.vm.get_hv_type() == "test"
            or "arm" in arch
            or "microblaze" in arch
            or "ppc" in arch
        )
        self.widget("boot-dtb-label").set_visible(show_dtb)
        self.widget("boot-dtb-box").set_visible(show_dtb)

        # <init> populate
        init, initargs = self.vm.get_init()
        self.widget("boot-init-path").set_text(init or "")
        self.widget("boot-init-args").set_text(initargs or "")

        # Boot menu populate
        menu = self.vm.get_boot_menu() or False
        self.widget("boot-menu").set_active(menu)
        self._refresh_boot_order()

    def _make_boot_rows(self):
        if not self.vm.can_use_device_boot_order():
            return [
                ["hd", _("Hard Disk"), "drive-harddisk", False, True],
                ["cdrom", _("CDROM"), "media-optical", False, True],
                ["network", _("Network (PXE)"), "network-idle", False, True],
                ["fd", _("Floppy"), "media-floppy", False, True],
            ]

        ret = []
        for dev in self.vm.get_bootable_devices():
            row = self._get_hw_row_for_device(dev)
            if not row:
                continue  # pragma: no cover
            label = row[HW_LIST_COL_LABEL]
            icon = row[HW_LIST_COL_ICON_NAME]

            ret.append([dev.get_xml_id(), label, icon, False, True])

        if not ret:
            ret.append([None, _("No bootable devices"), None, False, False])
        return ret

    def _refresh_boot_order(self):
        boot_list = self.widget("boot-list")
        boot_model = boot_list.get_model()
        boot_model.clear()
        boot_rows = self._make_boot_rows()
        boot_order = self.vm.get_boot_order()

        for key in boot_order:
            for row in boot_rows[:]:
                if key != row[BOOT_KEY]:
                    continue

                row[BOOT_ACTIVE] = True
                boot_model.append(row)
                boot_rows.remove(row)
                break

        for row in boot_rows:
            boot_model.append(row)

    ############################
    # Hardware list population #
    ############################

    def _make_hw_list_entry(self, title, page_id, icon_name, devobj=None):
        hw_entry = []
        hw_entry.insert(HW_LIST_COL_LABEL, title)
        hw_entry.insert(HW_LIST_COL_ICON_NAME, icon_name)
        hw_entry.insert(HW_LIST_COL_TYPE, page_id)
        hw_entry.insert(HW_LIST_COL_DEVICE, devobj)
        hw_entry.insert(HW_LIST_COL_KEY, devobj or title)
        return hw_entry

    def _init_hw_list(self):
        """
        Add the static entries to the hw list, like Overview
        """
        hw_list_model = self.widget("hw-list").get_model()
        hw_list_model.clear()

        def add_hw_list_option(*args, **kwargs):
            hw_list_model.append(self._make_hw_list_entry(*args, **kwargs))

        add_hw_list_option(_("Overview"), HW_LIST_TYPE_GENERAL, "computer")
        add_hw_list_option(_("OS information"), HW_LIST_TYPE_OS, "computer")
        if not self.is_customize_dialog:
            add_hw_list_option(_("Performance"), HW_LIST_TYPE_STATS, _get_performance_icon_name())
        add_hw_list_option(_("CPUs"), HW_LIST_TYPE_CPU, "device_cpu")
        add_hw_list_option(_("Memory"), HW_LIST_TYPE_MEMORY, "device_mem")
        add_hw_list_option(_("Boot Options"), HW_LIST_TYPE_BOOT, "system-run")

        self._repopulate_hw_list()
        self._set_hw_selection(0)

    def _repopulate_hw_list(self):
        """
        Refresh the hardware list entries with the latest VM config
        """
        hw_list = self.widget("hw-list")
        hw_list_model = hw_list.get_model()

        currentDevices = []

        def dev_cmp(origdev, newdev):
            if not origdev:
                return False

            if origdev == newdev:
                return True

            return origdev.get_xml_id() == newdev.get_xml_id()

        def update_hwlist(hwtype, dev, disk_bus_index=None):
            """
            See if passed hw is already in list, and if so, update info.
            If not in list, add it!
            """
            label = _label_for_device(dev, disk_bus_index)
            icon = _icon_for_device(dev)

            currentDevices.append(dev)

            insertAt = 0
            for row in hw_list_model:
                rowdev = row[HW_LIST_COL_DEVICE]
                if dev_cmp(rowdev, dev):
                    # Update existing HW info
                    row[HW_LIST_COL_DEVICE] = dev
                    row[HW_LIST_COL_LABEL] = label
                    row[HW_LIST_COL_ICON_NAME] = icon
                    return

                if row[HW_LIST_COL_TYPE] <= hwtype:
                    insertAt += 1

            # Add the new HW row
            hw_entry = self._make_hw_list_entry(label, hwtype, icon, dev)
            hw_list_model.insert(insertAt, hw_entry)

        consoles = self.vm.xmlobj.devices.console
        serials = self.vm.xmlobj.devices.serial
        if serials and consoles and self.vm.serial_is_console_dup(serials[0]):
            consoles.pop(0)

        disks = self.vm.xmlobj.devices.disk
        for dev, _disk_bus_index in _calculate_disk_bus_index(disks):
            update_hwlist(HW_LIST_TYPE_DISK, dev, _disk_bus_index)
        for dev in self.vm.xmlobj.devices.interface:
            update_hwlist(HW_LIST_TYPE_NIC, dev)
        for dev in self.vm.xmlobj.devices.input:
            update_hwlist(HW_LIST_TYPE_INPUT, dev)
        for dev in self.vm.xmlobj.devices.graphics:
            update_hwlist(HW_LIST_TYPE_GRAPHICS, dev)
        for dev in self.vm.xmlobj.devices.sound:
            update_hwlist(HW_LIST_TYPE_SOUND, dev)
        for dev in serials:
            update_hwlist(HW_LIST_TYPE_CHAR, dev)
        for dev in self.vm.xmlobj.devices.parallel:
            update_hwlist(HW_LIST_TYPE_CHAR, dev)
        for dev in consoles:
            update_hwlist(HW_LIST_TYPE_CHAR, dev)
        for dev in self.vm.xmlobj.devices.channel:
            update_hwlist(HW_LIST_TYPE_CHAR, dev)
        for dev in self.vm.xmlobj.devices.hostdev:
            update_hwlist(HW_LIST_TYPE_HOSTDEV, dev)
        for dev in self.vm.xmlobj.devices.redirdev:
            update_hwlist(HW_LIST_TYPE_REDIRDEV, dev)
        for dev in self.vm.xmlobj.devices.video:
            update_hwlist(HW_LIST_TYPE_VIDEO, dev)
        for dev in self.vm.xmlobj.devices.watchdog:
            update_hwlist(HW_LIST_TYPE_WATCHDOG, dev)

        for dev in self.vm.xmlobj.devices.controller:
            # skip USB2 ICH9 companion controllers
            if dev.model in ["ich9-uhci1", "ich9-uhci2", "ich9-uhci3"]:
                continue

            # These are all parts of a default PCIe setup, which we
            # condense down to one listing
            if dev.model in ["pcie-root-port", "dmi-to-pci-bridge", "pci-bridge"]:
                continue

            update_hwlist(HW_LIST_TYPE_CONTROLLER, dev)

        for dev in self.vm.xmlobj.devices.filesystem:
            update_hwlist(HW_LIST_TYPE_FILESYSTEM, dev)
        for dev in self.vm.xmlobj.devices.smartcard:
            update_hwlist(HW_LIST_TYPE_SMARTCARD, dev)
        for dev in self.vm.xmlobj.devices.tpm:
            update_hwlist(HW_LIST_TYPE_TPM, dev)
        for dev in self.vm.xmlobj.devices.rng:
            update_hwlist(HW_LIST_TYPE_RNG, dev)
        for dev in self.vm.xmlobj.devices.panic:
            update_hwlist(HW_LIST_TYPE_PANIC, dev)
        for dev in self.vm.xmlobj.devices.vsock:
            update_hwlist(HW_LIST_TYPE_VSOCK, dev)

        devs = list(range(len(hw_list_model)))
        devs.reverse()
        for i in devs:
            _iter = hw_list_model.iter_nth_child(None, i)
            olddev = hw_list_model[i][HW_LIST_COL_DEVICE]

            # Existing device, don't remove it
            if not olddev or olddev in currentDevices:
                continue

            hw_list_model.remove(_iter)

    ################
    # UI listeners #
    ################

    def _config_apply_clicked_cb(self, src):
        self._config_apply()

    def _config_cancel_clicked_cb(self, src):
        self._config_cancel()

    def _config_remove_clicked_cb(self, src):
        self._config_remove()

    def _refresh_ip_clicked_cb(self, src):
        self._refresh_ip()

    def _browse_kernel_clicked_cb(self, src):
        def cb(ignore, path):
            self.widget("boot-kernel").set_text(path)

        self._browse_file(cb)

    def _browse_initrd_clicked_cb(self, src):
        def cb(ignore, path):
            self.widget("boot-initrd").set_text(path)

        self._browse_file(cb)

    def _browse_dtb_clicked_cb(self, src):
        def cb(ignore, path):
            self.widget("boot-dtb").set_text(path)

        self._browse_file(cb)

    def _xmleditor_xml_requested_cb(self, src):
        self._refresh_page()

    def _xmleditor_xml_reset_cb(self, src):
        self._refresh_page()

    def _addhw_clicked_cb(self, src):
        self._show_addhw()

    def _boot_kernel_toggled_cb(self, src):
        self.widget("boot-kernel-box").set_sensitive(src.get_active())
        self._enable_apply(EDIT_KERNEL)

    def _boot_list_changed_cb(self, src):
        self._config_bootdev_selected()

    def _boot_moveup_clicked_cb(self, src):
        self._config_boot_move(True)

    def _boot_movedown_clicked_cb(self, src):
        self._config_boot_move(False)

    def _vm_inspection_changed_cb(self, vm):
        row = self._get_hw_row()
        if row and row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_OS:
            self._refresh_os_page()

#
# Copyright (C) 2006-2008, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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

from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk

import libvirt

import virtinst
from virtinst import util
from virtinst import VirtualRNGDevice

from . import vmmenu
from . import uiutil
from .baseclass import vmmGObjectUI
from .addhardware import vmmAddHardware
from .choosecd import vmmChooseCD
from .fsdetails import vmmFSDetails
from .gfxdetails import vmmGraphicsDetails
from .netlist import vmmNetworkList
from .snapshots import vmmSnapshotPage
from .storagebrowse import vmmStorageBrowser
from .graphwidgets import Sparkline


# Parameters that can be edited in the details window
(EDIT_NAME,
 EDIT_TITLE,
 EDIT_MACHTYPE,
 EDIT_FIRMWARE,
 EDIT_DESC,
 EDIT_IDMAP,

 EDIT_VCPUS,
 EDIT_MAXVCPUS,
 EDIT_CPU,
 EDIT_TOPOLOGY,

 EDIT_MEM,

 EDIT_AUTOSTART,
 EDIT_BOOTORDER,
 EDIT_BOOTMENU,
 EDIT_KERNEL,
 EDIT_INIT,

 EDIT_DISK_RO,
 EDIT_DISK_SHARE,
 EDIT_DISK_REMOVABLE,
 EDIT_DISK_CACHE,
 EDIT_DISK_IO,
 EDIT_DISK_BUS,
 EDIT_DISK_SERIAL,
 EDIT_DISK_FORMAT,
 EDIT_DISK_SGIO,

 EDIT_SOUND_MODEL,

 EDIT_SMARTCARD_MODE,

 EDIT_NET_MODEL,
 EDIT_NET_VPORT,
 EDIT_NET_SOURCE,
 EDIT_NET_MAC,

 EDIT_GFX_PASSWD,
 EDIT_GFX_TYPE,
 EDIT_GFX_KEYMAP,
 EDIT_GFX_LISTEN,
 EDIT_GFX_ADDRESS,
 EDIT_GFX_TLSPORT,
 EDIT_GFX_PORT,
 EDIT_GFX_OPENGL,
 EDIT_GFX_RENDERNODE,

 EDIT_VIDEO_MODEL,
 EDIT_VIDEO_3D,

 EDIT_WATCHDOG_MODEL,
 EDIT_WATCHDOG_ACTION,

 EDIT_CONTROLLER_MODEL,

 EDIT_TPM_TYPE,

 EDIT_FS,

 EDIT_HOSTDEV_ROMBAR) = range(1, 49)


# Columns in hw list model
(HW_LIST_COL_LABEL,
 HW_LIST_COL_ICON_NAME,
 HW_LIST_COL_ICON_SIZE,
 HW_LIST_COL_TYPE,
 HW_LIST_COL_DEVICE) = range(5)

# Types for the hw list model: numbers specify what order they will be listed
(HW_LIST_TYPE_GENERAL,
 HW_LIST_TYPE_INSPECTION,
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
 HW_LIST_TYPE_PANIC) = range(22)

remove_pages = [HW_LIST_TYPE_NIC, HW_LIST_TYPE_INPUT,
                HW_LIST_TYPE_GRAPHICS, HW_LIST_TYPE_SOUND, HW_LIST_TYPE_CHAR,
                HW_LIST_TYPE_HOSTDEV, HW_LIST_TYPE_DISK, HW_LIST_TYPE_VIDEO,
                HW_LIST_TYPE_WATCHDOG, HW_LIST_TYPE_CONTROLLER,
                HW_LIST_TYPE_FILESYSTEM, HW_LIST_TYPE_SMARTCARD,
                HW_LIST_TYPE_REDIRDEV, HW_LIST_TYPE_TPM,
                HW_LIST_TYPE_RNG, HW_LIST_TYPE_PANIC]

# Boot device columns
(BOOT_KEY,
 BOOT_LABEL,
 BOOT_ICON,
 BOOT_ACTIVE,
 BOOT_CAN_SELECT) = range(5)

# Main tab pages
(DETAILS_PAGE_DETAILS,
 DETAILS_PAGE_CONSOLE,
 DETAILS_PAGE_SNAPSHOTS) = range(3)

_remove_tooltip = _("Remove this device from the virtual machine")


def _label_for_device(dev):
    devtype = dev.virtual_device_type

    if devtype == "disk":
        busstr = virtinst.VirtualDisk.pretty_disk_bus(dev.bus) or ""

        if dev.device == "floppy":
            devstr = _("Floppy")
            busstr = ""
        elif dev.device == "cdrom":
            devstr = _("CDROM")
        elif dev.device == "disk":
            devstr = _("Disk")
        else:
            devstr = dev.device.capitalize()

        if busstr:
            ret = "%s %s" % (busstr, devstr)
        else:
            ret = devstr

        return "%s %s" % (ret, dev.disk_bus_index)

    if devtype == "interface":
        if dev.macaddr:
            return "NIC %s" % dev.macaddr[-9:]
        else:
            return "NIC"

    if devtype == "input":
        if dev.type == "tablet":
            return _("Tablet")
        elif dev.type == "mouse":
            return _("Mouse")
        elif dev.type == "keyboard":
            return _("Keyboard")
        return _("Input")

    if devtype in ["serial", "parallel", "console"]:
        if devtype == "serial":
            label = _("Serial")
        elif devtype == "parallel":
            label = _("Parallel")
        elif devtype == "console":
            label = _("Console")
        if dev.target_port is not None:
            label += " %s" % (int(dev.target_port) + 1)
        return label

    if devtype == "channel":
        label = _("Channel")
        name = dev.pretty_channel_name(dev.target_name)
        if not name:
            name = dev.pretty_type(dev.type)
        if name:
            label += " %s" % name
        return label

    if devtype == "graphics":
        return _("Display %s") % dev.pretty_type_simple(dev.type)
    if devtype == "redirdev":
        return _("%s Redirector %s") % (dev.bus.upper(), dev.vmmindex + 1)
    if devtype == "hostdev":
        return dev.pretty_name()
    if devtype == "sound":
        return _("Sound: %s") % dev.model
    if devtype == "video":
        return _("Video %s") % dev.pretty_model(dev.model)
    if devtype == "filesystem":
        return _("Filesystem %s") % dev.target[:8]
    if devtype == "controller":
        return _("Controller %s") % dev.pretty_desc()
    if devtype == "rng":
        label = _("RNG")
        if dev.device:
            label += (" %s" % dev.device)
        return label
    if devtype == "tpm":
        label = _("TPM")
        if dev.device_path:
            label += (" %s" % dev.device_path)
        return label

    devmap = {
        "panic": _("Panic Notifier"),
        "smartcard": _("Smartcard"),
        "watchdog": _("Watchdog"),
    }
    return devmap[devtype]


def _icon_for_device(dev):
    devtype = dev.virtual_device_type

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
        if dev.bus == "usb":
            return "device_usb"
        return "device_pci"

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
    }
    return typemap[devtype]


def _chipset_label_from_machine(machine):
    if machine and "q35" in machine:
        return "Q35"
    return "i440FX"


def _warn_cpu_thread_topo(threads, cpu_model):
    if (threads < 2):
        return False

    non_ht_cpus = ["athlon", "phenom", "opteron"]

    for cpu in non_ht_cpus:
        if (cpu in cpu_model.lower()):
            return True

    return False


def _label_for_os_type(os_type):
    typemap = {
        "dos": _("MS-DOS/FreeDOS"),
        "freebsd": _("FreeBSD"),
        "hurd": _("GNU/Hurd"),
        "linux": _("Linux"),
        "minix": _("MINIX"),
        "netbsd": _("NetBSD"),
        "openbsd": _("OpenBSD"),
        "windows": _("Microsoft Windows"),
    }
    try:
        return typemap[os_type]
    except KeyError:
        return _("unknown")


class vmmDetails(vmmGObjectUI):
    __gsignals__ = {
        "action-save-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-destroy-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-suspend-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-resume-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-run-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-shutdown-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-reset-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-reboot-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-exit-app": (GObject.SignalFlags.RUN_FIRST, None, []),
        "action-view-manager": (GObject.SignalFlags.RUN_FIRST, None, []),
        "action-migrate-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-delete-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-clone-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "details-closed": (GObject.SignalFlags.RUN_FIRST, None, []),
        "details-opened": (GObject.SignalFlags.RUN_FIRST, None, []),
        "customize-finished": (GObject.SignalFlags.RUN_FIRST, None, []),
        "inspection-refresh": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
    }

    def __init__(self, vm, parent=None):
        vmmGObjectUI.__init__(self, "details.ui", "vmm-details")
        self.vm = vm
        self.conn = self.vm.conn

        self.is_customize_dialog = False
        if parent:
            # Details window is being abused as a 'configure before install'
            # dialog, set things as appropriate
            self.is_customize_dialog = True
            self.topwin.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            self.topwin.set_transient_for(parent)

            self.widget("toolbar-box").show()
            self.widget("customize-toolbar").show()
            self.widget("details-toolbar").hide()
            self.widget("details-menubar").hide()
            pages = self.widget("details-pages")
            pages.set_current_page(DETAILS_PAGE_DETAILS)


        self.active_edits = []

        self.addhw = None
        self.media_choosers = {"cdrom": None, "floppy": None}
        self.storage_browser = None

        self.ignoreDetails = False

        from .console import vmmConsolePages
        self.console = vmmConsolePages(self.vm, self.builder, self.topwin)
        self.snapshots = vmmSnapshotPage(self.vm, self.builder, self.topwin)
        self.widget("snapshot-placeholder").add(self.snapshots.top_box)

        self.fsDetails = vmmFSDetails(self.vm, self.builder, self.topwin)
        self.widget("fs-alignment").add(self.fsDetails.top_box)
        self.fsDetails.connect("changed",
                               lambda *x: self.enable_apply(x, EDIT_FS))

        self.gfxdetails = vmmGraphicsDetails(
            self.vm, self.builder, self.topwin)
        self.widget("graphics-align").add(self.gfxdetails.top_box)
        self.gfxdetails.connect("changed-type",
            lambda *x: self.enable_apply(x, EDIT_GFX_TYPE))
        self.gfxdetails.connect("changed-port",
            lambda *x: self.enable_apply(x, EDIT_GFX_PORT))
        self.gfxdetails.connect("changed-opengl",
            lambda *x: self.enable_apply(x, EDIT_GFX_OPENGL))
        self.gfxdetails.connect("changed-rendernode",
            lambda *x: self.enable_apply(x, EDIT_GFX_RENDERNODE))
        self.gfxdetails.connect("changed-tlsport",
            lambda *x: self.enable_apply(x, EDIT_GFX_TLSPORT))
        self.gfxdetails.connect("changed-listen",
            lambda *x: self.enable_apply(x, EDIT_GFX_LISTEN))
        self.gfxdetails.connect("changed-address",
            lambda *x: self.enable_apply(x, EDIT_GFX_ADDRESS))
        self.gfxdetails.connect("changed-keymap",
            lambda *x: self.enable_apply(x, EDIT_GFX_KEYMAP))
        self.gfxdetails.connect("changed-password",
            lambda *x: self.enable_apply(x, EDIT_GFX_PASSWD))

        self.netlist = vmmNetworkList(self.conn, self.builder, self.topwin)
        self.widget("network-source-label-align").add(self.netlist.top_label)
        self.widget("network-source-ui-align").add(self.netlist.top_box)
        self.widget("network-vport-align").add(self.netlist.top_vport)
        self.netlist.connect("changed",
            lambda x: self.enable_apply(x, EDIT_NET_SOURCE))
        self.netlist.connect("changed-vport",
            lambda x: self.enable_apply(x, EDIT_NET_VPORT))

        # Set default window size
        w, h = self.vm.get_details_window_size()
        if w <= 0:
            w = 800
        if h <= 0:
            h = 600
        self.topwin.set_default_size(w, h)
        self._window_size = None

        self.oldhwkey = None
        self.addhwmenu = None
        self._addhwmenuitems = None
        self.keycombo_menu = None
        self.init_menus()
        self.init_details()

        self.cpu_usage_graph = None
        self.memory_usage_graph = None
        self.disk_io_graph = None
        self.network_traffic_graph = None
        self.init_graphs()

        self.builder.connect_signals({
            "on_close_details_clicked": self.close,
            "on_details_menu_close_activate": self.close,
            "on_vmm_details_delete_event": self._window_delete_event,
            "on_vmm_details_configure_event": self.window_resized,
            "on_details_menu_quit_activate": self.exit_app,
            "on_hw_list_changed": self.hw_changed,

            "on_control_vm_details_toggled": self.details_console_changed,
            "on_control_vm_console_toggled": self.details_console_changed,
            "on_control_snapshots_toggled": self.details_console_changed,
            "on_control_run_clicked": self.control_vm_run,
            "on_control_shutdown_clicked": self.control_vm_shutdown,
            "on_control_pause_toggled": self.control_vm_pause,
            "on_control_fullscreen_toggled": self.control_fullscreen,

            "on_details_customize_finish_clicked": self.customize_finish,
            "on_details_cancel_customize_clicked": self._customize_cancel_clicked,

            "on_details_menu_virtual_manager_activate": self.control_vm_menu,
            "on_details_menu_run_activate": self.control_vm_run,
            "on_details_menu_poweroff_activate": self.control_vm_shutdown,
            "on_details_menu_reboot_activate": self.control_vm_reboot,
            "on_details_menu_save_activate": self.control_vm_save,
            "on_details_menu_reset_activate": self.control_vm_reset,
            "on_details_menu_destroy_activate": self.control_vm_destroy,
            "on_details_menu_pause_activate": self.control_vm_pause,
            "on_details_menu_clone_activate": self.control_vm_clone,
            "on_details_menu_migrate_activate": self.control_vm_migrate,
            "on_details_menu_delete_activate": self.control_vm_delete,
            "on_details_menu_screenshot_activate": self.control_vm_screenshot,
            "on_details_menu_usb_redirection": self.control_vm_usb_redirection,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,
            "on_details_menu_view_manager_activate": self.view_manager,
            "on_details_menu_view_details_toggled": self.details_console_changed,
            "on_details_menu_view_console_toggled": self.details_console_changed,
            "on_details_menu_view_snapshots_toggled": self.details_console_changed,

            "on_details_pages_switch_page": self.switch_page,

            "on_overview_name_changed": lambda *x: self.enable_apply(x, EDIT_NAME),
            "on_overview_title_changed": lambda *x: self.enable_apply(x, EDIT_TITLE),
            "on_machine_type_changed": lambda *x: self.enable_apply(x, EDIT_MACHTYPE),
            "on_overview_firmware_changed": lambda *x: self.enable_apply(x, EDIT_FIRMWARE),
            "on_overview_chipset_changed": lambda *x: self.enable_apply(x, EDIT_MACHTYPE),
            "on_idmap_uid_target_changed": lambda *x: self.enable_apply(x, EDIT_IDMAP),
            "on_idmap_uid_count_changed": lambda *x: self.enable_apply(x, EDIT_IDMAP),
            "on_idmap_gid_target_changed": lambda *x: self.enable_apply(x, EDIT_IDMAP),
            "on_idmap_gid_count_changed": lambda *x: self.enable_apply(x, EDIT_IDMAP),
            "on_idmap_check_toggled": self.config_idmap_enable,

            "on_details_inspection_refresh_clicked": self.inspection_refresh,

            "on_cpu_vcpus_changed": self.config_vcpus_changed,
            "on_cpu_maxvcpus_changed": self.config_maxvcpus_changed,
            "on_cpu_model_changed": lambda *x: self.config_cpu_model_changed(x),
            "on_cpu_copy_host_clicked": self.on_cpu_copy_host_clicked,
            "on_cpu_cores_changed": self.config_cpu_topology_changed,
            "on_cpu_sockets_changed": self.config_cpu_topology_changed,
            "on_cpu_threads_changed": self.config_cpu_topology_changed,
            "on_cpu_topology_enable_toggled": self.config_cpu_topology_enable,

            "on_mem_memory_changed": self.config_memory_changed,
            "on_mem_maxmem_changed": self.config_maxmem_changed,


            "on_boot_list_changed": self.config_bootdev_selected,
            "on_boot_moveup_clicked": lambda *x: self.config_boot_move(x, True),
            "on_boot_movedown_clicked": lambda *x: self.config_boot_move(x, False),
            "on_boot_autostart_changed": lambda *x: self.enable_apply(x, x, EDIT_AUTOSTART),
            "on_boot_menu_changed": lambda *x: self.enable_apply(x, EDIT_BOOTMENU),
            "on_boot_kernel_enable_toggled": self.boot_kernel_toggled,
            "on_boot_kernel_changed": lambda *x: self.enable_apply(x, EDIT_KERNEL),
            "on_boot_initrd_changed": lambda *x: self.enable_apply(x, EDIT_KERNEL),
            "on_boot_dtb_changed": lambda *x: self.enable_apply(x, EDIT_KERNEL),
            "on_boot_kernel_args_changed": lambda *x: self.enable_apply(x, EDIT_KERNEL),
            "on_boot_kernel_browse_clicked": self.browse_kernel,
            "on_boot_initrd_browse_clicked": self.browse_initrd,
            "on_boot_dtb_browse_clicked": self.browse_dtb,
            "on_boot_init_path_changed": lambda *x: self.enable_apply(x, EDIT_INIT),
            "on_boot_init_args_changed": lambda *x: self.enable_apply(x, EDIT_INIT),

            "on_disk_cdrom_connect_clicked": self.toggle_storage_media,
            "on_disk_readonly_changed": lambda *x: self.enable_apply(x, EDIT_DISK_RO),
            "on_disk_shareable_changed": lambda *x: self.enable_apply(x, EDIT_DISK_SHARE),
            "on_disk_removable_changed": lambda *x: self.enable_apply(x, EDIT_DISK_REMOVABLE),
            "on_disk_cache_combo_changed": lambda *x: self.enable_apply(x, EDIT_DISK_CACHE),
            "on_disk_io_combo_changed": lambda *x: self.enable_apply(x, EDIT_DISK_IO),
            "on_disk_bus_combo_changed": lambda *x: self.enable_apply(x, EDIT_DISK_BUS),
            "on_disk_format_changed": self.disk_format_changed,
            "on_disk_serial_changed": lambda *x: self.enable_apply(x, EDIT_DISK_SERIAL),
            "on_disk_sgio_entry_changed": lambda *x: self.enable_apply(x, EDIT_DISK_SGIO),

            "on_network_model_combo_changed": lambda *x: self.enable_apply(x, EDIT_NET_MODEL),
            "on_network_mac_entry_changed": lambda *x: self.enable_apply(x,
                EDIT_NET_MAC),

            "on_sound_model_combo_changed": lambda *x: self.enable_apply(x,
                                             EDIT_SOUND_MODEL),

            "on_video_model_combo_changed": self.video_model_changed,
            "on_video_3d_toggled": self.video_3d_toggled,

            "on_watchdog_model_combo_changed": lambda *x: self.enable_apply(x,
                                                EDIT_WATCHDOG_MODEL),
            "on_watchdog_action_combo_changed": lambda *x: self.enable_apply(x,
                                                 EDIT_WATCHDOG_ACTION),

            "on_smartcard_mode_combo_changed": lambda *x: self.enable_apply(x,
                                                EDIT_SMARTCARD_MODE),

            "on_hostdev_rombar_toggled": lambda *x: self.enable_apply(
                x, EDIT_HOSTDEV_ROMBAR),
            "on_controller_model_combo_changed": (lambda *x:
                self.enable_apply(x, EDIT_CONTROLLER_MODEL)),

            "on_config_apply_clicked": self.config_apply,
            "on_config_cancel_clicked": self.config_cancel,

            "on_config_remove_clicked": self.remove_xml_dev,
            "on_add_hardware_button_clicked": self.add_hardware,

            "on_hw_list_button_press_event": self.popup_addhw_menu,

            # Listeners stored in vmmConsolePages
            "on_details_menu_view_fullscreen_activate": (
                self.console.details_toggle_fullscreen),
            "on_details_menu_view_size_to_vm_activate": (
                self.console.details_size_to_vm),
            "on_details_menu_view_scale_always_toggled": (
                self.console.details_scaling_ui_changed_cb),
            "on_details_menu_view_scale_fullscreen_toggled": (
                self.console.details_scaling_ui_changed_cb),
            "on_details_menu_view_scale_never_toggled": (
                self.console.details_scaling_ui_changed_cb),
            "on_details_menu_view_resizeguest_toggled": (
                self.console.details_resizeguest_ui_changed_cb),

            "on_console_pages_switch_page": (
                self.console.details_page_changed),
            "on_console_auth_password_activate": (
                self.console.details_auth_login),
            "on_console_auth_login_clicked": (
                self.console.details_auth_login),
        })

        # Deliberately keep all this after signal connection
        self.vm.connect("state-changed", self.refresh_vm_state)
        self.vm.connect("resources-sampled", self.refresh_resources)
        self.vm.connect("inspection-changed", lambda *x: self.refresh_inspection_page())

        self.populate_hw_list()

        self.hw_selected()
        self.refresh_vm_state()

    def _cleanup(self):
        self.oldhwkey = None

        if self.addhw:
            self.addhw.cleanup()
            self.addhw = None

        if self.storage_browser:
            self.storage_browser.cleanup()
            self.storage_browser = None

        for key in self.media_choosers:
            if self.media_choosers[key]:
                self.media_choosers[key].cleanup()
        self.media_choosers = {}

        self.console.cleanup()
        self.console = None
        self.snapshots.cleanup()
        self.snapshots = None

        if self._window_size:
            self.vm.set_details_window_size(*self._window_size)

        self.vm = None
        self.conn = None
        self.addhwmenu = None
        self._addhwmenuitems = None

        self.gfxdetails.cleanup()
        self.gfxdetails = None
        self.fsDetails.cleanup()
        self.fsDetails = None
        self.netlist.cleanup()
        self.netlist = None

    def show(self):
        logging.debug("Showing VM details: %s", self.vm)
        vis = self.is_visible()
        self.topwin.present()
        if vis:
            return

        self.emit("details-opened")
        self.refresh_vm_state()

    def customize_finish(self, src):
        ignore = src
        if self.has_unapplied_changes(self.get_hw_row()):
            return
        self.emit("customize-finished")

    def _customize_cancel(self):
        logging.debug("Asking to cancel customization")

        result = self.err.yes_no(
            _("This will abort the installation. Are you sure?"))
        if not result:
            logging.debug("Customize cancel aborted")
            return

        logging.debug("Canceling customization")
        return self._close()

    def _customize_cancel_clicked(self, src):
        ignore = src
        return self._customize_cancel()

    def _window_delete_event(self, ignore1=None, ignore2=None):
        return self.close()

    def close(self, ignore1=None, ignore2=None):
        if self.is_visible():
            logging.debug("Closing VM details: %s", self.vm)
        return self._close()

    def _close(self):
        fs = self.widget("details-menu-view-fullscreen")
        if fs.get_active():
            fs.set_active(False)

        if not self.is_visible():
            return

        self.topwin.hide()
        if self.console.details_viewer_is_visible():
            try:
                self.console.details_close_viewer()
            except Exception:
                logging.error("Failure when disconnecting from desktop server")

        self.emit("details-closed")
        return 1

    def is_visible(self):
        return bool(self.topwin.get_visible())


    ##########################
    # Initialization helpers #
    ##########################

    def init_menus(self):
        # Virtual Machine menu
        menu = vmmenu.VMShutdownMenu(self, lambda: self.vm)
        self.widget("control-shutdown").set_menu(menu)
        self.widget("control-shutdown").set_icon_name("system-shutdown")

        topmenu = self.widget("details-vm-menu")
        submenu = topmenu.get_submenu()
        newmenu = vmmenu.VMActionMenu(self, lambda: self.vm,
                                        show_open=False)
        for child in submenu.get_children():
            submenu.remove(child)
            newmenu.add(child)
        topmenu.set_submenu(newmenu)
        topmenu.show_all()

        # Add HW popup menu
        self.addhwmenu = Gtk.Menu()

        addHW = Gtk.ImageMenuItem.new_with_label(_("_Add Hardware"))
        addHW.set_use_underline(True)
        addHWImg = Gtk.Image()
        addHWImg.set_from_stock(Gtk.STOCK_ADD, Gtk.IconSize.MENU)
        addHW.set_image(addHWImg)
        addHW.show()
        addHW.connect("activate", self.add_hardware)

        rmHW = Gtk.ImageMenuItem.new_with_label(_("_Remove Hardware"))
        rmHW.set_use_underline(True)
        rmHWImg = Gtk.Image()
        rmHWImg.set_from_stock(Gtk.STOCK_REMOVE, Gtk.IconSize.MENU)
        rmHW.set_image(rmHWImg)
        rmHW.show()
        rmHW.connect("activate", self.remove_xml_dev)

        self._addhwmenuitems = {"add": addHW, "remove": rmHW}
        for i in self._addhwmenuitems.values():
            self.addhwmenu.add(i)

        self.widget("hw-panel").set_show_tabs(False)
        self.widget("details-pages").set_show_tabs(False)
        self.widget("details-menu-view-toolbar").set_active(
                                    self.config.get_details_show_toolbar())


    def init_graphs(self):
        def _make_graph():
            g = Sparkline()
            g.set_property("reversed", True)
            g.show()
            return g

        self.cpu_usage_graph = _make_graph()
        self.widget("overview-cpu-usage-align").add(self.cpu_usage_graph)

        self.memory_usage_graph = _make_graph()
        self.widget("overview-memory-usage-align").add(self.memory_usage_graph)

        self.disk_io_graph = _make_graph()
        self.disk_io_graph.set_property("filled", False)
        self.disk_io_graph.set_property("num_sets", 2)
        self.disk_io_graph.set_property("rgb", [x / 255.0 for x in
                                        [0x82, 0x00, 0x3B, 0x29, 0x5C, 0x45]])
        self.widget("overview-disk-usage-align").add(self.disk_io_graph)

        self.network_traffic_graph = _make_graph()
        self.network_traffic_graph.set_property("filled", False)
        self.network_traffic_graph.set_property("num_sets", 2)
        self.network_traffic_graph.set_property("rgb", [x / 255.0 for x in
                                                    [0x82, 0x00, 0x3B,
                                                     0x29, 0x5C, 0x45]])
        self.widget("overview-network-traffic-align").add(
            self.network_traffic_graph)

    def init_details(self):
        # Hardware list
        # [ label, icon name, icon size, hw type, hw data/class]
        hw_list_model = Gtk.ListStore(str, str, int, int, object)
        self.widget("hw-list").set_model(hw_list_model)

        hwCol = Gtk.TreeViewColumn(_("Hardware"))
        hwCol.set_spacing(6)
        hwCol.set_min_width(165)
        hw_txt = Gtk.CellRendererText()
        hw_img = Gtk.CellRendererPixbuf()
        hwCol.pack_start(hw_img, False)
        hwCol.pack_start(hw_txt, True)
        hwCol.add_attribute(hw_txt, 'text', HW_LIST_COL_LABEL)
        hwCol.add_attribute(hw_img, 'stock-size', HW_LIST_COL_ICON_SIZE)
        hwCol.add_attribute(hw_img, 'icon-name', HW_LIST_COL_ICON_NAME)
        self.widget("hw-list").append_column(hwCol)

        # Description text view
        desc = self.widget("overview-description")
        buf = Gtk.TextBuffer()
        buf.connect("changed", self.enable_apply, EDIT_DESC)
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
                machine=self.vm.get_machtype())

            machines = capsinfo.machines[:]
        except Exception:
            logging.exception("Error determining machine list")

        show_machine = (arch not in ["i686", "x86_64"])
        uiutil.set_grid_row_visible(self.widget("machine-type-title"),
            show_machine)

        if show_machine:
            for machine in machines:
                if machine == "none":
                    continue
                machtype_model.append([machine])

        self.widget("machine-type").set_visible(self.is_customize_dialog)
        self.widget("machine-type-label").set_visible(
            not self.is_customize_dialog)

        # Firmware
        combo = self.widget("overview-firmware")
        # [label, path, is_sensitive]
        model = Gtk.ListStore(str, str, bool)
        combo.set_model(model)
        text = Gtk.CellRendererText()
        combo.pack_start(text, True)
        combo.add_attribute(text, "text", 0)
        combo.add_attribute(text, "sensitive", 2)

        domcaps = self.vm.get_domain_capabilities()
        uefipaths = [v.value for v in domcaps.os.loader.values]

        warn_icon = self.widget("overview-firmware-warn")
        hv_supports_uefi = domcaps.supports_uefi_xml()
        if not hv_supports_uefi:
            warn_icon.set_tooltip_text(
                _("Libvirt or hypervisor does not support UEFI."))
        elif not uefipaths:
            warn_icon.set_tooltip_text(
                _("Libvirt did not detect any UEFI/OVMF firmware image "
                  "installed on the host."))

        model.append([domcaps.label_for_firmware_path(None), None, True])
        if not uefipaths:
            model.append([_("UEFI not found"), None, False])
        else:
            for path in uefipaths:
                model.append([domcaps.label_for_firmware_path(path),
                    path, True])

        combo.set_active(0)

        self.widget("overview-firmware-warn").set_visible(
            not (uefipaths and hv_supports_uefi) and self.is_customize_dialog)
        self.widget("overview-firmware").set_visible(self.is_customize_dialog)
        self.widget("overview-firmware-label").set_visible(
            not self.is_customize_dialog)
        show_firmware = ((self.conn.is_qemu() or
                          self.conn.is_test() or
                          self.conn.is_xen()) and
                         domcaps.arch_can_uefi())
        uiutil.set_grid_row_visible(
            self.widget("overview-firmware-title"), show_firmware)

        # Chipset
        combo = self.widget("overview-chipset")
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        model.append([_chipset_label_from_machine("pc"), "pc"])
        if "q35" in machines:
            model.append([_chipset_label_from_machine("q35"), "q35"])
        combo.set_active(0)

        def chipset_changed(*args):
            ignore = args
            combo = self.widget("overview-chipset")
            model = combo.get_model()
            show_warn = (combo.get_active() >= 0 and
                model[combo.get_active()][1] == "q35")
            uiutil.set_grid_row_visible(
                self.widget("overview-chipset-warn-box"), show_warn)
        combo.connect("changed", chipset_changed)

        self.widget("overview-chipset").set_visible(self.is_customize_dialog)
        self.widget("overview-chipset-label").set_visible(
            not self.is_customize_dialog)
        show_chipset = ((self.conn.is_qemu() or self.conn.is_test()) and
                        arch in ["i686", "x86_64"])
        uiutil.set_grid_row_visible(
            self.widget("overview-chipset-title"), show_chipset)

        # Inspection page
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
        name_col.add_attribute(name_text, 'text', 0)
        name_col.set_sort_column_id(0)

        version_text = Gtk.CellRendererText()
        version_col.pack_start(version_text, True)
        version_col.add_attribute(version_text, 'text', 1)
        version_col.set_sort_column_id(1)

        summary_text = Gtk.CellRendererText()
        summary_col.pack_start(summary_text, True)
        summary_col.add_attribute(summary_text, 'text', 2)
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
        chk.connect("toggled", self.config_boot_toggled)
        chkCol.pack_start(chk, False)
        chkCol.add_attribute(chk, 'active', BOOT_ACTIVE)
        chkCol.add_attribute(chk, 'visible', BOOT_CAN_SELECT)

        icon = Gtk.CellRendererPixbuf()
        txtCol.pack_start(icon, False)
        txtCol.add_attribute(icon, 'icon-name', BOOT_ICON)

        text = Gtk.CellRendererText()
        txtCol.pack_start(text, True)
        txtCol.add_attribute(text, 'text', BOOT_LABEL)
        txtCol.add_attribute(text, 'sensitive', BOOT_ACTIVE)

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
        model.append([_("Application Default"), "1", "appdefault", False])
        model.append([_("Hypervisor Default"), "2",
            virtinst.CPU.SPECIAL_MODE_HV_DEFAULT, False])
        model.append([_("Clear CPU configuration"), "3",
            virtinst.CPU.SPECIAL_MODE_CLEAR, False])
        model.append([None, None, None, True])
        for name in caps.get_cpu_values(self.vm.get_arch()):
            model.append([name, name, name, False])

        # Remove button tooltip
        self.widget("config-remove").set_tooltip_text(_remove_tooltip)

        # Disk cache combo
        disk_cache = self.widget("disk-cache")
        vmmAddHardware.build_disk_cache_combo(self.vm, disk_cache)

        # Disk io combo
        disk_io = self.widget("disk-io")
        vmmAddHardware.build_disk_io_combo(self.vm, disk_io)

        # Disk bus combo
        disk_bus = self.widget("disk-bus")
        vmmAddHardware.build_disk_bus_combo(self.vm, disk_bus)

        # Network model
        net_model = self.widget("network-model")
        vmmAddHardware.build_network_model_combo(self.vm, net_model)

        # Network mac
        self.widget("network-mac-label").set_visible(
            not self.is_customize_dialog)
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


    ##########################
    # Window state listeners #
    ##########################

    def window_resized(self, ignore, ignore2):
        if not self.is_visible():
            return
        self._window_size = self.topwin.get_size()

    def popup_addhw_menu(self, widget, event):
        ignore = widget
        if event.button != 3:
            return

        devobj = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not devobj:
            return

        # force select the list entry before showing popup_menu
        path_tuple = widget.get_path_at_pos(int(event.x), int(event.y))
        if path_tuple is None:
            return False
        path = path_tuple[0]
        _iter = widget.get_model().get_iter(path)
        widget.get_selection().select_iter(_iter)

        rmdev = self._addhwmenuitems["remove"]
        rmdev.set_visible(self.widget("config-remove").get_visible())
        rmdev.set_sensitive(self.widget("config-remove").get_sensitive())

        self.addhwmenu.popup(None, None, None, None, 0, event.time)

    def control_fullscreen(self, src):
        menu = self.widget("details-menu-view-fullscreen")
        if src.get_active() != menu.get_active():
            menu.set_active(src.get_active())

    def toggle_toolbar(self, src):
        if self.is_customize_dialog:
            return

        active = src.get_active()
        self.config.set_details_show_toolbar(active)

        if (active and not
            self.widget("details-menu-view-fullscreen").get_active()):
            self.widget("toolbar-box").show()
        else:
            self.widget("toolbar-box").hide()

    def get_boot_selection(self):
        return uiutil.get_list_selected_row(self.widget("boot-list"))

    def set_hw_selection(self, page, disable_apply=True):
        if disable_apply:
            self.disable_apply()
        uiutil.set_list_selection_by_number(self.widget("hw-list"), page)

    def get_hw_row(self):
        return uiutil.get_list_selected_row(self.widget("hw-list"))

    def get_hw_selection(self, field):
        row = self.get_hw_row()
        if not row:
            return None
        return row[field]

    def force_get_hw_pagetype(self, page=None):
        if page:
            return page

        page = self.get_hw_selection(HW_LIST_COL_TYPE)
        if page is None:
            page = HW_LIST_TYPE_GENERAL
            self.set_hw_selection(0)

        return page

    def has_unapplied_changes(self, row):
        if not row:
            return False

        if not self.widget("config-apply").get_sensitive():
            return False

        if not self.err.chkbox_helper(
            self.config.get_confirm_unapplied,
            self.config.set_confirm_unapplied,
            text1=(_("There are unapplied changes. Would you like to apply "
                     "them now?")),
            chktext=_("Don't warn me again."),
            default=False):
            return False

        return not self.config_apply(row=row)

    def hw_changed(self, ignore):
        newrow = self.get_hw_row()
        model = self.widget("hw-list").get_model()

        if not newrow or newrow[HW_LIST_COL_DEVICE] == self.oldhwkey:
            return

        oldhwrow = None
        for row in model:
            if row[HW_LIST_COL_DEVICE] == self.oldhwkey:
                oldhwrow = row
                break

        if self.has_unapplied_changes(oldhwrow):
            # Unapplied changes, and syncing them failed
            pageidx = 0
            for idx, row in enumerate(model):
                if row[HW_LIST_COL_DEVICE] == self.oldhwkey:
                    pageidx = idx
                    break
            self.set_hw_selection(pageidx, disable_apply=False)
        else:
            self.oldhwkey = newrow[HW_LIST_COL_DEVICE]
            self.hw_selected()

    def hw_selected(self, page=None):
        pagetype = self.force_get_hw_pagetype(page)

        self.widget("config-remove").set_sensitive(True)
        self.widget("hw-panel").set_sensitive(True)
        self.widget("hw-panel").show()

        try:
            if pagetype == HW_LIST_TYPE_GENERAL:
                self.refresh_overview_page()
            elif pagetype == HW_LIST_TYPE_INSPECTION:
                self.refresh_inspection_page()
            elif pagetype == HW_LIST_TYPE_STATS:
                self.refresh_stats_page()
            elif pagetype == HW_LIST_TYPE_CPU:
                self.refresh_config_cpu()
            elif pagetype == HW_LIST_TYPE_MEMORY:
                self.refresh_config_memory()
            elif pagetype == HW_LIST_TYPE_BOOT:
                self.refresh_boot_page()
            elif pagetype == HW_LIST_TYPE_DISK:
                self.refresh_disk_page()
            elif pagetype == HW_LIST_TYPE_NIC:
                self.refresh_network_page()
            elif pagetype == HW_LIST_TYPE_INPUT:
                self.refresh_input_page()
            elif pagetype == HW_LIST_TYPE_GRAPHICS:
                self.refresh_graphics_page()
            elif pagetype == HW_LIST_TYPE_SOUND:
                self.refresh_sound_page()
            elif pagetype == HW_LIST_TYPE_CHAR:
                self.refresh_char_page()
            elif pagetype == HW_LIST_TYPE_HOSTDEV:
                self.refresh_hostdev_page()
            elif pagetype == HW_LIST_TYPE_VIDEO:
                self.refresh_video_page()
            elif pagetype == HW_LIST_TYPE_WATCHDOG:
                self.refresh_watchdog_page()
            elif pagetype == HW_LIST_TYPE_CONTROLLER:
                self.refresh_controller_page()
            elif pagetype == HW_LIST_TYPE_FILESYSTEM:
                self.refresh_filesystem_page()
            elif pagetype == HW_LIST_TYPE_SMARTCARD:
                self.refresh_smartcard_page()
            elif pagetype == HW_LIST_TYPE_REDIRDEV:
                self.refresh_redir_page()
            elif pagetype == HW_LIST_TYPE_TPM:
                self.refresh_tpm_page()
            elif pagetype == HW_LIST_TYPE_RNG:
                self.refresh_rng_page()
            elif pagetype == HW_LIST_TYPE_PANIC:
                self.refresh_panic_page()
            else:
                pagetype = -1
        except Exception as e:
            self.err.show_err(_("Error refreshing hardware page: %s") % str(e))
            # Don't return, we want the rest of the bits to run regardless

        self.disable_apply()
        rem = pagetype in remove_pages
        self.widget("config-remove").set_visible(rem)

        self.widget("hw-panel").set_current_page(pagetype)

    def details_console_changed(self, src):
        if self.ignoreDetails:
            return

        if not src.get_active():
            return

        is_details = (src == self.widget("control-vm-details") or
                      src == self.widget("details-menu-view-details"))
        is_snapshot = (src == self.widget("control-snapshots") or
                       src == self.widget("details-menu-view-snapshots"))

        pages = self.widget("details-pages")
        if pages.get_current_page() == DETAILS_PAGE_DETAILS:
            if self.has_unapplied_changes(self.get_hw_row()):
                self.sync_details_console_view(True)
                return
            self.disable_apply()

        if is_details:
            pages.set_current_page(DETAILS_PAGE_DETAILS)
        elif is_snapshot:
            self.snapshots.show_page()
            pages.set_current_page(DETAILS_PAGE_SNAPSHOTS)
        else:
            pages.set_current_page(DETAILS_PAGE_CONSOLE)

    def sync_details_console_view(self, newpage):
        details = self.widget("control-vm-details")
        details_menu = self.widget("details-menu-view-details")
        console = self.widget("control-vm-console")
        console_menu = self.widget("details-menu-view-console")
        snapshot = self.widget("control-snapshots")
        snapshot_menu = self.widget("details-menu-view-snapshots")

        is_details = newpage == DETAILS_PAGE_DETAILS
        is_snapshot = newpage == DETAILS_PAGE_SNAPSHOTS
        is_console = not is_details and not is_snapshot

        try:
            self.ignoreDetails = True

            details.set_active(is_details)
            details_menu.set_active(is_details)
            snapshot.set_active(is_snapshot)
            snapshot_menu.set_active(is_snapshot)
            console.set_active(is_console)
            console_menu.set_active(is_console)
        finally:
            self.ignoreDetails = False

    def switch_page(self, notebook=None, ignore2=None, newpage=None):
        for i in range(notebook.get_n_pages()):
            w = notebook.get_nth_page(i)
            w.set_visible(i == newpage)

        self.page_refresh(newpage)

        self.sync_details_console_view(newpage)
        self.console.details_refresh_can_fullscreen()

    def change_run_text(self, can_restore):
        if can_restore:
            text = _("_Restore")
        else:
            text = _("_Run")
        strip_text = text.replace("_", "")

        self.widget("details-vm-menu").get_submenu().change_run_text(text)
        self.widget("control-run").set_label(strip_text)

    def refresh_vm_state(self, ignore=None):
        vm = self.vm
        status = self.vm.status()

        self.widget("details-menu-view-toolbar").set_active(
            self.config.get_details_show_toolbar())
        self.toggle_toolbar(self.widget("details-menu-view-toolbar"))

        active = vm.is_active()
        run = vm.is_runable()
        stop = vm.is_stoppable()
        paused = vm.is_paused()

        if vm.managedsave_supported:
            self.change_run_text(vm.has_managed_save())

        self.widget("control-run").set_sensitive(run)
        self.widget("control-shutdown").set_sensitive(stop)
        self.widget("control-shutdown").get_menu().update_widget_states(vm)
        self.widget("control-pause").set_sensitive(stop)

        if paused:
            pauseTooltip = _("Resume the virtual machine")
        else:
            pauseTooltip = _("Pause the virtual machine")
        self.widget("control-pause").set_tooltip_text(pauseTooltip)

        self.widget("details-vm-menu").get_submenu().update_widget_states(vm)
        self.set_pause_state(paused)

        self.widget("overview-name").set_editable(not active)

        self.console.details_update_widget_states()
        if not run:
            self.activate_default_console_page()

        reason = self.vm.run_status_reason()
        if reason:
            status = "%s (%s)" % (self.vm.run_status(), reason)
        else:
            status = self.vm.run_status()
        self.widget("overview-status-text").set_text(status)
        self.widget("overview-status-icon").set_from_icon_name(
                            self.vm.run_status_icon_name(), Gtk.IconSize.BUTTON)

        details = self.widget("details-pages")
        self.page_refresh(details.get_current_page())

        errmsg = self.vm.snapshots_supported()
        cansnap = not bool(errmsg)
        self.widget("control-snapshots").set_sensitive(cansnap)
        self.widget("details-menu-view-snapshots").set_sensitive(cansnap)
        tooltip = _("Manage VM snapshots")
        if not cansnap:
            tooltip += "\n" + errmsg
        self.widget("control-snapshots").set_tooltip_text(tooltip)


    #############################
    # External action listeners #
    #############################

    def view_manager(self, src_ignore):
        self.emit("action-view-manager")

    def exit_app(self, src_ignore):
        self.emit("action-exit-app")

    def activate_default_console_page(self):
        pages = self.widget("details-pages")

        # console.activate_default_console_page() will as a side effect
        # switch to DETAILS_PAGE_CONSOLE. However this code path is triggered
        # when the user runs a VM while they are focused on the details page,
        # and we don't want to switch pages out from under them.
        origpage = pages.get_current_page()
        self.console.details_activate_default_console_page()
        pages.set_current_page(origpage)

    # activate_* are called from engine.py via CLI options
    def activate_default_page(self):
        pages = self.widget("details-pages")
        pages.set_current_page(DETAILS_PAGE_CONSOLE)
        self.activate_default_console_page()

    def activate_console_page(self):
        pages = self.widget("details-pages")
        pages.set_current_page(DETAILS_PAGE_CONSOLE)

    def activate_performance_page(self):
        self.widget("details-pages").set_current_page(DETAILS_PAGE_DETAILS)
        index = 0
        model = self.widget("hw-list").get_model()
        for idx, row in enumerate(model):
            if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_STATS:
                index = idx
                break
        self.set_hw_selection(index)

    def activate_config_page(self):
        self.widget("details-pages").set_current_page(DETAILS_PAGE_DETAILS)

    def add_hardware(self, src_ignore):
        try:
            if self.addhw is None:
                self.addhw = vmmAddHardware(self.vm, self.is_customize_dialog)

            self.addhw.show(self.topwin)
        except Exception as e:
            self.err.show_err((_("Error launching hardware dialog: %s") %
                               str(e)))

    def remove_xml_dev(self, src_ignore):
        devobj = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not devobj:
            return
        self.remove_device(devobj)

    def set_pause_state(self, state):
        src = self.widget("control-pause")
        try:
            src.handler_block_by_func(self.control_vm_pause)
            src.set_active(state)
        finally:
            src.handler_unblock_by_func(self.control_vm_pause)

    def control_vm_pause(self, src):
        do_pause = src.get_active()

        # Set button state back to original value: just let the status
        # update function fix things for us
        self.set_pause_state(not do_pause)

        if do_pause:
            self.emit("action-suspend-domain",
                      self.vm.conn.get_uri(),
                      self.vm.get_connkey())
        else:
            self.emit("action-resume-domain",
                      self.vm.conn.get_uri(),
                      self.vm.get_connkey())

    def control_vm_menu(self, src_ignore):
        can_usb = bool(self.console.details_viewer_has_usb_redirection() and
                       self.vm.has_spicevmc_type_redirdev())
        self.widget("details-menu-usb-redirection").set_sensitive(can_usb)

    def control_vm_run(self, src_ignore):
        if self.has_unapplied_changes(self.get_hw_row()):
            return
        self.emit("action-run-domain",
                  self.vm.conn.get_uri(), self.vm.get_connkey())

    def control_vm_shutdown(self, src_ignore):
        self.emit("action-shutdown-domain",
                  self.vm.conn.get_uri(), self.vm.get_connkey())

    def control_vm_reboot(self, src_ignore):
        self.emit("action-reboot-domain",
                  self.vm.conn.get_uri(), self.vm.get_connkey())

    def control_vm_save(self, src_ignore):
        self.emit("action-save-domain",
                  self.vm.conn.get_uri(), self.vm.get_connkey())

    def control_vm_reset(self, src_ignore):
        self.emit("action-reset-domain",
                  self.vm.conn.get_uri(), self.vm.get_connkey())

    def control_vm_destroy(self, src_ignore):
        self.emit("action-destroy-domain",
                  self.vm.conn.get_uri(), self.vm.get_connkey())

    def control_vm_clone(self, src_ignore):
        self.emit("action-clone-domain",
                  self.vm.conn.get_uri(), self.vm.get_connkey())

    def control_vm_migrate(self, src_ignore):
        self.emit("action-migrate-domain",
                  self.vm.conn.get_uri(), self.vm.get_connkey())

    def control_vm_delete(self, src_ignore):
        self.emit("action-delete-domain",
                  self.vm.conn.get_uri(), self.vm.get_connkey())

    def control_vm_screenshot(self, src):
        ignore = src
        try:
            return self._take_screenshot()
        except Exception as e:
            self.err.show_err(_("Error taking screenshot: %s") % str(e))

    def control_vm_usb_redirection(self, src):
        ignore = src
        spice_usbdev_dialog = self.err

        spice_usbdev_widget = self.console.details_viewer_get_usb_widget()
        if not spice_usbdev_widget:
            self.err.show_err(_("Error initializing spice USB device widget"))
            return

        spice_usbdev_widget.show()
        spice_usbdev_dialog.show_info(_("Select USB devices for redirection"),
                                      widget=spice_usbdev_widget,
                                      buttons=Gtk.ButtonsType.CLOSE)

    def _take_screenshot(self):
        image = self.console.details_viewer_get_pixbuf()

        metadata = {
            'tEXt::Hypervisor URI': self.vm.conn.get_uri(),
            'tEXt::Domain Name': self.vm.get_name(),
            'tEXt::Domain UUID': self.vm.get_uuid(),
            'tEXt::Generator App': self.config.get_appname(),
            'tEXt::Generator Version': self.config.get_appversion(),
        }

        ret = image.save_to_bufferv('png', metadata.keys(), metadata.values())
        # On Fedora 19, ret is (bool, str)
        # Someday the bindings might be fixed to just return the str, try
        # and future proof it a bit
        if type(ret) is tuple and len(ret) >= 2:
            ret = ret[1]
        # F24 rawhide, ret[1] is a named tuple with a 'buffer' element...
        if hasattr(ret, "buffer"):
            ret = ret.buffer

        import datetime
        now = str(datetime.datetime.now()).split(".")[0].replace(" ", "_")
        default = "Screenshot_%s_%s.png" % (self.vm.get_name(), now)

        path = self.err.browse_local(
            self.vm.conn, _("Save Virtual Machine Screenshot"),
            _type=("png", _("PNG files")),
            dialog_type=Gtk.FileChooserAction.SAVE,
            browse_reason=self.config.CONFIG_DIR_SCREENSHOT,
            default_name=default)
        if not path:
            logging.debug("No screenshot path given, skipping save.")
            return

        filename = path
        if not filename.endswith(".png"):
            filename += ".png"
        open(filename, "wb").write(ret)


    ############################
    # Details/Hardware getters #
    ############################

    def get_config_boot_order(self):
        boot_model = self.widget("boot-list").get_model()
        devs = []

        for row in boot_model:
            if row[BOOT_ACTIVE]:
                devs.append(row[BOOT_KEY])

        return devs

    def get_config_cpu_model(self):
        cpu_list = self.widget("cpu-model")
        text = cpu_list.get_child().get_text()

        if self.widget("cpu-copy-host").get_active():
            return virtinst.CPU.SPECIAL_MODE_HOST_MODEL

        key = None
        for row in cpu_list.get_model():
            if text == row[0]:
                key = row[2]
                break

        if not key:
            return text

        if key == "appdefault":
            return self.config.get_default_cpu_setting(for_cpu=True)
        return key

    def inspection_refresh(self, src_ignore):
        self.emit("inspection-refresh",
                  self.vm.conn.get_uri(), self.vm.get_connkey())


    ##############################
    # Details/Hardware listeners #
    ##############################

    def _browse_file(self, callback, is_media=False):
        if is_media:
            reason = self.config.CONFIG_DIR_ISO_MEDIA
        else:
            reason = self.config.CONFIG_DIR_IMAGE

        if self.storage_browser is None:
            self.storage_browser = vmmStorageBrowser(self.conn)

        self.storage_browser.set_finish_cb(callback)
        self.storage_browser.set_browse_reason(reason)
        self.storage_browser.show(self.topwin)

    def boot_kernel_toggled(self, src):
        self.widget("boot-kernel-box").set_sensitive(src.get_active())
        self.enable_apply(EDIT_KERNEL)

    def browse_kernel(self, src_ignore):
        def cb(ignore, path):
            self.widget("boot-kernel").set_text(path)
        self._browse_file(cb)
    def browse_initrd(self, src_ignore):
        def cb(ignore, path):
            self.widget("boot-initrd").set_text(path)
        self._browse_file(cb)
    def browse_dtb(self, src_ignore):
        def cb(ignore, path):
            self.widget("boot-dtb").set_text(path)
        self._browse_file(cb)

    def disable_apply(self):
        self.active_edits = []
        self.widget("config-apply").set_sensitive(False)
        self.widget("config-cancel").set_sensitive(False)

    def enable_apply(self, *arglist):
        edittype = arglist[-1]
        self.widget("config-apply").set_sensitive(True)
        self.widget("config-cancel").set_sensitive(True)
        if edittype not in self.active_edits:
            self.active_edits.append(edittype)

    # Idmap
    def config_idmap_enable(self, src):
        do_enable = src.get_active()
        self.widget("idmap-spin-grid").set_sensitive(do_enable)
        self.enable_apply(EDIT_IDMAP)


    # Memory
    def config_get_maxmem(self):
        return uiutil.spin_get_helper(self.widget("mem-maxmem"))
    def config_get_memory(self):
        return uiutil.spin_get_helper(self.widget("mem-memory"))

    def config_maxmem_changed(self, src_ignore):
        self.enable_apply(EDIT_MEM)

    def config_memory_changed(self, src_ignore):
        self.enable_apply(EDIT_MEM)

        maxadj = self.widget("mem-maxmem")

        mem = self.config_get_memory()
        if maxadj.get_value() < mem:
            maxadj.set_value(mem)

        ignore, upper = maxadj.get_range()
        maxadj.set_range(mem, upper)


    # VCPUS
    def config_get_vcpus(self):
        return uiutil.spin_get_helper(self.widget("cpu-vcpus"))
    def config_get_maxvcpus(self):
        return uiutil.spin_get_helper(self.widget("cpu-maxvcpus"))

    def config_vcpus_changed(self, src):
        self.enable_apply(EDIT_VCPUS)

        conn = self.vm.conn
        host_active_count = conn.host_active_processor_count()
        cur = self.config_get_vcpus()

        # Warn about overcommit
        warn = bool(cur > host_active_count)
        self.widget("cpu-vcpus-warn-box").set_visible(warn)

        maxadj = self.widget("cpu-maxvcpus")
        maxval = self.config_get_maxvcpus()
        if maxval < cur:
            if maxadj.get_sensitive():
                maxadj.set_value(cur)
            else:
                src.set_value(maxval)
                cur = maxval
        ignore, upper = maxadj.get_range()
        maxadj.set_range(cur, upper)

    def config_maxvcpus_changed(self, ignore):
        if self.widget("cpu-maxvcpus").get_sensitive():
            self.config_cpu_topology_changed()

        # As this callback can be triggered by other events, set EDIT_MAXVCPUS
        # only when the value is changed.
        if self.config_get_maxvcpus() != self.vm.vcpu_max_count():
            self.enable_apply(EDIT_MAXVCPUS)

    def on_cpu_copy_host_clicked(self, src):
        uiutil.set_grid_row_visible(
            self.widget("cpu-model"), not src.get_active())
        self.enable_apply(EDIT_CPU)

    def config_cpu_model_changed(self, ignore):
        # Warn about hyper-threading setting
        cpu_model = self.get_config_cpu_model()
        threads = self.widget("cpu-threads").get_value()
        warn_ht = _warn_cpu_thread_topo(threads, cpu_model)
        self.widget("cpu-topology-warn-box").set_visible(warn_ht)

        self.enable_apply(EDIT_CPU)

    def config_cpu_topology_changed(self, ignore=None):
        manual_top = self.widget("cpu-topology-table").is_sensitive()
        self.widget("cpu-maxvcpus").set_sensitive(not manual_top)

        if manual_top:
            cores = uiutil.spin_get_helper(self.widget("cpu-cores")) or 1
            sockets = uiutil.spin_get_helper(self.widget("cpu-sockets")) or 1
            threads = uiutil.spin_get_helper(self.widget("cpu-threads")) or 1
            total = cores * sockets * threads
            if uiutil.spin_get_helper(self.widget("cpu-vcpus")) > total:
                self.widget("cpu-vcpus").set_value(total)
            self.widget("cpu-maxvcpus").set_value(total)

            # Warn about hyper-threading setting
            cpu_model = self.get_config_cpu_model()
            warn_ht = _warn_cpu_thread_topo(threads, cpu_model)
            self.widget("cpu-topology-warn-box").set_visible(warn_ht)

        else:
            maxvcpus = uiutil.spin_get_helper(self.widget("cpu-maxvcpus"))
            self.widget("cpu-sockets").set_value(maxvcpus or 1)
            self.widget("cpu-cores").set_value(1)
            self.widget("cpu-threads").set_value(1)

        self.enable_apply(EDIT_TOPOLOGY)

    def config_cpu_topology_enable(self, src):
        do_enable = src.get_active()
        self.widget("cpu-topology-table").set_sensitive(do_enable)
        self.config_cpu_topology_changed()

    def video_model_changed(self, ignore):
        model = uiutil.get_list_selection(self.widget("video-model"))
        uiutil.set_grid_row_visible(
            self.widget("video-3d"), model == "virtio")
        self.enable_apply(EDIT_VIDEO_MODEL)

    def video_3d_toggled(self, ignore):
        self.widget("video-3d").set_inconsistent(False)
        self.enable_apply(EDIT_VIDEO_3D)

    # Boot device / Autostart
    def config_bootdev_selected(self, ignore=None):
        boot_row = self.get_boot_selection()
        boot_selection = boot_row and boot_row[BOOT_KEY]
        boot_devs = self.get_config_boot_order()
        up_widget = self.widget("boot-moveup")
        down_widget = self.widget("boot-movedown")

        down_widget.set_sensitive(bool(boot_devs and
                                       boot_selection and
                                       boot_selection in boot_devs and
                                       boot_selection != boot_devs[-1]))
        up_widget.set_sensitive(bool(boot_devs and boot_selection and
                                     boot_selection in boot_devs and
                                     boot_selection != boot_devs[0]))

    def config_boot_toggled(self, ignore, index):
        model = self.widget("boot-list").get_model()
        row = model[index]

        row[BOOT_ACTIVE] = not row[BOOT_ACTIVE]
        self.config_bootdev_selected()
        self.enable_apply(EDIT_BOOTORDER)

    def config_boot_move(self, src, move_up):
        ignore = src
        row = self.get_boot_selection()
        if not row:
            return

        row_key = row[BOOT_KEY]
        boot_order = self.get_config_boot_order()
        key_idx = boot_order.index(row_key)
        if move_up:
            new_idx = key_idx - 1
        else:
            new_idx = key_idx + 1

        if new_idx < 0 or new_idx >= len(boot_order):
            # Somehow we went out of bounds
            return

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
        self.enable_apply(EDIT_BOOTORDER)

    def disk_format_changed(self, ignore):
        self.widget("disk-format-warn").show()
        self.enable_apply(EDIT_DISK_FORMAT)


    # CDROM Eject/Connect
    def _change_storage_media(self, devobj, newpath):
        kwargs = {"path": newpath}
        return vmmAddHardware.change_config_helper(self.vm.define_disk,
            kwargs, self.vm, self.err, devobj=devobj)

    def _eject_media(self, disk):
        try:
            self._change_storage_media(disk, None)
        except Exception as e:
            self.err.show_err((_("Error disconnecting media: %s") % e))

    def _insert_media(self, disk):
        try:
            devtype = disk.device

            def change_cdrom_wrapper(src_ignore, devobj, newpath):
                return self._change_storage_media(devobj, newpath)

            # Launch 'Choose CD' dialog
            if self.media_choosers[devtype] is None:
                ret = vmmChooseCD(self.vm, disk)

                ret.connect("cdrom-chosen", change_cdrom_wrapper)
                self.media_choosers[devtype] = ret

            dialog = self.media_choosers[devtype]
            dialog.disk = disk

            dialog.show(self.topwin)
        except Exception as e:
            self.err.show_err((_("Error launching media dialog: %s") % e))
            return

    def toggle_storage_media(self, src_ignore):
        disk = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not disk:
            return

        if disk.path:
            return self._eject_media(disk)
        return self._insert_media(disk)


    ##################################################
    # Details/Hardware config changes (apply button) #
    ##################################################

    def config_cancel(self, ignore=None):
        # Remove current changes and deactive 'apply' button
        self.hw_selected()

    def config_apply(self, ignore=None, row=None):
        pagetype = None
        devobj = None

        if not row:
            row = self.get_hw_row()
        if row:
            pagetype = row[HW_LIST_COL_TYPE]
            devobj = row[HW_LIST_COL_DEVICE]

        key = devobj
        ret = False

        try:
            if pagetype is HW_LIST_TYPE_GENERAL:
                ret = self.config_overview_apply()
            elif pagetype is HW_LIST_TYPE_CPU:
                ret = self.config_vcpus_apply()
            elif pagetype is HW_LIST_TYPE_MEMORY:
                ret = self.config_memory_apply()
            elif pagetype is HW_LIST_TYPE_BOOT:
                ret = self.config_boot_options_apply()
            elif pagetype is HW_LIST_TYPE_DISK:
                ret = self.config_disk_apply(key)
            elif pagetype is HW_LIST_TYPE_NIC:
                ret = self.config_network_apply(key)
            elif pagetype is HW_LIST_TYPE_GRAPHICS:
                ret = self.config_graphics_apply(key)
            elif pagetype is HW_LIST_TYPE_SOUND:
                ret = self.config_sound_apply(key)
            elif pagetype is HW_LIST_TYPE_VIDEO:
                ret = self.config_video_apply(key)
            elif pagetype is HW_LIST_TYPE_WATCHDOG:
                ret = self.config_watchdog_apply(key)
            elif pagetype is HW_LIST_TYPE_SMARTCARD:
                ret = self.config_smartcard_apply(key)
            elif pagetype is HW_LIST_TYPE_CONTROLLER:
                ret = self.config_controller_apply(key)
            elif pagetype is HW_LIST_TYPE_FILESYSTEM:
                ret = self.config_filesystem_apply(key)
            elif pagetype is HW_LIST_TYPE_HOSTDEV:
                ret = self.config_hostdev_apply(key)
            else:
                ret = False
        except Exception as e:
            return self.err.show_err(_("Error apply changes: %s") % e)

        if ret is not False:
            self.disable_apply()
        return True

    def get_text(self, widgetname, strip=True, checksens=False):
        widget = self.widget(widgetname)
        if (checksens and
            (not widget.is_sensitive() or not widget.is_visible())):
            return ""

        ret = widget.get_text()
        if strip:
            ret = ret.strip()
        return ret

    def edited(self, pagetype):
        return pagetype in self.active_edits

    def config_overview_apply(self):
        kwargs = {}
        hotplug_args = {}

        if self.edited(EDIT_TITLE):
            kwargs["title"] = self.widget("overview-title").get_text()
            hotplug_args["title"] = kwargs["title"]

        if self.edited(EDIT_FIRMWARE):
            kwargs["loader"] = uiutil.get_list_selection(
                self.widget("overview-firmware"), column=1)

        if self.edited(EDIT_MACHTYPE):
            if self.widget("overview-chipset").is_visible():
                kwargs["machine"] = uiutil.get_list_selection(
                    self.widget("overview-chipset"), column=1)
            else:
                kwargs["machine"] = uiutil.get_list_selection(
                    self.widget("machine-type"))

        if self.edited(EDIT_DESC):
            desc_widget = self.widget("overview-description")
            kwargs["description"] = (
                desc_widget.get_buffer().get_property("text") or "")
            hotplug_args["description"] = kwargs["description"]

        if self.edited(EDIT_IDMAP):
            enable_idmap = self.widget("idmap-checkbutton").get_active()
            if enable_idmap:
                uid_target = self.widget("uid-target").get_text().strip()
                uid_count = self.widget("uid-count").get_text().strip()
                gid_target = self.widget("gid-target").get_text().strip()
                gid_count = self.widget("gid-count").get_text().strip()

                idmap_list = [uid_target, uid_count, gid_target, gid_count]
            else:
                idmap_list = None
            kwargs["idmap_list"] = idmap_list

        # This needs to be last
        if self.edited(EDIT_NAME):
            # Renaming is pretty convoluted, so do it here synchronously
            self.vm.rename_domain(self.widget("overview-name").get_text())

            if not kwargs and not hotplug_args:
                # Saves some useless redefine attempts
                return

        return vmmAddHardware.change_config_helper(self.vm.define_overview,
                                          kwargs, self.vm, self.err,
                                          hotplug_args=hotplug_args)

    def config_vcpus_apply(self):
        kwargs = {}
        hotplug_args = {}

        if self.edited(EDIT_VCPUS):
            kwargs["vcpus"] = self.config_get_vcpus()
            hotplug_args["vcpus"] = kwargs["vcpus"]

        if self.edited(EDIT_MAXVCPUS):
            kwargs["maxvcpus"] = self.config_get_maxvcpus()

        if self.edited(EDIT_CPU):
            kwargs["model"] = self.get_config_cpu_model()

        if self.edited(EDIT_TOPOLOGY):
            do_top = self.widget("cpu-topology-enable").get_active()
            kwargs["sockets"] = self.widget("cpu-sockets").get_value()
            kwargs["cores"] = self.widget("cpu-cores").get_value()
            kwargs["threads"] = self.widget("cpu-threads").get_value()
            if not do_top:
                kwargs["sockets"] = None
                kwargs["cores"] = None
                kwargs["threads"] = None

        return vmmAddHardware.change_config_helper(self.vm.define_cpu,
                                          kwargs, self.vm, self.err,
                                          hotplug_args=hotplug_args)

    def config_memory_apply(self):
        kwargs = {}
        hotplug_args = {}

        if self.edited(EDIT_MEM):
            curmem = None
            maxmem = self.config_get_maxmem()
            if self.widget("mem-memory").get_sensitive():
                curmem = self.config_get_memory()

            if curmem:
                curmem = int(curmem) * 1024
            if maxmem:
                maxmem = int(maxmem) * 1024

            kwargs["memory"] = curmem
            kwargs["maxmem"] = maxmem
            hotplug_args["memory"] = kwargs["memory"]
            hotplug_args["maxmem"] = kwargs["maxmem"]

        return vmmAddHardware.change_config_helper(self.vm.define_memory,
                                          kwargs, self.vm, self.err,
                                          hotplug_args=hotplug_args)

    def config_boot_options_apply(self):
        kwargs = {}

        if self.edited(EDIT_AUTOSTART):
            auto = self.widget("boot-autostart")
            try:
                self.vm.set_autostart(auto.get_active())
            except Exception as e:
                self.err.show_err(
                    (_("Error changing autostart value: %s") % str(e)))
                return False

        if self.edited(EDIT_BOOTORDER):
            kwargs["boot_order"] = self.get_config_boot_order()

        if self.edited(EDIT_BOOTMENU):
            kwargs["boot_menu"] = self.widget("boot-menu").get_active()

        if self.edited(EDIT_KERNEL):
            kwargs["kernel"] = self.get_text("boot-kernel", checksens=True)
            kwargs["initrd"] = self.get_text("boot-initrd", checksens=True)
            kwargs["dtb"] = self.get_text("boot-dtb", checksens=True)
            kwargs["kernel_args"] = self.get_text("boot-kernel-args",
                checksens=True)

            if kwargs["initrd"] and not kwargs["kernel"]:
                return self.err.val_err(
                    _("Cannot set initrd without specifying a kernel path"))
            if kwargs["kernel_args"] and not kwargs["kernel"]:
                return self.err.val_err(
                    _("Cannot set kernel arguments without specifying a kernel path"))

        if self.edited(EDIT_INIT):
            kwargs["init"] = self.get_text("boot-init-path")
            kwargs["initargs"] = self.get_text("boot-init-args") or ""
            if not kwargs["init"]:
                return self.err.val_err(_("An init path must be specified"))

        return vmmAddHardware.change_config_helper(self.vm.define_boot,
                                          kwargs, self.vm, self.err)


    #####################
    # <device> defining #
    #####################

    def config_disk_apply(self, devobj):
        kwargs = {}

        if self.edited(EDIT_DISK_RO):
            kwargs["readonly"] = self.widget("disk-readonly").get_active()

        if self.edited(EDIT_DISK_SHARE):
            kwargs["shareable"] = self.widget("disk-shareable").get_active()

        if self.edited(EDIT_DISK_REMOVABLE):
            kwargs["removable"] = bool(
                self.widget("disk-removable").get_active())

        if self.edited(EDIT_DISK_CACHE):
            kwargs["cache"] = uiutil.get_list_selection(
                self.widget("disk-cache"))

        if self.edited(EDIT_DISK_IO):
            kwargs["io"] = uiutil.get_list_selection(self.widget("disk-io"))

        if self.edited(EDIT_DISK_FORMAT):
            kwargs["driver_type"] = self.widget("disk-format").get_text()

        if self.edited(EDIT_DISK_SERIAL):
            kwargs["serial"] = self.get_text("disk-serial")

        if self.edited(EDIT_DISK_SGIO):
            sgio = uiutil.get_list_selection(self.widget("disk-sgio"))
            kwargs["sgio"] = sgio

        if self.edited(EDIT_DISK_BUS):
            bus = uiutil.get_list_selection(self.widget("disk-bus"))
            addr = None

            kwargs["bus"] = bus
            kwargs["addrstr"] = addr

        return vmmAddHardware.change_config_helper(self.vm.define_disk,
                                          kwargs, self.vm, self.err,
                                          devobj=devobj)

    def config_sound_apply(self, devobj):
        kwargs = {}

        if self.edited(EDIT_SOUND_MODEL):
            model = uiutil.get_list_selection(self.widget("sound-model"))
            if model:
                kwargs["model"] = model

        return vmmAddHardware.change_config_helper(self.vm.define_sound,
                                          kwargs, self.vm, self.err,
                                          devobj=devobj)

    def config_smartcard_apply(self, devobj):
        kwargs = {}

        if self.edited(EDIT_SMARTCARD_MODE):
            model = uiutil.get_list_selection(self.widget("smartcard-mode"))
            if model:
                kwargs["model"] = model

        return vmmAddHardware.change_config_helper(self.vm.define_smartcard,
                                          kwargs, self.vm, self.err,
                                          devobj=devobj)

    def config_network_apply(self, devobj):
        kwargs = {}

        if self.edited(EDIT_NET_MODEL):
            model = uiutil.get_list_selection(self.widget("network-model"))
            addrstr = None
            if model == "spapr-vlan":
                addrstr = "spapr-vio"
            kwargs["model"] = model
            kwargs["addrstr"] = addrstr

        if self.edited(EDIT_NET_SOURCE):
            (kwargs["ntype"], kwargs["source"],
             kwargs["mode"], kwargs["portgroup"]) = (
                self.netlist.get_network_selection())

        if self.edited(EDIT_NET_VPORT):
            (kwargs["vtype"], kwargs["managerid"],
             kwargs["typeid"], kwargs["typeidversion"],
             kwargs["instanceid"]) = self.netlist.get_vport()

        if self.edited(EDIT_NET_MAC):
            kwargs["macaddr"] = self.widget("network-mac-entry").get_text()

        return vmmAddHardware.change_config_helper(self.vm.define_network,
                                          kwargs, self.vm, self.err,
                                          devobj=devobj)

    def config_graphics_apply(self, devobj):
        (gtype, port, tlsport, listen,
         addr, passwd, keymap, gl, rendernode) = self.gfxdetails.get_values()

        kwargs = {}

        if self.edited(EDIT_GFX_PASSWD):
            kwargs["passwd"] = passwd
        if self.edited(EDIT_GFX_LISTEN):
            kwargs["listen"] = listen
        if self.edited(EDIT_GFX_ADDRESS) or self.edited(EDIT_GFX_LISTEN):
            kwargs["addr"] = addr
        if self.edited(EDIT_GFX_KEYMAP):
            kwargs["keymap"] = keymap
        if self.edited(EDIT_GFX_PORT) or self.edited(EDIT_GFX_LISTEN):
            kwargs["port"] = port
        if self.edited(EDIT_GFX_OPENGL):
            kwargs["gl"] = gl
        if self.edited(EDIT_GFX_TLSPORT) or self.edited(EDIT_GFX_LISTEN):
            kwargs["tlsport"] = tlsport
        if self.edited(EDIT_GFX_RENDERNODE):
            kwargs["rendernode"] = rendernode
        if self.edited(EDIT_GFX_TYPE):
            kwargs["gtype"] = gtype

        return vmmAddHardware.change_config_helper(self.vm.define_graphics,
                                          kwargs, self.vm, self.err,
                                          devobj=devobj)

    def config_video_apply(self, devobj):
        kwargs = {}

        if self.edited(EDIT_VIDEO_MODEL):
            model = uiutil.get_list_selection(self.widget("video-model"))
            if model:
                kwargs["model"] = model

        if self.edited(EDIT_VIDEO_3D):
            kwargs["accel3d"] = self.widget("video-3d").get_active()

        return vmmAddHardware.change_config_helper(self.vm.define_video,
                                          kwargs, self.vm, self.err,
                                          devobj=devobj)

    def config_controller_apply(self, devobj):
        kwargs = {}

        if self.edited(EDIT_CONTROLLER_MODEL):
            model = uiutil.get_list_selection(self.widget("controller-model"))
            kwargs["model"] = model

        return vmmAddHardware.change_config_helper(self.vm.define_controller,
                                          kwargs, self.vm, self.err,
                                          devobj=devobj)

    def config_watchdog_apply(self, devobj):
        kwargs = {}

        if self.edited(EDIT_WATCHDOG_MODEL):
            kwargs["model"] = uiutil.get_list_selection(
                self.widget("watchdog-model"))

        if self.edited(EDIT_WATCHDOG_ACTION):
            kwargs["action"] = uiutil.get_list_selection(
                self.widget("watchdog-action"))

        return vmmAddHardware.change_config_helper(self.vm.define_watchdog,
                                          kwargs, self.vm, self.err,
                                          devobj=devobj)

    def config_filesystem_apply(self, devobj):
        kwargs = {}

        if self.edited(EDIT_FS):
            if self.fsDetails.validate_page_filesystem() is False:
                return False
            kwargs["newdev"] = self.fsDetails.get_dev()

        return vmmAddHardware.change_config_helper(self.vm.define_filesystem,
                                          kwargs, self.vm, self.err,
                                          devobj=devobj)

    def config_hostdev_apply(self, devobj):
        kwargs = {}

        if self.edited(EDIT_HOSTDEV_ROMBAR):
            kwargs["rom_bar"] = self.widget("hostdev-rombar").get_active()

        return vmmAddHardware.change_config_helper(self.vm.define_hostdev,
                                          kwargs, self.vm, self.err,
                                          devobj=devobj)


    # Device removal
    def remove_device(self, devobj):
        logging.debug("Removing device: %s", devobj)

        if not self.err.chkbox_helper(self.config.get_confirm_removedev,
            self.config.set_confirm_removedev,
            text1=(_("Are you sure you want to remove this device?"))):
            return

        # Define the change
        try:
            self.vm.remove_device(devobj)
        except Exception as e:
            self.err.show_err(_("Error Removing Device: %s") % str(e))
            return

        # Try to hot remove
        detach_err = ()
        try:
            if self.vm.is_active():
                self.vm.detach_device(devobj)
        except Exception as e:
            logging.debug("Device could not be hotUNplugged: %s", str(e))
            detach_err = (str(e), "".join(traceback.format_exc()))

        if not detach_err:
            self.disable_apply()
            return

        self.err.show_err(
            _("Device could not be removed from the running machine"),
            details=(detach_err[0] + "\n\n" + detach_err[1]),
            text2=_("This change will take effect after the next guest "
                    "shutdown."),
            buttons=Gtk.ButtonsType.OK,
            dialog_type=Gtk.MessageType.INFO)


    ########################
    # Details page refresh #
    ########################

    def refresh_resources(self, ignore):
        details = self.widget("details-pages")
        page = details.get_current_page()

        # If the dialog is visible, we want to make sure the XML is always
        # up to date
        try:
            if self.is_visible():
                self.vm.ensure_latest_xml()
        except libvirt.libvirtError as e:
            if util.exception_is_libvirt_error(e, "VIR_ERR_NO_DOMAIN"):
                self.close()
                return
            raise

        # Stats page needs to be refreshed every tick
        if (page == DETAILS_PAGE_DETAILS and
            self.get_hw_selection(HW_LIST_COL_TYPE) == HW_LIST_TYPE_STATS):
            self.refresh_stats_page()

    def page_refresh(self, page):
        if page != DETAILS_PAGE_DETAILS:
            return

        # This function should only be called when the VM xml actually
        # changes (not everytime it is refreshed). This saves us from blindly
        # parsing the xml every tick

        # Add / remove new devices
        self.repopulate_hw_list()

        pagetype = self.get_hw_selection(HW_LIST_COL_TYPE)
        if pagetype is None:
            return

        if self.widget("config-apply").get_sensitive():
            # Apply button sensitive means user is making changes, don't
            # erase them
            return

        self.hw_selected(page=pagetype)

    def refresh_overview_page(self):
        # Basic details
        self.widget("overview-name").set_text(self.vm.get_name())
        self.widget("overview-uuid").set_text(self.vm.get_uuid())
        desc = self.vm.get_description() or ""
        desc_widget = self.widget("overview-description")
        desc_widget.get_buffer().set_text(desc)

        title = self.vm.get_title()
        self.widget("overview-title").set_sensitive(self.vm.title_supported)
        self.widget("overview-title").set_text(title or "")

        # Hypervisor Details
        self.widget("overview-hv").set_text(self.vm.get_pretty_hv_type())
        arch = self.vm.get_arch() or _("Unknown")
        emu = self.vm.get_emulator() or _("None")
        self.widget("overview-arch").set_text(arch)
        self.widget("overview-emulator").set_text(emu)

        # Firmware
        domcaps = self.vm.get_domain_capabilities()
        firmware = domcaps.label_for_firmware_path(
            self.vm.get_xmlobj().os.loader)
        if self.widget("overview-firmware").is_visible():
            uiutil.set_list_selection(
                self.widget("overview-firmware"), firmware)
        elif self.widget("overview-firmware-label").is_visible():
            self.widget("overview-firmware-label").set_text(firmware)

        # Machine settings
        machtype = self.vm.get_machtype() or _("Unknown")
        if self.widget("machine-type").is_visible():
            uiutil.set_list_selection(
                self.widget("machine-type"), machtype)
        elif self.widget("machine-type-label").is_visible():
            self.widget("machine-type-label").set_text(machtype)

        # Chipset
        chipset = _chipset_label_from_machine(machtype)
        if self.widget("overview-chipset").is_visible():
            uiutil.set_list_selection(
                self.widget("overview-chipset"), chipset)
        elif self.widget("overview-chipset-label").is_visible():
            self.widget("overview-chipset-label").set_text(chipset)

        # User namespace idmap setting
        is_container = self.vm.is_container()
        self.widget("idmap-expander").set_visible(is_container)

        self.widget("uid-target").set_text('1000')
        self.widget("uid-count").set_text('10')
        self.widget("gid-target").set_text('1000')
        self.widget("gid-count").set_text('10')

        IdMap = self.vm.get_idmap()
        show_config = IdMap.uid_start is not None

        self.widget("idmap-checkbutton").set_active(show_config)
        self.widget("idmap-spin-grid").set_sensitive(show_config)
        if show_config:
            Name = ["uid-target", "uid-count", "gid-target", "gid-count"]
            for name in Name:
                IdMap_proper = getattr(IdMap, name.replace("-", "_"))
                self.widget(name).set_value(int(IdMap_proper))

    def refresh_inspection_page(self):
        inspection_supported = self.config.support_inspection
        uiutil.set_grid_row_visible(self.widget("details-overview-error"),
                                       self.vm.inspection.error)
        if self.vm.inspection.error:
            msg = _("Error while inspecting the guest configuration")
            self.widget("details-overview-error").set_text(msg)

        # Operating System (ie. inspection data)
        self.widget("details-inspection-os").set_visible(inspection_supported)
        if inspection_supported:
            hostname = self.vm.inspection.hostname
            if not hostname:
                hostname = _("unknown")
            self.widget("inspection-hostname").set_text(hostname)
            os_type = self.vm.inspection.os_type
            if not os_type:
                os_type = "unknown"
            self.widget("inspection-type").set_text(_label_for_os_type(os_type))
            product_name = self.vm.inspection.product_name
            if not product_name:
                product_name = _("unknown")
            self.widget("inspection-product-name").set_text(product_name)

        # Applications (also inspection data)
        self.widget("details-inspection-apps").set_visible(inspection_supported)
        if inspection_supported:
            apps = self.vm.inspection.applications or []
            apps_list = self.widget("inspection-apps")
            apps_model = apps_list.get_model()
            apps_model.clear()
            for app in apps:
                name = ""
                if app["app_name"]:
                    name = app["app_name"]
                if app["app_display_name"]:
                    name = app["app_display_name"]
                version = ""
                if app["app_epoch"] > 0:
                    version += str(app["app_epoch"]) + ":"
                if app["app_version"]:
                    version += app["app_version"]
                if app["app_release"]:
                    version += "-" + app["app_release"]
                summary = ""
                if app["app_summary"]:
                    summary = app["app_summary"]
                elif app["app_description"]:
                    summary = app["app_description"]
                    pos = summary.find("\n")
                    if pos > -1:
                        summary = _("%(summary)s ...") % {
                            "summary": summary[0:pos]
                        }

                apps_model.append([name, version, summary])

    def refresh_stats_page(self):
        def _multi_color(text1, text2):
            return ('<span color="#82003B">%s</span> '
                    '<span color="#295C45">%s</span>' % (text1, text2))
        def _dsk_rx_tx_text(rx, tx, unit):
            opts = {"received": rx, "transfered": tx, "units": unit}
            return _multi_color(_("%(received)d %(units)s read") % opts,
                                _("%(transfered)d %(units)s write") % opts)
        def _net_rx_tx_text(rx, tx, unit):
            opts = {"received": rx, "transfered": tx, "units": unit}
            return _multi_color(_("%(received)d %(units)s in") % opts,
                                _("%(transfered)d %(units)s out") % opts)

        cpu_txt = _("Disabled")
        mem_txt = _("Disabled")
        dsk_txt = _("Disabled")
        net_txt = _("Disabled")

        if self.config.get_stats_enable_cpu_poll():
            cpu_txt = "%d %%" % self.vm.guest_cpu_time_percentage()

        if self.config.get_stats_enable_memory_poll():
            cur_vm_memory = self.vm.stats_memory()
            vm_memory = self.vm.maximum_memory()
            mem_txt = _("%(current-memory)s of %(total-memory)s") % {
                "current-memory": util.pretty_mem(cur_vm_memory),
                "total-memory": util.pretty_mem(vm_memory)
            }

        if self.config.get_stats_enable_disk_poll():
            dsk_txt = _dsk_rx_tx_text(self.vm.disk_read_rate(),
                                      self.vm.disk_write_rate(), "KiB/s")

        if self.config.get_stats_enable_net_poll():
            net_txt = _net_rx_tx_text(self.vm.network_rx_rate(),
                                      self.vm.network_tx_rate(), "KiB/s")

        self.widget("overview-cpu-usage-text").set_text(cpu_txt)
        self.widget("overview-memory-usage-text").set_text(mem_txt)
        self.widget("overview-network-traffic-text").set_markup(net_txt)
        self.widget("overview-disk-usage-text").set_markup(dsk_txt)

        self.cpu_usage_graph.set_property("data_array",
                                          self.vm.guest_cpu_time_vector())
        self.memory_usage_graph.set_property("data_array",
                                             self.vm.stats_memory_vector())

        d1, d2 = self.vm.disk_io_vectors()
        self.disk_io_graph.set_property("data_array", d1 + d2)

        n1, n2 = self.vm.network_traffic_vectors()
        self.network_traffic_graph.set_property("data_array", n1 + n2)

    def refresh_config_cpu(self):
        # Set topology first, because it impacts maxvcpus values
        cpu = self.vm.get_cpu_config()
        show_top = bool(cpu.sockets or cpu.cores or cpu.threads)
        self.widget("cpu-topology-enable").set_active(show_top)

        sockets = cpu.sockets or 1
        cores = cpu.cores or 1
        threads = cpu.threads or 1

        self.widget("cpu-sockets").set_value(sockets)
        self.widget("cpu-cores").set_value(cores)
        self.widget("cpu-threads").set_value(threads)
        if show_top:
            self.widget("cpu-topology-expander").set_expanded(True)

        host_active_count = self.vm.conn.host_active_processor_count()
        maxvcpus = self.vm.vcpu_max_count()
        curvcpus = self.vm.vcpu_count()

        self.widget("cpu-vcpus").set_value(int(curvcpus))
        self.widget("cpu-maxvcpus").set_value(int(maxvcpus))
        self.widget("state-host-cpus").set_text(str(host_active_count))

        # Trigger this again to make sure maxvcpus is correct
        self.config_cpu_topology_changed()

        # Warn about overcommit
        warn = bool(self.config_get_vcpus() > host_active_count)
        self.widget("cpu-vcpus-warn-box").set_visible(warn)

        # CPU model config
        model = cpu.model or None
        if not model:
            if cpu.mode == "host-model" or cpu.mode == "host-passthrough":
                model = cpu.mode

        if model:
            self.widget("cpu-model").get_child().set_text(model)
        else:
            uiutil.set_list_selection(
                self.widget("cpu-model"),
                virtinst.CPU.SPECIAL_MODE_HV_DEFAULT, column=2)

        # Warn about hyper-threading setting
        cpu_model = self.get_config_cpu_model()
        warn_ht = _warn_cpu_thread_topo(threads, cpu_model)
        self.widget("cpu-topology-warn-box").set_visible(warn_ht)

        is_host = (cpu.mode == "host-model")
        self.widget("cpu-copy-host").set_active(bool(is_host))
        self.on_cpu_copy_host_clicked(self.widget("cpu-copy-host"))

    def refresh_config_memory(self):
        host_mem_widget = self.widget("state-host-memory")
        host_mem = self.vm.conn.host_memory_size() / 1024
        vm_cur_mem = self.vm.get_memory() / 1024.0
        vm_max_mem = self.vm.maximum_memory() / 1024.0

        host_mem_widget.set_text("%d MiB" % (int(round(host_mem))))

        curmem = self.widget("mem-memory")
        maxmem = self.widget("mem-maxmem")
        curmem.set_value(int(round(vm_cur_mem)))
        maxmem.set_value(int(round(vm_max_mem)))

        if not self.widget("mem-memory").get_sensitive():
            ignore, upper = maxmem.get_range()
            maxmem.set_range(curmem.get_value(), upper)

    @staticmethod
    def build_disk_sgio(vm, combo):
        ignore = vm
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        model.append([None, _("Hypervisor default")])
        model.append(["filtered", "filtered"])
        model.append(["unfiltered", "unfiltered"])

    def refresh_disk_page(self):
        disk = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not disk:
            return

        path = disk.path
        devtype = disk.device
        ro = disk.read_only
        share = disk.shareable
        bus = disk.bus
        removable = disk.removable
        cache = disk.driver_cache
        io = disk.driver_io
        driver_type = disk.driver_type or ""
        serial = disk.serial

        size = "-"
        if path:
            size = _("Unknown")
            vol = self.conn.get_vol_by_path(path)
            if vol:
                size = vol.get_pretty_capacity()

        is_cdrom = (devtype == virtinst.VirtualDisk.DEVICE_CDROM)
        is_floppy = (devtype == virtinst.VirtualDisk.DEVICE_FLOPPY)
        is_usb = (bus == "usb")

        can_set_removable = (is_usb and (self.conn.is_qemu() or
                                         self.conn.is_test()))
        if removable is None:
            removable = False
        else:
            can_set_removable = True

        pretty_name = _label_for_device(disk)

        self.widget("disk-source-path").set_text(path or "-")
        self.widget("disk-target-type").set_text(pretty_name)

        self.widget("disk-readonly").set_active(ro)
        self.widget("disk-readonly").set_sensitive(not is_cdrom)
        self.widget("disk-shareable").set_active(share)
        self.widget("disk-removable").set_active(removable)
        uiutil.set_grid_row_visible(self.widget("disk-removable"),
                                       can_set_removable)

        is_lun = disk.device == virtinst.VirtualDisk.DEVICE_LUN
        uiutil.set_grid_row_visible(self.widget("disk-sgio"), is_lun)
        if is_lun:
            self.build_disk_sgio(self.vm, self.widget("disk-sgio"))
            uiutil.set_list_selection(self.widget("disk-sgio"), disk.sgio)

        self.widget("disk-size").set_text(size)
        uiutil.set_list_selection(self.widget("disk-cache"), cache)
        uiutil.set_list_selection(self.widget("disk-io"), io)

        self.widget("disk-format").set_text(driver_type)
        self.widget("disk-format-warn").hide()

        vmmAddHardware.populate_disk_bus_combo(self.vm, devtype,
            self.widget("disk-bus").get_model())
        uiutil.set_list_selection(self.widget("disk-bus"), bus)
        self.widget("disk-serial").set_text(serial or "")

        button = self.widget("disk-cdrom-connect")
        if is_cdrom or is_floppy:
            if not path:
                # source device not connected
                button.set_label(Gtk.STOCK_CONNECT)
            else:
                button.set_label(Gtk.STOCK_DISCONNECT)
            button.show()
        else:
            button.hide()

    def refresh_network_page(self):
        net = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not net:
            return

        vmmAddHardware.populate_network_model_combo(
            self.vm, self.widget("network-model"))
        uiutil.set_list_selection(self.widget("network-model"), net.model)

        macaddr = net.macaddr or ""
        if self.widget("network-mac-label").is_visible():
            self.widget("network-mac-label").set_text(macaddr)
        else:
            self.widget("network-mac-entry").set_text(macaddr)

        self.netlist.set_dev(net)

    def refresh_input_page(self):
        inp = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not inp:
            return

        dev = vmmAddHardware.label_for_input_device(inp.type, inp.bus)

        mode = None
        if inp.type == "tablet":
            mode = _("Absolute Movement")
        elif inp.type == "mouse":
            mode = _("Relative Movement")

        self.widget("input-dev-type").set_text(dev)
        self.widget("input-dev-mode").set_text(mode or "")
        uiutil.set_grid_row_visible(self.widget("input-dev-mode"), bool(mode))

        tooltip = _remove_tooltip
        sensitive = True
        if ((inp.type == "mouse" and inp.bus in ("xen", "ps2")) or
            (inp.type == "keyboard" and inp.bus in ("xen", "ps2"))):
            sensitive = False
            tooltip = _("Hypervisor does not support removing this device")

        self.widget("config-remove").set_sensitive(sensitive)
        self.widget("config-remove").set_tooltip_text(tooltip)

    def refresh_graphics_page(self):
        gfx = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not gfx:
            return

        title = self.gfxdetails.set_dev(gfx)
        self.widget("graphics-title").set_markup("<b>%s</b>" % title)

    def refresh_sound_page(self):
        sound = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not sound:
            return

        uiutil.set_list_selection(self.widget("sound-model"), sound.model)

    def refresh_smartcard_page(self):
        sc = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not sc:
            return

        uiutil.set_list_selection(self.widget("smartcard-mode"), sc.mode)

    def refresh_redir_page(self):
        rd = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not rd:
            return

        address = None
        if rd.type == 'tcp':
            address = _("%s:%s") % (rd.host, rd.service)

        self.widget("redir-title").set_markup(_label_for_device(rd))
        self.widget("redir-type").set_text(rd.pretty_type(rd.type))

        self.widget("redir-address").set_text(address or "")
        uiutil.set_grid_row_visible(
            self.widget("redir-address"), bool(address))

    def refresh_tpm_page(self):
        tpmdev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not tpmdev:
            return

        def show_ui(param, val=None):
            widgetname = "tpm-" + param.replace("_", "-")
            doshow = tpmdev.supports_property(param)

            if not val and doshow:
                val = getattr(tpmdev, param)

            uiutil.set_grid_row_visible(self.widget(widgetname), doshow)
            self.widget(widgetname).set_text(val or "-")

        dev_type = tpmdev.type
        self.widget("tpm-dev-type").set_text(
                virtinst.VirtualTPMDevice.get_pretty_type(dev_type))

        # Device type specific properties, only show if apply to the cur dev
        show_ui("device_path")

    def refresh_panic_page(self):
        dev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not dev:
            return

        model = dev.model or "isa"
        pmodel = virtinst.VirtualPanicDevice.get_pretty_model(model)
        self.widget("panic-model").set_text(pmodel)

    def refresh_rng_page(self):
        dev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        values = {
            "rng-bind-host": "bind_host",
            "rng-bind-service": "bind_service",
            "rng-connect-host": "connect_host",
            "rng-connect-service": "connect_service",
            "rng-type": "type",
            "rng-device": "device",
            "rng-backend-type": "backend_type",
            "rng-rate-bytes": "rate_bytes",
            "rng-rate-period": "rate_period"
        }
        rewriter = {
            "rng-type": lambda x:
            VirtualRNGDevice.get_pretty_type(x),
            "rng-backend-type": lambda x:
            VirtualRNGDevice.get_pretty_backend_type(x),
        }

        def set_visible(widget, v):
            uiutil.set_grid_row_visible(self.widget(widget), v)

        is_egd = dev.type == VirtualRNGDevice.TYPE_EGD
        udp = dev.backend_type == VirtualRNGDevice.BACKEND_TYPE_UDP
        bind = VirtualRNGDevice.BACKEND_MODE_BIND in dev.backend_mode()

        set_visible("rng-device", not is_egd)
        set_visible("rng-mode", is_egd and not udp)
        set_visible("rng-backend-type", is_egd)
        set_visible("rng-connect-host", is_egd and (udp or not bind))
        set_visible("rng-connect-service", is_egd and (udp or not bind))
        set_visible("rng-bind-host", is_egd and (udp or bind))
        set_visible("rng-bind-service", is_egd and (udp or bind))

        for k, prop in values.items():
            val = "-"
            if dev.supports_property(prop):
                val = getattr(dev, prop) or "-"
                r = rewriter.get(k)
                if r:
                    val = r(val)
            self.widget(k).set_text(val)
            if "rate" in k:
                uiutil.set_grid_row_visible(self.widget(k), val != "-")

        if is_egd and not udp:
            mode = VirtualRNGDevice.get_pretty_mode(dev.backend_mode()[0])
            self.widget("rng-mode").set_text(mode)

    def refresh_char_page(self):
        chardev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not chardev:
            return

        show_target_type = not (chardev.virtual_device_type in
                                ["serial", "parallel"])
        show_target_name = chardev.virtual_device_type == "channel"

        def show_ui(param, val=None):
            widgetname = "char-" + param.replace("_", "-")
            doshow = chardev.supports_property(param, ro=True)

            # Exception: don't show target type for serial/parallel
            if (param == "target_type" and not show_target_type):
                doshow = False
            if (param == "target_name" and not show_target_name):
                doshow = False

            if not val and doshow:
                val = getattr(chardev, param)

            uiutil.set_grid_row_visible(self.widget(widgetname), doshow)
            self.widget(widgetname).set_text(val or "-")

        def build_host_str(base):
            if (not chardev.supports_property(base + "_host") or
                not chardev.supports_property(base + "_port")):
                return ""

            host = getattr(chardev, base + "_host") or ""
            port = getattr(chardev, base + "_port") or ""

            ret = str(host)
            if port:
                ret += ":%s" % str(port)
            return ret

        char_type = chardev.virtual_device_type.capitalize()
        target_port = chardev.target_port
        dev_type = chardev.type or "pty"
        primary = hasattr(chardev, "virtmanager_console_dup")

        typelabel = ""
        if char_type == "serial":
            typelabel = _("Serial Device")
        elif char_type == "parallel":
            typelabel = _("Parallel Device")
        elif char_type == "console":
            typelabel = _("Console Device")
        elif char_type == "channel":
            typelabel = _("Channel Device")
        else:
            typelabel = _("%s Device") % char_type.capitalize()

        if (target_port is not None and
                chardev.virtual_device_type == "console"):
            typelabel += " %s" % (int(target_port) + 1)
        if target_port is not None and not show_target_type:
            typelabel += " %s" % (int(target_port) + 1)
        if primary:
            typelabel += " (%s)" % _("Primary Console")
        typelabel = "<b>%s</b>" % typelabel

        self.widget("char-type").set_markup(typelabel)
        self.widget("char-dev-type").set_text(dev_type)

        # Device type specific properties, only show if apply to the cur dev
        show_ui("source_host", build_host_str("source"))
        show_ui("bind_host", build_host_str("bind"))
        show_ui("source_path")
        show_ui("target_type")
        show_ui("target_name")

    def refresh_hostdev_page(self):
        hostdev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not hostdev:
            return

        rom_bar = hostdev.rom_bar
        if rom_bar is None:
            rom_bar = True

        devtype = hostdev.type
        if hostdev.type == 'usb':
            devtype = 'usb_device'

        nodedev = None
        for trydev in self.vm.conn.filter_nodedevs(devtype, None):
            if trydev.xmlobj.compare_to_hostdev(hostdev):
                nodedev = trydev.xmlobj

        pretty_name = None
        if nodedev:
            pretty_name = nodedev.pretty_name()
        if not pretty_name:
            pretty_name = hostdev.pretty_name()

        uiutil.set_grid_row_visible(
            self.widget("hostdev-rombar"), hostdev.type == "pci")

        devlabel = "<b>" + _("Physical %s Device") % hostdev.type.upper() + "</b>"
        self.widget("hostdev-title").set_markup(devlabel)
        self.widget("hostdev-source").set_text(pretty_name)
        self.widget("hostdev-rombar").set_active(rom_bar)

    def refresh_video_page(self):
        vid = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not vid:
            return

        model = vid.model
        if model == "qxl" and vid.vgamem:
            ram = vid.vgamem
        else:
            ram = vid.vram
        heads = vid.heads
        try:
            ramlabel = ram and "%d MiB" % (int(ram) / 1024) or "-"
        except Exception:
            ramlabel = "-"

        self.widget("video-ram").set_text(ramlabel)
        self.widget("video-heads").set_text(heads and str(heads) or "-")

        uiutil.set_list_selection(self.widget("video-model"), model)

        if vid.accel3d is None:
            self.widget("video-3d").set_inconsistent(True)
        else:
            self.widget("video-3d").set_active(vid.accel3d)

    def refresh_watchdog_page(self):
        watch = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not watch:
            return

        model = watch.model
        action = watch.action

        uiutil.set_list_selection(self.widget("watchdog-model"), model)
        uiutil.set_list_selection(self.widget("watchdog-action"), action)

    def refresh_controller_page(self):
        dev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not dev:
            return

        can_remove = True
        if self.vm.get_xmlobj().os.is_x86() and dev.type == "usb":
            can_remove = False
        if dev.type == "pci":
            can_remove = False
        self.widget("config-remove").set_sensitive(can_remove)

        type_label = dev.pretty_desc()
        self.widget("controller-type").set_text(type_label)

        combo = self.widget("controller-model")
        vmmAddHardware.populate_controller_model_combo(combo, dev.type)
        show_model = (dev.model or len(combo.get_model()) > 1)
        if dev.type == "pci":
            show_model = False
        uiutil.set_grid_row_visible(combo, show_model)
        uiutil.set_list_selection(self.widget("controller-model"),
            dev.model or None)

    def refresh_filesystem_page(self):
        dev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not dev:
            return

        self.fsDetails.set_dev(dev)
        self.fsDetails.update_fs_rows()

    def refresh_boot_page(self):
        # Refresh autostart
        try:
            # Older libvirt versions return None if not supported
            autoval = self.vm.get_autostart()
        except libvirt.libvirtError:
            autoval = None

        # Autostart
        autostart_chk = self.widget("boot-autostart")
        enable_autostart = (autoval is not None)
        autostart_chk.set_sensitive(enable_autostart)
        autostart_chk.set_active(enable_autostart and autoval or False)

        show_kernel = not self.vm.is_container()
        show_init = self.vm.is_container()
        show_boot = (not self.vm.is_container() and not self.vm.is_xenpv())

        uiutil.set_grid_row_visible(
            self.widget("boot-order-frame"), show_boot)
        uiutil.set_grid_row_visible(
            self.widget("boot-kernel-expander"), show_kernel)
        uiutil.set_grid_row_visible(
            self.widget("boot-init-frame"), show_init)

        # Kernel/initrd boot
        kernel, initrd, dtb, args = self.vm.get_boot_kernel_info()
        expand = bool(kernel or dtb or initrd or args)

        def keep_text(wname, guestval):
            # If the user unsets kernel/initrd by unchecking the
            # 'enable kernel boot' box, we keep the previous values cached
            # in the text fields to allow easy switching back and forth.
            guestval = guestval or ""
            if self.get_text(wname) and not guestval:
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
        show_dtb = (self.get_text("boot-dtb") or
            self.vm.get_hv_type() == "test" or
            "arm" in arch or "microblaze" in arch or "ppc" in arch)
        self.widget("boot-dtb-label").set_visible(show_dtb)
        self.widget("boot-dtb-box").set_visible(show_dtb)

        # <init> populate
        init, initargs = self.vm.get_init()
        self.widget("boot-init-path").set_text(init or "")
        self.widget("boot-init-args").set_text(initargs or "")

        # Boot menu populate
        menu = self.vm.get_boot_menu() or False
        self.widget("boot-menu").set_active(menu)
        self.repopulate_boot_order()


    ############################
    # Hardware list population #
    ############################

    def populate_hw_list(self):
        hw_list_model = self.widget("hw-list").get_model()
        hw_list_model.clear()

        def add_hw_list_option(title, page_id, icon_name):
            hw_list_model.append([title, icon_name,
                                  Gtk.IconSize.LARGE_TOOLBAR,
                                  page_id, title])

        add_hw_list_option(_("Overview"), HW_LIST_TYPE_GENERAL, "computer")
        if not self.is_customize_dialog:
            if self.config.support_inspection:
                add_hw_list_option(_("OS information"),
                    HW_LIST_TYPE_INSPECTION, "computer")
            add_hw_list_option(_("Performance"), HW_LIST_TYPE_STATS,
                               "utilities-system-monitor")
        add_hw_list_option(_("CPUs"), HW_LIST_TYPE_CPU, "device_cpu")
        add_hw_list_option(_("Memory"), HW_LIST_TYPE_MEMORY, "device_mem")
        add_hw_list_option(_("Boot Options"), HW_LIST_TYPE_BOOT, "system-run")

        self.repopulate_hw_list()

    def repopulate_hw_list(self):
        hw_list = self.widget("hw-list")
        hw_list_model = hw_list.get_model()

        currentDevices = []

        def dev_cmp(origdev, newdev):
            if isinstance(origdev, str):
                return False

            if origdev == newdev:
                return True

            if not origdev.get_root_xpath():
                return False

            return origdev.get_root_xpath() == newdev.get_root_xpath()

        def add_hw_list_option(idx, name, page_id, info, icon_name):
            hw_list_model.insert(idx, [name, icon_name,
                                       Gtk.IconSize.LARGE_TOOLBAR,
                                       page_id, info])

        def update_hwlist(hwtype, dev):
            """
            See if passed hw is already in list, and if so, update info.
            If not in list, add it!
            """
            label = _label_for_device(dev)
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
            add_hw_list_option(insertAt, label, hwtype, dev, icon)


        for dev in self.vm.get_disk_devices():
            update_hwlist(HW_LIST_TYPE_DISK, dev)
        for dev in self.vm.get_network_devices():
            update_hwlist(HW_LIST_TYPE_NIC, dev)
        for dev in self.vm.get_input_devices():
            update_hwlist(HW_LIST_TYPE_INPUT, dev)
        for dev in self.vm.get_graphics_devices():
            update_hwlist(HW_LIST_TYPE_GRAPHICS, dev)
        for dev in self.vm.get_sound_devices():
            update_hwlist(HW_LIST_TYPE_SOUND, dev)
        for dev in self.vm.get_char_devices():
            update_hwlist(HW_LIST_TYPE_CHAR, dev)
        for dev in self.vm.get_hostdev_devices():
            update_hwlist(HW_LIST_TYPE_HOSTDEV, dev)
        for dev in self.vm.get_redirdev_devices():
            update_hwlist(HW_LIST_TYPE_REDIRDEV, dev)
        for dev in self.vm.get_video_devices():
            update_hwlist(HW_LIST_TYPE_VIDEO, dev)
        for dev in self.vm.get_watchdog_devices():
            update_hwlist(HW_LIST_TYPE_WATCHDOG, dev)

        for dev in self.vm.get_controller_devices():
            # skip USB2 ICH9 companion controllers
            if dev.model in ["ich9-uhci1", "ich9-uhci2", "ich9-uhci3"]:
                continue

            # These are all parts of a default PCIe setup, which we
            # condense down to one listing
            if dev.model in ["pcie-root-port", "dmi-to-pci-bridge",
                             "pci-bridge"]:
                continue

            update_hwlist(HW_LIST_TYPE_CONTROLLER, dev)

        for dev in self.vm.get_filesystem_devices():
            update_hwlist(HW_LIST_TYPE_FILESYSTEM, dev)
        for dev in self.vm.get_smartcard_devices():
            update_hwlist(HW_LIST_TYPE_SMARTCARD, dev)
        for dev in self.vm.get_tpm_devices():
            update_hwlist(HW_LIST_TYPE_TPM, dev)
        for dev in self.vm.get_rng_devices():
            update_hwlist(HW_LIST_TYPE_RNG, dev)
        for dev in self.vm.get_panic_devices():
            update_hwlist(HW_LIST_TYPE_PANIC, dev)

        devs = range(len(hw_list_model))
        devs.reverse()
        for i in devs:
            _iter = hw_list_model.iter_nth_child(None, i)
            olddev = hw_list_model[i][HW_LIST_COL_DEVICE]

            # Existing device, don't remove it
            if type(olddev) is str or olddev in currentDevices:
                continue

            hw_list_model.remove(_iter)

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
            icon = _icon_for_device(dev)
            label = _label_for_device(dev)

            ret.append([dev.vmmidstr, label, icon, False, True])

        if not ret:
            ret.append([None, _("No bootable devices"), None, False, False])
        return ret

    def repopulate_boot_order(self):
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

#
# Copyright (C) 2006-2008 Red Hat, Inc.
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

import gtk

import libvirt

import virtManager.uihelpers as uihelpers
from virtManager.storagebrowse import vmmStorageBrowser
from virtManager.baseclass import vmmGObjectUI
from virtManager.addhardware import vmmAddHardware
from virtManager.choosecd import vmmChooseCD
from virtManager.console import vmmConsolePages
from virtManager.serialcon import vmmSerialConsole
from virtManager.graphwidgets import Sparkline
from virtManager import util as util

import virtinst

_comboentry_xml = """
<interface>
    <object class="GtkComboBoxEntry" id="cpu-model">
        <property name="visible">True</property>
        <signal name="changed" handler="on_cpu_model_changed"/>
    </object>
    <object class="GtkComboBoxEntry" id="disk-format">
        <property name="visible">True</property>
        <signal name="changed" handler="on_disk_format_changed"/>
    </object>
</interface>
"""

# Parameters that can be editted in the details window
EDIT_TOTAL = 36
(EDIT_NAME,
EDIT_ACPI,
EDIT_APIC,
EDIT_CLOCK,
EDIT_MACHTYPE,
EDIT_SECURITY,
EDIT_DESC,

EDIT_VCPUS,
EDIT_CPUSET,
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
EDIT_DISK_CACHE,
EDIT_DISK_IO,
EDIT_DISK_BUS,
EDIT_DISK_SERIAL,
EDIT_DISK_FORMAT,

EDIT_SOUND_MODEL,

EDIT_SMARTCARD_MODE,

EDIT_NET_MODEL,
EDIT_NET_VPORT,
EDIT_NET_SOURCE,

EDIT_GFX_PASSWD,
EDIT_GFX_TYPE,
EDIT_GFX_KEYMAP,

EDIT_VIDEO_MODEL,

EDIT_WATCHDOG_MODEL,
EDIT_WATCHDOG_ACTION,

EDIT_CONTROLLER_MODEL
) = range(EDIT_TOTAL)


# Columns in hw list model
HW_LIST_COL_LABEL = 0
HW_LIST_COL_ICON_NAME = 1
HW_LIST_COL_ICON_SIZE = 2
HW_LIST_COL_TYPE = 3
HW_LIST_COL_DEVICE = 4

# Types for the hw list model: numbers specify what order they will be listed
HW_LIST_TYPE_GENERAL = 0
HW_LIST_TYPE_STATS = 1
HW_LIST_TYPE_CPU = 2
HW_LIST_TYPE_MEMORY = 3
HW_LIST_TYPE_BOOT = 4
HW_LIST_TYPE_DISK = 5
HW_LIST_TYPE_NIC = 6
HW_LIST_TYPE_INPUT = 7
HW_LIST_TYPE_GRAPHICS = 8
HW_LIST_TYPE_SOUND = 9
HW_LIST_TYPE_CHAR = 10
HW_LIST_TYPE_HOSTDEV = 11
HW_LIST_TYPE_VIDEO = 12
HW_LIST_TYPE_WATCHDOG = 13
HW_LIST_TYPE_CONTROLLER = 14
HW_LIST_TYPE_FILESYSTEM = 15
HW_LIST_TYPE_SMARTCARD = 16
HW_LIST_TYPE_REDIRDEV = 17

remove_pages = [HW_LIST_TYPE_NIC, HW_LIST_TYPE_INPUT,
                HW_LIST_TYPE_GRAPHICS, HW_LIST_TYPE_SOUND, HW_LIST_TYPE_CHAR,
                HW_LIST_TYPE_HOSTDEV, HW_LIST_TYPE_DISK, HW_LIST_TYPE_VIDEO,
                HW_LIST_TYPE_WATCHDOG, HW_LIST_TYPE_CONTROLLER,
                HW_LIST_TYPE_FILESYSTEM, HW_LIST_TYPE_SMARTCARD,
                HW_LIST_TYPE_REDIRDEV]

# Boot device columns
BOOT_DEV_TYPE = 0
BOOT_LABEL = 1
BOOT_ICON = 2
BOOT_ACTIVE = 3

# Main tab pages
PAGE_CONSOLE = 0
PAGE_DETAILS = 1
PAGE_DYNAMIC_OFFSET = 2

def prettyify_disk_bus(bus):
    if bus in ["ide", "sata", "scsi", "usb"]:
        return bus.upper()

    if bus in ["xen"]:
        return bus.capitalize()

    if bus == "virtio":
        return "VirtIO"

    if bus == "spapr-vscsi":
        return "vSCSI"

    return bus

def prettyify_disk(devtype, bus, idx):
    busstr = prettyify_disk_bus(bus) or ""

    if devtype == "floppy":
        devstr = "Floppy"
        busstr = ""
    elif devtype == "cdrom":
        devstr = "CDROM"
    else:
        devstr = devtype.capitalize()

    if busstr:
        ret = "%s %s" % (busstr, devstr)
    else:
        ret = devstr

    return "%s %s" % (ret, idx)

def safeint(val, fmt="%.3d"):
    try:
        int(val)
    except:
        return str(val)
    return fmt % int(val)

def prettyify_bytes(val):
    if val > (1024 * 1024 * 1024):
        return "%2.2f GB" % (val / (1024.0 * 1024.0 * 1024.0))
    else:
        return "%2.2f MB" % (val / (1024.0 * 1024.0))

def build_redir_label(redirdev):
    # String shown in the devices details section
    addrlabel = ""
    # String shown in the VMs hardware list
    hwlabel = ""

    if redirdev.type == 'spicevmc':
        addrlabel = None
    elif redirdev.type == 'tcp':
        addrlabel += _("%s:%s") % (redirdev.host, redirdev.service)
    else:
        raise RuntimeError("unhandled redirection kind: %s" % redirdev.type)

    hwlabel = _("Redirected %s") % redirdev.bus.upper()

    return addrlabel, hwlabel


def build_hostdev_label(hostdev):
    # String shown in the devices details section
    srclabel = ""
    # String shown in the VMs hardware list
    hwlabel = ""

    typ = hostdev.type
    vendor = hostdev.vendor
    product = hostdev.product
    addrbus = hostdev.bus
    addrdev = hostdev.device
    addrslt = hostdev.slot
    addrfun = hostdev.function
    addrdom = hostdev.domain

    def dehex(val):
        if val.startswith("0x"):
            val = val[2:]
        return val

    hwlabel = typ.upper()
    srclabel = typ.upper()

    if vendor and product:
        # USB by vendor + product
        devstr = " %s:%s" % (dehex(vendor), dehex(product))
        srclabel += devstr
        hwlabel += devstr

    elif addrbus and addrdev:
        # USB by bus + dev
        srclabel += (" Bus %s Device %s" %
                     (safeint(addrbus), safeint(addrdev)))
        hwlabel += " %s:%s" % (safeint(addrbus), safeint(addrdev))

    elif addrbus and addrslt and addrfun and addrdom:
        # PCI by bus:slot:function
        devstr = (" %s:%s:%s.%s" %
                  (dehex(addrdom), dehex(addrbus),
                   dehex(addrslt), dehex(addrfun)))
        srclabel += devstr
        hwlabel += devstr

    return srclabel, hwlabel

def lookup_nodedev(vmmconn, hostdev):
    def intify(val, do_hex=False):
        try:
            if do_hex:
                return int(val or '0x00', 16)
            else:
                return int(val)
        except:
            return -1

    def attrVal(node, attr):
        if not hasattr(node, attr):
            return None
        return getattr(node, attr)

    devtype     = hostdev.type
    vendor_id   = hostdev.vendor or -1
    product_id  = hostdev.product or -1
    device      = intify(hostdev.device, True)
    bus         = intify(hostdev.bus, True)
    domain      = intify(hostdev.domain, True)
    func        = intify(hostdev.function, True)
    slot        = intify(hostdev.slot, True)
    found_dev = None

    # For USB we want a device, not a bus
    if devtype == 'usb':
        devtype = 'usb_device'

    devs = vmmconn.get_nodedevs(devtype, None)
    for dev in devs:
        # Try to match with product_id|vendor_id|bus|device
        if (attrVal(dev, "product_id") == product_id and
            attrVal(dev, "vendor_id") == vendor_id and
            attrVal(dev, "bus") == bus and
            attrVal(dev, "device") == device):
            found_dev = dev
            break
        else:
            # Try to get info from bus/addr
            dev_id = intify(attrVal(dev, "device"))
            bus_id = intify(attrVal(dev, "bus"))
            dom_id = intify(attrVal(dev, "domain"))
            func_id = intify(attrVal(dev, "function"))
            slot_id = intify(attrVal(dev, "slot"))

            if ((dev_id == device and bus_id == bus) or
                (dom_id == domain and func_id == func and
                 bus_id == bus and slot_id == slot)):
                found_dev = dev
                break

    return found_dev

class vmmDetails(vmmGObjectUI):
    def __init__(self, vm, parent=None):
        vmmGObjectUI.__init__(self, "vmm-details.ui", "vmm-details")
        self.vm = vm
        self.conn = self.vm.conn

        self.is_customize_dialog = False
        if parent:
            # Details window is being abused as a 'configure before install'
            # dialog, set things as appropriate
            self.is_customize_dialog = True
            self.topwin.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_DIALOG)
            self.topwin.set_transient_for(parent)

            self.widget("toolbar-box").show()
            self.widget("customize-toolbar").show()
            self.widget("details-toolbar").hide()
            self.widget("details-menubar").hide()
            pages = self.widget("details-pages")
            pages.set_current_page(PAGE_DETAILS)


        self.active_edits = []

        self.serial_tabs = []
        self.last_console_page = PAGE_CONSOLE
        self.addhw = None
        self.media_choosers = {"cdrom": None, "floppy": None}
        self.storage_browser = None

        self.ignorePause = False
        self.ignoreDetails = False
        self._cpu_copy_host = False

        self.window.add_from_string(_comboentry_xml)
        self.widget("hbox17").pack_start(self.widget("disk-format"),
                                         False, True, 0)
        self.widget("hbox21").pack_start(self.widget("cpu-model"),
                                         False, True, 0)

        self.console = vmmConsolePages(self.vm, self.window)

        # Set default window size
        w, h = self.vm.get_details_window_size()
        self.topwin.set_default_size(w or 800, h or 600)

        self.oldhwrow = None
        self.addhwmenu = None
        self.keycombo_menu = None
        self.init_menus()
        self.init_details()

        self.cpu_usage_graph = None
        self.memory_usage_graph = None
        self.disk_io_graph = None
        self.network_traffic_graph = None
        self.init_graphs()

        self.window.connect_signals({
            "on_close_details_clicked": self.close,
            "on_details_menu_close_activate": self.close,
            "on_vmm_details_delete_event": self.close,
            "on_vmm_details_configure_event": self.window_resized,
            "on_details_menu_quit_activate": self.exit_app,

            "on_control_vm_details_toggled": self.details_console_changed,
            "on_control_vm_console_toggled": self.details_console_changed,
            "on_control_run_clicked": self.control_vm_run,
            "on_control_shutdown_clicked": self.control_vm_shutdown,
            "on_control_pause_toggled": self.control_vm_pause,
            "on_control_fullscreen_toggled": self.control_fullscreen,

            "on_details_customize_finish_clicked": self.customize_finish,
            "on_details_cancel_customize_clicked": self.close,

            "on_details_menu_run_activate": self.control_vm_run,
            "on_details_menu_poweroff_activate": self.control_vm_shutdown,
            "on_details_menu_reboot_activate": self.control_vm_reboot,
            "on_details_menu_save_activate": self.control_vm_save,
            "on_details_menu_destroy_activate": self.control_vm_destroy,
            "on_details_menu_pause_activate": self.control_vm_pause,
            "on_details_menu_clone_activate": self.control_vm_clone,
            "on_details_menu_migrate_activate": self.control_vm_migrate,
            "on_details_menu_screenshot_activate": self.control_vm_screenshot,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,
            "on_details_menu_view_manager_activate": self.view_manager,
            "on_details_menu_view_details_toggled": self.details_console_changed,
            "on_details_menu_view_console_toggled": self.details_console_changed,

            "on_details_pages_switch_page": self.switch_page,

            "on_overview_name_changed": (self.enable_apply, EDIT_NAME),
            "on_overview_acpi_changed": self.config_acpi_changed,
            "on_overview_apic_changed": self.config_apic_changed,
            "on_overview_clock_changed": (self.enable_apply, EDIT_CLOCK),
            "on_machine_type_changed": (self.enable_apply, EDIT_MACHTYPE),
            "on_security_label_changed": (self.enable_apply, EDIT_SECURITY),
            "on_security_type_changed": self.security_type_changed,

            "on_config_vcpus_changed": self.config_vcpus_changed,
            "on_config_maxvcpus_changed": self.config_maxvcpus_changed,
            "on_config_vcpupin_changed": (self.enable_apply, EDIT_CPUSET),
            "on_config_vcpupin_generate_clicked": self.config_vcpupin_generate,
            "on_cpu_model_changed": (self.enable_apply, EDIT_CPU),
            "on_cpu_cores_changed": (self.enable_apply, EDIT_TOPOLOGY),
            "on_cpu_sockets_changed": (self.enable_apply, EDIT_TOPOLOGY),
            "on_cpu_threads_changed": (self.enable_apply, EDIT_TOPOLOGY),
            "on_cpu_copy_host_clicked": self.config_cpu_copy_host,
            "on_cpu_topology_enable_toggled": self.config_cpu_topology_enable,

            "on_config_memory_changed": self.config_memory_changed,
            "on_config_maxmem_changed": self.config_maxmem_changed,

            "on_config_boot_moveup_clicked" : (self.config_boot_move, True),
            "on_config_boot_movedown_clicked" : (self.config_boot_move,
                                                 False),
            "on_config_autostart_changed": (self.enable_apply, EDIT_AUTOSTART),
            "on_boot_menu_changed": (self.enable_apply, EDIT_BOOTMENU),
            "on_boot_kernel_changed": (self.enable_apply, EDIT_KERNEL),
            "on_boot_kernel_initrd_changed": (self.enable_apply, EDIT_KERNEL),
            "on_boot_kernel_args_changed": (self.enable_apply, EDIT_KERNEL),
            "on_boot_kernel_browse_clicked": self.browse_kernel,
            "on_boot_kernel_initrd_browse_clicked": self.browse_initrd,
            "on_boot_init_path_changed": (self.enable_apply, EDIT_INIT),

            "on_disk_readonly_changed": (self.enable_apply, EDIT_DISK_RO),
            "on_disk_shareable_changed": (self.enable_apply, EDIT_DISK_SHARE),
            "on_disk_cache_combo_changed": (self.enable_apply,
                                            EDIT_DISK_CACHE),
            "on_disk_io_combo_changed": (self.enable_apply, EDIT_DISK_IO),
            "on_disk_bus_combo_changed": (self.enable_apply, EDIT_DISK_BUS),
            "on_disk_format_changed": (self.enable_apply, EDIT_DISK_FORMAT),
            "on_disk_serial_changed": (self.enable_apply, EDIT_DISK_SERIAL),

            "on_network_source_combo_changed": (self.enable_apply,
                                                EDIT_NET_SOURCE),
            "on_network_bridge_changed": (self.enable_apply,
                                          EDIT_NET_SOURCE),
            "on_network-source-mode-combo_changed": (self.enable_apply,
                                                     EDIT_NET_SOURCE),
            "on_network_model_combo_changed": (self.enable_apply,
                                               EDIT_NET_MODEL),

            "on_vport_type_changed": (self.enable_apply, EDIT_NET_VPORT),
            "on_vport_managerid_changed": (self.enable_apply,
                                           EDIT_NET_VPORT),
            "on_vport_typeid_changed": (self.enable_apply,
                                        EDIT_NET_VPORT),
            "on_vport_typeidversion_changed": (self.enable_apply,
                                               EDIT_NET_VPORT),
            "on_vport_instanceid_changed": (self.enable_apply,
                                            EDIT_NET_VPORT),

            "on_gfx_type_combo_changed": (self.enable_apply, EDIT_GFX_TYPE),
            "on_vnc_keymap_combo_changed": (self.enable_apply,
                                            EDIT_GFX_KEYMAP),
            "on_vnc_password_changed": (self.enable_apply, EDIT_GFX_PASSWD),

            "on_sound_model_combo_changed": (self.enable_apply,
                                             EDIT_SOUND_MODEL),

            "on_video_model_combo_changed": (self.enable_apply,
                                             EDIT_VIDEO_MODEL),

            "on_watchdog_model_combo_changed": (self.enable_apply,
                                                EDIT_WATCHDOG_MODEL),
            "on_watchdog_action_combo_changed": (self.enable_apply,
                                                 EDIT_WATCHDOG_ACTION),

            "on_smartcard_mode_combo_changed": (self.enable_apply,
                                                EDIT_SMARTCARD_MODE),

            "on_config_apply_clicked": self.config_apply,
            "on_config_cancel_clicked": self.config_cancel,

            "on_details_help_activate": self.show_help,

            "on_config_cdrom_connect_clicked": self.toggle_storage_media,
            "on_config_remove_clicked": self.remove_xml_dev,
            "on_add_hardware_button_clicked": self.add_hardware,

            "on_hw_list_button_press_event": self.popup_addhw_menu,

            # Listeners stored in vmmConsolePages
            "on_details_menu_view_fullscreen_activate": self.console.toggle_fullscreen,
            "on_details_menu_view_size_to_vm_activate": self.console.size_to_vm,
            "on_details_menu_view_scale_always_toggled": self.console.set_scale_type,
            "on_details_menu_view_scale_fullscreen_toggled": self.console.set_scale_type,
            "on_details_menu_view_scale_never_toggled": self.console.set_scale_type,

            "on_console_pages_switch_page": self.console.page_changed,
            "on_console_auth_password_activate": self.console.auth_login,
            "on_console_auth_login_clicked": self.console.auth_login,
            "on_controller_model_combo_changed": (self.enable_apply,
                                                  EDIT_CONTROLLER_MODEL),
        })

        # Deliberately keep all this after signal connection
        self.vm.connect("status-changed", self.refresh_vm_state)
        self.vm.connect("config-changed", self.refresh_vm_state)
        self.vm.connect("resources-sampled", self.refresh_resources)
        self.widget("hw-list").get_selection().connect("changed",
                                                       self.hw_changed)
        self.widget("config-boot-list").get_selection().connect(
                                            "changed",
                                            self.config_bootdev_selected)

        finish_img = gtk.image_new_from_stock(gtk.STOCK_ADD,
                                              gtk.ICON_SIZE_BUTTON)
        self.widget("add-hardware-button").set_image(finish_img)

        self.populate_hw_list()
        self.repopulate_boot_list()

        self.hw_selected()
        self.refresh_vm_state()

    def _cleanup(self):
        self.close()

        self.oldhwrow = None

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

        for serial in self.serial_tabs:
            self._close_serial_tab(serial)

        self.console.cleanup()
        self.console = None

        self.vm = None
        self.conn = None
        self.addhwmenu = None

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

        return self._close(customize_finish=True)

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing VM details: %s", self.vm)
        return self._close()

    def _close(self, customize_finish=False):
        fs = self.widget("details-menu-view-fullscreen")
        if fs.get_active():
            fs.set_active(False)

        if not self.is_visible():
            return

        self.topwin.hide()
        if (self.console.viewer and
            self.console.viewer.display and
            self.console.viewer.display.flags() & gtk.VISIBLE):
            try:
                self.console.close_viewer()
            except:
                logging.error("Failure when disconnecting from desktop server")

        if customize_finish:
            self.emit("customize-finished")
        else:
            self.emit("details-closed")
        return 1

    def is_visible(self):
        return bool(self.topwin.flags() & gtk.VISIBLE)


    ##########################
    # Initialization helpers #
    ##########################

    def init_menus(self):
        # Shutdown button menu
        uihelpers.build_shutdown_button_menu(self.widget("control-shutdown"),
                                             self.control_vm_shutdown,
                                             self.control_vm_reboot,
                                             self.control_vm_destroy,
                                             self.control_vm_save)

        icon_name = self.config.get_shutdown_icon_name()
        for name in ["details-menu-shutdown",
                     "details-menu-reboot",
                     "details-menu-poweroff",
                     "details-menu-destroy"]:
            image = gtk.image_new_from_icon_name(icon_name, gtk.ICON_SIZE_MENU)
            self.widget(name).set_image(image)

        # Add HW popup menu
        self.addhwmenu = gtk.Menu()

        addHW = gtk.ImageMenuItem(_("_Add Hardware"))
        addHWImg = gtk.Image()
        addHWImg.set_from_stock(gtk.STOCK_ADD, gtk.ICON_SIZE_MENU)
        addHW.set_image(addHWImg)
        addHW.show()
        addHW.connect("activate", self.add_hardware)

        rmHW = gtk.ImageMenuItem(_("_Remove Hardware"))
        rmHWImg = gtk.Image()
        rmHWImg.set_from_stock(gtk.STOCK_REMOVE, gtk.ICON_SIZE_MENU)
        rmHW.set_image(rmHWImg)
        rmHW.show()
        rmHW.connect("activate", self.remove_xml_dev)

        self.addhwmenu.add(addHW)
        self.addhwmenu.add(rmHW)

        # Serial list menu
        smenu = gtk.Menu()
        smenu.connect("show", self.populate_serial_menu)
        self.widget("details-menu-view-serial-list").set_submenu(smenu)

        # Don't allowing changing network/disks for Dom0
        dom0 = self.vm.is_management_domain()
        self.widget("add-hardware-button").set_sensitive(not dom0)

        self.widget("hw-panel").set_show_tabs(False)
        self.widget("details-pages").set_show_tabs(False)
        self.widget("console-pages").set_show_tabs(False)
        self.widget("details-menu-view-toolbar").set_active(
                                    self.config.get_details_show_toolbar())

        # Keycombo menu (ctrl+alt+del etc.)
        self.keycombo_menu = uihelpers.build_keycombo_menu(
                                                    self.console.send_key)
        self.widget("details-menu-send-key").set_submenu(self.keycombo_menu)

        # XXX: Help docs useless/out of date
        self.widget("help_menuitem").hide()

    def init_graphs(self):
        graph_table = self.widget("graph-table")

        self.cpu_usage_graph = Sparkline()
        self.cpu_usage_graph.set_property("reversed", True)
        graph_table.attach(self.cpu_usage_graph, 1, 2, 0, 1)

        self.memory_usage_graph = Sparkline()
        self.memory_usage_graph.set_property("reversed", True)
        graph_table.attach(self.memory_usage_graph, 1, 2, 1, 2)

        self.disk_io_graph = Sparkline()
        self.disk_io_graph.set_property("reversed", True)
        self.disk_io_graph.set_property("filled", False)
        self.disk_io_graph.set_property("num_sets", 2)
        self.disk_io_graph.set_property("rgb", map(lambda x: x / 255.0,
                                        [0x82, 0x00, 0x3B, 0x29, 0x5C, 0x45]))
        graph_table.attach(self.disk_io_graph, 1, 2, 2, 3)

        self.network_traffic_graph = Sparkline()
        self.network_traffic_graph.set_property("reversed", True)
        self.network_traffic_graph.set_property("filled", False)
        self.network_traffic_graph.set_property("num_sets", 2)
        self.network_traffic_graph.set_property("rgb",
                                                map(lambda x: x / 255.0,
                                                    [0x82, 0x00, 0x3B,
                                                     0x29, 0x5C, 0x45]))
        graph_table.attach(self.network_traffic_graph, 1, 2, 3, 4)

        graph_table.show_all()

    def init_details(self):
        # Hardware list
        # [ label, icon name, icon size, hw type, hw data/class]
        hw_list_model = gtk.ListStore(str, str, int, int, object)
        self.widget("hw-list").set_model(hw_list_model)

        hwCol = gtk.TreeViewColumn("Hardware")
        hwCol.set_spacing(6)
        hwCol.set_min_width(165)
        hw_txt = gtk.CellRendererText()
        hw_img = gtk.CellRendererPixbuf()
        hwCol.pack_start(hw_img, False)
        hwCol.pack_start(hw_txt, True)
        hwCol.add_attribute(hw_txt, 'text', HW_LIST_COL_LABEL)
        hwCol.add_attribute(hw_img, 'stock-size', HW_LIST_COL_ICON_SIZE)
        hwCol.add_attribute(hw_img, 'icon-name', HW_LIST_COL_ICON_NAME)
        self.widget("hw-list").append_column(hwCol)

        # Description text view
        desc = self.widget("overview-description")
        buf = gtk.TextBuffer()
        buf.connect("changed", self.enable_apply, EDIT_DESC)
        desc.set_buffer(buf)

        # List of applications.
        apps_list = self.widget("inspection-apps")
        apps_model = gtk.ListStore(str, str, str)
        apps_list.set_model(apps_model)

        name_col = gtk.TreeViewColumn(_("Name"))
        version_col = gtk.TreeViewColumn(_("Version"))
        summary_col = gtk.TreeViewColumn()

        apps_list.append_column(name_col)
        apps_list.append_column(version_col)
        apps_list.append_column(summary_col)

        name_text = gtk.CellRendererText()
        name_col.pack_start(name_text, True)
        name_col.add_attribute(name_text, 'text', 0)
        name_col.set_sort_column_id(0)

        version_text = gtk.CellRendererText()
        version_col.pack_start(version_text, True)
        version_col.add_attribute(version_text, 'text', 1)
        version_col.set_sort_column_id(1)

        summary_text = gtk.CellRendererText()
        summary_col.pack_start(summary_text, True)
        summary_col.add_attribute(summary_text, 'text', 2)
        summary_col.set_sort_column_id(2)

        # Clock combo
        clock_combo = self.widget("overview-clock-combo")
        clock_model = gtk.ListStore(str)
        clock_combo.set_model(clock_model)
        text = gtk.CellRendererText()
        clock_combo.pack_start(text, True)
        clock_combo.add_attribute(text, 'text', 0)
        clock_model.set_sort_column_id(0, gtk.SORT_ASCENDING)
        for offset in ["localtime", "utc"]:
            clock_model.append([offset])

        arch = self.vm.get_arch()
        caps = self.vm.conn.get_capabilities()
        machines = []

        if len(caps.guests) > 0:
            for guest in caps.guests:
                if len(guest.domains) > 0:
                    for domain in guest.domains:
                        machines = list(set(machines + domain.machines))

        if arch in ["i686", "x86_64"]:
            self.widget("label81").hide()
            self.widget("hbox30").hide()
        else:
            machtype_combo = self.widget("machine-type-combo")
            machtype_model = gtk.ListStore(str)
            machtype_combo.set_model(machtype_model)
            text = gtk.CellRendererText()
            machtype_combo.pack_start(text, True)
            machtype_combo.add_attribute(text, 'text', 0)
            machtype_model.set_sort_column_id(0, gtk.SORT_ASCENDING)

            if len(machines) > 0:
                for machine in machines:
                    machtype_model.append([machine])

        # Security info tooltips
        util.tooltip_wrapper(self.widget("security-static-info"),
            _("Static SELinux security type tells libvirt to always start the guest process with the specified label. The administrator is responsible for making sure the images are labeled correctly on disk."))
        util.tooltip_wrapper(self.widget("security-dynamic-info"),
            _("The dynamic SELinux security type tells libvirt to automatically pick a unique label for the guest process and guest image, ensuring total isolation of the guest. (Default)"))

        # VCPU Pinning list
        generate_cpuset = self.widget("config-vcpupin-generate")
        generate_warn = self.widget("config-vcpupin-generate-err")
        if not self.conn.get_capabilities().host.topology:
            generate_cpuset.set_sensitive(False)
            generate_warn.show()
            util.tooltip_wrapper(generate_warn,
                                 _("Libvirt did not detect NUMA capabilities."))


        # [ VCPU #, Currently running on Phys CPU #, CPU Pinning list ]
        vcpu_list = self.widget("config-vcpu-list")
        vcpu_model = gtk.ListStore(str, str, str)
        vcpu_list.set_model(vcpu_model)

        vcpuCol = gtk.TreeViewColumn(_("VCPU"))
        physCol = gtk.TreeViewColumn(_("On CPU"))
        pinCol  = gtk.TreeViewColumn(_("Pinning"))

        vcpu_list.append_column(vcpuCol)
        vcpu_list.append_column(physCol)
        vcpu_list.append_column(pinCol)

        vcpu_text = gtk.CellRendererText()
        vcpuCol.pack_start(vcpu_text, True)
        vcpuCol.add_attribute(vcpu_text, 'text', 0)
        vcpuCol.set_sort_column_id(0)

        phys_text = gtk.CellRendererText()
        physCol.pack_start(phys_text, True)
        physCol.add_attribute(phys_text, 'text', 1)
        physCol.set_sort_column_id(1)

        pin_text = gtk.CellRendererText()
        pin_text.set_property("editable", True)
        pin_text.connect("edited", self.config_vcpu_pin)
        pinCol.pack_start(pin_text, True)
        pinCol.add_attribute(pin_text, 'text', 2)

        # Boot device list
        boot_list = self.widget("config-boot-list")
        # model = [ XML boot type, display name, icon name, enabled ]
        boot_list_model = gtk.ListStore(str, str, str, bool)
        boot_list.set_model(boot_list_model)

        chkCol = gtk.TreeViewColumn()
        txtCol = gtk.TreeViewColumn()

        boot_list.append_column(chkCol)
        boot_list.append_column(txtCol)

        chk = gtk.CellRendererToggle()
        chk.connect("toggled", self.config_boot_toggled)
        chkCol.pack_start(chk, False)
        chkCol.add_attribute(chk, 'active', BOOT_ACTIVE)

        icon = gtk.CellRendererPixbuf()
        txtCol.pack_start(icon, False)
        txtCol.add_attribute(icon, 'icon-name', BOOT_ICON)

        text = gtk.CellRendererText()
        txtCol.pack_start(text, True)
        txtCol.add_attribute(text, 'text', BOOT_LABEL)
        txtCol.add_attribute(text, 'sensitive', BOOT_ACTIVE)

        no_default = not self.is_customize_dialog

        # CPU features
        caps = self.vm.conn.get_capabilities()
        cpu_values = None
        cpu_names = []
        all_features = []

        try:
            cpu_values = caps.get_cpu_values(self.vm.get_arch())
            cpu_names = sorted(map(lambda c: c.model, cpu_values.cpus),
                               key=str.lower)
            all_features = cpu_values.features
        except:
            logging.exception("Error populating CPU model list")

        # [ feature name, mode]
        feat_list = self.widget("cpu-features")
        feat_model = gtk.ListStore(str, str)
        feat_list.set_model(feat_model)

        nameCol = gtk.TreeViewColumn()
        polCol = gtk.TreeViewColumn()
        polCol.set_min_width(80)

        feat_list.append_column(nameCol)
        feat_list.append_column(polCol)

        # Feature name col
        name_text = gtk.CellRendererText()
        nameCol.pack_start(name_text, True)
        nameCol.add_attribute(name_text, 'text', 0)
        nameCol.set_sort_column_id(0)

        # Feature policy col
        feat_combo = gtk.CellRendererCombo()
        m = gtk.ListStore(str)
        for p in virtinst.CPUFeature.POLICIES:
            m.append([p])
        m.append(["default"])
        feat_combo.set_property("model", m)
        feat_combo.set_property("text-column", 0)
        feat_combo.set_property("editable", True)
        polCol.pack_start(feat_combo, False)
        polCol.add_attribute(feat_combo, 'text', 1)
        polCol.set_sort_column_id(1)

        def feature_changed(src, index, treeiter, model):
            model[index][1] = src.get_property("model")[treeiter][0]
            self.enable_apply(EDIT_CPU)

        feat_combo.connect("changed", feature_changed, feat_model)
        for name in all_features:
            feat_model.append([name, "default"])

        # CPU model combo
        cpu_model = self.widget("cpu-model")

        model = gtk.ListStore(str, object)
        cpu_model.set_model(model)
        cpu_model.set_text_column(0)
        model.set_sort_column_id(0, gtk.SORT_ASCENDING)
        for name in cpu_names:
            model.append([name, cpu_values.get_cpu(name)])

        # Disk cache combo
        disk_cache = self.widget("disk-cache-combo")
        uihelpers.build_cache_combo(self.vm, disk_cache)

        # Disk io combo
        disk_io = self.widget("disk-io-combo")
        uihelpers.build_io_combo(self.vm, disk_io)

        # Disk format combo
        format_list = self.widget("disk-format")
        uihelpers.build_storage_format_combo(self.vm, format_list)

        # Disk bus combo
        disk_bus = self.widget("disk-bus-combo")
        uihelpers.build_disk_bus_combo(self.vm, disk_bus)

        # Network source
        net_source = self.widget("network-source-combo")
        net_bridge = self.widget("network-bridge-box")
        source_mode_box   = self.widget("network-source-mode-box")
        source_mode_label = self.widget("network-source-mode")
        vport_expander = self.widget("vport-expander")
        uihelpers.init_network_list(net_source, net_bridge, source_mode_box,
                                    source_mode_label, vport_expander)

        # source mode
        source_mode = self.widget("network-source-mode-combo")
        uihelpers.build_source_mode_combo(self.vm, source_mode)

        # Network model
        net_model = self.widget("network-model-combo")
        uihelpers.build_netmodel_combo(self.vm, net_model)

        # Graphics type
        gfx_type = self.widget("gfx-type-combo")
        model = gtk.ListStore(str, str)
        gfx_type.set_model(model)
        text = gtk.CellRendererText()
        gfx_type.pack_start(text, True)
        gfx_type.add_attribute(text, 'text', 1)
        model.append([virtinst.VirtualGraphics.TYPE_VNC,
                      "VNC"])
        model.append([virtinst.VirtualGraphics.TYPE_SPICE,
                      "Spice"])
        gfx_type.set_active(-1)

        # Graphics keymap
        gfx_keymap = self.widget("gfx-keymap-combo")
        uihelpers.build_vnc_keymap_combo(self.vm, gfx_keymap,
                                         no_default=no_default)

        # Sound model
        sound_dev = self.widget("sound-model-combo")
        uihelpers.build_sound_combo(self.vm, sound_dev, no_default=no_default)

        # Video model combo
        video_dev = self.widget("video-model-combo")
        uihelpers.build_video_combo(self.vm, video_dev, no_default=no_default)

        # Watchdog model combo
        combo = self.widget("watchdog-model-combo")
        uihelpers.build_watchdogmodel_combo(self.vm, combo,
                                            no_default=no_default)

        # Watchdog action combo
        combo = self.widget("watchdog-action-combo")
        uihelpers.build_watchdogaction_combo(self.vm, combo,
                                             no_default=no_default)

        # Smartcard mode
        sc_mode = self.widget("smartcard-mode-combo")
        uihelpers.build_smartcard_mode_combo(self.vm, sc_mode)

        # Redirection type
        combo = self.widget("redir-type-combo")
        uihelpers.build_redir_type_combo(self.vm, combo)

        # Controller model
        combo = self.widget("controller-model-combo")
        model = gtk.ListStore(str, str)
        combo.set_model(model)
        text = gtk.CellRendererText()
        combo.pack_start(text, True)
        combo.add_attribute(text, 'text', 1)
        combo.set_active(-1)


    # Helper function to handle the combo/label pattern used for
    # video model, sound model, network model, etc.
    def set_combo_label(self, prefix, value, model_idx=0, label="",
                        comparefunc=None):
        label = label or value
        model_label = self.widget(prefix + "-label")
        model_combo = self.widget(prefix + "-combo")

        idx = -1
        if comparefunc:
            model_in_list, idx = comparefunc(model_combo.get_model(), value)
        else:
            model_list = map(lambda x: x[model_idx], model_combo.get_model())
            model_in_list = (value in model_list)
            if model_in_list:
                idx = model_list.index(value)

        model_label.set_property("visible", not model_in_list)
        model_combo.set_property("visible", model_in_list)
        model_label.set_text(label or "")

        if model_in_list:
            model_combo.set_active(idx)
        else:
            model_combo.set_active(-1)

    # Helper for accessing value of combo/label pattern
    def get_combo_value(self, widgetname, model_idx=0):
        combo = self.widget(widgetname)
        if combo.get_active() < 0:
            return None
        return combo.get_model()[combo.get_active()][model_idx]

    def get_combo_label_value(self, prefix, model_idx=0):
        comboname = prefix + "-combo"
        label = self.widget(prefix + "-label")
        value = None

        if label.get_property("visible"):
            value = label.get_text()
        else:
            value = self.get_combo_value(comboname, model_idx)

        return value

    ##########################
    # Window state listeners #
    ##########################

    def window_resized(self, ignore, event):
        # Sometimes dimensions change when window isn't visible
        if not self.is_visible():
            return

        self.vm.set_details_window_size(event.width, event.height)

    def popup_addhw_menu(self, widget, event):
        ignore = widget
        if event.button != 3:
            return

        self.addhwmenu.popup(None, None, None, 0, event.time)

    def build_serial_list(self):
        ret = []

        def add_row(text, err, sensitive, do_radio, cb, serialidx):
            ret.append([text, err, sensitive, do_radio, cb, serialidx])

        devs = self.vm.get_serial_devs()
        if len(devs) == 0:
            add_row(_("No text console available"),
                    None, False, False, None, None)

        def build_desc(dev):
            if dev.virtual_device_type == "console":
                return "Text Console %d" % (dev.vmmindex + 1)
            return "Serial %d" % (dev.vmmindex + 1)

        for dev in devs:
            desc = build_desc(dev)
            idx = dev.vmmindex

            err = vmmSerialConsole.can_connect(self.vm, dev)
            sensitive = not bool(err)

            def cb(src):
                return self.control_serial_tab(src, desc, idx)

            add_row(desc, err, sensitive, True, cb, idx)

        return ret

    def current_serial_dev(self):
        showing_serial = (self.last_console_page >= PAGE_DYNAMIC_OFFSET)
        if not showing_serial:
            return

        serial_idx = self.last_console_page - PAGE_DYNAMIC_OFFSET
        if len(self.serial_tabs) < serial_idx:
            return

        return self.serial_tabs[serial_idx]

    def populate_serial_menu(self, src):
        for ent in src:
            src.remove(ent)

        serial_page_dev = self.current_serial_dev()
        showing_graphics = (self.last_console_page == PAGE_CONSOLE)

        # Populate serial devices
        group = None
        itemlist = self.build_serial_list()
        for msg, err, sensitive, do_radio, cb, ignore in itemlist:
            if do_radio:
                item = gtk.RadioMenuItem(group, msg)
                if group is None:
                    group = item
            else:
                item = gtk.MenuItem(msg)

            item.set_sensitive(sensitive)

            if err and not sensitive:
                util.tooltip_wrapper(item, err)

            if cb:
                item.connect("toggled", cb)

            # Tab is already open, make sure marked as such
            if (sensitive and
                serial_page_dev and
                serial_page_dev.name == msg):
                item.set_active(True)

            src.add(item)

        src.add(gtk.SeparatorMenuItem())

        # Populate graphical devices
        devs = self.vm.get_graphics_devices()
        if len(devs) == 0:
            item = gtk.MenuItem(_("No graphical console available"))
            item.set_sensitive(False)
            src.add(item)
        else:
            dev = devs[0]
            item = gtk.RadioMenuItem(group, _("Graphical Console %s") %
                                     dev.pretty_type_simple(dev.type))
            if group == None:
                group = item

            if showing_graphics:
                item.set_active(True)
            item.connect("toggled", self.control_serial_tab,
                         dev.virtual_device_type, dev.type)
            src.add(item)

        src.show_all()

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

    def get_selected_row(self, widget):
        selection = widget.get_selection()
        model, treepath = selection.get_selected()
        if treepath == None:
            return None
        return model[treepath]

    def get_boot_selection(self):
        return self.get_selected_row(self.widget("config-boot-list"))

    def set_hw_selection(self, page, disable_apply=True):
        if disable_apply:
            self.widget("config-apply").set_sensitive(False)

        hwlist = self.widget("hw-list")
        selection = hwlist.get_selection()
        selection.select_path(str(page))

    def get_hw_row(self):
        return self.get_selected_row(self.widget("hw-list"))

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

    def compare_hw_rows(self, row1, row2):
        if row1 == row2:
            return True
        if not row1 or not row2:
            return False

        for idx in range(len(row1)):
            if row1[idx] != row2[idx]:
                return False
        return True

    def has_unapplied_changes(self, row):
        if not row:
            return False

        if not self.widget("config-apply").get_property("sensitive"):
            return False

        if not util.chkbox_helper(self,
            self.config.get_confirm_unapplied,
            self.config.set_confirm_unapplied,
            text1=(_("There are unapplied changes. Would you like to apply "
                     "them now?")),
            chktext=_("Don't warn me again."),
            alwaysrecord=True,
            default=False):
            return False

        return not self.config_apply(row=row)

    def hw_changed(self, ignore):
        newrow = self.get_hw_row()
        oldrow = self.oldhwrow
        model = self.widget("hw-list").get_model()

        if self.compare_hw_rows(newrow, oldrow):
            return

        if self.has_unapplied_changes(oldrow):
            # Unapplied changes, and syncing them failed
            pageidx = 0
            for idx in range(len(model)):
                if self.compare_hw_rows(model[idx], oldrow):
                    pageidx = idx
                    break
            self.set_hw_selection(pageidx, disable_apply=False)
        else:
            self.oldhwrow = newrow
            self.hw_selected()

    def hw_selected(self, page=None):
        pagetype = self.force_get_hw_pagetype(page)

        self.widget("config-remove").set_sensitive(True)
        self.widget("hw-panel").set_sensitive(True)
        self.widget("hw-panel").show()

        try:
            if pagetype == HW_LIST_TYPE_GENERAL:
                self.refresh_overview_page()
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
            else:
                pagetype = -1
        except Exception, e:
            self.err.show_err(_("Error refreshing hardware page: %s") % str(e))
            return

        rem = pagetype in remove_pages
        self.disable_apply()
        self.widget("config-remove").set_property("visible", rem)

        self.widget("hw-panel").set_current_page(pagetype)

    def details_console_changed(self, src):
        if self.ignoreDetails:
            return

        if not src.get_active():
            return

        is_details = False
        if (src == self.widget("control-vm-details") or
            src == self.widget("details-menu-view-details")):
            is_details = True

        pages = self.widget("details-pages")
        if pages.get_current_page() == PAGE_DETAILS:
            if self.has_unapplied_changes(self.get_hw_row()):
                self.sync_details_console_view(True)
                return

        if is_details:
            pages.set_current_page(PAGE_DETAILS)
        else:
            pages.set_current_page(self.last_console_page)

    def sync_details_console_view(self, is_details):
        details = self.widget("control-vm-details")
        details_menu = self.widget("details-menu-view-details")
        console = self.widget("control-vm-console")
        console_menu = self.widget("details-menu-view-console")

        try:
            self.ignoreDetails = True

            details.set_active(is_details)
            details_menu.set_active(is_details)
            console.set_active(not is_details)
            console_menu.set_active(not is_details)
        finally:
            self.ignoreDetails = False

    def switch_page(self, ignore1=None, ignore2=None, newpage=None):
        self.page_refresh(newpage)

        self.sync_details_console_view(newpage == PAGE_DETAILS)
        self.console.set_allow_fullscreen()

        if newpage == PAGE_CONSOLE or newpage >= PAGE_DYNAMIC_OFFSET:
            self.last_console_page = newpage

    def change_run_text(self, can_restore):
        if can_restore:
            text = _("_Restore")
        else:
            text = _("_Run")
        strip_text = text.replace("_", "")

        self.widget("details-menu-run").get_child().set_label(text)
        self.widget("control-run").set_label(strip_text)

    def refresh_vm_state(self, ignore1=None, ignore2=None, ignore3=None):
        vm = self.vm
        status = self.vm.status()

        self.toggle_toolbar(self.widget("details-menu-view-toolbar"))

        active  = vm.is_active()
        destroy = vm.is_destroyable()
        run     = vm.is_runable()
        stop    = vm.is_stoppable()
        paused  = vm.is_paused()
        ro      = vm.is_read_only()

        if vm.managedsave_supported:
            self.change_run_text(vm.hasSavedImage())

        self.widget("details-menu-destroy").set_sensitive(destroy)
        self.widget("control-run").set_sensitive(run)
        self.widget("details-menu-run").set_sensitive(run)

        self.widget("details-menu-migrate").set_sensitive(stop)
        self.widget("control-shutdown").set_sensitive(stop)
        self.widget("details-menu-shutdown").set_sensitive(stop)
        self.widget("details-menu-save").set_sensitive(stop)
        self.widget("control-pause").set_sensitive(stop)
        self.widget("details-menu-pause").set_sensitive(stop)

        self.set_pause_state(paused)

        self.widget("overview-name").set_editable(not active)

        self.widget("config-vcpus").set_sensitive(not ro)
        self.widget("config-vcpupin").set_sensitive(not ro)
        self.widget("config-memory").set_sensitive(not ro)
        self.widget("config-maxmem").set_sensitive(not ro)

        # Disable send key menu entries for offline VM
        self.console.send_key_button.set_sensitive(not (run or paused))
        send_key = self.widget("details-menu-send-key")
        for c in send_key.get_submenu().get_children():
            c.set_sensitive(not (run or paused))

        self.console.update_widget_states(vm, status)
        if not run:
            self.activate_default_console_page()

        self.widget("overview-status-text").set_text(
                                                    self.vm.run_status())
        self.widget("overview-status-icon").set_from_icon_name(
                            self.vm.run_status_icon_name(), gtk.ICON_SIZE_MENU)

        details = self.widget("details-pages")
        self.page_refresh(details.get_current_page())

        # This is safe to refresh, and is dependent on domain state
        self._refresh_runtime_pinning()


    #############################
    # External action listeners #
    #############################

    def show_help(self, src_ignore):
        self.emit("action-show-help", "virt-manager-details-window")

    def view_manager(self, src_ignore):
        self.emit("action-view-manager")

    def exit_app(self, src_ignore):
        self.emit("action-exit-app")

    def activate_default_console_page(self):
        if self.vm.get_graphics_devices() or not self.vm.get_serial_devs():
            return

        # Only show serial page if we are already on console view
        pages = self.widget("details-pages")
        if pages.get_current_page() != PAGE_CONSOLE:
            return

        # Show serial console
        devs = self.build_serial_list()
        for name, ignore, sensitive, ignore, cb, serialidx in devs:
            if not sensitive or not cb:
                continue

            self._show_serial_tab(name, serialidx)
            break

    def activate_default_page(self):
        pages = self.widget("details-pages")
        pages.set_current_page(PAGE_CONSOLE)
        self.activate_default_console_page()

    def activate_console_page(self):
        pages = self.widget("details-pages")
        pages.set_current_page(PAGE_CONSOLE)

    def activate_performance_page(self):
        self.widget("details-pages").set_current_page(PAGE_DETAILS)
        self.set_hw_selection(HW_LIST_TYPE_STATS)

    def activate_config_page(self):
        self.widget("details-pages").set_current_page(PAGE_DETAILS)

    def add_hardware(self, src_ignore):
        try:
            if self.addhw is None:
                self.addhw = vmmAddHardware(self.vm)

            self.addhw.show(self.topwin)
        except Exception, e:
            self.err.show_err((_("Error launching hardware dialog: %s") %
                               str(e)))

    def remove_xml_dev(self, src_ignore):
        info = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not info:
            return

        devtype = info.virtual_device_type
        self.remove_device(devtype, info)

    def set_pause_state(self, paused):
        # Set pause widget states
        try:
            self.ignorePause = True
            self.widget("control-pause").set_active(paused)
            self.widget("details-menu-pause").set_active(paused)
        finally:
            self.ignorePause = False

    def control_vm_pause(self, src):
        if self.ignorePause:
            return

        # Let state handler listener change things if necc.
        self.set_pause_state(not src.get_active())

        if not self.vm.is_paused():
            self.emit("action-suspend-domain",
                      self.vm.conn.get_uri(),
                      self.vm.get_uuid())
        else:
            self.emit("action-resume-domain",
                      self.vm.conn.get_uri(),
                      self.vm.get_uuid())


    def control_vm_run(self, src_ignore):
        self.emit("action-run-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_shutdown(self, src_ignore):
        self.emit("action-shutdown-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_reboot(self, src_ignore):
        self.emit("action-reboot-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_save(self, src_ignore):
        self.emit("action-save-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_destroy(self, src_ignore):
        self.emit("action-destroy-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_clone(self, src_ignore):
        self.emit("action-clone-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_migrate(self, src_ignore):
        self.emit("action-migrate-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_screenshot(self, src_ignore):
        image = self.console.viewer.get_pixbuf()

        # If someone feels kind they could extend this code to allow
        # user to choose what image format they'd like to save in....
        path = util.browse_local(
                        self.topwin,
                        _("Save Virtual Machine Screenshot"),
                        self.vm.conn,
                        _type=("png", "PNG files"),
                        dialog_type=gtk.FILE_CHOOSER_ACTION_SAVE,
                        browse_reason=self.config.CONFIG_DIR_SCREENSHOT)
        if not path:
            return

        filename = path
        if not filename.endswith(".png"):
            filename += ".png"

        # Save along with a little metadata about us & the domain
        image.save(filename, 'png',
                   {'tEXt::Hypervisor URI': self.vm.conn.get_uri(),
                    'tEXt::Domain Name': self.vm.get_name(),
                    'tEXt::Domain UUID': self.vm.get_uuid(),
                    'tEXt::Generator App': self.config.get_appname(),
                    'tEXt::Generator Version': self.config.get_appversion()})

        msg = gtk.MessageDialog(self.topwin,
                                gtk.DIALOG_MODAL,
                                gtk.MESSAGE_INFO,
                                gtk.BUTTONS_OK,
                                (_("The screenshot has been saved to:\n%s") %
                                 filename))
        msg.set_title(_("Screenshot saved"))
        msg.run()
        msg.destroy()


    #########################
    # Serial Console pieces #
    #########################

    def control_serial_tab(self, src_ignore, name, target_port):
        pages = self.widget("details-pages")
        is_graphics = (name == "graphics")
        is_serial = not is_graphics

        if is_graphics:
            pages.set_current_page(PAGE_CONSOLE)
        elif is_serial:
            self._show_serial_tab(name, target_port)

    def _show_serial_tab(self, name, target_port):
        serial = None
        for s in self.serial_tabs:
            if s.name == name:
                serial = s
                break

        if not serial:
            serial = vmmSerialConsole(self.vm, target_port, name)

            title = gtk.Label(name)
            self.widget("details-pages").append_page(serial.box, title)
            self.serial_tabs.append(serial)
            serial.open_console()

        page_idx = self.serial_tabs.index(serial) + PAGE_DYNAMIC_OFFSET
        self.widget("details-pages").set_current_page(page_idx)

    def _close_serial_tab(self, serial):
        if not serial in self.serial_tabs:
            return

        page_idx = self.serial_tabs.index(serial) + PAGE_DYNAMIC_OFFSET
        self.widget("details-pages").remove_page(page_idx)

        serial.cleanup()
        self.serial_tabs.remove(serial)


    ############################
    # Details/Hardware getters #
    ############################

    def get_config_boot_devs(self):
        boot_model = self.widget("config-boot-list").get_model()
        devs = []

        for row in boot_model:
            if row[BOOT_ACTIVE]:
                devs.append(row[BOOT_DEV_TYPE])

        return devs

    def get_config_cpu_model(self):
        cpu_list = self.widget("cpu-model")
        model = cpu_list.child.get_text()

        for row in cpu_list.get_model():
            if model == row[0]:
                return model, row[1].vendor

        return model, None

    def get_config_cpu_features(self):
        feature_list = self.widget("cpu-features")
        ret = []

        for row in feature_list.get_model():
            if row[1] in ["off", "model"]:
                continue
            ret.append(row)

        return ret

    ##############################
    # Details/Hardware listeners #
    ##############################

    def _browse_file(self, callback, is_media=False):
        if is_media:
            reason = self.config.CONFIG_DIR_ISO_MEDIA
        else:
            reason = self.config.CONFIG_DIR_IMAGE

        if self.storage_browser == None:
            self.storage_browser = vmmStorageBrowser(self.conn)

        self.storage_browser.set_finish_cb(callback)
        self.storage_browser.set_browse_reason(reason)
        self.storage_browser.show(self.topwin, self.conn)

    def browse_kernel(self, src_ignore):
        def cb(ignore, path):
            self.widget("boot-kernel").set_text(path)
        self._browse_file(cb)
    def browse_initrd(self, src_ignore):
        def cb(ignore, path):
            self.widget("boot-kernel-initrd").set_text(path)
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

    # Overview -> Machine settings
    def config_acpi_changed(self, ignore):
        widget = self.widget("overview-acpi")
        incon = widget.get_inconsistent()
        widget.set_inconsistent(False)
        if incon:
            widget.set_active(True)
        self.enable_apply(EDIT_ACPI)
    def config_apic_changed(self, ignore):
        widget = self.widget("overview-apic")
        incon = widget.get_inconsistent()
        widget.set_inconsistent(False)
        if incon:
            widget.set_active(True)
        self.enable_apply(EDIT_APIC)

    # Overview -> Security
    def security_type_changed(self, button):
        self.enable_apply(EDIT_SECURITY)
        self.widget("security-label").set_sensitive(not button.get_active())

    # Memory
    def config_get_maxmem(self):
        return uihelpers.spin_get_helper(self.widget("config-maxmem"))
    def config_get_memory(self):
        return uihelpers.spin_get_helper(self.widget("config-memory"))

    def config_maxmem_changed(self, src_ignore):
        self.enable_apply(EDIT_MEM)

    def config_memory_changed(self, src_ignore):
        self.enable_apply(EDIT_MEM)

        maxadj = self.widget("config-maxmem").get_adjustment()

        mem = self.config_get_memory()
        if maxadj.value < mem:
            maxadj.value = mem
        maxadj.lower = mem

    def generate_cpuset(self):
        mem = int(self.vm.get_memory()) / 1024 / 1024
        return virtinst.Guest.generate_cpuset(self.conn.vmm, mem)

    # VCPUS
    def config_get_vcpus(self):
        return uihelpers.spin_get_helper(self.widget("config-vcpus"))
    def config_get_maxvcpus(self):
        return uihelpers.spin_get_helper(self.widget("config-maxvcpus"))

    def config_vcpupin_generate(self, ignore):
        try:
            pinstr = self.generate_cpuset()
        except Exception, e:
            return self.err.val_err(
                _("Error generating CPU configuration"), e)

        self.widget("config-vcpupin").set_text("")
        self.widget("config-vcpupin").set_text(pinstr)

    def config_vcpus_changed(self, ignore):
        self.enable_apply(EDIT_VCPUS)

        conn = self.vm.conn
        host_active_count = conn.host_active_processor_count()
        cur = self.config_get_vcpus()

        # Warn about overcommit
        warn = bool(cur > host_active_count)
        self.widget("config-vcpus-warn-box").set_property("visible", warn)

        maxadj = self.widget("config-maxvcpus").get_adjustment()
        maxval = self.config_get_maxvcpus()
        if maxval < cur:
            maxadj.value = cur
        maxadj.lower = cur

    def config_maxvcpus_changed(self, ignore):
        self.enable_apply(EDIT_VCPUS)

    def config_cpu_copy_host(self, src_ignore):
        # Update UI with output copied from host
        try:
            CPU = virtinst.CPU(self.vm.conn.vmm)
            CPU.copy_host_cpu()

            self._refresh_cpu_config(CPU)
            self._cpu_copy_host = True
        except Exception, e:
            self.err.show_err(_("Error copying host CPU: %s") % str(e))
            return

    def config_cpu_topology_enable(self, src):
        do_enable = src.get_active()
        self.widget("cpu-topology-table").set_sensitive(do_enable)
        self.enable_apply(EDIT_TOPOLOGY)

    # Boot device / Autostart
    def config_bootdev_selected(self, ignore):
        boot_row = self.get_boot_selection()
        boot_selection = boot_row and boot_row[BOOT_DEV_TYPE]
        boot_devs = self.get_config_boot_devs()
        up_widget = self.widget("config-boot-moveup")
        down_widget = self.widget("config-boot-movedown")

        down_widget.set_sensitive(bool(boot_devs and
                                       boot_selection and
                                       boot_selection in boot_devs and
                                       boot_selection != boot_devs[-1]))
        up_widget.set_sensitive(bool(boot_devs and boot_selection and
                                     boot_selection in boot_devs and
                                     boot_selection != boot_devs[0]))

    def config_boot_toggled(self, ignore, index):
        boot_model = self.widget("config-boot-list").get_model()
        boot_row = boot_model[index]
        is_active = boot_row[BOOT_ACTIVE]

        boot_row[BOOT_ACTIVE] = not is_active

        self.repopulate_boot_list(self.get_config_boot_devs(),
                                  boot_row[BOOT_DEV_TYPE])
        self.enable_apply(EDIT_BOOTORDER)

    def config_boot_move(self, src_ignore, move_up):
        boot_row = self.get_boot_selection()
        if not boot_row:
            return

        boot_selection = boot_row[BOOT_DEV_TYPE]
        boot_devs = self.get_config_boot_devs()
        boot_idx = boot_devs.index(boot_selection)
        if move_up:
            new_idx = boot_idx - 1
        else:
            new_idx = boot_idx + 1

        if new_idx < 0 or new_idx >= len(boot_devs):
            # Somehow we got out of bounds
            return

        swap_dev = boot_devs[new_idx]
        boot_devs[new_idx] = boot_selection
        boot_devs[boot_idx] = swap_dev

        self.repopulate_boot_list(boot_devs, boot_selection)
        self.enable_apply(EDIT_BOOTORDER)

    # CDROM Eject/Connect
    def toggle_storage_media(self, src_ignore):
        disk = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not disk:
            return

        dev_id_info = disk
        curpath = disk.path
        devtype = disk.device

        try:
            if curpath:
                # Disconnect cdrom
                self.change_storage_media(dev_id_info, None)
                return
        except Exception, e:
            self.err.show_err((_("Error disconnecting media: %s") % e))
            return

        try:
            def change_cdrom_wrapper(src_ignore, dev_id_info, newpath):
                return self.change_storage_media(dev_id_info, newpath)

            # Launch 'Choose CD' dialog
            if self.media_choosers[devtype] is None:
                ret = vmmChooseCD(self.vm, dev_id_info)

                ret.connect("cdrom-chosen", change_cdrom_wrapper)
                self.media_choosers[devtype] = ret

            dialog = self.media_choosers[devtype]
            dialog.dev_id_info = dev_id_info

            dialog.show(self.topwin)
        except Exception, e:
            self.err.show_err((_("Error launching media dialog: %s") % e))
            return

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
            else:
                ret = False
        except Exception, e:
            return self.err.show_err(_("Error apply changes: %s") % e)

        if ret is not False:
            self.disable_apply()
        return True

    def get_text(self, widgetname, strip=True):
        ret = self.widget(widgetname).get_text()
        if strip:
            ret = ret.strip()
        return ret

    def editted(self, pagetype):
        if pagetype not in range(EDIT_TOTAL):
            raise RuntimeError("crap! %s" % pagetype)
        return pagetype in self.active_edits

    def make_apply_data(self):
        definefuncs = []
        defineargs = []
        hotplugfuncs = []
        hotplugargs = []

        def add_define(func, *args):
            definefuncs.append(func)
            defineargs.append(args)
        def add_hotplug(func, *args):
            hotplugfuncs.append(func)
            hotplugargs.append(args)

        return (definefuncs, defineargs, add_define,
                hotplugfuncs, hotplugargs, add_hotplug)

    # Overview section
    def config_overview_apply(self):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.editted(EDIT_NAME):
            name = self.widget("overview-name").get_text()
            add_define(self.vm.define_name, name)

        if self.editted(EDIT_ACPI):
            enable_acpi = self.widget("overview-acpi").get_active()
            if self.widget("overview-acpi").get_inconsistent():
                enable_acpi = None
            add_define(self.vm.define_acpi, enable_acpi)

        if self.editted(EDIT_APIC):
            enable_apic = self.widget("overview-apic").get_active()
            if self.widget("overview-apic").get_inconsistent():
                enable_apic = None
            add_define(self.vm.define_apic, enable_apic)

        if self.editted(EDIT_CLOCK):
            clock = self.get_combo_label_value("overview-clock")
            add_define(self.vm.define_clock, clock)

        if self.editted(EDIT_MACHTYPE):
            machtype = self.get_combo_label_value("machine-type")
            add_define(self.vm.define_machtype, machtype)

        if self.editted(EDIT_SECURITY):
            semodel = None
            setype = "static"
            selabel = self.get_text("security-label")

            if self.widget("security-dynamic").get_active():
                setype = "dynamic"
            if self.widget("security-type-box").get_property("sensitive"):
                semodel = self.get_text("security-model")

            add_define(self.vm.define_seclabel, semodel, setype, selabel)

        if self.editted(EDIT_DESC):
            desc_widget = self.widget("overview-description")
            desc = desc_widget.get_buffer().get_property("text") or ""
            add_define(self.vm.define_description, desc)

        return self._change_config_helper(df, da, hf, ha)

    # CPUs
    def config_vcpus_apply(self):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()

        if self.editted(EDIT_VCPUS):
            vcpus = self.config_get_vcpus()
            maxv = self.config_get_maxvcpus()
            add_define(self.vm.define_vcpus, vcpus, maxv)
            add_hotplug(self.vm.hotplug_vcpus, vcpus)

        if self.editted(EDIT_CPUSET):
            cpuset = self.get_text("config-vcpupin")
            print cpuset
            add_define(self.vm.define_cpuset, cpuset)
            add_hotplug(self.config_vcpu_pin_cpuset, cpuset)

        if self.editted(EDIT_CPU):
            model, vendor = self.get_config_cpu_model()
            features = self.get_config_cpu_features()
            add_define(self.vm.define_cpu,
                       model, vendor, self._cpu_copy_host, features)

        if self.editted(EDIT_TOPOLOGY):
            do_top = self.widget("cpu-topology-enable").get_active()
            sockets = self.widget("cpu-sockets").get_value()
            cores = self.widget("cpu-cores").get_value()
            threads = self.widget("cpu-threads").get_value()
            if not do_top:
                sockets = None
                cores = None
                threads = None

            add_define(self.vm.define_cpu_topology, sockets, cores, threads)

        ret = self._change_config_helper(df, da, hf, ha)
        if ret:
            self._cpu_copy_host = False
        return ret

    def config_vcpu_pin(self, src_ignore, path, new_text):
        vcpu_list = self.widget("config-vcpu-list")
        vcpu_model = vcpu_list.get_model()
        row = vcpu_model[path]
        conn = self.vm.conn

        try:
            new_text = new_text.strip()
            vcpu_num = int(row[0])
            pinlist = virtinst.Guest.cpuset_str_to_tuple(conn.vmm, new_text)
        except Exception, e:
            self.err.val_err(_("Error building pin list"), e)
            return

        try:
            self.vm.pin_vcpu(vcpu_num, pinlist)
        except Exception, e:
            self.err.show_err(_("Error pinning vcpus"), e)
            return

        self._refresh_runtime_pinning()

    def config_vcpu_pin_cpuset(self, cpuset):
        conn = self.vm.conn
        vcpu_list = self.widget("config-vcpu-list")
        vcpu_model = vcpu_list.get_model()

        if self.vm.vcpu_pinning() == cpuset:
            return

        pinlist = virtinst.Guest.cpuset_str_to_tuple(conn.vmm, cpuset)
        for row in vcpu_model:
            vcpu_num = row[0]
            self.vm.pin_vcpu(int(vcpu_num), pinlist)

    # Memory
    def config_memory_apply(self):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()

        if self.editted(EDIT_MEM):
            curmem = None
            maxmem = self.config_get_maxmem()
            if self.widget("config-memory").get_property("sensitive"):
                curmem = self.config_get_memory()

            if curmem:
                curmem = int(curmem) * 1024
            if maxmem:
                maxmem = int(maxmem) * 1024

            add_define(self.vm.define_both_mem, curmem, maxmem)
            add_hotplug(self.vm.hotplug_both_mem, curmem, maxmem)

        return self._change_config_helper(df, da, hf, ha)

    # Boot device / Autostart
    def config_boot_options_apply(self):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.editted(EDIT_AUTOSTART):
            auto = self.widget("config-autostart")
            try:
                self.vm.set_autostart(auto.get_active())
            except Exception, e:
                self.err.show_err(
                    (_("Error changing autostart value: %s") % str(e)))
                return False

        if self.editted(EDIT_BOOTORDER):
            bootdevs = self.get_config_boot_devs()
            add_define(self.vm.set_boot_device, bootdevs)

        if self.editted(EDIT_BOOTMENU):
            bootmenu = self.widget("boot-menu").get_active()
            add_define(self.vm.set_boot_menu, bootmenu)

        if self.editted(EDIT_KERNEL):
            kernel = self.get_text("boot-kernel")
            initrd = self.get_text("boot-kernel-initrd")
            args = self.get_text("boot-kernel-args")

            if initrd and not kernel:
                return self.err.val_err(
                    _("Cannot set initrd without specifying a kernel path"))
            if args and not kernel:
                return self.err.val_err(
                    _("Cannot set kernel arguments without specifying a kernel path"))

            add_define(self.vm.set_boot_kernel, kernel, initrd, args)

        if self.editted(EDIT_INIT):
            init = self.get_text("boot-init-path")
            if not init:
                return self.err.val_err(_("An init path must be specified"))
            add_define(self.vm.set_boot_init, init)

        return self._change_config_helper(df, da, hf, ha)

    # CDROM
    def change_storage_media(self, dev_id_info, newpath):
        return self._change_config_helper(self.vm.define_storage_media,
                                          (dev_id_info, newpath),
                                          self.vm.hotplug_storage_media,
                                          (dev_id_info, newpath))

    # Disk options
    def config_disk_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.editted(EDIT_DISK_RO):
            do_readonly = self.widget("disk-readonly").get_active()
            add_define(self.vm.define_disk_readonly, dev_id_info, do_readonly)

        if self.editted(EDIT_DISK_SHARE):
            do_shareable = self.widget("disk-shareable").get_active()
            add_define(self.vm.define_disk_shareable,
                       dev_id_info, do_shareable)

        if self.editted(EDIT_DISK_CACHE):
            cache = self.get_combo_label_value("disk-cache")
            add_define(self.vm.define_disk_cache, dev_id_info, cache)

        if self.editted(EDIT_DISK_IO):
            io = self.get_combo_label_value("disk-io")
            add_define(self.vm.define_disk_io, dev_id_info, io)

        if self.editted(EDIT_DISK_FORMAT):
            fmt = self.widget("disk-format").child.get_text().strip()
            add_define(self.vm.define_disk_driver_type, dev_id_info, fmt)

        if self.editted(EDIT_DISK_SERIAL):
            serial = self.get_text("disk-serial")
            add_define(self.vm.define_disk_serial, dev_id_info, serial)

        # Do this last since it can change uniqueness info of the dev
        if self.editted(EDIT_DISK_BUS):
            bus = self.get_combo_label_value("disk-bus")
            addr = None
            if bus == "spapr-vscsi":
                bus = "scsi"
                addr = "spapr-vio"
            add_define(self.vm.define_disk_bus, dev_id_info, bus, addr)

        return self._change_config_helper(df, da, hf, ha)

    # Audio options
    def config_sound_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.editted(EDIT_SOUND_MODEL):
            model = self.get_combo_label_value("sound-model")
            if model:
                add_define(self.vm.define_sound_model, dev_id_info, model)

        return self._change_config_helper(df, da, hf, ha)

    # Smartcard options
    def config_smartcard_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.editted(EDIT_SMARTCARD_MODE):
            model = self.get_combo_label_value("smartcard-mode")
            if model:
                add_define(self.vm.define_smartcard_mode, dev_id_info, model)

        return self._change_config_helper(df, da, hf, ha)

    # Network options
    def config_network_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.editted(EDIT_NET_MODEL):
            model = self.get_combo_label_value("network-model")
            addr = None
            if model == "spapr-vlan":
                addr = "spapr-vio"
            add_define(self.vm.define_network_model, dev_id_info, model, addr)

        if self.editted(EDIT_NET_SOURCE):
            mode = None
            net_list = self.widget("network-source-combo")
            net_bridge = self.widget("network-bridge")
            nettype, source = uihelpers.get_network_selection(net_list,
                                                              net_bridge)
            if nettype == "direct":
                mode = self.get_combo_label_value("network-source-mode")

            add_define(self.vm.define_network_source, dev_id_info,
                       nettype, source, mode)

        if self.editted(EDIT_NET_VPORT):
            vport_type = self.get_text("vport-type")
            vport_managerid = self.get_text("vport-managerid")
            vport_typeid = self.get_text("vport-typeid")
            vport_idver = self.get_text("vport-typeidversion")
            vport_instid = self.get_text("vport-instanceid")

            add_define(self.vm.define_virtualport, dev_id_info,
                       vport_type, vport_managerid, vport_typeid,
                       vport_idver, vport_instid)

        return self._change_config_helper(df, da, hf, ha)

    # Graphics options
    def _do_change_spicevmc(self, gdev, newgtype):
        has_multi_spice = (len(filter(
                                lambda dev: dev.type == dev.TYPE_SPICE,
                                self.vm.get_graphics_devices())) > 1)
        has_spicevmc = bool(filter(
                            (lambda dev:
                                (dev.dev_type == dev.DEV_CHANNEL and
                                 dev.char_type == dev.CHAR_SPICEVMC)),
                            self.vm.get_char_devices()))
        fromspice = (gdev.type == "spice")
        tospice = (newgtype == "spice")

        if fromspice and tospice:
            return False
        if not fromspice and not tospice:
            return False

        if tospice and has_spicevmc:
            return False
        if fromspice and not has_spicevmc:
            return False

        if fromspice and has_multi_spice:
            # Don't offer to remove if there are other spice displays
            return False

        msg = (_("You are switching graphics type to %(gtype)s, "
                 "would you like to %(action)s Spice agent channels?") %
                {"gtype": newgtype,
                 "action": fromspice and "remove" or "add"})
        return self.err.yes_no(msg)

    def config_graphics_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()

        if self.editted(EDIT_GFX_PASSWD):
            passwd = self.get_text("gfx-password", strip=False) or None
            add_define(self.vm.define_graphics_password, dev_id_info, passwd)
            add_hotplug(self.vm.hotplug_graphics_password, dev_id_info,
                        passwd)

        if self.editted(EDIT_GFX_KEYMAP):
            keymap = self.get_combo_label_value("gfx-keymap")
            add_define(self.vm.define_graphics_keymap, dev_id_info, keymap)

        # Do this last since it can change graphics unique ID
        if self.editted(EDIT_GFX_TYPE):
            gtype = self.get_combo_label_value("gfx-type")
            change_spicevmc = self._do_change_spicevmc(dev_id_info, gtype)
            add_define(self.vm.define_graphics_type, dev_id_info,
                       gtype, change_spicevmc)

        return self._change_config_helper(df, da, hf, ha)

    # Video options
    def config_video_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.editted(EDIT_VIDEO_MODEL):
            model = self.get_combo_label_value("video-model")
            if model:
                add_define(self.vm.define_video_model, dev_id_info, model)

        return self._change_config_helper(df, da, hf, ha)

    # Controller options
    def config_controller_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.editted(EDIT_CONTROLLER_MODEL):
            model = self.get_combo_label_value("controller-model")
            if model:
                add_define(self.vm.define_controller_model, dev_id_info, model)

        return self._change_config_helper(df, da, hf, ha)

    # Watchdog options
    def config_watchdog_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.editted(EDIT_WATCHDOG_MODEL):
            model = self.get_combo_label_value("watchdog-model")
            add_define(self.vm.define_watchdog_model, dev_id_info, model)

        if self.editted(EDIT_WATCHDOG_ACTION):
            action = self.get_combo_label_value("watchdog-action")
            add_define(self.vm.define_watchdog_action, dev_id_info, action)

        return self._change_config_helper(df, da, hf, ha)

    # Device removal
    def remove_device(self, dev_type, dev_id_info):
        logging.debug("Removing device: %s %s", dev_type, dev_id_info)

        if not util.chkbox_helper(self, self.config.get_confirm_removedev,
            self.config.set_confirm_removedev,
            text1=(_("Are you sure you want to remove this device?"))):
            return

        # Define the change
        try:
            self.vm.remove_device(dev_id_info)
        except Exception, e:
            self.err.show_err(_("Error Removing Device: %s" % str(e)))
            return

        # Try to hot remove
        detach_err = False
        try:
            if self.vm.is_active():
                self.vm.detach_device(dev_id_info)
        except Exception, e:
            logging.debug("Device could not be hotUNplugged: %s", str(e))
            detach_err = (str(e), "".join(traceback.format_exc()))

        if not detach_err:
            self.widget("config-apply").set_sensitive(False)
            return

        self.err.show_err(
            _("Device could not be removed from the running machine"),
            details=(detach_err[0] + "\n\n" + detach_err[1]),
            text2=_("This change will take effect after the next guest "
                    "shutdown."),
            buttons=gtk.BUTTONS_OK,
            dialog_type=gtk.MESSAGE_INFO)

    # Generic config change helpers
    def _change_config_helper(self,
                              define_funcs, define_funcs_args,
                              hotplug_funcs=None, hotplug_funcs_args=None):
        """
        Requires at least a 'define' function and arglist to be specified
        (a function where we change the inactive guest config).

        Arguments can be a single arg or a list or appropriate arg type (e.g.
        a list of functions for define_funcs)
        """
        def listify(val):
            if not val:
                return []
            if type(val) is not list:
                return [val]
            return val

        define_funcs = listify(define_funcs)
        define_funcs_args = listify(define_funcs_args)
        hotplug_funcs = listify(hotplug_funcs)
        hotplug_funcs_args = listify(hotplug_funcs_args)

        hotplug_err = []
        active = self.vm.is_active()

        # Hotplug change
        func = None
        if active and hotplug_funcs:
            for idx in range(len(hotplug_funcs)):
                func = hotplug_funcs[idx]
                args = hotplug_funcs_args[idx]
                try:
                    func(*args)
                except Exception, e:
                    logging.debug("Hotplug failed: func=%s: %s",
                                  func, str(e))
                    hotplug_err.append((str(e),
                                        "".join(traceback.format_exc())))

        # Persistent config change
        try:
            for idx in range(len(define_funcs)):
                func = define_funcs[idx]
                args = define_funcs_args[idx]
                func(*args)
            if define_funcs:
                self.vm.redefine_cached()
        except Exception, e:
            self.err.show_err((_("Error changing VM configuration: %s") %
                              str(e)))
            # If we fail, make sure we flush the cache
            self.vm.refresh_xml()
            return False


        if (hotplug_err or
            (active and not len(hotplug_funcs) == len(define_funcs))):
            if len(define_funcs) > 1:
                msg = _("Some changes may require a guest shutdown "
                        "to take effect.")
            else:
                msg = _("These changes will take effect after "
                        "the next guest shutdown.")

            dtype = hotplug_err and gtk.MESSAGE_WARNING or gtk.MESSAGE_INFO
            hotplug_msg = ""
            for err1, tb in hotplug_err:
                hotplug_msg += (err1 + "\n\n" + tb + "\n")

            self.err.show_err(msg,
                              details=hotplug_msg,
                              buttons=gtk.BUTTONS_OK,
                              dialog_type=dtype)

        return True

    ########################
    # Details page refresh #
    ########################

    def refresh_resources(self, ignore):
        details = self.widget("details-pages")
        page = details.get_current_page()

        # If the dialog is visible, we want to make sure the XML is always
        # up to date
        if self.is_visible():
            self.vm.refresh_xml()

        # Stats page needs to be refreshed every tick
        if (page == PAGE_DETAILS and
            self.get_hw_selection(HW_LIST_COL_TYPE) == HW_LIST_TYPE_STATS):
            self.refresh_stats_page()

    def page_refresh(self, page):
        if page != PAGE_DETAILS:
            return

        # This function should only be called when the VM xml actually
        # changes (not everytime it is refreshed). This saves us from blindly
        # parsing the xml every tick

        # Add / remove new devices
        self.repopulate_hw_list()

        pagetype = self.get_hw_selection(HW_LIST_COL_TYPE)
        if pagetype is None:
            return

        if self.widget("config-apply").get_property("sensitive"):
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

        # Hypervisor Details
        self.widget("overview-hv").set_text(self.vm.get_pretty_hv_type())
        arch = self.vm.get_arch() or _("Unknown")
        emu = self.vm.get_emulator() or _("None")
        self.widget("overview-arch").set_text(arch)
        self.widget("overview-emulator").set_text(emu)

        # Operating System (ie. inspection data)
        hostname = self.vm.inspection.hostname
        if not hostname:
            hostname = _("unknown")
        self.widget("inspection-hostname").set_text(hostname)
        product_name = self.vm.inspection.product_name
        if not product_name:
            product_name = _("unknown")
        self.widget("inspection-product-name").set_text(product_name)

        # Applications (also inspection data)
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
            if app["app_version"]:
                version = app["app_version"]
            if app["app_release"]:
                version += "-" + app["app_release"]
            summary = ""
            if app["app_summary"]:
                summary = app["app_summary"]

            apps_model.append([name, version, summary])

        # Machine settings
        acpi = self.vm.get_acpi()
        apic = self.vm.get_apic()
        clock = self.vm.get_clock()
        machtype = self.vm.get_machtype()

        # Hack in a way to represent 'default' acpi/apic for customize dialog
        self.widget("overview-acpi").set_active(bool(acpi))
        self.widget("overview-acpi").set_inconsistent(
                                acpi is None and self.is_customize_dialog)
        self.widget("overview-apic").set_active(bool(apic))
        self.widget("overview-apic").set_inconsistent(
                                apic is None and self.is_customize_dialog)

        if not clock:
            clock = _("Same as host")
        self.set_combo_label("overview-clock", clock)

        if not arch in ["i686", "x86_64"]:
            if machtype is not None:
                self.set_combo_label("machine-type", machtype)

        # Security details
        semodel, ignore, vmlabel = self.vm.get_seclabel()
        caps = self.vm.conn.get_capabilities()

        if caps.host.secmodel and caps.host.secmodel.model:
            semodel = caps.host.secmodel.model

        self.widget("security-model").set_text(semodel or _("None"))

        if not semodel or semodel == "apparmor":
            self.widget("security-type-box").hide()
            self.widget("security-type-label").hide()
        else:
            self.widget("security-type-box").set_sensitive(bool(semodel))

            if self.vm.get_seclabel()[1] == "static":
                self.widget("security-static").set_active(True)
            else:
                self.widget("security-dynamic").set_active(True)

            self.widget("security-label").set_text(vmlabel)

    def refresh_stats_page(self):
        def _dsk_rx_tx_text(rx, tx, unit):
            return ('<span color="#82003B">%(rx)d %(unit)s read</span>\n'
                    '<span color="#295C45">%(tx)d %(unit)s write</span>' %
                    {"rx": rx, "tx": tx, "unit": unit})
        def _net_rx_tx_text(rx, tx, unit):
            return ('<span color="#82003B">%(rx)d %(unit)s in</span>\n'
                    '<span color="#295C45">%(tx)d %(unit)s out</span>' %
                    {"rx": rx, "tx": tx, "unit": unit})

        cpu_txt = _("Disabled")
        mem_txt = _("Disabled")
        dsk_txt = _("Disabled")
        net_txt = _("Disabled")

        cpu_txt = "%d %%" % self.vm.host_cpu_time_percentage()

        vm_memory = self.vm.stats_memory()
        host_memory = self.vm.conn.host_memory_size()
        mem_txt = "%d MB of %d MB" % (int(round(vm_memory / 1024.0)),
                                      int(round(host_memory / 1024.0)))

        if self.config.get_stats_enable_disk_poll():
            dsk_txt = _dsk_rx_tx_text(self.vm.disk_read_rate(),
                                      self.vm.disk_write_rate(), "KB/s")

        if self.config.get_stats_enable_net_poll():
            net_txt = _net_rx_tx_text(self.vm.network_rx_rate(),
                                      self.vm.network_tx_rate(), "KB/s")

        self.widget("overview-cpu-usage-text").set_text(cpu_txt)
        self.widget("overview-memory-usage-text").set_text(mem_txt)
        self.widget("overview-network-traffic-text").set_markup(net_txt)
        self.widget("overview-disk-usage-text").set_markup(dsk_txt)

        self.cpu_usage_graph.set_property("data_array",
                                          self.vm.host_cpu_time_vector())
        self.memory_usage_graph.set_property("data_array",
                                             self.vm.stats_memory_vector())
        self.disk_io_graph.set_property("data_array",
                                        self.vm.disk_io_vector())
        self.network_traffic_graph.set_property("data_array",
                                                self.vm.network_traffic_vector())

    def _refresh_cpu_count(self):
        conn = self.vm.conn
        host_active_count = conn.host_active_processor_count()
        maxvcpus = self.vm.vcpu_max_count()
        curvcpus = self.vm.vcpu_count()

        curadj = self.widget("config-vcpus").get_adjustment()
        maxadj = self.widget("config-maxvcpus").get_adjustment()
        curadj.value = int(curvcpus)
        maxadj.value = int(maxvcpus)

        self.widget("state-host-cpus").set_text(str(host_active_count))

        # Warn about overcommit
        warn = bool(self.config_get_vcpus() > host_active_count)
        self.widget("config-vcpus-warn-box").set_property("visible", warn)
    def _refresh_cpu_pinning(self):
        # Populate VCPU pinning
        vcpupin  = self.vm.vcpu_pinning()
        self.widget("config-vcpupin").set_text(vcpupin)

    def _refresh_runtime_pinning(self):
        conn = self.vm.conn
        host_active_count = conn.host_active_processor_count()

        vcpu_list = self.widget("config-vcpu-list")
        vcpu_model = vcpu_list.get_model()
        vcpu_model.clear()

        reason = ""
        if not self.vm.is_active():
            reason = _("VCPU info only available for running domain.")
        else:
            try:
                vcpu_info, vcpu_pinning = self.vm.vcpu_info()
            except Exception, e:
                reason = _("Error getting VCPU info: %s") % str(e)

            if not self.vm.getvcpus_supported:
                reason = _("Virtual machine does not support runtime "
                           "VPCU info.")

        vcpu_list.set_sensitive(not bool(reason))
        util.tooltip_wrapper(vcpu_list, reason or None)
        if reason:
            return

        def build_cpuset_str(pin_info):
            pinstr = ""
            for i in range(host_active_count):
                if i < len(pin_info) and pin_info[i]:
                    pinstr += (",%s" % str(i))

            return pinstr.strip(",")

        for idx in range(len(vcpu_info)):
            vcpu = str(vcpu_info[idx][0])
            vcpucur = str(vcpu_info[idx][3])
            vcpupin = build_cpuset_str(vcpu_pinning[idx])

            vcpu_model.append([vcpu, vcpucur, vcpupin])

    def _refresh_cpu_config(self, cpu):
        feature_ui = self.widget("cpu-features")
        model = cpu.model or ""
        caps = self.vm.conn.get_capabilities()

        capscpu = None
        try:
            arch = self.vm.get_arch()
            if arch:
                cpu_values = caps.get_cpu_values(arch)
                for c in cpu_values.cpus:
                    if model and c.model == model:
                        capscpu = c
                        break
        except:
            pass

        show_top = bool(cpu.sockets or cpu.cores or cpu.threads)
        sockets = cpu.sockets or 1
        cores = cpu.cores or 1
        threads = cpu.threads or 1

        self.widget("cpu-topology-enable").set_active(show_top)
        self.widget("cpu-model").child.set_text(model)
        self.widget("cpu-sockets").set_value(sockets)
        self.widget("cpu-cores").set_value(cores)
        self.widget("cpu-threads").set_value(threads)

        def get_feature_policy(name):
            for f in cpu.features:
                if f.name == name:
                    return f.policy

            if capscpu:
                for f in capscpu.features:
                    if f == name:
                        return "model"
            return "off"

        for row in feature_ui.get_model():
            row[1] = get_feature_policy(row[0])

    def refresh_config_cpu(self):
        self._cpu_copy_host = False
        cpu = self.vm.get_cpu_config()

        self._refresh_cpu_count()
        self._refresh_cpu_pinning()
        self._refresh_runtime_pinning()
        self._refresh_cpu_config(cpu)

    def refresh_config_memory(self):
        host_mem_widget = self.widget("state-host-memory")
        host_mem = self.vm.conn.host_memory_size() / 1024
        vm_cur_mem = self.vm.get_memory() / 1024.0
        vm_max_mem = self.vm.maximum_memory() / 1024.0

        host_mem_widget.set_text("%d MB" % (int(round(host_mem))))

        curmem = self.widget("config-memory").get_adjustment()
        maxmem = self.widget("config-maxmem").get_adjustment()
        curmem.value = int(round(vm_cur_mem))
        maxmem.value = int(round(vm_max_mem))

        if not self.widget("config-memory").get_property("sensitive"):
            maxmem.lower = curmem.value


    def refresh_disk_page(self):
        disk = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not disk:
            return

        path = disk.path
        devtype = disk.device
        ro = disk.read_only
        share = disk.shareable
        bus = disk.bus
        addr = disk.address.type
        idx = disk.disk_bus_index
        cache = disk.driver_cache
        io = disk.driver_io
        driver_type = disk.driver_type or ""
        serial = disk.serial
        show_format = (not self.is_customize_dialog or
                       disk.path_exists(disk.conn, disk.path))

        size = _("Unknown")
        if not path:
            size = "-"
        else:
            vol = self.conn.get_vol_by_path(path)
            if vol:
                size = vol.get_pretty_capacity()
            elif not self.conn.is_remote():
                ignore, val = virtinst.VirtualDisk.stat_local_path(path)
                if val != 0:
                    size = prettyify_bytes(val)

        is_cdrom = (devtype == virtinst.VirtualDisk.DEVICE_CDROM)
        is_floppy = (devtype == virtinst.VirtualDisk.DEVICE_FLOPPY)

        if addr == "spapr-vio":
            bus = "spapr-vscsi"

        pretty_name = prettyify_disk(devtype, bus, idx)

        self.widget("disk-source-path").set_text(path or "-")
        self.widget("disk-target-type").set_text(pretty_name)

        self.widget("disk-readonly").set_active(ro)
        self.widget("disk-readonly").set_sensitive(not is_cdrom)
        self.widget("disk-shareable").set_active(share)
        self.widget("disk-size").set_text(size)
        self.set_combo_label("disk-cache", cache)
        self.set_combo_label("disk-io", io)

        self.widget("disk-format").set_sensitive(show_format)
        self.widget("disk-format").child.set_text(driver_type)

        no_default = not self.is_customize_dialog

        self.populate_disk_bus_combo(devtype, no_default)
        self.set_combo_label("disk-bus", bus)
        self.widget("disk-serial").set_text(serial or "")

        button = self.widget("config-cdrom-connect")
        if is_cdrom or is_floppy:
            if not path:
                # source device not connected
                button.set_label(gtk.STOCK_CONNECT)
            else:
                button.set_label(gtk.STOCK_DISCONNECT)
            button.show()
        else:
            button.hide()

    def refresh_network_page(self):
        net = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not net:
            return

        nettype = net.type
        source = net.get_source()
        source_mode = net.source_mode
        model = net.model

        netobj = None
        if nettype == virtinst.VirtualNetworkInterface.TYPE_VIRTUAL:
            name_dict = {}
            for uuid in self.conn.list_net_uuids():
                vnet = self.conn.get_net(uuid)
                name = vnet.get_name()
                name_dict[name] = vnet

            if source and source in name_dict:
                netobj = name_dict[source]

        desc = uihelpers.pretty_network_desc(nettype, source, netobj)

        self.widget("network-mac-address").set_text(net.macaddr)
        uihelpers.populate_network_list(
                    self.widget("network-source-combo"),
                    self.conn)
        self.widget("network-source-combo").set_active(-1)

        self.widget("network-bridge").set_text("")
        def compare_network(model, info):
            for idx in range(len(model)):
                row = model[idx]
                if row[0] == info[0] and row[1] == info[1]:
                    return True, idx

            if info[0] == virtinst.VirtualNetworkInterface.TYPE_BRIDGE:
                idx = (len(model) - 1)
                self.widget("network-bridge").set_text(str(info[1]))
                return True, idx

            return False, 0

        self.set_combo_label("network-source",
                             (nettype, source), label=desc,
                             comparefunc=compare_network)

        # source mode
        uihelpers.populate_source_mode_combo(self.vm,
                            self.widget("network-source-mode-combo"))
        self.set_combo_label("network-source-mode", source_mode)

        # Virtualport config
        show_vport = (nettype == "direct")
        vport = net.virtualport
        self.widget("vport-expander").set_property("visible", show_vport)
        self.widget("vport-type").set_text(vport.type or "")
        self.widget("vport-managerid").set_text(vport.managerid or "")
        self.widget("vport-typeid").set_text(vport.typeid or "")
        self.widget("vport-typeidversion").set_text(vport.typeidversion or "")
        self.widget("vport-instanceid").set_text(vport.instanceid or "")

        uihelpers.populate_netmodel_combo(self.vm,
                                          self.widget("network-model-combo"))
        self.set_combo_label("network-model", model)

    def refresh_input_page(self):
        inp = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not inp:
            return

        ident = "%s:%s" % (inp.type, inp.bus)
        if   ident == "tablet:usb":
            dev = _("EvTouch USB Graphics Tablet")
        elif ident == "mouse:usb":
            dev = _("Generic USB Mouse")
        elif ident == "mouse:xen":
            dev = _("Xen Mouse")
        elif ident == "mouse:ps2":
            dev = _("PS/2 Mouse")
        else:
            dev = inp.bus + " " + inp.type

        if inp.type == "tablet":
            mode = _("Absolute Movement")
        else:
            mode = _("Relative Movement")

        self.widget("input-dev-type").set_text(dev)
        self.widget("input-dev-mode").set_text(mode)

        # Can't remove primary Xen or PS/2 mice
        if inp.type == "mouse" and inp.bus in ("xen", "ps2"):
            self.widget("config-remove").set_sensitive(False)
        else:
            self.widget("config-remove").set_sensitive(True)

    def refresh_graphics_page(self):
        gfx = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not gfx:
            return

        title = self.widget("graphics-title")
        table = self.widget("graphics-table")
        table.foreach(lambda w, ignore: w.hide(), ())

        def set_title(text):
            title.set_markup("<b>%s</b>" % text)

        def show_row(widget_name, suffix=""):
            base = "gfx-%s" % widget_name
            self.widget(base + "-title").show()
            self.widget(base + suffix).show()

        def show_text(widget_name, text):
            show_row(widget_name)
            self.widget("gfx-" + widget_name).set_text(text)

        def port_to_string(port):
            if port is None:
                return "-"
            return (port == -1 and _("Automatically allocated") or str(port))

        gtype = gfx.type
        is_vnc = (gtype == "vnc")
        is_sdl = (gtype == "sdl")
        is_spice = (gtype == "spice")
        is_other = not (True in [is_vnc, is_sdl, is_spice])

        set_title(_("%(graphicstype)s Server") %
                  {"graphicstype" : gfx.pretty_type_simple(gtype)})

        settype = ""
        if is_vnc or is_spice:
            port  = port_to_string(gfx.port)
            address = (gfx.listen or "127.0.0.1")
            keymap  = (gfx.keymap or None)
            passwd  = gfx.passwd or ""

            show_text("password", passwd)
            show_text("port", port)
            show_text("address", address)

            show_row("keymap", "-box")
            self.set_combo_label("gfx-keymap", keymap)
            settype = gtype

        if is_spice:
            tlsport = port_to_string(gfx.tlsPort)
            show_text("tlsport", tlsport)

        if is_sdl:
            set_title(_("Local SDL Window"))

            display = gfx.display or _("Unknown")
            xauth   = gfx.xauth or _("Unknown")

            show_text("display", display)
            show_text("xauth", xauth)

        if is_other:
            settype = gfx.pretty_type_simple(gtype)

        if settype:
            show_row("type", "-box")
            self.set_combo_label("gfx-type", gtype, label=settype)

    def refresh_sound_page(self):
        sound = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not sound:
            return

        self.set_combo_label("sound-model", sound.model)

    def refresh_smartcard_page(self):
        sc = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not sc:
            return

        self.set_combo_label("smartcard-mode", sc.mode)

    def refresh_redir_page(self):
        rd = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not rd:
            return

        address = build_redir_label(rd)[0] or "-"

        devlabel = "<b>Redirected %s Device</b>" % rd.bus.upper()
        self.widget("redir-title").set_markup(devlabel)
        self.widget("redir-address").set_text(address)

        self.widget("redir-type-label").set_text(rd.type)
        self.widget("redir-type-combo").hide()

    def refresh_char_page(self):
        chardev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not chardev:
            return

        show_target_type = not (chardev.dev_type in
                                [chardev.DEV_SERIAL, chardev.DEV_PARALLEL])

        def show_ui(param, val=None):
            widgetname = "char-" + param.replace("_", "-")
            labelname = widgetname + "-label"
            doshow = chardev.supports_property(param)

            # Exception: don't show target type for serial/parallel
            if (param == "target_type" and not show_target_type):
                doshow = False

            if not val and doshow:
                val = getattr(chardev, param)

            self.widget(widgetname).set_property("visible", doshow)
            self.widget(labelname).set_property("visible", doshow)
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
        dev_type = chardev.char_type or "pty"
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

        devtype = hostdev.type
        pretty_name = None
        nodedev = lookup_nodedev(self.vm.conn, hostdev)
        if nodedev:
            pretty_name = nodedev.pretty_name()

        if not pretty_name:
            pretty_name = build_hostdev_label(hostdev)[0] or "-"

        devlabel = "<b>Physical %s Device</b>" % devtype.upper()
        self.widget("hostdev-title").set_markup(devlabel)
        self.widget("hostdev-source").set_text(pretty_name)

    def refresh_video_page(self):
        vid = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not vid:
            return

        no_default = not self.is_customize_dialog
        uihelpers.populate_video_combo(self.vm,
                                self.widget("video-model-combo"),
                                no_default=no_default)

        model = vid.model_type
        ram = vid.vram
        heads = vid.heads
        try:
            ramlabel = ram and "%d MB" % (int(ram) / 1024) or "-"
        except:
            ramlabel = "-"

        self.widget("video-ram").set_text(ramlabel)
        self.widget("video-heads").set_text(heads and heads or "-")

        self.set_combo_label("video-model", model)

    def refresh_watchdog_page(self):
        watch = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not watch:
            return

        model = watch.model
        action = watch.action

        self.set_combo_label("watchdog-model", model)
        self.set_combo_label("watchdog-action", action)

    def refresh_controller_page(self):
        dev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not dev:
            return

        type_label = virtinst.VirtualController.pretty_type(dev.type)
        model_label = dev.model
        if not model_label:
            model_label = _("Default")

        self.widget("controller-type").set_text(type_label)

        combo = self.widget("controller-model-combo")
        model = combo.get_model()
        model.clear()
        if dev.type == virtinst.VirtualController.CONTROLLER_TYPE_USB:
            model.append(["Default", "Default"])
            model.append(["ich9-ehci1", "USB 2"])
            self.widget("config-remove").set_sensitive(False)
        else:
            self.widget("config-remove").set_sensitive(True)

        self.set_combo_label("controller-model", model_label)

    def refresh_filesystem_page(self):
        dev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not dev:
            return

        self.widget("fs-type").set_text(dev.type)

        # mode can be irrelevant depending on the fs driver type
        # selected.
        if dev.mode:
            self.show_pair("fs-mode", True)
            self.widget("fs-mode").set_text(dev.mode)
        else:
            self.show_pair("fs-mode", False)

        self.widget("fs-driver").set_text(dev.driver or _("Default"))

        self.widget("fs-wrpolicy").set_text(dev.wrpolicy or _("Default"))

        self.widget("fs-source").set_text(dev.source)
        self.widget("fs-target").set_text(dev.target)
        if dev.readonly:
            self.widget("fs-readonly").set_text("Yes")
        else:
            self.widget("fs-readonly").set_text("No")

    def refresh_boot_page(self):
        # Refresh autostart
        try:
            # Older libvirt versions return None if not supported
            autoval = self.vm.get_autostart()
        except libvirt.libvirtError:
            autoval = None

        # Autostart
        autostart_chk = self.widget("config-autostart")
        enable_autostart = (autoval is not None)
        autostart_chk.set_sensitive(enable_autostart)
        autostart_chk.set_active(enable_autostart and autoval or False)

        show_kernel = not self.vm.is_container()
        show_init = self.vm.is_container()
        show_boot = (not self.vm.is_container() and not self.vm.is_xenpv())

        self.widget("boot-order-align").set_property("visible", show_boot)
        self.widget("boot-kernel-align").set_property("visible", show_kernel)
        self.widget("boot-init-align").set_property("visible", show_init)

        # Kernel/initrd boot
        kernel, initrd, args = self.vm.get_boot_kernel_info()
        expand = bool(kernel or initrd or args)
        self.widget("boot-kernel").set_text(kernel or "")
        self.widget("boot-kernel-initrd").set_text(initrd or "")
        self.widget("boot-kernel-args").set_text(args or "")
        if expand:
            self.widget("boot-kernel-expander").set_expanded(True)

        # <init> populate
        init = self.vm.get_init()
        self.widget("boot-init-path").set_text(init or "")

        # Boot menu populate
        menu = self.vm.get_boot_menu() or False
        self.widget("boot-menu").set_active(menu)
        self.repopulate_boot_list()


    ############################
    # Hardware list population #
    ############################

    def populate_disk_bus_combo(self, devtype, no_default):
        buslist     = self.widget("disk-bus-combo")
        busmodel    = buslist.get_model()
        busmodel.clear()

        buses = []
        if devtype == virtinst.VirtualDisk.DEVICE_FLOPPY:
            buses.append(["fdc", "Floppy"])
        elif devtype == virtinst.VirtualDisk.DEVICE_CDROM:
            buses.append(["ide", "IDE"])
            if self.vm.rhel6_defaults():
                buses.append(["scsi", "SCSI"])
        else:
            if self.vm.is_hvm():
                buses.append(["ide", "IDE"])
                if self.vm.rhel6_defaults():
                    buses.append(["scsi", "SCSI"])
                    buses.append(["usb", "USB"])
            if self.vm.get_hv_type() in ["kvm", "test"]:
                buses.append(["sata", "SATA"])
                buses.append(["virtio", "Virtio"])
            if (self.vm.get_hv_type() == "kvm" and
                    self.vm.get_machtype() == "pseries"):
                buses.append(["spapr-vscsi", "sPAPR-vSCSI"])
            if self.vm.conn.is_xen() or self.vm.get_hv_type() == "test":
                buses.append(["xen", "Xen"])

        for row in buses:
            busmodel.append(row)
        if not no_default:
            busmodel.append([None, "default"])

    def populate_hw_list(self):
        hw_list_model = self.widget("hw-list").get_model()
        hw_list_model.clear()

        def add_hw_list_option(title, page_id, data, icon_name):
            hw_list_model.append([title, icon_name,
                                  gtk.ICON_SIZE_LARGE_TOOLBAR,
                                  page_id, data])

        add_hw_list_option("Overview", HW_LIST_TYPE_GENERAL, [], "computer")
        if not self.is_customize_dialog:
            add_hw_list_option("Performance", HW_LIST_TYPE_STATS, [],
                               "utilities-system-monitor")
        add_hw_list_option("Processor", HW_LIST_TYPE_CPU, [], "device_cpu")
        add_hw_list_option("Memory", HW_LIST_TYPE_MEMORY, [], "device_mem")
        add_hw_list_option("Boot Options", HW_LIST_TYPE_BOOT, [], "system-run")

        self.repopulate_hw_list()

    def repopulate_hw_list(self):
        hw_list = self.widget("hw-list")
        hw_list_model = hw_list.get_model()

        currentDevices = []

        def dev_cmp(origdev, newdev):
            if not origdev:
                return False

            if origdev == newdev:
                return True

            if not origdev.get_xml_node_path():
                return False

            return origdev.get_xml_node_path() == newdev.get_xml_node_path()

        def add_hw_list_option(idx, name, page_id, info, icon_name):
            hw_list_model.insert(idx, [name, icon_name,
                                       gtk.ICON_SIZE_LARGE_TOOLBAR,
                                       page_id, info])

        def update_hwlist(hwtype, info, name, icon_name):
            """
            See if passed hw is already in list, and if so, update info.
            If not in list, add it!
            """
            currentDevices.append(info)

            insertAt = 0
            for row in hw_list_model:
                rowdev = row[HW_LIST_COL_DEVICE]
                if dev_cmp(rowdev, info):
                    # Update existing HW info
                    row[HW_LIST_COL_DEVICE] = info
                    row[HW_LIST_COL_LABEL] = name
                    row[HW_LIST_COL_ICON_NAME] = icon_name
                    return

                if row[HW_LIST_COL_TYPE] <= hwtype:
                    insertAt += 1

            # Add the new HW row
            add_hw_list_option(insertAt, name, hwtype, info, icon_name)

        # Populate list of disks
        for disk in self.vm.get_disk_devices():
            devtype = disk.device
            bus = disk.bus
            idx = disk.disk_bus_index

            icon = "drive-harddisk"
            if devtype == "cdrom":
                icon = "media-optical"
            elif devtype == "floppy":
                icon = "media-floppy"

            if disk.address.type == "spapr-vio":
                bus = "spapr-vscsi"

            label = prettyify_disk(devtype, bus, idx)

            update_hwlist(HW_LIST_TYPE_DISK, disk, label, icon)

        # Populate list of NICs
        for net in self.vm.get_network_devices():
            mac = net.macaddr

            update_hwlist(HW_LIST_TYPE_NIC, net,
                          "NIC %s" % mac[-9:], "network-idle")

        # Populate list of input devices
        for inp in self.vm.get_input_devices():
            inptype = inp.type

            icon = "input-mouse"
            if inptype == "tablet":
                label = _("Tablet")
                icon = "input-tablet"
            elif inptype == "mouse":
                label = _("Mouse")
            else:
                label = _("Input")

            update_hwlist(HW_LIST_TYPE_INPUT, inp, label, icon)

        # Populate list of graphics devices
        for gfx in self.vm.get_graphics_devices():
            update_hwlist(HW_LIST_TYPE_GRAPHICS, gfx,
                          _("Display %s") % gfx.pretty_type_simple(gfx.type),
                          "video-display")

        # Populate list of sound devices
        for sound in self.vm.get_sound_devices():
            update_hwlist(HW_LIST_TYPE_SOUND, sound,
                          _("Sound: %s" % sound.model), "audio-card")

        # Populate list of char devices
        for chardev in self.vm.get_char_devices():
            devtype = chardev.virtual_device_type
            port = chardev.target_port

            label = devtype.capitalize()
            if devtype not in ["console", "channel"]:
                # Don't show port for console
                label += " %s" % (int(port) + 1)

            update_hwlist(HW_LIST_TYPE_CHAR, chardev, label,
                          "device_serial")

        # Populate host devices
        for hostdev in self.vm.get_hostdev_devices():
            devtype = hostdev.type
            label = build_hostdev_label(hostdev)[1]

            if devtype == "usb":
                icon = "device_usb"
            else:
                icon = "device_pci"
            update_hwlist(HW_LIST_TYPE_HOSTDEV, hostdev, label, icon)

        # Populate redir devices
        for redirdev in self.vm.get_redirdev_devices():
            bus = redirdev.bus
            label = build_redir_label(redirdev)[1]

            if bus == "usb":
                icon = "device_usb"
            else:
                icon = "device_pci"
            update_hwlist(HW_LIST_TYPE_REDIRDEV, redirdev, label, icon)

        # Populate video devices
        for vid in self.vm.get_video_devices():
            update_hwlist(HW_LIST_TYPE_VIDEO, vid, _("Video"), "video-display")

        # Populate watchdog devices
        for watch in self.vm.get_watchdog_devices():
            update_hwlist(HW_LIST_TYPE_WATCHDOG, watch, _("Watchdog"),
                          "device_pci")

        # Populate controller devices
        for cont in self.vm.get_controller_devices():
            # skip USB2 ICH9 companion controllers
            if cont.model in ["ich9-uhci1", "ich9-uhci2", "ich9-uhci3"]:
                continue

            pretty_type = virtinst.VirtualController.pretty_type(cont.type)
            update_hwlist(HW_LIST_TYPE_CONTROLLER, cont,
                          _("Controller %s") % pretty_type,
                          "device_pci")

        # Populate filesystem devices
        for fs in self.vm.get_filesystem_devices():
            target = fs.target[:8]
            update_hwlist(HW_LIST_TYPE_FILESYSTEM, fs,
                          _("Filesystem %s") % target,
                          gtk.STOCK_DIRECTORY)

        # Populate list of smartcard devices
        for sc in self.vm.get_smartcard_devices():
            update_hwlist(HW_LIST_TYPE_SMARTCARD, sc,
                          _("Smartcard"), "device_serial")

        devs = range(len(hw_list_model))
        devs.reverse()
        for i in devs:
            _iter = hw_list_model.iter_nth_child(None, i)
            olddev = hw_list_model[i][HW_LIST_COL_DEVICE]

            # Existing device, don't remove it
            if not olddev or olddev in currentDevices:
                continue

            hw_list_model.remove(_iter)

    def repopulate_boot_list(self, bootdevs=None, dev_select=None):
        boot_list = self.widget("config-boot-list")
        boot_model = boot_list.get_model()
        old_order = map(lambda x: x[BOOT_DEV_TYPE], boot_model)
        boot_model.clear()

        if bootdevs == None:
            bootdevs = self.vm.get_boot_device()

        boot_rows = {
            "hd" : ["hd", "Hard Disk", "drive-harddisk", False],
            "cdrom" : ["cdrom", "CDROM", "media-optical", False],
            "network" : ["network", "Network (PXE)", "network-idle", False],
            "fd" : ["fd", "Floppy", "media-floppy", False],
        }

        for dev in bootdevs:
            foundrow = None

            for key, row in boot_rows.items():
                if key == dev:
                    foundrow = row
                    del(boot_rows[key])
                    break

            if not foundrow:
                # Some boot device listed that we don't know about.
                foundrow = [dev, "Boot type '%s'" % dev,
                            "drive-harddisk", True]

            foundrow[BOOT_ACTIVE] = True
            boot_model.append(foundrow)

        # Append all remaining boot_rows that aren't enabled
        for dev in old_order:
            if dev in boot_rows:
                boot_model.append(boot_rows[dev])
                del(boot_rows[dev])

        for row in boot_rows.values():
            boot_model.append(row)

        boot_list.set_model(boot_model)
        selection = boot_list.get_selection()

        if dev_select:
            idx = 0
            for row in boot_model:
                if row[BOOT_DEV_TYPE] == dev_select:
                    break
                idx += 1

            boot_list.get_selection().select_path(str(idx))

        elif not selection.get_selected()[1]:
            # Set a default selection
            selection.select_path("0")

    def show_pair(self, basename, show):
        combo = self.widget(basename)
        label = self.widget(basename + "-title")

        combo.set_property("visible", show)
        label.set_property("visible", show)

vmmGObjectUI.type_register(vmmDetails)
vmmDetails.signal_new(vmmDetails, "action-save-domain", [str, str])
vmmDetails.signal_new(vmmDetails, "action-destroy-domain", [str, str])
vmmDetails.signal_new(vmmDetails, "action-suspend-domain", [str, str])
vmmDetails.signal_new(vmmDetails, "action-resume-domain", [str, str])
vmmDetails.signal_new(vmmDetails, "action-run-domain", [str, str])
vmmDetails.signal_new(vmmDetails, "action-shutdown-domain", [str, str])
vmmDetails.signal_new(vmmDetails, "action-reboot-domain", [str, str])
vmmDetails.signal_new(vmmDetails, "action-show-help", [str])
vmmDetails.signal_new(vmmDetails, "action-exit-app", [])
vmmDetails.signal_new(vmmDetails, "action-view-manager", [])
vmmDetails.signal_new(vmmDetails, "action-migrate-domain", [str, str])
vmmDetails.signal_new(vmmDetails, "action-clone-domain", [str, str])
vmmDetails.signal_new(vmmDetails, "details-closed", [])
vmmDetails.signal_new(vmmDetails, "details-opened", [])
vmmDetails.signal_new(vmmDetails, "customize-finished", [])

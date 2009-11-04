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

import gobject
import gtk
import gtk.glade
import libvirt
import logging
import traceback
import os

from virtManager.error import vmmErrorDialog
from virtManager.addhardware import vmmAddHardware
from virtManager.choosecd import vmmChooseCD
from virtManager.console import vmmConsolePages
from virtManager.manager import build_shutdown_button_menu
from virtManager.serialcon import vmmSerialConsole
from virtManager.graphwidgets import Sparkline
from virtManager import util as util

import virtinst

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

apply_pages  = [ HW_LIST_TYPE_GENERAL, HW_LIST_TYPE_CPU, HW_LIST_TYPE_MEMORY,
                 HW_LIST_TYPE_BOOT]
remove_pages = [ HW_LIST_TYPE_DISK, HW_LIST_TYPE_NIC, HW_LIST_TYPE_INPUT,
                 HW_LIST_TYPE_GRAPHICS, HW_LIST_TYPE_SOUND, HW_LIST_TYPE_CHAR,
                 HW_LIST_TYPE_HOSTDEV, HW_LIST_TYPE_VIDEO ]

# Main tab pages
PAGE_CONSOLE = 0
PAGE_DETAILS = 1
PAGE_DYNAMIC_OFFSET = 2


class vmmDetails(gobject.GObject):
    __gsignals__ = {
        "action-show-console": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-save-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str,str)),
        "action-destroy-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str,str)),
        "action-suspend-domain": (gobject.SIGNAL_RUN_FIRST,
                                  gobject.TYPE_NONE, (str, str)),
        "action-resume-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str, str)),
        "action-run-domain": (gobject.SIGNAL_RUN_FIRST,
                              gobject.TYPE_NONE, (str, str)),
        "action-shutdown-domain": (gobject.SIGNAL_RUN_FIRST,
                                   gobject.TYPE_NONE, (str, str)),
        "action-reboot-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str, str)),
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                               gobject.TYPE_NONE, [str]),
        "action-exit-app": (gobject.SIGNAL_RUN_FIRST,
                            gobject.TYPE_NONE, []),
        "action-view-manager": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, []),
        "action-migrate-domain": (gobject.SIGNAL_RUN_FIRST,
                                  gobject.TYPE_NONE, (str,str,str)),
        "action-clone-domain": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        }


    def __init__(self, config, vm, engine):
        self.__gobject_init__()
        self.window = gtk.glade.XML((config.get_glade_dir() +
                                     "/vmm-details.glade"),
                                     "vmm-details", domain="virt-manager")
        self.config = config
        self.vm = vm
        self.engine = engine

        self.topwin = self.window.get_widget("vmm-details")
        self.err = vmmErrorDialog(self.topwin,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))

        self.serial_tabs = []
        self.last_console_page = PAGE_CONSOLE
        self.addhw = None
        self.choose_cd = None

        self.ignorePause = False
        self.ignoreDetails = False

        self.console = vmmConsolePages(self.config, self.vm, self.engine,
                                       self.window)

        self.init_menus()
        self.init_details()

        self.serial_popup = None
        self.serial_copy = None
        self.serial_paste = None
        self.serial_close = None
        self.init_serial()

        self.cpu_usage_graph = None
        self.memory_usage_graph = None
        self.disk_io_graph = None
        self.network_traffic_graph = None
        self.init_graphs()

        self.window.signal_autoconnect({
            "on_close_details_clicked": self.close,
            "on_details_menu_close_activate": self.close,
            "on_vmm_details_delete_event": self.close,
            "on_details_menu_quit_activate": self.exit_app,

            "on_control_vm_details_toggled": self.details_console_changed,
            "on_control_vm_console_toggled": self.details_console_changed,
            "on_control_run_clicked": self.control_vm_run,
            "on_control_shutdown_clicked": self.control_vm_shutdown,
            "on_control_pause_toggled": self.control_vm_pause,
            "on_control_fullscreen_toggled": self.control_fullscreen,

            "on_details_menu_run_activate": self.control_vm_run,
            "on_details_menu_poweroff_activate": self.control_vm_shutdown,
            "on_details_menu_reboot_activate": self.control_vm_reboot,
            "on_details_menu_save_activate": self.control_vm_save_domain,
            "on_details_menu_destroy_activate": self.control_vm_destroy,
            "on_details_menu_pause_activate": self.control_vm_pause,
            "on_details_menu_migrate_activate": self.populate_migrate_menu,
            "on_details_menu_clone_activate": self.control_vm_clone,
            "on_details_menu_screenshot_activate": self.control_vm_screenshot,
            "on_details_menu_graphics_activate": self.control_vm_console,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,
            "on_details_menu_view_manager_activate": self.view_manager,
            "on_details_menu_view_details_toggled": self.details_console_changed,
            "on_details_menu_view_console_toggled": self.details_console_changed,

            "on_details_pages_switch_page": self.switch_page,

            "on_config_vcpus_changed": self.config_vcpus_changed,
            "on_config_memory_changed": self.config_memory_changed,
            "on_config_maxmem_changed": self.config_maxmem_changed,
            "on_config_boot_device_changed": self.config_boot_options_changed,
            "on_config_autostart_changed": self.config_boot_options_changed,

            "on_config_apply_clicked": self.config_apply,

            "on_details_help_activate": self.show_help,

            "on_config_cdrom_connect_clicked": self.toggle_cdrom,
            "on_config_remove_clicked": self.remove_xml_dev,
            "on_add_hardware_button_clicked": self.add_hardware,

            "on_security_label_changed": self.security_label_changed,
            "on_security_type_changed": self.security_type_changed,
            "on_security_model_changed": self.security_model_changed,

            # Listeners stored in vmmConsolePages
            "on_details_menu_view_fullscreen_activate": self.console.toggle_fullscreen,
            "on_details_menu_view_scale_always_toggled": self.console.set_scale_type,
            "on_details_menu_view_scale_fullscreen_toggled": self.console.set_scale_type,
            "on_details_menu_view_scale_never_toggled": self.console.set_scale_type,

            "on_details_menu_send_cad_activate": self.console.send_key,
            "on_details_menu_send_cab_activate": self.console.send_key,
            "on_details_menu_send_caf1_activate": self.console.send_key,
            "on_details_menu_send_caf2_activate": self.console.send_key,
            "on_details_menu_send_caf3_activate": self.console.send_key,
            "on_details_menu_send_caf4_activate": self.console.send_key,
            "on_details_menu_send_caf5_activate": self.console.send_key,
            "on_details_menu_send_caf6_activate": self.console.send_key,
            "on_details_menu_send_caf7_activate": self.console.send_key,
            "on_details_menu_send_caf8_activate": self.console.send_key,
            "on_details_menu_send_caf9_activate": self.console.send_key,
            "on_details_menu_send_caf10_activate": self.console.send_key,
            "on_details_menu_send_caf11_activate": self.console.send_key,
            "on_details_menu_send_caf12_activate": self.console.send_key,
            "on_details_menu_send_printscreen_activate": self.console.send_key,

            "on_console_auth_password_activate": self.console.auth_login,
            "on_console_auth_login_clicked": self.console.auth_login,
        })

        # Deliberately keep all this after signal connection
        self.vm.connect("status-changed", self.update_widget_states)
        self.vm.connect("resources-sampled", self.refresh_resources)
        self.vm.connect("config-changed", self.refresh_vm_info)
        self.window.get_widget("hw-list").get_selection().connect("changed", self.hw_selected)

        self.update_widget_states(self.vm, self.vm.status())

        self.populate_hw_list()
        self.repopulate_boot_list()

        self.hw_selected(page=0)
        self.refresh_vm_info()


    def show(self):
        if self.is_visible():
            self.topwin.present()
            return
        self.topwin.show()
        self.topwin.present()

        self.engine.increment_window_counter()
        self.update_widget_states(self.vm, self.vm.status())

    def close(self,ignore1=None,ignore2=None):
        fs = self.window.get_widget("details-menu-view-fullscreen")
        if fs.get_active():
            fs.set_active(False)

        if not self.is_visible():
            return

        self.topwin.hide()
        if self.console.vncViewer.flags() & gtk.VISIBLE:
            try:
                self.console.vncViewer.close()
            except:
                logging.error("Failure when disconnecting from VNC server")
        self.engine.decrement_window_counter()
        return 1

    def is_visible(self):
        if self.topwin.flags() & gtk.VISIBLE:
            return 1
        return 0


    ##########################
    # Initialization helpers #
    ##########################

    def init_menus(self):
        # Shutdown button menu
        build_shutdown_button_menu(self.config,
                                   self.window.get_widget("control-shutdown"),
                                   self.control_vm_shutdown,
                                   self.control_vm_reboot,
                                   self.control_vm_destroy)

        # Serial list menu
        smenu = gtk.Menu()
        smenu.connect("show", self.populate_serial_menu)
        self.window.get_widget("details-menu-view-serial-list").set_submenu(smenu)

        # Don't allowing changing network/disks for Dom0
        dom0 = self.vm.is_management_domain()
        self.window.get_widget("add-hardware-button").set_sensitive(not dom0)

        self.window.get_widget("hw-panel").set_show_tabs(False)
        self.window.get_widget("details-pages").set_show_tabs(False)
        self.window.get_widget("console-pages").set_show_tabs(False)
        self.window.get_widget("details-menu-view-toolbar").set_active(self.config.get_details_show_toolbar())

        # XXX: Help docs useless/out of date
        self.window.get_widget("help_menuitem").hide()

    def init_serial(self):
        self.serial_popup = gtk.Menu()

        self.serial_copy = gtk.ImageMenuItem(gtk.STOCK_COPY)
        self.serial_popup.add(self.serial_copy)

        self.serial_paste = gtk.ImageMenuItem(gtk.STOCK_PASTE)
        self.serial_popup.add(self.serial_paste)

        self.serial_popup.add(gtk.SeparatorMenuItem())

        self.serial_close = gtk.ImageMenuItem(_("Close tab"))
        close_image = gtk.Image()
        close_image.set_from_stock(gtk.STOCK_CLOSE, gtk.ICON_SIZE_MENU)
        self.serial_close.set_image(close_image)
        self.serial_popup.add(self.serial_close)

    def init_graphs(self):
        graph_table = self.window.get_widget("graph-table")

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
        self.disk_io_graph.set_property("rgb", map(lambda x: x/255.0,
                                        [0x82, 0x00, 0x3B, 0x29, 0x5C, 0x45]))
        graph_table.attach(self.disk_io_graph, 1, 2, 2, 3)

        self.network_traffic_graph = Sparkline()
        self.network_traffic_graph.set_property("reversed", True)
        self.network_traffic_graph.set_property("filled", False)
        self.network_traffic_graph.set_property("num_sets", 2)
        self.network_traffic_graph.set_property("rgb",
                                                map(lambda x: x/255.0,
                                                    [0x82, 0x00, 0x3B,
                                                     0x29, 0x5C, 0x45]))
        graph_table.attach(self.network_traffic_graph, 1, 2, 3, 4)

    def init_details(self):
        # Disable all 'machine details' options since we don't yet allow edit
        self.window.get_widget("overview-clock-combo").set_sensitive(False)
        self.window.get_widget("overview-acpi").set_sensitive(False)
        self.window.get_widget("overview-apic").set_sensitive(False)

        # Hardware list
        # [ label, icon name, icon size, hw type, hw data ]
        hw_list_model = gtk.ListStore(str, str, int, int,
                                      gobject.TYPE_PYOBJECT)
        self.window.get_widget("hw-list").set_model(hw_list_model)

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
        self.window.get_widget("hw-list").append_column(hwCol)

        # Clock combo
        clock_combo = self.window.get_widget("overview-clock-combo")
        clock_model = gtk.ListStore(str)
        clock_combo.set_model(clock_model)
        text = gtk.CellRendererText()
        clock_combo.pack_start(text, True)
        clock_combo.add_attribute(text, 'text', 0)
        clock_model.set_sort_column_id(0, gtk.SORT_ASCENDING)
        for offset in [ "localtime", "utc" ]:
            clock_model.append([offset])

        # Security info tooltips
        util.tooltip_wrapper(self.window.get_widget("security-static-info"),
            _("Static SELinux security type tells libvirt to always start the guest process with the specified label. The administrator is responsible for making sure the images are labeled corectly on disk."))
        util.tooltip_wrapper(self.window.get_widget("security-dynamic-info"),
            _("The dynamic SELinux security type tells libvirt to automatically pick a unique label for the guest process and guest image, ensuring total isolation of the guest. (Default)"))

        # Boot device list
        boot_list = self.window.get_widget("config-boot-device")
        # model = [ display name, icon name, boot type (hd, fd, etc) ]
        boot_list_model = gtk.ListStore(str, str, str)
        boot_list.set_model(boot_list_model)

        icon = gtk.CellRendererPixbuf()
        boot_list.pack_start(icon, False)
        boot_list.add_attribute(icon, 'icon-name', 1)
        text = gtk.CellRendererText()
        boot_list.pack_start(text, True)
        boot_list.add_attribute(text, 'text', 0)


    ##########################
    # Window state listeners #
    ##########################

    def populate_serial_menu(self, src):
        for ent in src:
            src.remove(ent)

        devs = self.vm.get_serial_devs()
        if len(devs) == 0:
            item = gtk.MenuItem(_("No serial devices found"))
            item.set_sensitive(False)
            src.add(item)

        on_serial = (self.last_console_page >= PAGE_DYNAMIC_OFFSET)
        serial_page_dev = None
        if on_serial:
            serial_idx = self.last_console_page - PAGE_DYNAMIC_OFFSET
            if len(self.serial_tabs) >= serial_idx:
                serial_page_dev = self.serial_tabs[serial_idx]
        on_graphics = (self.last_console_page == PAGE_CONSOLE)

        group = None
        usable_types = [ "pty" ]
        for dev in devs:
            sensitive = False
            msg = ""
            item = gtk.RadioMenuItem(group, dev[0])
            if group == None:
                group = item

            if self.vm.get_connection().is_remote():
                msg = _("Serial console not yet supported over remote "
                        "connection.")
            elif not self.vm.is_active():
                msg = _("Serial console not available for inactive guest.")
            elif not dev[1] in usable_types:
                msg = _("Console for device type '%s' not yet supported.") % \
                        dev[1]
            elif dev[2] and not os.access(dev[2], os.R_OK | os.W_OK):
                msg = _("Can not access console path '%s'.") % str(dev[2])
            else:
                sensitive = True

            if not sensitive:
                util.tooltip_wrapper(item, msg)
            item.set_sensitive(sensitive)

            if sensitive and on_serial and serial_page_dev == dev[0]:
                # Tab is already open, make sure marked as such
                item.set_active(True)
            item.connect("toggled", self.control_serial_tab, dev[0], dev[3])
            src.add(item)

        src.add(gtk.SeparatorMenuItem())

        devs = self.vm.get_graphics_devices()
        if len(devs) == 0:
            item = gtk.MenuItem(_("No graphics console found."))
            item.set_sensitive(False)
            src.add(item)
        else:
            dev = devs[0]
            item = gtk.RadioMenuItem(group, _("Graphical Console %s") % dev[2])
            if group == None:
                group = item

            if on_graphics:
                item.set_active(True)
            item.connect("toggled", self.control_serial_tab, dev[0], dev[2])
            src.add(item)

        src.show_all()

    def populate_migrate_menu(self, ignore1=None):
        menu = self.window.get_widget("details-menu-migrate_menu")
        self.engine.populate_migrate_menu(menu, self.control_vm_migrate,
                                          self.vm)

    def control_fullscreen(self, src):
        menu = self.window.get_widget("details-menu-view-fullscreen")
        if src.get_active() != menu.get_active():
            menu.set_active(src.get_active())

    def toggle_toolbar(self, src):
        active = src.get_active()
        self.config.set_details_show_toolbar(active)
        if active and not \
           self.window.get_widget("details-menu-view-fullscreen").get_active():
            self.window.get_widget("toolbar-box").show()
        else:
            self.window.get_widget("toolbar-box").hide()

    def get_hw_selection(self, field):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] == None:
            return None
        else:
            return active[0].get_value(active[1], field)

    def hw_selected(self, src=None, page=None, selected=True):
        pagetype = page
        if pagetype is None:
            pagetype = self.get_hw_selection(HW_LIST_COL_TYPE)

        if pagetype is None:
            pagetype = HW_LIST_TYPE_GENERAL
            self.window.get_widget("hw-list").get_selection().select_path(0)

        self.window.get_widget("config-remove").set_sensitive(True)
        self.window.get_widget("hw-panel").set_sensitive(True)
        self.window.get_widget("hw-panel").show_all()

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
        else:
            pagetype = -1

        app = pagetype in apply_pages
        rem = pagetype in remove_pages
        if selected:
            self.window.get_widget("config-apply").set_sensitive(False)
        self.window.get_widget("config-apply").set_property("visible", app)
        self.window.get_widget("config-remove").set_property("visible", rem)

        self.window.get_widget("hw-panel").set_current_page(pagetype)

    def details_console_changed(self, src):
        if self.ignoreDetails:
            return

        if not src.get_active():
            return

        is_details = False
        if (src == self.window.get_widget("control-vm-details") or
            src == self.window.get_widget("details-menu-view-details")):
            is_details = True

        pages = self.window.get_widget("details-pages")
        if is_details:
            pages.set_current_page(PAGE_DETAILS)
        else:
            pages.set_current_page(self.last_console_page)

    def sync_details_console_view(self, is_details):
        details = self.window.get_widget("control-vm-details")
        details_menu = self.window.get_widget("details-menu-view-details")
        console = self.window.get_widget("control-vm-console")
        console_menu = self.window.get_widget("details-menu-view-console")

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

        if newpage == PAGE_CONSOLE or newpage >= PAGE_DYNAMIC_OFFSET:
            self.last_console_page = newpage

    def update_widget_states(self, vm, status):
        self.toggle_toolbar(self.window.get_widget("details-menu-view-toolbar"))

        destroy = vm.is_destroyable()
        run     = vm.is_runable()
        stop    = vm.is_stoppable()
        paused  = vm.is_paused()
        ro      = vm.is_read_only()

        self.window.get_widget("details-menu-destroy").set_sensitive(destroy)
        self.window.get_widget("control-run").set_sensitive(run)
        self.window.get_widget("details-menu-run").set_sensitive(run)

        self.window.get_widget("control-shutdown").set_sensitive(stop)
        self.window.get_widget("details-menu-shutdown").set_sensitive(stop)
        self.window.get_widget("details-menu-save").set_sensitive(stop)
        self.window.get_widget("control-pause").set_sensitive(stop)
        self.window.get_widget("details-menu-pause").set_sensitive(stop)

        # Set pause widget states
        try:
            self.ignorePause = True
            self.window.get_widget("control-pause").set_active(paused)
            self.window.get_widget("details-menu-pause").set_active(paused)
        finally:
            self.ignorePause = False

        self.window.get_widget("config-vcpus").set_sensitive(not ro)
        self.window.get_widget("config-vcpupin").set_sensitive(not ro)
        self.window.get_widget("config-memory").set_sensitive(not ro)
        self.window.get_widget("config-maxmem").set_sensitive(not ro)
        self.window.get_widget("details-menu-migrate").set_sensitive(not ro)

        self.console.update_widget_states(vm, status)

        self.window.get_widget("overview-status-text").set_text(self.vm.run_status())
        self.window.get_widget("overview-status-icon").set_from_pixbuf(self.vm.run_status_icon())


    #############################
    # External action listeners #
    #############################

    def show_help(self, src):
        self.emit("action-show-help", "virt-manager-details-window")

    def view_manager(self, src):
        self.emit("action-view-manager")

    def exit_app(self, src):
        self.emit("action-exit-app")

    def activate_console_page(self):
        self.window.get_widget("details-pages").set_current_page(PAGE_CONSOLE)

    def activate_performance_page(self):
        self.window.get_widget("details-pages").set_current_page(PAGE_DETAILS)
        self.window.get_widget("hw-panel").set_current_page(HW_LIST_TYPE_STATS)

    def activate_config_page(self):
        self.window.get_widget("details-pages").set_current_page(PAGE_DETAILS)

    def add_hardware(self, src):
        if self.addhw is None:
            self.addhw = vmmAddHardware(self.config, self.vm)

        self.addhw.show()

    def remove_xml_dev(self, src):
        info = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not info:
            return

        self.remove_device(info[0], info[1])

    def control_vm_pause(self, src):
        if self.ignorePause:
            return

        if src.get_active():
            self.emit("action-suspend-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())
        else:
            self.emit("action-resume-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

        self.update_widget_states(self.vm, self.vm.status())

    def control_vm_run(self, src):
        self.emit("action-run-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_shutdown(self, src):
        self.emit("action-shutdown-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_reboot(self, src):
        self.emit("action-reboot-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_console(self, src):
        self.emit("action-show-console", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_save_domain(self, src):
        self.emit("action-save-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_destroy(self, src):
        self.emit("action-destroy-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_clone(self, src):
        self.emit("action-clone-domain", self.vm.get_connection().get_uri(),
                  self.vm.get_uuid())

    def control_vm_migrate(self, src, uri):
        self.emit("action-migrate-domain", self.vm.get_connection().get_uri(),
                  self.vm.get_uuid(), uri)

    def control_vm_screenshot(self, src):
        # If someone feels kind they could extend this code to allow
        # user to choose what image format they'd like to save in....
        path = util.browse_local(self.topwin,
                                 _("Save Virtual Machine Screenshot"),
                                 self.config, self.vm.get_connection(),
                                 _type = ("png", "PNG files"),
                                 dialog_type = gtk.FILE_CHOOSER_ACTION_SAVE,
                                 browse_reason=self.config.CONFIG_DIR_SCREENSHOT)
        if not path:
            return

        filename = path
        if not(filename.endswith(".png")):
            filename += ".png"
        image = self.console.vncViewer.get_pixbuf()

        # Save along with a little metadata about us & the domain
        image.save(filename, 'png',
                   { 'tEXt::Hypervisor URI': self.vm.get_connection().get_uri(),
                     'tEXt::Domain Name': self.vm.get_name(),
                     'tEXt::Domain UUID': self.vm.get_uuid(),
                     'tEXt::Generator App': self.config.get_appname(),
                     'tEXt::Generator Version': self.config.get_appversion() })

        msg = gtk.MessageDialog(self.topwin,
                                gtk.DIALOG_MODAL,
                                gtk.MESSAGE_INFO,
                                gtk.BUTTONS_OK,
                                (_("The screenshot has been saved to:\n%s") %
                                 filename))
        msg.set_title(_("Screenshot saved"))
        msg.run()
        msg.destroy()


    # ------------------------------
    # Serial Console pieces
    # ------------------------------

    def control_serial_tab(self, src, name, target_port):
        is_graphics = (name == "graphics")
        is_serial = not is_graphics

        if is_graphics:
            self.window.get_widget("details-pages").set_current_page(PAGE_CONSOLE)
        elif is_serial:
            self._show_serial_tab(name, target_port)

    def show_serial_rcpopup(self, src, event):
        if event.button != 3:
            return

        self.serial_popup.show_all()
        self.serial_copy.connect("activate", self.serial_copy_text, src)
        self.serial_paste.connect("activate", self.serial_paste_text, src)
        self.serial_close.connect("activate", self.serial_close_tab,
                                  self.window.get_widget("details-pages").get_current_page())

        if src.get_has_selection():
            self.serial_copy.set_sensitive(True)
        else:
            self.serial_copy.set_sensitive(False)
        self.serial_popup.popup(None, None, None, 0, event.time)

    def serial_close_tab(self, src, pagenum):
        tab_idx = (pagenum - PAGE_DYNAMIC_OFFSET)
        if (tab_idx < 0) or (tab_idx > len(self.serial_tabs)-1):
            return
        return self._close_serial_tab(self.serial_tabs[tab_idx])

    def serial_copy_text(self, src, terminal):
        terminal.copy_clipboard()

    def serial_paste_text(self, src, terminal):
        terminal.paste_clipboard()

    def _show_serial_tab(self, name, target_port):
        if not self.serial_tabs.count(name):
            child = vmmSerialConsole(self.vm, target_port)
            child.terminal.connect("button-press-event",
                                   self.show_serial_rcpopup)
            title = gtk.Label(name)
            child.show_all()
            self.window.get_widget("details-pages").append_page(child, title)
            self.serial_tabs.append(name)

        page_idx = self.serial_tabs.index(name) + PAGE_DYNAMIC_OFFSET
        self.window.get_widget("details-pages").set_current_page(page_idx)

    def _close_serial_tab(self, name):
        if not self.serial_tabs.count(name):
            return

        page_idx = self.serial_tabs.index(name) + PAGE_DYNAMIC_OFFSET
        self.window.get_widget("details-pages").remove_page(page_idx)
        self.serial_tabs.remove(name)


    ##############################
    # Details/Hardware listeners #
    ##############################

    # Overview -> Security
    def security_model_changed(self, combo):
        model = combo.get_model()
        idx = combo.get_active()
        if idx < 0:
            return

        self.window.get_widget("config-apply").set_sensitive(True)
        val = model[idx][0]
        show_type = (val == "selinux")
        self.window.get_widget("security-type-box").set_sensitive(show_type)

    def security_label_changed(self, label):
        self.window.get_widget("config-apply").set_sensitive(True)

    def security_type_changed(self, button, sensitive = True):
        self.window.get_widget("config-apply").set_sensitive(True)
        self.window.get_widget("security-label").set_sensitive(not button.get_active())

    # CPUS
    def config_vcpus_changed(self, src):
        self.window.get_widget("config-apply").set_sensitive(True)

    # Memory
    def config_get_maxmem(self):
        maxadj = self.window.get_widget("config-maxmem").get_adjustment()
        txtmax = self.window.get_widget("config-maxmem").get_text()
        try:
            maxmem = int(txtmax)
        except:
            maxmem = maxadj.value
        return maxmem

    def config_get_memory(self):
        memadj = self.window.get_widget("config-memory").get_adjustment()
        txtmem = self.window.get_widget("config-memory").get_text()
        try:
            mem = int(txtmem)
        except:
            mem = memadj.value
        return mem

    def config_maxmem_changed(self, src):
        self.window.get_widget("config-apply").set_sensitive(True)

    def config_memory_changed(self, src):
        self.window.get_widget("config-apply").set_sensitive(True)

        maxadj = self.window.get_widget("config-maxmem").get_adjustment()

        mem = self.config_get_memory()
        if maxadj.value < mem:
            maxadj.value = mem
        maxadj.lower = mem

    # Boot device / Autostart
    def config_boot_options_changed(self, src):
        self.window.get_widget("config-apply").set_sensitive(True)


    ##################################################
    # Details/Hardware config changes (apply button) #
    ##################################################

    def config_apply(self, ignore):
        pagetype = self.get_hw_selection(HW_LIST_COL_TYPE)
        ret = False

        if pagetype is HW_LIST_TYPE_GENERAL:
            ret = self.config_security_apply()
        elif pagetype is HW_LIST_TYPE_CPU:
            ret = self.config_vcpus_apply()
        elif pagetype is HW_LIST_TYPE_MEMORY:
            ret = self.config_memory_apply()
        elif pagetype is HW_LIST_TYPE_BOOT:
            ret = self.config_boot_options_apply()
        else:
            ret = False

        if ret is not False:
            self.window.get_widget("config-apply").set_sensitive(False)

    # Overview -> Security
    def config_security_apply(self):
        combo = self.window.get_widget("security-model")
        model = combo.get_model()
        semodel = model[combo.get_active()][0]

        if not semodel or str(semodel).lower() == "none":
            semodel = None

        if self.window.get_widget("security-dynamic").get_active():
            setype = "dynamic"
        else:
            setype = "static"

        selabel = self.window.get_widget("security-label").get_text()
        try:
            self.vm.define_seclabel(semodel, setype, selabel)
        except Exception, e:
            self.err.show_err(_("Error Setting Security data: %s") % str(e),
                              "".join(traceback.format_exc()))
            return False

    # CPUs
    def config_vcpus_apply(self):
        vcpus = self.window.get_widget("config-vcpus").get_adjustment().value
        cpuset = self.window.get_widget("config-vcpupin").get_text()

        logging.info("Setting vcpus for %s to %s, cpuset is %s" %
                     (self.vm.get_name(), str(vcpus), cpuset))
        hotplug_err = False

        try:
            if self.vm.is_active():
                self.vm.hotplug_vcpus(vcpus)
        except Exception, e:
            logging.debug("VCPU hotplug failed: %s" % str(e))
            hotplug_err = True

        # Change persistent config
        try:
            self.vm.define_vcpus(vcpus, cpuset)
        except Exception, e:
            self.err.show_err(_("Error changing vcpu value: %s" % str(e)),
                              "".join(traceback.format_exc()))
            return False

        if hotplug_err:
            self.err.show_info(_("These changes will take effect after the "
                                 "next guest reboot. "))
    # Memory
    def config_memory_apply(self):
        self.refresh_config_memory()
        hotplug_err = False

        curmem = None
        maxmem = self.config_get_maxmem()
        if self.window.get_widget("config-memory").get_property("sensitive"):
            curmem = self.config_get_memory()

        if curmem:
            curmem = int(curmem) * 1024
        if maxmem:
            maxmem = int(maxmem) * 1024

        try:
            if self.vm.is_active():
                self.vm.hotplug_both_mem(curmem, maxmem)
        except Exception, e:
            logging.debug("Memory hotplug failed: %s" % str(e))
            hotplug_err = True

        # Change persistent config
        try:
            self.vm.define_both_mem(curmem, maxmem)
        except Exception, e:
            self.err.show_err(_("Error changing memory values: %s" % str(e)),
                              "".join(traceback.format_exc()))
            return False

        if hotplug_err:
            self.err.show_info(_("These changes will take effect after the "
                                 "next guest reboot. "))

    # Boot device / Autostart
    def config_boot_options_apply(self):
        boot = self.window.get_widget("config-boot-device")
        auto = self.window.get_widget("config-autostart")
        if auto.get_property("sensitive"):
            try:
                self.vm.set_autostart(auto.get_active())
            except Exception, e:
                self.err.show_err(_("Error changing autostart value: %s") % \
                                  str(e), "".join(traceback.format_exc()))

        if boot.get_property("sensitive"):
            try:
                self.vm.set_boot_device(boot.get_model()[boot.get_active()][2])
            except Exception, e:
                self.err.show_err(_("Error changing boot device: %s" % str(e)),
                                  "".join(traceback.format_exc()))
                return False

    # CDROM
    def toggle_cdrom(self, src):
        info = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not info:
            return

        dev_id_info = info[1]

        if src.get_label() == gtk.STOCK_DISCONNECT:
            # Disconnect cdrom
            self.vm.change_cdrom_media(dev_id_info, None)

        else:
            # connect a new cdrom
            if self.choose_cd is None:
                self.choose_cd = vmmChooseCD(self.config,
                                             dev_id_info,
                                             self.vm.get_connection())
                self.choose_cd.connect("cdrom-chosen", self.change_cdrom_media)
            else:
                self.choose_cd.dev_id_info = dev_id_info
            self.choose_cd.show()

    def change_cdrom_media(self, ignore, dev_id_info, newpath, _type=None):
        try:
            self.vm.change_cdrom_media(dev_id_info, newpath, _type)
        except Exception, e:
            self.err.show_err(_("Error changing CDROM media: %s" % str(e)),
                              "".join(traceback.format_exc()))

    def remove_device(self, dev_type, dev_id_info):
        logging.debug("Removing device: %s %s" % (dev_type, dev_id_info))

        detach_err = False
        devxml = self.vm.get_device_xml(dev_type, dev_id_info)
        try:
            if self.vm.is_active():
                self.vm.detach_device(devxml)
                return
        except Exception, e:
            logging.debug("Device could not be hotUNplugged: %s" % str(e))
            detach_err = True

        if detach_err:
            if not self.err.yes_no(_("Are you sure you want to remove this "
                                     "device?"),
                                   _("This device could not be removed from "
                                     "the running machine. Would you like to "
                                     "remove the device after the next VM "
                                     "shutdown? \n\n"
                                     "Warning: this will overwrite any "
                                     "other changes that require a VM "
                                     "reboot.")):
                return

        try:
            self.vm.remove_device(dev_type, dev_id_info)
        except Exception, e:
            self.err.show_err(_("Error Removing Device: %s" % str(e)),
                              "".join(traceback.format_exc()))


    ########################
    # Details page refresh #
    ########################

    def refresh_resources(self, ignore):
        details = self.window.get_widget("details-pages")
        page = details.get_current_page()

        # If the dialog is visible, we want to make sure the XML is always
        # up to date
        if self.is_visible():
            self.vm.refresh_xml()

        if (page == PAGE_DETAILS and
            self.get_hw_selection(HW_LIST_COL_TYPE) == HW_LIST_TYPE_STATS):
            self.refresh_stats_page()

    def refresh_vm_info(self, ignore=None):
        details = self.window.get_widget("details-pages")
        self.page_refresh(details.get_current_page())

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

        pagetype = self.get_hw_selection(HW_LIST_COL_TYPE)
        self.hw_selected(page=pagetype)

    def refresh_overview_page(self):
        # Basic details
        self.window.get_widget("overview-name").set_text(self.vm.get_name())
        self.window.get_widget("overview-uuid").set_text(self.vm.get_uuid())

        # Hypervisor Details
        self.window.get_widget("overview-hv").set_text(self.vm.get_pretty_hv_type())
        arch = self.vm.get_arch() or _("Unknown")
        emu = self.vm.get_emulator() or _("None")
        self.window.get_widget("overview-arch").set_text(arch)
        self.window.get_widget("overview-emulator").set_text(emu)

        # Machine settings
        acpi = self.vm.get_acpi()
        apic = self.vm.get_apic()
        clock = self.vm.get_clock()

        self.window.get_widget("overview-acpi").set_active(acpi)
        self.window.get_widget("overview-apic").set_active(apic)
        if not clock:
            clock = _("Same as host")

        clock_combo = self.window.get_widget("overview-clock-combo")
        clock_label = self.window.get_widget("overview-clock-label")
        clock_list = map(lambda x: x[0], clock_combo.get_model())
        clock_in_combo = (clock in clock_list)

        clock_combo.set_property("visible", clock_in_combo)
        clock_label.set_property("visible", not clock_in_combo)
        if clock_in_combo:
            clock_combo.set_active(clock_list.index(clock))
        else:
            clock_label.set_text(clock)

        # Security details
        vmmodel, ignore, vmlabel = self.vm.get_seclabel()
        semodel_combo = self.window.get_widget("security-model")
        semodel_model = semodel_combo.get_model()
        caps = self.vm.get_connection().get_capabilities()

        semodel_model.clear()
        semodel_model.append(["None"])
        if caps.host.secmodel and caps.host.secmodel.model:
            semodel_model.append([caps.host.secmodel.model])

        active = 0
        for i in range(0, len(semodel_model)):
            if vmmodel and vmmodel == semodel_model[i][0]:
                active = i
                break
        semodel_combo.set_active(active)

        if self.vm.get_seclabel()[1] == "static":
            self.window.get_widget("security-static").set_active(True)
        else:
            self.window.get_widget("security-dynamic").set_active(True)

        self.window.get_widget("security-label").set_text(vmlabel)
        semodel_combo.emit("changed")

    def refresh_stats_page(self):
        def _rx_tx_text(rx, tx, unit):
            return '<span color="#82003B">%(rx)d %(unit)s in</span>\n<span color="#295C45">%(tx)d %(unit)s out</span>' % locals()

        cpu_txt = _("Disabled")
        mem_txt = _("Disabled")
        dsk_txt = _("Disabled")
        net_txt = _("Disabled")

        cpu_txt = "%d %%" % self.vm.cpu_time_percentage()

        vm_memory = self.vm.current_memory()
        host_memory = self.vm.get_connection().host_memory_size()
        mem_txt = "%d MB of %d MB" % (int(round(vm_memory/1024.0)),
                                      int(round(host_memory/1024.0)))

        if self.config.get_stats_enable_disk_poll():
            dsk_txt = _rx_tx_text(self.vm.disk_read_rate(),
                                  self.vm.disk_write_rate(), "KB/s")

        if self.config.get_stats_enable_net_poll():
            net_txt = _rx_tx_text(self.vm.network_rx_rate(),
                                  self.vm.network_tx_rate(), "KB/s")

        self.window.get_widget("overview-cpu-usage-text").set_text(cpu_txt)
        self.window.get_widget("overview-memory-usage-text").set_text(mem_txt)
        self.window.get_widget("overview-network-traffic-text").set_markup(net_txt)
        self.window.get_widget("overview-disk-usage-text").set_markup(dsk_txt)

        self.cpu_usage_graph.set_property("data_array",
                                          self.vm.cpu_time_vector())
        self.memory_usage_graph.set_property("data_array",
                                             self.vm.current_memory_vector())
        self.disk_io_graph.set_property("data_array",
                                        self.vm.disk_io_vector())
        self.network_traffic_graph.set_property("data_array",
                                                self.vm.network_traffic_vector())

    def refresh_config_cpu(self):
        self.window.get_widget("state-host-cpus").set_text("%d" % self.vm.get_connection().host_active_processor_count())
        status = self.vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
            cpu_max = self.vm.get_connection().get_max_vcpus(self.vm.get_hv_type())
            self.window.get_widget("config-vcpus").get_adjustment().upper = cpu_max
            self.window.get_widget("state-vm-maxvcpus").set_text(str(cpu_max))
        else:
            self.window.get_widget("config-vcpus").get_adjustment().upper = self.vm.vcpu_max_count()
            self.window.get_widget("state-vm-maxvcpus").set_text("%d" % (self.vm.vcpu_max_count()))

        if not(self.window.get_widget("config-apply").get_property("sensitive")):
            self.window.get_widget("config-vcpus").get_adjustment().value = self.vm.vcpu_count()
        self.window.get_widget("state-vm-vcpus").set_text("%d" % (self.vm.vcpu_count()))
        self.window.get_widget("config-vcpupin").set_text("%s" % self.vm.vcpu_pinning() )

    def refresh_config_memory(self):
        self.window.get_widget("state-host-memory").set_text("%d MB" % (int(round(self.vm.get_connection().host_memory_size()/1024))))

        curmem = self.window.get_widget("config-memory").get_adjustment()
        maxmem = self.window.get_widget("config-maxmem").get_adjustment()

        if self.window.get_widget("config-apply").get_property("sensitive"):
            memval = self.config_get_memory()
            maxval = self.config_get_maxmem()
            if maxval < memval:
                maxmem.value = memval
            maxmem.lower = memval
        else:
            curmem.value = int(round(self.vm.get_memory()/1024.0))
            maxmem.value = int(round(self.vm.maximum_memory()/1024.0))

        if not self.window.get_widget("config-memory").get_property("sensitive"):
            maxmem.lower = curmem.value
        self.window.get_widget("state-vm-memory").set_text("%d MB" % int(round(self.vm.get_memory()/1024.0)))

    def refresh_disk_page(self):
        diskinfo = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not diskinfo:
            return

        self.window.get_widget("disk-source-type").set_text(diskinfo[5])
        self.window.get_widget("disk-source-path").set_text(diskinfo[3])
        self.window.get_widget("disk-target-type").set_text(diskinfo[4])
        self.window.get_widget("disk-target-device").set_text(diskinfo[2])
        if diskinfo[6] == True:
            perms = "Readonly"
        else:
            perms = "Read/Write"
        if diskinfo[7] == True:
            perms += ", Shareable"
        self.window.get_widget("disk-permissions").set_text(perms)
        bus = diskinfo[8] or _("Unknown")
        self.window.get_widget("disk-bus").set_text(bus)

        button = self.window.get_widget("config-cdrom-connect")
        if diskinfo[4] == "cdrom":
            if diskinfo[3] == "-":
                # source device not connected
                button.set_label(gtk.STOCK_CONNECT)
            else:
                button.set_label(gtk.STOCK_DISCONNECT)
            button.show()
        else:
            button.hide()

    def refresh_network_page(self):
        netinfo = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not netinfo:
            return

        self.window.get_widget("network-source-type").set_text(netinfo[5])
        if netinfo[3] is not None:
            self.window.get_widget("network-source-device").set_text(netinfo[3])
        else:
            self.window.get_widget("network-source-device").set_text("-")
        self.window.get_widget("network-mac-address").set_text(netinfo[2])

        model = netinfo[6] or _("Hypervisor Default")
        self.window.get_widget("network-source-model").set_text(model)

    def refresh_input_page(self):
        inputinfo = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not inputinfo:
            return

        if inputinfo[2] == "tablet:usb":
            self.window.get_widget("input-dev-type").set_text(_("EvTouch USB Graphics Tablet"))
        elif inputinfo[2] == "mouse:usb":
            self.window.get_widget("input-dev-type").set_text(_("Generic USB Mouse"))
        elif inputinfo[2] == "mouse:xen":
            self.window.get_widget("input-dev-type").set_text(_("Xen Mouse"))
        elif inputinfo[2] == "mouse:ps2":
            self.window.get_widget("input-dev-type").set_text(_("PS/2 Mouse"))
        else:
            self.window.get_widget("input-dev-type").set_text(inputinfo[4] + \
                                                              " " \
                                                              + inputinfo[3])

        if inputinfo[4] == "tablet":
            self.window.get_widget("input-dev-mode").set_text(_("Absolute Movement"))
        else:
            self.window.get_widget("input-dev-mode").set_text(_("Relative Movement"))

        # Can't remove primary Xen or PS/2 mice
        if inputinfo[4] == "mouse" and inputinfo[3] in ("xen", "ps2"):
            self.window.get_widget("config-remove").set_sensitive(False)
        else:
            self.window.get_widget("config-remove").set_sensitive(True)

    def refresh_graphics_page(self):
        gfxinfo = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not gfxinfo:
            return

        if gfxinfo[2] == "vnc":
            self.window.get_widget("graphics-type").set_text(_("VNC server"))
        elif gfxinfo[2] == "sdl":
            self.window.get_widget("graphics-type").set_text(_("Local SDL window"))
        else:
            self.window.get_widget("graphics-type").set_text(gfxinfo[2])

        if gfxinfo[2] == "vnc":
            if gfxinfo[3] == None:
                self.window.get_widget("graphics-address").set_text("127.0.0.1")
            else:
                self.window.get_widget("graphics-address").set_text(gfxinfo[3])
            if int(gfxinfo[4]) == -1:
                self.window.get_widget("graphics-port").set_text(_("Automatically allocated"))
            else:
                self.window.get_widget("graphics-port").set_text(gfxinfo[4])
            self.window.get_widget("graphics-password").set_text("-")
            self.window.get_widget("graphics-keymap").set_text(gfxinfo[5] or "en-us")
        else:
            self.window.get_widget("graphics-address").set_text(_("N/A"))
            self.window.get_widget("graphics-port").set_text(_("N/A"))
            self.window.get_widget("graphics-password").set_text("N/A")
            self.window.get_widget("graphics-keymap").set_text("N/A")

    def refresh_sound_page(self):
        soundinfo = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not soundinfo:
            return

        self.window.get_widget("sound-model").set_text(soundinfo[2])

    def refresh_char_page(self):
        charinfo = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not charinfo:
            return

        typelabel = "<b>%s Device %s</b>" % (charinfo[0].capitalize(),
                                             charinfo[6] and \
                                             _("(Primary Console)") or "")
        self.window.get_widget("char-type").set_markup(typelabel)
        self.window.get_widget("char-dev-type").set_text(charinfo[4] or "-")
        self.window.get_widget("char-target-port").set_text(charinfo[3] or "")
        self.window.get_widget("char-source-path").set_text(charinfo[5] or "-")

    def refresh_hostdev_page(self):
        hostdevinfo = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not hostdevinfo:
            return

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

        devinfo = hostdevinfo[1]
        vendor_id = -1
        product_id = -1
        device = 0
        bus = 0
        domain = 0
        func = 0
        slot = 0

        if devinfo.get("vendor") and devinfo.get("product"):
            vendor_id = devinfo["vendor"].get("id") or -1
            product_id = devinfo["product"].get("id") or -1

        elif devinfo.get("address"):
            device = intify(devinfo["address"].get("device"), True)
            bus = intify(devinfo["address"].get("bus"), True)
            domain = intify(devinfo["address"].get("domain"), True)
            func = intify(devinfo["address"].get("function"), True)
            slot = intify(devinfo["address"].get("slot"), True)

        typ = devinfo.get("type")
        # For USB we want a device, not a bus
        if typ == 'usb':
            typ = 'usb_device'
        dev_pretty_name = None
        devs = self.vm.get_connection().get_devices( typ, None )

        # Get device pretty name
        for dev in devs:
            # Try to get info from {product|vendor}_id
            if (attrVal(dev, "product_id") == product_id and
                attrVal(dev, "vendor_id") == vendor_id):
                dev_pretty_name = dev.pretty_name()
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
                    dev_pretty_name = dev.pretty_name()
                    break

        devlabel = "<b>Physical %s Device</b>" % hostdevinfo[4].upper()

        self.window.get_widget("hostdev-title").set_markup(devlabel)
        self.window.get_widget("hostdev-source").set_text(dev_pretty_name or
                                                          "-")

    def refresh_video_page(self):
        vidinfo = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not vidinfo:
            return

        ignore, ignore, model, ram, heads = vidinfo
        try:
            ramlabel = ram and "%d MB" % (int(ram) / 1024) or "-"
        except:
            ramlabel = "-"

        self.window.get_widget("video-model").set_text(model)
        self.window.get_widget("video-ram").set_text(ramlabel)
        self.window.get_widget("video-heads").set_text(heads and heads or "-")

    def refresh_boot_page(self):
        # Refresh autostart
        try:
            autoval = self.vm.get_autostart()
            self.window.get_widget("config-autostart").set_active(autoval)
            self.window.get_widget("config-autostart").set_sensitive(True)
        except libvirt.libvirtError:
            # Autostart isn't supported
            self.window.get_widget("config-autostart").set_active(False)
            self.window.get_widget("config-autostart").set_sensitive(False)

        # Refresh Boot Device list and correct selection
        boot_combo = self.window.get_widget("config-boot-device")
        if not self.vm.is_hvm():
            # Boot dev selection not supported for PV guest
            boot_combo.set_sensitive(False)
            boot_combo.set_active(-1)
            return

        self.repopulate_boot_list()
        bootdev = self.vm.get_boot_device()
        boot_combo = self.window.get_widget("config-boot-device")
        boot_model = boot_combo.get_model()
        for i in range(0, len(boot_model)):
            if bootdev == boot_model[i][2]:
                boot_combo.set_active(i)
                break

        if boot_model[0][2] == None:
            # If no boot devices, select the 'No Device' entry
            boot_combo.set_active(0)


    ############################
    # Hardware list population #
    ############################

    def populate_hw_list(self):
        hw_list_model = self.window.get_widget("hw-list").get_model()
        hw_list_model.clear()

        def add_hw_list_option(title, page_id, data, icon_name):
            hw_list_model.append([title, icon_name,
                                  gtk.ICON_SIZE_LARGE_TOOLBAR,
                                  page_id, data])

        add_hw_list_option("Overview", HW_LIST_TYPE_GENERAL, [], "computer")
        add_hw_list_option("Performance", HW_LIST_TYPE_STATS, [],
                           "utilities-system-monitor")
        add_hw_list_option("Processor", HW_LIST_TYPE_CPU, [], "device_cpu")
        add_hw_list_option("Memory", HW_LIST_TYPE_MEMORY, [], "device_mem")
        add_hw_list_option("Boot Options", HW_LIST_TYPE_BOOT, [], "system-run")

        self.repopulate_hw_list()

    def repopulate_hw_list(self):
        hw_list = self.window.get_widget("hw-list")
        hw_list_model = hw_list.get_model()

        currentDisks = {}
        currentNICs = {}
        currentInputs = {}
        currentGraphics = {}
        currentSounds = {}
        currentChars = {}
        currentHostdevs = {}
        currentVids = {}

        def add_hw_list_option(idx, name, page_id, info, icon_name):
            hw_list_model.insert(idx, [name, icon_name,
                                       gtk.ICON_SIZE_LARGE_TOOLBAR,
                                       page_id, info])

        def update_hwlist(hwtype, info, name, icon_name):
            """
            See if passed hw is already in list, and if so, update info.
            If not in list, add it!
            """
            insertAt = 0
            for row in hw_list_model:
                if (row[HW_LIST_COL_TYPE] == hwtype and
                    row[HW_LIST_COL_DEVICE][2] == info[2]):
                    # Update existing HW info
                    row[HW_LIST_COL_DEVICE] = info
                    return

                if row[HW_LIST_COL_TYPE] <= hwtype:
                    insertAt += 1

            # Add the new HW row
            add_hw_list_option(insertAt, name, hwtype, info, icon_name)

        # Populate list of disks
        for diskinfo in self.vm.get_disk_devices():
            currentDisks[diskinfo[2]] = 1
            icon = "drive-harddisk"
            if diskinfo[4] == "cdrom":
                icon = "media-optical"
            elif diskinfo[4] == "floppy":
                icon = "media-floppy"

            update_hwlist(HW_LIST_TYPE_DISK, diskinfo, "Disk %s" % diskinfo[2],
                          icon)

        # Populate list of NICs
        for netinfo in self.vm.get_network_devices():
            currentNICs[netinfo[2]] = 1
            update_hwlist(HW_LIST_TYPE_NIC, netinfo,
                          "NIC %s" % netinfo[2][-9:], "network-idle")

        # Populate list of input devices
        for inputinfo in self.vm.get_input_devices():
            currentInputs[inputinfo[2]] = 1
            icon = "input-mouse"
            if inputinfo[4] == "tablet":
                label = _("Tablet")
                icon = "input-tablet"
            elif inputinfo[4] == "mouse":
                label = _("Mouse")
            else:
                label = _("Input")

            update_hwlist(HW_LIST_TYPE_INPUT, inputinfo, label, icon)

        # Populate list of graphics devices
        for gfxinfo in self.vm.get_graphics_devices():
            currentGraphics[gfxinfo[2]] = 1
            update_hwlist(HW_LIST_TYPE_GRAPHICS, gfxinfo,
                          _("Display %s") % gfxinfo[1],
                          "video-display")

        # Populate list of sound devices
        for soundinfo in self.vm.get_sound_devices():
            currentSounds[soundinfo[2]] = 1
            update_hwlist(HW_LIST_TYPE_SOUND, soundinfo,
                          _("Sound: %s" % soundinfo[2]), "audio-card")

        # Populate list of char devices
        for charinfo in self.vm.get_char_devices():
            currentChars[charinfo[2]] = 1
            label = charinfo[0].capitalize()
            if charinfo[0] != "console":
                label += " %s" % charinfo[3] # Don't show port for console

            update_hwlist(HW_LIST_TYPE_CHAR, charinfo, label,
                          "device_serial")

        # Populate host devices
        for hostdevinfo in self.vm.get_hostdev_devices():
            currentHostdevs[hostdevinfo[2]] = 1
            if hostdevinfo[4] == "usb":
                icon = "device_usb"
            else:
                icon = "device_pci"
            update_hwlist(HW_LIST_TYPE_HOSTDEV, hostdevinfo, hostdevinfo[2],
                          icon)

        # Populate video devices
        for vidinfo in self.vm.get_video_devices():
            currentVids[vidinfo[2]] = 1
            update_hwlist(HW_LIST_TYPE_VIDEO, vidinfo, _("Video"),
                          "video-display")

        # Now remove any no longer current devs
        devs = range(len(hw_list_model))
        devs.reverse()
        for i in devs:
            _iter = hw_list_model.iter_nth_child(None, i)
            row = hw_list_model[i]
            removeIt = False

            mapping = {
                HW_LIST_TYPE_DISK       : currentDisks,
                HW_LIST_TYPE_NIC        : currentNICs,
                HW_LIST_TYPE_INPUT      : currentInputs,
                HW_LIST_TYPE_GRAPHICS   : currentGraphics,
                HW_LIST_TYPE_SOUND      : currentSounds,
                HW_LIST_TYPE_CHAR       : currentChars,
                HW_LIST_TYPE_HOSTDEV    : currentHostdevs,
                HW_LIST_TYPE_VIDEO      : currentVids,
            }


            hwtype   = row[HW_LIST_COL_TYPE]
            if (mapping.has_key(hwtype) and not
                mapping[hwtype].has_key(row[HW_LIST_COL_DEVICE][2])):
                removeIt = True

            if removeIt:
                # Re-select the first row, if we're viewing the device
                # we're about to remove
                (selModel, selIter) = hw_list.get_selection().get_selected()
                selType = selModel.get_value(selIter, HW_LIST_COL_TYPE)
                selInfo = selModel.get_value(selIter, HW_LIST_COL_DEVICE)
                if (selType == row[HW_LIST_COL_TYPE] and
                    selInfo[2] == row[HW_LIST_COL_DEVICE][2]):
                    hw_list.get_selection().select_iter(selModel.iter_nth_child(None, 0))

                # Now actually remove it
                hw_list_model.remove(_iter)

    def repopulate_boot_list(self):
        hw_list_model = self.window.get_widget("hw-list").get_model()
        boot_combo = self.window.get_widget("config-boot-device")
        boot_model = boot_combo.get_model()
        boot_model.clear()
        found_dev = {}
        for row in hw_list_model:
            hwtype = row[HW_LIST_COL_TYPE]

            if hwtype == HW_LIST_TYPE_DISK:
                diskinfo = row[HW_LIST_COL_DEVICE]

                if diskinfo[4] == virtinst.VirtualDisk.DEVICE_DISK and not \
                   found_dev.get(virtinst.VirtualDisk.DEVICE_DISK, False):
                    boot_model.append(["Hard Disk", "drive-harddisk", "hd"])
                    found_dev[virtinst.VirtualDisk.DEVICE_DISK] = True
                elif diskinfo[4] == virtinst.VirtualDisk.DEVICE_CDROM and not \
                     found_dev.get(virtinst.VirtualDisk.DEVICE_CDROM, False):
                    boot_model.append(["CDROM", "media-optical", "cdrom"])
                    found_dev[virtinst.VirtualDisk.DEVICE_CDROM] = True
                elif diskinfo[4] == virtinst.VirtualDisk.DEVICE_FLOPPY and not \
                     found_dev.get(virtinst.VirtualDisk.DEVICE_FLOPPY, False):
                    boot_model.append(["Floppy", "media-floppy", "fd"])
                    found_dev[virtinst.VirtualDisk.DEVICE_FLOPPY] = True

            elif (hwtype == HW_LIST_TYPE_NIC and not
                  found_dev.get(HW_LIST_TYPE_NIC, False)):
                boot_model.append(["Network (PXE)", "network-idle", "network"])
                found_dev[HW_LIST_TYPE_NIC] = True

        if len(boot_model) <= 0:
            boot_model.append([_("No Boot Device"), None, None])

        boot_combo.set_model(boot_model)

gobject.type_register(vmmDetails)

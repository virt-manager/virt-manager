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
import sparkline
import logging
import traceback
import sys
import dbus
import gtkvnc
import os
import socket
import cairo

from virtManager.error import vmmErrorDialog
from virtManager.addhardware import vmmAddHardware
from virtManager.choosecd import vmmChooseCD
from virtManager.serialcon import vmmSerialConsole
from virtManager import util as util

import virtinst

# Columns in hw list model
HW_LIST_COL_LABEL = 0
HW_LIST_COL_STOCK_ID = 1
HW_LIST_COL_STOCK_SIZE = 2
HW_LIST_COL_PIXBUF = 3
HW_LIST_COL_TYPE = 4
HW_LIST_COL_DEVICE = 5

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

# Console pages
PAGE_UNAVAILABLE = 0
PAGE_SCREENSHOT = 1
PAGE_AUTHENTICATE = 2
PAGE_VNCVIEWER = 3

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
        }


    def __init__(self, config, vm, engine):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-details.glade", "vmm-details", domain="virt-manager")
        self.config = config
        self.vm = vm

        topwin = self.window.get_widget("vmm-details")
        self.err = vmmErrorDialog(topwin,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))
        self.title = vm.get_name() + " " + topwin.get_title()
        topwin.set_title(self.title)

        self.engine = engine
        self.dynamic_tabs = []
        self.ignorePause = False

        # Don't allowing changing network/disks for Dom0
        if self.vm.is_management_domain():
            self.window.get_widget("add-hardware-button").set_sensitive(False)
        else:
            self.window.get_widget("add-hardware-button").set_sensitive(True)

        self.window.get_widget("control-shutdown").set_icon_widget(gtk.Image())
        self.window.get_widget("control-shutdown").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_shutdown.png")

        menu = gtk.Menu()
        self.window.get_widget("control-shutdown").set_menu(menu)

        rebootimg = gtk.Image()
        rebootimg.set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/icon_shutdown.png", 18, 18))
        shutdownimg = gtk.Image()
        shutdownimg.set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/icon_shutdown.png", 18, 18))
        destroyimg = gtk.Image()
        destroyimg.set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/icon_shutdown.png", 18, 18))

        reboot = gtk.ImageMenuItem(_("_Reboot"))
        reboot.set_image(rebootimg)
        reboot.show()
        reboot.connect("activate", self.control_vm_reboot)
        menu.add(reboot)

        shutdown = gtk.ImageMenuItem(_("_Shut Down"))
        shutdown.set_image(shutdownimg)
        shutdown.show()
        shutdown.connect("activate", self.control_vm_shutdown)
        menu.add(shutdown)

        destroy = gtk.ImageMenuItem(_("_Force Off"))
        destroy.set_image(destroyimg)
        destroy.show()
        destroy.connect("activate", self.control_vm_destroy)
        menu.add(destroy)

        smenu = gtk.Menu()
        smenu.connect("show", self.populate_serial_menu)
        self.window.get_widget("details-menu-view-serial-list").set_submenu(smenu)

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

        self.window.get_widget("hw-panel").set_show_tabs(False)

        self.addhw = None
        self.choose_cd = None

        # Security info tooltips
        util.tooltip_wrapper(self.window.get_widget("security-static-info"),
            _("Static SELinux security type tells libvirt to always start the guest process with the specified label. The administrator is responsible for making sure the images are labeled corectly on disk."))
        util.tooltip_wrapper(self.window.get_widget("security-dynamic-info"),
            _("The dynamic SELinux security type tells libvirt to automatically pick a unique label for the guest process and guest image, ensuring total isolation of the guest. (Default)"))

        self.cpu_usage_graph = sparkline.Sparkline()
        self.cpu_usage_graph.set_property("reversed", True)
        self.window.get_widget("graph-table").attach(self.cpu_usage_graph, 1, 2, 0, 1)

        self.memory_usage_graph = sparkline.Sparkline()
        self.memory_usage_graph.set_property("reversed", True)
        self.window.get_widget("graph-table").attach(self.memory_usage_graph, 1, 2, 1, 2)

        self.disk_io_graph = sparkline.Sparkline()
        self.disk_io_graph.set_property("reversed", True)
        self.disk_io_graph.set_property("filled", False)
        self.disk_io_graph.set_property("num_sets", 2)
        self.disk_io_graph.set_property("rgb", map(lambda x: x/255.0,
                                        [0x82, 0x00, 0x3B, 0x29, 0x5C, 0x45]))
        self.window.get_widget("graph-table").attach(self.disk_io_graph, 1, 2, 2, 3)

        self.network_traffic_graph = sparkline.Sparkline()
        self.network_traffic_graph.set_property("reversed", True)
        self.network_traffic_graph.set_property("filled", False)
        self.network_traffic_graph.set_property("num_sets", 2)
        self.network_traffic_graph.set_property("rgb", map(lambda x: x/255.0,
                                                [0x82, 0x00, 0x3B, 0x29, 0x5C, 0x45]))
        self.window.get_widget("graph-table").attach(self.network_traffic_graph, 1, 2, 3, 4)

        self.accel_groups = gtk.accel_groups_from_object(topwin)
        self.gtk_settings_accel = None

        self.vncViewer = gtkvnc.Display()
        self.window.get_widget("console-vnc-viewport").add(self.vncViewer)
        self.vncViewer.realize()
        self.vncTunnel = None
        if self.config.get_console_keygrab() == 2:
            self.vncViewer.set_keyboard_grab(True)
        else:
            self.vncViewer.set_keyboard_grab(False)
        self.vncViewer.set_pointer_grab(True)

        self.scale_type = self.vm.get_console_scaling()
        self.vm.on_console_scaling_changed(self.refresh_scaling)
        self.refresh_scaling()

        self.vncViewer.connect("vnc-pointer-grab", self.notify_grabbed)
        self.vncViewer.connect("vnc-pointer-ungrab", self.notify_ungrabbed)

        self.vncViewer.show()
        self.vncViewerRetriesScheduled = 0
        self.vncViewerRetryDelay = 125
        self.vncViewer.connect("size-request", self._force_resize)
        self.vncViewer.connect("vnc-auth-credential", self._vnc_auth_credential)
        self.vncViewer.connect("vnc-initialized", self._vnc_initialized)
        self.vncViewer.connect("vnc-disconnected", self._vnc_disconnected)
        self.vncViewer.connect("vnc-keyboard-grab", self._disable_modifiers)
        self.vncViewer.connect("vnc-keyboard-ungrab", self._enable_modifiers)
        self.vnc_connected = False

        self.notifyID = None
        self.notifyInterface = None
        try:
            bus = dbus.SessionBus()
            notifyObject = bus.get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
            self.notifyInterface = dbus.Interface(notifyObject, "org.freedesktop.Notifications")
            self.notifyInterface.connect_to_signal("ActionInvoked", self.notify_action)
            self.notifyInterface.connect_to_signal("NotificationClosed", self.notify_closed)
        except Exception, e:
            logging.error("Cannot initialize notification system" + str(e))

        self.window.get_widget("console-pages").set_show_tabs(False)
        self.window.get_widget("details-menu-view-toolbar").set_active(self.config.get_details_show_toolbar())

        self.window.signal_autoconnect({
            "on_close_details_clicked": self.close,
            "on_details_menu_close_activate": self.close,
            "on_vmm_details_delete_event": self.close,
            "on_details_menu_quit_activate": self.exit_app,

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
            "on_details_menu_screenshot_activate": self.control_vm_screenshot,
            "on_details_menu_graphics_activate": self.control_vm_console,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,
            "on_details_menu_view_manager_activate": self.view_manager,

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

            "on_details_menu_view_fullscreen_activate": self.toggle_fullscreen,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,
            "on_details_menu_view_scale_always_toggled": self.set_scale_type,
            "on_details_menu_view_scale_fullscreen_toggled": self.set_scale_type,
            "on_details_menu_view_scale_never_toggled": self.set_scale_type,

            "on_details_menu_send_cad_activate": self.send_key,
            "on_details_menu_send_cab_activate": self.send_key,
            "on_details_menu_send_caf1_activate": self.send_key,
            "on_details_menu_send_caf2_activate": self.send_key,
            "on_details_menu_send_caf3_activate": self.send_key,
            "on_details_menu_send_caf4_activate": self.send_key,
            "on_details_menu_send_caf5_activate": self.send_key,
            "on_details_menu_send_caf6_activate": self.send_key,
            "on_details_menu_send_caf7_activate": self.send_key,
            "on_details_menu_send_caf8_activate": self.send_key,
            "on_details_menu_send_caf9_activate": self.send_key,
            "on_details_menu_send_caf10_activate": self.send_key,
            "on_details_menu_send_caf11_activate": self.send_key,
            "on_details_menu_send_caf12_activate": self.send_key,
            "on_details_menu_send_printscreen_activate": self.send_key,

            "on_console_auth_password_activate": self.auth_login,
            "on_console_auth_login_clicked": self.auth_login,
            "on_security_label_changed": self.security_label_changed,
            "on_security_type_changed": self.security_type_changed,
            "on_security_model_changed": self.security_model_changed,
            })

        self.vm.connect("status-changed", self.update_widget_states)
        self.vm.connect("resources-sampled", self.refresh_resources)
        self.vm.connect("config-changed", self.refresh_vm_info)
        self.window.get_widget("hw-list").get_selection().connect("changed", self.hw_selected)

        self.update_widget_states(self.vm, self.vm.status())

        self.pixbuf_processor = gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")
        self.pixbuf_memory = gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")
        self.prepare_hw_list()
        self.hw_selected(page=0)
        self.refresh_vm_info()


    # Black magic todo with scrolled windows. Basically the behaviour we want
    # is that if it possible to resize the window to show entire guest desktop
    # then we should do that and never show scrollbars. If the local screen is
    # too small then we can turn on scrolling. You would think the 'Automatic'
    # policy would work, but even if viewport is identical sized to the VNC
    # widget it still seems to show scrollbars. So we do evil stuff here
    def _force_resize(self, src, size):
        w,h = src.get_size_request()
        if w == -1 or h == -1:
            return

        topw,toph = self.window.get_widget("vmm-details").size_request()

        padx = topw-w
        pady = toph-h
        rootw = src.get_screen().get_width()
        rooth = src.get_screen().get_height()

        maxw = rootw - 100 - padx
        maxh = rooth - 100 - pady

        self.window.get_widget("console-vnc-viewport").set_size_request(w, h)
        self.window.get_widget("console-screenshot").set_size_request(w, h)
        self.window.get_widget("console-screenshot-viewport").set_size_request(w, h)
        self.window.get_widget("console-vnc-scroll").set_size_request(w, h)
        if w > maxw or h > maxh:
            self.window.get_widget("console-vnc-scroll").set_policy(gtk.POLICY_ALWAYS, gtk.POLICY_ALWAYS)
            self.window.get_widget("console-screenshot-scroll").set_policy(gtk.POLICY_ALWAYS, gtk.POLICY_ALWAYS)
        else:
            self.window.get_widget("console-vnc-scroll").set_policy(gtk.POLICY_NEVER, gtk.POLICY_NEVER)
            self.window.get_widget("console-screenshot-scroll").set_policy(gtk.POLICY_NEVER, gtk.POLICY_NEVER)

    def _disable_modifiers(self, ignore=None):
        topwin = self.window.get_widget("vmm-details")
        for g in self.accel_groups:
            topwin.remove_accel_group(g)
        settings = gtk.settings_get_default()
        self.gtk_settings_accel = settings.get_property('gtk-menu-bar-accel')
        settings.set_property('gtk-menu-bar-accel', None)

    def _enable_modifiers(self, ignore=None):
        topwin = self.window.get_widget("vmm-details")
        if self.gtk_settings_accel is None:
            return
        settings = gtk.settings_get_default()
        settings.set_property('gtk-menu-bar-accel', self.gtk_settings_accel)
        self.gtk_settings_accel = None
        for g in self.accel_groups:
            topwin.add_accel_group(g)

    def notify_grabbed(self, src):
        topwin = self.window.get_widget("vmm-details")
        topwin.set_title(_("Press Ctrl+Alt to release pointer.") + " " + self.title)

        if self.config.show_console_grab_notify() and self.notifyInterface:
            try:
                (x, y) = topwin.window.get_origin()
                self.notifyID = self.notifyInterface.Notify(topwin.get_title(),
                                                            0,
                                                            '',
                                                            _("Pointer grabbed"),
                                                            _("The mouse pointer has been restricted to the virtual console window. To release the pointer, press the key pair: Ctrl+Alt"),
                                                            ["dismiss", _("Do not show this notification in the future.")],
                                                            {"desktop-entry": "virt-manager",
                                                             "x": x+200, "y": y},
                                                            8 * 1000)
            except Exception, e:
                logging.error("Cannot popup notification " + str(e))

    def notify_ungrabbed(self, src):
        topwin = self.window.get_widget("vmm-details")
        topwin.set_title(self.title)

    def notify_closed(self, i, reason=None):
        if self.notifyID is not None and self.notifyID == i:
            self.notifyID = None

    def notify_action(self, i, action):
        if self.notifyID is None or self.notifyID != i:
            return

        if action == "dismiss":
            self.config.set_console_grab_notify(False)

    def keygrab_changed(self, src, ignore1=None,ignore2=None,ignore3=None):
        if self.config.get_console_keygrab() == 2:
            self.vncViewer.set_keyboard_grab(True)
        else:
            self.vncViewer.set_keyboard_grab(False)

    def refresh_scaling(self,ignore1=None, ignore2=None, ignore3=None,
                        ignore4=None):
        self.scale_type = self.vm.get_console_scaling()
        self.window.get_widget("details-menu-view-scale-always").set_active(self.scale_type == self.config.CONSOLE_SCALE_ALWAYS)
        self.window.get_widget("details-menu-view-scale-never").set_active(self.scale_type == self.config.CONSOLE_SCALE_NEVER)
        self.window.get_widget("details-menu-view-scale-fullscreen").set_active(self.scale_type == self.config.CONSOLE_SCALE_FULLSCREEN)

        self.update_scaling()

    def set_scale_type(self, src):
        if not src.get_active():
            return

        if src == self.window.get_widget("details-menu-view-scale-always"):
            self.scale_type = self.config.CONSOLE_SCALE_ALWAYS
        elif src == self.window.get_widget("details-menu-view-scale-fullscreen"):
            self.scale_type = self.config.CONSOLE_SCALE_FULLSCREEN
        elif src == self.window.get_widget("details-menu-view-scale-never"):
            self.scale_type = self.config.CONSOLE_SCALE_NEVER

        self.vm.set_console_scaling(self.scale_type)
        self.update_scaling()

    def update_scaling(self):
        curscale = self.vncViewer.get_scaling()
        fs = self.window.get_widget("control-fullscreen").get_active()

        if (self.scale_type == self.config.CONSOLE_SCALE_NEVER
            and curscale == True):
            self.vncViewer.set_scaling(False)
        elif (self.scale_type == self.config.CONSOLE_SCALE_ALWAYS
              and curscale == False):
            self.vncViewer.set_scaling(True)
        elif (self.scale_type == self.config.CONSOLE_SCALE_FULLSCREEN
              and curscale != fs):
            self.vncViewer.set_scaling(fs)

    def control_fullscreen(self, src):
        menu = self.window.get_widget("details-menu-view-fullscreen")
        if src.get_active() != menu.get_active():
            menu.set_active(src.get_active())

    def toggle_fullscreen(self, src):
        self.window.get_widget("control-fullscreen").set_active(src.get_active())
        if src.get_active():

            # if scaling is enabled make sure we fit onto the root window
            if self.vncViewer.get_scaling():
                ignore, h = self.window.get_widget("menubar3").size_request()
                rootw = src.get_screen().get_width()
                rooth = src.get_screen().get_height() - h
                self.vncViewer.set_size_request(rootw, rooth)
            else:
                self.vncViewer.set_size_request(-1, -1)

            self.window.get_widget("vmm-details").fullscreen()
            if self.config.get_console_keygrab() == 1:
                gtk.gdk.keyboard_grab(self.vncViewer.window, False, 0L)
                self._disable_modifiers()

            tabs = self.window.get_widget("details-pages")
            tabs.set_show_tabs(False)
            tabs.set_border_width(0)
            self.window.get_widget("details-toolbar").hide()
        else:
            if self.config.get_console_keygrab() == 1:
                self._enable_modifiers()
                gtk.gdk.keyboard_ungrab(0L)
            self.window.get_widget("vmm-details").unfullscreen()

            tabs = self.window.get_widget("details-pages")
            tabs.set_show_tabs(True)
            tabs.set_border_width(6)
            if self.window.get_widget("details-menu-view-toolbar").get_active():
                self.window.get_widget("details-toolbar").show()
        self.update_scaling()

    def auth_login(self, ignore):
        self.set_credentials()
        self.activate_viewer_page()

    def toggle_toolbar(self, src):
        active = src.get_active()
        self.config.set_details_show_toolbar(active)
        if active and not \
           self.window.get_widget("details-menu-view-fullscreen").get_active():
            self.window.get_widget("details-toolbar").show()
        else:
            self.window.get_widget("details-toolbar").hide()

    def populate_serial_menu(self, src):
        for ent in src:
            src.remove(ent)

        devs = self.vm.get_serial_devs()
        if len(devs) == 0:
            item = gtk.CheckMenuItem(_("No serial devices found"))
            item.set_sensitive(False)
            src.add(item)

        usable_types = [ "pty" ]
        for dev in devs:
            sensitive = False
            msg = ""
            item = gtk.CheckMenuItem(dev[0])

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

            if sensitive and self.dynamic_tabs.count(dev[0]):
                # Tab is already open, make sure marked as such
                item.set_active(True)
            item.connect("activate", self.control_serial_tab, dev[0], dev[3])
            src.add(item)

        src.show_all()

    def show(self):
        dialog = self.window.get_widget("vmm-details")
        if self.is_visible():
            dialog.present()
            return
        dialog.show_all()
        dialog.present()

        self.engine.increment_window_counter()
        self.update_widget_states(self.vm, self.vm.status())

    def show_help(self, src):
        # From the Details window, show the help document from the Details page
        self.emit("action-show-help", "virt-manager-details-window")

    def activate_console_page(self):
        self.window.get_widget("details-pages").set_current_page(PAGE_CONSOLE)

    def activate_performance_page(self):
        self.window.get_widget("details-pages").set_current_page(PAGE_DETAILS)
        self.window.get_widget("hw-panel").set_current_page(HW_LIST_TYPE_STATS)

    def activate_config_page(self):
        self.window.get_widget("details-pages").set_current_page(PAGE_DETAILS)

    def close(self,ignore1=None,ignore2=None):
        fs = self.window.get_widget("details-menu-view-fullscreen")
        if fs.get_active():
            fs.set_active(False)

        if not self.is_visible():
            return

        self.window.get_widget("vmm-details").hide()
        if self.vncViewer.flags() & gtk.VISIBLE:
            try:
                self.vncViewer.close()
            except:
                logging.error("Failure when disconnecting from VNC server")
        self.engine.decrement_window_counter()
        return 1

    def exit_app(self, src):
        self.emit("action-exit-app")

    def is_visible(self):
        if self.window.get_widget("vmm-details").flags() & gtk.VISIBLE:
            return 1
        return 0

    def view_manager(self, src):
        self.emit("action-view-manager")

    def send_key(self, src):
        keys = None
        if src.get_name() == "details-menu-send-cad":
            keys = ["Control_L", "Alt_L", "Delete"]
        elif src.get_name() == "details-menu-send-cab":
            keys = ["Control_L", "Alt_L", "BackSpace"]
        elif src.get_name() == "details-menu-send-caf1":
            keys = ["Control_L", "Alt_L", "F1"]
        elif src.get_name() == "details-menu-send-caf2":
            keys = ["Control_L", "Alt_L", "F2"]
        elif src.get_name() == "details-menu-send-caf3":
            keys = ["Control_L", "Alt_L", "F3"]
        elif src.get_name() == "details-menu-send-caf4":
            keys = ["Control_L", "Alt_L", "F4"]
        elif src.get_name() == "details-menu-send-caf5":
            keys = ["Control_L", "Alt_L", "F5"]
        elif src.get_name() == "details-menu-send-caf6":
            keys = ["Control_L", "Alt_L", "F6"]
        elif src.get_name() == "details-menu-send-caf7":
            keys = ["Control_L", "Alt_L", "F7"]
        elif src.get_name() == "details-menu-send-caf8":
            keys = ["Control_L", "Alt_L", "F8"]
        elif src.get_name() == "details-menu-send-caf9":
            keys = ["Control_L", "Alt_L", "F9"]
        elif src.get_name() == "details-menu-send-caf10":
            keys = ["Control_L", "Alt_L", "F10"]
        elif src.get_name() == "details-menu-send-caf11":
            keys = ["Control_L", "Alt_L", "F11"]
        elif src.get_name() == "details-menu-send-caf12":
            keys = ["Control_L", "Alt_L", "F12"]
        elif src.get_name() == "details-menu-send-printscreen":
            keys = ["Print"]

        if keys != None:
            self.vncViewer.send_keys(keys)


    def hw_selected(self, src=None, page=None, selected=True):
        pagetype = page
        if pagetype is None:
            pagetype = self.get_hw_selection(HW_LIST_COL_TYPE)

        if pagetype is None:
            pagetype = HW_LIST_TYPE_GENERAL
            self.window.get_widget("hw-list").get_selection().select_path(0)

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

    def control_vm_migrate(self, src, uri):
        self.emit("action-migrate-domain", self.vm.get_connection().get_uri(),
                  self.vm.get_uuid(), uri)

    def populate_migrate_menu(self, ignore1=None):
        menu = self.window.get_widget("details-menu-migrate_menu")
        self.engine.populate_migrate_menu(menu, self.control_vm_migrate,
                                          self.vm)

    def set_pause_widget_states(self, state):
        try:
            self.ignorePause = True
            self.window.get_widget("control-pause").set_active(state)
            self.window.get_widget("details-menu-pause").set_active(state)
        finally:
            self.ignorePause = False

    def update_widget_states(self, vm, status):
        self.toggle_toolbar(self.window.get_widget("details-menu-view-toolbar"))

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                       libvirt.VIR_DOMAIN_SHUTOFF ] or vm.is_read_only():
            self.window.get_widget("details-menu-destroy").set_sensitive(False)
        else:
            self.window.get_widget("details-menu-destroy").set_sensitive(True)

        if status in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ] and not self.vm.is_read_only():
            self.window.get_widget("control-run").set_sensitive(True)
            self.window.get_widget("details-menu-run").set_sensitive(True)
        else:
            self.window.get_widget("control-run").set_sensitive(False)
            self.window.get_widget("details-menu-run").set_sensitive(False)

        if status in [libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF,
                      libvirt.VIR_DOMAIN_CRASHED ] or vm.is_read_only():
            self.set_pause_widget_states(False)
            self.window.get_widget("control-shutdown").set_sensitive(False)
            self.window.get_widget("details-menu-shutdown").set_sensitive(False)
            self.window.get_widget("details-menu-save").set_sensitive(False)
            self.window.get_widget("control-pause").set_sensitive(False)
            self.window.get_widget("details-menu-pause").set_sensitive(False)
        else:
            self.window.get_widget("control-pause").set_sensitive(True)
            self.window.get_widget("details-menu-pause").set_sensitive(True)
            self.set_pause_widget_states(status == libvirt.VIR_DOMAIN_PAUSED)
            self.window.get_widget("control-shutdown").set_sensitive(True)
            self.window.get_widget("details-menu-shutdown").set_sensitive(True)
            self.window.get_widget("details-menu-save").set_sensitive(True)

        ro = vm.is_read_only()
        self.window.get_widget("config-vcpus").set_sensitive(not ro)
        self.window.get_widget("config-memory").set_sensitive(not ro)
        self.window.get_widget("config-maxmem").set_sensitive(not ro)
        self.window.get_widget("details-menu-migrate").set_sensitive(not ro)

        if status in [ libvirt.VIR_DOMAIN_SHUTOFF,
                       libvirt.VIR_DOMAIN_CRASHED ]:
            if self.window.get_widget("console-pages").get_current_page() != PAGE_UNAVAILABLE:
                self.vncViewer.close()
                self.window.get_widget("console-pages").set_current_page(PAGE_UNAVAILABLE)
            self.view_vm_status()
        else:
            # Disabled screenshot when paused - doesn't work when scaled
            # and you can connect to VNC when paused already, it'll simply
            # not respond to input.
            if status == libvirt.VIR_DOMAIN_PAUSED and 0 == 1:
                if self.window.get_widget("console-pages").get_current_page() == PAGE_VNCVIEWER:
                    screenshot = self.window.get_widget("console-screenshot")
                    image = self.vncViewer.get_pixbuf()
                    width = image.get_width()
                    height = image.get_height()
                    pixmap = gtk.gdk.Pixmap(screenshot.get_root_window(), width, height)
                    cr = pixmap.cairo_create()
                    cr.set_source_pixbuf(image, 0, 0)
                    cr.rectangle(0, 0, width, height)
                    cr.fill()

                    # Set 50% gray overlayed
                    cr.set_source_rgba(0, 0, 0, 0.5)
                    cr.rectangle(0, 0, width, height)
                    cr.fill()

                    # Render a big text 'paused' across it
                    cr.set_source_rgba(1, 1,1, 1)
                    cr.set_font_size(80)
                    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
                    overlay = _("paused")
                    extents = cr.text_extents(overlay)
                    x = width/2 - (extents[2]/2)
                    y = height/2 - (extents[3]/2)
                    cr.move_to(x, y)
                    cr.show_text(overlay)
                    screenshot.set_from_pixmap(pixmap, None)
                    self.activate_screenshot_page()
                elif self.window.get_widget("console-pages").get_current_page() == PAGE_SCREENSHOT:
                    pass
                else:
                    if self.window.get_widget("console-pages").get_current_page() != PAGE_UNAVAILABLE:
                        self.vncViewer.close()
                    self.activate_unavailable_page(_("Console not available while paused"))
            else:
                page = self.window.get_widget("console-pages").get_current_page()
                if page in [PAGE_UNAVAILABLE, PAGE_SCREENSHOT, PAGE_VNCVIEWER]:
                    if self.vncViewer.is_open():
                        self.activate_viewer_page()
                    else:
                        self.vncViewerRetriesScheduled = 0
                        self.vncViewerRetryDelay = 125
                        self.try_login()

        self.window.get_widget("overview-status-text").set_text(self.vm.run_status())
        self.window.get_widget("overview-status-icon").set_from_pixbuf(self.vm.run_status_icon())

    def switch_page(self, ignore1=None, ignore2=None, newpage=None):
        self.page_refresh(newpage)

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
        self.window.get_widget("overview-name").set_text(self.vm.get_name())
        self.window.get_widget("overview-uuid").set_text(self.vm.get_uuid())

        self.window.get_widget("overview-hv").set_text(self.vm.get_pretty_hv_type())
        arch = self.vm.get_arch() or _("Unknown")
        emu = self.vm.get_emulator() or _("None")
        self.window.get_widget("overview-arch").set_text(arch)
        self.window.get_widget("overview-emulator").set_text(emu)

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

        if self.config.get_stats_enable_cpu_poll():
            cpu_txt = "%d %%" % self.vm.cpu_time_percentage()

        if self.config.get_stats_enable_mem_poll():
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

    def get_hw_selection(self, field):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] == None:
            return None
        else:
            return active[0].get_value(active[1], field)

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

        devlabel = "<b>Physical %s Device</b>" % hostdevinfo[4].upper()

        self.window.get_widget("hostdev-title").set_markup(devlabel)
        self.window.get_widget("hostdev-type").set_text(hostdevinfo[4])
        self.window.get_widget("hostdev-mode").set_text(hostdevinfo[3])
        self.window.get_widget("hostdev-source").set_text(hostdevinfo[5])

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

        # TODO: if nothing selected, what to select? auto change device?



    def view_vm_status(self):
        status = self.vm.status()
        if status == libvirt.VIR_DOMAIN_SHUTOFF:
            self.activate_unavailable_page(_("Guest not running"))
        else:
            if status == libvirt.VIR_DOMAIN_CRASHED:
                self.activate_unavailable_page(_("Guest has crashed"))

    def _vnc_disconnected(self, src):
        if self.vncTunnel is not None:
            self.close_tunnel()
        self.vnc_connected = False
        logging.debug("VNC disconnected")
        if self.vm.status() in [ libvirt.VIR_DOMAIN_SHUTOFF,
                                 libvirt.VIR_DOMAIN_CRASHED ]:
            self.view_vm_status()
            return

        self.activate_unavailable_page(_("TCP/IP error: VNC connection to hypervisor host got refused or disconnected!"))

        if not self.is_visible():
            return

        self.schedule_retry()

    def _vnc_initialized(self, src):
        self.vnc_connected = True
        logging.debug("VNC initialized")
        self.activate_viewer_page()

        # Had a succesfull connect, so reset counters now
        self.vncViewerRetriesScheduled = 0
        self.vncViewerRetryDelay = 125

    def schedule_retry(self):
        self.vncViewerRetriesScheduled = self.vncViewerRetriesScheduled + 1
        if self.vncViewerRetriesScheduled >= 10:
            logging.error("Too many connection failures, not retrying again")
            return
        logging.warn("Retrying connection in %d ms", self.vncViewerRetryDelay)
        gobject.timeout_add(self.vncViewerRetryDelay, self.retry_login)
        if self.vncViewerRetryDelay < 2000:
            self.vncViewerRetryDelay = self.vncViewerRetryDelay * 2

    def retry_login(self):
        if self.vnc_connected:
            return

        if self.vm.status() in [ libvirt.VIR_DOMAIN_SHUTOFF,
                                 libvirt.VIR_DOMAIN_CRASHED ]:
            return

        gtk.gdk.threads_enter()
        try:
            logging.debug("Got timed retry")
            self.try_login()
            return
        finally:
            gtk.gdk.threads_leave()

    def open_tunnel(self, server, vncaddr, vncport, username):
        if self.vncTunnel is not None:
            return -1

        logging.debug("Spawning SSH tunnel to %s, for %s:%d" %(server, vncaddr, vncport))

        fds = socket.socketpair()
        pid = os.fork()
        if pid == 0:
            fds[0].close()
            os.close(0)
            os.close(1)
            os.dup(fds[1].fileno())
            os.dup(fds[1].fileno())
            if not server.count(":"):
                sshport = "22"
            else:
                (server, sshport) = server.split(":")
            argv = ["ssh", "ssh", "-p", sshport]
            if username:
                argv += ['-l', username]
            argv += [ server, "nc", vncaddr, str(vncport) ]
            os.execlp(*argv)
            os._exit(1)
        else:
            fds[1].close()

        logging.debug("Tunnel PID %d FD %d" % (fds[0].fileno(), pid))
        self.vncTunnel = [fds[0], pid]
        return fds[0].fileno()

    def close_tunnel(self):
        if self.vncTunnel is None:
            return

        logging.debug("Shutting down tunnel PID %d FD %d" % (self.vncTunnel[1], self.vncTunnel[0].fileno()))
        self.vncTunnel[0].close()
        os.waitpid(self.vncTunnel[1], 0)
        self.vncTunnel = None

    def try_login(self, src=None):
        if not self.vm.vm:
            # VM was removed, skip login attempt
            return

        if self.vm.get_id() < 0:
            self.activate_unavailable_page(_("Guest not running"))
            self.schedule_retry()
            return

        logging.debug("Trying console login")
        protocol, host, port, trans, username = self.vm.get_graphics_console()

        if protocol is None:
            logging.debug("No graphics configured in guest")
            self.activate_unavailable_page(_("Console not configured for guest"))
            return

        uri = str(protocol) + "://"
        if username:
            uri = uri + str(username) + '@'
        uri = uri + str(host) + ":" + str(port)

        logging.debug("Graphics console configured at " + uri)

        if protocol != "vnc":
            logging.debug("Not a VNC console, disabling")
            self.activate_unavailable_page(_("Console not supported for guest"))
            return

        if int(port) == -1:
            self.activate_unavailable_page(_("Console is not yet active for guest"))
            self.schedule_retry()
            return

        self.activate_unavailable_page(_("Connecting to console for guest"))
        logging.debug("Starting connect process for %s %s" % (host, str(port)))
        try:
            if trans is not None and trans in ("ssh", "ext"):
                if self.vncTunnel:
                    logging.debug("Tunnel already open, skipping open_tunnel.")
                    return

                fd = self.open_tunnel(host, "127.0.0.1", port, username)
                if fd >= 0:
                    self.vncViewer.open_fd(fd)
            else:
                self.vncViewer.open_host(host, str(port))
        except:
            (typ, value, stacktrace) = sys.exc_info ()
            details = \
                    "Unable to start virtual machine '%s'" % \
                    (str(typ) + " " + str(value) + "\n" + \
                     traceback.format_exc (stacktrace))
            logging.error(details)

    def set_credentials(self, src=None):
        passwd = self.window.get_widget("console-auth-password")
        if passwd.flags() & gtk.VISIBLE:
            self.vncViewer.set_credential(gtkvnc.CREDENTIAL_PASSWORD,
                                          passwd.get_text())
        username = self.window.get_widget("console-auth-username")
        if username.flags() & gtk.VISIBLE:
            self.vncViewer.set_credential(gtkvnc.CREDENTIAL_USERNAME,
                                          username.get_text())

        if self.window.get_widget("console-auth-remember").get_active():
            self.config.set_console_password(self.vm, passwd.get_text(), username.get_text())

    def _vnc_auth_credential(self, src, credList):
        for i in range(len(credList)):
            if credList[i] not in (gtkvnc.CREDENTIAL_PASSWORD, gtkvnc.CREDENTIAL_USERNAME, gtkvnc.CREDENTIAL_CLIENTNAME):
                self.err.show_err(summary=_("Unable to provide requested credentials to the VNC server"),
                                  details=_("The credential type %s is not supported") % (str(credList[i])),
                                  title=_("Unable to authenticate"),
                                  async=True)
                self.vncViewerRetriesScheduled = 10
                self.vncViewer.close()
                self.activate_unavailable_page(_("Unsupported console authentication type"))
                return

        withUsername = False
        withPassword = False
        for i in range(len(credList)):
            logging.debug("Got credential request %s", str(credList[i]))
            if credList[i] == gtkvnc.CREDENTIAL_PASSWORD:
                withPassword = True
            elif credList[i] == gtkvnc.CREDENTIAL_USERNAME:
                withUsername = True
            elif credList[i] == gtkvnc.CREDENTIAL_CLIENTNAME:
                self.vncViewer.set_credential(credList[i], "libvirt-vnc")

        if withUsername or withPassword:
            self.activate_auth_page(withPassword, withUsername)

    def activate_unavailable_page(self, msg):
        self.window.get_widget("console-pages").set_current_page(PAGE_UNAVAILABLE)
        self.window.get_widget("details-menu-vm-screenshot").set_sensitive(False)
        self.window.get_widget("console-unavailable").set_label("<b>" + msg + "</b>")

    def activate_screenshot_page(self):
        self.window.get_widget("console-pages").set_current_page(PAGE_SCREENSHOT)
        self.window.get_widget("details-menu-vm-screenshot").set_sensitive(True)

    def activate_auth_page(self, withPassword=True, withUsername=False):
        (pw, username) = self.config.get_console_password(self.vm)
        self.window.get_widget("details-menu-vm-screenshot").set_sensitive(False)

        if withPassword:
            self.window.get_widget("console-auth-password").show()
            self.window.get_widget("label-auth-password").show()
        else:
            self.window.get_widget("console-auth-password").hide()
            self.window.get_widget("label-auth-password").hide()

        if withUsername:
            self.window.get_widget("console-auth-username").show()
            self.window.get_widget("label-auth-username").show()
        else:
            self.window.get_widget("console-auth-username").hide()
            self.window.get_widget("label-auth-username").hide()

        self.window.get_widget("console-auth-username").set_text(username)
        self.window.get_widget("console-auth-password").set_text(pw)

        if self.config.has_keyring():
            self.window.get_widget("console-auth-remember").set_sensitive(True)
            if pw != "" or username != "":
                self.window.get_widget("console-auth-remember").set_active(True)
            else:
                self.window.get_widget("console-auth-remember").set_active(False)
        else:
            self.window.get_widget("console-auth-remember").set_sensitive(False)
        self.window.get_widget("console-pages").set_current_page(PAGE_AUTHENTICATE)
        if withUsername:
            self.window.get_widget("console-auth-username").grab_focus()
        else:
            self.window.get_widget("console-auth-password").grab_focus()


    def activate_viewer_page(self):
        self.window.get_widget("console-pages").set_current_page(PAGE_VNCVIEWER)
        self.window.get_widget("details-menu-vm-screenshot").set_sensitive(True)
        self.vncViewer.grab_focus()

    def control_vm_screenshot(self, src):
        # If someone feels kind they could extend this code to allow
        # user to choose what image format they'd like to save in....
        path = util.browse_local(self.window.get_widget("vmm-details"),
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
        image = self.vncViewer.get_pixbuf()

        # Save along with a little metadata about us & the domain
        image.save(filename, 'png',
                   { 'tEXt::Hypervisor URI': self.vm.get_connection().get_uri(),
                     'tEXt::Domain Name': self.vm.get_name(),
                     'tEXt::Domain UUID': self.vm.get_uuid(),
                     'tEXt::Generator App': self.config.get_appname(),
                     'tEXt::Generator Version': self.config.get_appversion() })

        msg = gtk.MessageDialog(self.window.get_widget("vmm-details"),
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
        if src.get_active():
            self._show_serial_tab(name, target_port)
        else:
            self._close_serial_tab(name)

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
        if (tab_idx < 0) or (tab_idx > len(self.dynamic_tabs)-1):
            return
        return self._close_serial_tab(self.dynamic_tabs[tab_idx])

    def serial_copy_text(self, src, terminal):
        terminal.copy_clipboard()

    def serial_paste_text(self, src, terminal):
        terminal.paste_clipboard()

    def _show_serial_tab(self, name, target_port):
        if not self.dynamic_tabs.count(name):
            child = vmmSerialConsole(self.vm, target_port)
            child.terminal.connect("button-press-event",
                                   self.show_serial_rcpopup)
            title = gtk.Label(name)
            child.show_all()
            self.window.get_widget("details-pages").append_page(child, title)
            self.dynamic_tabs.append(name)

        page_idx = self.dynamic_tabs.index(name) + PAGE_DYNAMIC_OFFSET
        self.window.get_widget("details-pages").set_current_page(page_idx)

    def _close_serial_tab(self, name):
        if not self.dynamic_tabs.count(name):
            return

        page_idx = self.dynamic_tabs.index(name) + PAGE_DYNAMIC_OFFSET
        self.window.get_widget("details-pages").remove_page(page_idx)
        self.dynamic_tabs.remove(name)

    # -----------------------
    # Overview -> Security
    # -----------------------
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

    # -----------------------
    # Hardware Section Pieces
    # -----------------------

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

    def config_vcpus_changed(self, src):
        self.window.get_widget("config-apply").set_sensitive(True)

    def config_vcpus_apply(self):
        vcpus = self.window.get_widget("config-vcpus").get_adjustment().value
        logging.info("Setting vcpus for %s to %s" % (self.vm.get_name(),
                                                     str(vcpus)))
        hotplug_err = False

        try:
            if self.vm.is_active():
                self.vm.hotplug_vcpus(vcpus)
        except Exception, e:
            logging.debug("VCPU hotplug failed: %s" % str(e))
            hotplug_err = True

        # Change persistent config
        try:
            self.vm.define_vcpus(vcpus)
        except Exception, e:
            self.err.show_err(_("Error changing vcpu value: %s" % str(e)),
                              "".join(traceback.format_exc()))
            return False

        if hotplug_err:
            self.err.show_info(_("These changes will take effect after the "
                                 "next guest reboot. "))

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

    def config_boot_options_changed(self, src):
        self.window.get_widget("config-apply").set_sensitive(True)

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

    def remove_xml_dev(self, src):
        info = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not info:
            return

        self.remove_device(info[0], info[1])

    def prepare_hw_list(self):
        hw_list_model = gtk.ListStore(str, str, int, gtk.gdk.Pixbuf, int, gobject.TYPE_PYOBJECT)
        self.window.get_widget("hw-list").set_model(hw_list_model)

        hwCol = gtk.TreeViewColumn("Hardware")
        hwCol.set_spacing(24)
        hw_txt = gtk.CellRendererText()
        hw_txt.set_property("xpad", 2)
        hw_img = gtk.CellRendererPixbuf()
        hw_img.set_property("xpad", 4)
        hwCol.pack_start(hw_txt, True)
        hwCol.pack_start(hw_img, False)
        hwCol.add_attribute(hw_txt, 'text', HW_LIST_COL_LABEL)
        hwCol.add_attribute(hw_img, 'stock-id', HW_LIST_COL_STOCK_ID)
        hwCol.add_attribute(hw_img, 'stock-size', HW_LIST_COL_STOCK_SIZE)
        hwCol.add_attribute(hw_img, 'pixbuf', HW_LIST_COL_PIXBUF)
        self.window.get_widget("hw-list").append_column(hwCol)
        self.prepare_boot_list()

        self.populate_hw_list()
        self.repopulate_boot_list()

    def prepare_boot_list(self):
        boot_list = self.window.get_widget("config-boot-device")
        # model = [ display name, icon name, boot type (hd, fd, etc) ]
        boot_list_model = gtk.ListStore(str, str, str)
        boot_list.set_model(boot_list_model)

        icon = gtk.CellRendererPixbuf()
        boot_list.pack_start(icon, False)
        boot_list.add_attribute(icon, 'stock-id', 1)
        text = gtk.CellRendererText()
        boot_list.pack_start(text, True)
        boot_list.add_attribute(text, 'text', 0)

    def populate_hw_list(self):
        hw_list_model = self.window.get_widget("hw-list").get_model()
        hw_list_model.clear()
        hw_list_model.append([_("Overview"), None, 0, self.pixbuf_processor,
                              HW_LIST_TYPE_GENERAL, []])
        hw_list_model.append([_("Performance"), None, 0, self.pixbuf_memory,
                              HW_LIST_TYPE_STATS, []])
        hw_list_model.append([_("Processor"), None, 0, self.pixbuf_processor, HW_LIST_TYPE_CPU, []])
        hw_list_model.append([_("Memory"), None, 0, self.pixbuf_memory, HW_LIST_TYPE_MEMORY, []])
        hw_list_model.append([_("Boot Options"), None, 0, self.pixbuf_memory, HW_LIST_TYPE_BOOT, []])
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

        def update_hwlist(hwtype, info):
            """Return (true if we updated an entry,
                       index to insert at if we didn't update an entry)
            """
            insertAt = 0
            for row in hw_list_model:
                if row[HW_LIST_COL_TYPE] == hwtype and \
                   row[HW_LIST_COL_DEVICE][2] == info[2]:
                    row[HW_LIST_COL_DEVICE] = info
                    return (False, insertAt)

                if row[HW_LIST_COL_TYPE] <= hwtype:
                    insertAt += 1

            return (True, insertAt)

        # Populate list of disks
        for diskinfo in self.vm.get_disk_devices():
            currentDisks[diskinfo[2]] = 1
            missing, insertAt = update_hwlist(HW_LIST_TYPE_DISK,
                                              diskinfo)

            # Add in row
            if missing:
                stock = gtk.STOCK_HARDDISK
                if diskinfo[4] == "cdrom":
                    stock = gtk.STOCK_CDROM
                elif diskinfo[4] == "floppy":
                    stock = gtk.STOCK_FLOPPY
                hw_list_model.insert(insertAt, ["Disk %s" % diskinfo[2], stock, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_DISK, diskinfo])

        # Populate list of NICs
        for netinfo in self.vm.get_network_devices():
            currentNICs[netinfo[2]] = 1
            missing, insertAt = update_hwlist(HW_LIST_TYPE_NIC,
                                              netinfo)

            # Add in row
            if missing:
                hw_list_model.insert(insertAt, ["NIC %s" % netinfo[2][-9:], gtk.STOCK_NETWORK, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_NIC, netinfo])

        # Populate list of input devices
        for inputinfo in self.vm.get_input_devices():
            currentInputs[inputinfo[2]] = 1
            missing, insertAt = update_hwlist(HW_LIST_TYPE_INPUT,
                                              inputinfo)

            # Add in row
            if missing:
                if inputinfo[4] == "tablet":
                    label = _("Tablet")
                elif inputinfo[4] == "mouse":
                    label = _("Mouse")
                else:
                    label = _("Input")
                hw_list_model.insert(insertAt, [label, gtk.STOCK_INDEX, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_INPUT, inputinfo])

        # Populate list of graphics devices
        for gfxinfo in self.vm.get_graphics_devices():
            currentGraphics[gfxinfo[2]] = 1
            missing, insertAt = update_hwlist(HW_LIST_TYPE_GRAPHICS,
                                              gfxinfo)

            # Add in row
            if missing:
                hw_list_model.insert(insertAt, [_("Display %s") % gfxinfo[1].upper(), gtk.STOCK_SELECT_COLOR, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_GRAPHICS, gfxinfo])

        # Populate list of sound devices
        for soundinfo in self.vm.get_sound_devices():
            currentSounds[soundinfo[2]] = 1
            missing, insertAt = update_hwlist(HW_LIST_TYPE_SOUND,
                                              soundinfo)

            # Add in row
            if missing:
                hw_list_model.insert(insertAt, [_("Sound: %s" % soundinfo[2]), gtk.STOCK_MEDIA_PLAY, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_SOUND, soundinfo])

        # Populate list of char devices
        for charinfo in self.vm.get_char_devices():
            currentChars[charinfo[2]] = 1
            missing, insertAt = update_hwlist(HW_LIST_TYPE_CHAR,
                                              charinfo)

            # Add in row
            if missing:
                l = charinfo[0].capitalize()
                if charinfo[0] != "console":
                    l += " %s" % charinfo[3] # Don't show port for console
                hw_list_model.insert(insertAt, [l, gtk.STOCK_CONNECT, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_CHAR, charinfo])

        # Populate host devices
        for hostdevinfo in self.vm.get_hostdev_devices():
            currentHostdevs[hostdevinfo[2]] = 1
            missing, insertAt = update_hwlist(HW_LIST_TYPE_HOSTDEV,
                                              hostdevinfo)

            if missing:
                hw_list_model.insert(insertAt, [hostdevinfo[2], None, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_HOSTDEV, hostdevinfo])

        # Populate video devices
        for vidinfo in self.vm.get_video_devices():
            currentVids[vidinfo[2]] = 1
            missing, insertAt = update_hwlist(HW_LIST_TYPE_VIDEO,
                                              vidinfo)

            if missing:
                hw_list_model.insert(insertAt,
                                     [_("Video"), gtk.STOCK_SELECT_COLOR,
                                      gtk.ICON_SIZE_LARGE_TOOLBAR,
                                      None, HW_LIST_TYPE_VIDEO, vidinfo])

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
            if row[4] == HW_LIST_TYPE_DISK:
                diskinfo = row[5]
                if diskinfo[4] == virtinst.VirtualDisk.DEVICE_DISK and not \
                   found_dev.get(virtinst.VirtualDisk.DEVICE_DISK, False):
                    boot_model.append(["Hard Disk", gtk.STOCK_HARDDISK, "hd"])
                    found_dev[virtinst.VirtualDisk.DEVICE_DISK] = True
                elif diskinfo[4] == virtinst.VirtualDisk.DEVICE_CDROM and not \
                     found_dev.get(virtinst.VirtualDisk.DEVICE_CDROM, False):
                    boot_model.append(["CDROM", gtk.STOCK_CDROM, "cdrom"])
                    found_dev[virtinst.VirtualDisk.DEVICE_CDROM] = True
                elif diskinfo[4] == virtinst.VirtualDisk.DEVICE_FLOPPY and not \
                     found_dev.get(virtinst.VirtualDisk.DEVICE_FLOPPY, False):
                    boot_model.append(["Floppy", gtk.STOCK_FLOPPY, "fd"])
                    found_dev[virtinst.VirtualDisk.DEVICE_FLOPPY] = True
            elif row[4] == HW_LIST_TYPE_NIC and not \
                 found_dev.get(HW_LIST_TYPE_NIC, False):
                boot_model.append(["Network (PXE)", gtk.STOCK_NETWORK, "network"])
                found_dev[HW_LIST_TYPE_NIC] = True

        if len(boot_model) <= 0:
            boot_model.append([_("No Boot Device"), None, None])

        boot_combo.set_model(boot_model)

    def add_hardware(self, src):
        if self.addhw is None:
            self.addhw = vmmAddHardware(self.config, self.vm)

        self.addhw.show()

    def toggle_cdrom(self, src):
        info = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not info:
            return

        if src.get_label() == gtk.STOCK_DISCONNECT:
            #disconnect the cdrom
            try:
                self.vm.disconnect_cdrom_device(info[1])
            except Exception, e:
                self.err.show_err(_("Error Removing CDROM: %s" % str(e)),
                                  "".join(traceback.format_exc()))
                return

        else:
            # connect a new cdrom
            if self.choose_cd is None:
                self.choose_cd = vmmChooseCD(self.config, self.window.get_widget("disk-target-device").get_text(), self.vm.get_connection())
                self.choose_cd.connect("cdrom-chosen", self.connect_cdrom)
            else:
                self.choose_cd.dev_id_info = info[1]
            self.choose_cd.show()

    def connect_cdrom(self, src, typ, source, dev_id_info):
        try:
            self.vm.connect_cdrom_device(typ, source, dev_id_info)
        except Exception, e:
            self.err.show_err(_("Error Connecting CDROM: %s" % str(e)),
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

gobject.type_register(vmmDetails)

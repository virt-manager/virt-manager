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
import traceback
import gtkvnc
import os
import socket
import cairo

from virtManager.error import vmmErrorDialog
from virtManager.addhardware import vmmAddHardware
from virtManager.choosecd import vmmChooseCD

import virtinst
import urlgrabber.progress as progress

# Columns in hw list model
HW_LIST_COL_LABEL = 0
HW_LIST_COL_STOCK_ID = 1
HW_LIST_COL_STOCK_SIZE = 2
HW_LIST_COL_PIXBUF = 3
HW_LIST_COL_TYPE = 4
HW_LIST_COL_DEVICE = 5

# Types for the hw list model: numbers specify what order they will be listed
HW_LIST_TYPE_CPU = 0
HW_LIST_TYPE_MEMORY = 1
HW_LIST_TYPE_BOOT = 2
HW_LIST_TYPE_DISK = 3
HW_LIST_TYPE_NIC = 4
HW_LIST_TYPE_INPUT = 5
HW_LIST_TYPE_GRAPHICS = 6
HW_LIST_TYPE_SOUND = 7
HW_LIST_TYPE_CHAR = 8

# Console pages
PAGE_UNAVAILABLE = 0
PAGE_SCREENSHOT = 1
PAGE_AUTHENTICATE = 2
PAGE_VNCVIEWER = 3

PAGE_CONSOLE = 0
PAGE_OVERVIEW = 1
PAGE_DETAILS = 2
PAGE_FIRST_CHAR = 3

class vmmDetails(gobject.GObject):
    __gsignals__ = {
        "action-show-console": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-terminal": (gobject.SIGNAL_RUN_FIRST,
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
        }


    def __init__(self, config, vm, engine):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-details.glade", "vmm-details", domain="virt-manager")
        self.config = config
        self.vm = vm

        topwin = self.window.get_widget("vmm-details")
        topwin.hide_all()
        self.err = vmmErrorDialog(topwin,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))
        self.title = vm.get_name() + " " + topwin.get_title()
        topwin.set_title(self.title)

        self.engine = engine

        # Don't allowing changing network/disks for Dom0
        if self.vm.is_management_domain():
            self.window.get_widget("add-hardware-button").set_sensitive(False)
        else:
            self.window.get_widget("add-hardware-button").set_sensitive(True)

        self.window.get_widget("overview-name").set_text(self.vm.get_name())
        self.window.get_widget("overview-uuid").set_text(self.vm.get_uuid())

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

        reboot = gtk.ImageMenuItem("_Reboot")
        reboot.set_image(rebootimg)
        reboot.show()
        reboot.connect("activate", self.control_vm_reboot)
        menu.add(reboot)

        shutdown = gtk.ImageMenuItem("_Poweroff")
        shutdown.set_image(shutdownimg)
        shutdown.show()
        shutdown.connect("activate", self.control_vm_shutdown)
        menu.add(shutdown)

        destroy = gtk.ImageMenuItem("_Force poweroff")
        destroy.set_image(destroyimg)
        destroy.show()
        destroy.connect("activate", self.control_vm_destroy)
        menu.add(destroy)


        self.window.get_widget("hw-panel").set_show_tabs(False)

        self.addhw = None
        self.choose_cd = None
        
        self.cpu_usage_graph = sparkline.Sparkline()
        self.window.get_widget("graph-table").attach(self.cpu_usage_graph, 1, 2, 0, 1)

        self.memory_usage_graph = sparkline.Sparkline()
        self.window.get_widget("graph-table").attach(self.memory_usage_graph, 1, 2, 1, 2)

        self.network_traffic_graph = sparkline.Sparkline()
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
        if not topwin.is_composited():
            self.vncViewer.set_scaling(True)
            self.window.get_widget("details-menu-view-scale-display").set_active(True)

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
        self.connected = 0

        self.notifyID = None
        try:
            bus = dbus.SessionBus()
            self.notifyObject = bus.get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
            self.notifyInterface = dbus.Interface(self.notifyObject, "org.freedesktop.Notifications")
            self.notifyInterface.connect_to_signal("ActionInvoked", self.notify_action)
            self.notifyInterface.connect_to_signal("NotificationClosed", self.notify_closed)
        except Exception, e:
            logging.error("Cannot initialize notification system" + str(e))
            pass

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
            "on_details_menu_screenshot_activate": self.control_vm_screenshot,
            "on_details_menu_graphics_activate": self.control_vm_console,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,
            "on_details_menu_view_manager_activate": self.view_manager,
            "on_details_menu_view_serial_activate": self.control_vm_terminal,

            "on_details_pages_switch_page": self.switch_page,

            "on_config_vcpus_apply_clicked": self.config_vcpus_apply,
            "on_config_vcpus_changed": self.config_vcpus_changed,
            "on_config_memory_changed": self.config_memory_changed,
            "on_config_maxmem_changed": self.config_maxmem_changed,
            "on_config_memory_apply_clicked": self.config_memory_apply,
            "on_config_boot_device_changed": self.config_boot_options_changed,
            "on_config_autostart_changed": self.config_boot_options_changed,
            "on_config_boot_apply_clicked": self.config_boot_options_apply,
            "on_details_help_activate": self.show_help,

            "on_config_cdrom_connect_clicked": self.toggle_cdrom,
            "on_config_disk_remove_clicked": self.remove_disk,
            "on_config_network_remove_clicked": self.remove_network,
            "on_config_input_remove_clicked": self.remove_input,
            "on_config_graphics_remove_clicked": self.remove_graphics,
            "on_config_sound_remove_clicked": self.remove_sound,
            "on_config_char_remove_clicked": self.remove_char,
            "on_add_hardware_button_clicked": self.add_hardware,

            "on_details_menu_view_fullscreen_activate": self.toggle_fullscreen,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,
            "on_details_menu_view_scale_display_activate": self.scale_display,

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
            })

        self.vm.connect("status-changed", self.update_widget_states)
        self.vm.connect("resources-sampled", self.refresh_resources)
        self.window.get_widget("hw-list").get_selection().connect("changed", self.hw_selected)

        self.update_widget_states(self.vm, self.vm.status())

        self.pixbuf_processor = gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")
        self.pixbuf_memory = gtk.gdk.pixbuf_new_from_file(config.get_icon_dir() + "/icon_cpu.png")
        self.prepare_hw_list()
        self.hw_selected()
        self.refresh_resources(self.vm)


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

        if self.config.show_console_grab_notify():
            try:
                (x, y) = topwin.window.get_origin()
                self.notifyID = self.notifyInterface.Notify(topwin.get_title(),
                                                            0,
                                                            '',
                                                            _("Pointer grabbed"),
                                                            _("The mouse pointer has been restricted to the virtual " \
                                                            "console window. To release the pointer press the key pair " \
                                                              "Ctrl+Alt"),
                                                            ["dismiss", _("Do not show this notification in the future")],
                                                            {"desktop-entry": "virt-manager",
                                                             "x": x+200, "y": y},
                                                            8 * 1000);
            except Exception, e:
                logging.error("Cannot popup notification " + str(e))
                pass

    def notify_ungrabbed(self, src):
        topwin = self.window.get_widget("vmm-details")
        topwin.set_title(self.title)

    def notify_closed(self, id, reason=None):
        if self.notifyID is not None and self.notifyID == id:
            self.notifyID = None

    def notify_action(self, id, action):
        if self.notifyID is None or self.notifyID != id:
            return

        if action == "dismiss":
            self.config.set_console_grab_notify(False)

    def keygrab_changed(self, src, ignore1=None,ignore2=None,ignore3=None):
        if self.config.get_console_keygrab() == 2:
            self.vncViewer.set_keyboard_grab(True)
        else:
            self.vncViewer.set_keyboard_grab(False)

    def scale_display(self, src):
        if src.get_active():
            self.vncViewer.set_scaling(True)
        else:
            self.vncViewer.set_scaling(False)

    def control_fullscreen(self, src):
        menu = self.window.get_widget("details-menu-view-fullscreen")
        if src.get_active() != menu.get_active():
            menu.set_active(src.get_active())

    def toggle_fullscreen(self, src):
        self.window.get_widget("control-fullscreen").set_active(src.get_active())
        if src.get_active():
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

    def toggle_toolbar(self, src):
        active = src.get_active()
        self.config.set_details_show_toolbar(active)
        if active and not \
           self.window.get_widget("details-menu-view-fullscreen").get_active():
            self.window.get_widget("details-toolbar").show()
        else:
            self.window.get_widget("details-toolbar").hide()

    def show(self):
        dialog = self.window.get_widget("vmm-details")
        if self.is_visible():
            dialog.present()
            return
        dialog.show_all()
        self.window.get_widget("overview-network-traffic-text").hide()
        self.window.get_widget("overview-network-traffic-label").hide()
        self.window.get_widget("overview-disk-usage-bar").hide()
        self.window.get_widget("overview-disk-usage-text").hide()
        self.window.get_widget("overview-disk-usage-label").hide()
        self.network_traffic_graph.hide()
        dialog.present()
        self.engine.increment_window_counter()
        self.update_widget_states(self.vm, self.vm.status())

    def show_help(self, src):
        # From the Details window, show the help document from the Details page
        self.emit("action-show-help", "virt-manager-details-window")

    def activate_console_page(self):
        self.window.get_widget("details-pages").set_current_page(PAGE_CONSOLE)

    def activate_performance_page(self):
        self.window.get_widget("details-pages").set_current_page(PAGE_OVERVIEW)

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


    def hw_selected(self, src=None):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            pagetype = active[0].get_value(active[1], HW_LIST_COL_TYPE)
            self.window.get_widget("hw-panel").set_sensitive(True)
            self.window.get_widget("hw-panel").show_all()

            pagenum = pagetype
            if pagetype == HW_LIST_TYPE_CPU:
                self.window.get_widget("config-vcpus-apply").set_sensitive(False)
                self.refresh_config_cpu()
            elif pagetype == HW_LIST_TYPE_MEMORY:
                self.window.get_widget("config-memory-apply").set_sensitive(False)
                self.refresh_config_memory()
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
            elif pagetype == HW_LIST_TYPE_BOOT:
                self.refresh_boot_page()
                self.window.get_widget("config-boot-options-apply").set_sensitive(False)
            else:
                pagenum = -1

            self.window.get_widget("hw-panel").set_current_page(pagenum)
        else:
            self.window.get_widget("hw-panel").set_sensitive(False)
            selection.select_path(0)
            self.window.get_widget("hw-panel").set_current_page(0)

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

    def control_vm_terminal(self, src):
        self.emit("action-show-terminal", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_console(self, src):
        self.emit("action-show-console", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_save_domain(self, src):
        self.emit("action-save-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_destroy(self, src):
        self.emit("action-destroy-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def set_pause_widget_states(self, state):
        try:
            self.ignorePause = True
            self.window.get_widget("control-pause").set_active(state)
            self.window.get_widget("details-menu-pause").set_active(state)
        finally:
            self.ignorePause = False

    def update_widget_states(self, vm, status):
        self.toggle_toolbar(self.window.get_widget("details-menu-view-toolbar"))

        if vm.is_serial_console_tty_accessible():
            self.window.get_widget("details-menu-view-serial").set_sensitive(True)
        else:
            self.window.get_widget("details-menu-view-serial").set_sensitive(False)

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                       libvirt.VIR_DOMAIN_SHUTOFF ] or vm.is_read_only():
            self.window.get_widget("details-menu-destroy").set_sensitive(False)
        else:
            self.window.get_widget("details-menu-destroy").set_sensitive(True)

        if status in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ] and not self.vm.is_read_only():
            self.window.get_widget("control-run").set_sensitive(True)
            self.window.get_widget("details-menu-run").set_sensitive(True)
            self.window.get_widget("config-vcpus").set_sensitive(True)
            self.window.get_widget("config-memory").set_sensitive(True)
            self.window.get_widget("config-maxmem").set_sensitive(True)
            self.window.get_widget("details-menu-view-serial").set_sensitive(False)
        else:
            self.window.get_widget("control-run").set_sensitive(False)
            self.window.get_widget("details-menu-run").set_sensitive(False)
            self.window.get_widget("config-vcpus").set_sensitive(self.vm.is_vcpu_hotplug_capable())
            self.window.get_widget("config-memory").set_sensitive(self.vm.is_memory_hotplug_capable())
            self.window.get_widget("config-maxmem").set_sensitive(True)

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

        if status in [ libvirt.VIR_DOMAIN_SHUTOFF ,libvirt.VIR_DOMAIN_CRASHED ]:
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

    def switch_page(self, ignore1=None, ignore2=None,newpage=None):
        details = self.window.get_widget("details-pages")
        self.page_refresh(newpage)

    def refresh_resources(self, ignore=None):
        details = self.window.get_widget("details-pages")
        self.page_refresh(details.get_current_page())

    def page_refresh(self, page):
        if page == PAGE_OVERVIEW:
            self.refresh_summary()
        elif page == PAGE_DETAILS:
            # Add / remove new devices
            self.repopulate_hw_list()

            # Now refresh desired page
            hw_list = self.window.get_widget("hw-list")
            selection = hw_list.get_selection()
            active = selection.get_selected()
            if active[1] != None:
                pagetype = active[0].get_value(active[1], HW_LIST_COL_TYPE)
                device_info = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
                hw_model = hw_list.get_model()
                if pagetype == HW_LIST_TYPE_CPU:
                    self.refresh_config_cpu()
                elif pagetype == HW_LIST_TYPE_MEMORY:
                    self.refresh_config_memory()
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

    def refresh_summary(self):
        self.window.get_widget("overview-cpu-usage-text").set_text("%d %%" % self.vm.cpu_time_percentage())
        vm_memory = self.vm.current_memory()
        host_memory = self.vm.get_connection().host_memory_size()
        self.window.get_widget("overview-memory-usage-text").set_text("%d MB of %d MB" % \
                                                                      (int(round(vm_memory/1024.0)), \
                                                                       int(round(host_memory/1024.0))))

        history_len = self.config.get_stats_history_length()
        cpu_vector = self.vm.cpu_time_vector()
        cpu_vector.reverse()
        self.cpu_usage_graph.set_property("data_array", cpu_vector)

        memory_vector = self.vm.current_memory_vector()
        memory_vector.reverse()
        self.memory_usage_graph.set_property("data_array", memory_vector)

        network_vector = self.vm.network_traffic_vector()
        network_vector.reverse()
        self.network_traffic_graph.set_property("data_array", network_vector)

    def refresh_config_cpu(self):
        self.window.get_widget("state-host-cpus").set_text("%d" % self.vm.get_connection().host_active_processor_count())
        status = self.vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
            cpu_max = self.vm.get_connection().get_max_vcpus(self.vm.get_type())
            self.window.get_widget("config-vcpus").get_adjustment().upper = cpu_max
            self.window.get_widget("state-vm-maxvcpus").set_text(str(cpu_max))
        else:
            self.window.get_widget("config-vcpus").get_adjustment().upper = self.vm.vcpu_max_count()
            self.window.get_widget("state-vm-maxvcpus").set_text("%d" % (self.vm.vcpu_max_count()))

        if not(self.window.get_widget("config-vcpus-apply").get_property("sensitive")):
            self.window.get_widget("config-vcpus").get_adjustment().value = self.vm.vcpu_count()
            # XXX hack - changing the value above will have just re-triggered
            # the callback making apply button sensitive again. So we have to
            # turn it off again....
            self.window.get_widget("config-vcpus-apply").set_sensitive(False)
        self.window.get_widget("state-vm-vcpus").set_text("%d" % (self.vm.vcpu_count()))

    def refresh_config_memory(self):
        self.window.get_widget("state-host-memory").set_text("%d MB" % (int(round(self.vm.get_connection().host_memory_size()/1024))))

        curmem = self.window.get_widget("config-memory").get_adjustment()
        maxmem = self.window.get_widget("config-maxmem").get_adjustment()


        if self.window.get_widget("config-memory-apply").get_property("sensitive"):
            if curmem.value > maxmem.value:
                curmem.value = maxmem.value
            curmem.upper = maxmem.value
        else:
            curmem.value = int(round(self.vm.get_memory()/1024.0))
            maxmem.value = int(round(self.vm.maximum_memory()/1024.0))
            # XXX hack - changing the value above will have just re-triggered
            # the callback making apply button sensitive again. So we have to
            # turn it off again....
            self.window.get_widget("config-memory-apply").set_sensitive(False)

        if not self.window.get_widget("config-memory").get_property("sensitive"):
            maxmem.lower = curmem.value
        self.window.get_widget("state-vm-memory").set_text("%d MB" % int(round(self.vm.get_memory()/1024.0)))

    def refresh_disk_page(self):
        # get the currently selected line
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            diskinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
            self.window.get_widget("disk-source-type").set_text(diskinfo[0])
            self.window.get_widget("disk-source-path").set_text(diskinfo[1])
            self.window.get_widget("disk-target-type").set_text(diskinfo[2])
            self.window.get_widget("disk-target-device").set_text(diskinfo[3])
            if diskinfo[4] == True:
                perms = "Readonly"
            else:
                perms = "Read/Write"
            if diskinfo[5] == True:
                perms += ", Sharable"
            self.window.get_widget("disk-permissions").set_text(perms)
            bus = diskinfo[6] or _("Unknown")
            self.window.get_widget("disk-bus").set_text(bus)

            button = self.window.get_widget("config-cdrom-connect")
            if diskinfo[2] == "cdrom":
                if diskinfo[1] == "-":
                    # source device not connected
                    button.set_label(gtk.STOCK_CONNECT)
                else:
                    button.set_label(gtk.STOCK_DISCONNECT)
                button.show()
            else:
                button.hide()

    def refresh_network_page(self):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            netinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
            self.window.get_widget("network-source-type").set_text(netinfo[0])
            if netinfo[1] is not None:
                self.window.get_widget("network-source-device").set_text(netinfo[1])
            else:
                self.window.get_widget("network-source-device").set_text("-")
            self.window.get_widget("network-mac-address").set_text(netinfo[3])
            model = netinfo[4] or _("Hypervisor Default")
            self.window.get_widget("network-source-model").set_text(model)

    def refresh_input_page(self):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            inputinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
            if inputinfo[3] == "tablet:usb":
                self.window.get_widget("input-dev-type").set_text(_("EvTouch USB Graphics Tablet"))
            elif inputinfo[3] == "mouse:usb":
                self.window.get_widget("input-dev-type").set_text(_("Generic USB Mouse"))
            elif inputinfo[3] == "mouse:xen":
                self.window.get_widget("input-dev-type").set_text(_("Xen Mouse"))
            elif inputinfo[3] == "mouse:ps2":
                self.window.get_widget("input-dev-type").set_text(_("PS/2 Mouse"))
            else:
                self.window.get_widget("input-dev-type").set_text(inputinfo[0] + " " + inputinfo[1])

            if inputinfo[0] == "tablet":
                self.window.get_widget("input-dev-mode").set_text(_("Absolute Movement"))
            else:
                self.window.get_widget("input-dev-mode").set_text(_("Relative Movement"))

            # Can't remove primary Xen or PS/2 mice
            if inputinfo[0] == "mouse" and inputinfo[1] in ("xen", "ps2"):
                self.window.get_widget("config-input-remove").set_sensitive(False)
            else:
                self.window.get_widget("config-input-remove").set_sensitive(True)

    def refresh_graphics_page(self):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            inputinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
            if inputinfo[0] == "vnc":
                self.window.get_widget("graphics-type").set_text(_("VNC server"))
            elif inputinfo[0] == "sdl":
                self.window.get_widget("graphics-type").set_text(_("Local SDL window"))
            else:
                self.window.get_widget("graphics-type").set_text(inputinfo[0])

            if inputinfo[0] == "vnc":
                if inputinfo[1] == None:
                    self.window.get_widget("graphics-address").set_text("127.0.0.1")
                else:
                    self.window.get_widget("graphics-address").set_text(inputinfo[1])
                if int(inputinfo[2]) == -1:
                    self.window.get_widget("graphics-port").set_text(_("Automatically allocated"))
                else:
                    self.window.get_widget("graphics-port").set_text(inputinfo[2])
                self.window.get_widget("graphics-password").set_text("-")
                self.window.get_widget("graphics-keymap").set_text(inputinfo[4] or "en-us")
            else:
                self.window.get_widget("graphics-address").set_text(_("N/A"))
                self.window.get_widget("graphics-port").set_text(_("N/A"))
                self.window.get_widget("graphics-password").set_text("N/A")
                self.window.get_widget("graphics-keymap").set_text("N/A")

            # Can't remove display from live guest
            if self.vm.is_active():
                self.window.get_widget("config-graphics-remove").set_sensitive(False)
            else:
                self.window.get_widget("config-graphics-remove").set_sensitive(True)

    def refresh_sound_page(self):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] is None:
            return
        sound = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
        self.window.get_widget("sound-model").set_text(sound[3])

        # Can't remove sound dev from live guest
        if self.vm.is_active():
            self.window.get_widget("config-sound-remove").set_sensitive(False)
        else:
            self.window.get_widget("config-sound-remove").set_sensitive(True)

    def refresh_char_page(self):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] is None:
            return
        char = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
        typelabel = "<b>%s Device %s</b>" % (char[0].capitalize(),
                                             char[5] and _("(Primary Console)") or "")
        self.window.get_widget("char-type").set_markup(typelabel)
        self.window.get_widget("char-dev-type").set_text(char[1] or "-")
        self.window.get_widget("char-target-port").set_text(char[2])
        self.window.get_widget("char-source-path").set_text(char[4] or "-")

        # Can't remove char dev from live guest
        if self.vm.is_active() or char[0] == "console":
            self.window.get_widget("config-char-remove").set_sensitive(False)
        else:
            self.window.get_widget("config-char-remove").set_sensitive(True)

    def refresh_boot_page(self):
        # Refresh autostart
        try:
            autoval = self.vm.get_autostart()
            self.window.get_widget("config-autostart").set_active(autoval)
            self.window.get_widget("config-autostart").set_sensitive(True)
        except libvirt.libvirtError, e:
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
        self.connected = 0
        logging.debug("VNC disconnected")
        if self.vm.status() in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
            self.view_vm_status()
            return

        self.activate_unavailable_page(_("TCP/IP error: VNC connection to hypervisor host got refused or disconnected!"))

        if not self.is_visible():
            return

        self.schedule_retry()

    def _vnc_initialized(self, src):
        self.connected = 1
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
        if self.connected:
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
            return

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
        if self.vm.get_id() < 0:
            self.activate_unavailable_page(_("Guest not running"))
            self.schedule_retry()
            return

        logging.debug("Trying console login")
        password = self.window.get_widget("console-auth-password").get_text()
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
                fd = self.open_tunnel(host, "127.0.0.1", port, username)
                self.vncViewer.open_fd(fd)
            else:
                self.vncViewer.open_host(host, str(port))
        except:
            (type, value, stacktrace) = sys.exc_info ()
            details = \
                    "Unable to start virtual machine '%s'" % \
                    (str(type) + " " + str(value) + "\n" + \
                     traceback.format_exc (stacktrace))
            logging.error(details)

    def set_password(self, src=None):
        txt = self.window.get_widget("console-auth-password")
        logging.debug("Setting a password to " + str(txt.get_text()))

        self.vncViewer.set_credential(gtkvnc.CREDENTIAL_PASSWORD, txt.get_text())

    def _vnc_auth_credential(self, src, credList):
        for i in range(len(credList)):
            logging.debug("Got credential request %s", str(credList[i]))
            if credList[i] == gtkvnc.CREDENTIAL_PASSWORD:
                self.activate_auth_page()
            elif credList[i] == gtkvnc.CREDENTIAL_CLIENTNAME:
                self.vncViewer.set_credential(credList[i], "libvirt-vnc")
            else:
                # Force it to stop re-trying
                self.vncViewerRetriesScheduled = 10
                self.vncViewer.close()
                self.activate_unavailable_page(_("Unsupported console authentication type"))

    def activate_unavailable_page(self, msg):
        self.window.get_widget("console-pages").set_current_page(PAGE_UNAVAILABLE)
        self.window.get_widget("details-menu-vm-screenshot").set_sensitive(False)
        self.window.get_widget("console-unavailable").set_label("<b>" + msg + "</b>")

    def activate_screenshot_page(self):
        self.window.get_widget("console-pages").set_current_page(PAGE_SCREENSHOT)
        self.window.get_widget("details-menu-vm-screenshot").set_sensitive(True)

    def activate_auth_page(self):
        pw = self.config.get_console_password(self.vm)
        self.window.get_widget("details-menu-vm-screenshot").set_sensitive(False)
        self.window.get_widget("console-auth-password").set_text(pw)
        self.window.get_widget("console-auth-password").grab_focus()
        if self.config.has_keyring():
            self.window.get_widget("console-auth-remember").set_sensitive(True)
            if pw != None and pw != "":
                self.window.get_widget("console-auth-remember").set_active(True)
            else:
                self.window.get_widget("console-auth-remember").set_active(False)
        else:
            self.window.get_widget("console-auth-remember").set_sensitive(False)
        self.window.get_widget("console-pages").set_current_page(PAGE_AUTHENTICATE)

    def activate_viewer_page(self):
        self.window.get_widget("console-pages").set_current_page(PAGE_VNCVIEWER)
        self.window.get_widget("details-menu-vm-screenshot").set_sensitive(True)
        self.vncViewer.grab_focus()

    def control_vm_screenshot(self, src):
        # If someone feels kind they could extend this code to allow
        # user to choose what image format they'd like to save in....
        fcdialog = gtk.FileChooserDialog(_("Save Virtual Machine Screenshot"),
                                         self.window.get_widget("vmm-details"),
                                         gtk.FILE_CHOOSER_ACTION_SAVE,
                                         (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                          gtk.STOCK_SAVE, gtk.RESPONSE_ACCEPT),
                                         None)
        fcdialog.set_default_response(gtk.RESPONSE_ACCEPT)
        png = gtk.FileFilter()
        png.set_name("PNG files")
        png.add_pattern("*.png")
        fcdialog.add_filter(png)
        fcdialog.set_do_overwrite_confirmation(True)
        if fcdialog.run() == gtk.RESPONSE_ACCEPT:
            fcdialog.hide()
            file = fcdialog.get_filename()
            if not(file.endswith(".png")):
                file = file + ".png"
            image = self.vncViewer.get_pixbuf()
            width = image.get_width()
            height = image.get_height()

            # Save along with a little metadata about us & the domain
            image.save(file, 'png', { 'tEXt::Hypervisor URI': self.vm.get_connection().get_uri(),
                                      'tEXt::Domain Name': self.vm.get_name(),
                                      'tEXt::Domain UUID': self.vm.get_uuid(),
                                      'tEXt::Generator App': self.config.get_appname(),
                                      'tEXt::Generator Version': self.config.get_appversion() })
            msg = gtk.MessageDialog(self.window.get_widget("vmm-details"),
                                    gtk.DIALOG_MODAL,
                                    gtk.MESSAGE_INFO,
                                    gtk.BUTTONS_OK,_("The screenshot has been saved to:\n%s") % file)
            msg.set_title(_("Screenshot saved"))
            msg.run()
            msg.destroy()
        else:
            fcdialog.hide()
        fcdialog.destroy()

    def config_vcpus_changed(self, src):
        self.window.get_widget("config-vcpus-apply").set_sensitive(True)

    def config_vcpus_apply(self, src):
        vcpus = self.window.get_widget("config-vcpus").get_adjustment().value
        logging.info("Setting vcpus for " + self.vm.get_uuid() + " to " + str(vcpus))
        self.vm.set_vcpu_count(vcpus)
        self.window.get_widget("config-vcpus-apply").set_sensitive(False)

    def config_memory_changed(self, src):
        self.window.get_widget("config-memory-apply").set_sensitive(True)

    def config_maxmem_changed(self, src):
        self.window.get_widget("config-memory-apply").set_sensitive(True)
        memory = self.window.get_widget("config-maxmem").get_adjustment().value
        memadj = self.window.get_widget("config-memory").get_adjustment()
        memadj.upper = memory
        if memadj.value > memory:
            memadj.value = memory

    def config_memory_apply(self, src):
        status = self.vm.status()
        self.refresh_config_memory()
        exc = None
        curmem = None
        maxmem = self.window.get_widget("config-maxmem").get_adjustment()
        if self.window.get_widget("config-memory").get_property("sensitive"):
            curmem = self.window.get_widget("config-memory").get_adjustment()

        logging.info("Setting max-memory for " + self.vm.get_name() + \
                     " to " + str(maxmem.value))

        actual_cur = self.vm.get_memory()
        if curmem is not None:
            logging.info("Setting memory for " + self.vm.get_name() + \
                         " to " + str(curmem.value))
            if (maxmem.value * 1024) < actual_cur:
                # Set current first to avoid error
                try:
                    self.vm.set_memory(curmem.value * 1024)
                    self.vm.set_max_memory(maxmem.value * 1024)
                except Exception, e:
                    exc = e
            else:
                try:
                    self.vm.set_max_memory(maxmem.value * 1024)
                    self.vm.set_memory(curmem.value * 1024)
                except Exception, e:
                    exc = e

        else:
            try:
                self.vm.set_max_memory(maxmem.value * 1024)
            except Exception, e:
                exc = e

        if exc:
            self.err.show_err(_("Error changing memory values: %s" % str(e)),\
                              "".join(traceback.format_exc()))
        else:
            self.window.get_widget("config-memory-apply").set_sensitive(False)

    def config_boot_options_changed(self, src):
        self.window.get_widget("config-boot-options-apply").set_sensitive(True)

    def config_boot_options_apply(self, src):
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
                self.window.get_widget("config-boot-options-apply").set_sensitive(False)
            except Exception, e:
                self.err.show_err(_("Error changing boot device: %s" % str(e)),
                                  "".join(traceback.format_exc()))
                return

    def remove_disk(self, src):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            diskinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)
            self.remove_device(self.vm.get_disk_xml(diskinfo[3]))
            self.refresh_resources()

    def remove_network(self, src):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            netinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)

            vnic = None
            try:
                if netinfo[0] == "bridge":
                    vnic = virtinst.VirtualNetworkInterface(type=netinfo[0], bridge=netinfo[1], macaddr=netinfo[3])
                elif netinfo[0] == "network":
                    vnic = virtinst.VirtualNetworkInterface(type=netinfo[0], network=netinfo[1], macaddr=netinfo[3])
                else:
                    vnic = virtinst.VirtualNetworkInterface(type=netinfo[0], macaddr=netinfo[3])
            except ValueError, e:
                self.err.show_err(_("Error Removing Network: %s" % str(e)),
                                  "".join(traceback.format_exc()))
                return False

            xml = vnic.get_xml_config()
            self.remove_device(xml)
            self.refresh_resources()

    def remove_input(self, src):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            inputinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)

            xml = "<input type='%s' bus='%s'/>" % (inputinfo[0], inputinfo[1])
            self.remove_device(xml)
            self.refresh_resources()

    def remove_graphics(self, src):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] != None:
            inputinfo = active[0].get_value(active[1], HW_LIST_COL_DEVICE)

            xml = "<graphics type='%s'/>" % inputinfo[0]
            self.remove_device(xml)
            self.refresh_resources()

    def remove_sound(self, src):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] is None:
            return
        sound = active[0].get_value(active[1], HW_LIST_COL_DEVICE)

        xml = "<sound model='%s'/>" % sound[3]
        self.remove_device(xml)
        self.refresh_resources()

    def remove_char(self, src):
        vmlist = self.window.get_widget("hw-list")
        selection = vmlist.get_selection()
        active = selection.get_selected()
        if active[1] is None:
            return
        char = active[0].get_value(active[1], HW_LIST_COL_DEVICE)

        xml = "<%s>\n" % char[0] + \
              "  <target port='%s'/>\n" % char[2] + \
              "</%s>" % char[0]
        self.remove_device(xml)
        self.refresh_resources()

    def prepare_hw_list(self):
        hw_list_model = gtk.ListStore(str, str, int, gtk.gdk.Pixbuf, int, gobject.TYPE_PYOBJECT)
        self.window.get_widget("hw-list").set_model(hw_list_model)

        hwCol = gtk.TreeViewColumn("Hardware")
        hw_txt = gtk.CellRendererText()
        hw_img = gtk.CellRendererPixbuf()
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
        hw_list_model.append(["Processor", None, 0, self.pixbuf_processor, HW_LIST_TYPE_CPU, []])
        hw_list_model.append(["Memory", None, 0, self.pixbuf_memory, HW_LIST_TYPE_MEMORY, []])
        hw_list_model.append(["Boot Options", None, 0, self.pixbuf_memory, HW_LIST_TYPE_BOOT, []])
        self.repopulate_hw_list()

    def repopulate_hw_list(self):
        hw_list = self.window.get_widget("hw-list")
        hw_list_model = hw_list.get_model()

        # Populate list of disks
        currentDisks = {}
        for disk in self.vm.get_disk_devices():
            missing = True
            insertAt = 0
            currentDisks[disk[3]] = 1
            for row in hw_list_model:
                if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_DISK and row[HW_LIST_COL_DEVICE][3] == disk[3]:
                    # Update metadata
                    row[HW_LIST_COL_DEVICE] = disk
                    missing = False

                if row[HW_LIST_COL_TYPE] <= HW_LIST_TYPE_DISK:
                    insertAt = insertAt + 1

            # Add in row
            if missing:
                stock = gtk.STOCK_HARDDISK
                if disk[2] == "cdrom":
                    stock = gtk.STOCK_CDROM
                elif disk[2] == "floppy":
                    stock = gtk.STOCK_FLOPPY
                hw_list_model.insert(insertAt, ["Disk %s" % disk[3], stock, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_DISK, disk])

        # Populate list of NICs
        currentNICs = {}
        for nic in self.vm.get_network_devices():
            missing = True
            insertAt = 0
            currentNICs[nic[3]] = 1
            for row in hw_list_model:
                if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_NIC and row[HW_LIST_COL_DEVICE][3] == nic[3]:
                    # Update metadata
                    row[HW_LIST_COL_DEVICE] = nic
                    missing = False

                if row[HW_LIST_COL_TYPE] <= HW_LIST_TYPE_NIC:
                    insertAt = insertAt + 1

            # Add in row
            if missing:
                hw_list_model.insert(insertAt, ["NIC %s" % nic[3][-9:], gtk.STOCK_NETWORK, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_NIC, nic])

        # Populate list of input devices
        currentInputs = {}
        for input in self.vm.get_input_devices():
            missing = True
            insertAt = 0
            currentInputs[input[3]] = 1
            for row in hw_list_model:
                if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_INPUT and row[HW_LIST_COL_DEVICE][3] == input[3]:
                    # Update metadata
                    row[HW_LIST_COL_DEVICE] = input
                    missing = False

                if row[HW_LIST_COL_TYPE] <= HW_LIST_TYPE_INPUT:
                    insertAt = insertAt + 1

            # Add in row
            if missing:
                if input[0] == "tablet":
                    hw_list_model.insert(insertAt, [_("Tablet"), gtk.STOCK_INDEX, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_INPUT, input])
                elif input[0] == "mouse":
                    hw_list_model.insert(insertAt, [_("Mouse"), gtk.STOCK_INDEX, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_INPUT, input])
                else:
                    hw_list_model.insert(insertAt, [_("Input"), gtk.STOCK_INDEX, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_INPUT, input])

        # Populate list of graphics devices
        currentGraphics = {}
        for graphic in self.vm.get_graphics_devices():
            missing = True
            insertAt = 0
            currentGraphics[graphic[3]] = 1
            for row in hw_list_model:
                if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_GRAPHICS and row[HW_LIST_COL_DEVICE][3] == graphic[3]:
                    # Update metadata
                    row[HW_LIST_COL_DEVICE] = graphic
                    missing = False

                if row[HW_LIST_COL_TYPE] <= HW_LIST_TYPE_GRAPHICS:
                    insertAt = insertAt + 1

            # Add in row
            if missing:
                hw_list_model.insert(insertAt, [_("Display"), gtk.STOCK_SELECT_COLOR, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_GRAPHICS, graphic])

        # Populate list of sound devices
        currentSounds = {}
        for sound in self.vm.get_sound_devices():
            missing = True
            insertAt = 0
            currentSounds[sound[3]] = 1
            for row in hw_list_model:
                if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_SOUND and \
                   row[HW_LIST_COL_DEVICE][3] == sound[3]:
                    # Update metadata
                    row[HW_LIST_COL_DEVICE] = sound
                    missing = False

                if row[HW_LIST_COL_TYPE] <= HW_LIST_TYPE_SOUND:
                    insertAt = insertAt + 1
            # Add in row
            if missing:
                hw_list_model.insert(insertAt, [_("Sound: %s" % sound[3]), gtk.STOCK_MEDIA_PLAY, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_SOUND, sound])


        # Populate list of char devices
        currentChars = {}
        for char in self.vm.get_char_devices():
            missing = True
            insertAt = 0
            currentChars[char[3]] = 1
            for row in hw_list_model:
                if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_CHAR and \
                   row[HW_LIST_COL_DEVICE][3] == char[3]:
                    # Update metadata
                    row[HW_LIST_COL_DEVICE] = char
                    missing = False

                if row[HW_LIST_COL_TYPE] <= HW_LIST_TYPE_CHAR:
                    insertAt = insertAt + 1
            # Add in row
            if missing:
                l = char[0].capitalize()
                if char[0] != "console":
                    l += " %s" % char[2] # Don't show port for console
                hw_list_model.insert(insertAt, [l, gtk.STOCK_CONNECT, gtk.ICON_SIZE_LARGE_TOOLBAR, None, HW_LIST_TYPE_CHAR, char])


        # Now remove any no longer current devs
        devs = range(len(hw_list_model))
        devs.reverse()
        for i in devs:
            iter = hw_list_model.iter_nth_child(None, i)
            row = hw_list_model[i]
            removeIt = False

            if row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_DISK and not \
               currentDisks.has_key(row[HW_LIST_COL_DEVICE][3]):
                removeIt = True
            elif row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_NIC and not \
                 currentNICs.has_key(row[HW_LIST_COL_DEVICE][3]):
                removeIt = True
            elif row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_INPUT and not \
                 currentInputs.has_key(row[HW_LIST_COL_DEVICE][3]):
                removeIt = True
            elif row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_GRAPHICS and not \
                 currentGraphics.has_key(row[HW_LIST_COL_DEVICE][3]):
                removeIt = True
            elif row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_SOUND and not \
                 currentSounds.has_key(row[HW_LIST_COL_DEVICE][3]):
                removeIt = True
            elif row[HW_LIST_COL_TYPE] == HW_LIST_TYPE_CHAR and not \
                 currentChars.has_key(row[HW_LIST_COL_DEVICE][3]):
                removeIt = True

            if removeIt:
                # Re-select the first row, if we're viewing the device
                # we're about to remove
                (selModel, selIter) = hw_list.get_selection().get_selected()
                selType = selModel.get_value(selIter, HW_LIST_COL_TYPE)
                selInfo = selModel.get_value(selIter, HW_LIST_COL_DEVICE)
                if selType == row[HW_LIST_COL_TYPE] and selInfo[3] == row[HW_LIST_COL_DEVICE][3]:
                    hw_list.get_selection().select_iter(selModel.iter_nth_child(None, 0))

                # Now actually remove it
                hw_list_model.remove(iter)

    def repopulate_boot_list(self):
        hw_list_model = self.window.get_widget("hw-list").get_model()
        boot_combo = self.window.get_widget("config-boot-device")
        boot_model = boot_combo.get_model()
        boot_model.clear()
        found_dev = {}
        for row in hw_list_model:
            if row[4] == HW_LIST_TYPE_DISK:
                disk = row[5]
                if disk[2] == virtinst.VirtualDisk.DEVICE_DISK and not \
                   found_dev.get(virtinst.VirtualDisk.DEVICE_DISK, False):
                    boot_model.append(["Hard Disk", gtk.STOCK_HARDDISK, "hd"])
                    found_dev[virtinst.VirtualDisk.DEVICE_DISK] = True
                elif disk[2] == virtinst.VirtualDisk.DEVICE_CDROM and not \
                     found_dev.get(virtinst.VirtualDisk.DEVICE_CDROM, False):
                    boot_model.append(["CDROM", gtk.STOCK_CDROM, "cdrom"])
                    found_dev[virtinst.VirtualDisk.DEVICE_CDROM] = True
                elif disk[2] == virtinst.VirtualDisk.DEVICE_FLOPPY and not \
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
            self.addhw.topwin.connect("hide", self.add_hardware_done)

        self.addhw.show()

    def add_hardware_done(self, ignore=None):
        self.refresh_resources()

    def toggle_cdrom(self, src):
        if src.get_label() == gtk.STOCK_DISCONNECT:
            #disconnect the cdrom
            try:
                self.vm.disconnect_cdrom_device(self.window.get_widget("disk-target-device").get_text())
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
                self.choose_cd.set_target(self.window.get_widget("disk-target-device").get_text())
            self.choose_cd.show()

    def connect_cdrom(self, src, type, source, target):
        try:
            self.vm.connect_cdrom_device(type, source, target)
        except Exception, e:
            self.err.show_err(_("Error Connecting CDROM: %s" % str(e)),
                              "".join(traceback.format_exc()))

    def remove_device(self, xml):
        logging.debug("Removing device:\n%s" % xml)

        detach_err = False
        try:
            self.vm.detach_device(xml)
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

        if self.vm.is_active() and not detach_err:
            return

        try:
            self.vm.remove_device(xml)
        except Exception, e:
            self.err.show_err(_("Error Removing Device: %s" % str(e)),
                              "".join(traceback.format_exc()))

gobject.type_register(vmmDetails)

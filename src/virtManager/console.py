#
# Copyright (C) 2006 Red Hat, Inc.
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
import cairo
import gtk.glade
import libvirt
import sys
import logging
import dbus
import traceback
import gtkvnc
import os
import socket

from virtManager.error import vmmErrorDialog

PAGE_UNAVAILABLE = 0
PAGE_SCREENSHOT = 1
PAGE_AUTHENTICATE = 2
PAGE_VNCVIEWER = 3

class vmmConsole(gobject.GObject):
    __gsignals__ = {
        "action-show-details": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-terminal": (gobject.SIGNAL_RUN_FIRST,
                                   gobject.TYPE_NONE, (str,str)),
        "action-save-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str,str)),
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                               gobject.TYPE_NONE, [str]),
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
        }
    def __init__(self, config, vm):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-console.glade", "vmm-console", domain="virt-manager")
        self.config = config
        self.vm = vm

        topwin = self.window.get_widget("vmm-console")
        topwin.hide()
        self.title = vm.get_name() + " " + topwin.get_title()
        topwin.set_title(self.title)
        self.window.get_widget("control-shutdown").set_icon_widget(gtk.Image())
        self.window.get_widget("control-shutdown").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_shutdown.png")

        self.accel_groups = gtk.accel_groups_from_object(topwin)
        self.gtk_settings_accel = None

        self.vncViewer = gtkvnc.Display()
        self.window.get_widget("console-vnc-align").add(self.vncViewer)
        self.vncViewer.realize()
        self.vncTunnel = None
        if self.config.get_console_keygrab() == 2:
            self.vncViewer.set_keyboard_grab(True)
            self.vncViewer.set_pointer_grab(True)
        else:
            self.vncViewer.set_keyboard_grab(False)
            self.vncViewer.set_pointer_grab(False)
        self.vncViewer.set_pointer_local(True)

        self.vncViewer.connect("vnc-pointer-grab", self.notify_grabbed)
        self.vncViewer.connect("vnc-pointer-ungrab", self.notify_ungrabbed)

        self.vncViewer.show()
        self.vncViewerRetriesScheduled = 0
        self.vncViewerRetryDelay = 125
        self.vncViewer.connect("size-request", self._force_resize)
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

        self.config.on_console_keygrab_changed(self.keygrab_changed)

        self.ignorePause = False

        self.window.signal_autoconnect({
            "on_vmm_console_delete_event": self.close,

            "on_control_run_clicked": self.control_vm_run,
            "on_control_shutdown_clicked": self.control_vm_shutdown,
            "on_control_pause_toggled": self.control_vm_pause,

            "on_menu_vm_run_activate": self.control_vm_run,
            "on_menu_vm_shutdown_activate": self.control_vm_shutdown,
            "on_menu_vm_save_activate": self.control_vm_save_domain,
            "on_menu_vm_destroy_activate": self.control_vm_destroy,
            "on_menu_vm_screenshot_activate": self.control_vm_screenshot,
            "on_menu_vm_pause_activate": self.control_vm_pause,

            "on_menu_view_serial_activate": self.control_vm_terminal,
            "on_menu_view_details_activate": self.control_vm_details,
            "on_menu_view_fullscreen_activate": self.toggle_fullscreen,
            "on_menu_view_toolbar_activate": self.toggle_toolbar,

            "on_menu_vm_close_activate": self.close,

            "on_console_auth_login_clicked": self.set_password,
            "on_console_help_activate": self.show_help,

            "on_menu_send_cad_activate": self.send_key,
            "on_menu_send_cab_activate": self.send_key,
            "on_menu_send_caf1_activate": self.send_key,
            "on_menu_send_caf2_activate": self.send_key,
            "on_menu_send_caf3_activate": self.send_key,
            "on_menu_send_caf4_activate": self.send_key,
            "on_menu_send_caf5_activate": self.send_key,
            "on_menu_send_caf6_activate": self.send_key,
            "on_menu_send_caf7_activate": self.send_key,
            "on_menu_send_caf8_activate": self.send_key,
            "on_menu_send_printscreen_activate": self.send_key,
            })

        self.vm.connect("status-changed", self.update_widget_states)

        self.vncViewer.connect("vnc-auth-credential", self._vnc_auth_credential)
        self.vncViewer.connect("vnc-initialized", self._vnc_initialized)
        self.vncViewer.connect("vnc-disconnected", self._vnc_disconnected)
        self.vncViewer.connect("vnc-keyboard-grab", self._disable_modifiers)
        self.vncViewer.connect("vnc-keyboard-ungrab", self._enable_modifiers)

    # Black magic todo with scrolled windows. Basically the behaviour we want
    # is that if it possible to resize the window to show entire guest desktop
    # then we should do that and never show scrollbars. If the local screen is
    # too small then we can turn on scrolling. You would think the 'Automatic'
    # policy would work, but even if viewport is identical sized to the VNC
    # widget it still seems to show scrollbars. So we do evil stuff here
    def _force_resize(self, src, size):
        w,h = src.get_size_request()
        self.window.get_widget("console-screenshot").set_size_request(w, h)
        self.window.get_widget("console-vnc-scroll").set_size_request(w, h)
        topw,toph = self.window.get_widget("vmm-console").size_request()

        padx = topw-w
        pady = toph-h
        rootw = src.get_screen().get_width()
        rooth = src.get_screen().get_height()

        maxw = rootw - 100 - padx
        maxh = rooth - 100 - pady
        self.window.get_widget("console-vnc-viewport").set_size_request(w, h)
        self.window.get_widget("console-screenshot-viewport").set_size_request(w, h)
        if w > maxw or h > maxh:
            self.window.get_widget("console-vnc-scroll").set_policy(gtk.POLICY_ALWAYS, gtk.POLICY_ALWAYS)
            self.window.get_widget("console-screenshot-scroll").set_policy(gtk.POLICY_ALWAYS, gtk.POLICY_ALWAYS)
        else:
            self.window.get_widget("console-vnc-scroll").set_policy(gtk.POLICY_NEVER, gtk.POLICY_NEVER)
            self.window.get_widget("console-screenshot-scroll").set_policy(gtk.POLICY_NEVER, gtk.POLICY_NEVER)

    # Auto-increase the window size to fit the console - within reason
    # though, cos we don't want a min window size greater than the screen
    # the user has scrollbars anyway if they want it smaller / it can't fit
    def autosize(self, src, size):
        rootWidth = gtk.gdk.screen_width()
        rootHeight = gtk.gdk.screen_height()

        vncWidth, vncHeight = src.get_size_request()

        if vncWidth > (rootWidth-200):
            vncWidth = rootWidth - 200
        if vncHeight > (rootHeight-200):
            vncHeight = rootHeight - 200

        self.window.get_widget("console-vnc-vp").set_size_request(vncWidth+2, vncHeight+2)

    def send_key(self, src):
        keys = None
        if src.get_name() == "menu-send-cad":
            keys = ["Control_L", "Alt_L", "Del"]
        elif src.get_name() == "menu-send-cab":
            keys = ["Control_L", "Alt_L", "BackSpace"]
        elif src.get_name() == "menu-send-caf1":
            keys = ["Control_L", "Alt_L", "F1"]
        elif src.get_name() == "menu-send-caf2":
            keys = ["Control_L", "Alt_L", "F2"]
        elif src.get_name() == "menu-send-caf3":
            keys = ["Control_L", "Alt_L", "F3"]
        elif src.get_name() == "menu-send-caf4":
            keys = ["Control_L", "Alt_L", "F4"]
        elif src.get_name() == "menu-send-caf5":
            keys = ["Control_L", "Alt_L", "F5"]
        elif src.get_name() == "menu-send-caf6":
            keys = ["Control_L", "Alt_L", "F6"]
        elif src.get_name() == "menu-send-caf7":
            keys = ["Control_L", "Alt_L", "F7"]
        elif src.get_name() == "menu-send-caf8":
            keys = ["Control_L", "Alt_L", "F8"]
        elif src.get_name() == "menu-send-printscreen":
            keys = ["PrintScreen"]

        if keys != None:
            self.vncViewer.send_keys(keys)

    def _disable_modifiers(self, ignore=None):
        topwin = self.window.get_widget("vmm-console")
        for g in self.accel_groups:
            topwin.remove_accel_group(g)
        settings = gtk.settings_get_default()
        self.gtk_settings_accel = settings.get_property('gtk-menu-bar-accel')
        settings.set_property('gtk-menu-bar-accel', None)

    def _enable_modifiers(self, ignore=None):
        topwin = self.window.get_widget("vmm-console")
        if self.gtk_settings_accel is None:
            return
        settings = gtk.settings_get_default()
        settings.set_property('gtk-menu-bar-accel', self.gtk_settings_accel)
        self.gtk_settings_accel = None
        for g in self.accel_groups:
            topwin.add_accel_group(g)

    def notify_grabbed(self, src):
        topwin = self.window.get_widget("vmm-console")
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
        topwin = self.window.get_widget("vmm-console")
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
            self.vncViewer.set_pointer_grab(True)
        else:
            self.vncViewer.set_keyboard_grab(False)
            self.vncViewer.set_pointer_grab(False)

    def toggle_fullscreen(self, src):
        if src.get_active():
            self.window.get_widget("vmm-console").fullscreen()
            if self.config.get_console_keygrab() == 1:
                gtk.gdk.keyboard_grab(self.vncViewer.window, False, 0L)
                self._disable_modifiers()
        else:
            if self.config.get_console_keygrab() == 1:
                self._enable_modifiers()
                gtk.gdk.keyboard_ungrab(0L)
            self.window.get_widget("vmm-console").unfullscreen()

    def toggle_toolbar(self, src):
        if src.get_active():
            self.window.get_widget("console-toolbar").show()
        else:
            self.window.get_widget("console-toolbar").hide()

    def show(self):
        dialog = self.window.get_widget("vmm-console")
        dialog.show_all()
        dialog.present()
        self.update_widget_states(self.vm, self.vm.status())

    def show_help(self, src):
        # From the Console window, show the help document from the Console page
        self.emit("action-show-help", "virt-manager-console-window") 


    def close(self,ignore1=None,ignore2=None):
        fs = self.window.get_widget("menu-view-fullscreen")
        if fs.get_active():
            fs.set_active(False)

        self.window.get_widget("vmm-console").hide()
        if self.vncViewer.flags() & gtk.VISIBLE:
	    try:
                self.vncViewer.close()
	    except:
		logging.error("Failure when disconnecting from VNC server")
        return 1

    def is_visible(self):
        if self.window.get_widget("vmm-console").flags() & gtk.VISIBLE:
           return 1
        return 0

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

    def open_tunnel(self, server, vncaddr ,vncport):
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
            os.execlp("ssh", "ssh", "-p", "22", "-l", "root", server, "nc", vncaddr, str(vncport))
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
        protocol, host, port, trans = self.vm.get_graphics_console()

        if protocol is None:
            logging.debug("No graphics configured in guest")
            self.activate_unavailable_page(_("Console not configured for guest"))
            return

        uri = str(protocol) + "://" + str(host) + ":" + str(port)
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
                fd = self.open_tunnel(host, "127.0.0.1", port)
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
        self.window.get_widget("menu-vm-screenshot").set_sensitive(False)
        self.window.get_widget("console-unavailable").set_label("<b>" + msg + "</b>")

    def activate_screenshot_page(self):
        self.window.get_widget("console-pages").set_current_page(PAGE_SCREENSHOT)
        self.window.get_widget("menu-vm-screenshot").set_sensitive(True)

    def activate_auth_page(self):
        pw = self.config.get_console_password(self.vm)
        self.window.get_widget("menu-vm-screenshot").set_sensitive(False)
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
        self.window.get_widget("menu-vm-screenshot").set_sensitive(True)
        self.vncViewer.grab_focus()

    def control_vm_screenshot(self, src):
        # If someone feels kind they could extend this code to allow
        # user to choose what image format they'd like to save in....
        fcdialog = gtk.FileChooserDialog(_("Save Virtual Machine Screenshot"),
                                         self.window.get_widget("vmm-console"),
                                         gtk.FILE_CHOOSER_ACTION_SAVE,
                                         (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                          gtk.STOCK_SAVE, gtk.RESPONSE_ACCEPT),
                                         None)
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
            msg = gtk.MessageDialog(self.window.get_widget("vmm-console"),
                                    gtk.DIALOG_MODAL,
                                    gtk.MESSAGE_INFO,
                                    gtk.BUTTONS_OK,_("The screenshot has been saved to:\n%s") % file)
            msg.set_title(_("Screenshot saved"))
            msg.run()
            msg.destroy()
        else:
            fcdialog.hide()
        fcdialog.destroy()

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

    def control_vm_terminal(self, src):
        self.emit("action-show-terminal", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_save_domain(self, src):
        self.emit("action-save-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_destroy(self, src):
        self.emit("action-destroy-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_details(self, src):
        self.emit("action-show-details", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def update_widget_states(self, vm, status):
        self.toggle_toolbar(self.window.get_widget("menu-view-toolbar"))
        self.ignorePause = True
        if status in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
            self.window.get_widget("control-run").set_sensitive(True)
            self.window.get_widget("menu-vm-run").set_sensitive(True)
        else:
            self.window.get_widget("control-run").set_sensitive(False)
            self.window.get_widget("menu-vm-run").set_sensitive(False)

        if vm.is_serial_console_tty_accessible():
            self.window.get_widget("menu-view-serial").set_sensitive(True)
        else:
            self.window.get_widget("menu-view-serial").set_sensitive(False)

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF ] or vm.is_read_only():
            # apologies for the spaghetti, but the destroy choice is a special case
            self.window.get_widget("menu-vm-destroy").set_sensitive(False)
        else:
            self.window.get_widget("menu-vm-destroy").set_sensitive(True)

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF ,libvirt.VIR_DOMAIN_CRASHED ] or vm.is_read_only():
            self.window.get_widget("control-pause").set_sensitive(False)
            self.window.get_widget("control-shutdown").set_sensitive(False)
            self.window.get_widget("menu-vm-pause").set_sensitive(False)
            self.window.get_widget("menu-vm-shutdown").set_sensitive(False)
            self.window.get_widget("menu-vm-save").set_sensitive(False)
        else:
            self.window.get_widget("control-pause").set_sensitive(True)
            self.window.get_widget("control-shutdown").set_sensitive(True)
            self.window.get_widget("menu-vm-pause").set_sensitive(True)
            self.window.get_widget("menu-vm-shutdown").set_sensitive(True)
            self.window.get_widget("menu-vm-save").set_sensitive(True)
            if status == libvirt.VIR_DOMAIN_PAUSED:
                self.window.get_widget("control-pause").set_active(True)
                self.window.get_widget("menu-vm-pause").set_active(True)
            else:
                self.window.get_widget("control-pause").set_active(False)
                self.window.get_widget("menu-vm-pause").set_active(False)

        if status in [ libvirt.VIR_DOMAIN_SHUTOFF ,libvirt.VIR_DOMAIN_CRASHED ]:
            if self.window.get_widget("console-pages").get_current_page() != PAGE_UNAVAILABLE:
                self.vncViewer.close()
                self.window.get_widget("console-pages").set_current_page(PAGE_UNAVAILABLE)
            self.view_vm_status()
        else:
            if status == libvirt.VIR_DOMAIN_PAUSED:
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
                else:
                    if self.window.get_widget("console-pages").get_current_page() != PAGE_UNAVAILABLE:
                        self.vncViewer.close()
                    self.activate_unavailable_page(_("Console not available while paused"))
            else:
                if self.window.get_widget("console-pages").get_current_page() in (PAGE_UNAVAILABLE, PAGE_SCREENSHOT):
                    if self.vncViewer.is_open():
                        self.activate_viewer_page()
                    else:
                        self.vncViewerRetriesScheduled = 0
                        self.vncViewerRetryDelay = 125
                        self.try_login()
                        self.ignorePause = False
        self.ignorePause = False


gobject.type_register(vmmConsole)

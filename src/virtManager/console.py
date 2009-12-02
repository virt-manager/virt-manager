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
import sys
import dbus
import gtkvnc
import os
import socket

from virtManager.error import vmmErrorDialog

# Console pages
PAGE_UNAVAILABLE = 0
PAGE_AUTHENTICATE = 1
PAGE_VNCVIEWER = 2

def has_property(obj, setting):
    try:
        obj.get_property(setting)
    except TypeError:
        return False
    return True

class vmmConsolePages(gobject.GObject):
    def __init__(self, config, vm, engine, window):
        self.__gobject_init__()

        self.config = config
        self.vm = vm
        self.engine = engine
        self.window = window

        self.topwin = self.window.get_widget("vmm-details")
        self.err = vmmErrorDialog(self.topwin,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))

        self.title = vm.get_name() + " " + self.topwin.get_title()
        self.topwin.set_title(self.title)

        # State for disabling modifiers when keyboard is grabbed
        self.accel_groups = gtk.accel_groups_from_object(self.topwin)
        self.gtk_settings_accel = None
        self.gtk_settings_mnemonic = None

        # Last noticed desktop resolution
        self.desktop_resolution = None

        # Initialize display widget
        self.scale_type = self.vm.get_console_scaling()
        self.vncTunnel = None
        self.vncViewerRetriesScheduled = 0
        self.vncViewerRetryDelay = 125
        self.vnc_connected = False

        self.vncViewer = gtkvnc.Display()
        self.window.get_widget("console-vnc-viewport").add(self.vncViewer)

        self.init_vnc()

        finish_img = gtk.image_new_from_stock(gtk.STOCK_YES,
                                              gtk.ICON_SIZE_BUTTON)
        self.window.get_widget("console-auth-login").set_image(finish_img)

        self.notifyID = None
        self.notifyInterface = None
        self.init_dbus()

        # Make VNC widget background always be black
        black = gtk.gdk.Color("black")
        self.window.get_widget("console-vnc-viewport").modify_bg(
                                                        gtk.STATE_NORMAL,
                                                        black)

        # Signals are added by vmmDetails. Don't use signal_autoconnect here
        # or it changes will be overwritten


    def is_visible(self):
        if self.topwin.flags() & gtk.VISIBLE:
            return 1
        return 0

    ##########################
    # Initialization helpers #
    ##########################

    def init_dbus(self):
        try:
            bus = dbus.SessionBus()
            notifyObject = bus.get_object("org.freedesktop.Notifications",
                                          "/org/freedesktop/Notifications")
            self.notifyInterface = dbus.Interface(notifyObject,
                                                  "org.freedesktop.Notifications")
            self.notifyInterface.connect_to_signal("ActionInvoked",
                                                   self.notify_action)
            self.notifyInterface.connect_to_signal("NotificationClosed",
                                                   self.notify_closed)
        except Exception, e:
            logging.error("Cannot initialize notification system" + str(e))


    def init_vnc(self):
        self.vncViewer.realize()

        # Make sure viewer doesn't force resize itself
        self.vncViewer.set_force_size(False)

        # Set VNC console scaling
        self.vm.on_console_scaling_changed(self.refresh_scaling)
        self.refresh_scaling()

        if self.config.get_console_keygrab() == 2:
            self.vncViewer.set_keyboard_grab(True)
        else:
            self.vncViewer.set_keyboard_grab(False)
        self.vncViewer.set_pointer_grab(True)

        scroll = self.window.get_widget("console-vnc-scroll")
        scroll.connect("size-allocate", self.scroll_size_allocate)

        self.vncViewer.connect("vnc-pointer-grab", self.notify_grabbed)
        self.vncViewer.connect("vnc-pointer-ungrab", self.notify_ungrabbed)
        self.vncViewer.connect("vnc-auth-credential", self._vnc_auth_credential)
        self.vncViewer.connect("vnc-initialized", self._vnc_initialized)
        self.vncViewer.connect("vnc-disconnected", self._vnc_disconnected)
        self.vncViewer.connect("vnc-keyboard-grab", self._disable_modifiers)
        self.vncViewer.connect("vnc-keyboard-ungrab", self._enable_modifiers)
        self.vncViewer.connect("vnc-desktop-resize", self.desktop_resize)
        self.vncViewer.show()

    #############
    # Listeners #
    #############

    def notify_grabbed(self, src):
        self.topwin.set_title(_("Press Ctrl+Alt to release pointer.") +
                              " " + self.title)

        if (not self.config.show_console_grab_notify() or
            not self.notifyInterface):
            return

        try:
            if self.notifyID is not None:
                self.notifyInterface.CloseNotification(self.notifyID)
                self.notifyID = None

            (x, y) = self.topwin.window.get_origin()
            self.notifyID = self.notifyInterface.Notify(self.topwin.get_title(),
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
        self.topwin.set_title(self.title)

    def notify_closed(self, i, reason=None):
        if self.notifyID is not None and self.notifyID == i:
            self.notifyID = None

    def notify_action(self, i, action):
        if self.notifyID is None or self.notifyID != i:
            return

        if action == "dismiss":
            self.config.set_console_grab_notify(False)


    def _disable_modifiers(self, ignore=None):
        if self.gtk_settings_accel is not None:
            return

        for g in self.accel_groups:
            self.topwin.remove_accel_group(g)

        settings = gtk.settings_get_default()
        self.gtk_settings_accel = settings.get_property('gtk-menu-bar-accel')
        settings.set_property('gtk-menu-bar-accel', None)

        if has_property(settings, "gtk-enable-mnemonics"):
            self.gtk_settings_mnemonic = settings.get_property("gtk-enable-mnemonics")
            settings.set_property("gtk-enable-mnemonics", False)


    def _enable_modifiers(self, ignore=None):
        if self.gtk_settings_accel is None:
            return

        settings = gtk.settings_get_default()
        settings.set_property('gtk-menu-bar-accel', self.gtk_settings_accel)
        self.gtk_settings_accel = None

        if self.gtk_settings_mnemonic is not None:
            settings.set_property("gtk-enable-mnemonics",
                                  self.gtk_settings_mnemonic)

        for g in self.accel_groups:
            self.topwin.add_accel_group(g)

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
        vnc_scroll = self.window.get_widget("console-vnc-scroll")

        if (self.scale_type == self.config.CONSOLE_SCALE_NEVER
            and curscale == True):
            self.vncViewer.set_scaling(False)
        elif (self.scale_type == self.config.CONSOLE_SCALE_ALWAYS
              and curscale == False):
            self.vncViewer.set_scaling(True)
        elif (self.scale_type == self.config.CONSOLE_SCALE_FULLSCREEN
              and curscale != fs):
            self.vncViewer.set_scaling(fs)

        # Refresh viewer size
        vnc_scroll.queue_resize()

    def auth_login(self, ignore):
        self.set_credentials()
        self.activate_viewer_page()

    def toggle_fullscreen(self, src):
        do_fullscreen = src.get_active()

        self.window.get_widget("control-fullscreen").set_active(do_fullscreen)

        if do_fullscreen:
            self.topwin.fullscreen()

            if self.config.get_console_keygrab() == 1:
                gtk.gdk.keyboard_grab(self.vncViewer.window, False, 0L)
                self._disable_modifiers()

            self.window.get_widget("toolbar-box").hide()
        else:
            if self.config.get_console_keygrab() == 1:
                self._enable_modifiers()
                gtk.gdk.keyboard_ungrab(0L)

            self.topwin.unfullscreen()

            if self.window.get_widget("details-menu-view-toolbar").get_active():
                self.window.get_widget("toolbar-box").show()

        self.update_scaling()

    def size_to_vm(self, src):
        # Resize the console to best fit the VM resolution
        if not self.desktop_resolution:
            return

        w, h = self.desktop_resolution
        self.topwin.unmaximize()
        self.topwin.resize(1, 1)
        self.queue_resize_helper("console-vnc-scroll", w, h)

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


    ##########################
    # State tracking methods #
    ##########################

    def view_vm_status(self):
        status = self.vm.status()
        if status == libvirt.VIR_DOMAIN_SHUTOFF:
            self.activate_unavailable_page(_("Guest not running"))
        else:
            if status == libvirt.VIR_DOMAIN_CRASHED:
                self.activate_unavailable_page(_("Guest has crashed"))

    def update_widget_states(self, vm, status):
        runable = vm.is_runable()
        pages   = self.window.get_widget("console-pages")
        page    = pages.get_current_page()

        if runable:
            if page != PAGE_UNAVAILABLE:
                self.vncViewer.close()
                pages.set_current_page(PAGE_UNAVAILABLE)

            self.view_vm_status()
            return

        elif page in [PAGE_UNAVAILABLE, PAGE_VNCVIEWER]:
            if self.vncViewer.is_open():
                self.activate_viewer_page()
            else:
                self.vncViewerRetriesScheduled = 0
                self.vncViewerRetryDelay = 125
                self.try_login()

        return

    ###################
    # Page Navigation #
    ###################

    def activate_unavailable_page(self, msg):
        self.window.get_widget("console-pages").set_current_page(PAGE_UNAVAILABLE)
        self.window.get_widget("details-menu-vm-screenshot").set_sensitive(False)
        self.window.get_widget("console-unavailable").set_label("<b>" + msg + "</b>")

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


    ########################
    # VNC Specific methods #
    ########################

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
            self.try_login()
            return
        finally:
            gtk.gdk.threads_leave()

    def open_tunnel(self, server, vncaddr, vncport, username):
        if self.vncTunnel is not None:
            return -1

        # Build SSH cmd
        argv = ["ssh", "ssh"]
        if server.count(":"):
            (server, sshport) = server.split(":")
            argv += ["-p", sshport]

        if username:
            argv += ['-l', username]

        argv += [ server, "nc", vncaddr, str(vncport) ]

        logging.debug("Creating SSH tunnel: %s" % argv)

        fds = socket.socketpair()
        pid = os.fork()
        if pid == 0:
            fds[0].close()
            os.close(0)
            os.close(1)
            os.dup(fds[1].fileno())
            os.dup(fds[1].fileno())
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

        logging.debug("Shutting down tunnel PID %d FD %d" %
                      (self.vncTunnel[1], self.vncTunnel[0].fileno()))
        self.vncTunnel[0].close()
        os.waitpid(self.vncTunnel[1], 0)
        self.vncTunnel = None

    def try_login(self, src=None):
        if not self.vm.get_handle():
            # VM was removed, skip login attempt
            return

        if self.vm.get_id() < 0:
            self.activate_unavailable_page(_("Guest not running"))
            self.schedule_retry()
            return

        protocol, host, port, trans, username = self.vm.get_graphics_console()

        if protocol is None:
            logging.debug("No graphics configured in guest")
            self.activate_unavailable_page(_("Graphical console not configured for guest"))
            return

        uri = str(protocol) + "://"
        if username:
            uri = uri + str(username) + '@'
        uri = uri + str(host) + ":" + str(port)

        logging.debug("Graphics console configured at " + uri)

        if protocol != "vnc":
            logging.debug("Not a VNC console, disabling")
            self.activate_unavailable_page(_("Graphical console not supported for guest"))
            return

        if int(port) == -1:
            self.activate_unavailable_page(_("Graphical console is not yet active for guest"))
            self.schedule_retry()
            return

        self.activate_unavailable_page(_("Connecting to graphical console for guest"))
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
            self.config.set_console_password(self.vm, passwd.get_text(),
                                             username.get_text())

    def _vnc_auth_credential(self, src, credList):
        for i in range(len(credList)):
            if credList[i] not in [gtkvnc.CREDENTIAL_PASSWORD,
                                   gtkvnc.CREDENTIAL_USERNAME,
                                   gtkvnc.CREDENTIAL_CLIENTNAME]:
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

    def desktop_resize(self, src, w, h):
        self.desktop_resolution = (w, h)
        self.window.get_widget("console-vnc-scroll").queue_resize()

    def queue_resize_helper(self, widget_name, w, h):
        """
        Resize the VNC container widget to the requested size. The new size
        isn't a hard requirment so the user can still shrink the window
        again, as opposed to set_size_request
        """
        widget = self.window.get_widget(widget_name)
        signal_holder = []

        def unset_cb(src):
            widget.queue_resize_no_redraw()
            return False

        def request_cb(src, req):
            signal_id = signal_holder[0]
            req.width = w
            req.height = h

            src.disconnect(signal_id)

            gobject.idle_add(unset_cb, widget)
            return False

        signal_id = widget.connect("size-request", request_cb)
        signal_holder.append(signal_id)

        widget.queue_resize()

    def scroll_size_allocate(self, src, req):
        if not self.desktop_resolution:
            return

        scroll = self.window.get_widget("console-vnc-scroll")
        is_scale = self.vncViewer.get_scaling()

        dx = 0
        dy = 0
        align_ratio = float(req.width) / float(req.height)

        vnc_w, vnc_h = self.desktop_resolution
        vnc_ratio = float(vnc_w) / float(vnc_h)

        if not is_scale:
            # Scaling disabled is easy, just force the VNC widget size. Since
            # we are inside a scrollwindow, it shouldn't cause issues.
            scroll.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
            self.vncViewer.set_size_request(vnc_w, vnc_h)
            return

        # Make sure we never show scrollbars when scaling
        scroll.set_policy(gtk.POLICY_NEVER, gtk.POLICY_NEVER)

        # Make sure there is no hard size requirement so we can scale down
        self.vncViewer.set_size_request(-1, -1)

        # Make sure desktop aspect ratio is maintained
        if align_ratio > vnc_ratio:
            vnc_w = int(req.height * vnc_ratio)
            vnc_h = req.height
            dx = (req.width - vnc_w) / 2

        else:
            vnc_w = req.width
            vnc_h = int(req.width / vnc_ratio)
            dy = (req.height - vnc_h) / 2

        vnc_alloc = gtk.gdk.Rectangle(x=dx,
                                      y=dy,
                                      width=vnc_w,
                                      height=vnc_h)

        self.vncViewer.size_allocate(vnc_alloc)

gobject.type_register(vmmConsolePages)

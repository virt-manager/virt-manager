# -*- coding: utf-8 -*-
#
# Copyright (C) 2006-2008 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
# Copyright (C) 2010 Marc-André Lureau <marcandre.lureau@redhat.com>
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

import gtk
import gobject

import libvirt

import gtkvnc

try:
    import SpiceClientGtk as spice
except:
    spice = None

import os
import signal
import socket
import logging

import virtManager.util as util
import virtManager.uihelpers as uihelpers
from virtManager.autodrawer import AutoDrawer
from virtManager.baseclass import vmmGObjectUI, vmmGObject
from virtManager.error import vmmErrorDialog

# Console pages
PAGE_UNAVAILABLE = 0
PAGE_AUTHENTICATE = 1
PAGE_VIEWER = 2

def has_property(obj, setting):
    try:
        obj.get_property(setting)
    except TypeError:
        return False
    return True

class ConnectionInfo(object):
    """
    Holds all the bits needed to make a connection to a graphical console
    """
    def __init__(self, conn, gdev):
        self.gtype      = gdev.type
        self.gport      = gdev.port and str(gdev.port) or None
        self.gsocket    = gdev.socket
        self.gaddr      = gdev.listen or "127.0.0.1"

        self.transport, self.connuser = conn.get_transport()
        self._connhost = conn.get_uri_hostname() or "127.0.0.1"

        self._connport = None
        if self._connhost.count(":"):
            self._connhost, self._connport = self._connhost.split(":", 1)

    def need_tunnel(self):
        if self.gaddr != "127.0.0.1":
            return False

        return self.transport in ["ssh", "ext"]

    def get_conn_host(self):
        host = self._connhost
        port = self._connport

        if not self.need_tunnel():
            port = self.gport
            if self.gaddr != "0.0.0.0":
                host = self.gaddr

        return host, port

    def logstring(self):
        return ("proto=%s trans=%s connhost=%s connuser=%s "
                "connport=%s gaddr=%s gport=%s gsocket=%s" %
                (self.gtype, self.transport, self._connhost, self.connuser,
                 self._connport, self.gaddr, self.gport, self.gsocket))
    def console_active(self):
        if self.gsocket:
            return True
        if not self.gport:
            return False
        return int(self.gport) == -1

class Tunnel(object):
    def __init__(self):
        self.outfd = None
        self.errfd = None
        self.pid = None

    def open(self, ginfo):
        if self.outfd is not None:
            return -1

        host, port = ginfo.get_conn_host()

        # Build SSH cmd
        argv = ["ssh", "ssh"]
        if port:
            argv += ["-p", str(port)]

        if ginfo.connuser:
            argv += ['-l', ginfo.connuser]

        argv += [host]

        # Build 'nc' command run on the remote host
        #
        # This ugly thing is a shell script to detect availability of
        # the -q option for 'nc': debian and suse based distros need this
        # flag to ensure the remote nc will exit on EOF, so it will go away
        # when we close the VNC tunnel. If it doesn't go away, subsequent
        # VNC connection attempts will hang.
        #
        # Fedora's 'nc' doesn't have this option, and apparently defaults
        # to the desired behavior.
        #
        if ginfo.gsocket:
            nc_params = "-U %s" % ginfo.gsocket
        else:
            nc_params = "%s %s" % (ginfo.gaddr, ginfo.gport)

        nc_cmd = (
            """nc -q 2>&1 | grep "requires an argument" >/dev/null;"""
            """if [ $? -eq 0 ] ; then"""
            """   CMD="nc -q 0 %(nc_params)s";"""
            """else"""
            """   CMD="nc %(nc_params)s";"""
            """fi;"""
            """eval "$CMD";""" %
            {'nc_params': nc_params})

        argv.append("sh -c")
        argv.append("'%s'" % nc_cmd)

        argv_str = reduce(lambda x, y: x + " " + y, argv[1:])
        logging.debug("Creating SSH tunnel: %s", argv_str)

        fds      = socket.socketpair()
        errorfds = socket.socketpair()

        pid = os.fork()
        if pid == 0:
            fds[0].close()
            errorfds[0].close()

            os.close(0)
            os.close(1)
            os.close(2)
            os.dup(fds[1].fileno())
            os.dup(fds[1].fileno())
            os.dup(errorfds[1].fileno())
            os.execlp(*argv)
            os._exit(1)
        else:
            fds[1].close()
            errorfds[1].close()

        logging.debug("Tunnel PID=%d OUTFD=%d ERRFD=%d",
                      pid, fds[0].fileno(), errorfds[0].fileno())
        errorfds[0].setblocking(0)

        self.outfd = fds[0]
        self.errfd = errorfds[0]
        self.pid = pid

        fd = fds[0].fileno()
        if fd < 0:
            raise SystemError("can't open a new tunnel: fd=%d" % fd)
        return fd

    def close(self):
        if self.outfd is None:
            return

        logging.debug("Shutting down tunnel PID=%d OUTFD=%d ERRFD=%d",
                      self.pid, self.outfd.fileno(),
                      self.errfd.fileno())
        self.outfd.close()
        self.outfd = None
        self.errfd.close()
        self.errfd = None

        os.kill(self.pid, signal.SIGKILL)
        os.waitpid(self.pid, 0)
        self.pid = None

    def get_err_output(self):
        errout = ""
        while True:
            try:
                new = self.errfd.recv(1024)
            except:
                break

            if not new:
                break

            errout += new

        return errout

class Tunnels(object):
    def __init__(self, ginfo):
        self.ginfo = ginfo
        self._tunnels = []

    def open_new(self):
        t = Tunnel()
        fd = t.open(self.ginfo)
        self._tunnels.append(t)
        return fd

    def close_all(self):
        for l in self._tunnels:
            l.close()

    def get_err_output(self):
        errout = ""
        for l in self._tunnels:
            errout += l.get_err_output()
        return errout


class Viewer(vmmGObject):
    def __init__(self, console):
        vmmGObject.__init__(self)
        self.console = console
        self.display = None
        self.need_keygrab = False

    def close(self):
        raise NotImplementedError()

    def _cleanup(self):
        self.close()

        if self.display:
            self.display.destroy()
        self.display = None
        self.console = None

    def get_pixbuf(self):
        return self.display.get_pixbuf()

    def get_grab_keys(self):
        keystr = None
        try:
            keys = self.display.get_grab_keys()
            for k in keys:
                if keystr is None:
                    keystr = gtk.gdk.keyval_name(k)
                else:
                    keystr = keystr + "+" + gtk.gdk.keyval_name(k)
        except:
            pass

        return keystr

    def send_keys(self, keys):
        return self.display.send_keys(keys)

    def set_grab_keys(self):
        try:
            keys = self.config.get_keys_combination()
            if not keys:
                return

            if not hasattr(self.display, "set_grab_keys"):
                logging.debug("Display class doesn't support custom grab "
                              "combination.")
                return

            try:
                keys = map(int, keys.split(','))
            except:
                logging.debug("Error in grab_keys configuration in GConf",
                              exc_info=True)
                return

            self.display.set_grab_keys(keys)
        except Exception, e:
            logging.debug("Error when getting the grab keys combination: %s",
                          str(e))

    def open_host(self, ginfo, password=None):
        raise NotImplementedError()

    def open_fd(self, fd, password=None):
        raise NotImplementedError()

    def get_desktop_resolution(self):
        raise NotImplementedError()

class VNCViewer(Viewer):
    def __init__(self, console):
        Viewer.__init__(self, console)
        self.display = gtkvnc.Display()
        self.sockfd = None

        # Last noticed desktop resolution
        self.desktop_resolution = None

        # VNC viewer needs a bit of help grabbing keyboard in a friendly way
        self.need_keygrab = True

    def init_widget(self):
        self.set_grab_keys()

        self.display.realize()

        # Make sure viewer doesn't force resize itself
        self.display.set_force_size(False)

        self.console.refresh_scaling()

        self.display.set_keyboard_grab(False)
        self.display.set_pointer_grab(True)

        self.display.connect("vnc-pointer-grab", self.console.pointer_grabbed)
        self.display.connect("vnc-pointer-ungrab", self.console.pointer_ungrabbed)
        self.display.connect("vnc-auth-credential", self._auth_credential)
        self.display.connect("vnc-initialized",
                             lambda src: self.console.connected())
        self.display.connect("vnc-disconnected",
                             lambda src: self.console.disconnected())
        self.display.connect("vnc-desktop-resize", self._desktop_resize)
        self.display.connect("focus-in-event", self.console.viewer_focus_changed)
        self.display.connect("focus-out-event", self.console.viewer_focus_changed)

        self.display.show()

    def _desktop_resize(self, src_ignore, w, h):
        self.desktop_resolution = (w, h)
        self.console.window.get_object("console-vnc-scroll").queue_resize()

    def get_desktop_resolution(self):
        return self.desktop_resolution

    def _auth_credential(self, src_ignore, credList):
        for cred in credList:
            if cred in [gtkvnc.CREDENTIAL_PASSWORD,
                        gtkvnc.CREDENTIAL_USERNAME,
                        gtkvnc.CREDENTIAL_CLIENTNAME]:
                continue

            self.console.err.show_err(
                summary=_("Unable to provide requested credentials to "
                          "the VNC server"),
                details=(_("The credential type %s is not supported") %
                         (str(cred))),
                title=_("Unable to authenticate"),
                async=True)

            # schedule_retry will error out
            self.console.viewerRetriesScheduled = 10
            self.close()
            self.console.activate_unavailable_page(
                            _("Unsupported console authentication type"))
            return

        withUsername = False
        withPassword = False
        for cred in credList:
            logging.debug("Got credential request %s", cred)
            if cred == gtkvnc.CREDENTIAL_PASSWORD:
                withPassword = True
            elif cred == gtkvnc.CREDENTIAL_USERNAME:
                withUsername = True
            elif cred == gtkvnc.CREDENTIAL_CLIENTNAME:
                self.display.set_credential(cred, "libvirt-vnc")

        if withUsername or withPassword:
            self.console.activate_auth_page(withPassword, withUsername)

    def get_scaling(self):
        return self.display.get_scaling()

    def set_scaling(self, scaling):
        return self.display.set_scaling(scaling)

    def close(self):
        self.display.close()
        if not self.sockfd:
            return

        self.sockfd.close()
        self.sockfd = None

    def is_open(self):
        return self.display.is_open()

    def open_host(self, ginfo, password=None):
        host, port = ginfo.get_conn_host()

        if not ginfo.gsocket:
            logging.debug("VNC connection to %s:%s", host, port)
            self.display.open_host(host, port)
            return

        logging.debug("VNC connecting to socket=%s", ginfo.gsocket)
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(ginfo.gsocket)
            self.sockfd = sock
        except Exception, e:
            raise RuntimeError(_("Error opening socket path '%s': %s") %
                               (ginfo.gsocket, e))

        fd = self.sockfd.fileno()
        if fd < 0:
            raise RuntimeError((_("Error opening socket path '%s'") %
                                ginfo.gsocket) + " fd=%s" % fd)
        self.open_fd(fd)

    def open_fd(self, fd, password=None):
        ignore = password
        self.display.open_fd(fd)

    def set_credential_username(self, cred):
        self.display.set_credential(gtkvnc.CREDENTIAL_USERNAME, cred)

    def set_credential_password(self, cred):
        self.display.set_credential(gtkvnc.CREDENTIAL_PASSWORD, cred)


class SpiceViewer(Viewer):
    def __init__(self, console):
        Viewer.__init__(self, console)
        self.spice_session = None
        self.display = None
        self.audio = None
        self.display_channel = None

    def _init_widget(self):
        self.set_grab_keys()
        self.console.refresh_scaling()

        self.display.realize()
        self.display.connect("mouse-grab", lambda src, g: g and self.console.pointer_grabbed(src))
        self.display.connect("mouse-grab", lambda src, g: g or self.console.pointer_ungrabbed(src))

        self.display.connect("focus-in-event",
                             self.console.viewer_focus_changed)
        self.display.connect("focus-out-event",
                             self.console.viewer_focus_changed)

        self.display.show()

    def close(self):
        if self.spice_session is not None:
            self.spice_session.disconnect()
        self.spice_session = None
        self.audio = None
        if self.display:
            self.display.destroy()
        self.display = None
        self.display_channel = None

    def is_open(self):
        return self.spice_session != None

    def _main_channel_event_cb(self, channel, event):
        if event == spice.CHANNEL_CLOSED:
            if self.console:
                self.console.disconnected()
        elif event == spice.CHANNEL_ERROR_AUTH:
            if self.console:
                self.console.activate_auth_page()

    def _channel_open_fd_request(self, channel, tls_ignore):
        if not self.console.tunnels:
            raise SystemError("Got fd request with no configured tunnel!")

        logging.debug("Opening tunnel for channel: %s", channel)
        fd = self.console.tunnels.open_new()
        channel.open_fd(fd)

    def _channel_new_cb(self, session, channel):
        gobject.GObject.connect(channel, "open-fd",
                                self._channel_open_fd_request)

        if type(channel) == spice.MainChannel:
            channel.connect_after("channel-event", self._main_channel_event_cb)
            return

        if type(channel) == spice.DisplayChannel:
            channel_id = channel.get_property("channel-id")

            if channel_id != 0:
                logging.debug("Spice multi-head unsupported")
                return

            self.display_channel = channel
            self.display = spice.Display(self.spice_session, channel_id)
            self.console.window.get_object("console-vnc-viewport").add(self.display)
            self._init_widget()
            self.console.connected()
            return

        if (type(channel) in [spice.PlaybackChannel, spice.RecordChannel] and
            not self.audio):
            self.audio = spice.Audio(self.spice_session)
            return

    def get_desktop_resolution(self):
        if (not self.display_channel or
            not has_property(self.display_channel, "width")):
            return None
        return self.display_channel.get_properties("width", "height")

    def open_host(self, ginfo, password=None):
        host, port = ginfo.get_conn_host()

        uri = "spice://"
        uri += str(host) + "?port=" + str(port)
        logging.debug("spice uri: %s", uri)

        self.spice_session = spice.Session()
        self.spice_session.set_property("uri", uri)
        if password:
            self.spice_session.set_property("password", password)
        gobject.GObject.connect(self.spice_session, "channel-new",
                                self._channel_new_cb)
        self.spice_session.connect()

    def open_fd(self, fd, password=None):
        self.spice_session = spice.Session()
        if password:
            self.spice_session.set_property("password", password)
        gobject.GObject.connect(self.spice_session, "channel-new",
                                self._channel_new_cb)
        self.spice_session.open_fd(fd)

    def set_credential_password(self, cred):
        self.spice_session.set_property("password", cred)
        if self.console.tunnels:
            fd = self.console.tunnels.open_new()
            self.spice_session.open_fd(fd)
        else:
            self.spice_session.connect()

    def get_scaling(self):
        if not has_property(self.display, "scaling"):
            return False
        return self.display.get_property("scaling")

    def set_scaling(self, scaling):
        if not has_property(self.display, "scaling"):
            logging.debug("Spice version doesn't support scaling.")
            return
        self.display.set_property("scaling", scaling)


class vmmConsolePages(vmmGObjectUI):
    def __init__(self, vm, window):
        vmmGObjectUI.__init__(self, None, None)

        self.vm = vm

        self.windowname = "vmm-details"
        self.window = window
        self.topwin = self.widget(self.windowname)
        self.err = vmmErrorDialog(self.topwin)

        self.pointer_is_grabbed = False
        self.change_title()
        self.vm.connect("config-changed", self.change_title)

        # State for disabling modifiers when keyboard is grabbed
        self.accel_groups = gtk.accel_groups_from_object(self.topwin)
        self.gtk_settings_accel = None
        self.gtk_settings_mnemonic = None

        # Initialize display widget
        self.viewer = None
        self.tunnels = None
        self.viewerRetriesScheduled = 0
        self.viewerRetryDelay = 125
        self._viewer_connected = False
        self.viewer_connecting = False
        self.scale_type = self.vm.get_console_scaling()

        # Fullscreen toolbar
        self.send_key_button = None
        self.fs_toolbar = None
        self.fs_drawer = None
        self.keycombo_menu = uihelpers.build_keycombo_menu(self.send_key)
        self.init_fs_toolbar()

        finish_img = gtk.image_new_from_stock(gtk.STOCK_YES,
                                              gtk.ICON_SIZE_BUTTON)
        self.widget("console-auth-login").set_image(finish_img)

        # Make viewer widget background always be black
        black = gtk.gdk.Color(0, 0, 0)
        self.widget("console-vnc-viewport").modify_bg(gtk.STATE_NORMAL,
                                                      black)

        # Signals are added by vmmDetails. Don't use connect_signals here
        # or it changes will be overwritten
        # Set console scaling
        self.add_gconf_handle(
            self.vm.on_console_scaling_changed(self.refresh_scaling))

        scroll = self.widget("console-vnc-scroll")
        scroll.connect("size-allocate", self.scroll_size_allocate)
        self.add_gconf_handle(
            self.config.on_console_accels_changed(self.set_enable_accel))
        self.add_gconf_handle(
            self.config.on_keys_combination_changed(self.grab_keys_changed))

        self.page_changed()

    def is_visible(self):
        if self.topwin.flags() & gtk.VISIBLE:
            return 1
        return 0

    def _cleanup(self):
        self.vm = None

        if self.viewer:
            self.viewer.cleanup()
        self.viewer = None

        self.keycombo_menu.destroy()
        self.keycombo_menu = None
        self.fs_drawer.destroy()
        self.fs_drawer = None
        self.fs_toolbar.destroy()
        self.fs_toolbar = None

    ##########################
    # Initialization helpers #
    ##########################

    def init_fs_toolbar(self):
        scroll = self.widget("console-vnc-scroll")
        pages = self.widget("console-pages")
        pages.remove(scroll)

        self.fs_toolbar = gtk.Toolbar()
        self.fs_toolbar.set_show_arrow(False)
        self.fs_toolbar.set_no_show_all(True)
        self.fs_toolbar.set_style(gtk.TOOLBAR_BOTH_HORIZ)

        # Exit fullscreen button
        button = gtk.ToolButton(gtk.STOCK_LEAVE_FULLSCREEN)
        util.tooltip_wrapper(button, _("Leave fullscreen"))
        button.show()
        self.fs_toolbar.add(button)
        button.connect("clicked", self.leave_fullscreen)

        def keycombo_menu_clicked(src):
            ignore = src
            def menu_location(menu, toolbar):
                ignore = menu
                x, y = toolbar.window.get_origin()
                ignore, height = toolbar.window.get_size()

                return x, y + height, True

            self.keycombo_menu.popup(None, None, menu_location, 0,
                                     gtk.get_current_event_time(),
                                     self.fs_toolbar)

        self.send_key_button = gtk.ToolButton()
        self.send_key_button.set_icon_name(
                                "preferences-desktop-keyboard-shortcuts")
        util.tooltip_wrapper(self.send_key_button, _("Send key combination"))
        self.send_key_button.show_all()
        self.send_key_button.connect("clicked", keycombo_menu_clicked)
        self.fs_toolbar.add(self.send_key_button)

        self.fs_drawer = AutoDrawer()
        self.fs_drawer.set_active(False)
        self.fs_drawer.set_over(self.fs_toolbar)
        self.fs_drawer.set_under(scroll)
        self.fs_drawer.set_offset(-1)
        self.fs_drawer.set_fill(False)
        self.fs_drawer.set_overlap_pixels(1)
        self.fs_drawer.set_nooverlap_pixels(0)
        self.fs_drawer.show_all()

        pages.add(self.fs_drawer)

    def change_title(self, ignore1=None):
        title = self.vm.get_name() + " " + _("Virtual Machine")

        if self.pointer_is_grabbed and self.viewer:
            keystr = self.viewer.get_grab_keys()
            keymsg = _("Press %s to release pointer.") % keystr

            title = keymsg + " " + title

        self.topwin.set_title(title)

    def grab_keyboard(self, do_grab):
        if self.viewer and not self.viewer.need_keygrab:
            return

        if (not do_grab or
            not self.viewer or
            not self.viewer.display):
            gtk.gdk.keyboard_ungrab()
        else:
            gtk.gdk.keyboard_grab(self.viewer.display.window)

    def viewer_focus_changed(self, ignore1=None, ignore2=None):
        has_focus = (self.viewer and
                     self.viewer.display and
                     self.viewer.display.get_property("has-focus"))
        force_accel = self.config.get_console_accels()

        if force_accel:
            self._enable_modifiers()
        elif has_focus and self.viewer_connected:
            self._disable_modifiers()
        else:
            self._enable_modifiers()

        self.grab_keyboard(has_focus)

    def pointer_grabbed(self, src_ignore):
        self.pointer_is_grabbed = True
        self.change_title()

    def pointer_ungrabbed(self, src_ignore):
        self.pointer_is_grabbed = False
        self.change_title()

    def _disable_modifiers(self):
        if self.gtk_settings_accel is not None:
            return

        for g in self.accel_groups:
            self.topwin.remove_accel_group(g)

        settings = gtk.settings_get_default()
        self.gtk_settings_accel = settings.get_property('gtk-menu-bar-accel')
        settings.set_property('gtk-menu-bar-accel', None)

        if has_property(settings, "gtk-enable-mnemonics"):
            self.gtk_settings_mnemonic = settings.get_property(
                                                        "gtk-enable-mnemonics")
            settings.set_property("gtk-enable-mnemonics", False)

    def _enable_modifiers(self):
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

    def grab_keys_changed(self,
                          ignore1=None, ignore2=None,
                          ignore3=None, ignore4=None):
        self.viewer.set_grab_keys()

    def set_enable_accel(self, ignore=None, ignore1=None,
                         ignore2=None, ignore3=None):
        # Make sure modifiers are up to date
        self.viewer_focus_changed()

    def refresh_scaling(self, ignore1=None, ignore2=None, ignore3=None,
                        ignore4=None):
        self.scale_type = self.vm.get_console_scaling()
        self.widget("details-menu-view-scale-always").set_active(
            self.scale_type == self.config.CONSOLE_SCALE_ALWAYS)
        self.widget("details-menu-view-scale-never").set_active(
            self.scale_type == self.config.CONSOLE_SCALE_NEVER)
        self.widget("details-menu-view-scale-fullscreen").set_active(
            self.scale_type == self.config.CONSOLE_SCALE_FULLSCREEN)

        self.update_scaling()

    def set_scale_type(self, src):
        if not src.get_active():
            return

        if src == self.widget("details-menu-view-scale-always"):
            self.scale_type = self.config.CONSOLE_SCALE_ALWAYS
        elif src == self.widget("details-menu-view-scale-fullscreen"):
            self.scale_type = self.config.CONSOLE_SCALE_FULLSCREEN
        elif src == self.widget("details-menu-view-scale-never"):
            self.scale_type = self.config.CONSOLE_SCALE_NEVER

        self.vm.set_console_scaling(self.scale_type)
        self.update_scaling()

    def update_scaling(self):
        if not self.viewer:
            return

        curscale = self.viewer.get_scaling()
        fs = self.widget("control-fullscreen").get_active()
        vnc_scroll = self.widget("console-vnc-scroll")

        if (self.scale_type == self.config.CONSOLE_SCALE_NEVER
            and curscale == True):
            self.viewer.set_scaling(False)
        elif (self.scale_type == self.config.CONSOLE_SCALE_ALWAYS
              and curscale == False):
            self.viewer.set_scaling(True)
        elif (self.scale_type == self.config.CONSOLE_SCALE_FULLSCREEN
              and curscale != fs):
            self.viewer.set_scaling(fs)

        # Refresh viewer size
        vnc_scroll.queue_resize()

    def auth_login(self, ignore):
        self.set_credentials()
        self.activate_viewer_page()

    def toggle_fullscreen(self, src):
        do_fullscreen = src.get_active()
        self._change_fullscreen(do_fullscreen)

    def leave_fullscreen(self, ignore=None):
        self._change_fullscreen(False)

    def _change_fullscreen(self, do_fullscreen):
        self.widget("control-fullscreen").set_active(do_fullscreen)

        if do_fullscreen:
            self.topwin.fullscreen()
            self.fs_toolbar.show()
            self.fs_drawer.set_active(True)
            self.widget("toolbar-box").hide()
            self.widget("details-menubar").hide()
        else:
            self.fs_toolbar.hide()
            self.fs_drawer.set_active(False)
            self.topwin.unfullscreen()

            if self.widget("details-menu-view-toolbar").get_active():
                self.widget("toolbar-box").show()
            self.widget("details-menubar").show()

        self.update_scaling()

    def size_to_vm(self, src_ignore):
        # Resize the console to best fit the VM resolution
        if not self.viewer:
            return
        if not self.viewer.get_desktop_resolution():
            return

        w, h = self.viewer.get_desktop_resolution()
        self.topwin.unmaximize()
        self.topwin.resize(1, 1)
        self.queue_scroll_resize_helper(w, h)

    def send_key(self, src, keys):
        ignore = src

        if keys != None:
            self.viewer.send_keys(keys)


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

    def close_viewer(self):
        viewport = self.widget("console-vnc-viewport")
        if self.viewer is None:
            return

        v = self.viewer # close_viewer() can be reentered
        self.viewer = None
        w = v.display

        if w and w in viewport.get_children():
            viewport.remove(w)

        v.close()
        self.viewer_connected = False
        self.leave_fullscreen()

    def update_widget_states(self, vm, status_ignore):
        runable = vm.is_runable()
        pages   = self.widget("console-pages")
        page    = pages.get_current_page()

        if runable:
            if page != PAGE_UNAVAILABLE:
                pages.set_current_page(PAGE_UNAVAILABLE)

            self.view_vm_status()
            return

        elif page in [PAGE_UNAVAILABLE, PAGE_VIEWER]:
            if self.viewer and self.viewer.is_open():
                self.activate_viewer_page()
            else:
                self.viewerRetriesScheduled = 0
                self.viewerRetryDelay = 125
                self.try_login()

        return

    ###################
    # Page Navigation #
    ###################

    def activate_unavailable_page(self, msg):
        """
        This function is passed to serialcon.py at least, so change
        with care
        """
        self.close_viewer()
        self.widget("console-pages").set_current_page(PAGE_UNAVAILABLE)
        self.widget("details-menu-vm-screenshot").set_sensitive(False)
        self.widget("console-unavailable").set_label("<b>" + msg + "</b>")

    def activate_auth_page(self, withPassword=True, withUsername=False):
        (pw, username) = self.config.get_console_password(self.vm)
        self.widget("details-menu-vm-screenshot").set_sensitive(False)

        if withPassword:
            self.widget("console-auth-password").show()
            self.widget("label-auth-password").show()
        else:
            self.widget("console-auth-password").hide()
            self.widget("label-auth-password").hide()

        if withUsername:
            self.widget("console-auth-username").show()
            self.widget("label-auth-username").show()
        else:
            self.widget("console-auth-username").hide()
            self.widget("label-auth-username").hide()

        self.widget("console-auth-username").set_text(username)
        self.widget("console-auth-password").set_text(pw)

        if self.config.has_keyring():
            self.widget("console-auth-remember").set_sensitive(True)
            if pw != "" or username != "":
                self.widget("console-auth-remember").set_active(True)
            else:
                self.widget("console-auth-remember").set_active(False)
        else:
            self.widget("console-auth-remember").set_sensitive(False)
        self.widget("console-pages").set_current_page(PAGE_AUTHENTICATE)
        if withUsername:
            self.widget("console-auth-username").grab_focus()
        else:
            self.widget("console-auth-password").grab_focus()


    def activate_viewer_page(self):
        self.widget("console-pages").set_current_page(PAGE_VIEWER)
        self.widget("details-menu-vm-screenshot").set_sensitive(True)
        if self.viewer and self.viewer.display:
            self.viewer.display.grab_focus()

    def page_changed(self, ignore1=None, ignore2=None, ignore3=None):
        self.set_allow_fullscreen()

    def set_allow_fullscreen(self):
        cpage = self.widget("console-pages").get_current_page()
        dpage = self.widget("details-pages").get_current_page()

        allow_fullscreen = (dpage == 0 and
                            cpage == PAGE_VIEWER and
                            self.viewer_connected)

        self.widget("control-fullscreen").set_sensitive(allow_fullscreen)
        self.widget("details-menu-view-fullscreen").set_sensitive(allow_fullscreen)

    def disconnected(self):
        errout = ""
        if self.tunnels is not None:
            errout = self.tunnels.get_err_output()
            self.tunnels.close_all()
            self.tunnels = None

        self.close_viewer()
        logging.debug("Viewer disconnected")

        # Make sure modifiers are set correctly
        self.viewer_focus_changed()

        if (self.skip_connect_attempt() or
            self.guest_not_avail()):
            # Exit was probably for legitimate reasons
            self.view_vm_status()
            return

        error = _("Error: viewer connection to hypervisor host got refused "
                  "or disconnected!")
        if errout:
            logging.debug("Error output from closed console: %s", errout)
            error += "\n\nError: %s" % errout

        self.activate_unavailable_page(error)

    def _set_viewer_connected(self, val):
        self._viewer_connected = val
        self.set_allow_fullscreen()
    def _get_viewer_connected(self):
        return self._viewer_connected
    viewer_connected = property(_get_viewer_connected, _set_viewer_connected)

    def connected(self):
        self.viewer_connected = True
        logging.debug("Viewer connected")
        self.activate_viewer_page()

        # Had a succesfull connect, so reset counters now
        self.viewerRetriesScheduled = 0
        self.viewerRetryDelay = 125

        # Make sure modifiers are set correctly
        self.viewer_focus_changed()

    def schedule_retry(self):
        if self.viewerRetriesScheduled >= 10:
            logging.error("Too many connection failures, not retrying again")
            return

        self.timeout_add(self.viewerRetryDelay, self.try_login)

        if self.viewerRetryDelay < 2000:
            self.viewerRetryDelay = self.viewerRetryDelay * 2

    def skip_connect_attempt(self):
        return (self.viewer or
                not self.is_visible())

    def guest_not_avail(self):
        return (self.vm.is_shutoff() or self.vm.is_crashed())

    def try_login(self, src_ignore=None):
        if self.viewer_connecting:
            return

        try:
            self.viewer_connecting = True
            self._try_login()
        finally:
            self.viewer_connecting = False

    def _try_login(self):
        if self.skip_connect_attempt():
            # Don't try and login for these cases
            return

        if self.guest_not_avail():
            # Guest isn't running, schedule another try
            self.activate_unavailable_page(_("Guest not running"))
            self.schedule_retry()
            return

        ginfo = None
        try:
            gdevs = self.vm.get_graphics_devices()
            gdev = gdevs and gdevs[0] or None
            if gdev:
                ginfo = ConnectionInfo(self.vm.conn, gdev)
        except Exception, e:
            # We can fail here if VM is destroyed: xen is a bit racy
            # and can't handle domain lookups that soon after
            logging.exception("Getting graphics console failed: %s", str(e))
            return

        if ginfo is None:
            logging.debug("No graphics configured for guest")
            self.activate_unavailable_page(
                            _("Graphical console not configured for guest"))
            return

        if ginfo.gtype not in self.config.embeddable_graphics():
            logging.debug("Don't know how to show graphics type '%s' "
                          "disabling console page", ginfo.gtype)

            msg = (_("Cannot display graphical console type '%s'")
                     % ginfo.gtype)
            if ginfo.gtype == "spice":
                msg += ":\n %s" % self.config.get_spice_error()

            self.activate_unavailable_page(msg)
            return

        if ginfo.console_active():
            self.activate_unavailable_page(
                            _("Graphical console is not yet active for guest"))
            self.schedule_retry()
            return

        self.activate_unavailable_page(
                _("Connecting to graphical console for guest"))

        logging.debug("Starting connect process for %s", ginfo.logstring())
        try:
            if ginfo.gtype == "vnc":
                self.viewer = VNCViewer(self)
                self.widget("console-vnc-viewport").add(self.viewer.display)
                self.viewer.init_widget()
            elif ginfo.gtype == "spice":
                self.viewer = SpiceViewer(self)

            self.set_enable_accel()

            if ginfo.need_tunnel():
                if self.tunnels:
                    # Tunnel already open, no need to continue
                    return

                self.tunnels = Tunnels(ginfo)
                self.viewer.open_fd(self.tunnels.open_new())
            else:
                self.viewer.open_host(ginfo)

        except Exception, e:
            logging.exception("Error connection to graphical console")
            self.activate_unavailable_page(
                    _("Error connecting to graphical console") + ":\n%s" % e)

    def set_credentials(self, src_ignore=None):
        passwd = self.widget("console-auth-password")
        if passwd.flags() & gtk.VISIBLE:
            self.viewer.set_credential_password(passwd.get_text())
        username = self.widget("console-auth-username")
        if username.flags() & gtk.VISIBLE:
            self.viewer.set_credential_username(username.get_text())

        if self.widget("console-auth-remember").get_active():
            self.config.set_console_password(self.vm, passwd.get_text(),
                                             username.get_text())

    def queue_scroll_resize_helper(self, w, h):
        """
        Resize the VNC container widget to the requested size. The new size
        isn't a hard requirment so the user can still shrink the window
        again, as opposed to set_size_request
        """
        widget = self.widget("console-vnc-scroll")
        signal_holder = []

        def restore_scroll(src):
            is_scale = self.viewer.get_scaling()

            if is_scale:
                w_policy = gtk.POLICY_NEVER
                h_policy = gtk.POLICY_NEVER
            else:
                w_policy = gtk.POLICY_AUTOMATIC
                h_policy = gtk.POLICY_AUTOMATIC

            src.set_policy(w_policy, h_policy)
            return False

        def unset_cb(src):
            src.queue_resize_no_redraw()
            self.idle_add(restore_scroll, src)
            return False

        def request_cb(src, req):
            signal_id = signal_holder[0]
            req.width = w
            req.height = h

            src.disconnect(signal_id)

            self.idle_add(unset_cb, widget)
            return False

        # Disable scroll bars while we resize, since resizing to the VM's
        # dimensions can erroneously show scroll bars when they aren't needed
        widget.set_policy(gtk.POLICY_NEVER, gtk.POLICY_NEVER)

        signal_id = widget.connect("size-request", request_cb)
        signal_holder.append(signal_id)

        widget.queue_resize()

    def scroll_size_allocate(self, src_ignore, req):
        if not self.viewer or not self.viewer.get_desktop_resolution():
            return

        scroll = self.widget("console-vnc-scroll")
        is_scale = self.viewer.get_scaling()

        dx = 0
        dy = 0
        align_ratio = float(req.width) / float(req.height)

        desktop_w, desktop_h = self.viewer.get_desktop_resolution()
        if desktop_h == 0:
            return
        desktop_ratio = float(desktop_w) / float(desktop_h)

        if not is_scale:
            # Scaling disabled is easy, just force the VNC widget size. Since
            # we are inside a scrollwindow, it shouldn't cause issues.
            scroll.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
            self.viewer.display.set_size_request(desktop_w, desktop_h)
            return

        # Make sure we never show scrollbars when scaling
        scroll.set_policy(gtk.POLICY_NEVER, gtk.POLICY_NEVER)

        # Make sure there is no hard size requirement so we can scale down
        self.viewer.display.set_size_request(-1, -1)

        # Make sure desktop aspect ratio is maintained
        if align_ratio > desktop_ratio:
            desktop_w = int(req.height * desktop_ratio)
            desktop_h = req.height
            dx = (req.width - desktop_w) / 2

        else:
            desktop_w = req.width
            desktop_h = int(req.width / desktop_ratio)
            dy = (req.height - desktop_h) / 2

        viewer_alloc = gtk.gdk.Rectangle(x=dx,
                                         y=dy,
                                         width=desktop_w,
                                         height=desktop_h)

        self.viewer.display.size_allocate(viewer_alloc)

vmmGObjectUI.type_register(vmmConsolePages)

# -*- coding: utf-8 -*-
#
# Copyright (C) 2006-2008, 2013 Red Hat, Inc.
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

from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GtkVnc
from gi.repository import SpiceClientGtk
from gi.repository import SpiceClientGLib

import libvirt

import logging
import socket

from .autodrawer import AutoDrawer
from .baseclass import vmmGObjectUI, vmmGObject
from .details import DETAILS_PAGE_CONSOLE
from .serialcon import vmmSerialConsole
from .sshtunnels import ConnectionInfo, SSHTunnels

# Console pages
(CONSOLE_PAGE_UNAVAILABLE,
 CONSOLE_PAGE_AUTHENTICATE,
 CONSOLE_PAGE_VIEWER,
 CONSOLE_PAGE_OFFSET) = range(4)


def _has_property(obj, setting):
    try:
        obj.get_property(setting)
    except TypeError:
        return False
    return True


##################################
# VNC/Spice abstraction handling #
##################################

class Viewer(vmmGObject):
    def __init__(self, console):
        vmmGObject.__init__(self)
        self.console = console
        self._display = None

    def close(self):
        raise NotImplementedError()

    def _cleanup(self):
        self.close()

        if self._display:
            self._display.destroy()
        self._display = None
        self.console = None

    def grab_focus(self):
        if self._display:
            self._display.grab_focus()
    def has_focus(self):
        return self._display and self._display.get_property("has-focus")
    def set_size_request(self, *args, **kwargs):
        return self._display.set_size_request(*args, **kwargs)
    def size_allocate(self, *args, **kwargs):
        return self._display.size_allocate(*args, **kwargs)
    def get_visible(self):
        return self._display and self._display.get_visible()

    def get_pixbuf(self):
        return self._display.get_pixbuf()

    def open_ginfo(self, ginfo):
        if ginfo.need_tunnel():
            self.open_fd(self.console.tunnels.open_new())
        else:
            self.open_host(ginfo)

    def get_grab_keys(self):
        raise NotImplementedError()

    def set_grab_keys(self):
        raise NotImplementedError()

    def send_keys(self, keys):
        raise NotImplementedError()

    def set_keyboard_grab_default(self):
        raise NotImplementedError()

    def open_host(self, ginfo):
        raise NotImplementedError()

    def open_fd(self, fd):
        raise NotImplementedError()

    def get_desktop_resolution(self):
        raise NotImplementedError()

    def has_usb_redirection(self):
        return False
    def has_agent(self):
        return False
    def set_resizeguest(self, val):
        ignore = val
    def get_resizeguest(self):
        return False


class VNCViewer(Viewer):
    viewer_type = "vnc"

    def __init__(self, console):
        Viewer.__init__(self, console)
        self._display = GtkVnc.Display.new()
        self.sockfd = None

        # Last noticed desktop resolution
        self.desktop_resolution = None

        self._tunnel_unlocked = False

        self._init_widget()

    def _init_widget(self):
        self.console.widget("console-gfx-viewport").add(self._display)

        self.set_grab_keys()
        self.set_keyboard_grab_default()

        self._display.realize()

        # Make sure viewer doesn't force resize itself
        self._display.set_force_size(False)

        self.console.sync_scaling_with_display()
        self.console.refresh_resizeguest_from_settings()

        self._display.set_pointer_grab(True)

        self._display.connect("size-allocate",
                             self.console.viewer_allocate_cb)

        self._display.connect("vnc-pointer-grab", self.console.pointer_grabbed)
        self._display.connect("vnc-pointer-ungrab",
                             self.console.pointer_ungrabbed)
        self._display.connect("vnc-auth-credential", self._auth_credential)
        self._display.connect("vnc-initialized", self._connected_cb)
        self._display.connect("vnc-disconnected", self._disconnected_cb)
        self._display.connect("vnc-desktop-resize", self._desktop_resize)
        self._display.connect("focus-in-event",
                             self.console.viewer_focus_changed)
        self._display.connect("focus-out-event",
                             self.console.viewer_focus_changed)

        self._display.show()

    def _unlock_tunnel(self):
        if self.console.tunnels and not self._tunnel_unlocked:
            self.console.tunnels.unlock()
            self._tunnel_unlocked = True

    def _connected_cb(self, ignore):
        self._unlock_tunnel()
        self.console.connected()

    def _disconnected_cb(self, ignore):
        self._unlock_tunnel()
        self.console.disconnected()

    def get_grab_keys(self):
        return self._display.get_grab_keys().as_string()

    def set_grab_keys(self):
        try:
            keys = self.config.get_keys_combination()
            if not keys:
                return

            try:
                keys = [int(k) for k in keys.split(',')]
            except:
                logging.debug("Error in grab_keys configuration in Gsettings",
                              exc_info=True)
                return

            seq = GtkVnc.GrabSequence.new(keys)
            self._display.set_grab_keys(seq)
        except Exception, e:
            logging.debug("Error when getting the grab keys combination: %s",
                          str(e))

    def send_keys(self, keys):
        return self._display.send_keys([Gdk.keyval_from_name(k) for k in keys])

    def set_keyboard_grab_default(self):
        self._display.set_keyboard_grab(self.config.get_keyboard_grab_default())

    def _desktop_resize(self, src_ignore, w, h):
        self.desktop_resolution = (w, h)
        self.console.widget("console-gfx-scroll").queue_resize()

    def get_desktop_resolution(self):
        return self.desktop_resolution

    def _auth_credential(self, src_ignore, credList):
        values = []
        for idx in range(int(credList.n_values)):
            values.append(credList.get_nth(idx))

        for cred in values:
            if cred in [GtkVnc.DisplayCredential.PASSWORD,
                        GtkVnc.DisplayCredential.USERNAME,
                        GtkVnc.DisplayCredential.CLIENTNAME]:
                continue

            self.console.err.show_err(
                summary=_("Unable to provide requested credentials to "
                          "the VNC server"),
                details=(_("The credential type %s is not supported") %
                         (str(cred))),
                title=_("Unable to authenticate"))

            # schedule_retry will error out
            self.console.viewerRetriesScheduled = 10
            self.close()
            self.console.activate_unavailable_page(
                            _("Unsupported console authentication type"))
            return

        withUsername = False
        withPassword = False
        for cred in values:
            logging.debug("Got credential request %s", cred)
            if cred == GtkVnc.DisplayCredential.PASSWORD:
                withPassword = True
            elif cred == GtkVnc.DisplayCredential.USERNAME:
                withUsername = True
            elif cred == GtkVnc.DisplayCredential.CLIENTNAME:
                self._display.set_credential(cred, "libvirt-vnc")

        if withUsername or withPassword:
            self.console.activate_auth_page(withPassword, withUsername)

    def get_scaling(self):
        return self._display.get_scaling()

    def set_scaling(self, scaling):
        return self._display.set_scaling(scaling)

    def close(self):
        self._display.close()
        if not self.sockfd:
            return

        self.sockfd.close()
        self.sockfd = None

    def is_open(self):
        return self._display.is_open()

    def open_host(self, ginfo):
        host, port, ignore = ginfo.get_conn_host()

        if not ginfo.gsocket:
            logging.debug("VNC connection to %s:%s", host, port)
            self._display.open_host(host, port)
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

    def open_fd(self, fd):
        self._display.open_fd(fd)

    def set_credential_username(self, cred):
        self._display.set_credential(GtkVnc.DisplayCredential.USERNAME, cred)

    def set_credential_password(self, cred):
        self._display.set_credential(GtkVnc.DisplayCredential.PASSWORD, cred)


class SpiceViewer(Viewer):
    viewer_type = "spice"

    def __init__(self, console):
        Viewer.__init__(self, console)
        self.spice_session = None
        self._display = None
        self.audio = None
        self.main_channel = None
        self._main_channel_hids = []
        self._display_channel = None
        self.usbdev_manager = None

    def _init_widget(self):
        self.set_grab_keys()
        self.set_keyboard_grab_default()
        self.console.sync_scaling_with_display()
        self.console.refresh_resizeguest_from_settings()

        self._display.realize()

        self._display.connect("size-allocate",
                             self.console.viewer_allocate_cb)

        self._display.connect("mouse-grab",
            lambda src, g: g and self.console.pointer_grabbed(src))
        self._display.connect("mouse-grab",
            lambda src, g: g or self.console.pointer_ungrabbed(src))

        self._display.connect("focus-in-event",
                             self.console.viewer_focus_changed)
        self._display.connect("focus-out-event",
                             self.console.viewer_focus_changed)

        self._display.show()

    def get_grab_keys(self):
        return self._display.get_grab_keys().as_string()

    def set_grab_keys(self):
        try:
            keys = self.config.get_keys_combination()
            if not keys:
                return

            try:
                keys = [int(k) for k in keys.split(',')]
            except:
                logging.debug("Error in grab_keys configuration in Gsettings",
                              exc_info=True)
                return

            seq = SpiceClientGtk.GrabSequence.new(keys)
            self._display.set_grab_keys(seq)
        except Exception, e:
            logging.debug("Error when getting the grab keys combination: %s",
                          str(e))

    def send_keys(self, keys):
        return self._display.send_keys([Gdk.keyval_from_name(k) for k in keys],
                                      SpiceClientGtk.DisplayKeyEvent.CLICK)

    def set_keyboard_grab_default(self):
        self._display.set_property("grab-keyboard",
            self.config.get_keyboard_grab_default())

    def _close_main_channel(self):
        for i in self._main_channel_hids:
            self.main_channel.handler_disconnect(i)
        self._main_channel_hids = []

        self.main_channel = None

    def close(self):
        if self.spice_session is not None:
            self.spice_session.disconnect()
        self.spice_session = None
        self.audio = None
        if self._display:
            self._display.destroy()
        self._display = None
        self._display_channel = None

        self._close_main_channel()
        self.usbdev_manager = None

    def is_open(self):
        return self.spice_session is not None

    def _main_channel_event_cb(self, channel, event):
        if not self.console:
            return

        if event == SpiceClientGLib.ChannelEvent.CLOSED:
            self.console.disconnected()
        elif event == SpiceClientGLib.ChannelEvent.ERROR_AUTH:
            self.console.activate_auth_page()
            self._close_main_channel()
        elif event in [SpiceClientGLib.ChannelEvent.ERROR_CONNECT,
                       SpiceClientGLib.ChannelEvent.ERROR_IO,
                       SpiceClientGLib.ChannelEvent.ERROR_LINK,
                       SpiceClientGLib.ChannelEvent.ERROR_TLS]:
            logging.debug("Spice channel event error: %s", event)
            self.console.disconnected()

    def _fd_channel_event_cb(self, channel, event):
        # When we see any event from the channel, release the
        # associated tunnel lock
        channel.disconnect_by_func(self._fd_channel_event_cb)
        self.console.tunnels.unlock()

    def _channel_open_fd_request(self, channel, tls_ignore):
        if not self.console.tunnels:
            raise SystemError("Got fd request with no configured tunnel!")

        logging.debug("Opening tunnel for channel: %s", channel)
        channel.connect_after("channel-event", self._fd_channel_event_cb)

        fd = self.console.tunnels.open_new()
        channel.open_fd(fd)

    def _channel_new_cb(self, session, channel):
        GObject.GObject.connect(channel, "open-fd",
                                self._channel_open_fd_request)

        if (type(channel) == SpiceClientGLib.MainChannel and
            not self.main_channel):
            if self.console.tunnels:
                self.console.tunnels.unlock()
            self.main_channel = channel
            hid = self.main_channel.connect_after("channel-event",
                self._main_channel_event_cb)
            self._main_channel_hids.append(hid)
            hid = self.main_channel.connect_after("notify::agent-connected",
                self._agent_connected_cb)
            self._main_channel_hids.append(hid)

        elif (type(channel) == SpiceClientGLib.DisplayChannel and
            not self._display):
            channel_id = channel.get_property("channel-id")

            if channel_id != 0:
                logging.debug("Spice multi-head unsupported")
                return

            self._display_channel = channel
            self._display = SpiceClientGtk.Display.new(self.spice_session,
                                                      channel_id)
            self.console.widget("console-gfx-viewport").add(self._display)
            self._init_widget()
            self.console.connected()

        elif (type(channel) in [SpiceClientGLib.PlaybackChannel,
                                SpiceClientGLib.RecordChannel] and
            not self.audio):
            self.audio = SpiceClientGLib.Audio.get(self.spice_session, None)

    def get_desktop_resolution(self):
        if (not self._display_channel or
            not _has_property(self._display_channel, "width")):
            return None
        return self._display_channel.get_properties("width", "height")

    def has_agent(self):
        if (not self.main_channel or
            not _has_property(self.main_channel, "agent-connected")):
            return False
        ret = self.main_channel.get_property("agent-connected")
        return ret

    def _agent_connected_cb(self, src, val):
        self.console.refresh_resizeguest_from_settings()

    def _create_spice_session(self):
        self.spice_session = SpiceClientGLib.Session()
        SpiceClientGLib.set_session_option(self.spice_session)
        gtk_session = SpiceClientGtk.GtkSession.get(self.spice_session)
        gtk_session.set_property("auto-clipboard", True)

        GObject.GObject.connect(self.spice_session, "channel-new",
                                self._channel_new_cb)

        self.usbdev_manager = SpiceClientGLib.UsbDeviceManager.get(
                                    self.spice_session)
        self.usbdev_manager.connect("auto-connect-failed",
                                    self._usbdev_redirect_error)
        self.usbdev_manager.connect("device-error",
                                    self._usbdev_redirect_error)

        autoredir = self.config.get_auto_redirection()
        if autoredir:
            gtk_session.set_property("auto-usbredir", True)

    def open_host(self, ginfo):
        host, port, tlsport = ginfo.get_conn_host()
        self._create_spice_session()

        self.spice_session.set_property("host", str(host))
        if port:
            self.spice_session.set_property("port", str(port))
        if tlsport:
            self.spice_session.set_property("tls-port", str(tlsport))

        self.spice_session.connect()

    def open_fd(self, fd):
        self._create_spice_session()
        self.spice_session.open_fd(fd)

    def set_credential_password(self, cred):
        self.spice_session.set_property("password", cred)
        if self.console.tunnels:
            fd = self.console.tunnels.open_new()
            self.spice_session.open_fd(fd)
        else:
            self.spice_session.connect()

    def get_scaling(self):
        if not _has_property(self._display, "scaling"):
            return False
        return self._display.get_property("scaling")

    def set_scaling(self, scaling):
        if not _has_property(self._display, "scaling"):
            logging.debug("Spice version doesn't support scaling.")
            return
        self._display.set_property("scaling", scaling)

    def set_resizeguest(self, val):
        if self._display:
            self._display.set_property("resize-guest", val)

    def get_resizeguest(self):
        if self._display:
            return self._display.get_property("resize-guest")
        return False

    def _usbdev_redirect_error(self,
                             spice_usbdev_widget, spice_usb_device,
                             errstr):
        ignore_widget = spice_usbdev_widget
        ignore_device = spice_usb_device

        error = self.console.err
        error.show_err(_("USB redirection error"),
                         text2=str(errstr),
                         modal=True)

    def get_usb_widget(self):

        # The @format positional parameters are the following:
        # 1 '%s' manufacturer
        # 2 '%s' product
        # 3 '%s' descriptor (a [vendor_id:product_id] string)
        # 4 '%d' bus
        # 5 '%d' address

        usb_device_description_fmt = _("%s %s %s at %d-%d")

        if not self.spice_session:
            return

        usbwidget = SpiceClientGtk.UsbDeviceWidget.new(
                                                self.spice_session,
                                                usb_device_description_fmt)
        usbwidget.connect("connect-failed", self._usbdev_redirect_error)
        return usbwidget

    def has_usb_redirection(self):
        if not self.spice_session or not self.usbdev_manager:
            return False

        for c in self.spice_session.get_channels():
            if c.__class__ is SpiceClientGLib.UsbredirChannel:
                return True
        return False


#####################
# UI logic handling #
#####################

class vmmConsolePages(vmmGObjectUI):
    def __init__(self, vm, builder, topwin):
        vmmGObjectUI.__init__(self, None, None, builder=builder, topwin=topwin)

        self.vm = vm
        self.pointer_is_grabbed = False
        self.change_title()
        self.vm.connect("config-changed", self.change_title)
        self.force_resize = False

        # State for disabling modifiers when keyboard is grabbed
        self.accel_groups = Gtk.accel_groups_from_object(self.topwin)
        self.gtk_settings_accel = None
        self.gtk_settings_mnemonic = None

        # Initialize display widget
        self.viewer = None
        self.tunnels = None
        self.viewerRetriesScheduled = 0
        self.viewerRetryDelay = 125
        self._viewer_connected = False
        self.viewer_connecting = False

        # Fullscreen toolbar
        self.send_key_button = None
        self.fs_toolbar = None
        self.fs_drawer = None
        self.keycombo_menu = self.build_keycombo_menu(self.send_key)
        self.init_fs_toolbar()

        # Make viewer widget background always be black
        black = Gdk.Color(0, 0, 0)
        self.widget("console-gfx-viewport").modify_bg(Gtk.StateType.NORMAL,
                                                      black)

        self.serial_tabs = []
        self.last_gfx_page = 0
        self._init_menus()

        # Signals are added by vmmDetails. Don't use connect_signals here
        # or it changes will be overwritten

        self.refresh_scaling_from_settings()
        self.add_gsettings_handle(
            self.vm.on_console_scaling_changed(
                self.refresh_scaling_from_settings))
        self.refresh_resizeguest_from_settings()
        self.add_gsettings_handle(
            self.vm.on_console_resizeguest_changed(
                self.refresh_resizeguest_from_settings))

        scroll = self.widget("console-gfx-scroll")
        scroll.connect("size-allocate", self.scroll_size_allocate)
        self.add_gsettings_handle(
            self.config.on_console_accels_changed(self.set_enable_accel))
        self.add_gsettings_handle(
            self.config.on_keys_combination_changed(self.grab_keys_changed))
        self.add_gsettings_handle(
            self.config.on_keyboard_grab_default_changed(
            self.keyboard_grab_default_changed))

        self.page_changed()


    def is_visible(self):
        if self.topwin:
            return self.topwin.get_visible()
        else:
            return False

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

        for serial in self.serial_tabs:
            serial.cleanup()
        self.serial_tabs = []


    ##########################
    # Initialization helpers #
    ##########################

    @staticmethod
    def build_keycombo_menu(cb):
        # Shared with vmmDetails
        menu = Gtk.Menu()

        def make_item(name, combo):
            item = Gtk.MenuItem.new_with_mnemonic(name)
            item.connect("activate", cb, combo)

            menu.add(item)

        make_item("Ctrl+Alt+_Backspace", ["Control_L", "Alt_L", "BackSpace"])
        make_item("Ctrl+Alt+_Delete", ["Control_L", "Alt_L", "Delete"])
        menu.add(Gtk.SeparatorMenuItem())

        for i in range(1, 13):
            make_item("Ctrl+Alt+F_%d" % i, ["Control_L", "Alt_L", "F%d" % i])
        menu.add(Gtk.SeparatorMenuItem())

        make_item("_Printscreen", ["Print"])

        menu.show_all()
        return menu

    def init_fs_toolbar(self):
        scroll = self.widget("console-gfx-scroll")
        pages = self.widget("console-pages")
        pages.remove(scroll)

        self.fs_toolbar = Gtk.Toolbar()
        self.fs_toolbar.set_show_arrow(False)
        self.fs_toolbar.set_no_show_all(True)
        self.fs_toolbar.set_style(Gtk.ToolbarStyle.BOTH_HORIZ)

        # Exit fullscreen button
        button = Gtk.ToolButton.new_from_stock(Gtk.STOCK_LEAVE_FULLSCREEN)
        button.set_tooltip_text(_("Leave fullscreen"))
        button.show()
        self.fs_toolbar.add(button)
        button.connect("clicked", self.leave_fullscreen)

        def keycombo_menu_clicked(src):
            ignore = src
            def menu_location(menu, toolbar):
                ignore = menu
                ignore, x, y = toolbar.get_window().get_origin()
                height = toolbar.get_window().get_height()

                return x, y + height, True

            self.keycombo_menu.popup(None, None, menu_location,
                                     self.fs_toolbar, 0,
                                     Gtk.get_current_event_time())

        self.send_key_button = Gtk.ToolButton()
        self.send_key_button.set_icon_name(
                                "preferences-desktop-keyboard-shortcuts")
        self.send_key_button.set_tooltip_text(_("Send key combination"))
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
        self.fs_drawer.period = 20
        self.fs_drawer.step = .1

        self.fs_drawer.show_all()

        pages.add(self.fs_drawer)

    def _init_menus(self):
        # Serial list menu
        smenu = Gtk.Menu()
        smenu.connect("show", self.populate_serial_menu)
        self.widget("details-menu-view-serial-list").set_submenu(smenu)

    def change_title(self, ignore1=None):
        title = self.vm.get_name() + " " + _("Virtual Machine")

        if self.pointer_is_grabbed and self.viewer:
            keystr = self.viewer.get_grab_keys()
            keymsg = _("Press %s to release pointer.") % keystr

            title = keymsg + " " + title

        self.topwin.set_title(title)

    def someone_has_focus(self):
        if (self.viewer and
            self.viewer.has_focus() and
            self.viewer_connected):
            return True

        for serial in self.serial_tabs:
            if (serial.terminal and
                serial.terminal.get_property("has-focus")):
                return True

    def viewer_focus_changed(self, ignore1=None, ignore2=None):
        force_accel = self.config.get_console_accels()

        if force_accel:
            self._enable_modifiers()
        elif self.someone_has_focus():
            self._disable_modifiers()
        else:
            self._enable_modifiers()

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

        settings = Gtk.Settings.get_default()
        self.gtk_settings_accel = settings.get_property('gtk-menu-bar-accel')
        settings.set_property('gtk-menu-bar-accel', None)

        if _has_property(settings, "gtk-enable-mnemonics"):
            self.gtk_settings_mnemonic = settings.get_property(
                                                        "gtk-enable-mnemonics")
            settings.set_property("gtk-enable-mnemonics", False)

    def _enable_modifiers(self):
        if self.gtk_settings_accel is None:
            return

        settings = Gtk.Settings.get_default()
        settings.set_property('gtk-menu-bar-accel', self.gtk_settings_accel)
        self.gtk_settings_accel = None

        if self.gtk_settings_mnemonic is not None:
            settings.set_property("gtk-enable-mnemonics",
                                  self.gtk_settings_mnemonic)

        for g in self.accel_groups:
            self.topwin.add_accel_group(g)

    def grab_keys_changed(self):
        if self.viewer:
            self.viewer.set_grab_keys()

    def keyboard_grab_default_changed(self):
        if self.viewer:
            self.viewer.set_keyboard_grab_default()

    def set_enable_accel(self):
        # Make sure modifiers are up to date
        self.viewer_focus_changed()

    def refresh_resizeguest_from_settings(self):
        tooltip = ""
        if self.viewer:
            if self.viewer.viewer_type != "spice":
                tooltip = (
                    _("Graphics type '%s' does not support auto resize.") %
                    self.viewer.viewer_type)
            elif not self.viewer.has_agent():
                tooltip = _("Guest agent is not available.")

        val = self.vm.get_console_resizeguest()
        widget = self.widget("details-menu-view-resizeguest")
        widget.set_tooltip_text(tooltip)
        widget.set_sensitive(not bool(tooltip))
        if not tooltip:
            self.widget("details-menu-view-resizeguest").set_active(bool(val))

        self.sync_resizeguest_with_display()

    def resizeguest_ui_changed_cb(self, src):
        # Called from details.py
        if not src.get_sensitive():
            return

        val = int(self.widget("details-menu-view-resizeguest").get_active())
        self.vm.set_console_resizeguest(val)
        self.sync_resizeguest_with_display()

    def sync_resizeguest_with_display(self):
        if not self.viewer:
            return

        val = bool(self.vm.get_console_resizeguest())
        self.viewer.set_resizeguest(val)
        self.widget("console-gfx-scroll").queue_resize()

    def refresh_scaling_from_settings(self):
        scale_type = self.vm.get_console_scaling()
        self.widget("details-menu-view-scale-always").set_active(
            scale_type == self.config.CONSOLE_SCALE_ALWAYS)
        self.widget("details-menu-view-scale-never").set_active(
            scale_type == self.config.CONSOLE_SCALE_NEVER)
        self.widget("details-menu-view-scale-fullscreen").set_active(
            scale_type == self.config.CONSOLE_SCALE_FULLSCREEN)

        self.sync_scaling_with_display()

    def scaling_ui_changed_cb(self, src):
        # Called from details.py
        if not src.get_active():
            return

        scale_type = 0
        if src == self.widget("details-menu-view-scale-always"):
            scale_type = self.config.CONSOLE_SCALE_ALWAYS
        elif src == self.widget("details-menu-view-scale-fullscreen"):
            scale_type = self.config.CONSOLE_SCALE_FULLSCREEN
        elif src == self.widget("details-menu-view-scale-never"):
            scale_type = self.config.CONSOLE_SCALE_NEVER

        self.vm.set_console_scaling(scale_type)
        self.sync_scaling_with_display()

    def sync_scaling_with_display(self):
        if not self.viewer:
            return

        curscale = self.viewer.get_scaling()
        fs = self.widget("control-fullscreen").get_active()
        scale_type = self.vm.get_console_scaling()

        if (scale_type == self.config.CONSOLE_SCALE_NEVER
            and curscale is True):
            self.viewer.set_scaling(False)
        elif (scale_type == self.config.CONSOLE_SCALE_ALWAYS
              and curscale is False):
            self.viewer.set_scaling(True)
        elif (scale_type == self.config.CONSOLE_SCALE_FULLSCREEN
              and curscale != fs):
            self.viewer.set_scaling(fs)

        # Refresh viewer size
        self.widget("console-gfx-scroll").queue_resize()

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

        self.sync_scaling_with_display()

    def viewer_allocate_cb(self, src, req):
        self.widget("console-gfx-scroll").queue_resize()

    def size_to_vm(self, src_ignore):
        # Resize the console to best fit the VM resolution
        if not self.viewer:
            return
        if not self.viewer.get_desktop_resolution():
            return

        self.topwin.unmaximize()
        self.topwin.resize(1, 1)
        self.force_resize = True
        self.widget("console-gfx-scroll").queue_resize()

    def send_key(self, src, keys):
        ignore = src

        if keys is not None:
            self.viewer.send_keys(keys)


    ##########################
    # State tracking methods #
    ##########################

    def view_vm_status(self):
        if not self.vm:
            # window has been closed and no pages to update are available.
            return
        status = self.vm.status()
        if status == libvirt.VIR_DOMAIN_SHUTOFF:
            self.activate_unavailable_page(_("Guest not running"))
        else:
            if status == libvirt.VIR_DOMAIN_CRASHED:
                self.activate_unavailable_page(_("Guest has crashed"))

    def close_viewer(self):
        if self.viewer is None:
            return

        viewer = self.viewer
        display = getattr(viewer, "_display")
        self.viewer = None

        viewport = self.widget("console-gfx-viewport")
        if display and display in viewport.get_children():
            viewport.remove(display)

        viewer.close()
        self.viewer_connected = False
        self.leave_fullscreen()

        for serial in self.serial_tabs:
            serial.close()

    def update_widget_states(self, vm, status_ignore):
        runable = vm.is_runable()
        pages   = self.widget("console-pages")
        page    = pages.get_current_page()

        if runable:
            if page != CONSOLE_PAGE_UNAVAILABLE:
                pages.set_current_page(CONSOLE_PAGE_UNAVAILABLE)

            self.view_vm_status()

        elif page in [CONSOLE_PAGE_UNAVAILABLE, CONSOLE_PAGE_VIEWER]:
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
        self.widget("console-pages").set_current_page(CONSOLE_PAGE_UNAVAILABLE)
        self.widget("details-menu-vm-screenshot").set_sensitive(False)
        self.widget("details-menu-usb-redirection").set_sensitive(False)
        self.widget("console-unavailable").set_label("<b>" + msg + "</b>")

    def activate_auth_page(self, withPassword=True, withUsername=False):
        (pw, username) = self.config.get_console_password(self.vm)
        self.widget("details-menu-vm-screenshot").set_sensitive(False)
        self.widget("details-menu-usb-redirection").set_sensitive(False)

        self.widget("console-auth-password").set_visible(withPassword)
        self.widget("label-auth-password").set_visible(withPassword)

        self.widget("console-auth-username").set_visible(withUsername)
        self.widget("label-auth-username").set_visible(withUsername)

        if withUsername:
            self.widget("console-auth-username").grab_focus()
        else:
            self.widget("console-auth-password").grab_focus()

        self.widget("console-auth-username").set_text(username)
        self.widget("console-auth-password").set_text(pw)

        self.widget("console-auth-remember").set_sensitive(
                bool(self.config.has_keyring()))
        if self.config.has_keyring():
            self.widget("console-auth-remember").set_active(bool(pw and
                                                                 username))

        self.widget("console-pages").set_current_page(
            CONSOLE_PAGE_AUTHENTICATE)


    def activate_viewer_page(self):
        self.widget("console-pages").set_current_page(CONSOLE_PAGE_VIEWER)
        self.widget("details-menu-vm-screenshot").set_sensitive(True)
        if self.viewer:
            self.viewer.grab_focus()

        if (self.viewer.has_usb_redirection() and
            self.vm.has_spicevmc_type_redirdev()):
            self.widget("details-menu-usb-redirection").set_sensitive(True)
            return

    def page_changed(self, ignore1=None, ignore2=None, newpage=None):
        pagenum = self.widget("console-pages").get_current_page()

        for i in range(self.widget("console-pages").get_n_pages()):
            w = self.widget("console-pages").get_nth_page(i)
            w.set_visible(i == newpage)

        if pagenum < CONSOLE_PAGE_OFFSET:
            self.last_gfx_page = pagenum
        self.set_allow_fullscreen()

    def set_allow_fullscreen(self):
        cpage = self.widget("console-pages").get_current_page()
        dpage = self.widget("details-pages").get_current_page()

        allow_fullscreen = (dpage == DETAILS_PAGE_CONSOLE and
                            cpage == CONSOLE_PAGE_VIEWER and
                            self.viewer_connected)

        self.widget("control-fullscreen").set_sensitive(allow_fullscreen)
        self.widget("details-menu-view-fullscreen").set_sensitive(allow_fullscreen)

    def disconnected(self):
        errout = ""
        if self.tunnels is not None:
            errout = self.tunnels.get_err_output()
            self.tunnels.close_all()
            self.tunnels = None

        self.widget("console-pages").set_current_page(CONSOLE_PAGE_UNAVAILABLE)
        self.close_viewer()
        logging.debug("Viewer disconnected")

        # Make sure modifiers are set correctly
        self.viewer_focus_changed()

        if self.guest_not_avail():
            # Exit was probably for legitimate reasons
            self.view_vm_status()
            return

        error = _("Error: viewer connection to hypervisor host got refused "
                  "or disconnected!")
        if errout:
            logging.debug("Error output from closed console: %s", errout)
            error += "\n\nError: %s" % errout

        self.activate_unavailable_page(error)
        self.refresh_resizeguest_from_settings()

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

        # Had a successful connect, so reset counters now
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

            self.activate_unavailable_page(msg)
            return

        if ginfo.is_bad_localhost():
            self.activate_unavailable_page(
                        _("Guest is on a remote host with transport '%s'\n"
                          "but is only configured to listen on locally.\n"
                          "Connect using 'ssh' transport or change the\n"
                          "guest's listen address." % ginfo.transport))
            return

        if not ginfo.console_active():
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
            elif ginfo.gtype == "spice":
                self.viewer = SpiceViewer(self)

            self.set_enable_accel()

            if ginfo.need_tunnel():
                self.tunnels = SSHTunnels(ginfo)
            self.viewer.open_ginfo(ginfo)
        except Exception, e:
            logging.exception("Error connection to graphical console")
            self.activate_unavailable_page(
                    _("Error connecting to graphical console") + ":\n%s" % e)

    def set_credentials(self, src_ignore=None):
        passwd = self.widget("console-auth-password")
        if passwd.get_visible():
            self.viewer.set_credential_password(passwd.get_text())
        username = self.widget("console-auth-username")
        if username.get_visible():
            self.viewer.set_credential_username(username.get_text())

        if self.widget("console-auth-remember").get_active():
            self.config.set_console_password(self.vm, passwd.get_text(),
                                             username.get_text())

    def scroll_size_allocate(self, src_ignore, req):
        if not self.viewer or not self.viewer.get_desktop_resolution():
            return

        scroll = self.widget("console-gfx-scroll")
        is_scale = self.viewer.get_scaling()
        is_resizeguest = self.viewer.get_resizeguest()

        dx = 0
        dy = 0
        align_ratio = float(req.width) / float(req.height)

        # pylint: disable=unpacking-non-sequence
        desktop_w, desktop_h = self.viewer.get_desktop_resolution()
        if desktop_h == 0:
            return
        desktop_ratio = float(desktop_w) / float(desktop_h)

        if is_scale or self.force_resize:
            # Make sure we never show scrollbars when scaling
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        else:
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC,
                              Gtk.PolicyType.AUTOMATIC)

        if not self.force_resize and is_resizeguest:
            # With resize guest, we don't want to maintain aspect ratio,
            # since the guest can resize to arbitrary resolutions.
            self.viewer.set_size_request(req.width, req.height)
            return

        if not is_scale or self.force_resize:
            # Scaling disabled is easy, just force the VNC widget size. Since
            # we are inside a scrollwindow, it shouldn't cause issues.
            self.force_resize = False
            self.viewer.set_size_request(desktop_w, desktop_h)
            return

        # Make sure there is no hard size requirement so we can scale down
        self.viewer.set_size_request(-1, -1)

        # Make sure desktop aspect ratio is maintained
        if align_ratio > desktop_ratio:
            desktop_w = int(req.height * desktop_ratio)
            desktop_h = req.height
            dx = (req.width - desktop_w) / 2

        else:
            desktop_w = req.width
            desktop_h = int(req.width / desktop_ratio)
            dy = (req.height - desktop_h) / 2

        viewer_alloc = Gdk.Rectangle()
        viewer_alloc.x = dx
        viewer_alloc.y = dy
        viewer_alloc.width = desktop_w
        viewer_alloc.height = desktop_h
        self.viewer.size_allocate(viewer_alloc)


    ###########################
    # Serial console handling #
    ###########################

    def activate_default_console_page(self):
        if self.vm.get_graphics_devices() or not self.vm.get_serial_devs():
            return

        # Show serial console
        devs = self.build_serial_list()
        for name, ignore, sensitive, ignore, cb, serialidx in devs:
            if not sensitive or not cb:
                continue

            self._show_serial_tab(name, serialidx)
            break

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
        current_page = self.widget("console-pages").get_current_page()
        if not current_page >= CONSOLE_PAGE_OFFSET:
            return

        serial_idx = current_page - CONSOLE_PAGE_OFFSET
        if len(self.serial_tabs) < serial_idx:
            return

        return self.serial_tabs[serial_idx]

    def control_serial_tab(self, src_ignore, name, target_port):
        self.widget("details-pages").set_current_page(DETAILS_PAGE_CONSOLE)
        if name == "graphics":
            self.widget("console-pages").set_current_page(self.last_gfx_page)
        else:
            self._show_serial_tab(name, target_port)

    def _show_serial_tab(self, name, target_port):
        serial = None
        for s in self.serial_tabs:
            if s.name == name:
                serial = s
                break

        if not serial:
            serial = vmmSerialConsole(self.vm, target_port, name)
            serial.terminal.connect("focus-in-event",
                                    self.viewer_focus_changed)
            serial.terminal.connect("focus-out-event",
                                    self.viewer_focus_changed)

            title = Gtk.Label(label=name)
            self.widget("console-pages").append_page(serial.box, title)
            self.serial_tabs.append(serial)

        serial.open_console()
        page_idx = self.serial_tabs.index(serial) + CONSOLE_PAGE_OFFSET
        self.widget("console-pages").set_current_page(page_idx)

    def populate_serial_menu(self, src):
        for ent in src:
            src.remove(ent)

        serial_page_dev = self.current_serial_dev()
        showing_graphics = (
            self.widget("console-pages").get_current_page() ==
            CONSOLE_PAGE_VIEWER)

        # Populate serial devices
        group = None
        itemlist = self.build_serial_list()
        for msg, err, sensitive, do_radio, cb, ignore in itemlist:
            if do_radio:
                item = Gtk.RadioMenuItem(group)
                item.set_label(msg)
                if group is None:
                    group = item
            else:
                item = Gtk.MenuItem.new_with_label(msg)

            item.set_sensitive(sensitive)

            if err and not sensitive:
                item.set_tooltip_text(err)

            if cb:
                item.connect("toggled", cb)

            # Tab is already open, make sure marked as such
            if (sensitive and
                serial_page_dev and
                serial_page_dev.name == msg):
                item.set_active(True)

            src.add(item)

        src.add(Gtk.SeparatorMenuItem())

        # Populate graphical devices
        devs = self.vm.get_graphics_devices()
        if len(devs) == 0:
            item = Gtk.MenuItem.new_with_label(
                _("No graphical console available"))
            item.set_sensitive(False)
            src.add(item)
        else:
            dev = devs[0]
            item = Gtk.RadioMenuItem(group)
            item.set_label(_("Graphical Console %s") %
                           dev.pretty_type_simple(dev.type))
            if group is None:
                group = item

            if showing_graphics:
                item.set_active(True)
            item.connect("toggled", self.control_serial_tab,
                         dev.virtual_device_type, dev.type)
            src.add(item)

        src.show_all()

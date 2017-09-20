#
# Copyright (C) 2006-2008, 2015 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
# Copyright (C) 2010 Marc-Andre Lureau <marcandre.lureau@redhat.com>
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
import socket

from gi.repository import GObject
from gi.repository import Gdk

import gi
gi.require_version('GtkVnc', '2.0')
from gi.repository import GtkVnc
try:
    gi.require_version('SpiceClientGtk', '3.0')
    from gi.repository import SpiceClientGtk
    from gi.repository import SpiceClientGLib
    have_spice_gtk = True
except (ValueError, ImportError):
    have_spice_gtk = False

from .baseclass import vmmGObject
from .sshtunnels import SSHTunnels


##################################
# VNC/Spice abstraction handling #
##################################

class Viewer(vmmGObject):
    """
    Base class for viewer abstraction
    """
    __gsignals__ = {
        "add-display-widget": (GObject.SignalFlags.RUN_FIRST, None, [object]),
        "size-allocate": (GObject.SignalFlags.RUN_FIRST, None, [object]),
        "focus-in-event": (GObject.SignalFlags.RUN_FIRST, None, [object]),
        "focus-out-event": (GObject.SignalFlags.RUN_FIRST, None, [object]),
        "pointer-grab": (GObject.SignalFlags.RUN_FIRST, None, []),
        "pointer-ungrab": (GObject.SignalFlags.RUN_FIRST, None, []),
        "connected": (GObject.SignalFlags.RUN_FIRST, None, []),
        "disconnected": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "auth-error": (GObject.SignalFlags.RUN_FIRST, None, [str, bool]),
        "auth-rejected": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "need-auth": (GObject.SignalFlags.RUN_FIRST, None, [bool, bool]),
        "agent-connected": (GObject.SignalFlags.RUN_FIRST, None, []),
        "usb-redirect-error": (GObject.SignalFlags.RUN_FIRST, None, [str]),
    }

    def __init__(self, vm, ginfo):
        vmmGObject.__init__(self)
        self._display = None
        self._vm = vm
        self._ginfo = ginfo
        self._tunnels = SSHTunnels(self._ginfo)

        self.add_gsettings_handle(
            self.config.on_keys_combination_changed(self._refresh_grab_keys))
        self.add_gsettings_handle(
            self.config.on_keyboard_grab_default_changed(
            self._refresh_keyboard_grab_default))

        self.connect("add-display-widget", self._common_init)

    def _cleanup(self):
        self.close()

        if self._display:
            self._display.destroy()
        self._display = None
        self._vm = None

        self._tunnels.close_all()


    ########################
    # Internal helper APIs #
    ########################

    def _make_signal_proxy(self, new_signal):
        """
        Helper for redirecting a signal from self._display out
        through the viewer
        """
        def _proxy_signal(src, *args, **kwargs):
            ignore = src
            self.emit(new_signal, *args, **kwargs)
        return _proxy_signal

    def _common_init(self, ignore1, ignore2):
        self._refresh_grab_keys()
        self._refresh_keyboard_grab_default()

        self._display.connect("size-allocate",
            self._make_signal_proxy("size-allocate"))
        self._display.connect("focus-in-event",
            self._make_signal_proxy("focus-in-event"))
        self._display.connect("focus-out-event",
            self._make_signal_proxy("focus-out-event"))



    #########################
    # Generic internal APIs #
    #########################

    def _grab_focus(self):
        if self._display:
            self._display.grab_focus()
    def _has_focus(self):
        return self._display and self._display.get_property("has-focus")
    def _set_size_request(self, *args, **kwargs):
        return self._display.set_size_request(*args, **kwargs)
    def _size_allocate(self, *args, **kwargs):
        return self._display.size_allocate(*args, **kwargs)
    def _get_visible(self):
        return self._display and self._display.get_visible()

    def _get_pixbuf(self):
        return self._display.get_pixbuf()

    def _get_fd_for_open(self):
        if self._ginfo.need_tunnel():
            return self._tunnels.open_new()

        if self._vm.conn.is_remote():
            # OpenGraphics only works for local libvirtd connections
            return None

        if self._ginfo.gtlsport and not self._ginfo.gport:
            # This makes spice loop requesting an fd. Disable until spice is
            # fixed: https://bugzilla.redhat.com/show_bug.cgi?id=1334071
            return None

        if not self._vm.conn.check_support(
                self._vm.conn.SUPPORT_DOMAIN_OPEN_GRAPHICS):
            return None

        return self._vm.open_graphics_fd()

    def _open(self):
        if self._ginfo.bad_config():
            raise RuntimeError(self._ginfo.bad_config())

        fd = self._get_fd_for_open()
        if fd is not None:
            self._open_fd(fd)
        else:
            self._open_host()

    def _get_grab_keys(self):
        return self._display.get_grab_keys().as_string()

    def _emit_disconnected(self, errdetails=None):
        ssherr = self._tunnels.get_err_output()
        self.emit("disconnected", errdetails, ssherr)


    #######################################################
    # Internal API that will be overwritten by subclasses #
    #######################################################

    def close(self):
        raise NotImplementedError()

    def _is_open(self):
        raise NotImplementedError()

    def _set_username(self, cred):
        raise NotImplementedError()
    def _set_password(self, cred):
        raise NotImplementedError()

    def _send_keys(self, keys):
        raise NotImplementedError()

    def _refresh_grab_keys(self):
        raise NotImplementedError()
    def _refresh_keyboard_grab_default(self):
        raise NotImplementedError()

    def _open_host(self):
        raise NotImplementedError()
    def _open_fd(self, fd):
        raise NotImplementedError()

    def _get_desktop_resolution(self):
        raise NotImplementedError()

    def _get_scaling(self):
        raise NotImplementedError()
    def _set_scaling(self, scaling):
        raise NotImplementedError()

    def _set_resizeguest(self, val):
        raise NotImplementedError()
    def _get_resizeguest(self):
        raise NotImplementedError()

    def _get_usb_widget(self):
        raise NotImplementedError()
    def _has_usb_redirection(self):
        raise NotImplementedError()
    def _has_agent(self):
        raise NotImplementedError()


    ####################################
    # APIs accessed by vmmConsolePages #
    ####################################

    def console_is_open(self):
        return self._is_open()

    def console_grab_focus(self):
        return self._grab_focus()
    def console_has_focus(self):
        return self._has_focus()
    def console_set_size_request(self, *args, **kwargs):
        return self._set_size_request(*args, **kwargs)
    def console_size_allocate(self, *args, **kwargs):
        return self._size_allocate(*args, **kwargs)
    def console_get_visible(self):
        return self._get_visible()

    def console_get_pixbuf(self):
        return self._get_pixbuf()

    def console_open(self):
        return self._open()

    def console_set_password(self, val):
        return self._set_password(val)
    def console_set_username(self, val):
        return self._set_username(val)

    def console_send_keys(self, keys):
        return self._send_keys(keys)

    def console_get_grab_keys(self):
        return self._get_grab_keys()

    def console_get_desktop_resolution(self):
        ret = self._get_desktop_resolution()
        if not ret:
            return ret

        # Don't pass on bogus resolutions
        if (ret[0] == 0) or (ret[1] == 0):
            return None
        return ret

    def console_get_scaling(self):
        return self._get_scaling()
    def console_set_scaling(self, val):
        return self._set_scaling(val)

    def console_get_resizeguest(self):
        return self._get_resizeguest()
    def console_set_resizeguest(self, val):
        return self._set_resizeguest(val)

    def console_get_usb_widget(self):
        return self._get_usb_widget()
    def console_has_usb_redirection(self):
        return self._has_usb_redirection()
    def console_has_agent(self):
        return self._has_agent()

    def console_remove_display_from_widget(self, widget):
        if self._display and self._display in widget.get_children():
            widget.remove(self._display)


####################
# VNC viewer class #
####################

class VNCViewer(Viewer):
    viewer_type = "vnc"

    def __init__(self, *args, **kwargs):
        Viewer.__init__(self, *args, **kwargs)
        self._display = None
        self._sockfd = None
        self._desktop_resolution = None


    ###################
    # Private helpers #
    ###################

    def _init_widget(self):
        self._display = GtkVnc.Display()

        # Make sure viewer doesn't force resize itself
        self._display.set_force_size(False)
        self._display.set_pointer_grab(True)

        self.emit("add-display-widget", self._display)
        self._display.realize()

        self._display.connect("vnc-pointer-grab",
            self._make_signal_proxy("pointer-grab"))
        self._display.connect("vnc-pointer-ungrab",
            self._make_signal_proxy("pointer-ungrab"))

        self._display.connect("vnc-auth-credential", self._auth_credential)
        self._display.connect("vnc-auth-failure", self._auth_failure_cb)
        self._display.connect("vnc-initialized", self._connected_cb)
        self._display.connect("vnc-disconnected", self._disconnected_cb)
        self._display.connect("vnc-desktop-resize", self._desktop_resize)

        self._display.show()

    def _connected_cb(self, ignore):
        self._tunnels.unlock()
        self.emit("connected")

    def _disconnected_cb(self, ignore):
        self._tunnels.unlock()
        self._emit_disconnected()

    def _desktop_resize(self, src_ignore, w, h):
        self._desktop_resolution = (w, h)
        # Queue a resize
        self.emit("size-allocate", None)

    def _auth_failure_cb(self, ignore, msg):
        logging.debug("VNC auth failure. msg=%s", msg)
        self.emit("auth-error", msg, True)

    def _auth_credential(self, src_ignore, credList):
        values = []
        for idx in range(int(credList.n_values)):
            values.append(credList.get_nth(idx))

        for cred in values:
            if cred in [GtkVnc.DisplayCredential.PASSWORD,
                        GtkVnc.DisplayCredential.USERNAME,
                        GtkVnc.DisplayCredential.CLIENTNAME]:
                continue

            errmsg = (_("Unable to provide requested credentials to the VNC "
                "server.\n The credential type %s is not supported") %
                str(cred.value_name))

            self.emit("auth-rejected", errmsg)
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
            self.emit("need-auth", withPassword, withUsername)


    ###############################
    # Private API implementations #
    ###############################

    def close(self):
        self._display.close()
        if self._sockfd:
            self._sockfd.close()
            self._sockfd = None

    def _is_open(self):
        return self._display.is_open()

    def _get_scaling(self):
        return self._display.get_scaling()
    def _set_scaling(self, scaling):
        return self._display.set_scaling(scaling)

    def _get_grab_keys(self):
        return self._display.get_grab_keys().as_string()

    def _refresh_grab_keys(self):
        if not self._display:
            return

        try:
            keys = self.config.get_keys_combination()
            if not keys:
                return

            try:
                keys = [int(k) for k in keys.split(',')]
            except Exception:
                logging.debug("Error in grab_keys configuration in Gsettings",
                              exc_info=True)
                return

            seq = GtkVnc.GrabSequence.new(keys)
            self._display.set_grab_keys(seq)
        except Exception as e:
            logging.debug("Error when getting the grab keys combination: %s",
                          str(e))

    def _send_keys(self, keys):
        return self._display.send_keys([Gdk.keyval_from_name(k) for k in keys])

    def _refresh_keyboard_grab_default(self):
        if not self._display:
            return
        self._display.set_keyboard_grab(self.config.get_keyboard_grab_default())

    def _get_desktop_resolution(self):
        return self._desktop_resolution

    def _set_username(self, cred):
        self._display.set_credential(GtkVnc.DisplayCredential.USERNAME, cred)
    def _set_password(self, cred):
        self._display.set_credential(GtkVnc.DisplayCredential.PASSWORD, cred)

    def _set_resizeguest(self, val):
        ignore = val
    def _get_resizeguest(self):
        return False

    def _get_usb_widget(self):
        return None
    def _has_usb_redirection(self):
        return False
    def _has_agent(self):
        return False


    #######################
    # Connection routines #
    #######################

    def _open(self):
        self._init_widget()
        return Viewer._open(self)

    def _open_host(self):
        host, port, ignore = self._ginfo.get_conn_host()

        if not self._ginfo.gsocket:
            logging.debug("VNC connecting to host=%s port=%s", host, port)
            self._display.open_host(host, port)
            return

        logging.debug("VNC connecting to socket=%s", self._ginfo.gsocket)
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self._ginfo.gsocket)
            self._sockfd = sock
        except Exception as e:
            raise RuntimeError(_("Error opening socket path '%s': %s") %
                               (self._ginfo.gsocket, e))

        fd = self._sockfd.fileno()
        if fd < 0:
            raise RuntimeError((_("Error opening socket path '%s'") %
                                self._ginfo.gsocket) + " fd=%s" % fd)
        self._open_fd(fd)

    def _open_fd(self, fd):
        self._display.open_fd(fd)


######################
# Spice viewer class #
######################

class SpiceViewer(Viewer):
    viewer_type = "spice"

    def __init__(self, *args, **kwargs):
        Viewer.__init__(self, *args, **kwargs)
        self._spice_session = None
        self._display = None
        self._audio = None
        self._main_channel = None
        self._main_channel_hids = []
        self._display_channel = None
        self._usbdev_manager = None


    ###################
    # Private helpers #
    ###################

    def _init_widget(self):
        self.emit("add-display-widget", self._display)
        self._display.realize()

        self._display.connect("mouse-grab", self._mouse_grab_event)

        self._display.show()

    def _mouse_grab_event(self, ignore, grab):
        if grab:
            self.emit("pointer-grab")
        else:
            self.emit("pointer-ungrab")

    def _close_main_channel(self):
        for i in self._main_channel_hids:
            self._main_channel.handler_disconnect(i)
        self._main_channel_hids = []
        self._main_channel = None

    def _create_spice_session(self):
        self._spice_session = SpiceClientGLib.Session()
        SpiceClientGLib.set_session_option(self._spice_session)
        gtk_session = SpiceClientGtk.GtkSession.get(self._spice_session)
        gtk_session.set_property("auto-clipboard", True)

        GObject.GObject.connect(self._spice_session, "channel-new",
                                self._channel_new_cb)

        # Distros might have usb redirection compiled out, like OpenBSD
        # https://bugzilla.redhat.com/show_bug.cgi?id=1348479
        try:
            self._usbdev_manager = SpiceClientGLib.UsbDeviceManager.get(
                                        self._spice_session)
            self._usbdev_manager.connect("auto-connect-failed",
                                        self._usbdev_redirect_error)
            self._usbdev_manager.connect("device-error",
                                        self._usbdev_redirect_error)

            autoredir = self.config.get_auto_redirection()
            if autoredir:
                gtk_session.set_property("auto-usbredir", True)
        except Exception:
            self._usbdev_manager = None
            logging.debug("Error initializing spice usb device manager",
                exc_info=True)


    #####################
    # Channel listeners #
    #####################

    def _main_channel_event_cb(self, channel, event):
        self._tunnels.unlock()

        if event == SpiceClientGLib.ChannelEvent.CLOSED:
            self._emit_disconnected()
        elif event == SpiceClientGLib.ChannelEvent.ERROR_AUTH:
            if not self._spice_session.get_property("password"):
                logging.debug("Spice channel received ERROR_AUTH, but no "
                    "password set, assuming it wants credentials.")
                self.emit("need-auth", True, False)
            else:
                logging.debug("Spice channel received ERROR_AUTH, but a "
                    "password is already set. Assuming authentication failed.")
                self.emit("auth-error", channel.get_error().message, False)
        elif "ERROR" in str(event):
            # SpiceClientGLib.ChannelEvent.ERROR_CONNECT
            # SpiceClientGLib.ChannelEvent.ERROR_IO
            # SpiceClientGLib.ChannelEvent.ERROR_LINK
            # SpiceClientGLib.ChannelEvent.ERROR_TLS
            error = None
            if channel.get_error():
                error = channel.get_error().message
            logging.debug("Spice channel event=%s message=%s", event, error)

            msg = _("Encountered SPICE %(error-name)s") % {
                "error-name": event.value_nick}
            if error:
                msg += ": %s" % error
            self._emit_disconnected(msg)

    def _fd_channel_event_cb(self, channel, event):
        # When we see any event from the channel, release the
        # associated tunnel lock
        channel.disconnect_by_func(self._fd_channel_event_cb)
        self._tunnels.unlock()

    def _channel_open_fd_request(self, channel, tls_ignore):
        if not self._tunnels:
            # Can happen if we close the details window and clear self._tunnels
            # while initially connecting to spice and channel FD requests
            # are still rolling in
            return

        logging.debug("Requesting fd for channel: %s", channel)
        channel.connect_after("channel-event", self._fd_channel_event_cb)

        fd = self._get_fd_for_open()
        channel.open_fd(fd)

    def _channel_new_cb(self, session, channel):
        GObject.GObject.connect(channel, "open-fd",
                                self._channel_open_fd_request)

        if (isinstance(channel, SpiceClientGLib.MainChannel) and
            not self._main_channel):
            self._main_channel = channel
            hid = self._main_channel.connect_after("channel-event",
                self._main_channel_event_cb)
            self._main_channel_hids.append(hid)
            hid = self._main_channel.connect_after("notify::agent-connected",
                self._agent_connected_cb)
            self._main_channel_hids.append(hid)

        elif (type(channel) == SpiceClientGLib.DisplayChannel and
                not self._display):
            channel_id = channel.get_property("channel-id")

            if channel_id != 0:
                logging.debug("Spice multi-head unsupported")
                return

            self._display_channel = channel
            self._display = SpiceClientGtk.Display.new(self._spice_session,
                                                      channel_id)
            self._init_widget()
            self.emit("connected")

        elif (type(channel) in [SpiceClientGLib.PlaybackChannel,
                                SpiceClientGLib.RecordChannel] and
                                not self._audio):
            self._audio = SpiceClientGLib.Audio.get(self._spice_session, None)

    def _agent_connected_cb(self, src, val):
        self.emit("agent-connected")


    ################################
    # Internal API implementations #
    ################################

    def close(self):
        if self._spice_session is not None:
            self._spice_session.disconnect()
        self._spice_session = None
        self._audio = None
        if self._display:
            self._display.destroy()
        self._display = None
        self._display_channel = None

        self._close_main_channel()
        self._usbdev_manager = None

    def _is_open(self):
        return self._spice_session is not None

    def _refresh_grab_keys(self):
        if not self._display:
            return

        try:
            keys = self.config.get_keys_combination()
            if not keys:
                return

            try:
                keys = [int(k) for k in keys.split(',')]
            except Exception:
                logging.debug("Error in grab_keys configuration in Gsettings",
                              exc_info=True)
                return

            seq = SpiceClientGtk.GrabSequence.new(keys)
            self._display.set_grab_keys(seq)
        except Exception as e:
            logging.debug("Error when getting the grab keys combination: %s",
                          str(e))

    def _send_keys(self, keys):
        return self._display.send_keys([Gdk.keyval_from_name(k) for k in keys],
                                      SpiceClientGtk.DisplayKeyEvent.CLICK)

    def _refresh_keyboard_grab_default(self):
        if not self._display:
            return
        self._display.set_property("grab-keyboard",
            self.config.get_keyboard_grab_default())

    def _get_desktop_resolution(self):
        if not self._display_channel:
            return None
        return self._display_channel.get_properties("width", "height")

    def _has_agent(self):
        if not self._main_channel:
            return False
        return self._main_channel.get_property("agent-connected")

    def _open_host(self):
        host, port, tlsport = self._ginfo.get_conn_host()
        self._create_spice_session()

        logging.debug("Spice connecting to host=%s port=%s tlsport=%s",
            host, port, tlsport)
        self._spice_session.set_property("host", str(host))
        if port:
            self._spice_session.set_property("port", str(port))
        if tlsport:
            self._spice_session.set_property("tls-port", str(tlsport))

        self._spice_session.connect()

    def _open_fd(self, fd):
        self._create_spice_session()
        self._spice_session.open_fd(fd)

    def _set_username(self, cred):
        ignore = cred
    def _set_password(self, cred):
        self._spice_session.set_property("password", cred)
        fd = self._get_fd_for_open()
        if fd is not None:
            self._spice_session.open_fd(fd)
        else:
            self._spice_session.connect()

    def _get_scaling(self):
        return self._display.get_property("scaling")
    def _set_scaling(self, scaling):
        self._display.set_property("scaling", scaling)

    def _set_resizeguest(self, val):
        if self._display:
            self._display.set_property("resize-guest", val)

    def _get_resizeguest(self):
        if self._display:
            return self._display.get_property("resize-guest")
        return False

    def _usbdev_redirect_error(self, spice_usbdev_widget, spice_usb_device,
            errstr):
        ignore = spice_usbdev_widget
        ignore = spice_usb_device
        self.emit("usb-redirect-error", errstr)

    def _get_usb_widget(self):
        if not self._spice_session:
            return

        usbwidget = SpiceClientGtk.UsbDeviceWidget.new(self._spice_session,
            None)
        usbwidget.connect("connect-failed", self._usbdev_redirect_error)
        return usbwidget

    def _has_usb_redirection(self):
        if not self._spice_session or not self._usbdev_manager:
            return False

        for c in self._spice_session.get_channels():
            if c.__class__ is SpiceClientGLib.UsbredirChannel:
                return True
        return False

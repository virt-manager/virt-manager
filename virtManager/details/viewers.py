# Copyright (C) 2006-2008, 2015 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
# Copyright (C) 2010 Marc-Andre Lureau <marcandre.lureau@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from gi.repository import Gdk
from gi.repository import GObject

import gi
gi.require_version('GtkVnc', '2.0')
from gi.repository import GtkVnc
try:
    SPICE_GTK_IMPORT_ERROR = None
    if "VIRTINST_TEST_SUITE_FAKE_NO_SPICE" in os.environ:
        raise ImportError("test suite faking no spice")

    gi.require_version('SpiceClientGtk', '3.0')
    from gi.repository import SpiceClientGtk
    from gi.repository import SpiceClientGLib
except (ValueError, ImportError) as _SPICE_GTK_IMPORT_ERROR:
    SPICE_GTK_IMPORT_ERROR = str(_SPICE_GTK_IMPORT_ERROR)

from virtinst import log

from .sshtunnels import SSHTunnels
from ..baseclass import vmmGObject


##################################
# VNC/Spice abstraction handling #
##################################

_GTKVNC_SUPPORT_CACHE = {}


def _gtkvnc_check_display_support(funcname):
    if funcname not in _GTKVNC_SUPPORT_CACHE:
        val = hasattr(GtkVnc.Display, funcname)
        log.debug("GtkVnc.Display %s support=%s", funcname, val)
        _GTKVNC_SUPPORT_CACHE[funcname] = val
    return _GTKVNC_SUPPORT_CACHE[funcname]


def _gtkvnc_supports_resizeguest():
    return _gtkvnc_check_display_support("set_allow_resize")


class Viewer(vmmGObject):
    """
    Base class for viewer abstraction
    """
    __gsignals__ = {
        "add-display-widget": (vmmGObject.RUN_FIRST, None, [object]),
        "size-allocate": (vmmGObject.RUN_FIRST, None, [object]),
        "desktop-resolution-changed": (vmmGObject.RUN_FIRST, None, []),
        "pointer-grab": (vmmGObject.RUN_FIRST, None, []),
        "pointer-ungrab": (vmmGObject.RUN_FIRST, None, []),
        "keyboard-grab": (vmmGObject.RUN_FIRST, None, []),
        "keyboard-ungrab": (vmmGObject.RUN_FIRST, None, []),
        "connected": (vmmGObject.RUN_FIRST, None, []),
        "disconnected": (vmmGObject.RUN_FIRST, None, [str, str]),
        "auth-error": (vmmGObject.RUN_FIRST, None, [str, bool]),
        "need-auth": (vmmGObject.RUN_FIRST, None, [bool, bool]),
        "agent-connected": (vmmGObject.RUN_FIRST, None, []),
        "usb-redirect-error": (vmmGObject.RUN_FIRST, None, [str]),
    }

    def __init__(self, vm, ginfo):
        vmmGObject.__init__(self)
        self._display = None
        self._vm = vm
        self._ginfo = ginfo
        self._tunnels = SSHTunnels(self._ginfo)
        self._keyboard_grab = False
        self._desktop_resolution = (0, 0)

        self.add_gsettings_handle(
            self.config.on_keys_combination_changed(self._refresh_grab_keys))

    def _cleanup(self):
        self._close()

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

    def _set_display(self, display):
        self._display = display
        self._refresh_grab_keys()

        self._display.connect("size-allocate",
            self._make_signal_proxy("size-allocate"))

        self.emit("add-display-widget", self._display)
        self._display.realize()

        self._connect_display_signals()

        self._display.show()


    #########################
    # Generic internal APIs #
    #########################

    def _grab_focus(self):
        if self._display:
            self._display.grab_focus()

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
            return None  # pragma: no cover

        if not self._vm.conn.support.domain_open_graphics():
            return None

        return self._vm.open_graphics_fd(self._ginfo.gidx)

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

    def _refresh_grab_keys(self):
        if not self._display:
            return  # pragma: no cover

        try:
            keys = self.config.get_keys_combination()
            if not keys:
                return  # pragma: no cover

            try:
                keys = [int(k) for k in keys.split(',')]
            except Exception:  # pragma: no cover
                log.debug("Error in grab_keys configuration in Gsettings",
                              exc_info=True)
                return

            self._set_grab_keys(keys)
        except Exception as e:  # pragma: no cover
            log.debug("Error when getting the grab keys combination: %s",
                          str(e))

    def _emit_disconnected(self, errdetails=None):
        ssherr = self._tunnels.get_err_output()
        self.emit("disconnected", errdetails, ssherr)

    def _set_desktop_resolution(self, w, h):
        if w == 0 or h == 0:
            return  # pragma: no cover

        origres = self._desktop_resolution
        newres = (w, h)
        if origres == newres:
            return  # pragma: no cover

        log.debug("vm=%s resolution changed: orig=%s new=%s",
                  self._vm.get_name(), origres, newres)
        self._desktop_resolution = newres
        self.emit("desktop-resolution-changed")


    #######################################################
    # Internal API that will be overwritten by subclasses #
    #######################################################

    def _close(self):
        raise NotImplementedError()

    def _is_open(self):
        raise NotImplementedError()
    def _connect_display_signals(self):
        raise NotImplementedError()

    def _set_username(self, cred):
        raise NotImplementedError()
    def _set_password(self, cred):
        raise NotImplementedError()

    def _send_keys(self, keys):
        raise NotImplementedError()

    def _set_grab_keys(self, keys):
        raise NotImplementedError()

    def _open_host(self):
        raise NotImplementedError()
    def _open_fd(self, fd):
        raise NotImplementedError()

    def _get_scaling(self):
        raise NotImplementedError()
    def _set_scaling(self, scaling):
        raise NotImplementedError()

    def _set_resizeguest(self, val):
        raise NotImplementedError()
    def _get_resizeguest(self):
        raise NotImplementedError()
    def _get_resizeguest_warning(self):
        raise NotImplementedError()

    def _get_usb_widget(self):
        raise NotImplementedError()
    def _has_usb_redirection(self):
        raise NotImplementedError()

    def _get_preferred_size(self):
        raise NotImplementedError()


    ####################################
    # APIs accessed by vmmConsolePages #
    ####################################

    def console_is_open(self):
        return self._is_open()

    def console_grab_focus(self):
        return self._grab_focus()
    def console_has_keyboard_grab(self):
        return bool(self._display and self._keyboard_grab)

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

    def console_get_preferred_size(self):
        return self._get_preferred_size()

    def console_set_scaling(self, val):
        return self._set_scaling(val)

    def console_set_resizeguest(self, val):
        return self._set_resizeguest(val)
    def console_get_resizeguest_warning(self):
        return self._get_resizeguest_warning()

    def console_get_usb_widget(self):
        return self._get_usb_widget()
    def console_has_usb_redirection(self):
        return self._has_usb_redirection()

    def console_remove_display_from_widget(self, widget):
        if self._display and self._display in widget.get_children():
            widget.remove(self._display)


####################
# VNC viewer class #
####################

class VNCViewer(Viewer):
    viewer_type = "vnc"


    ###################
    # Private helpers #
    ###################

    def _connect_display_signals(self):
        self._display.connect("vnc-pointer-grab",
            self._make_signal_proxy("pointer-grab"))
        self._display.connect("vnc-pointer-ungrab",
            self._make_signal_proxy("pointer-ungrab"))
        self._display.connect("vnc-keyboard-grab", self._keyboard_grab_cb)
        self._display.connect("vnc-keyboard-ungrab", self._keyboard_ungrab_cb)

        self._display.connect("vnc-auth-credential", self._auth_credential)
        self._display.connect("vnc-auth-failure", self._auth_failure_cb)
        self._display.connect("vnc-initialized", self._connected_cb)
        self._display.connect("vnc-disconnected", self._disconnected_cb)
        self._display.connect("vnc-desktop-resize", self._desktop_resize_cb)

    def _init_display(self):
        display = GtkVnc.Display()

        display.set_pointer_grab(True)

        if _gtkvnc_check_display_support("set_keep_aspect_ratio"):
            display.set_keep_aspect_ratio(True)

        self._set_display(display)

    def _keyboard_grab_cb(self, src):
        self._keyboard_grab = True
        self.emit("keyboard-grab")

    def _keyboard_ungrab_cb(self, src):
        self._keyboard_grab = False
        self.emit("keyboard-ungrab")

    def _connected_cb(self, ignore):
        self._tunnels.unlock()
        self.emit("connected")

    def _disconnected_cb(self, ignore):
        self._tunnels.unlock()
        self._emit_disconnected()

    def _desktop_resize_cb(self, src, w, h):
        self._set_desktop_resolution(w, h)

    def _auth_failure_cb(self, ignore, msg):
        log.debug("VNC auth failure. msg=%s", msg)
        self.emit("auth-error", msg, True)

    def _auth_credential(self, src_ignore, credList):
        values = []
        for idx in range(int(credList.n_values)):
            values.append(credList.get_nth(idx))

        if self.config.CLITestOptions.fake_vnc_username:
            values.append(GtkVnc.DisplayCredential.USERNAME)

        withUsername = False
        withPassword = False
        for cred in values:
            log.debug("Got credential request %s", cred)
            if cred == GtkVnc.DisplayCredential.PASSWORD:
                withPassword = True
            elif cred == GtkVnc.DisplayCredential.USERNAME:
                withUsername = True
            elif cred == GtkVnc.DisplayCredential.CLIENTNAME:  # pragma: no cover
                self._display.set_credential(cred, "libvirt-vnc")
            else:  # pragma: no cover
                errmsg = (
                        _("Unable to provide requested credentials to the VNC server.\n"
                        "The credential type %s is not supported") %
                        str(cred.value_name))
                self.emit("auth-error", errmsg, True)
                return

        if withUsername or withPassword:
            self.emit("need-auth", withPassword, withUsername)

    def _sync_force_size(self):
        force_size = not self._get_scaling() and not self._get_resizeguest()
        self._display.set_force_size(force_size)


    ###############################
    # Private API implementations #
    ###############################

    def _close(self):
        self._display.close()

    def _is_open(self):
        return self._display.is_open()

    def _get_scaling(self):
        if self._display:
            return self._display.get_scaling()
    def _set_scaling(self, scaling):
        if self._display:
            self._display.set_scaling(scaling)
            self._sync_force_size()

    def _set_grab_keys(self, keys):
        seq = GtkVnc.GrabSequence.new(keys)
        self._display.set_grab_keys(seq)

    def _send_keys(self, keys):
        return self._display.send_keys([Gdk.keyval_from_name(k) for k in keys])

    def _set_username(self, cred):
        self._display.set_credential(GtkVnc.DisplayCredential.USERNAME, cred)
    def _set_password(self, cred):
        self._display.set_credential(GtkVnc.DisplayCredential.PASSWORD, cred)

    def _set_resizeguest(self, val):
        if _gtkvnc_supports_resizeguest():
            self._display.set_allow_resize(val)  # pylint: disable=no-member
            self._sync_force_size()
    def _get_resizeguest(self):
        if _gtkvnc_supports_resizeguest():
            return self._display.get_allow_resize()  # pylint: disable=no-member
        return False  # pragma: no cover
    def _get_resizeguest_warning(self):
        if not _gtkvnc_supports_resizeguest():
            return _("GTK-VNC viewer is too old")  # pragma: no cover

    def _get_usb_widget(self):
        return None  # pragma: no cover
    def _has_usb_redirection(self):
        return False

    def _get_preferred_size(self):
        return self._desktop_resolution


    #######################
    # Connection routines #
    #######################

    def _open(self):
        self._init_display()
        return Viewer._open(self)

    def _open_host(self):
        host, port, ignore = self._ginfo.get_conn_host()
        log.debug("VNC connecting to host=%s port=%s", host, port)
        self._display.open_host(host, port)

    def _open_fd(self, fd):
        self._display.open_fd(fd)


######################
# Spice viewer class #
######################

class _SignalTracker:
    # Helper class to more conveniently connect and disconnect signals
    # from spice objects. This ensures we don't leave circular references
    # at object destroy time
    def __init__(self):
        self._sigmap = {}

    def _add_hid(self, obj, hid):
        if obj not in self._sigmap:
            self._sigmap[obj] = []
        self._sigmap[obj].append(hid)

    def connect(self, obj, name, handler, *args):
        hid = GObject.GObject.connect(obj, name, handler, *args)
        self._add_hid(obj, hid)

    def connect_after(self, obj, name, handler, *args):
        hid = GObject.GObject.connect_after(obj, name, handler, *args)
        self._add_hid(obj, hid)

    def disconnect_obj_signals(self, obj):
        for hid in self._sigmap.get(obj, []):
            GObject.GObject.disconnect(obj, hid)


_SIGS = _SignalTracker()


class SpiceViewer(Viewer):
    viewer_type = "spice"

    def __init__(self, *args, **kwargs):
        Viewer.__init__(self, *args, **kwargs)
        self._spice_session = None
        self._display = None
        self._audio = None
        self._main_channel = None
        self._usbdev_manager = None
        self._channels = set()


    ###################
    # Private helpers #
    ###################

    def _mouse_grab_cb(self, src, grab):
        if grab:
            self.emit("pointer-grab")
        else:
            self.emit("pointer-ungrab")

    def _keyboard_grab_cb(self, src, grab):
        self._keyboard_grab = grab
        if grab:
            self.emit("keyboard-grab")
        else:
            self.emit("keyboard-ungrab")

    def _connect_display_signals(self):
        self._display.connect("mouse-grab", self._mouse_grab_cb)
        self._display.connect("keyboard-grab", self._keyboard_grab_cb)

    def _create_spice_session(self):
        self._spice_session = SpiceClientGLib.Session()
        SpiceClientGLib.set_session_option(self._spice_session)
        gtk_session = SpiceClientGtk.GtkSession.get(self._spice_session)
        gtk_session.set_property("auto-clipboard", True)

        _SIGS.connect(self._spice_session, "channel-new", self._channel_new_cb)

        # Distros might have usb redirection compiled out, like OpenBSD
        # https://bugzilla.redhat.com/show_bug.cgi?id=1348479
        try:
            self._usbdev_manager = SpiceClientGLib.UsbDeviceManager.get(
                                        self._spice_session)
            _SIGS.connect(
                    self._usbdev_manager, "auto-connect-failed",
                    self._usbdev_redirect_error)
            _SIGS.connect(
                    self._usbdev_manager, "device-error",
                    self._usbdev_redirect_error)

            autoredir = self.config.get_auto_usbredir()
            if autoredir:
                gtk_session.set_property("auto-usbredir", True)
        except Exception:  # pragma: no cover
            self._usbdev_manager = None
            log.debug("Error initializing spice usb device manager",
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
                log.debug("Spice channel received ERROR_AUTH, but no "
                    "password set, assuming it wants credentials.")
                self.emit("need-auth", True, False)
            else:
                log.debug("Spice channel received ERROR_AUTH, but a "
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
            log.debug("Spice channel event=%s message=%s", event, error)

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
            return  # pragma: no cover

        log.debug("Requesting fd for channel: %s", channel)
        channel.connect_after("channel-event", self._fd_channel_event_cb)

        fd = self._get_fd_for_open()
        channel.open_fd(fd)

    def _channel_new_cb(self, session, channel):
        self._channels.add(channel)
        _SIGS.connect(channel, "open-fd", self._channel_open_fd_request)

        if (isinstance(channel, SpiceClientGLib.MainChannel) and
            not self._main_channel):
            self._main_channel = channel
            _SIGS.connect_after(
                self._main_channel, "channel-event",
                self._main_channel_event_cb)
            _SIGS.connect_after(
                self._main_channel, "notify::agent-connected",
                self._agent_connected_cb)

        elif (isinstance(channel, SpiceClientGLib.DisplayChannel) and
              not self._display):
            channel_id = channel.get_property("channel-id")

            if channel_id != 0:  # pragma: no cover
                log.debug("Spice multi-head unsupported")
                return

            display = SpiceClientGtk.Display.new(
                    self._spice_session, channel_id)
            self._set_display(display)

            _SIGS.connect_after(
                channel, "display-primary-create",
                self._display_primary_create_cb)
            self.emit("connected")

        elif (type(channel) in [SpiceClientGLib.PlaybackChannel,
                                SpiceClientGLib.RecordChannel] and
                                not self._audio):
            # It's unclear why we need this audio handle, but it
            # does matter:
            # https://bugzilla.redhat.com/show_bug.cgi?id=1881080
            self._audio = SpiceClientGLib.Audio.get(self._spice_session, None)

    def _agent_connected_cb(self, src, val):
        self.emit("agent-connected")  # pragma: no cover

    def _display_primary_create_cb(self, *args):
        self._set_desktop_resolution(args[2], args[3])


    ################################
    # Internal API implementations #
    ################################

    def _close(self):
        if self._spice_session is not None:
            _SIGS.disconnect_obj_signals(self._spice_session)
            self._spice_session.disconnect()
        self._spice_session = None
        self._audio = None

        for channel in self._channels:
            _SIGS.disconnect_obj_signals(channel)
        self._channels = None

        self._main_channel = None

        _SIGS.disconnect_obj_signals(self._usbdev_manager)
        self._usbdev_manager = None

    def _is_open(self):
        return self._spice_session is not None

    def _set_grab_keys(self, keys):
        seq = SpiceClientGtk.GrabSequence.new(keys)
        self._display.set_grab_keys(seq)

    def _send_keys(self, keys):
        return self._display.send_keys([Gdk.keyval_from_name(k) for k in keys],
                                      SpiceClientGtk.DisplayKeyEvent.CLICK)

    def _has_agent(self):
        if not self._main_channel:
            return False  # pragma: no cover
        return self._main_channel.get_property("agent-connected")

    def _open_host(self):
        host, port, tlsport = self._ginfo.get_conn_host()
        self._create_spice_session()

        log.debug("Spice connecting to host=%s port=%s tlsport=%s",
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
        ignore = cred  # pragma: no cover
    def _set_password(self, cred):
        self._spice_session.set_property("password", cred)
        fd = self._get_fd_for_open()
        if fd is not None:
            self._spice_session.open_fd(fd)
        else:
            self._spice_session.connect()  # pragma: no cover

    def _get_scaling(self):
        if self._display:
            return self._display.get_property("scaling")
    def _set_scaling(self, scaling):
        if self._display:
            self._display.set_property("scaling", scaling)

    def _set_resizeguest(self, val):
        if self._display:
            self._display.set_property("resize-guest", val)
    def _get_resizeguest(self):
        if self._display:
            return self._display.get_property("resize-guest")
        return False  # pragma: no cover
    def _get_resizeguest_warning(self):
        if not self._has_agent():
            return _("Guest agent is not available.")

    def _usbdev_redirect_error(self, spice_usbdev_widget, spice_usb_device,
            errstr):  # pragma: no cover
        ignore = spice_usbdev_widget
        ignore = spice_usb_device
        self.emit("usb-redirect-error", errstr)

    def _get_usb_widget(self):
        if not self._spice_session:
            return  # pragma: no cover

        usbwidget = SpiceClientGtk.UsbDeviceWidget.new(self._spice_session,
            None)
        usbwidget.connect("connect-failed", self._usbdev_redirect_error)
        return usbwidget

    def _has_usb_redirection(self):
        if not self._spice_session or not self._usbdev_manager:
            return False  # pragma: no cover
        return True

    def _get_preferred_size(self):
        if (not self._display or
            self._get_scaling() or
            self._get_resizeguest()):
            return self._desktop_resolution

        # When scaling and resizeguest disabled, this usually matches the
        # VM resolution. But when host desktop scaling is used, spice will
        # intentionally have different values here.
        w = self._display.get_preferred_width()[1]
        h = self._display.get_preferred_height()[1]
        return (w, h)

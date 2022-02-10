#
# Copyright 2006-2009, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from .device import Device
from ..logger import log
from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


def _validate_port(name, val):
    if val is None:
        return val
    val = int(val)

    if val < 5900 and val != -1:
        raise ValueError(_("%s must be above 5900, or "
                           "-1 for auto allocation") % name)
    return val


class _GraphicsListen(XMLBuilder):
    XML_NAME = "listen"

    type = XMLProperty("./@type")
    address = XMLProperty("./@address")
    network = XMLProperty("./@network")
    socket = XMLProperty("./@socket")


class DeviceGraphics(Device):
    XML_NAME = "graphics"

    TYPE_SDL = "sdl"
    TYPE_VNC = "vnc"
    TYPE_RDP = "rdp"
    TYPE_SPICE = "spice"

    _XML_PROP_ORDER = ["type", "gl", "_port", "_tlsPort", "autoport", "websocket",
                       "keymap", "_listen",
                       "passwd", "display", "xauth"]

    keymap = XMLProperty("./@keymap")

    def _set_port(self, val):
        val = _validate_port("Port", val)
        self.autoport = self._get_default_autoport()
        self._port = val
    def _get_port(self):
        return self._port
    _port = XMLProperty("./@port", is_int=True)
    port = property(_get_port, _set_port)

    def _set_tlsport(self, val):
        val = _validate_port("TLS Port", val)
        self.autoport = self._get_default_autoport()
        self._tlsPort = val
    def _get_tlsport(self):
        return self._tlsPort
    _tlsPort = XMLProperty("./@tlsPort", is_int=True)
    tlsPort = property(_get_tlsport, _set_tlsport)

    autoport = XMLProperty("./@autoport", is_yesno=True)
    websocket = XMLProperty("./@websocket", is_int=True)

    xauth = XMLProperty("./@xauth")
    display = XMLProperty("./@display")


    def _set_listen(self, val):
        if val == "none":
            self._set_listen_none()
        elif val == "socket":
            self._remove_all_listens()
            obj = self.listens.add_new()
            obj.type = "socket"
        else:
            self._remove_all_listens()
            self._listen = val
    def _get_listen(self):
        return self._listen
    _listen = XMLProperty("./@listen")
    listen = property(_get_listen, _set_listen)

    type = XMLProperty("./@type")
    passwd = XMLProperty("./@passwd")
    passwdValidTo = XMLProperty("./@passwdValidTo")
    socket = XMLProperty("./@socket")
    connected = XMLProperty("./@connected")
    defaultMode = XMLProperty("./@defaultMode")

    listens = XMLChildProperty(_GraphicsListen)
    def _remove_all_listens(self):
        for listen in self.listens:
            self.remove_child(listen)

    def get_first_listen_type(self):
        if len(self.listens) > 0:
            return self.listens[0].type
        return None

    def _set_listen_none(self):
        self._remove_all_listens()
        self.listen = None
        self.port = None
        self.tlsPort = None
        self.autoport = None
        self.socket = None

        if self.conn.support.conn_graphics_listen_none():
            obj = self.listens.add_new()
            obj.type = "none"

    # Spice bits
    image_compression = XMLProperty("./image/@compression")
    streaming_mode = XMLProperty("./streaming/@mode")
    clipboard_copypaste = XMLProperty("./clipboard/@copypaste", is_yesno=True)
    mouse_mode = XMLProperty("./mouse/@mode")
    filetransfer_enable = XMLProperty("./filetransfer/@enable", is_yesno=True)
    gl = XMLProperty("./gl/@enable", is_yesno=True)
    rendernode = XMLProperty("./gl/@rendernode")
    zlib_compression = XMLProperty("./zlib/@compression")


    ##################
    # Default config #
    ##################

    def _listen_need_port(self):
        listen = self.get_first_listen_type()
        return not listen or listen in ["address", "network"]

    def _get_default_port(self):
        if self.type in ["vnc", "spice"] and self._listen_need_port():
            return -1
        return None

    def _get_default_tlsport(self):
        if self.type == "spice" and self._listen_need_port():
            return -1
        return None

    def _get_default_autoport(self):
        # By default, don't do this for VNC to maintain back compat with
        # old libvirt that didn't support 'autoport'
        if self.type != "spice":
            return None
        if (self.port == -1 and self.tlsPort == -1):
            return True
        return None

    def _default_type(self, guest):
        gtype = guest.default_graphics_type
        log.debug("App is configured with default_graphics=%s", gtype)

        if self.conn.is_xen():
            # Xen domcaps can advertise spice support, but we have historically
            # not defaulted to it for xen, so force vnc.
            log.debug("Not defaulting to spice for xen driver. Using vnc.")
            gtype = "vnc"

        if (gtype == "spice" and
            not guest.lookup_domcaps().supports_graphics_spice()):
            log.debug("spice requested but HV doesn't support it. Using vnc.")
            gtype = "vnc"
        return gtype

    def _default_image_compression(self, _guest):
        if self.type != "spice":
            return None
        if not self.conn.is_remote():
            log.debug("Local connection, disabling spice image "
                "compression.")
            return "off"
        return None

    def _default_spice_gl(self, _guest):
        # If spice GL but rendernode wasn't specified, hardcode
        # the first one
        if not self.rendernode:
            for nodedev in self.conn.fetch_all_nodedevs():
                if not nodedev.is_drm_render():
                    continue
                self.rendernode = nodedev.get_devnode().path
                break

    def set_defaults(self, guest):
        if not self.type:
            self.type = self._default_type(guest)

        if self.type == "sdl":
            if not self.xauth:
                self.xauth = os.path.expanduser("~/.Xauthority")
            if not self.display:
                self.display = os.environ.get("DISPLAY")

        if self.port is None:
            self.port = self._get_default_port()
        if self.tlsPort is None:
            self.tlsPort = self._get_default_tlsport()
        if self.autoport is None:
            self.autoport = self._get_default_autoport()

        if not self.image_compression:
            self.image_compression = self._default_image_compression(guest)
        if self.type == "spice" and self.gl:
            self._default_spice_gl(guest)

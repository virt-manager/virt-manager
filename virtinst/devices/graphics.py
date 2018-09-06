#
# Copyright 2006-2009, 2013 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import os

from .device import Device
from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


def _get_mode_prop(channel_type):
    xpath = "./channel[@name='%s']/@mode" % channel_type
    return XMLProperty(xpath)


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

    CHANNEL_TYPE_MAIN     = "main"
    CHANNEL_TYPE_DISPLAY  = "display"
    CHANNEL_TYPE_INPUTS   = "inputs"
    CHANNEL_TYPE_CURSOR   = "cursor"
    CHANNEL_TYPE_PLAYBACK = "playback"
    CHANNEL_TYPE_RECORD   = "record"

    KEYMAP_LOCAL = "local"
    KEYMAP_DEFAULT = "default"
    _special_keymaps = [KEYMAP_LOCAL, KEYMAP_DEFAULT]

    @staticmethod
    def valid_keymaps():
        """
        Return a list of valid keymap values.
        """
        from .. import hostkeymap

        orig_list = list(hostkeymap.keytable.values())
        sort_list = []

        orig_list.sort()
        for k in orig_list:
            if k not in sort_list:
                sort_list.append(k)

        return sort_list

    @staticmethod
    def pretty_type_simple(gtype):
        if (gtype in [DeviceGraphics.TYPE_VNC,
                      DeviceGraphics.TYPE_SDL,
                      DeviceGraphics.TYPE_RDP]):
            return str(gtype).upper()

        return str(gtype).capitalize()

    def __init__(self, *args, **kwargs):
        Device.__init__(self, *args, **kwargs)

        self._local_keymap = -1


    _XML_PROP_ORDER = ["type", "gl", "_port", "_tlsPort", "autoport",
                       "_keymap", "_listen",
                       "passwd", "display", "xauth"]

    def _get_local_keymap(self):
        if self._local_keymap == -1:
            from .. import hostkeymap
            self._local_keymap = hostkeymap.default_keymap()
        return self._local_keymap

    def _set_keymap(self, val):
        if val == self.KEYMAP_DEFAULT:
            # Leave it up to the hypervisor
            val = None
        elif val == self.KEYMAP_LOCAL:
            val = self._get_local_keymap()
        self._keymap = val
    def _get_keymap(self):
        return self._keymap
    _keymap = XMLProperty("./@keymap")
    keymap = property(_get_keymap, _set_keymap)

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

    channel_main_mode = _get_mode_prop(CHANNEL_TYPE_MAIN)
    channel_display_mode = _get_mode_prop(CHANNEL_TYPE_DISPLAY)
    channel_inputs_mode = _get_mode_prop(CHANNEL_TYPE_INPUTS)
    channel_cursor_mode = _get_mode_prop(CHANNEL_TYPE_CURSOR)
    channel_playback_mode = _get_mode_prop(CHANNEL_TYPE_PLAYBACK)
    channel_record_mode = _get_mode_prop(CHANNEL_TYPE_RECORD)

    xauth = XMLProperty("./@xauth")
    display = XMLProperty("./@display")


    def _set_listen(self, val):
        # Update the corresponding <listen> block
        find_listen = [l for l in self.listens if
                       (l.type == "address" and l.address == self._listen)]
        if find_listen:
            if val is None:
                self.remove_child(find_listen[0])
            else:
                find_listen[0].address = val
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
    def remove_all_listens(self):
        for listen in self.listens:
            self.remove_child(listen)

    def get_first_listen_type(self):
        if len(self.listens) > 0:
            return self.listens[0].type
        return None

    def set_listen_none(self):
        self.remove_all_listens()
        self.listen = None
        self.port = None
        self.tlsPort = None
        self.autoport = None
        self.socket = None

        if self.conn.check_support(
                self.conn.SUPPORT_CONN_GRAPHICS_LISTEN_NONE):
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


    ##################
    # Default config #
    ##################

    def _spice_supported(self):
        if not self.conn.is_qemu() and not self.conn.is_test():
            return False
        # Spice has issues on some host arches, like ppc, so whitelist it
        if self.conn.caps.host.cpu.arch not in ["i686", "x86_64"]:
            return False
        return True

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
        logging.debug("Using default_graphics=%s", gtype)
        if gtype == "spice" and not self._spice_supported():
            logging.debug("spice requested but HV doesn't support it. "
                          "Using vnc.")
            gtype = "vnc"
        return gtype

    def _default_image_compression(self, _guest):
        if self.type != "spice":
            return None
        if not self.conn.is_remote():
            logging.debug("Local connection, disabling spice image "
                "compression.")
            return "off"
        return None

    def _default_spice_gl(self, _guest):
        if not self.conn.check_support(
                self.conn.SUPPORT_CONN_SPICE_GL):
            raise ValueError(_("Host does not support spice GL"))

        # If spice GL but rendernode wasn't specified, hardcode
        # the first one
        if not self.rendernode and self.conn.check_support(
                self.conn.SUPPORT_CONN_SPICE_RENDERNODE):
            for nodedev in self.conn.fetch_all_nodedevs():
                if (nodedev.device_type != 'drm' or
                    nodedev.drm_type != 'render'):
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

#
# Copyright 2006-2009, 2013 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

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
    TYPES = [TYPE_VNC, TYPE_SDL, TYPE_RDP, TYPE_SPICE]

    CHANNEL_TYPE_MAIN     = "main"
    CHANNEL_TYPE_DISPLAY  = "display"
    CHANNEL_TYPE_INPUTS   = "inputs"
    CHANNEL_TYPE_CURSOR   = "cursor"
    CHANNEL_TYPE_PLAYBACK = "playback"
    CHANNEL_TYPE_RECORD   = "record"
    CHANNEL_TYPES = [CHANNEL_TYPE_MAIN, CHANNEL_TYPE_DISPLAY,
                     CHANNEL_TYPE_INPUTS, CHANNEL_TYPE_CURSOR,
                     CHANNEL_TYPE_PLAYBACK, CHANNEL_TYPE_RECORD]

    CHANNEL_MODE_SECURE   = "secure"
    CHANNEL_MODE_INSECURE = "insecure"
    CHANNEL_MODE_ANY      = "any"
    CHANNEL_MODES = [CHANNEL_MODE_SECURE, CHANNEL_MODE_INSECURE,
                     CHANNEL_MODE_ANY]

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


    _XML_PROP_ORDER = ["type", "gl", "port", "tlsPort", "autoport",
                       "keymap", "listen",
                       "passwd", "display", "xauth"]

    def _get_local_keymap(self):
        if self._local_keymap == -1:
            from .. import hostkeymap
            self._local_keymap = hostkeymap.default_keymap()
        return self._local_keymap

    def _set_keymap_converter(self, val):
        if val == self.KEYMAP_DEFAULT:
            # Leave it up to the hypervisor
            return None
        if val == self.KEYMAP_LOCAL:
            return self._get_local_keymap()
        return val
    keymap = XMLProperty("./@keymap", set_converter=_set_keymap_converter)

    def _set_port_converter(self, val):
        val = _validate_port("Port", val)
        self.autoport = self._get_default_autoport()
        return val
    def _set_tlsport_converter(self, val):
        val = _validate_port("TLS Port", val)
        self.autoport = self._get_default_autoport()
        return val
    def _listen_need_port(self):
        listen = self.get_first_listen_type()
        return not listen or listen in ["address", "network"]
    def _get_default_port(self):
        if (self.type == "vnc" or self.type == "spice") and self._listen_need_port():
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
    port = XMLProperty("./@port", is_int=True,
            set_converter=_set_port_converter,
            default_cb=_get_default_port)
    tlsPort = XMLProperty("./@tlsPort", is_int=True,
            set_converter=_set_tlsport_converter,
            default_cb=_get_default_tlsport)
    autoport = XMLProperty("./@autoport", is_yesno=True,
                           default_cb=_get_default_autoport)

    channel_main_mode = _get_mode_prop(CHANNEL_TYPE_MAIN)
    channel_display_mode = _get_mode_prop(CHANNEL_TYPE_DISPLAY)
    channel_inputs_mode = _get_mode_prop(CHANNEL_TYPE_INPUTS)
    channel_cursor_mode = _get_mode_prop(CHANNEL_TYPE_CURSOR)
    channel_playback_mode = _get_mode_prop(CHANNEL_TYPE_PLAYBACK)
    channel_record_mode = _get_mode_prop(CHANNEL_TYPE_RECORD)


    def _get_default_display(self):
        if self.type != "sdl":
            return None
        if "DISPLAY" not in os.environ:
            raise RuntimeError("No DISPLAY environment variable set.")
        return os.environ["DISPLAY"]
    def _get_default_xauth(self):
        if self.type != "sdl":
            return None
        return os.path.expanduser("~/.Xauthority")
    xauth = XMLProperty("./@xauth",
                        default_cb=_get_default_xauth)
    display = XMLProperty("./@display",
                          default_cb=_get_default_display)


    def _set_listen(self, val):
        # Update the corresponding <listen> block
        find_listen = [l for l in self.listens if
                       (l.type == "address" and l.address == self.listen)]
        if find_listen:
            if val is None:
                self.remove_child(find_listen[0])
            else:
                find_listen[0].address = val
        return val
    listen = XMLProperty("./@listen", set_converter=_set_listen)

    type = XMLProperty("./@type",
                       default_cb=lambda s: "vnc",
                       default_name="default")
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

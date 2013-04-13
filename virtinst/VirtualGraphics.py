#
# Copyright 2006-2009  Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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

import re
import os

from virtinst.VirtualDevice import VirtualDevice
from virtinst import support
from virtinst.XMLBuilderDomain import _xml_property


def _get_mode_prop(channel_type):
    # pylint: disable=W0212
    xpath = "./channel[@name='%s']/@mode" % channel_type
    def get_mode(s):
        return s._channels.get(channel_type, None)
    def set_mode(s, val):
        s._channels[channel_type] = val
    return _xml_property(get_mode, set_mode, xpath=xpath)


class VirtualGraphics(VirtualDevice):

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_GRAPHICS

    TYPE_SDL = "sdl"
    TYPE_VNC = "vnc"
    TYPE_RDP = "rdp"
    TYPE_SPICE = "spice"
    types = [TYPE_VNC, TYPE_SDL, TYPE_RDP, TYPE_SPICE]

    CHANNEL_TYPE_MAIN     = "main"
    CHANNEL_TYPE_DISPLAY  = "display"
    CHANNEL_TYPE_INPUTS   = "inputs"
    CHANNEL_TYPE_CURSOR   = "cursor"
    CHANNEL_TYPE_PLAYBACK = "playback"
    CHANNEL_TYPE_RECORD   = "record"
    channel_types = [CHANNEL_TYPE_MAIN, CHANNEL_TYPE_DISPLAY,
                     CHANNEL_TYPE_INPUTS, CHANNEL_TYPE_CURSOR,
                     CHANNEL_TYPE_PLAYBACK, CHANNEL_TYPE_RECORD]

    CHANNEL_MODE_SECURE   = "secure"
    CHANNEL_MODE_INSECURE = "insecure"
    CHANNEL_MODE_ANY      = "any"
    channel_modes = [CHANNEL_MODE_SECURE, CHANNEL_MODE_INSECURE,
                     CHANNEL_MODE_ANY]

    KEYMAP_LOCAL = "local"
    KEYMAP_DEFAULT = "default"
    _special_keymaps = [KEYMAP_LOCAL, KEYMAP_DEFAULT]

    @staticmethod
    def valid_keymaps():
        """
        Return a list of valid keymap values.
        """
        from virtinst import hostkeymap

        orig_list = hostkeymap.keytable.values()
        sort_list = []

        orig_list.sort()
        for k in orig_list:
            if k not in sort_list:
                sort_list.append(k)

        return sort_list

    @staticmethod
    def pretty_type_simple(gtype):
        if (gtype in [VirtualGraphics.TYPE_VNC,
                      VirtualGraphics.TYPE_SDL,
                      VirtualGraphics.TYPE_RDP]):
            return str(gtype).upper()

        return str(gtype).capitalize()

    def __init__(self, type=TYPE_VNC, port=-1, listen=None, passwd=None,
                 keymap=KEYMAP_DEFAULT, conn=None, parsexml=None,
                 parsexmlnode=None, tlsPort=-1, channels=None,
                 caps=None, passwdValidTo=None):
        # pylint: disable=W0622
        # Redefining built-in 'type', but it matches the XML so keep it

        VirtualDevice.__init__(self, conn, parsexml, parsexmlnode, caps)

        self._type   = None
        self._port   = None
        self._tlsPort = None
        self._listen = None
        self._passwd = None
        self._passwdValidTo = None
        self._keymap = None
        self._xauth = None
        self._display = None
        self._socket = None
        self._channels = {}
        self._local_keymap = -1

        if self._is_parse():
            return

        self.type = type
        self.port = port
        self.tlsPort = tlsPort
        self.keymap = keymap
        self.listen = listen
        self.passwd = passwd
        self.passwdValidTo = passwdValidTo
        if channels:
            self.channels = channels

    def _cache(self):
        # Make sure we've cached the _local_keymap value before copy()
        self._default_keymap()

    def _default_keymap(self, force_local=False):
        if (not force_local and self.conn and
            support.check_conn_support(self.conn,
                                support.SUPPORT_CONN_KEYMAP_AUTODETECT)):
            return None

        if self._local_keymap == -1:
            from virtinst import hostkeymap
            self._local_keymap = hostkeymap.default_keymap()
        return self._local_keymap

    def get_type(self):
        return self._type
    def set_type(self, val):
        if val not in self.types:
            raise ValueError(_("Unknown graphics type '%s'") % val)

        self._type = val
    type = _xml_property(get_type, set_type,
                         xpath="./@type")

    def _get_xauth(self):
        return self._xauth
    def _set_xauth(self, val):
        self._xauth = val
    xauth = _xml_property(_get_xauth, _set_xauth,
                          xpath="./@xauth")

    def _get_display(self):
        return self._display
    def _set_display(self, val):
        self._display = val
    display = _xml_property(_get_display, _set_display,
                            xpath="./@display")

    def get_keymap(self):
        if self._keymap == self.KEYMAP_DEFAULT:
            return self._default_keymap()
        if self._keymap == self.KEYMAP_LOCAL:
            return self._default_keymap(force_local=True)
        return self._keymap
    def set_keymap(self, val):
        # At this point, 'None' is a valid value
        if val is None:
            self._keymap = None
            return

        if val in self._special_keymaps:
            self._keymap = val
            return

        if type(val) is not str:
            raise ValueError(_("Keymap must be a string"))
        if val.lower() == self.KEYMAP_LOCAL:
            val = self._default_keymap(force_local=True)
        elif len(val) > 16:
            raise ValueError(_("Keymap must be less than 16 characters"))
        elif re.match("^[a-zA-Z0-9_-]*$", val) is None:
            raise ValueError(_("Keymap can only contain alphanumeric, "
                               "'_', or '-' characters"))

        self._keymap = val
    keymap = _xml_property(get_keymap, set_keymap,
                           xpath="./@keymap")

    def get_port(self):
        return self._port
    def set_port(self, val):
        if val is None:
            val = -1

        try:
            val = int(val)
        except:
            pass

        if (type(val) is not int or
            (val != -1 and (val < 5900 or val > 65535))):
            raise ValueError(_("VNC port must be a number between "
                               "5900 and 65535, or -1 for auto allocation"))
        self._port = val
    port = _xml_property(get_port, set_port,
                         get_converter=lambda s, x: int(x or -1),
                         xpath="./@port")

    def get_listen(self):
        return self._listen
    def set_listen(self, val):
        self._listen = val
    listen = _xml_property(get_listen, set_listen,
                           xpath="./@listen")

    def get_passwd(self):
        return self._passwd
    def set_passwd(self, val):
        self._passwd = val
    passwd = _xml_property(get_passwd, set_passwd,
                           xpath="./@passwd")

    def get_passwdValidTo(self):
        return self._passwdValidTo
    def set_passwdValidTo(self, val):
        self._passwdValidTo = val
    passwdValidTo = _xml_property(get_passwdValidTo, set_passwdValidTo,
                                  xpath="./@passwdValidTo")

    def _get_socket(self):
        return self._socket
    def _set_socket(self, val):
        self._socket = val
    socket = _xml_property(_get_socket, _set_socket,
                           xpath="./@socket")

    def get_tlsPort(self):
        return self._tlsPort
    def set_tlsPort(self, val):
        if val is None:
            val = -1

        try:
            val = int(val)
        except:
            pass

        if (type(val) is not int or
            (val != -1 and (val < 5900 or val > 65535))):
            raise ValueError(_("TLS port must be a number between "
                               "5900 and 65535, or -1 for auto allocation"))
        self._tlsPort = val
    tlsPort = _xml_property(get_tlsPort, set_tlsPort,
                            get_converter=lambda s, x: int(x or -1),
                            xpath="./@tlsPort")

    channel_main_mode = _get_mode_prop(CHANNEL_TYPE_MAIN)
    channel_display_mode = _get_mode_prop(CHANNEL_TYPE_DISPLAY)
    channel_inputs_mode = _get_mode_prop(CHANNEL_TYPE_INPUTS)
    channel_cursor_mode = _get_mode_prop(CHANNEL_TYPE_CURSOR)
    channel_playback_mode = _get_mode_prop(CHANNEL_TYPE_PLAYBACK)
    channel_record_mode = _get_mode_prop(CHANNEL_TYPE_RECORD)

    def _build_xml(self, port=None, listen=None, keymap=None, passwd=None,
                   display=None, xauth=None, tlsPort=None, canautoport=False,
                   passwdValidTo=None, socket=None):

        doautoport = (canautoport and
                      (port in [None, -1] and
                       tlsPort in [None, -1]))
        portxml     = (port is not None and (" port='%d'" % port) or "")
        tlsportxml  = (tlsPort is not None and (" tlsPort='%d'" % tlsPort) or "")
        autoportxml = (doautoport and " autoport='yes'" or "")

        keymapxml   = (keymap and (" keymap='%s'" % keymap) or "")
        listenxml   = (listen and (" listen='%s'" % listen) or "")
        passwdxml   = (passwd and (" passwd='%s'" % passwd) or "")
        passwdValidToxml = (passwdValidTo and
                            (" passwdValidTo='%s'" % passwdValidTo) or "")

        xauthxml    = (xauth and (" xauth='%s'" % xauth) or "")
        displayxml  = (display and (" display='%s'" % display) or "")

        socketxml   = (socket and (" socket='%s'" % socket) or "")

        xml = ("    " +
               "<graphics type='%s'" % self.type +
               portxml +
               tlsportxml +
               autoportxml +
               keymapxml +
               listenxml +
               passwdxml +
               passwdValidToxml +
               socketxml +
               displayxml +
               xauthxml +
               "/>")
        return xml

    def _sdl_config(self):
        if "DISPLAY" not in os.environ and not self.display:
            raise RuntimeError("No DISPLAY environment variable set.")

        disp  = self.display or os.environ["DISPLAY"]
        xauth = self.xauth or os.path.expanduser("~/.Xauthority")

        return self._build_xml(display=disp, xauth=xauth)

    def _spice_config(self):
        return self._build_xml(port=self.port, keymap=self.keymap,
                               passwd=self.passwd, listen=self.listen,
                               tlsPort=self.tlsPort, canautoport=True,
                               passwdValidTo=self.passwdValidTo)

    def _vnc_config(self):
        return self._build_xml(port=self.port, keymap=self.keymap,
                               passwd=self.passwd, listen=self.listen,
                               # VNC supports autoport, but use legacy
                               # syntax to not break XML tests
                               canautoport=False,
                               passwdValidTo=self.passwdValidTo,
                               socket=self.socket)

    def _get_xml_config(self):
        if self._type == self.TYPE_SDL:
            return self._sdl_config()
        if self._type == self.TYPE_SPICE:
            return self._spice_config()
        if self._type == self.TYPE_VNC:
            return self._vnc_config()
        else:
            raise ValueError(_("Unknown graphics type"))

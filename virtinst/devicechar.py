#
# Copyright 2009, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

from virtinst import VirtualDevice
from virtinst.xmlbuilder import XMLProperty


class _VirtualCharDevice(VirtualDevice):
    """
    Base class for all character devices. Shouldn't be instantiated
    directly.
    """

    TYPE_PTY      = "pty"
    TYPE_DEV      = "dev"
    TYPE_STDIO    = "stdio"
    TYPE_PIPE     = "pipe"
    TYPE_FILE     = "file"
    TYPE_VC       = "vc"
    TYPE_NULL     = "null"
    TYPE_TCP      = "tcp"
    TYPE_UDP      = "udp"
    TYPE_UNIX     = "unix"
    TYPE_SPICEVMC = "spicevmc"
    # We don't list the non-UI friendly types here
    _TYPES_FOR_ALL = [TYPE_PTY, TYPE_DEV, TYPE_FILE,
                      TYPE_TCP, TYPE_UDP, TYPE_UNIX]
    _TYPES_FOR_CHANNEL = [TYPE_SPICEVMC]
    TYPES = _TYPES_FOR_ALL

    MODE_CONNECT = "connect"
    MODE_BIND = "bind"
    MODES = [MODE_CONNECT, MODE_BIND]

    PROTOCOL_RAW = "raw"
    PROTOCOL_TELNET = "telnet"
    PROTOCOLS = [PROTOCOL_RAW, PROTOCOL_TELNET]

    CHANNEL_TARGET_GUESTFWD = "guestfwd"
    CHANNEL_TARGET_VIRTIO = "virtio"
    CHANNEL_TARGETS = [CHANNEL_TARGET_GUESTFWD,
                       CHANNEL_TARGET_VIRTIO]

    CONSOLE_TARGET_SERIAL = "serial"
    CONSOLE_TARGET_UML = "uml"
    CONSOLE_TARGET_XEN = "xen"
    CONSOLE_TARGET_VIRTIO = "virtio"
    CONSOLE_TARGETS = [CONSOLE_TARGET_SERIAL, CONSOLE_TARGET_UML,
                       CONSOLE_TARGET_XEN, CONSOLE_TARGET_VIRTIO]

    CHANNEL_NAME_SPICE = "com.redhat.spice.0"
    CHANNEL_NAME_QEMUGA = "org.qemu.guest_agent.0"
    CHANNEL_NAME_LIBGUESTFS = "org.libguestfs.channel.0"
    CHANNEL_NAMES = [CHANNEL_NAME_SPICE,
                     CHANNEL_NAME_QEMUGA,
                     CHANNEL_NAME_LIBGUESTFS]

    @staticmethod
    def pretty_channel_name(val):
        if val == _VirtualCharDevice.CHANNEL_NAME_SPICE:
            return "spice"
        if val == _VirtualCharDevice.CHANNEL_NAME_QEMUGA:
            return "qemu-ga"
        if val == _VirtualCharDevice.CHANNEL_NAME_LIBGUESTFS:
            return "libguestfs"
        return None

    @staticmethod
    def pretty_type(ctype):
        """
        Return a human readable description of the passed char type
        """
        desc = ""

        if ctype == _VirtualCharDevice.TYPE_PTY:
            desc = _("Pseudo TTY")
        elif ctype == _VirtualCharDevice.TYPE_DEV:
            desc = _("Physical host character device")
        elif ctype == _VirtualCharDevice.TYPE_STDIO:
            desc = _("Standard input/output")
        elif ctype == _VirtualCharDevice.TYPE_PIPE:
            desc = _("Named pipe")
        elif ctype == _VirtualCharDevice.TYPE_FILE:
            desc = _("Output to a file")
        elif ctype == _VirtualCharDevice.TYPE_VC:
            desc = _("Virtual console")
        elif ctype == _VirtualCharDevice.TYPE_NULL:
            desc = _("Null device")
        elif ctype == _VirtualCharDevice.TYPE_TCP:
            desc = _("TCP net console")
        elif ctype == _VirtualCharDevice.TYPE_UDP:
            desc = _("UDP net console")
        elif ctype == _VirtualCharDevice.TYPE_UNIX:
            desc = _("Unix socket")
        elif ctype == _VirtualCharDevice.TYPE_SPICEVMC:
            desc = _("Spice agent")

        return desc

    @staticmethod
    def pretty_mode(char_mode):
        """
        Return a human readable description of the passed char type
        """
        desc = ""

        if char_mode == _VirtualCharDevice.MODE_CONNECT:
            desc = _("Client mode")
        elif char_mode == _VirtualCharDevice.MODE_BIND:
            desc = _("Server mode")

        return desc

    def supports_property(self, propname, ro=False):
        """
        Whether the character dev type supports the passed property name
        """
        users = {
            "source_path"   : [self.TYPE_FILE, self.TYPE_UNIX,
                               self.TYPE_DEV,  self.TYPE_PIPE],
            "source_mode"   : [self.TYPE_UNIX, self.TYPE_TCP],
            "source_host"   : [self.TYPE_TCP, self.TYPE_UDP],
            "source_port"   : [self.TYPE_TCP, self.TYPE_UDP],
            "protocol"      : [self.TYPE_TCP],
            "bind_host"     : [self.TYPE_UDP],
            "bind_port"     : [self.TYPE_UDP],
        }

        if ro:
            users["source_path"] += [self.TYPE_PTY]

        if users.get(propname):
            return self.type in users[propname]
        return hasattr(self, propname)

    def _set_host_helper(self, hostparam, portparam, val):
        def parse_host(val):
            host, ignore, port = (val or "").partition(":")
            return host or None, port or None

        host, port = parse_host(val)
        if host:
            setattr(self, hostparam, host)
        if port:
            setattr(self, portparam, port)

    def set_friendly_source(self, val):
        self._set_host_helper("source_host", "source_port", val)
    def set_friendly_bind(self, val):
        self._set_host_helper("bind_host", "bind_port", val)
    def set_friendly_target(self, val):
        self._set_host_helper("target_address", "target_port", val)


    _XML_PROP_ORDER = ["type", "_has_mode_bind", "_has_mode_connect",
                       "bind_host", "bind_port",
                       "source_mode", "_source_path", "source_channel",
                       "source_host", "source_port",
                       "target_type", "target_name"]

    type = XMLProperty(
                doc=_("Method used to expose character device in the host."),
                xpath="./@type")

    _tty = XMLProperty("./@tty")
    _source_path = XMLProperty(xpath="./source/@path",
        doc=_("Host input path to attach to the guest."))

    def _get_source_path(self):
        source = self._source_path
        if source is None and self._tty:
            return self._tty
        return source
    def _set_source_path(self, val):
        self._source_path = val
    source_path = property(_get_source_path, _set_source_path)

    source_channel = XMLProperty(xpath="./source/@channel",
                                 doc=_("Source channel name."))

    def _get_default_source_mode(self):
        if self.type == self.TYPE_UDP:
            return self.MODE_CONNECT
        if not self.supports_property("source_mode"):
            return None
        return self.MODE_BIND
    def _make_sourcemode_xpath(self):
        if self.type == self.TYPE_UDP:
            return "./source[@mode='connect']/@mode"
        return "./source/@mode"
    source_mode = XMLProperty(name="char sourcemode",
                              doc=_("Target connect/listen mode."),
                              make_xpath_cb=_make_sourcemode_xpath,
                              default_cb=_get_default_source_mode)

    def _get_default_sourcehost(self):
        if not self.supports_property("source_host"):
            return None
        return "127.0.0.1"
    def _set_source_validate(self, val):
        if val is None or self.type != self.TYPE_UDP:
            return val
        if not self._has_mode_connect:
            self._has_mode_connect = self.MODE_CONNECT
        return val
    def _make_sourcehost_xpath(self):
        mode = self.source_mode
        if self.type == self.TYPE_UDP:
            mode = "connect"
        return "./source[@mode='%s']/@host" % mode
    source_host = XMLProperty(name="char sourcehost",
                              doc=_("Address to connect/listen to."),
                              make_xpath_cb=_make_sourcehost_xpath,
                              default_cb=_get_default_sourcehost,
                              set_converter=_set_source_validate)

    def _make_sourceport_xpath(self):
        return "./source[@mode='%s']/@service" % self.source_mode
    source_port = XMLProperty(name="char sourceport",
                        doc=_("Port on target host to connect/listen to."),
                        make_xpath_cb=_make_sourceport_xpath,
                        set_converter=_set_source_validate, is_int=True)

    _has_mode_connect = XMLProperty("./source[@mode='connect']/@mode")
    _has_mode_bind = XMLProperty("./source[@mode='bind']/@mode")

    def _set_bind_validate(self, val):
        if val is None:
            return None
        if not self._has_mode_bind:
            self._has_mode_bind = self.MODE_BIND
        return val
    bind_host = XMLProperty("./source[@mode='bind']/@host",
                            doc=_("Host address to bind to."),
                            set_converter=_set_bind_validate)
    bind_port = XMLProperty("./source[@mode='bind']/@service",
                            doc=_("Host port to bind to."),
                            set_converter=_set_bind_validate, is_int=True)

    def _get_default_protocol(self):
        if not self.supports_property("protocol"):
            return None
        return self.PROTOCOL_RAW
    protocol = XMLProperty("./protocol/@type",
                           doc=_("Format used when sending data."),
                           default_cb=_get_default_protocol)

    def _get_default_target_type(self):
        if self.virtual_device_type == "channel":
            return self.CHANNEL_TARGET_VIRTIO
        return None
    target_type = XMLProperty("./target/@type",
                              doc=_("Channel type as exposed in the guest."),
                              default_cb=_get_default_target_type)

    target_address = XMLProperty("./target/@address",
                        doc=_("Guest forward channel address in the guest."))

    target_port = XMLProperty("./target/@port", is_int=True,
                           doc=_("Guest forward channel port in the guest."))

    def _default_target_name(self):
        if self.type == self.TYPE_SPICEVMC:
            return self.CHANNEL_NAME_SPICE
        return None
    target_name = XMLProperty("./target/@name",
                           doc=_("Sysfs name of virtio port in the guest"),
                           default_cb=_default_target_name)


class VirtualConsoleDevice(_VirtualCharDevice):
    virtual_device_type = "console"
    TYPES = [_VirtualCharDevice.TYPE_PTY]


class VirtualSerialDevice(_VirtualCharDevice):
    virtual_device_type = "serial"


class VirtualParallelDevice(_VirtualCharDevice):
    virtual_device_type = "parallel"


class VirtualChannelDevice(_VirtualCharDevice):
    virtual_device_type = "channel"
    TYPES = (_VirtualCharDevice._TYPES_FOR_CHANNEL +
             _VirtualCharDevice._TYPES_FOR_ALL)


VirtualConsoleDevice.register_type()
VirtualSerialDevice.register_type()
VirtualParallelDevice.register_type()
VirtualChannelDevice.register_type()

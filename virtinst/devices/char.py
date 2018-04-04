#
# Copyright 2009, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class _DeviceChar(Device):
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
    TYPE_SPICEPORT = "spiceport"
    TYPE_NMDM = "nmdm"

    # We don't list the non-UI friendly types here
    _TYPES_FOR_ALL = [TYPE_PTY, TYPE_DEV, TYPE_FILE,
                      TYPE_TCP, TYPE_UDP, TYPE_UNIX]
    _TYPES_FOR_CHANNEL = [TYPE_SPICEVMC, TYPE_SPICEPORT]
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
    CHANNEL_NAME_SPICE_WEBDAV = "org.spice-space.webdav.0"
    CHANNEL_NAMES = [CHANNEL_NAME_SPICE,
                     CHANNEL_NAME_QEMUGA,
                     CHANNEL_NAME_LIBGUESTFS,
                     CHANNEL_NAME_SPICE_WEBDAV]

    @staticmethod
    def pretty_channel_name(val):
        if val == _DeviceChar.CHANNEL_NAME_SPICE:
            return "spice"
        if val == _DeviceChar.CHANNEL_NAME_QEMUGA:
            return "qemu-ga"
        if val == _DeviceChar.CHANNEL_NAME_LIBGUESTFS:
            return "libguestfs"
        if val == _DeviceChar.CHANNEL_NAME_SPICE_WEBDAV:
            return "spice-webdav"
        return None

    @staticmethod
    def pretty_type(ctype):
        """
        Return a human readable description of the passed char type
        """
        desc = ""

        if ctype == _DeviceChar.TYPE_PTY:
            desc = _("Pseudo TTY")
        elif ctype == _DeviceChar.TYPE_DEV:
            desc = _("Physical host character device")
        elif ctype == _DeviceChar.TYPE_STDIO:
            desc = _("Standard input/output")
        elif ctype == _DeviceChar.TYPE_PIPE:
            desc = _("Named pipe")
        elif ctype == _DeviceChar.TYPE_FILE:
            desc = _("Output to a file")
        elif ctype == _DeviceChar.TYPE_VC:
            desc = _("Virtual console")
        elif ctype == _DeviceChar.TYPE_NULL:
            desc = _("Null device")
        elif ctype == _DeviceChar.TYPE_TCP:
            desc = _("TCP net console")
        elif ctype == _DeviceChar.TYPE_UDP:
            desc = _("UDP net console")
        elif ctype == _DeviceChar.TYPE_UNIX:
            desc = _("Unix socket")
        elif ctype == _DeviceChar.TYPE_SPICEVMC:
            desc = _("Spice agent")
        elif ctype == _DeviceChar.TYPE_SPICEPORT:
            desc = _("Spice port")

        return desc

    @staticmethod
    def pretty_mode(char_mode):
        """
        Return a human readable description of the passed char type
        """
        desc = ""

        if char_mode == _DeviceChar.MODE_CONNECT:
            desc = _("Client mode")
        elif char_mode == _DeviceChar.MODE_BIND:
            desc = _("Server mode")

        return desc

    def supports_property(self, propname, ro=False):
        """
        Whether the character dev type supports the passed property name
        """
        users = {
            "source_path":      [self.TYPE_FILE, self.TYPE_UNIX,
                                    self.TYPE_DEV,  self.TYPE_PIPE],
            "source_mode":      [self.TYPE_UNIX, self.TYPE_TCP],
            "source_host":      [self.TYPE_TCP, self.TYPE_UDP],
            "source_port":      [self.TYPE_TCP, self.TYPE_UDP],
            "source_channel":   [self.TYPE_SPICEPORT],
            "source_master":    [self.TYPE_NMDM],
            "source_slave":     [self.TYPE_NMDM],
            "protocol":         [self.TYPE_TCP],
            "bind_host":        [self.TYPE_UDP],
            "bind_port":        [self.TYPE_UDP],
        }

        if ro:
            users["source_path"] += [self.TYPE_PTY]

        if users.get(propname):
            return self.type in users[propname]
        return hasattr(self, propname)

    def set_defaults(self, guest):
        ignore = guest
        if not self.source_mode and self.supports_property("source_mode"):
            self.source_mode = self.MODE_BIND


    def _set_host_helper(self, hostparam, portparam, val):
        def parse_host(val):
            host, ignore, port = (val or "").partition(":")
            return host or None, port or None

        host, port = parse_host(val)
        if not host:
            host = "127.0.0.1"
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
                       "source_mode", "source_host", "source_port",
                       "_source_path", "source_channel",
                       "target_type", "target_name"]

    type = XMLProperty("./@type")
    _tty = XMLProperty("./@tty")
    _source_path = XMLProperty("./source/@path")

    def _get_source_path(self):
        source = self._source_path
        if source is None and self._tty:
            return self._tty
        return source
    def _set_source_path(self, val):
        self._source_path = val
    source_path = property(_get_source_path, _set_source_path)

    source_channel = XMLProperty("./source/@channel")
    source_master = XMLProperty("./source/@master")
    source_slave = XMLProperty("./source/@slave")


    ###################
    # source handling #
    ###################

    source_mode = XMLProperty("./source/@mode")

    _has_mode_connect = XMLProperty("./source[@mode='connect']/@mode")
    _has_mode_bind = XMLProperty("./source[@mode='bind']/@mode")

    def _set_source_validate(self, val):
        if val is None:
            return None
        self._has_mode_connect = self.MODE_CONNECT
        return val
    source_host = XMLProperty("./source[@mode='connect']/@host",
                            set_converter=_set_source_validate)
    source_port = XMLProperty("./source[@mode='connect']/@service",
                              set_converter=_set_source_validate,
                              is_int=True)

    def _set_bind_validate(self, val):
        if val is None:
            return None
        self._has_mode_bind = self.MODE_BIND
        return val
    bind_host = XMLProperty("./source[@mode='bind']/@host",
                            set_converter=_set_bind_validate)
    bind_port = XMLProperty("./source[@mode='bind']/@service",
                            set_converter=_set_bind_validate,
                            is_int=True)


    #######################
    # Remaining XML props #
    #######################

    def _get_default_protocol(self):
        if not self.supports_property("protocol"):
            return None
        return self.PROTOCOL_RAW
    protocol = XMLProperty("./protocol/@type",
                           default_cb=_get_default_protocol)

    def _get_default_target_type(self):
        if self.DEVICE_TYPE == "channel":
            return self.CHANNEL_TARGET_VIRTIO
        return None
    target_type = XMLProperty("./target/@type",
                              default_cb=_get_default_target_type)

    target_address = XMLProperty("./target/@address")

    target_port = XMLProperty("./target/@port", is_int=True)

    def _default_target_name(self):
        if self.type == self.TYPE_SPICEVMC:
            return self.CHANNEL_NAME_SPICE
        return None
    target_name = XMLProperty("./target/@name",
                           default_cb=_default_target_name)

    log_file = XMLProperty("./log/@file")
    log_append = XMLProperty("./log/@append", is_onoff=True)


class DeviceConsole(_DeviceChar):
    XML_NAME = "console"
    TYPES = [_DeviceChar.TYPE_PTY]


class DeviceSerial(_DeviceChar):
    XML_NAME = "serial"


class DeviceParallel(_DeviceChar):
    XML_NAME = "parallel"


class DeviceChannel(_DeviceChar):
    XML_NAME = "channel"
    TYPES = (_DeviceChar._TYPES_FOR_CHANNEL +
             _DeviceChar._TYPES_FOR_ALL)

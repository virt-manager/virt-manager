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

    CHANNEL_NAME_SPICE = "com.redhat.spice.0"
    CHANNEL_NAME_QEMUGA = "org.qemu.guest_agent.0"
    CHANNEL_NAME_LIBGUESTFS = "org.libguestfs.channel.0"
    CHANNEL_NAME_SPICE_WEBDAV = "org.spice-space.webdav.0"
    CHANNEL_NAMES = [CHANNEL_NAME_SPICE,
                     CHANNEL_NAME_QEMUGA,
                     CHANNEL_NAME_LIBGUESTFS,
                     CHANNEL_NAME_SPICE_WEBDAV]

    @classmethod
    def get_recommended_types(cls, _guest):
        if cls.XML_NAME == "console":
            return [cls.TYPE_PTY]

        ret = [cls.TYPE_PTY, cls.TYPE_FILE, cls.TYPE_UNIX]
        if cls.XML_NAME == "channel":
            ret = [cls.TYPE_SPICEVMC, cls.TYPE_SPICEPORT] + ret
        return ret

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


    _XML_PROP_ORDER = ["type",
                       "bind_host", "bind_port",
                       "source_mode", "source_host", "source_port",
                       "_source_path", "source_channel",
                       "target_type", "target_name", "target_state"]

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

    target_state = XMLProperty("./target/@state")


    ###################
    # source handling #
    ###################

    source_mode = XMLProperty("./source/@mode")

    source_host = XMLProperty("./source[@mode='connect']/@host")
    source_port = XMLProperty(
            "./source[@mode='connect']/@service", is_int=True)

    bind_host = XMLProperty("./source[@mode='bind']/@host")
    bind_port = XMLProperty("./source[@mode='bind']/@service", is_int=True)


    #######################
    # Remaining XML props #
    #######################

    protocol = XMLProperty("./protocol/@type")

    target_address = XMLProperty("./target/@address")
    target_port = XMLProperty("./target/@port", is_int=True)
    target_type = XMLProperty("./target/@type")
    target_name = XMLProperty("./target/@name")

    log_file = XMLProperty("./log/@file")
    log_append = XMLProperty("./log/@append", is_onoff=True)


    ##################
    # Default config #
    ##################

    def set_defaults(self, _guest):
        if not self.source_mode and self.supports_property("source_mode"):
            self.source_mode = "bind"
        if not self.protocol and self.supports_property("protocol"):
            self.protocol = "raw"
        if not self.target_type and self.DEVICE_TYPE == "channel":
            self.target_type = "virtio"
        if not self.target_name and self.type == self.TYPE_SPICEVMC:
            self.target_name = self.CHANNEL_NAME_SPICE



class DeviceConsole(_DeviceChar):
    XML_NAME = "console"


class DeviceSerial(_DeviceChar):
    XML_NAME = "serial"


class DeviceParallel(_DeviceChar):
    XML_NAME = "parallel"


class DeviceChannel(_DeviceChar):
    XML_NAME = "channel"

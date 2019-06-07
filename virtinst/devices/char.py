#
# Copyright 2009, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device, DeviceSeclabel
from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty
from .. import xmlutil


def _set_host_helper(obj, hostparam, portparam, val):
    def parse_host(val):
        host, ignore, port = (val or "").partition(":")
        return host or None, port or None

    host, port = parse_host(val)
    if port and not host:
        host = "127.0.0.1"
    xmlutil.set_prop_path(obj, hostparam, host)
    if port:
        xmlutil.set_prop_path(obj, portparam, port)


class CharSource(XMLBuilder):
    XML_NAME = "source"
    _XML_PROP_ORDER = ["bind_host", "bind_service",
                       "mode", "connect_host", "connect_service",
                       "path", "channel"]

    def set_friendly_connect(self, val):
        _set_host_helper(self, "connect_host", "connect_service", val)
    def set_friendly_bind(self, val):
        _set_host_helper(self, "bind_host", "bind_service", val)
    def set_friendly_host(self, val):
        _set_host_helper(self, "host", "service", val)

    seclabels = XMLChildProperty(DeviceSeclabel)

    host = XMLProperty("./@host")
    service = XMLProperty("./@service", is_int=True)
    path = XMLProperty("./@path")
    channel = XMLProperty("./@channel")
    master = XMLProperty("./@master")
    slave = XMLProperty("./@slave")
    mode = XMLProperty("./@mode")

    # It's weird to track these properties here, since the XML is set on
    # the parent, but this is how libvirt does it internally, which means
    # everything that shares a charsource has these values too.
    protocol = XMLProperty("./../protocol/@type")
    log_file = XMLProperty("./../log/@file")
    log_append = XMLProperty("./../log/@append", is_onoff=True)


    # Convenience source helpers for setting connect/bind host and service
    connect_host = XMLProperty("./../source[@mode='connect']/@host")
    connect_service = XMLProperty(
            "./../source[@mode='connect']/@service", is_int=True)
    bind_host = XMLProperty("./../source[@mode='bind']/@host")
    bind_service = XMLProperty("./../source[@mode='bind']/@service", is_int=True)


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

    def set_friendly_target(self, val):
        _set_host_helper(self, "target_address", "target_port", val)

    _XML_PROP_ORDER = ["type", "source",
                       "target_type", "target_name", "target_state"]

    type = XMLProperty("./@type")
    source = XMLChildProperty(CharSource, is_single=True)

    target_address = XMLProperty("./target/@address")
    target_port = XMLProperty("./target/@port", is_int=True)
    target_type = XMLProperty("./target/@type")
    target_name = XMLProperty("./target/@name")
    target_state = XMLProperty("./target/@state")
    target_model_name = XMLProperty("./target/model/@name")


    ##################
    # Default config #
    ##################

    def set_defaults(self, _guest):
        if (not self.source.mode and
            self.type in [self.TYPE_UNIX, self.TYPE_TCP]):
            self.source.mode = "bind"
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

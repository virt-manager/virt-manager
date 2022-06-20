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
    tls = XMLProperty("./@tls", is_yesno=True)

    # for qemu-vdagent channel
    clipboard_copypaste = XMLProperty("./clipboard/@copypaste", is_yesno=True)
    mouse_mode = XMLProperty("./mouse/@mode")

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
    TYPE_QEMUVDAGENT = "qemu-vdagent"

    CHANNEL_NAME_SPICE = "com.redhat.spice.0"
    CHANNEL_NAME_QEMUGA = "org.qemu.guest_agent.0"
    CHANNEL_NAME_LIBGUESTFS = "org.libguestfs.channel.0"
    CHANNEL_NAME_SPICE_WEBDAV = "org.spice-space.webdav.0"
    CHANNEL_NAMES = [CHANNEL_NAME_SPICE,
                     CHANNEL_NAME_QEMUGA,
                     CHANNEL_NAME_LIBGUESTFS,
                     CHANNEL_NAME_SPICE_WEBDAV]

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
        if not self.target_name and (self.type == self.TYPE_SPICEVMC or
                self.type == self.TYPE_QEMUVDAGENT):
            self.target_name = self.CHANNEL_NAME_SPICE



class DeviceConsole(_DeviceChar):
    @staticmethod
    def get_console_duplicate(guest, serial):
        """
        Determine if the passed serial device has a duplicate
        <console> device in the passed Guest
        """
        if serial.DEVICE_TYPE != "serial":
            return

        consoles = guest.devices.console
        if not consoles:
            return  # pragma: no cover

        console = consoles[0]
        if (console.type == serial.type and
            (console.target_type is None or console.target_type == "serial")):
            return console

    XML_NAME = "console"


class DeviceSerial(_DeviceChar):
    XML_NAME = "serial"


class DeviceParallel(_DeviceChar):
    XML_NAME = "parallel"


class DeviceChannel(_DeviceChar):
    XML_NAME = "channel"

#
# Copyright 2009  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

import VirtualDevice
from _util import  xml_escape

from XMLBuilderDomain import _xml_property
from virtinst import _gettext as _

class VirtualCharDevice(VirtualDevice.VirtualDevice):
    """
    Base class for all character devices. Shouldn't be instantiated
    directly.
    """

    DEV_SERIAL   = "serial"
    DEV_PARALLEL = "parallel"
    DEV_CONSOLE  = "console"
    DEV_CHANNEL  = "channel"
    dev_types    = [ DEV_SERIAL, DEV_PARALLEL, DEV_CONSOLE, DEV_CHANNEL]

    CHAR_PTY      = "pty"
    CHAR_DEV      = "dev"
    CHAR_STDIO    = "stdio"
    CHAR_PIPE     = "pipe"
    CHAR_FILE     = "file"
    CHAR_VC       = "vc"
    CHAR_NULL     = "null"
    CHAR_TCP      = "tcp"
    CHAR_UDP      = "udp"
    CHAR_UNIX     = "unix"
    CHAR_SPICEVMC = "spicevmc"
    char_types  = [ CHAR_PTY, CHAR_DEV, CHAR_STDIO, CHAR_FILE, CHAR_VC,
                    CHAR_PIPE, CHAR_NULL, CHAR_TCP, CHAR_UDP, CHAR_UNIX,
                    CHAR_SPICEVMC ]

    _non_channel_types = char_types[:]
    _non_channel_types.remove(CHAR_SPICEVMC)

    char_types_for_dev_type = {
        DEV_SERIAL: _non_channel_types,
        DEV_PARALLEL: _non_channel_types,
        DEV_CONSOLE: _non_channel_types,
        DEV_CHANNEL: [ CHAR_SPICEVMC ],
    }

    CHAR_MODE_CONNECT = "connect"
    CHAR_MODE_BIND = "bind"
    char_modes = [ CHAR_MODE_CONNECT, CHAR_MODE_BIND ]

    CHAR_PROTOCOL_RAW = "raw"
    CHAR_PROTOCOL_TELNET = "telnet"
    char_protocols = [ CHAR_PROTOCOL_RAW, CHAR_PROTOCOL_TELNET ]

    CHAR_CHANNEL_TARGET_GUESTFWD = "guestfwd"
    CHAR_CHANNEL_TARGET_VIRTIO = "virtio"
    target_types = [ CHAR_CHANNEL_TARGET_GUESTFWD,
                     CHAR_CHANNEL_TARGET_VIRTIO ]

    CHAR_CHANNEL_ADDRESS_VIRTIO_SERIAL = "virtio-serial"
    address_types = [ CHAR_CHANNEL_ADDRESS_VIRTIO_SERIAL ]

    CHAR_CONSOLE_TARGET_SERIAL = "serial"
    CHAR_CONSOLE_TARGET_UML = "uml"
    CHAR_CONSOLE_TARGET_XEN = "xen"
    CHAR_CONSOLE_TARGET_VIRTIO = "virtio"

    has_target = False

    def get_char_type_desc(char_type):
        """
        Return a human readable description of the passed char type
        """
        desc = ""

        if char_type == VirtualCharDevice.CHAR_PTY:
            desc = _("Pseudo TTY")
        elif char_type == VirtualCharDevice.CHAR_DEV:
            desc = _("Physical host character device")
        elif char_type == VirtualCharDevice.CHAR_STDIO:
            desc = _("Standard input/output")
        elif char_type == VirtualCharDevice.CHAR_PIPE:
            desc = _("Named pipe")
        elif char_type == VirtualCharDevice.CHAR_FILE:
            desc = _("Output to a file")
        elif char_type == VirtualCharDevice.CHAR_VC:
            desc = _("Virtual console")
        elif char_type == VirtualCharDevice.CHAR_NULL:
            desc = _("Null device")
        elif char_type == VirtualCharDevice.CHAR_TCP:
            desc = _("TCP net console")
        elif char_type == VirtualCharDevice.CHAR_UDP:
            desc = _("UDP net console")
        elif char_type == VirtualCharDevice.CHAR_UNIX:
            desc = _("Unix socket")
        elif char_type == VirtualCharDevice.CHAR_SPICEVMC:
            desc = _("Spice agent")

        return desc
    get_char_type_desc = staticmethod(get_char_type_desc)

    def get_char_mode_desc(char_mode):
        """
        Return a human readable description of the passed char type
        """
        desc = ""

        if char_mode == VirtualCharDevice.CHAR_MODE_CONNECT:
            desc = _("Client mode")
        elif char_mode == VirtualCharDevice.CHAR_MODE_BIND:
            desc = _("Server mode")

        return desc
    get_char_mode_desc = staticmethod(get_char_mode_desc)

    # 'char_type' of class (must be properly set in subclass)
    _char_type = None

    def get_dev_instance(conn, dev_type, char_type):
        """
        Set up the class attributes for the passed char_type
        """

        # By default, all the possible parameters are enabled for the
        # device class. We go through here and del() all the ones that
        # don't apply. This is kind of whacky, but it's nice to to
        # allow an API user to just use hasattr(obj, paramname) to see
        # what parameters apply, instead of having to hardcode all that
        # information.
        if char_type == VirtualCharDevice.CHAR_PTY:
            c = VirtualCharPtyDevice
        elif char_type == VirtualCharDevice.CHAR_STDIO:
            c = VirtualCharStdioDevice
        elif char_type == VirtualCharDevice.CHAR_NULL:
            c = VirtualCharNullDevice
        elif char_type == VirtualCharDevice.CHAR_VC:
            c = VirtualCharVcDevice
        elif char_type == VirtualCharDevice.CHAR_DEV:
            c = VirtualCharDevDevice
        elif char_type == VirtualCharDevice.CHAR_FILE:
            c = VirtualCharFileDevice
        elif char_type == VirtualCharDevice.CHAR_PIPE:
            c = VirtualCharPipeDevice
        elif char_type == VirtualCharDevice.CHAR_TCP:
            c = VirtualCharTcpDevice
        elif char_type == VirtualCharDevice.CHAR_UNIX:
            c = VirtualCharUnixDevice
        elif char_type == VirtualCharDevice.CHAR_UDP:
            c = VirtualCharUdpDevice
        elif char_type == VirtualCharDevice.CHAR_SPICEVMC:
            c = VirtualCharSpicevmcDevice
        else:
            raise ValueError(_("Unknown character device type '%s'.") %
                             char_type)

        if dev_type == VirtualCharDevice.DEV_CONSOLE:
            return VirtualConsoleDevice(conn)

        return c(conn, dev_type)
    get_dev_instance = staticmethod(get_dev_instance)

    def __init__(self, conn, dev_type,
                 parsexml=None, parsexmlnode=None, caps=None):
        if dev_type not in self.dev_types:
            raise ValueError(_("Unknown character device type '%s'") % dev_type)
        self._dev_type = dev_type
        self._virtual_device_type = self._dev_type

        VirtualDevice.VirtualDevice.__init__(self, conn,
                                             parsexml, parsexmlnode, caps)

        # Init
        self._source_path = None
        self._source_mode = self.CHAR_MODE_BIND
        self._source_host = "127.0.0.1"
        self._source_port = None
        self._target_type = None
        self._target_address = None
        self._target_port = None
        self._target_name = None
        self._bind_host = None
        self._bind_port = None
        self._protocol = self.CHAR_PROTOCOL_RAW
        self._address_type = None

        if self.char_type == self.CHAR_UDP:
            self._source_mode = self.CHAR_MODE_CONNECT

        if self._is_parse():
            return

        if not self._char_type:
            raise ValueError("Must be instantiated through a subclass.")

        self.char_type = self._char_type

    def supports_property(self, propname, ro=False):
        """
        Whether the character dev type supports the passed property name
        """
        users = {
            "source_path"   : [self.CHAR_FILE, self.CHAR_UNIX,
                               self.CHAR_DEV,  self.CHAR_PIPE],
            "source_mode"   : [self.CHAR_UNIX, self.CHAR_TCP],
            "source_host"   : [self.CHAR_TCP, self.CHAR_UDP],
            "source_port"   : [self.CHAR_TCP, self.CHAR_UDP],
            "protocol"      : [self.CHAR_TCP],
            "bind_host"     : [self.CHAR_UDP],
            "bind_port"     : [self.CHAR_UDP],
        }

        if ro:
            users["source_path"] += [self.CHAR_PTY]

        channel_users = {
            "target_name"   : [self.CHAR_CHANNEL_TARGET_VIRTIO],
        }

        if users.get(propname):
            return self.char_type in users[propname]
        if channel_users.get(propname):
            return (self.dev_type == self.DEV_CHANNEL and
                    self.target_type in channel_users[propname])
        return hasattr(self, propname)

    # Properties
    def get_dev_type(self):
        return self._dev_type
    dev_type = property(get_dev_type)

    def get_char_type(self):
        return self._char_type
    def set_char_type(self, val):
        if val not in self.char_types:
            raise ValueError(_("Unknown character device type '%s'")
                             % val)
        self._char_type = val
    char_type = _xml_property(get_char_type, set_char_type,
                doc=_("Method used to expose character device in the host."),
                xpath="./@type")

    # Properties functions used by the various subclasses
    def get_source_path(self):
        return self._source_path
    def set_source_path(self, val):
        self._source_path = val
    def _sourcepath_get_xpath(self):
        return "./source/@path | ./@tty"
    source_path = _xml_property(get_source_path, set_source_path,
                                xml_get_xpath=_sourcepath_get_xpath,
                                xpath="./source/@path")

    def get_source_mode(self):
        return self._source_mode
    def set_source_mode(self, val):
        if val not in self.char_modes:
            raise ValueError(_("Unknown character mode '%s'.") % val)
        self._source_mode = val
    def _sourcemode_xpath(self):
        if self.char_type == self.CHAR_UDP:
            return "./source[@mode='connect']/@mode"
        return "./source/@mode"
    source_mode = _xml_property(get_source_mode, set_source_mode,
                                xml_get_xpath=_sourcemode_xpath,
                                xml_set_xpath=_sourcemode_xpath)

    def get_source_host(self):
        return self._source_host
    def set_source_host(self, val):
        self._source_host = val
    def _sourcehost_xpath(self):
        return "./source[@mode='%s']/@host" % self.source_mode
    source_host = _xml_property(get_source_host, set_source_host,
                                xml_get_xpath=_sourcehost_xpath,
                                xml_set_xpath=_sourcehost_xpath)

    def get_source_port(self):
        return self._source_port
    def set_source_port(self, val):
        self._source_port = int(val)
    def _sourceport_xpath(self):
        return "./source[@mode='%s']/@service" % self.source_mode
    source_port = _xml_property(get_source_port, set_source_port,
                                xml_get_xpath=_sourceport_xpath,
                                xml_set_xpath=_sourceport_xpath)

    def get_bind_host(self):
        return self._bind_host
    def set_bind_host(self, val):
        self._bind_host = val
    bind_host = _xml_property(get_bind_host, set_bind_host,
                              xpath="./source[@mode='bind']/@host")

    def get_bind_port(self):
        return self._bind_port
    def set_bind_port(self, val):
        self._bind_port = int(val)
    bind_port = _xml_property(get_bind_port, set_bind_port,
                              xpath="./source[@mode='bind']/@service")

    def get_protocol(self):
        return self._protocol
    def set_protocol(self, val):
        if val not in self.char_protocols:
            raise ValueError(_("Unknown protocol '%s'.") % val)
        self._protocol = val
    protocol = _xml_property(get_protocol, set_protocol,
                             xpath="./protocol/@type")

    # GuestFWD target properties
    def get_target_type(self):
        return self._target_type
    def set_target_type(self, val):
        if val not in self.target_types:
            raise ValueError(_("Unknown target type '%s'. Must be in: ") % val,
                             self.target_types)
        self._target_type = val
    target_type = _xml_property(get_target_type, set_target_type,
                                doc=_("Channel type as exposed in the guest."),
                                xpath="./target/@type")

    def set_target_address(self, val):
        self._target_address = val
    def get_target_address(self):
        return self._target_address
    target_address = _xml_property(get_target_address, set_target_address,
                        doc=_("Guest forward channel address in the guest."),
                        xpath="./target/@address")

    def set_target_port(self, val):
        self._target_port = val
    def get_target_port(self):
        return self._target_port
    target_port = _xml_property(get_target_port, set_target_port,
                           doc=_("Guest forward channel port in the guest."),
                           xpath="./target/@port")

    def set_target_name(self, val):
        self._target_name = val
    def get_target_name(self):
        return self._target_name
    target_name = _xml_property(get_target_name, set_target_name,
                           doc=_("Sysfs name of virtio port in the guest"),
                           xpath="./target/@name")

    def get_address_type(self):
        return self._address_type
    def set_address_type(self, val):
        if val not in self.address_types:
            raise ValueError(_("Unknown address type '%s'. Must be in: ") % val,
                             self.address_types)
        self._address_type = val
    address_type = _xml_property(get_address_type, set_address_type,
                                doc=_("Channel type as exposed in the guest."),
                                xpath="./address/@type")

    # XML building helpers
    def _char_empty_xml(self):
        """
        Provide source xml for devices with no params (null, stdio, ...)
        """
        return ""

    def _char_file_xml(self):
        """
        Provide source xml for devs that require only a path (dev, pipe)
        """
        file_xml = ""
        mode_xml = ""
        if self.source_path:
            file_xml = " path='%s'" % xml_escape(self.source_path)
        else:
            raise ValueError(_("A source path is required for character "
                               "device type '%s'" % self.char_type))

        if self.supports_property("source_mode") and self.source_mode:
            mode_xml = " mode='%s'" % xml_escape(self.source_mode)

        xml = "      <source%s%s/>\n" % (mode_xml, file_xml)
        return xml

    def _char_xml(self):
        raise NotImplementedError("Must be implemented in subclass.")

    def _get_target_xml(self):
        xml = ""
        if not self.target_type:
            return xml

        xml = "      <target type='%s'" % self.target_type

        if self._dev_type == self.DEV_CHANNEL:
            if self.target_type == self.CHAR_CHANNEL_TARGET_GUESTFWD:
                if not self.target_address and not self.target_port:
                    raise RuntimeError("A target address and port must be "
                                       "specified for '%s'" % self.target_type)

                xml += " address='%s'" % self.target_address
                xml += " port='%s'" % self.target_port

            elif self.target_type == self.CHAR_CHANNEL_TARGET_VIRTIO:
                if self.target_name:
                    xml += " name='%s'" % self.target_name


        xml += "/>\n"
        return xml

    def _get_address_xml(self):
        xml = ""
        if not self.address_type:
            return xml

        xml = "      <address type='%s'" % self.address_type
        xml += "/>\n"
        return xml


    def _get_xml_config(self):
        xml  = "    <%s type='%s'" % (self._dev_type, self._char_type)
        char_xml = self._char_xml()
        target_xml = self._get_target_xml()
        has_target = (self._dev_type == self.DEV_CHANNEL or
                      self._dev_type == self.DEV_CONSOLE or
                      self.has_target)

        if target_xml and not has_target:
            raise RuntimeError(
                "Target parameters not used with '%s' devices, only '%s'" %
                (self._dev_type, self.DEV_CHANNEL))

        address_xml = self._get_address_xml()
        has_address = self._target_type == self.CHAR_CHANNEL_TARGET_VIRTIO
        if address_xml and not has_address:
            raise RuntimeError(
                "Address parameters not used with '%s' target, only '%s'" %
                (self._target_type, self.CHAR_CHANNEL_TARGET_VIRTIO))

        if char_xml or target_xml or address_xml:
            xml += ">"
            if char_xml:
                xml += "\n%s" % char_xml

            if target_xml:
                xml += "\n%s" % target_xml

            if address_xml:
                xml += "\n%s" % target_xml

            xml += "    </%s>" % self._dev_type
        else:
            xml += "/>"

        return xml

# Back compat class for building a simple PTY 'console' element
class VirtualConsoleDevice(VirtualCharDevice):
    _char_xml = VirtualCharDevice._char_empty_xml
    _char_type = VirtualCharDevice.CHAR_PTY

    def __init__(self, conn, parsexml=None, parsexmlnode=None):
        VirtualCharDevice.__init__(self, conn, VirtualCharDevice.DEV_CONSOLE,
                                   parsexml, parsexmlnode)

        self.target_types = [self.CHAR_CONSOLE_TARGET_SERIAL,
                             self.CHAR_CONSOLE_TARGET_VIRTIO,
                             self.CHAR_CONSOLE_TARGET_XEN,
                             self.CHAR_CONSOLE_TARGET_UML]

# Classes for each device 'type'

class VirtualCharPtyDevice(VirtualCharDevice):
    _char_type = VirtualCharDevice.CHAR_PTY
    _char_xml = VirtualCharDevice._char_empty_xml
    source_path = property(VirtualCharDevice.get_source_path,
                           VirtualCharDevice.set_source_path,
                           doc=_("PTY allocated to the guest."))
class VirtualCharStdioDevice(VirtualCharDevice):
    _char_type = VirtualCharDevice.CHAR_STDIO
    _char_xml = VirtualCharDevice._char_empty_xml
class VirtualCharNullDevice(VirtualCharDevice):
    _char_type = VirtualCharDevice.CHAR_NULL
    _char_xml = VirtualCharDevice._char_empty_xml
class VirtualCharVcDevice(VirtualCharDevice):
    _char_type = VirtualCharDevice.CHAR_VC
    _char_xml = VirtualCharDevice._char_empty_xml

class VirtualCharDevDevice(VirtualCharDevice):
    _char_type = VirtualCharDevice.CHAR_DEV
    _char_xml = VirtualCharDevice._char_file_xml
    source_path = property(VirtualCharDevice.get_source_path,
                           VirtualCharDevice.set_source_path,
                           doc=_("Host character device to attach to guest."))
class VirtualCharPipeDevice(VirtualCharDevice):
    _char_type = VirtualCharDevice.CHAR_PIPE
    _char_xml = VirtualCharDevice._char_file_xml
    source_path = property(VirtualCharDevice.get_source_path,
                           VirtualCharDevice.set_source_path,
                           doc=_("Named pipe to use for input and output."))
class VirtualCharFileDevice(VirtualCharDevice):
    _char_type = VirtualCharDevice.CHAR_FILE
    _char_xml = VirtualCharDevice._char_file_xml
    source_path = property(VirtualCharDevice.get_source_path,
                           VirtualCharDevice.set_source_path,
                           doc=_("File path to record device output."))

class VirtualCharUnixDevice(VirtualCharDevice):
    _char_type = VirtualCharDevice.CHAR_UNIX
    _char_xml = VirtualCharDevice._char_file_xml

    source_mode = property(VirtualCharDevice.get_source_mode,
                           VirtualCharDevice.set_source_mode,
                           doc=_("Target connect/listen mode."))
    source_path = property(VirtualCharDevice.get_source_path,
                           VirtualCharDevice.set_source_path,
                           doc=_("Unix socket path."))

class VirtualCharTcpDevice(VirtualCharDevice):
    _char_type = VirtualCharDevice.CHAR_TCP

    source_mode = property(VirtualCharDevice.get_source_mode,
                           VirtualCharDevice.set_source_mode,
                           doc=_("Target connect/listen mode."))
    source_host = property(VirtualCharDevice.get_source_host,
                           VirtualCharDevice.set_source_host,
                           doc=_("Address to connect/listen to."))
    source_port = property(VirtualCharDevice.get_source_port,
                           VirtualCharDevice.set_source_port,
                           doc=_("Port on target host to connect/listen to."))
    protocol = property(VirtualCharDevice.get_protocol,
                         VirtualCharDevice.set_protocol,
                         doc=_("Format used when sending data."))

    def _char_xml(self):
        if not self.source_host and not self.source_port:
            raise ValueError(_("A host and port must be specified."))

        xml = ("      <source mode='%s' host='%s' service='%s'/>\n" %
               (self.source_mode, self.source_host, self.source_port))
        xml += "      <protocol type='%s'/>\n" % self.protocol
        return xml

class VirtualCharUdpDevice(VirtualCharDevice):
    _char_type = VirtualCharDevice.CHAR_UDP

    bind_host = property(VirtualCharDevice.get_bind_host,
                         VirtualCharDevice.set_bind_host,
                         doc=_("Host address to bind to."))
    bind_port = property(VirtualCharDevice.get_bind_port,
                         VirtualCharDevice.set_bind_port,
                         doc=_("Host port to bind to."))
    source_host = property(VirtualCharDevice.get_source_host,
                           VirtualCharDevice.set_source_host,
                           doc=_("Host address to send output to."))
    source_port = property(VirtualCharDevice.get_source_port,
                           VirtualCharDevice.set_source_port,
                           doc=_("Host port to send output to."))

    # XXX: UDP: Only source _connect_ port required?
    def _char_xml(self):
        if not self.source_port:
            raise ValueError(_("A connection port must be specified."))

        xml = ""
        bind_xml = ""
        bind_host_xml = ""
        bind_port_xml = ""
        source_host_xml = ""

        if self.bind_port:
            bind_port_xml = " service='%s'" % self.bind_port
            if not self.bind_host:
                self.bind_host = "127.0.0.1"
        if self.bind_host:
            bind_host_xml = " host='%s'" % self.bind_host
        if self.source_host:
            source_host_xml = " host='%s'" % self.source_host

        if self.bind_host or self.bind_port:
            bind_xml = ("      <source mode='bind'%s%s/>\n" %
                        (bind_host_xml, bind_port_xml))

        xml += bind_xml
        xml += ("      <source mode='connect'%s service='%s'/>\n" %
                (source_host_xml, self.source_port))
        return xml

class VirtualCharSpicevmcDevice(VirtualCharDevice):
    _char_type = VirtualCharDevice.CHAR_SPICEVMC
    _char_xml = VirtualCharDevice._char_empty_xml
    target_types = [ VirtualCharDevice.CHAR_CHANNEL_TARGET_VIRTIO ]
    has_target = True

    def __init__(self, conn, dev_type=VirtualCharDevice.DEV_CHANNEL,
                 parsexml=None, parsexmlnode=None, caps=None):
        VirtualCharDevice.__init__(self, conn, dev_type,
                                   parsexml, parsexmlnode, caps)
        self._target_type = VirtualCharDevice.CHAR_CHANNEL_TARGET_VIRTIO
        self._target_name = "com.redhat.spice.0"

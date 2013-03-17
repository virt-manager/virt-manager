#
# Base class for all VM devices
#
# Copyright 2008  Red Hat, Inc.
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

from XMLBuilderDomain import XMLBuilderDomain, _xml_property
from virtinst import _gettext as _
import logging

class VirtualDevice(XMLBuilderDomain):
    """
    Base class for all domain xml device objects.
    """

    VIRTUAL_DEV_DISK            = "disk"
    VIRTUAL_DEV_NET             = "interface"
    VIRTUAL_DEV_INPUT           = "input"
    VIRTUAL_DEV_GRAPHICS        = "graphics"
    VIRTUAL_DEV_AUDIO           = "sound"
    VIRTUAL_DEV_HOSTDEV         = "hostdev"
    VIRTUAL_DEV_SERIAL          = "serial"
    VIRTUAL_DEV_PARALLEL        = "parallel"
    VIRTUAL_DEV_CHANNEL         = "channel"
    VIRTUAL_DEV_CONSOLE         = "console"
    VIRTUAL_DEV_VIDEO           = "video"
    VIRTUAL_DEV_CONTROLLER      = "controller"
    VIRTUAL_DEV_WATCHDOG        = "watchdog"
    VIRTUAL_DEV_FILESYSTEM      = "filesystem"
    VIRTUAL_DEV_SMARTCARD       = "smartcard"
    VIRTUAL_DEV_REDIRDEV        = "redirdev"
    VIRTUAL_DEV_MEMBALLOON      = "memballoon"

    # Ordering in this list is important: it will be the order the
    # Guest class outputs XML. So changing this may upset the test suite
    virtual_device_types = [VIRTUAL_DEV_DISK,
                            VIRTUAL_DEV_CONTROLLER,
                            VIRTUAL_DEV_FILESYSTEM,
                            VIRTUAL_DEV_NET,
                            VIRTUAL_DEV_INPUT,
                            VIRTUAL_DEV_GRAPHICS,
                            VIRTUAL_DEV_SERIAL,
                            VIRTUAL_DEV_PARALLEL,
                            VIRTUAL_DEV_CONSOLE,
                            VIRTUAL_DEV_CHANNEL,
                            VIRTUAL_DEV_AUDIO,
                            VIRTUAL_DEV_VIDEO,
                            VIRTUAL_DEV_HOSTDEV,
                            VIRTUAL_DEV_WATCHDOG,
                            VIRTUAL_DEV_SMARTCARD,
                            VIRTUAL_DEV_REDIRDEV,
                            VIRTUAL_DEV_MEMBALLOON]

    # General device type (disk, interface, etc.)
    _virtual_device_type = None

    def __init__(self, conn=None, parsexml=None, parsexmlnode=None, caps=None):
        """
        Initialize device state

        @param conn: libvirt connection to validate device against
        @type conn: virConnect
        """
        XMLBuilderDomain.__init__(self, conn, parsexml, parsexmlnode,
                                  caps=caps)

        self.alias = VirtualDeviceAlias(conn,
                                        parsexml=parsexml,
                                        parsexmlnode=parsexmlnode,
                                        caps=caps)
        self.address = VirtualDeviceAddress(conn,
                                            parsexml=parsexml,
                                            parsexmlnode=parsexmlnode,
                                            caps=caps)

        if not self._virtual_device_type:
            raise ValueError(_("Virtual device type must be set in subclass."))

        if self._virtual_device_type not in self.virtual_device_types:
            raise ValueError(_("Unknown virtual device type '%s'.") %
                             self._virtual_device_type)


    def get_virtual_device_type(self):
        return self._virtual_device_type
    virtual_device_type = property(get_virtual_device_type)

    def _get_xml_config(self):
        # See XMLBuilderDomain for docs
        raise NotImplementedError()

    def setup_dev(self, conn=None, meter=None):
        """
        Perform potentially hazardous device initialization, like
        storage creation or host device reset

        @param conn: Optional connection to use if neccessary. If not
                     specified, device's 'conn' will be used
        @param meter: Optional progress meter to use
        """
        # Will be overwritten by subclasses if necessary.
        ignore = conn
        ignore = meter
        return

    def set_address(self, addrstr):
        self.address = VirtualDeviceAddress(self.conn, addrstr=addrstr)


class VirtualDeviceAlias(XMLBuilderDomain):
    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None):
        XMLBuilderDomain.__init__(self, conn, parsexml, parsexmlnode,
                                  caps=caps)

        self._name = None


    def _get_name(self):
        return self._name
    def _set_name(self, val):
        self._name = val
    name = _xml_property(_get_name, _set_name, xpath="./alias/@name")

    def _get_xml_config(self):
        return ""

class VirtualDeviceAddress(XMLBuilderDomain):

    ADDRESS_TYPE_PCI           = "pci"
    ADDRESS_TYPE_DRIVE         = "drive"
    ADDRESS_TYPE_VIRTIO_SERIAL = "virtio-serial"
    ADDRESS_TYPE_CCID          = "ccid"
    ADDRESS_TYPE_SPAPR_VIO     = "spapr-vio"

    TYPES = [ADDRESS_TYPE_PCI, ADDRESS_TYPE_DRIVE,
             ADDRESS_TYPE_VIRTIO_SERIAL, ADDRESS_TYPE_CCID,
             ADDRESS_TYPE_SPAPR_VIO]

    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None,
                 addrstr=None):
        XMLBuilderDomain.__init__(self, conn, parsexml, parsexmlnode,
                                  caps=caps)

        self._type = None

        # PCI address:
        # <address type='pci' domain='0x0000' bus='0x00' slot='0x04' \
        #                     function='0x0'/>
        self._bus = None
        self._domain = None
        self._slot = None
        self._function = None

        # Drive address:
        # <address type='drive' controller='0' bus='0' unit='0'/>
        self._controller = None
        self._unit = None

        # VirtioSerial address:
        # <address type='virtio-serial' controller='1' bus='0' port='4'/>
        self._port = None

        # CCID address:
        # <address type='ccid' controller='0' slot='0'/>

        if addrstr:
            self.parse_friendly_address(addrstr)

    def parse_friendly_address(self, addrstr):
        try:
            if addrstr.count(":") in [1, 2] and addrstr.count("."):
                self.type = self.ADDRESS_TYPE_PCI
                addrstr, self.function = addrstr.split(".", 1)
                addrstr, self.slot = addrstr.rsplit(":", 1)
                self.domain = "0"
                if addrstr.count(":"):
                    self.domain, self.bus = addrstr.split(":", 1)
            elif addrstr == "spapr-vio":
                self.type = self.ADDRESS_TYPE_SPAPR_VIO
            else:
                raise ValueError(_("Could not determine or unsupported format of '%s'") % addrstr)
        except:
            logging.exception("Error parsing address.")
            return None


    def clear(self):
        self._type = None
        self._bus = None
        self._domain = None
        self._slot = None
        self._function = None
        self._controller = None
        self._unit = None
        self._port = None

        if self._is_parse():
            self._remove_child_xpath("./address")

    def _get_type(self):
        return self._type
    def _set_type(self, val):
        self._type = val
    type = _xml_property(_get_type, _set_type, xpath="./address/@type")

    def _get_domain(self):
        return self._domain
    def _set_domain(self, val):
        self._domain = val
    domain = _xml_property(_get_domain, _set_domain, xpath="./address/@domain")

    def _get_bus(self):
        return self._bus
    def _set_bus(self, val):
        self._bus = val
    bus = _xml_property(_get_bus, _set_bus, xpath="./address/@bus")

    def _get_slot(self):
        return self._slot
    def _set_slot(self, val):
        self._slot = val
    slot = _xml_property(_get_slot, _set_slot, xpath="./address/@slot")

    def _get_function(self):
        return self._function
    def _set_function(self, val):
        self._function = val
    function = _xml_property(_get_function, _set_function,
                             xpath="./address/@function")

    def _get_controller(self):
        return self._controller
    def _set_controller(self, val):
        self._controller = val
    controller = _xml_property(_get_controller, _set_controller,
                               xpath="./address/@controller")

    def _get_unit(self):
        return self._unit
    def _set_unit(self, val):
        self._unit = val
    unit = _xml_property(_get_unit, _set_unit, xpath="./address/@unit")

    def _get_port(self):
        return self._port
    def _set_port(self, val):
        self._port = val
    port = _xml_property(_get_port, _set_port, xpath="./address/@port")

    def _get_xml_config(self):
        if not self.type:
            return

        xml = "<address type='%s'" % self.type
        if self.type == self.ADDRESS_TYPE_PCI:
            xml += " domain='%s' bus='%s' slot='%s' function='%s'" % (self.domain, self.bus, self.slot, self.function)
        elif self.type == self.ADDRESS_TYPE_DRIVE:
            xml += " controller='%s' bus='%s' unit='%s'" % (self.controller, self.bus, self.unit)
        elif self.type == self.ADDRESS_TYPE_VIRTIO_SERIAL:
            xml += " controller='%s' bus='%s' port='%s'" % (self.controller, self.bus, self.port)
        elif self.type == self.ADDRESS_TYPE_CCID:
            xml += " controller='%s' slot='%s'" % (self.controller, self.slot)
        xml += "/>"
        return xml

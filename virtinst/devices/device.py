#
# Base class for all VM devices
#
# Copyright 2008, 2013 Red Hat, Inc.
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

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class DeviceAlias(XMLBuilder):
    _XML_ROOT_NAME = "alias"
    name = XMLProperty("./@name")


class DeviceBoot(XMLBuilder):
    _XML_ROOT_NAME = "boot"
    order = XMLProperty("./@order", is_int=True)


class DeviceAddress(XMLBuilder):
    """
    Examples:
    <address type='pci' domain='0x0000' bus='0x00' slot='0x04' function='0x0'/>
    <address type='drive' controller='0' bus='0' unit='0'/>
    <address type='ccid' controller='0' slot='0'/>
    <address type='virtio-serial' controller='1' bus='0' port='4'/>
    """

    ADDRESS_TYPE_PCI           = "pci"
    ADDRESS_TYPE_DRIVE         = "drive"
    ADDRESS_TYPE_VIRTIO_SERIAL = "virtio-serial"
    ADDRESS_TYPE_CCID          = "ccid"
    ADDRESS_TYPE_SPAPR_VIO     = "spapr-vio"

    TYPES = [ADDRESS_TYPE_PCI, ADDRESS_TYPE_DRIVE,
             ADDRESS_TYPE_VIRTIO_SERIAL, ADDRESS_TYPE_CCID,
             ADDRESS_TYPE_SPAPR_VIO]

    _XML_ROOT_NAME = "address"
    _XML_PROP_ORDER = ["type", "domain", "controller", "bus", "slot",
                       "function", "target", "unit", "multifunction"]

    def set_addrstr(self, addrstr):
        if addrstr is None:
            return

        if addrstr.count(":") in [1, 2] and "." in addrstr:
            self.type = self.ADDRESS_TYPE_PCI
            addrstr, self.function = addrstr.split(".", 1)
            addrstr, self.slot = addrstr.rsplit(":", 1)
            self.domain = "0"
            if ":" in addrstr:
                self.domain, self.bus = addrstr.split(":", 1)
        elif addrstr == "spapr-vio":
            self.type = self.ADDRESS_TYPE_SPAPR_VIO
        else:
            raise ValueError(_("Could not determine or unsupported "
                               "format of '%s'") % addrstr)

    def pretty_desc(self):
        pretty_desc = None
        if self.type == self.ADDRESS_TYPE_DRIVE:
            pretty_desc = _("%s:%s:%s:%s" %
                            (self.controller, self.bus, self.target, self.unit))
        return pretty_desc

    def compare_controller(self, controller, dev_bus):
        if (controller.type == dev_bus and
            controller.index == self.controller):
            return True
        return False


    type = XMLProperty("./@type")
    # type=pci
    domain = XMLProperty("./@domain", is_int=True)
    bus = XMLProperty("./@bus", is_int=True)
    slot = XMLProperty("./@slot", is_int=True)
    function = XMLProperty("./@function", is_int=True)
    multifunction = XMLProperty("./@multifunction", is_onoff=True)
    # type=drive
    controller = XMLProperty("./@controller", is_int=True)
    unit = XMLProperty("./@unit", is_int=True)
    port = XMLProperty("./@port", is_int=True)
    target = XMLProperty("./@target", is_int=True)
    # type=spapr-vio
    reg = XMLProperty("./@reg")
    # type=ccw
    cssid = XMLProperty("./@cssid")
    ssid = XMLProperty("./@ssid")
    devno = XMLProperty("./@devno")
    # type=isa
    iobase = XMLProperty("./@iobase")
    irq = XMLProperty("./@irq")
    # type=dimm
    base = XMLProperty("./@base")


class Device(XMLBuilder):
    """
    Base class for all domain xml device objects.
    """

    DEVICE_DISK            = "disk"
    DEVICE_NET             = "interface"
    DEVICE_INPUT           = "input"
    DEVICE_GRAPHICS        = "graphics"
    DEVICE_AUDIO           = "sound"
    DEVICE_HOSTDEV         = "hostdev"
    DEVICE_SERIAL          = "serial"
    DEVICE_PARALLEL        = "parallel"
    DEVICE_CHANNEL         = "channel"
    DEVICE_CONSOLE         = "console"
    DEVICE_VIDEO           = "video"
    DEVICE_CONTROLLER      = "controller"
    DEVICE_WATCHDOG        = "watchdog"
    DEVICE_FILESYSTEM      = "filesystem"
    DEVICE_SMARTCARD       = "smartcard"
    DEVICE_REDIRDEV        = "redirdev"
    DEVICE_MEMBALLOON      = "memballoon"
    DEVICE_TPM             = "tpm"
    DEVICE_RNG             = "rng"
    DEVICE_PANIC           = "panic"
    DEVICE_MEMORY          = "memory"

    # Ordering in this list is important: it will be the order the
    # Guest class outputs XML. So changing this may upset the test suite
    virtual_device_types = [DEVICE_DISK,
                            DEVICE_CONTROLLER,
                            DEVICE_FILESYSTEM,
                            DEVICE_NET,
                            DEVICE_INPUT,
                            DEVICE_GRAPHICS,
                            DEVICE_SERIAL,
                            DEVICE_PARALLEL,
                            DEVICE_CONSOLE,
                            DEVICE_CHANNEL,
                            DEVICE_AUDIO,
                            DEVICE_VIDEO,
                            DEVICE_HOSTDEV,
                            DEVICE_WATCHDOG,
                            DEVICE_SMARTCARD,
                            DEVICE_REDIRDEV,
                            DEVICE_MEMBALLOON,
                            DEVICE_TPM,
                            DEVICE_RNG,
                            DEVICE_PANIC,
                            DEVICE_MEMORY]

    virtual_device_classes = {}

    @classmethod
    def register_type(cls):
        cls._XML_ROOT_NAME = cls.virtual_device_type
        Device.virtual_device_classes[cls.virtual_device_type] = cls

    # General device type (disk, interface, etc.)
    virtual_device_type = None

    def __init__(self, *args, **kwargs):
        """
        Initialize device state

        :param conn: libvirt connection to validate device against
        """
        XMLBuilder.__init__(self, *args, **kwargs)
        self._XML_PROP_ORDER = self._XML_PROP_ORDER + ["alias", "address"]

        if not self.virtual_device_type:
            raise ValueError(_("Virtual device type must be set in subclass."))

        if self.virtual_device_type not in self.virtual_device_types:
            raise ValueError(_("Unknown virtual device type '%s'.") %
                             self.virtual_device_type)

    alias = XMLChildProperty(DeviceAlias, is_single=True)
    address = XMLChildProperty(DeviceAddress, is_single=True)
    boot = XMLChildProperty(DeviceBoot, is_single=True)


    def setup(self, meter=None):
        """
        Perform potentially hazardous device initialization, like
        storage creation or host device reset

        :param meter: Optional progress meter to use
        """
        # Will be overwritten by subclasses if necessary.
        ignore = meter
        return

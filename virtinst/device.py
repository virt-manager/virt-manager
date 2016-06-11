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

from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class VirtualDeviceAlias(XMLBuilder):
    _XML_ROOT_NAME = "alias"
    name = XMLProperty("./@name")


class VirtualDeviceBoot(XMLBuilder):
    _XML_ROOT_NAME = "boot"
    order = XMLProperty("./@order", is_int=True)


class VirtualDeviceAddress(XMLBuilder):
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
            raise ValueError(_("Could not determine or unsupported "
                               "format of '%s'") % addrstr)


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


class VirtualDevice(XMLBuilder):
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
    VIRTUAL_DEV_TPM             = "tpm"
    VIRTUAL_DEV_RNG             = "rng"
    VIRTUAL_DEV_PANIC           = "panic"

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
                            VIRTUAL_DEV_MEMBALLOON,
                            VIRTUAL_DEV_TPM,
                            VIRTUAL_DEV_RNG,
                            VIRTUAL_DEV_PANIC]

    virtual_device_classes = {}

    @classmethod
    def register_type(cls):
        cls._XML_ROOT_NAME = cls.virtual_device_type
        VirtualDevice.virtual_device_classes[cls.virtual_device_type] = cls

    # General device type (disk, interface, etc.)
    virtual_device_type = None

    def __init__(self, *args, **kwargs):
        """
        Initialize device state

        @param conn: libvirt connection to validate device against
        """
        XMLBuilder.__init__(self, *args, **kwargs)
        self._XML_PROP_ORDER = self._XML_PROP_ORDER + ["alias", "address"]

        if not self.virtual_device_type:
            raise ValueError(_("Virtual device type must be set in subclass."))

        if self.virtual_device_type not in self.virtual_device_types:
            raise ValueError(_("Unknown virtual device type '%s'.") %
                             self.virtual_device_type)

    alias = XMLChildProperty(VirtualDeviceAlias, is_single=True)
    address = XMLChildProperty(VirtualDeviceAddress, is_single=True)
    boot = XMLChildProperty(VirtualDeviceBoot, is_single=True)


    def setup(self, meter=None):
        """
        Perform potentially hazardous device initialization, like
        storage creation or host device reset

        @param meter: Optional progress meter to use
        """
        # Will be overwritten by subclasses if necessary.
        ignore = meter
        return

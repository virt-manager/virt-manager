#
# Base class for all VM devices
#
# Copyright 2008, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class DeviceAlias(XMLBuilder):
    XML_NAME = "alias"
    name = XMLProperty("./@name")


class DeviceBoot(XMLBuilder):
    XML_NAME = "boot"
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

    XML_NAME = "address"
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
    def __init__(self, *args, **kwargs):
        """
        Initialize device state

        :param conn: libvirt connection to validate device against
        """
        XMLBuilder.__init__(self, *args, **kwargs)
        self._XML_PROP_ORDER = self._XML_PROP_ORDER + ["alias", "address"]

    alias = XMLChildProperty(DeviceAlias, is_single=True)
    address = XMLChildProperty(DeviceAddress, is_single=True)
    boot = XMLChildProperty(DeviceBoot, is_single=True)

    @property
    def DEVICE_TYPE(self):
        return self.XML_NAME

    def setup(self, meter=None):
        """
        Perform potentially hazardous device initialization, like
        storage creation or host device reset

        :param meter: Optional progress meter to use
        """
        # Will be overwritten by subclasses if necessary.
        ignore = meter
        return

#
# Base class for all VM devices
#
# Copyright 2008, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class DeviceVirtioDriver(XMLBuilder):
    """
    Represents shared virtio <driver> options
    """
    XML_NAME = "driver"
    ats = XMLProperty("./@ats", is_onoff=True)
    iommu = XMLProperty("./@iommu", is_onoff=True)
    packed = XMLProperty("./@packed", is_onoff=True)
    page_per_vq = XMLProperty("./@page_per_vq", is_onoff=True)


class DeviceSeclabel(XMLBuilder):
    """
    Minimal seclabel that's used for device sources.
    """
    XML_NAME = "seclabel"
    model = XMLProperty("./@model")
    relabel = XMLProperty("./@relabel", is_yesno=True)
    label = XMLProperty("./label")


class DeviceAlias(XMLBuilder):
    XML_NAME = "alias"
    name = XMLProperty("./@name")


class DeviceBoot(XMLBuilder):
    XML_NAME = "boot"
    order = XMLProperty("./@order", is_int=True)
    loadparm = XMLProperty("./@loadparm")


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

    XML_NAME = "address"
    _XML_PROP_ORDER = ["type", "domain", "controller", "bus", "slot",
                       "function", "target", "unit", "multifunction"]

    def pretty_desc(self):
        pretty_desc = None
        if self.type == self.ADDRESS_TYPE_DRIVE:
            pretty_desc = ("%s:%s:%s:%s" %
                            (self.controller, self.bus, self.target, self.unit))
        return pretty_desc


    type = XMLProperty("./@type")
    # type=pci
    domain = XMLProperty("./@domain", is_int=True)
    bus = XMLProperty("./@bus", is_int=True)
    slot = XMLProperty("./@slot", is_int=True)
    function = XMLProperty("./@function", is_int=True)
    multifunction = XMLProperty("./@multifunction", is_onoff=True)
    zpci_uid = XMLProperty("./zpci/@uid")
    zpci_fid = XMLProperty("./zpci/@fid")
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
        self._XML_PROP_ORDER = self._XML_PROP_ORDER + [
                "virtio_driver", "alias", "address"]

    alias = XMLChildProperty(DeviceAlias, is_single=True)
    address = XMLChildProperty(DeviceAddress, is_single=True)
    boot = XMLChildProperty(DeviceBoot, is_single=True)
    virtio_driver = XMLChildProperty(DeviceVirtioDriver, is_single=True)

    @property
    def DEVICE_TYPE(self):
        return self.XML_NAME

    def compare_device(self, newdev, idx):
        """
        Attempt to compare this device against the passed @newdev,
        using various heuristics. For example, when removing a device
        from both active and inactive XML, the device XML my be very
        different or the devices may appear in different orders, so
        we have to do some fuzzy matching to determine if the devices
        are a 'match'
        """
        devprops = {
            "disk":          ["target", "bus"],
            "interface":     ["macaddr", "xmlindex"],
            "input":         ["bus", "type", "xmlindex"],
            "sound":         ["model", "xmlindex"],
            "video":         ["model", "xmlindex"],
            "watchdog":      ["model", "xmlindex"],
            "hostdev":       ["type", "managed", "xmlindex",
                              "product", "vendor",
                              "function", "domain", "slot"],
            "serial":        ["type", "target_port"],
            "parallel":      ["type", "target_port"],
            "console":       ["type", "target_type", "target_port"],
            "graphics":      ["type", "xmlindex"],
            "controller":    ["type", "index"],
            "channel":       ["type", "target_name"],
            "filesystem":    ["target", "xmlindex"],
            "smartcard":     ["mode", "xmlindex"],
            "redirdev":      ["bus", "type", "xmlindex"],
            "tpm":           ["type", "xmlindex"],
            "rng":           ["backend_model", "xmlindex"],
            "panic":         ["model", "xmlindex"],
            "shmem":         ["name", "xmlindex"],
            "vsock":         ["model", "xmlindex"],
            "memballoon":    ["model", "xmlindex"],
            "iommu":         ["model", "xmlindex"],
        }

        if id(self) == id(newdev):
            return True

        if not isinstance(self, type(newdev)):
            return False

        if self.DEVICE_TYPE not in devprops:  # pragma: no cover
            return False

        # Only compare against XML ID values, if both devices were
        # taken from inside a complete guest hierarchy, otherwise
        # things won't line up.
        can_check_xml = ("devices" in newdev.get_xml_id() and
                "devices" in self.get_xml_id())

        for devprop in devprops[self.DEVICE_TYPE]:
            if devprop == "xmlindex":
                if not can_check_xml:
                    continue
                origval = self.get_xml_idx()
                newval = idx
            else:
                origval = getattr(self, devprop)
                newval = getattr(newdev, devprop)

            if origval != newval:
                return False

        return True

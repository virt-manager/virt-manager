#
# Copyright 2009, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
#

import logging
import os
import xml.etree.ElementTree

import virtinst

from .formats import parser_class


# Mapping of ResourceType value to device type
# http://konkretcmpi.org/cim218/CIM_ResourceAllocationSettingData.html
#
# "Other" [1]
# "Computer System" [2]
# "Processor" [3]
# "Memory" [4]
# "IDE Controller" [5]
# "Parallel SCSI HBA" [6]
# "FC HBA" [7]
# "iSCSI HBA" [8]
# "IB HCA" [9]
# "Ethernet Adapter" [10]
# "Other Network Adapter" [11]
# "I/O Slot" [12]
# "I/O Device" [13]
# "Floppy Drive" [14]
# "CD Drive" [15]
# "DVD drive" [16]
# "Disk Drive" [17]
# "Tape Drive" [18]
# "Storage Extent" [19]
# "Other storage device" [20]
# "Serial port" [21]
# "Parallel port" [22]
# "USB Controller" [23]
# "Graphics controller" [24]
# "IEEE 1394 Controller" [25]
# "Partitionable Unit" [26]
# "Base Partitionable Unit" [27]
# "Power" [28]
# "Cooling Capacity" [29]
# "Ethernet Switch Port" [30]


DEVICE_CPU = "3"
DEVICE_MEMORY = "4"
DEVICE_IDE_BUS = "5"
DEVICE_SCSI_BUS = "6"
DEVICE_ETHERNET = "10"
DEVICE_DISK = "17"
DEVICE_GRAPHICS = "24"

# AllocationUnits mapping can be found in Appendix C here:
# https://www.dmtf.org/standards/documents/CIM/DSP0004.pdf


OVF_NAMESPACES = {
    "ovf": "http://schemas.dmtf.org/ovf/envelope/1",
    "ovfenv": "http://schemas.dmtf.org/ovf/environment/1",
    "rasd": "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData",
    "vssd": "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData",
    "vmw": "http://www.vmware.com/schema/ovf",
}


def _convert_alloc_val(ignore, val):
    # This is a hack, but should we really have to decode
    # allocation units = "bytes * 2^20"?
    val = float(val)

    if val > 100000000:
        # Assume bytes
        return int(round(val / 1024.0 / 1024.0))

    elif val > 100000:
        # Assume kilobytes
        return int(round(val / 1024.0))

    elif val < 32:
        # Assume GiB
        return int(val * 1024)

    return int(val)


def _convert_bool_val(val):
    if str(val).lower() == "false":
        return False
    elif str(val).lower() == "true":
        return True

    return False


def _find(_node, _xpath):
    return _node.find(_xpath, namespaces=OVF_NAMESPACES)


def _findall(_node, _xpath):
    return _node.findall(_xpath, namespaces=OVF_NAMESPACES)


def _text(_node):
    if _node is not None:
        return _node.text


def _lookup_disk_path(root, path):
    """
    Map the passed HostResource ID to the actual host disk path
    """
    ref = None

    def _path_has_prefix(prefix):
        if path.startswith(prefix):
            return path[len(prefix):]
        if path.startswith("ovf:" + prefix):
            return path[len("ovf:" + prefix):]
        return False

    if _path_has_prefix("/disk/"):
        disk_ref = _path_has_prefix("/disk/")
        xpath = "./ovf:DiskSection/ovf:Disk[@ovf:diskId='%s']" % disk_ref
        dnode = _find(root, xpath)

        if dnode is None:
            raise ValueError(_("Unknown disk reference id '%s' "
                               "for path %s.") % (path, disk_ref))

        ref = dnode.attrib["{%s}fileRef" % OVF_NAMESPACES["ovf"]]
    elif _path_has_prefix("/file/"):
        ref = _path_has_prefix("/file/")

    else:
        raise ValueError(_("Unknown storage path type %s.") % path)

    xpath = "./ovf:References/ovf:File[@ovf:id='%s']" % ref
    refnode = _find(root, xpath)
    if refnode is None:
        raise ValueError(_("Unknown reference id '%s' "
            "for path %s.") % (ref, path))

    return refnode.attrib["{%s}href" % OVF_NAMESPACES["ovf"]]


def _import_file(conn, input_file):
    """
    Parse the OVF file and generate a virtinst.Guest object from it
    """
    root = xml.etree.ElementTree.parse(input_file).getroot()
    vsnode = _find(root, "./ovf:VirtualSystem")
    vhnode = _find(vsnode, "./ovf:VirtualHardwareSection")

    # General info
    name = _text(vsnode.find("./ovf:Name", OVF_NAMESPACES))
    desc = _text(vsnode.find("./ovf:AnnotationSection/ovf:Annotation",
        OVF_NAMESPACES))
    if not desc:
        desc = _text(vsnode.find("./ovf:Description", OVF_NAMESPACES))

    vhxpath = "./ovf:Item[rasd:ResourceType='%s']"
    vcpus = _text(_find(vhnode,
        (vhxpath % DEVICE_CPU) + "/rasd:VirtualQuantity"))
    mem = _text(_find(vhnode,
        (vhxpath % DEVICE_MEMORY) + "/rasd:VirtualQuantity"))
    alloc_mem = _text(_find(vhnode,
        (vhxpath % DEVICE_MEMORY) + "/rasd:AllocationUnits"))

    # Sections that we handle
    # NetworkSection is ignored, since I don't have an example of
    # a valid section in the wild.
    parsed_sections = ["References", "DiskSection", "NetworkSection",
        "VirtualSystem"]

    # Check for unhandled 'required' sections
    for env_node in root.findall("./"):
        if any([p for p in parsed_sections if p in env_node.tag]):
            continue

        logging.debug("Unhandled XML section '%s'",
                      env_node.tag)

        if not _convert_bool_val(env_node.attrib.get("required")):
            continue
        raise Exception(_("OVF section '%s' is listed as "
                          "required, but parser doesn't know "
                          "how to handle it.") % env_node.name)

    disk_buses = {}
    for node in _findall(vhnode, vhxpath % DEVICE_IDE_BUS):
        instance_id = _text(_find(node, "rasd:InstanceID"))
        disk_buses[instance_id] = "ide"
    for node in _findall(vhnode, vhxpath % DEVICE_SCSI_BUS):
        instance_id = _text(_find(node, "rasd:InstanceID"))
        disk_buses[instance_id] = "scsi"

    ifaces = []
    for node in _findall(vhnode, vhxpath % DEVICE_ETHERNET):
        iface = virtinst.DeviceInterface(conn)
        # Just ignore 'source' info for now and choose the default
        net_model = _text(_find(node, "rasd:ResourceSubType"))
        if net_model and not net_model.isdigit():
            iface.model = net_model.lower()
        iface.set_default_source()
        ifaces.append(iface)

    disks = []
    for node in _findall(vhnode, vhxpath % DEVICE_DISK):
        bus_id = _text(_find(node, "rasd:Parent"))
        path = _text(_find(node, "rasd:HostResource"))

        bus = disk_buses.get(bus_id, "ide")
        fmt = "raw"

        if path:
            path = _lookup_disk_path(root, path)
            fmt = "vmdk"

        disk = virtinst.DeviceDisk(conn)
        disk.path = path
        disk.driver_type = fmt
        disk.bus = bus
        disk.device = "disk"
        disks.append(disk)


    # Generate the Guest
    guest = virtinst.Guest(conn)
    if not name:
        name = os.path.basename(input_file)

    guest.name = name.replace(" ", "_")
    guest.description = desc or None
    if vcpus:
        guest.vcpus = int(vcpus)

    if mem:
        guest.memory = _convert_alloc_val(alloc_mem, mem) * 1024

    for dev in ifaces + disks:
        guest.add_device(dev)

    return guest


class ovf_parser(parser_class):
    """
    Support for OVF appliance configurations.

    Whitepaper: https://www.vmware.com/pdf/ovf_whitepaper_specification.pdf
    Spec: https://www.dmtf.org/standards/published_documents/DSP0243_1.0.0.pdf
    """
    name = "ovf"
    suffix = ".ovf"

    @staticmethod
    def identify_file(input_file):
        """
        Return True if the given file is of this format.
        """
        # Small heuristic to ensure we aren't attempting to identify
        # a large .zip archive or similar
        if os.path.getsize(input_file) > (1024 * 1024 * 2):
            return

        try:
            root = xml.etree.ElementTree.parse(input_file).getroot()
            return root.tag == ("{%s}Envelope" % OVF_NAMESPACES["ovf"])
        except Exception:
            logging.debug("Error parsing OVF XML", exc_info=True)

        return False

    @staticmethod
    def export_libvirt(conn, input_file):
        logging.debug("Importing OVF XML:\n%s", open(input_file).read())
        return _import_file(conn, input_file)

#
# Copyright 2009, 2013 Red Hat, Inc.
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
#

import logging
import os

import libxml2

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
# http://www.dmtf.org/standards/documents/CIM/DSP0004.pdf



def _ovf_register_namespace(ctx):
    ctx.xpathRegisterNs("ovf", "http://schemas.dmtf.org/ovf/envelope/1")
    ctx.xpathRegisterNs("ovfenv", "http://schemas.dmtf.org/ovf/environment/1")
    ctx.xpathRegisterNs("rasd", "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData")
    ctx.xpathRegisterNs("vssd", "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData")
    ctx.xpathRegisterNs("vmw", "http://www.vmware.com/schema/ovf")
    ctx.xpathRegisterNs("xsi", "http://www.w3.org/2001/XMLSchema-instance")


def node_list(node):
    child_list = []
    child = node.children
    while child:
        child_list.append(child)
        child = child.next
    return child_list


def _get_child_content(parent_node, child_name):
    for node in node_list(parent_node):
        if node.name == child_name:
            return node.content

    return None


def _xml_parse_wrapper(xml, parse_func, *args, **kwargs):
    """
    Parse the passed xml string into an xpath context, which is passed
    to parse_func, along with any extra arguments.
    """
    doc = None
    ctx = None
    ret = None

    try:
        doc = libxml2.parseDoc(xml)
        ctx = doc.xpathNewContext()
        _ovf_register_namespace(ctx)
        ret = parse_func(doc, ctx, *args, **kwargs)
    finally:
        if ctx is not None:
            ctx.xpathFreeContext()
        if doc is not None:
            doc.freeDoc()
    return ret



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


def _import_file(doc, ctx, conn, input_file):
    ignore = doc
    def xpath_str(path):
        ret = ctx.xpathEval(path)
        result = None
        if ret is not None:
            if type(ret) == list:
                if len(ret) >= 1:
                    result = ret[0].content
            else:
                result = ret
        return result

    def bool_val(val):
        if str(val).lower() == "false":
            return False
        elif str(val).lower() == "true":
            return True

        return False

    def xpath_nodechildren(path):
        # Return the children of the first node found by the xpath
        nodes = ctx.xpathEval(path)
        if not nodes:
            return []
        return node_list(nodes[0])

    def _lookup_disk_path(path):
        fmt = "vmdk"
        ref = None

        def _path_has_prefix(prefix):
            if path.startswith(prefix):
                return path[len(prefix):]
            if path.startswith("ovf:" + prefix):
                return path[len("ovf:" + prefix):]
            return False

        if _path_has_prefix("/disk/"):
            disk_ref = _path_has_prefix("/disk/")
            xpath = (_make_section_xpath(envbase, "DiskSection") +
                "/ovf:Disk[@ovf:diskId='%s']" % disk_ref)

            if not ctx.xpathEval(xpath):
                raise ValueError(_("Unknown disk reference id '%s' "
                                   "for path %s.") % (path, disk_ref))

            ref = xpath_str(xpath + "/@ovf:fileRef")

        elif _path_has_prefix("/file/"):
            ref = _path_has_prefix("/file/")

        else:
            raise ValueError(_("Unknown storage path type %s.") % path)

        xpath = (envbase + "/ovf:References/ovf:File[@ovf:id='%s']" % ref)

        if not ctx.xpathEval(xpath):
            raise ValueError(_("Unknown reference id '%s' "
                "for path %s.") % (ref, path))

        return xpath_str(xpath + "/@ovf:href"), fmt

    is_ovirt_format = False
    envbase = "/ovf:Envelope[1]"
    vsbase = envbase + "/ovf:VirtualSystem"
    if not ctx.xpathEval(vsbase):
        vsbase = envbase + "/ovf:Content[@xsi:type='ovf:VirtualSystem_Type']"
        is_ovirt_format = True

    def _make_section_xpath(base, section_name):
        if is_ovirt_format:
            return (base +
                    "/ovf:Section[@xsi:type='ovf:%s_Type']" % section_name)
        return base + "/ovf:%s" % section_name

    osbase = _make_section_xpath(vsbase, "OperatingSystemSection")
    vhstub = _make_section_xpath(vsbase, "VirtualHardwareSection")

    if not ctx.xpathEval(vsbase):
        raise RuntimeError("Did not find any VirtualSystem section")
    if not ctx.xpathEval(vhstub):
        raise RuntimeError("Did not find any VirtualHardwareSection")
    vhbase = vhstub + "/ovf:Item[rasd:ResourceType='%s']"

    # General info
    name = xpath_str(vsbase + "/ovf:Name")
    desc = xpath_str(vsbase + "/ovf:AnnotationSection/ovf:Annotation")
    if not desc:
        desc = xpath_str(vsbase + "/ovf:Description")
    vcpus = xpath_str((vhbase % DEVICE_CPU) + "/rasd:VirtualQuantity")
    sockets = xpath_str((vhbase % DEVICE_CPU) + "/rasd:num_of_sockets")
    cores = xpath_str((vhbase % DEVICE_CPU) + "/rasd:num_of_cores")
    mem = xpath_str((vhbase % DEVICE_MEMORY) + "/rasd:VirtualQuantity")
    alloc_mem = xpath_str((vhbase % DEVICE_MEMORY) +
        "/rasd:AllocationUnits")

    os_id = xpath_str(osbase + "/@id")
    os_version = xpath_str(osbase + "/@version")
    # This is the VMWare OS name
    os_vmware = xpath_str(osbase + "/@osType")

    logging.debug("OS parsed as: id=%s version=%s vmware=%s",
        os_id, os_version, os_vmware)

    # Sections that we handle
    # NetworkSection is ignored, since I don't have an example of
    # a valid section in the wild.
    parsed_sections = ["References", "DiskSection", "NetworkSection",
        "VirtualSystem"]

    # Check for unhandled 'required' sections
    for env_node in xpath_nodechildren(envbase):
        if env_node.name in parsed_sections:
            continue
        elif env_node.isText():
            continue

        logging.debug("Unhandled XML section '%s'",
                      env_node.name)

        if not bool_val(env_node.prop("required")):
            continue
        raise StandardError(_("OVF section '%s' is listed as "
                              "required, but parser doesn't know "
                              "how to handle it.") %
                              env_node.name)

    disk_buses = {}
    for node in ctx.xpathEval(vhbase % DEVICE_IDE_BUS):
        instance_id = _get_child_content(node, "InstanceID")
        disk_buses[instance_id] = "ide"
    for node in ctx.xpathEval(vhbase % DEVICE_SCSI_BUS):
        instance_id = _get_child_content(node, "InstanceID")
        disk_buses[instance_id] = "scsi"

    ifaces = []
    for node in ctx.xpathEval(vhbase % DEVICE_ETHERNET):
        iface = virtinst.VirtualNetworkInterface(conn)
        # XXX: Just ignore 'source' info and choose the default
        net_model = _get_child_content(node, "ResourceSubType")
        if net_model and not net_model.isdigit():
            iface.model = net_model.lower()
        iface.set_default_source()
        ifaces.append(iface)

    disks = []
    for node in ctx.xpathEval(vhbase % DEVICE_DISK):
        bus_id = _get_child_content(node, "Parent")
        path = _get_child_content(node, "HostResource")

        bus = disk_buses.get(bus_id, "ide")
        fmt = "raw"

        if path:
            path, fmt = _lookup_disk_path(path)

        disk = virtinst.VirtualDisk(conn)
        disk.path = path
        disk.driver_type = fmt
        disk.bus = bus
        disk.device = "disk"
        disks.append(disk)


    # XXX: Convert these OS values to something useful
    ignore = os_version
    ignore = os_id
    ignore = os_vmware

    guest = conn.caps.lookup_virtinst_guest()
    guest.installer = virtinst.ImportInstaller(conn)

    if not name:
        name = os.path.basename(input_file)

    guest.name = name.replace(" ", "_")
    guest.description = desc or None
    if vcpus:
        guest.vcpus = int(vcpus)
    elif sockets or cores:
        if sockets:
            guest.cpu.sockets = int(sockets)
        if cores:
            guest.cpu.cores = int(cores)
        guest.cpu.vcpus_from_topology()

    if mem:
        guest.memory = _convert_alloc_val(alloc_mem, mem) * 1024

    for dev in ifaces + disks:
        guest.add_device(dev)

    return guest


class ovf_parser(parser_class):
    """
    Support for OVF appliance configurations.

    Whitepaper: http://www.vmware.com/pdf/ovf_whitepaper_specification.pdf
    Spec: http://www.dmtf.org/standards/published_documents/DSP0243_1.0.0.pdf
    """
    name = "ovf"
    suffix = ".ovf"

    @staticmethod
    def identify_file(input_file):
        """
        Return True if the given file is of this format.
        """
        if os.path.getsize(input_file) > (1024 * 1024 * 2):
            return

        infile = open(input_file, "r")
        xml = infile.read()
        infile.close()

        def parse_cb(doc, ctx):
            ignore = doc
            return bool(ctx.xpathEval("/ovf:Envelope"))

        try:
            return _xml_parse_wrapper(xml, parse_cb)
        except Exception, e:
            logging.debug("Error parsing OVF XML: %s", str(e))

        return False

    @staticmethod
    def export_libvirt(conn, input_file):
        infile = open(input_file, "r")
        xml = infile.read()
        infile.close()
        logging.debug("Importing OVF XML:\n%s", xml)

        return _xml_parse_wrapper(xml, _import_file, conn, input_file)

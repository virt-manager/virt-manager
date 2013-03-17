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
#

import libxml2

from virtconv import _gettext as _
import virtconv.formats as formats
import virtconv.vmcfg as vmcfg
import virtconv.diskcfg as diskcfg
import virtconv.netdevcfg as netdevcfg

import logging

# Mapping of ResourceType value to device type
# http://konkretcmpi.org/cim218/CIM_ResourceAllocationSettingData.html
"""
    "Other" [1]
    "Computer System" [2]
    "Processor" [3]
    "Memory" [4]
    "IDE Controller" [5]
    "Parallel SCSI HBA" [6]
    "FC HBA" [7]
    "iSCSI HBA" [8]
    "IB HCA" [9]
    "Ethernet Adapter" [10]
    "Other Network Adapter" [11]
    "I/O Slot" [12]
    "I/O Device" [13]
    "Floppy Drive" [14]
    "CD Drive" [15]
    "DVD drive" [16]
    "Disk Drive" [17]
    "Tape Drive" [18]
    "Storage Extent" [19]
    "Other storage device" [20]
    "Serial port" [21]
    "Parallel port" [22]
    "USB Controller" [23]
    "Graphics controller" [24]
    "IEEE 1394 Controller" [25]
    "Partitionable Unit" [26]
    "Base Partitionable Unit" [27]
    "Power" [28]
    "Cooling Capacity" [29]
    "Ethernet Switch Port" [30]
"""

DEVICE_CPU = "3"
DEVICE_MEMORY = "4"
DEVICE_IDE_BUS = "5"
DEVICE_SCSI_BUS = "6"
DEVICE_ETHERNET = "10"
DEVICE_DISK = "17"
DEVICE_GRAPHICS = "24"

# AllocationUnits mapping can be found in Appendix C here:
#http://www.dmtf.org/standards/documents/CIM/DSP0004.pdf



def register_namespace(ctx):
    ctx.xpathRegisterNs("ovf", "http://schemas.dmtf.org/ovf/envelope/1")
    ctx.xpathRegisterNs("ovfenv", "http://schemas.dmtf.org/ovf/environment/1")
    ctx.xpathRegisterNs("rasd", "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData")
    ctx.xpathRegisterNs("vssd", "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData")
    ctx.xpathRegisterNs("vmw", "http://www.vmware.com/schema/ovf")

def node_list(node):
    child_list = []
    child = node.children
    while child:
        child_list.append(child)
        child = child.next
    return child_list

def get_child_content(parent_node, child_name):

    for node in node_list(parent_node):
        if node.name == child_name:
            return node.content

    return None

def convert_alloc_val(ignore, val):
    # XXX: This is a hack, but should we really have to decode
    #      allocation units = "bytes * 2^20"?
    val = float(val)

    if val > 100000000:
        # Assume bytes
        return int(round(val / 1024.0 / 1024.0))

    elif val > 100000:
        # Assume kilobytes
        return int(round(val / 1024.0))

    elif val < 32:
        # Assume GB
        return int(val * 1024)

    return int(val)

def _xml_wrapper(xml, func):
    doc = None
    ctx = None
    result = None

    try:
        doc = libxml2.parseDoc(xml)
        ctx = doc.xpathNewContext()
        register_namespace(ctx)

        result = func(ctx)
    finally:
        if doc:
            doc.freeDoc()
        if ctx:
            ctx.xpathFreeContext()
    return result

def get_xml_path(xml, path=None, func=None):
    """
    Return the content from the passed xml xpath, or return the result
    of a passed function (receives xpathContext as its only arg)
    """
    def _get_xml_path(ctx):
        result = None

        if path:
            ret = ctx.xpathEval(path)
            if ret != None:
                if type(ret) == list:
                    if len(ret) >= 1:
                        #result = ret[0].content
                        result = ret
                else:
                    result = ret

        elif func:
            result = func(ctx)
        else:
            raise ValueError(_("'path' or 'func' is required."))

        return result

    return _xml_wrapper(xml, _get_xml_path)

def _parse_hw_section(vm, nodes, file_refs, disk_section):
    vm.nr_vcpus = 0
    disk_buses = {}

    for device_node in nodes:
        if device_node.name != "Item":
            continue

        devtype = None
        for item_node in node_list(device_node):
            if item_node.name == "ResourceType":
                devtype = item_node.content

        if devtype == DEVICE_CPU:
            cpus = get_child_content(device_node, "VirtualQuantity")
            if cpus:
                vm.nr_vcpus += int(cpus)

        elif devtype == DEVICE_MEMORY:
            mem = get_child_content(device_node, "VirtualQuantity")
            alloc_str = get_child_content(device_node, "AllocationUnits")
            if mem:
                vm.memory = convert_alloc_val(alloc_str, mem)

        elif devtype == DEVICE_ETHERNET:
            net_model = get_child_content(device_node, "ResourceSubType")
            if net_model:
                net_model = net_model.lower()
            netdev = netdevcfg.netdev(driver=net_model)
            vm.netdevs[len(vm.netdevs)] = netdev

        elif devtype == DEVICE_IDE_BUS:
            instance_id = get_child_content(device_node, "InstanceID")
            disk_buses[instance_id] = "ide"

        elif devtype == DEVICE_SCSI_BUS:
            instance_id = get_child_content(device_node, "InstanceID")
            disk_buses[instance_id] = "scsi"

        elif devtype in [ DEVICE_DISK ]:
            bus_id = get_child_content(device_node, "Parent")
            path = get_child_content(device_node, "HostResource")

            dev_num = int(get_child_content(device_node, "AddressOnParent"))

            if bus_id and bus_id not in disk_buses:
                raise ValueError(_("Didn't find parent bus for disk '%s'" %
                                 path))

            bus = (bus_id and disk_buses[bus_id]) or "ide"

            fmt = diskcfg.DISK_FORMAT_RAW

            if path:
                ref = None
                fmt = diskcfg.DISK_FORMAT_VMDK

                if path.startswith("ovf:/disk/"):
                    disk_ref = path[len("ovf:/disk/"):]
                    if disk_ref not in disk_section:
                        raise ValueError(_("Unknown reference id '%s' "
                                           "for path %s.") % (path, ref))

                    ref, fmt = disk_section[disk_ref]

                elif path.startswith("ovf:/file/"):
                    ref = path[len("ovf:/file/"):]

                else:
                    raise ValueError(_("Unknown storage path type %s." % path))

                if not ref:
                    # XXX: This means allocate the disk.
                    pass

                if ref not in file_refs:
                    raise ValueError(_("Unknown reference id '%s' "
                                       "for path %s.") % (path, ref))

                path = file_refs[ref]

            disk = diskcfg.disk(path=path, format=fmt, bus=bus,
                                type=diskcfg.DISK_TYPE_DISK)

            vm.disks[(bus, dev_num)] = disk

        else:
            desc = get_child_content(device_node, "Description")
            logging.debug("Unhandled device type=%s desc=%s", devtype, desc)

class ovf_parser(formats.parser):
    """
    Support for OVF appliance configurations.

    Whitepaper: http://www.vmware.com/pdf/ovf_whitepaper_specification.pdf
    Spec: http://www.dmtf.org/standards/published_documents/DSP0243_1.0.0.pdf
    """

    name = "ovf"
    suffix = ".ovf"
    can_import = True
    can_export = False
    can_identify = True

    @staticmethod
    def identify_file(input_file):
        """
        Return True if the given file is of this format.
        """
        infile = open(input_file, "r")
        xml = infile.read()
        infile.close()

        res = False
        try:
            if xml.count("</Envelope>"):
                res = bool(get_xml_path(xml, "/ovf:Envelope"))
        except Exception, e:
            logging.debug("Error parsing OVF XML: %s", str(e))

        return res

    @staticmethod
    def import_file(input_file):
        """
        Import a configuration file.  Raises if the file couldn't be
        opened, or parsing otherwise failed.
        """

        infile = open(input_file, "r")
        xml = infile.read()
        infile.close()
        logging.debug("Importing OVF XML:\n%s", xml)

        return _xml_wrapper(xml, ovf_parser._import_file)

    @staticmethod
    def _import_file(ctx):
        def xpath_str(path):
            ret = ctx.xpathEval(path)
            result = None
            if ret != None:
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

        def xpath_nodes(path):
            return ctx.xpathEval(path)

        vm = vmcfg.vm()

        file_refs = {}
        disk_section = {}
        net_section = {}
        name = None
        desc = None

        os_id_ignore = None
        os_ver_ignore = None
        os_type_ignore = None

        # XXX: Can have multiple machines nested as VirtualSystemCollection
        # XXX: Need to check all Envelope

        # General info
        name = xpath_str("/ovf:Envelope/ovf:VirtualSystem/ovf:Name")

        # Map files in <References> to actual filename
        ens = xpath_nodes("/ovf:Envelope[1]")[0]
        envelope_node = ens.children
        for envelope_node in node_list(ens):

            if envelope_node.name == "References":
                for reference_node in envelope_node.children:
                    if reference_node.name != "File":
                        continue

                    file_id = reference_node.prop("id")
                    path = reference_node.prop("href")

                    # XXX: Should we validate the path exists? This can
                    #      be http.
                    if file_id and path:
                        file_refs[file_id] = path

            elif envelope_node.name == "DiskSection":
                for disk_node in envelope_node.children:
                    if disk_node.name != "Disk":
                        continue

                    fmt = disk_node.prop("format")
                    if not fmt:
                        fmt = diskcfg.DISK_FORMAT_VMDK
                    elif fmt.lower().count("vmdk"):
                        fmt = diskcfg.DISK_FORMAT_VMDK
                    else:
                        fmt = diskcfg.DISK_FORMAT_VMDK

                    disk_id = disk_node.prop("diskId")
                    file_ref = disk_node.prop("fileRef")
                    capacity = disk_node.prop("capacity")
                    alloc_str = disk_node.prop("AllocationUnits")
                    capacity = convert_alloc_val(alloc_str, capacity)

                    # XXX: Empty fileref means 'create this disk'
                    disk_section[disk_id] = (file_ref, fmt)

            elif envelope_node.name == "NetworkSection":
                for net_node in envelope_node.children:
                    if net_node.name != "Network":
                        continue

                    net_name_ignore = net_node.prop("name")
                    net_section[name] = None

            elif not envelope_node.isText():
                logging.debug("Unhandled XML section '%s'",
                              envelope_node.name)

                req = bool_val(envelope_node.prop("required"))
                if req:
                    raise StandardError(_("OVF section '%s' is listed as "
                                          "required, but parser doesn't know "
                                          "how to handle it.") %
                                          envelope_node.name)

        # Now parse VirtualSystem, since we should have set up all the
        # necessary file/disk/whatever refs
        for envelope_node in node_list(ens):
            if envelope_node.name != "VirtualSystem":
                continue

            for vs_node in node_list(envelope_node):

                if vs_node.name == "Info":
                    pass

                elif vs_node.name == "Name":
                    name = vs_node.content

                elif vs_node.name == "OperatingSystemSection":
                    os_id_ignore = vs_node.prop("id")
                    os_ver_ignore = vs_node.prop("version")
                    # This is the VMWare OS name
                    os_type_ignore = vs_node.prop("osType")

                elif vs_node.name == "VirtualHardwareSection":
                    _parse_hw_section(vm, node_list(vs_node), file_refs,
                                      disk_section)

                elif vs_node.name == "AnnotationSection":
                    for an_node in node_list(vs_node):
                        if an_node.name == "Annotation":
                            desc = an_node.content


        vm.name = name
        vm.description = desc
        vm.validate()

        return vm

    @staticmethod
    def export(vm):
        """
        Export a configuration file as a string.
        @vm vm configuration instance

        Raises ValueError if configuration is not suitable.
        """
        raise NotImplementedError

formats.register_parser(ovf_parser)

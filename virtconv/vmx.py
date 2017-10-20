# Copyright (C) 2013 Red Hat, Inc.
#
# Copyright 2008 Sun Microsystems, Inc.  All rights reserved.
# Use is subject to license terms.
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

import collections
import logging
import os
import re
import shlex

import virtinst
from virtinst import util

from .formats import parser_class


class _VMXLine(object):
    """
    Class tracking an individual line in a VMX/VMDK file
    """
    def __init__(self, content):
        self.content = content

        self.pair = None
        self.is_blank = False
        self.is_comment = False
        self.is_disk = False
        self._parse()

    def _parse(self):
        line = self.content.strip()
        if not line:
            self.is_blank = True
        elif line.startswith("#"):
            self.is_comment = True
        elif line.startswith("RW ") or line.startswith("RDONLY "):
            self.is_disk = True
        else:
            # Expected that this will raise an error for unknown format
            before_eq, after_eq = line.split("=", 1)
            key = before_eq.strip().lower()
            value = after_eq.strip().strip('"')
            self.pair = (key, value)

    def parse_disk_path(self):
        # format:
        # RW 16777216 VMFS "test-flat.vmdk"
        # RDONLY 156296322 V2I "virtual-pc-diskformat.v2i"
        content = self.content.split(" ", 3)[3]
        if not content.startswith("\""):
            raise ValueError("Path was not fourth entry in VMDK storage line")
        return shlex.split(content, " ", 1)[0]


class _VMXFile(object):
    """
    Class tracking a parsed VMX/VMDK format file
    """
    def __init__(self, content):
        self.content = content
        self.lines = []

        self._parse()

    def _parse(self):
        for line in self.content:
            try:
                lineobj = _VMXLine(line)
                self.lines.append(lineobj)
            except Exception as e:
                raise Exception(_("Syntax error at line %d: %s\n%s") %
                    (len(self.lines) + 1, line.strip(), e))

    def pairs(self):
        ret = collections.OrderedDict()
        for line in self.lines:
            if line.pair:
                ret[line.pair[0]] = line.pair[1]
        return ret


def parse_vmdk(filename):
    """
    Parse a VMDK descriptor file
    Reference: http://sanbarrow.com/vmdk-basics.html
    """
    # Detect if passed file is a descriptor file
    # Assume descriptor isn't larger than 10K
    if not os.path.exists(filename):
        logging.debug("VMDK file '%s' doesn't exist", filename)
        return
    if os.path.getsize(filename) > (10 * 1024):
        logging.debug("VMDK file '%s' too big to be a descriptor", filename)
        return

    f = open(filename, "r")
    content = f.readlines()
    f.close()

    try:
        vmdkfile = _VMXFile(content)
    except Exception:
        logging.exception("%s looked like a vmdk file, but parsing failed",
                          filename)
        return

    disklines = [l for l in vmdkfile.lines if l.is_disk]
    if len(disklines) == 0:
        raise RuntimeError(_("Didn't detect a storage line in the VMDK "
                             "descriptor file"))
    if len(disklines) > 1:
        raise RuntimeError(_("Don't know how to handle multistorage VMDK "
                             "descriptors"))

    return disklines[0].parse_disk_path()


def parse_netdev_entry(conn, ifaces, fullkey, value):
    """
    Parse a particular key/value for a network.  Throws ValueError.
    """
    ignore, ignore, inst, key = re.split("^(ethernet)([0-9]+).", fullkey)
    lvalue = value.lower()

    if key == "present" and lvalue == "false":
        return

    net = None
    for checkiface in ifaces:
        if getattr(checkiface, "vmx_inst") == inst:
            net = checkiface
            break
    if not net:
        net = virtinst.VirtualNetworkInterface(conn)
        setattr(net, "vmx_inst", inst)
        net.set_default_source()
        ifaces.append(net)

    if key == "virtualdev":
        # "vlance", "vmxnet", "e1000"
        if lvalue in ["e1000"]:
            net.model = lvalue
    if key == "addresstype" and lvalue == "generated":
        # Autogenerate a MAC address, the default
        pass
    if key == "address":
        # we ignore .generatedAddress for auto mode
        net.macaddr = lvalue
    return net, inst


def parse_disk_entry(conn, disks, fullkey, value):
    """
    Parse a particular key/value for a disk.  FIXME: this should be a
    lot smarter.
    """
    # skip bus values, e.g. 'scsi0.present = "TRUE"'
    if re.match(r"^(scsi|ide)[0-9]+[^:]", fullkey):
        return

    ignore, bus, bus_nr, inst, key = re.split(
        r"^(scsi|ide)([0-9]+):([0-9]+)\.", fullkey)

    lvalue = value.lower()

    if key == "present" and lvalue == "false":
        return

    # Does anyone else think it's scary that we're still doing things
    # like this?
    if bus == "ide":
        inst = int(bus_nr) * 2 + (int(inst) % 2)
    elif bus == "scsi":
        inst = int(bus_nr) * 16 + (int(inst) % 16)

    disk = None
    for checkdisk in disks:
        if checkdisk.bus == bus and getattr(checkdisk, "vmx_inst") == inst:
            disk = checkdisk
            break
    if not disk:
        disk = virtinst.VirtualDisk(conn)
        disk.bus = bus
        setattr(disk, "vmx_inst", inst)
        disks.append(disk)

    if key == "devicetype":
        if (lvalue == "atapi-cdrom" or
            lvalue == "cdrom-raw" or
            lvalue == "cdrom-image"):
            disk.device = "cdrom"

    if key == "filename":
        disk.path = value
        fmt = "raw"
        if lvalue.endswith(".vmdk"):
            fmt = "vmdk"
            # See if the filename is actually a VMDK descriptor file
            newpath = parse_vmdk(disk.path)
            if newpath:
                logging.debug("VMDK file parsed path %s->%s",
                    disk.path, newpath)
                disk.path = newpath

        disk.driver_type = fmt


class vmx_parser(parser_class):
    """
    Support for VMWare .vmx files.  Note that documentation is
    particularly sparse on this format, with pretty much the best
    resource being http://sanbarrow.com/vmx.html
    """
    name = "vmx"
    suffix = ".vmx"

    @staticmethod
    def identify_file(input_file):
        """
        Return True if the given file is of this format.
        """
        if os.path.getsize(input_file) > (1024 * 1024 * 2):
            return

        infile = open(input_file, "r")
        content = infile.readlines()
        infile.close()

        for line in content:
            # some .vmx files don't bother with the header
            if (re.match(r'^config.version\s+=', line) or
                re.match(r'^#!\s*/usr/bin/vm(ware|player)', line)):
                return True
        return False

    @staticmethod
    def export_libvirt(conn, input_file):
        infile = open(input_file, "r")
        contents = infile.readlines()
        infile.close()
        logging.debug("Importing VMX file:\n%s", "".join(contents))

        vmxfile = _VMXFile(contents)
        config = vmxfile.pairs()

        if not config.get("displayname"):
            raise ValueError(_("No displayName defined in '%s'") %
                             input_file)

        name = config.get("displayname")
        mem = config.get("memsize")
        desc = config.get("annotation")
        vcpus = config.get("numvcpus")

        def _find_keys(prefixes):
            ret = []
            for key, value in config.items():
                for p in util.listify(prefixes):
                    if key.startswith(p):
                        ret.append((key, value))
                        break
            return ret

        disks = []
        for key, value in _find_keys(["scsi", "ide"]):
            parse_disk_entry(conn, disks, key, value)

        ifaces = []
        for key, value in _find_keys("ethernet"):
            parse_netdev_entry(conn, ifaces, key, value)

        for disk in disks:
            if disk.device == "disk":
                continue

            # vmx files often have dross left in path for CD entries
            if (disk.path is None or
                disk.path.lower() == "auto detect" or
                not os.path.exists(disk.path)):
                disk.path = None

        guest = conn.caps.lookup_virtinst_guest()
        guest.installer = virtinst.ImportInstaller(conn)

        guest.name = name.replace(" ", "_")
        guest.description = desc or None
        if vcpus:
            guest.vcpus = int(vcpus)
        if mem:
            guest.memory = int(mem) * 1024

        for dev in ifaces + disks:
            guest.add_device(dev)

        return guest

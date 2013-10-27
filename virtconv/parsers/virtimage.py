#
# Copyright 2013 Red Hat, Inc.
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

import virtconv.formats as formats
import virtconv.vmcfg as vmcfg
import virtconv.diskcfg as diskcfg
import virtconv.netdevcfg as netdevcfg

from virtinst import virtimage

from xml.sax.saxutils import escape
import re
import logging

ide_letters = list("abcdefghijklmnopqrstuvwxyz")

pv_boot_template = \
"""  <boot type="xen">
   <guest>
    <arch>%(arch)s</arch>
    <features>
     <pae/>
    </features>
   </guest>
   <os>
    <loader>pygrub</loader>
   </os>
%(disks)s
  </boot>"""

hvm_boot_template = \
"""  <boot type="hvm">
   <guest>
    <arch>%(arch)s</arch>
   </guest>
   <os>
    <loader dev="hd"/>
   </os>
%(disks)s
  </boot>"""

image_template = \
"""<image>
 <name>%(name)s</name>
 <label>%(name)s</label>
 <description>%(description)s</description>
 <domain>
%(boot_template)s
  <devices>
   <vcpu>%(nr_vcpus)s</vcpu>
   <memory>%(memory)s</memory>
%(interface)s
   <graphics/>
  </devices>
 </domain>
 <storage>
%(storage)s
 </storage>
</image>
"""


def export_os_params(vm):
    """
    Export OS-specific parameters.
    """
    from virtinst import osdict
    os = osdict.lookup_os(vm.os_variant)

    def get_os_val(key, default):
        val = None
        if os:
            val = os.to_dict().get(key)
        if val is None:
            val = default
        return val

    acpi = ""
    if vm.noacpi is False and get_os_val("acpi", True):
        acpi = "<acpi />"

    apic = ""
    if vm.noapic is False and get_os_val("apic", False):
        apic = "<apic />"

    return acpi, apic


def export_disks(vm):
    """
    Export code for the disks.  Slightly tricky for two reasons.

    We can't handle duplicate disks: some vmx files define SCSI/IDE devices
    that point to the same storage, and Xen isn't happy about that. We
    just ignore any entries that have duplicate paths.

    Since there is no SCSI support in rombios, and the SCSI emulation is
    troublesome with Solaris, we forcibly switch the disks to IDE, and expect
    the guest OS to cope (which at least Linux does admirably).

    Note that we even go beyond hdd: above that work if the domU has PV
    drivers.
    """

    paths = []

    disks = {}

    for (bus, instance), disk in sorted(vm.disks.iteritems()):

        if disk.path and disk.path in paths:
            continue

        if bus == "scsi":
            instance = 0
            while disks.get(("ide", instance)):
                instance += 1

        disks[("ide", instance)] = disk

        if disk.path:
            paths += [disk.path]

    diskout = []
    storage = []

    for (bus, instance), disk in sorted(disks.iteritems()):

        # virt-image XML cannot handle an empty CD device
        if not disk.path:
            continue

        path = disk.path
        drive_nr = ide_letters[int(instance) % 26]

        disk_prefix = "xvd"
        if vm.type == vmcfg.VM_TYPE_HVM:
            if bus == "ide":
                disk_prefix = "hd"
            else:
                disk_prefix = "sd"

        # FIXME: needs updating for later Xen enhancements; need to
        # implement capabilities checking for max disks etc.
        diskout.append("""   <drive disk="%s" target="%s%s"/>\n""" %
            (path, disk_prefix, drive_nr))

        typ = "raw"
        if disk.format in diskcfg.qemu_formats:
            typ = diskcfg.qemu_formats[disk.format]
        elif disk.typ == diskcfg.DISK_TYPE_ISO:
            typ = "iso"

        storage.append(
            """  <disk file="%s" use="system" format="%s"/>\n""" %
                (path, typ))

    return storage, diskout


class virtimage_parser(formats.parser):
    """
    Support for virt-install's image format (see virt-image man page).
    """
    name = "virt-image"
    suffix = ".virt-image.xml"
    can_import = True
    can_export = True
    can_identify = True

    @staticmethod
    def identify_file(input_file):
        """
        Return True if the given file is of this format.
        """
        try:
            f = file(input_file, "r")
            output = f.read()
            f.close()

            virtimage.parse(output, input_file)
        except RuntimeError:
            return False
        return True

    @staticmethod
    def import_file(input_file):
        """
        Import a configuration file.  Raises if the file couldn't be
        opened, or parsing otherwise failed.
        """
        vm = vmcfg.vm()
        try:
            f = file(input_file, "r")
            output = f.read()
            f.close()

            logging.debug("Importing virt-image XML:\n%s", output)
            config = virtimage.parse(output, input_file)
        except Exception, e:
            raise ValueError(_("Couldn't import file '%s': %s") %
                             (input_file, e))

        domain = config.domain
        boot = domain.boots[0]

        if not config.name:
            raise ValueError(_("No Name defined in '%s'") % input_file)
        vm.name = config.name
        vm.arch = boot.arch
        vm.memory = int(config.domain.memory / 1024)
        if config.descr:
            vm.description = config.descr
        vm.nr_vcpus = config.domain.vcpu

        bus = "ide"
        nr_disk = 0

        for d in boot.drives:
            disk = d.disk
            format_mappings = {
                virtimage.Disk.FORMAT_RAW: diskcfg.DISK_FORMAT_RAW,
                virtimage.Disk.FORMAT_VMDK: diskcfg.DISK_FORMAT_VMDK,
                virtimage.Disk.FORMAT_QCOW: diskcfg.DISK_FORMAT_QCOW,
                virtimage.Disk.FORMAT_QCOW2: diskcfg.DISK_FORMAT_QCOW2,
                virtimage.Disk.FORMAT_VDI: diskcfg.DISK_FORMAT_VDI,
           }

            fmt = None
            if disk.format in format_mappings:
                fmt = format_mappings[disk.format]
            else:
                raise ValueError(_("Unknown disk format '%s'"), disk.format)

            devid = (bus, nr_disk)
            vm.disks[devid] = diskcfg.disk(bus=bus,
                typ=diskcfg.DISK_TYPE_DISK)
            vm.disks[devid].format = fmt
            vm.disks[devid].path = disk.file
            nr_disk = nr_disk + 1

        nics = domain.interface
        nic_idx = 0
        while nic_idx in range(0, nics):
            # XXX Eventually need to add support for mac addresses if given
            vm.netdevs[nic_idx] = netdevcfg.netdev(
                                    typ=netdevcfg.NETDEV_TYPE_UNKNOWN)
            nic_idx = nic_idx + 1
        vm.validate()
        return vm

    @staticmethod
    def export(vm):
        """
        Export a configuration file as a string.
        @vm vm configuration instance

        Raises ValueError if configuration is not suitable.
        """

        if not vm.memory:
            raise ValueError(_("VM must have a memory setting"))

        # xend wants the name to match r'^[A-Za-z0-9_\-\.\:\/\+]+$', and
        # the schema agrees.
        vmname = re.sub(r'[^A-Za-z0-9_\-\.:\/\+]+',  '_', vm.name)

        # Hmm.  Any interface is a good interface?
        interface = None
        if len(vm.netdevs):
            interface = "   <interface/>"

        acpi, apic = export_os_params(vm)

        if vm.type == vmcfg.VM_TYPE_PV:
            boot_template = pv_boot_template
        else:
            boot_template = hvm_boot_template

        (storage, disks) = export_disks(vm)

        boot_xml = boot_template % {
            "disks" : "".join(disks).strip("\n"),
            "arch" : vm.arch,
            "acpi" : acpi,
            "apic" : apic,
       }

        out = image_template % {
            "boot_template": boot_xml,
            "name" : vmname,
            "description" : escape(vm.description),
            "nr_vcpus" : vm.nr_vcpus,
            # Mb to Kb
            "memory" : int(vm.memory) * 1024,
            "interface" : interface,
            "storage" : "".join(storage).strip("\n"),
       }

        return out

formats.register_parser(virtimage_parser)

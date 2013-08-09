# Sample code to parse an image XML description and
# spit out libvirt XML
#
# Copyright 2007, 2013  Red Hat, Inc.
# David Lutterkort <dlutter@redhat.com>
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

import logging
import os

import urlgrabber

from virtinst import CapabilitiesParser
from virtinst import Installer
from virtinst import VirtualDisk
from virtinst import util


class Image(object):
    """The toplevel object representing a VM image"""
    def __init__(self, node=None, base=None, filename=None):
        self.storage = {}
        self.domain = None
        if filename is None:
            self.filename = None
        else:
            self.filename = os.path.abspath(filename)
        if base is None:
            if filename is not None:
                self.base = os.path.dirname(filename)
                if self.base == '':
                    self.base = "."
            else:
                self.base = "."
        else:
            self.base = base
        self.name = None
        self.label = None
        self.descr = None
        self.version = None
        self.release = None
        if not node is None:
            self.parseXML(node)

    def abspath(self, p):
        """Turn P into an absolute path. Relative paths are taken relative
           to self.BASE"""
        return os.path.abspath(os.path.join(self.base, p))

    def parseXML(self, node):
        self.name = xpathString(node, "name")
        self.label = xpathString(node, "label")
        self.descr = xpathString(node, "description")
        self.version = xpathString(node, "name/@version")
        self.release = xpathString(node, "name/@release")
        for d in node.xpathEval("storage/disk"):
            disk = Disk(d)
            if disk.file is None:
                disk.id = "disk%d.img" % len(self.storage)
                disk.file = "disk%d.img" % (len(self.storage) + 1)
            if disk.id in self.storage:
                raise RuntimeError("Disk file '%s' defined twice" % disk.file)
            self.storage[disk.id] = disk
        lm = node.xpathEval("domain")
        if len(lm) == 1:
            self.domain = Domain(lm[0])
        else:
            raise RuntimeError(_("Expected exactly one 'domain' element"))
        # Connect the disk maps to the disk definitions
        for boot in self.domain.boots:
            for d in boot.drives:
                if d.disk_id not in self.storage:
                    raise RuntimeError(_("Disk entry for '%s' not found")
                                       % d.disk_id)
                d.disk = self.storage[d.disk_id]


class Domain(object):
    """The description of a virtual domain as part of an image"""
    def __init__(self, node=None):
        self.boots = []
        self.vcpu = None
        self.memory = None
        self.interface = 0
        self.graphics = None
        if not node is None:
            self.parseXML(node)

    def parseXML(self, node):
        self.boots = [Boot(b) for b in node.xpathEval("boot")]
        self.vcpu = xpathString(node, "devices/vcpu", 1)
        tmpmem = xpathString(node, "devices/memory")
        self.interface = int(node.xpathEval("count(devices/interface)"))
        self.graphics = node.xpathEval("count(devices/graphics)") > 0

        if tmpmem is not None:
            try:
                self.memory = int(tmpmem)
            except ValueError:
                raise RuntimeError(_("Memory must be an integer, "
                                     "but is '%s'") % self.memory)
        else:
            tmpmem = 0


class ImageFeatures(CapabilitiesParser.Features):
    def __init__(self, node=None):
        CapabilitiesParser.Features.__init__(self, node)

    def _extractFeature(self, feature, d, n):
        state = xpathString(n, "@state", "on")

        if state == "on":
            d[feature] = CapabilitiesParser.FEATURE_ON
        elif state == "off":
            d[feature] = CapabilitiesParser.FEATURE_OFF
        else:
            raise RuntimeError("The state for feature %s must be "
                               "either 'on' or 'off', but is '%s'" %
                               (feature, state))


class Boot(object):
    """The overall description of how the image can be booted, including
    required capabilities of the host and mapping of disks into the VM"""
    def __init__(self, node=None):
        # 'xen' or 'hvm'
        self.type = None
        # Either 'pygrub' or nothing; might have others in the future
        # For HVM, figure outhte right loader based on the guest
        self.loader = None
        # Only used for hvm
        self.bootdev = None
        self.kernel = None
        self.initrd = None
        self.cmdline = None
        self.drives = []
        self.arch = None
        self.features = ImageFeatures()
        if not node is None:
            self.parseXML(node)

    def parseXML(self, node):
        self.type = xpathString(node, "@type")
        self.loader = xpathString(node, "os/loader")
        self.bootdev = xpathString(node, "os/loader/@dev")
        self.kernel = xpathString(node, "os/kernel")
        self.initrd = xpathString(node, "os/initrd")
        self.cmdline = xpathString(node, "os/cmdline")
        self.arch = util.sanitize_arch(xpathString(node, "guest/arch"))

        fl = node.xpathEval("guest/features")
        if len(fl) > 1:
            raise RuntimeError("Expected at most one <features> element "
                               "in %s boot descriptor for %s" %
                               (self.type, self.arch))
        elif len(fl) == 1:
            self.features = ImageFeatures(fl[0])

        for d in node.xpathEval("drive"):
            self.drives.append(Drive(d))

        validate(self.type is not None,
           "The boot type must be provided")
        validate(self.type == "hvm" or self.type == "xen",
           "Boot type must be 'xen' or 'hvm', but is %s" % self.type)
        validate(self.arch is not None, "Missing guest arch")
        validate(self.loader is None or self.loader == "pygrub",
                 "Invalid loader %s" % self.loader)
        validate([None, "hd", "cdrom"].count(self.bootdev) > 0,
                 "Invalid bootdev %s" % self.bootdev)
        # We should make sure that kernel/initrd/cmdline are only used for pv
        # and without a loader


class Drive(object):
    """The mapping of a disk from the storage section to a virtual drive
    in a guest"""
    def __init__(self, node=None):
        self.disk_id = None
        self.target = None
        self.disk = None   # Will point to the underlying Disk object
        if node:
            self.parseXML(node)

    def parseXML(self, node):
        self.disk_id = xpathString(node, "@disk")
        self.target = xpathString(node, "@target")


class Disk(object):
    FORMAT_RAW = "raw"
    FORMAT_ISO = "iso"
    FORMAT_QCOW = "qcow"
    FORMAT_QCOW2 = "qcow2"
    FORMAT_VMDK = "vmdk"
    FORMAT_VDI = "vdi"

    USE_SYSTEM = "system"
    USE_USER = "user"
    USE_SCRATCH = "scratch"

    def __init__(self, node=None):
        self.id = None
        self.file = None
        self.format = None
        self.size = None
        self.use = None
        self.csum = {}
        if not node is None:
            self.parseXML(node)

    def parseXML(self, node):
        self.file = xpathString(node, "@file")
        self.id = xpathString(node, "@id", self.file)
        self.format = xpathString(node, "@format", Disk.FORMAT_RAW)
        self.size = xpathString(node, "@size")
        self.use = xpathString(node, "@use", Disk.USE_SYSTEM)

        for d in node.xpathEval("checksum"):
            csumtype = xpathString(d, "@type")
            csumvalue = xpathString(d, "")
            self.csum[csumtype] = csumvalue
        formats = [Disk.FORMAT_RAW,
                   Disk.FORMAT_QCOW,
                   Disk.FORMAT_QCOW2,
                   Disk.FORMAT_VMDK,
                   Disk.FORMAT_ISO,
                   Disk.FORMAT_VDI]
        validate(formats.count(self.format) > 0,
                 _("The format for disk %s must be one of %s") %
                 (self.file, ",".join(formats)))

    def check_disk_signature(self, meter=None):
        try:
            import hashlib
            sha = None
        except:
            import sha
            hashlib = None

        if meter is None:
            meter = urlgrabber.progress.BaseMeter()

        m = None
        if hashlib:
            if "sha256" in self.csum:
                csumvalue = self.csum["sha256"]
                m = hashlib.sha256()

            elif "sha1" in self.csum:
                csumvalue = self.csum["sha1"]
                m = hashlib.sha1()
        else:
            if "sha1" in self.csum:
                csumvalue = self.csum["sha1"]
                m = sha.new()

        if not m:
            return

        meter_ct = 0
        disk_size = os.path.getsize(self.file)
        meter.start(size=disk_size,
                    text=_("Checking disk signature for %s" % self.file))

        f = file(self.file)
        while 1:
            chunk = f.read(65536)
            if not chunk:
                break
            meter.update(meter_ct)
            meter_ct = meter_ct + 65536
            m.update(chunk)
        checksum = m.hexdigest()
        if checksum != csumvalue:
            logging.debug(_("Disk signature for %s does not match "
                            "Expected: %s  Received: %s" % (self.file,
                             csumvalue, checksum)))
            raise ValueError(_("Disk signature for %s does not "
                               "match" % self.file))


def validate(cond, msg):
    if not cond:
        raise RuntimeError(msg)


def xpathString(node, path, default=None):
    result = node.xpathEval("string(%s)" % path)
    if len(result) == 0:
        result = default
    return result


def parse(xml, filename):
    """Parse the XML description of a VM image into a data structure. Returns
    an object of class Image. BASE should be the directory where the disk
    image files for this image can be found"""
    def cb(x):
        return Image(x, filename=filename)
    return util.parse_node_helper(xml, "image", cb, RuntimeError)


def parse_file(filename):
    f = open(filename, "r")
    xml = f.read()
    f.close()
    return parse(xml, filename=filename)


class ImageInstaller(Installer):
    """
    Installer for virt-image-based guests
    """
    _has_install_phase = False

    def __init__(self, conn, image, boot_index=None):
        Installer.__init__(self, conn)

        self._image = image

        # Set boot _boot_caps/_boot_parameters
        if boot_index is None:
            self._boot_caps = match_boots(self.conn.caps,
                                     self.image.domain.boots)
            if self._boot_caps is None:
                raise RuntimeError(_("Could not find suitable boot "
                                     "descriptor for this host"))
        else:
            if (boot_index < 0 or
                (boot_index + 1) > len(image.domain.boots)):
                raise ValueError(_("boot_index out of range."))
            self._boot_caps = image.domain.boots[boot_index]

        # Set up internal caps.guest object
        self._guest = self.conn.caps.guestForOSType(self.boot_caps.type,
                                                    self.boot_caps.arch)
        if self._guest is None:
            raise RuntimeError(_("Unsupported virtualization type: %s %s" %
                               (self.boot_caps.type, self.boot_caps.arch)))
        self._domain = self._guest.bestDomainType()



    # Custom ImageInstaller methods
    def get_caps_guest(self):
        return self._guest, self._domain

    def get_image(self):
        return self._image
    image = property(get_image)

    def get_boot_caps(self):
        return self._boot_caps
    boot_caps = property(get_boot_caps)


    # General Installer methods
    def _prepare(self, guest, meter, scratchdir):
        ignore = scratchdir
        ignore = meter

        self._make_disks()

        for f in ['pae', 'acpi', 'apic']:
            if self.boot_caps.features[f] & CapabilitiesParser.FEATURE_ON:
                guest.features[f] = True
            elif self.boot_caps.features[f] & CapabilitiesParser.FEATURE_OFF:
                guest.features[f] = False

        guest.os.kernel = self.boot_caps.kernel
        guest.os.initrd = self.boot_caps.initrd
        guest.os.kernel_args = self.boot_caps.cmdline

    # Private methods
    def _get_bootdev(self, isinstall, guest):
        return self.boot_caps.bootdev

    def _make_disks(self):
        for drive in self.boot_caps.drives:
            path = self._abspath(drive.disk.file)
            size = None
            if drive.disk.size is not None:
                size = float(drive.disk.size) / 1024

            # FIXME: This is awkward; the image should be able to express
            # whether the disk is expected to be there or not independently
            # of its classification, especially for user disks
            # FIXME: We ignore the target for the mapping in m.target
            if (drive.disk.use == Disk.USE_SYSTEM and
                not os.path.exists(path)):
                raise RuntimeError(_("System disk %s does not exist") % path)

            device = VirtualDisk.DEVICE_DISK
            if drive.disk.format == Disk.FORMAT_ISO:
                device = VirtualDisk.DEVICE_CDROM

            disk = VirtualDisk(self.conn)
            disk.path = path
            disk.device = device
            disk.target = drive.target

            disk.set_create_storage(size=size, fmt=drive.disk.format)
            disk.validate()
            self.install_devices.append(disk)

    def _abspath(self, p):
        return self.image.abspath(p)


def match_boots(capabilities, boots):
    for b in boots:
        for g in capabilities.guests:
            if b.type == g.os_type and b.arch == g.arch:
                found = True
                for bf in b.features.names():
                    if not b.features[bf] & g.features[bf]:
                        found = False
                        break
                if found:
                    return b
    return None

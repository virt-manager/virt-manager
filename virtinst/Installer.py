#
# Common code for all guests
#
# Copyright 2006-2009  Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
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

import os
import platform
import logging
import copy

from virtinst import util
import virtinst
from virtinst import XMLBuilderDomain
from virtinst.XMLBuilderDomain import _xml_property
from virtinst import CapabilitiesParser
from virtinst.Boot import Boot

XEN_SCRATCH = "/var/lib/xen"
LIBVIRT_SCRATCH = "/var/lib/libvirt/boot"


def _pygrub_path(conn=None):
    # FIXME: This should be removed/deprecated when capabilities are
    #        fixed to provide bootloader info
    if conn:
        cap = CapabilitiesParser.parse(conn.getCapabilities())
        if (cap.host.arch == "i86pc"):
            return "/usr/lib/xen/bin/pygrub"
        else:
            return "/usr/bin/pygrub"

    if platform.system() == "SunOS":
        return "/usr/lib/xen/bin/pygrub"
    return "/usr/bin/pygrub"


class Installer(XMLBuilderDomain.XMLBuilderDomain):
    """
    Installer classes attempt to encapsulate all the parameters needed
    to 'install' a guest: essentially, booting the guest with the correct
    media for the OS install phase (if there is one), and setting up the
    guest to boot to the correct media for all subsequent runs.

    Some of the actual functionality:

        - Determining what type of install media has been requested, and
          representing it correctly to the Guest

        - Fetching install kernel/initrd or boot.iso from a URL

        - Setting the boot device as appropriate depending on whether we
          are booting into an OS install, or booting post-install

    Some of the information that the Installer needs to know to accomplish
    this:

        - Install media location (could be a URL, local path, ...)
        - Virtualization type (parameter 'os_type') ('xen', 'hvm', etc.)
        - Hypervisor name (parameter 'type') ('qemu', 'kvm', 'xen', etc.)
        - Guest architecture ('i686', 'x86_64')
    """
    _dumpxml_xpath = "/domain/os"
    _has_install_phase = True

    def __init__(self, type="xen", location=None,
                 extraargs=None, os_type=None, conn=None,
                 parsexml=None, parsexmlnode=None, caps=None):
        # pylint: disable=W0622
        # Redefining built-in 'type', but it matches the XML so keep it

        XMLBuilderDomain.XMLBuilderDomain.__init__(self, conn, parsexml,
                                                   parsexmlnode, caps=caps)

        self._type = None
        self._location = None
        self._initrd_injections = []
        self._cdrom = False
        self._os_type = None
        self._scratchdir = None
        self._arch = None
        self._machine = None
        self._loader = None
        self._init = None
        self._install_bootconfig = Boot(self.conn)
        self._bootconfig = Boot(self.conn, parsexml, parsexmlnode)

        # Devices created/added during the prepare() stage
        self.install_devices = []

        if self._is_parse():
            return

        # FIXME: Better solution? Skip validating this since we may not be
        # able to install a VM of the host arch
        if self._get_caps():
            self._arch = self._get_caps().host.arch

        if type is None:
            type = "xen"
        self.type = type

        if not os_type is None:
            self.os_type = os_type
        else:
            self.os_type = "xen"
        if not location is None:
            self.location = location

        self.extraargs = extraargs

        self._tmpfiles = []
        self._tmpvols = []

    def get_conn(self):
        return self._conn
    conn = property(get_conn)

    def _get_bootconfig(self):
        return self._bootconfig
    bootconfig = property(_get_bootconfig)

    # Hypervisor name (qemu, kvm, xen, lxc, etc.)
    def get_type(self):
        return self._type
    def set_type(self, val):
        self._type = val
    type = _xml_property(get_type, set_type,
                         xpath="./@type")

    # Virtualization type ('xen' == xen paravirt, or 'hvm)
    def get_os_type(self):
        return self._os_type
    def set_os_type(self, val):
        # Older libvirt back compat: if user specifies 'linux', convert
        # internally to newer equivalent value 'xen'
        if val == "linux":
            val = "xen"

        # XXX: Need to validate this: have some whitelist based on caps?
        self._os_type = val
    os_type = _xml_property(get_os_type, set_os_type,
                            xpath="./os/type")

    def get_arch(self):
        return self._arch
    def set_arch(self, val):
        # XXX: Sanitize to a consisten value (i368 -> i686)
        # XXX: Validate against caps
        self._arch = val
    arch = _xml_property(get_arch, set_arch,
                         xpath="./os/type/@arch")

    def _get_machine(self):
        return self._machine
    def _set_machine(self, val):
        self._machine = val
    machine = _xml_property(_get_machine, _set_machine,
                            xpath="./os/type/@machine")

    def _get_loader(self):
        return self._loader
    def _set_loader(self, val):
        self._loader = val
    loader = _xml_property(_get_loader, _set_loader,
                           xpath="./os/loader")

    def _get_init(self):
        return self._init
    def _set_init(self, val):
        self._init = val
    init = _xml_property(_get_init, _set_init,
                         xpath="./os/init")

    def get_scratchdir(self):
        if not self.scratchdir_required():
            return None

        if not self._scratchdir:
            self._scratchdir = self._get_scratchdir()
            logging.debug("scratchdir=%s", self._scratchdir)
        return self._scratchdir
    scratchdir = property(get_scratchdir)

    def get_cdrom(self):
        return self._cdrom
    def set_cdrom(self, enable):
        if enable not in [True, False]:
            raise ValueError(_("Guest.cdrom must be a boolean type"))
        self._cdrom = enable
    cdrom = property(get_cdrom, set_cdrom)

    def get_location(self):
        return self._location
    def set_location(self, val):
        self._location = val
    location = property(get_location, set_location)

    def get_initrd_injections(self):
        return self._initrd_injections
    def set_initrd_injections(self, val):
        self._initrd_injections = val
    initrd_injections = property(get_initrd_injections, set_initrd_injections)

    # extra arguments to pass to the guest installer
    def get_extra_args(self):
        return self._install_bootconfig.kernel_args
    def set_extra_args(self, val):
        self._install_bootconfig.kernel_args = val
    extraargs = property(get_extra_args, set_extra_args)


    # Public helper methods
    def scratchdir_required(self):
        """
        Returns true if scratchdir is needed for the passed install parameters.
        Apps can use this to determine if they should attempt to ensure
        scratchdir permissions are adequate
        """
        return False

    def is_hvm(self):
        return self.os_type == "hvm"
    def is_xenpv(self):
        return self.os_type in ["xen", "linux"]
    def is_container(self):
        return self.os_type == "exe"

    # Private methods
    def _get_system_scratchdir(self):
        if platform.system() == "SunOS":
            return "/var/tmp"

        if self.type == "test":
            return "/tmp"
        elif self.type == "xen":
            return XEN_SCRATCH
        else:
            return LIBVIRT_SCRATCH

    def _get_scratchdir(self):
        scratch = None
        if not self.is_session_uri():
            scratch = self._get_system_scratchdir()

        if (not scratch or
            not os.path.exists(scratch) or
            not os.access(scratch, os.W_OK)):
            scratch = os.path.expanduser("~/.virtinst/boot")
            if not os.path.exists(scratch):
                os.makedirs(scratch, 0751)

        return scratch

    def _get_bootdev(self, isinstall, guest):
        raise NotImplementedError("Must be implemented in subclass")

    def _build_boot_order(self, isinstall, guest):
        bootorder = [self._get_bootdev(isinstall, guest)]

        # If guest has an attached disk, always have 'hd' in the boot
        # list, so disks are marked as bootable/installable (needed for
        # windows virtio installs, and booting local disk from PXE)
        for disk in guest.get_devices("disk"):
            if disk.device == disk.DEVICE_DISK:
                bootdev = self.bootconfig.BOOT_DEVICE_HARDDISK
                if bootdev not in bootorder:
                    bootorder.append(bootdev)
                break

        return bootorder

    def _get_default_init(self, guest):
        if not self.is_container():
            return

        for fs in guest.get_devices("filesystem"):
            if fs.target == "/":
                return "/sbin/init"
        return "/bin/sh"

    def _get_osblob_helper(self, guest, isinstall, bootconfig):
        conn = guest.conn
        arch = self.arch
        machine = self.machine
        hvtype = self.type
        loader = self.loader
        os_type = self.os_type
        init = self.init or self._get_default_init(guest)

        hvxen = (hvtype == "xen")

        if not loader and self.is_hvm() and hvxen:
            loader = "/usr/lib/xen/boot/hvmloader"

        # Use older libvirt 'linux' value for back compat
        if os_type == "xen" and hvxen:
            os_type = "linux"

        if (not isinstall and
            self.is_xenpv() and
            not self.bootconfig.kernel):
            return "<bootloader>%s</bootloader>" % _pygrub_path(conn)

        osblob = "<os>"

        typexml = "    <type"
        if arch:
            typexml += " arch='%s'" % arch
        if machine:
            typexml += " machine='%s'" % machine
        typexml += ">%s</type>" % os_type

        osblob = util.xml_append(osblob, typexml)

        if init:
            osblob = util.xml_append(osblob,
                                      "    <init>%s</init>" %
                                      util.xml_escape(init))
        if loader:
            osblob = util.xml_append(osblob,
                                      "    <loader>%s</loader>" %
                                      util.xml_escape(loader))

        if not self.is_container():
            osblob = util.xml_append(osblob, bootconfig.get_xml_config())
        osblob = util.xml_append(osblob, "  </os>")

        return osblob


    # Method definitions

    def _get_xml_config(self, guest, isinstall):
        """
        Generate the portion of the guest xml that determines boot devices
        and parameters. (typically the <os></os> block)

        @param guest: Guest instance we are installing
        @type guest: L{Guest}
        @param isinstall: Whether we want xml for the 'install' phase or the
                          'post-install' phase.
        @type isinstall: C{bool}
        """
        # pylint: disable=W0221
        # Argument number differs from overridden method

        if isinstall:
            bootconfig = self._install_bootconfig
        else:
            bootconfig = self.bootconfig

        if isinstall and not self.has_install_phase():
            return

        bootorder = self._build_boot_order(isinstall, guest)
        bootconfig = copy.copy(bootconfig)
        if not bootconfig.bootorder:
            bootconfig.bootorder = bootorder

        return self._get_osblob_helper(guest, isinstall, bootconfig)

    def has_install_phase(self):
        """
        Return True if the requested setup is actually installing an OS
        into the guest. Things like LiveCDs, Import, or a manually specified
        bootorder do not have an install phase.
        """
        return self._has_install_phase

    def cleanup(self):
        """
        Remove any temporary files retrieved during installation
        """
        for f in self._tmpfiles:
            logging.debug("Removing " + f)
            os.unlink(f)

        for vol in self._tmpvols:
            logging.debug("Removing volume '%s'", vol.name())
            vol.delete(0)

        self._tmpvols = []
        self._tmpfiles = []
        self.install_devices = []

    def prepare(self, guest, meter):
        """
        Fetch any files needed for installation.
        @param guest: guest instance being installed
        @type guest: L{Guest}
        @param meter: progress meter
        @type meter: Urlgrabber ProgressMeter
        """
        raise NotImplementedError("Must be implemented in subclass")

    def detect_distro(self):
        """
        Attempt to detect the distro for the Installer's 'location'. If
        an error is encountered in the detection process (or if detection
        is not relevant for the Installer type), (None, None) is returned

        @returns: (distro type, distro variant) tuple
        """
        return (None, None)

    def guest_from_installer(self):
        """
        Return a L{Guest} instance wrapping the current installer.

        If all the appropriate values are present in the installer
        (conn, type, os_type, arch, machine), we have everything we need
        to determine what L{Guest} class is expected and what default values
        to pass it. This is a convenience method to save the API user from
        having to enter all these known details twice.
        """

        if not self.conn:
            raise ValueError(_("A connection must be specified."))

        guest, domain = CapabilitiesParser.guest_lookup(conn=self.conn,
                                                        caps=self._get_caps(),
                                                        os_type=self.os_type,
                                                        typ=self.type,
                                                        arch=self.arch,
                                                        machine=self.machine)

        gobj = virtinst.Guest(installer=self, conn=self.conn)
        gobj.arch = guest.arch
        gobj.emulator = domain.emulator
        self.loader = domain.loader

        return gobj


class ContainerInstaller(Installer):
    _has_install_phase = False

    def prepare(self, guest, meter):
        ignore = guest
        ignore = meter

    def _get_bootdev(self, isinstall, guest):
        ignore = isinstall
        ignore = guest
        return self.bootconfig.BOOT_DEVICE_HARDDISK

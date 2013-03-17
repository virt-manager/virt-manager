#
# Copyright 2008 Sun Microsystems, Inc.  All rights reserved.
# Use is subject to license terms.
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

import platform
from virtconv import _gettext as _
from virtconv import diskcfg
from virtinst import CapabilitiesParser

VM_TYPE_UNKNOWN = 0
VM_TYPE_PV = 1
VM_TYPE_HVM = 2

class vm(object):
    """
    Generic configuration for a particular VM instance.

    At export, a plugin is guaranteed to have the at least the following
    values set (any others needed should be checked for, raising
    ValueError on failure):

    vm.name
    vm.description (defaults to empty string)
    vm.nr_vcpus (defaults to 1)
    vm.type
    vm.arch

    If vm.memory is set, it is in Mb units.
    """

    name = None
    suffix = None

    def __init__(self):
        self.name = None
        self.description = None
        self.memory = None
        self.nr_vcpus = None
        self.disks = {}
        self.netdevs = {}
        self.type = VM_TYPE_HVM
        self.arch = "i686"
        self.noacpi = None
        self.noapic = None
        self.os_type = None
        self.os_variant = None

    def validate(self):
        """
        Validate all parameters, and fix up any unset values to meet the
        guarantees we make above.
        """

        if not self.name:
            raise ValueError(_("VM name is not set"))
        if not self.description:
            self.description = ""
        if not self.nr_vcpus:
            self.nr_vcpus = 1
        if self.type == VM_TYPE_UNKNOWN:
            raise ValueError(_("VM type is not set"))
        if not self.arch:
            raise ValueError(_("VM arch is not set"))

        for (bus, inst), disk in sorted(self.disks.iteritems()):
            if disk.type == diskcfg.DISK_TYPE_DISK and not disk.path:
                raise ValueError(_("Disk %s:%s storage does not exist")
                    % (bus, inst))

def host(conn=None):
    """
    Return the host, as seen in platform.system(), but possibly from a
    hypervisor connection.  Note: use default_arch() in almost all
    cases, unless you need to detect the OS.  In particular, this value
    gives no indication of 32 vs 64 bitness.
    """
    if conn:
        cap = CapabilitiesParser.parse(conn.getCapabilities())
        if cap.host.arch == "i86pc":
            return "SunOS"
        else:
            # or Linux-alike. Hmm.
            return "Linux"

    return platform.system()

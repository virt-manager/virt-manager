#
# Copyright 2013-2014 Red Hat, Inc.
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

import libvirt

from . import util
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _SnapshotDisk(XMLBuilder):
    _XML_ROOT_NAME = "disk"
    name = XMLProperty("./@name")
    snapshot = XMLProperty("./@snapshot")


class DomainSnapshot(XMLBuilder):
    @staticmethod
    def find_free_name(vm, collidelist):
        return util.generate_name("snapshot", vm.snapshotLookupByName,
                                  sep="", start_num=1, force_num=True,
                                  collidelist=collidelist)

    @staticmethod
    def state_str_to_int(state):
        statemap = {
            "nostate": libvirt.VIR_DOMAIN_NOSTATE,
            "running": libvirt.VIR_DOMAIN_RUNNING,
            "blocked": libvirt.VIR_DOMAIN_BLOCKED,
            "paused": libvirt.VIR_DOMAIN_PAUSED,
            "shutdown": libvirt.VIR_DOMAIN_SHUTDOWN,
            "shutoff": libvirt.VIR_DOMAIN_SHUTOFF,
            "crashed": libvirt.VIR_DOMAIN_CRASHED,
            "pmsuspended": getattr(libvirt, "VIR_DOMAIN_PMSUSPENDED", 7)
        }

        if state == "disk-snapshot" or state not in statemap:
            state = "shutoff"
        return statemap.get(state, libvirt.VIR_DOMAIN_NOSTATE)


    _XML_ROOT_NAME = "domainsnapshot"
    _XML_PROP_ORDER = ["name", "description", "creationTime"]

    name = XMLProperty("./name")
    description = XMLProperty("./description")
    state = XMLProperty("./state")
    creationTime = XMLProperty("./creationTime", is_int=True)
    parent = XMLProperty("./parent/name")

    memory_type = XMLProperty("./memory/@snapshot")

    disks = XMLChildProperty(_SnapshotDisk, relative_xpath="./disks")


    ##################
    # Public helpers #
    ##################

    def validate(self):
        if not self.name:
            raise RuntimeError(_("A name must be specified."))

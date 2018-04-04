#
# Copyright 2013-2014 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import libvirt

from . import util
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _SnapshotDisk(XMLBuilder):
    XML_NAME = "disk"
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


    XML_NAME = "domainsnapshot"
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

#
# Copyright 2013-2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _SnapshotDisk(XMLBuilder):
    XML_NAME = "disk"
    name = XMLProperty("./@name")
    snapshot = XMLProperty("./@snapshot")


class DomainSnapshot(XMLBuilder):
    XML_NAME = "domainsnapshot"
    _XML_PROP_ORDER = ["name", "description", "creationTime"]

    name = XMLProperty("./name")
    description = XMLProperty("./description")
    state = XMLProperty("./state")
    creationTime = XMLProperty("./creationTime", is_int=True)
    parent = XMLProperty("./parent/name")

    memory_type = XMLProperty("./memory/@snapshot")

    disks = XMLChildProperty(_SnapshotDisk, relative_xpath="./disks")

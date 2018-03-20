#
# Copyright 2014 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2.
# See the COPYING file in the top-level directory.

from .xmlbuilder import XMLBuilder, XMLProperty


class PM(XMLBuilder):
    _XML_ROOT_NAME = "pm"

    suspend_to_mem = XMLProperty("./suspend-to-mem/@enabled", is_yesno=True)
    suspend_to_disk = XMLProperty("./suspend-to-disk/@enabled", is_yesno=True)

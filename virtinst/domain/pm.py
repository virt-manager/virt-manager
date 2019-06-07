#
# Copyright 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty


class DomainPm(XMLBuilder):
    XML_NAME = "pm"

    suspend_to_mem = XMLProperty("./suspend-to-mem/@enabled", is_yesno=True)
    suspend_to_disk = XMLProperty("./suspend-to-disk/@enabled", is_yesno=True)


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        # When the suspend feature is exposed to VMs, an ACPI shutdown
        # event triggers a suspend in the guest, which causes a lot of
        # user confusion (especially compounded with the face that suspend
        # is often buggy so VMs can get hung, etc).
        #
        # We've been disabling this in virt-manager for a while, but lets
        # do it here too for consistency.
        if (guest.os.is_x86() and
            self.conn.support.conn_pm_disable()):
            if self.suspend_to_mem is None:
                self.suspend_to_mem = False
            if self.suspend_to_disk is None:
                self.suspend_to_disk = False

# Copyright (C) 2009, 2013 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from virtinst import Interface

from .libvirtobject import vmmLibvirtObject


class vmmInterface(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, Interface)


    ##########################
    # Required class methods #
    ##########################

    # Routines from vmmLibvirtObject
    def _conn_tick_poll_param(self):
        return "polliface"
    def class_name(self):
        return "interface"

    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def _get_backend_status(self):
        # The libvirt object can be active or inactive, but our code
        # doesn't care.
        return True

    def tick(self, stats_update=True):
        ignore = stats_update
        self._refresh_status()

    def _init_libvirt_state(self):
        self.tick()


    ################
    # XML routines #
    ################

    def is_bridge(self):
        return self.get_xmlobj().type == "bridge"

    def get_interface_names(self):
        return [obj.name for obj in self.get_xmlobj().interfaces]

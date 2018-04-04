# Copyright (C) 2011, 2013 Red Hat, Inc.
# Copyright (C) 2011 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from virtinst import NodeDevice

from .libvirtobject import vmmLibvirtObject


def _parse_convert(conn, parsexml=None):
    return NodeDevice.parse(conn, parsexml)


class vmmNodeDevice(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, _parse_convert)

    def _conn_tick_poll_param(self):
        return "pollnodedev"
    def class_name(self):
        return "nodedev"

    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def _get_backend_status(self):
        return self._STATUS_ACTIVE
    def _backend_get_name(self):
        return self.get_connkey()
    def is_active(self):
        return True
    def _using_events(self):
        return self.conn.using_node_device_events

    def tick(self, stats_update=True):
        # Deliberately empty
        ignore = stats_update
    def _init_libvirt_state(self):
        self.ensure_latest_xml()

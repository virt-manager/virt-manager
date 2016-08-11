#
# Copyright (C) 2011, 2013 Red Hat, Inc.
# Copyright (C) 2011 Cole Robinson <crobinso@redhat.com>
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
#

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

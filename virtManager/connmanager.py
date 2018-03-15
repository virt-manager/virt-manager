#
# Copyright (C) 2018 Red Hat, Inc.
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

import logging

from .baseclass import vmmGObject
from .connection import vmmConnection


class vmmConnectionManager(vmmGObject):
    """
    Tracks the list of connections, emits conn-added and conn-removed
    """
    __gsignals__ = {
        "conn-added": (vmmGObject.RUN_FIRST, None, [object]),
        "conn-removed": (vmmGObject.RUN_FIRST, None, [str]),
    }

    _instance = None

    @classmethod
    def get_instance(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = vmmConnectionManager(*args, **kwargs)
        return cls._instance

    def __init__(self):
        vmmGObject.__init__(self)

        self._conns = {}

        # Load URIs from gsettings
        for uri in self.config.get_conn_uris():
            self.add_conn(uri)

    def _cleanup(self):
        for conn in self._conns.values():
            uri = conn.get_uri()
            try:
                self.emit("conn-removed", uri)
                conn.cleanup()
            except Exception:
                logging.exception("Error cleaning up conn=%s", uri)
        self._conns = {}

    @property
    def conns(self):
        return self._conns.copy()

    def add_conn(self, uri):
        if uri in self._conns:
            return self._conns[uri]
        print("add uri", uri)
        conn = vmmConnection(uri)
        self._conns[uri] = conn
        self.config.add_conn_uri(uri)
        self.emit("conn-added", conn)
        return conn

    def remove_conn(self, uri):
        if uri not in self._conns:
            return
        conn = self._conns.pop(uri)
        self.config.remove_conn_uri(uri)
        self.emit("conn-removed", uri)
        conn.cleanup()

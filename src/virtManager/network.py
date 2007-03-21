#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import gobject
import libvirt
import libxml2
import os
import sys
import logging

class vmmNetwork(gobject.GObject):
    __gsignals__ = { }

    def __init__(self, config, connection, net, uuid):
        self.__gobject_init__()
        self.config = config
        self.connection = connection
        self.net = net
        self.uuid = uuid

    def set_handle(self, net):
        self.net = net

    def is_active(self):
        if self.net.ID() == -1:
            return False
        else:
            return True

    def get_connection(self):
        return self.connection

    def get_id(self):
        return self.net.ID()

    def get_id_pretty(self):
        id = self.get_id()
        if id < 0:
            return "-"
        return str(id)

    def get_name(self):
        return self.net.name()

    def get_label(self):
        return self.get_name()

    def get_uuid(self):
        return self.uuid

    def is_read_only(self):
        if self.connection.is_read_only():
            return True
        return False

    def get_xml_string(self, path):
        xml = self.net.XMLDesc(0)
        doc = None
        try:
            doc = libxml2.parseDoc(xml)
        except:
            return None
        ctx = doc.xpathNewContext()
        try:
            ret = ctx.xpathEval(path)
            tty = None
            if len(ret) == 1:
                tty = ret[0].content
            ctx.xpathFreeContext()
            doc.freeDoc()
            return tty
        except:
            ctx.xpathFreeContext()
            doc.freeDoc()
            return None

gobject.type_register(vmmNetwork)

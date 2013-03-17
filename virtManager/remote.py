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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.
#

import dbus.service

class vmmRemote(dbus.service.Object):
    def __init__(self, engine, bus_name, object_path="/com/redhat/virt/manager"):
        dbus.service.Object.__init__(self, bus_name, object_path)

        self.engine = engine

    @dbus.service.method("com.redhat.virt.manager", in_signature="s")
    def show_domain_creator(self, uri):
        self.engine.show_domain_creator(str(uri))

    @dbus.service.method("com.redhat.virt.manager", in_signature="ss")
    def show_domain_editor(self, uri, uuid):
        self.engine.show_domain_editor(str(uri), str(uuid))

    @dbus.service.method("com.redhat.virt.manager", in_signature="ss")
    def show_domain_performance(self, uri, uuid):
        self.engine.show_domain_performance(str(uri), str(uuid))

    @dbus.service.method("com.redhat.virt.manager", in_signature="ss")
    def show_domain_console(self, uri, uuid):
        self.engine.show_domain_console(str(uri), str(uuid))

    @dbus.service.method("com.redhat.virt.manager", in_signature="s")
    def show_host_summary(self, uri):
        self.engine.show_host_summary(str(uri))

    @dbus.service.method("com.redhat.virt.manager", in_signature="")
    def show_manager(self):
        self.engine.show_manager()

    @dbus.service.method("com.redhat.virt.manager")
    def show_connect(self):
        self.engine.show_connect()

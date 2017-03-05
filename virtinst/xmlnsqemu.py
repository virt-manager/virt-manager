# Copyright 2017 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _XMLNSQemuArg(XMLBuilder):
    _XML_ROOT_NAME = "qemu:arg"

    value = XMLProperty("./@value")


class _XMLNSQemuEnv(XMLBuilder):
    _XML_ROOT_NAME = "qemu:env"

    name = XMLProperty("./@name")
    value = XMLProperty("./@value")


class XMLNSQemu(XMLBuilder):
    """
    Class for generating <qemu:commandline> XML
    """
    _XML_ROOT_NAME = "qemu:commandline"

    args = XMLChildProperty(_XMLNSQemuArg)
    def add_arg(self, value):
        arg = _XMLNSQemuArg(conn=self.conn)
        arg.value = value
        self.add_child(arg)

    envs = XMLChildProperty(_XMLNSQemuEnv)
    def add_env(self, name, value):
        env = _XMLNSQemuEnv(conn=self.conn)
        env.name = name
        env.value = value
        self.add_child(env)

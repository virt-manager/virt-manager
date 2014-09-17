#
# Support for parsing libvirt's domcapabilities XML
#
# Copyright 2014 Red Hat, Inc.
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

from .xmlbuilder import XMLBuilder, XMLChildProperty
from .xmlbuilder import XMLProperty as _XMLProperty


class XMLProperty(_XMLProperty):
    # We don't care about full parsing coverage, so tell the test suite
    # not to warn
    _track = False


class _Value(XMLBuilder):
    _XML_ROOT_NAME = "value"
    value = XMLProperty(".")


class _HasValues(XMLBuilder):
    values = XMLChildProperty(_Value)

    def get_values(self):
        return [v.value for v in self.values]


class _Enum(_HasValues):
    _XML_ROOT_NAME = "enum"
    name = XMLProperty("./@name")


class _CapsBlock(_HasValues):
    supported = XMLProperty("./@supported", is_yesno=True)
    enums = XMLChildProperty(_Enum)

    def enum_names(self):
        return [e.name for e in self.enums]

    def get_enum(self, name):
        d = dict((e.name, e) for e in self.enums)
        return d[name]


def _make_capsblock(xml_root_name):
    class TmpClass(_CapsBlock):
        pass
    setattr(TmpClass, "_XML_ROOT_NAME", xml_root_name)
    return TmpClass


class _OS(_CapsBlock):
    _XML_ROOT_NAME = "os"
    loader = XMLChildProperty(_make_capsblock("loader"), is_single=True)


class _Devices(_CapsBlock):
    _XML_ROOT_NAME = "devices"
    hostdev = XMLChildProperty(_make_capsblock("hostdev"), is_single=True)
    disk = XMLChildProperty(_make_capsblock("disk"), is_single=True)


class DomainCapabilities(XMLBuilder):
    _XML_ROOT_NAME = "domainCapabilities"
    os = XMLChildProperty(_OS, is_single=True)
    devices = XMLChildProperty(_Devices, is_single=True)

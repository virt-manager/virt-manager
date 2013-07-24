#
# Copyright 2010  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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

from virtinst.xmlbuilder import XMLBuilder, XMLProperty


class DomainFeatures(XMLBuilder):
    """
    Class for generating <features> XML
    """
    _XML_ROOT_XPATH = "/domain/features"
    _XML_PROP_ORDER = ["acpi", "apic", "pae"]

    acpi = XMLProperty(xpath="./features/acpi", is_tri=True)
    apic = XMLProperty(xpath="./features/apic", is_tri=True)
    pae = XMLProperty(xpath="./features/pae", is_tri=True)

    def __setitem__(self, attr, val):
        return setattr(self, attr, bool(val))
    def __getitem__(self, attr):
        return getattr(self, attr)
    def __delitem__(self, attr):
        return setattr(self, attr, None)

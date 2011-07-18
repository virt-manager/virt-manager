#
# Copyright (C) 2011 Red Hat, Inc.
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

class vmmInspectionData(object):
    def __init__(self):
        self._type = None
        self._distro = None
        self._major_version = None
        self._minor_version = None
        self._hostname = None
        self._product_name = None
        self._product_variant = None
        self._icon = None
        self._applications = None

    def _set_type(self, new):
        self._type = str(new)
    def _get_type(self):
        return self._type
    type = property(_get_type, _set_type)
    def _set_distro(self, new):
        self._distro = str(new)
    def _get_distro(self):
        return self._distro
    distro = property(_get_distro, _set_distro)
    def _set_major_version(self, new):
        self._major_version = int(new)
    def _get_major_version(self):
        return self._major_version
    major_version = property(_get_major_version, _set_major_version)
    def _set_minor_version(self, new):
        self._minor_version = int(new)
    def _get_minor_version(self):
        return self._minor_version
    minor_version = property(_get_minor_version, _set_minor_version)
    def _set_hostname(self, new):
        self._hostname = str(new)
    def _get_hostname(self):
        return self._hostname
    hostname = property(_get_hostname, _set_hostname)
    def _set_product_name(self, new):
        self._product_name = str(new)
    def _get_product_name(self):
        return self._product_name
    product_name = property(_get_product_name, _set_product_name)
    def _set_product_variant(self, new):
        self._product_variant = str(new)
    def _get_product_variant(self):
        return self._product_variant
    product_variant = property(_get_product_variant, _set_product_variant)
    def _set_icon(self, new):
        self._icon = str(new)
    def _get_icon(self):
        return self._icon
    icon = property(_get_icon, _set_icon)
    def _set_applications(self, new):
        self._applications = list(new)
    def _get_applications(self):
        return self._applications
    applications = property(_get_applications, _set_applications)

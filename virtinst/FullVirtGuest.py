#
# Fullly virtualized guest support
#
# Copyright 2006-2007  Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
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

from Guest import Guest

class FullVirtGuest(Guest):

    _default_os_type = "hvm"

    def __init__(self, type=None, arch=None, connection=None,
                 hypervisorURI=None, emulator=None, installer=None,
                 caps=None, conn=None):
        Guest.__init__(self, type, connection, hypervisorURI, installer,
                       caps=caps, conn=conn)

        self.emulator = emulator
        if arch:
            self.arch = arch

    # Back compat
    def _get_loader(self):
        if not self.installer:
            return None
        return self.installer.loader
    def _set_loader(self, val):
        print val
        if not self.installer:
            return
        self.installer.loader = val
    loader = property(_get_loader, _set_loader)

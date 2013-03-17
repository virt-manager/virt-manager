# domainlistconfigscreen.py - Copyright (C) 2011 Red Hat, Inc.
# Written by Darryl L. Pierce <dpierce@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.  A copy of the GNU General Public License is
# also available at http://www.gnu.org/copyleft/gpl.html.

import snack

from vmmconfigscreen import VmmTuiConfigScreen

class DomainListConfigScreen(VmmTuiConfigScreen):
    '''Provides a base class for all config screens that require a domain list.'''

    def __init__(self, title):
        VmmTuiConfigScreen.__init__(self, title)
        self.__has_domains = None
        self.__domain_list = None

    def get_domain_list_page(self, screen, defined=True, created=True):
        ignore = screen # pylint ignore since it is not used here
        domuuids = self.get_libvirt().list_domains(defined, created)
        self.__has_domains = bool(domuuids)
        result = None

        if self.__has_domains:
            self.__domain_list = snack.Listbox(0)
            for uuid in domuuids:
                domain = self.get_libvirt().get_domain(uuid)

                # dom is a vmmDomain
                self.__domain_list.append(domain.get_name(), domain)
            result = [self.__domain_list]
        else:
            grid = snack.Grid(1, 1)
            grid.setField(snack.Label("There are no domains available."), 0, 0)
            result = [grid]

        return result

    def get_selected_domain(self):
        return self.__domain_list.current()

    def has_selectable_domains(self):
        return self.__has_domains

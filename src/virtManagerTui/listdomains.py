#!/usr/bin/env python
#
# listdomains.py - Copyright (C) 2009 Red Hat, Inc.
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

from snack import *
from libvirtworker import LibvirtWorker
from configscreen import *

class ListDomainsConfigScreen(DomainListConfigScreen):
    LIST_PAGE   = 1
    DETAIL_PAGE = 2

    def __init__(self):
        DomainListConfigScreen.__init__(self, 'List Virtual Machines')

    def page_has_next(self, page):
        return (page == self.LIST_PAGE)

    def page_has_back(self, page):
        return (page == self.DETAIL_PAGE)

    def validate_input(self, page, errors):
        if page == self.LIST_PAGE:
            if self.get_selected_domain() is None:
                errors.append("Please select a virtual machine to view.")
            else:
                return True

    def get_elements_for_page(self, screen, page):
        if page == self.LIST_PAGE:
            return self.get_domain_list_page(screen)
        elif page == self.DETAIL_PAGE:
            return self.get_detail_page_elements(screen)

    def get_detail_page_elements(self, screen):
        domain = self.get_libvirt().get_domain(self.get_selected_domain())
        grid = Grid(2, 5)
        grid.setField(Label("Name:  "), 0, 0, anchorRight = 1)
        grid.setField(Label(domain.name()), 1, 0, anchorLeft = 1)
        grid.setField(Label("UUID:  "), 0, 1, anchorRight = 1)
        grid.setField(Label(domain.UUIDString()), 1, 1, anchorLeft = 1)
        grid.setField(Label("OS Type:  "), 0, 2, anchorRight = 1)
        grid.setField(Label(domain.OSType()), 1, 2, anchorLeft = 1)
        grid.setField(Label("Max. Memory:  "), 0, 3, anchorRight = 1)
        grid.setField(Label(str(domain.maxMemory())), 1, 3, anchorLeft = 1)
        grid.setField(Label("Max. VCPUs:  "), 0, 4, anchorRight = 1)
        grid.setField(Label(str(domain.maxVcpus())), 1, 4, anchorLeft = 1)
        return [grid]

def ListDomains():
    screen = ListDomainsConfigScreen()
    screen.start()

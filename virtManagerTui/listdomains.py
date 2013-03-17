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

import snack
from domainlistconfigscreen import DomainListConfigScreen

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
        ignore = screen
        domain = self.get_selected_domain()
        fields = []

        # build the list to display
        fields.append(("Basic Details", None))
        fields.append(("Name", domain.get_name()))
        fields.append(("UUID", domain.get_uuid()))
        fields.append(("Status", domain.run_status()))
        fields.append(("Description", domain.get_description() or ""))
        fields.append(("", None))

        fields.append(("Hypervisor Details", None))
        fields.append(("Hypervisor", domain.get_pretty_hv_type()))
        fields.append(("Architecture", domain.get_arch() or "Unknown"))
        fields.append(("Emulator", domain.get_emulator() or "None"))
        fields.append(("", None))

        fields.append(("Machine Settings", None))
        if bool(domain.get_acpi()):
            fields.append(("ACPI", "Enabled"))
        if bool(domain.get_apic()):
            fields.append(("APIC", "Enabled"))
        fields.append(("Clock offset", domain.get_clock() or "Same as host"))
        fields.append(("", None))

        fields.append(("Security", None))

        semodel, setype, vmlabel = domain.get_seclabel()
        caps = self.get_libvirt().get_capabilities()
        if caps.host.secmodel  and caps.host.secmodel.model:
            semodel = caps.host.secmodel.model
        fields.append(("Model", semodel or "None"))

        if semodel is not None and semodel != "apparmor":
            fields.append(("Type", setype))
            fields.append(("Label", vmlabel))

        grid = snack.Grid(2, len(fields))
        row = 0
        for field in fields:
            if field[1] is not None:
                grid.setField(snack.Label("%s :  " % field[0]), 0, row, anchorRight=1)
                grid.setField(snack.Label(field[1]), 1, row, anchorLeft=1)
            else:
                grid.setField(snack.Label("%s" % field[0]), 1, row)
            row += 1

        return [grid]

def ListDomains():
    screen = ListDomainsConfigScreen()
    screen.start()

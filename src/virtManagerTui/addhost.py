# addhost.py - Copyright (C) 2009 Red Hat, Inc.
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

DETAILS_PAGE = 1
CONFIRM_PAGE = 2

HYPERVISOR_XEN      = "xen"
HYPERVISOR_KVM      = "kvm"

HYPERVISORS = {HYPERVISOR_XEN : "Xen",
               HYPERVISOR_KVM : "QEMU/KVM"}

CONNECTION_LOCAL    = "local"
CONNECTION_KERBEROS = "kerberos"
CONNECTION_SSL      = "ssl"
CONNECTION_SSH      = "ssh"

CONNECTIONS = {CONNECTION_LOCAL    : "Local",
               CONNECTION_KERBEROS : "Remote Password or Kerberos",
               CONNECTION_SSL      : "Remote SSL/TLS with x509 certificate",
               CONNECTION_SSH      : "Remote tunnel over SSH"}

class AddHostConfigScreen(VmmTuiConfigScreen):
    def __init__(self):
        VmmTuiConfigScreen.__init__(self, "Add A Remote Host")
        self.__configured = False
        self.__connection = None
        self.__hostname = None
        self.__autoconnect = None
        self.__hypervisor = None

    def get_elements_for_page(self, screen, page):
        if page is DETAILS_PAGE:
            return self.get_details_page(screen)
        elif page is CONFIRM_PAGE:
            return self.get_confirm_page(screen)

    def page_has_next(self, page):
        return page < CONFIRM_PAGE

    def page_has_back(self, page):
        return page > DETAILS_PAGE

    def page_has_finish(self, page):
        return page is CONFIRM_PAGE

    def validate_input(self, page, errors):
        if page is DETAILS_PAGE:
            if self.__connection.getSelection() is CONNECTION_LOCAL:
                return True
            elif len(self.__hostname.value()) > 0:
                return True
            else:
                errors.append("You must enter a remote hostname.")
        elif page is CONFIRM_PAGE:
            return True
        return False

    def process_input(self, page):
        if page is CONFIRM_PAGE:
            hv       = self.__hypervisor.getSelection()
            conn     = self.__connection.getSelection()
            hostname = self.__hostname.value()

            if   hv is HYPERVISOR_XEN:
                if   conn is CONNECTION_LOCAL:
                    url = "xen:///"
                elif conn is CONNECTION_KERBEROS:
                    url = "xen+tcp:///" + hostname + "/"
                elif conn is CONNECTION_SSL:
                    url = "xen+tls:///" + hostname + "/"
                elif conn is CONNECTION_SSH:
                    url = "xen+ssh:///" + hostname + "/"
            elif hv is HYPERVISOR_KVM:
                if   conn is CONNECTION_LOCAL:
                    url = "qemu:///system"
                elif conn is CONNECTION_KERBEROS:
                    url = "qemu+tcp://" + hostname + "/system"
                elif conn is CONNECTION_SSL:
                    url = "qemu+tls://" + hostname + "/system"
                elif conn is CONNECTION_SSH:
                    url = "qemu+ssh://" + hostname + "/system"

            self.get_virt_manager_config().add_connection(url)
            self.set_finished()

    def get_details_page(self, screen):
        if not self.__configured:
            self.__hypervisor = snack.RadioBar(screen, ((HYPERVISORS[HYPERVISOR_XEN], HYPERVISOR_XEN, True),
                                                  (HYPERVISORS[HYPERVISOR_KVM], HYPERVISOR_KVM, False)))
            self.__connection = snack.RadioBar(screen, ((CONNECTIONS[CONNECTION_LOCAL],    CONNECTION_LOCAL, True),
                                                  (CONNECTIONS[CONNECTION_KERBEROS], CONNECTION_KERBEROS, False),
                                                  (CONNECTIONS[CONNECTION_SSL],      CONNECTION_SSL, False),
                                                  (CONNECTIONS[CONNECTION_SSH],      CONNECTION_SSH, False)))
            self.__hostname = snack.Entry(50, "")
            self.__autoconnect = snack.Checkbox("Autoconnect on Startup")
            self.__configured = True
        grid = snack.Grid(2, 4)
        grid.setField(snack.Label("Hypervisor:"), 0, 0, anchorRight=1, anchorTop=1)
        grid.setField(self.__hypervisor, 1, 0, anchorLeft=1)
        grid.setField(snack.Label("Connection:"), 0, 1, anchorRight=1, anchorTop=1)
        grid.setField(self.__connection, 1, 1, anchorLeft=1)
        grid.setField(snack.Label("Hostname:"), 0, 2, anchorRight=1)
        grid.setField(self.__hostname, 1, 2, anchorLeft=1)
        grid.setField(snack.Label(""), 0, 3, anchorRight=1)
        grid.setField(self.__autoconnect, 1, 3, anchorLeft=1)
        return [snack.Label("Add Connection"),
                grid]

    def get_confirm_page(self, screen):
        ignore = screen

        grid = snack.Grid(2, 4)
        grid.setField(snack.Label("Hypervisor:"), 0, 0, anchorRight=1)
        grid.setField(snack.Label(HYPERVISORS[self.__hypervisor.getSelection()]), 1, 0, anchorLeft=1)
        grid.setField(snack.Label("Connection:"), 0, 1, anchorRight=1)
        grid.setField(snack.Label(CONNECTIONS[self.__connection.getSelection()]), 1, 1, anchorLeft=1)
        if self.__connection.getSelection() is not CONNECTION_LOCAL:
            hostname = self.__hostname.value()
        else:
            hostname = "local"
        grid.setField(snack.Label("Hostname:"), 0, 2, anchorRight=1)
        grid.setField(snack.Label(hostname), 1, 2, anchorLeft=1)
        grid.setField(snack.Label("Autoconnect on Startup:"), 0, 3, anchorRight=1)
        label = "Yes"
        if not self.__autoconnect.value():
            label = "No"
        grid.setField(snack.Label(label), 1, 3, anchorLeft=1)
        return [snack.Label("Confirm Connection"),
                grid]

def AddHost():
    screen = AddHostConfigScreen()
    screen.start()

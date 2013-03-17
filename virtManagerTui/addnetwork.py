# addnetwork.py - Copyright (C) 2009 Red Hat, Inc.
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

from snack import Checkbox
from snack import Entry
from snack import Label
from snack import RadioBar

from IPy import IP
import logging
import re

from vmmconfigscreen import VmmTuiConfigScreen
from networkconfig import NetworkConfig

NETWORK_NAME_PAGE            = 1
IPV4_ADDRESS_PAGE            = 2
PUBLIC_NETWORK_ALERT_PAGE    = 3
NETWORK_DETAILS_PAGE         = 4
DHCP_RANGE_PAGE              = 5
NETWORK_TYPE_PAGE            = 6
SELECT_PHYSICAL_NETWORK_PAGE = 7
SUMMARY_PAGE                 = 8

class AddNetworkConfigScreen(VmmTuiConfigScreen):
    def __init__(self):
        VmmTuiConfigScreen.__init__(self, "Create A Virtual Network Interface")
        self.__config = NetworkConfig()
        self.__end_address = None
        self.__start_address = None
        self.__name = None
        self.__isolated_network = None
        self.__physical_devices = None
        self.__ipv4_address = None

    def get_elements_for_page(self, screen, page):
        if   page is NETWORK_NAME_PAGE:
            return self.get_network_name_page(screen)
        elif page is IPV4_ADDRESS_PAGE:
            return self.get_ipv4_address_page(screen)
        elif page is PUBLIC_NETWORK_ALERT_PAGE:
            return self.get_public_network_alert_page(screen)
        elif page is NETWORK_DETAILS_PAGE:
            return self.get_network_details_page(screen)
        elif page is DHCP_RANGE_PAGE:
            return self.get_dhcp_range_page(screen)
        elif page is NETWORK_TYPE_PAGE:
            return self.get_network_type_page(screen)
        elif page is SELECT_PHYSICAL_NETWORK_PAGE:
            return self.get_select_physical_network_page(screen)
        elif page is SUMMARY_PAGE:
            return self.get_summary_page(screen)

    def validate_input(self, page, errors):
        if page is NETWORK_NAME_PAGE:
            if len(self.__name.value()) > 0:
                if re.match("^[a-zA-Z0-9_]*$", self.__name.value()):
                    return True
                else:
                    errors.append("The network name can only contain letters, numbers and the underscore, and no spaces.")
            else:
                errors.append("Network name must be non-blank and less than 50 characters")
        elif page is IPV4_ADDRESS_PAGE:
            if len(self.__ipv4_address.value()) > 0:
                try:
                    self.__config.set_ipv4_address(self.__ipv4_address.value())
                    return True
                except Exception, error:
                    errors.append("The network address could not be understood: %s" % str(error))
            else:
                errors.append("Network must be entered in the format 1.2.3.4/8")
        elif page is PUBLIC_NETWORK_ALERT_PAGE:
            return True
        elif page is NETWORK_DETAILS_PAGE:
            return True
        elif page is DHCP_RANGE_PAGE:
            try:
                if len(self.__start_address.value()) > 0 and len(self.__end_address.value()) > 0:
                    start = IP(self.__start_address.value(), )
                    end   = IP(self.__end_address.value())
                    if not self.__config.is_bad_address(start) and not self.__config.is_bad_address(end):
                        return True
                    else:
                        errors.append("Start and/or end address are outside of the choosen network.")
                else:
                    errors.append("Start and end address must be non-blank.")
            except Exception, error:
                logging.error(str(error))
                errors.append("The start and/or end addresses could not be understood.")
        elif page is NETWORK_TYPE_PAGE:
            return True
        elif page is SELECT_PHYSICAL_NETWORK_PAGE:
            return True
        elif page is SUMMARY_PAGE:
            return True
        return False

    def process_input(self, page):
        if page is NETWORK_NAME_PAGE:
            self.__config.set_name(self.__name.value())
        elif page is DHCP_RANGE_PAGE:
            self.__config.set_ipv4_start_address(self.__start_address.value())
            self.__config.set_ipv4_end_address(self.__end_address.value())
        elif page is NETWORK_TYPE_PAGE:
            self.__config.set_isolated_network(self.__isolated_network.value())
        elif page is SELECT_PHYSICAL_NETWORK_PAGE:
            self.__config.set_physical_device(self.__physical_devices.getSelection())
        elif page is SUMMARY_PAGE:
            self.get_libvirt().define_network(self.__config)
            self.set_finished()

    def get_next_page(self, page):
        if page is IPV4_ADDRESS_PAGE:
            if self.__config.is_public_ipv4_network():
                return PUBLIC_NETWORK_ALERT_PAGE
            else:
                return NETWORK_DETAILS_PAGE
        if page is NETWORK_TYPE_PAGE:
            if self.__config.is_isolated_network():
                return SUMMARY_PAGE
            else:
                return SELECT_PHYSICAL_NETWORK_PAGE
        return VmmTuiConfigScreen.get_next_page(self, page)

    def get_back_page(self, page):
        if page is NETWORK_DETAILS_PAGE:
            return IPV4_ADDRESS_PAGE
        if page is SUMMARY_PAGE:
            if self.__config.is_isolated_network():
                return NETWORK_TYPE_PAGE
            else:
                return SELECT_PHYSICAL_NETWORK_PAGE
        return VmmTuiConfigScreen.get_back_page(self, page)

    def page_has_finish(self, page):
        if page is SUMMARY_PAGE:
            return True
        return False

    def page_has_next(self, page):
        if page < SUMMARY_PAGE:
            return True

    def page_has_back(self, page):
        if page > NETWORK_NAME_PAGE:
            return True
        return False

    def get_network_name_page(self, screen):
        ignore = screen
        self.__name = Entry(50, self.__config.get_name())
        fields = []
        fields.append(("Network name", self.__name))

        return [Label("Please choose a name for your virtual network"),
                self.create_grid_from_fields(fields)]

    def get_ipv4_address_page(self, screen):
        ignore = screen
        self.__ipv4_address = Entry(18, self.__config.get_ipv4_address())
        fields = []
        fields.append(("Network", self.__ipv4_address))
        return [Label("You will need to choose an IPv4 address space for the virtual network"),
                self.create_grid_from_fields(fields)]

    def get_network_details_page(self, screen):
        ignore = screen
        fields = []
        fields.append(("Network details", None))
        fields.append(("Network", self.__config.get_ipv4_address()))
        fields.append(("Netmask", self.__config.get_ipv4_netmask()))
        fields.append(("Broadcast", self.__config.get_ipv4_broadcast()))
        fields.append(("Gateway", self.__config.get_ipv4_gateway()))
        fields.append(("Size", "%i" % self.__config.get_ipv4_max_addresses()))
        fields.append(("Type", self.__config.get_ipv4_network_type()))
        return [self.create_grid_from_fields(fields)]

    def get_public_network_alert_page(self, screen):
        ignore = screen
        return [Label("Check Network Address"),
                Label("The network should normally use a private IPv4 address."),
                Label("Use this non-private address anyway?")]

    def get_dhcp_range_page(self, screen):
        ignore = screen
        self.__start_address = Entry(15, self.__config.get_ipv4_start_address())
        self.__end_address   = Entry(15, self.__config.get_ipv4_end_address())
        fields = []
        fields.append(("Select the DHCP range", None))
        fields.append(("Start", self.__start_address))
        fields.append(("End", self.__end_address))
        return [Label("Selecting The DHCP Range"),
                self.create_grid_from_fields(fields),
                Label("TIP: Unless you wish to reserve some addresses to allow static network"),
                Label("configuration in virtual machines, these paraemters can be left with"),
                Label("their default values.")]

    def get_network_type_page(self, screen):
        ignore = screen
        self.__isolated_network = Checkbox("Isolated virtual network",
                                           self.__config.is_isolated_network())
        fields = []
        fields.append((self.__isolated_network, None))

        return [Label("Please indicate whether this virtual network should be"),
                Label("connected to the physical network."),
                self.create_grid_from_fields(fields)]

    def get_select_physical_network_page(self, screen):
        ignore = screen
        devices = []
        devices.append(["NAT to any physical device", "", self.__config.get_physical_device() == ""])
        for device in self.get_libvirt().list_network_devices():
            devices.append(["NAT to physical device %s" % device, device, self.__config.get_physical_device() == device])
        self.__physical_devices = RadioBar(screen, (devices))
        fields = []
        fields.append(("Forward to physical network", self.__physical_devices))
        return [Label("Connecting To Physical Network"),
                self.create_grid_from_fields(fields)]

    def get_summary_page(self, screen):
        ignore = screen
        fields = []
        fields.append(("Summary", None))
        fields.append(("Network name", self.__config.get_name()))
        fields.append(("IPv4 network", None))
        fields.append(("Network", self.__config.get_ipv4_address()))
        fields.append(("Gateway", self.__config.get_ipv4_gateway()))
        fields.append(("Netmask", self.__config.get_ipv4_netmask()))
        fields.append(("DHCP", None))
        fields.append(("Start address", self.__config.get_ipv4_start_address()))
        fields.append(("End address", self.__config.get_ipv4_end_address()))
        fields.append(("Forwarding", None))
        forwarding = "Isolated virtual network"
        if not self.__config.is_isolated_network():
            forwarding = "NAT to %s" % self.__config.get_physical_device_text()
        fields.append(("Connectivity", forwarding))

        return [Label("Ready To Create Network"),
                self.create_grid_from_fields(fields)]

def AddNetwork():
    screen = AddNetworkConfigScreen()
    screen.start()

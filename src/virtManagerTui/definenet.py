# definenet.py - Copyright (C) 2009 Red Hat, Inc.
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
from IPy import IP
import logging
import re

from configscreen import ConfigScreen
from networkconfig import NetworkConfig

NETWORK_NAME_PAGE            = 1
IPV4_ADDRESS_PAGE            = 2
PUBLIC_NETWORK_ALERT_PAGE    = 3
NETWORK_DETAILS_PAGE         = 4
DHCP_RANGE_PAGE              = 5
NETWORK_TYPE_PAGE            = 6
SELECT_PHYSICAL_NETWORK_PAGE = 7
SUMMARY_PAGE                 = 8

class DefineNetworkConfigScreen(ConfigScreen):
    def __init__(self):
        ConfigScreen.__init__(self, "Create A Virtual Network Interface")
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
        return ConfigScreen.get_next_page(self, page)

    def get_back_page(self, page):
        if page is NETWORK_DETAILS_PAGE:
            return IPV4_ADDRESS_PAGE
        if page is SUMMARY_PAGE:
            if self.__config.is_isolated_network():
                return NETWORK_TYPE_PAGE
            else:
                return SELECT_PHYSICAL_NETWORK_PAGE
        return ConfigScreen.get_back_page(self, page)

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
        self.__name = snack.Entry(50, self.__config.get_name())
        grid = snack.Grid(2, 1)
        grid.setField(snack.Label("Network Name:"), 0, 0)
        grid.setField(self.__name, 1, 0)
        return [snack.Label("Please choose a name for your virtual network"),
                grid]

    def get_ipv4_address_page(self, screen):
        ignore = screen
        self.__ipv4_address = snack.Entry(18, self.__config.get_ipv4_address())
        grid = snack.Grid(2, 1)
        grid.setField(snack.Label("Network:"), 0, 0, anchorRight = 1)
        grid.setField(self.__ipv4_address, 1, 0, anchorLeft = 1)
        return [snack.Label("You will need to choose an IPv4 address space for the virtual network:"),
                grid,
                snack.Label("HINT: The network should be chosen from"),
                snack.Label("one of the IPv4 private address ranges;"),
                snack.Label("e.g., 10.0.0.0/8, 172.168.0.0/12, 192.168.0.0/16")]

    def get_network_details_page(self, screen):
        ignore = screen
        grid = snack.Grid(2, 6)
        grid.setField(snack.Label("Network:"), 0, 0, anchorRight = 1)
        grid.setField(snack.Label(self.__config.get_ipv4_address()), 1, 0, anchorLeft = 1)
        grid.setField(snack.Label("Netmask:"), 0, 1, anchorRight = 1)
        grid.setField(snack.Label(self.__config.get_ipv4_netmask()), 1, 1, anchorLeft = 1)
        grid.setField(snack.Label("Broadcast:"), 0, 2, anchorRight = 1)
        grid.setField(snack.Label(self.__config.get_ipv4_broadcast()), 1, 2, anchorLeft = 1)
        grid.setField(snack.Label("Gateway:"), 0, 3, anchorRight = 1)
        grid.setField(snack.Label(self.__config.get_ipv4_gateway()), 1, 3, anchorLeft = 1)
        grid.setField(snack.Label("Size:"), 0, 4, anchorRight = 1)
        grid.setField(snack.Label("%d addresses" % self.__config.get_ipv4_max_addresses()), 1, 4, anchorLeft = 1)
        grid.setField(snack.Label("Type:"), 0, 5, anchorRight = 1)
        grid.setField(snack.Label(self.__config.get_ipv4_network_type()), 1, 5, anchorLeft = 1)
        return [snack.Label("Network Details"),
                grid]

    def get_public_network_alert_page(self, screen):
        ignore = screen
        grid = snack.Grid(1, 2)
        grid.setField(snack.Label("The network should normally use a private IPv4 address."), 0, 0, anchorLeft = 1)
        grid.setField(snack.Label("Use this non-private address anyway?"), 0, 1, anchorLeft = 1)
        return [snack.Label("Check Network Address"),
                grid]

    def get_dhcp_range_page(self, screen):
        ignore = screen
        self.__start_address = snack.Entry(15, self.__config.get_ipv4_start_address())
        self.__end_address   = snack.Entry(15, self.__config.get_ipv4_end_address())
        grid = snack.Grid(2, 2)
        grid.setField(snack.Label("Start:"), 0, 0, anchorRight = 1)
        grid.setField(self.__start_address, 1, 0, anchorLeft = 1)
        grid.setField(snack.Label("End:"), 0, 1, anchorRight = 1)
        grid.setField(self.__end_address, 1, 1, anchorLeft = 1)
        return [snack.Label("Selecting The DHCP Range"),
                grid,
                snack.Label("TIP: Unless you wish to reserve some addresses to allow static network"),
                snack.Label("configuration in virtual machines, these paraemters can be left with"),
                snack.Label("their default values.")]

    def get_network_type_page(self, screen):
        ignore = screen
        self.__isolated_network = snack.Checkbox("Isolated virtual network",
                                           self.__config.is_isolated_network())
        grid = snack.Grid(1, 3)
        grid.setField(snack.Label("Please indicate whether this virtual network should be"), 0, 0, anchorLeft = 1)
        grid.setField(snack.Label("connected to the physical network."), 0, 1, anchorLeft = 1)
        grid.setField(self.__isolated_network, 0, 2)
        return [snack.Label("Connecting To Physical Network"),
                grid]

    def get_select_physical_network_page(self, screen):
        ignore = screen
        devices = []
        devices.append(["NAT to any physical device", "", self.__config.get_physical_device() == ""])
        for device in self.get_hal().list_network_devices():
            devices.append(["NAT to physical device %s" % device, device, self.__config.get_physical_device() == device])
        self.__physical_devices = snack.RadioBar(screen, (devices))
        grid = snack.Grid(1, 2)
        grid.setField(snack.Label("Forward to physical network:"), 0, 0)
        grid.setField(self.__physical_devices, 0, 1)
        return [snack.Label("Connecting To Physical Network"),
                grid]

    def get_summary_page(self, screen):
        ignore = screen
        grid1 = snack.Grid(2, 1)
        grid1.setField(snack.Label("Network name:"), 0, 0, anchorRight = 1)
        grid1.setField(snack.Label(self.__config.get_name()), 1, 0, anchorLeft = 1)

        grid2 = snack.Grid(2, 3)
        grid2.setField(snack.Label("Network:"), 0, 0, anchorRight = 1)
        grid2.setField(snack.Label(self.__config.get_ipv4_address()), 1, 0, anchorLeft = 1)
        grid2.setField(snack.Label("Gateway:"), 0, 1, anchorRight = 1)
        grid2.setField(snack.Label(self.__config.get_ipv4_gateway()), 1, 1, anchorLeft = 1)
        grid2.setField(snack.Label("Netmask:"), 0, 2, anchorRight = 1)
        grid2.setField(snack.Label(self.__config.get_ipv4_netmask()), 1, 2, anchorLeft = 1)

        grid3 = snack.Grid(2, 2)
        grid3.setField(snack.Label("Start address:"), 0, 0, anchorRight = 1)
        grid3.setField(snack.Label(self.__config.get_ipv4_start_address()), 1, 0, anchorLeft = 1)
        grid3.setField(snack.Label("End address:"), 0, 1, anchorRight = 1)
        grid3.setField(snack.Label(self.__config.get_ipv4_end_address()), 1, 1, anchorLeft = 1)

        grid4 = snack.Grid(2, 1)
        grid4.setField(snack.Label("Connectivity:"), 0, 0, anchorRight = 1)
        if self.__config.is_isolated_network():
            grid4.setField(snack.Label("Isolated virtual network"), 1, 0, anchorLeft = 1)
        else:
            grid4.setField(snack.Label("NAT to %s" % self.__config.get_physical_device_text()), 1, 0, anchorLeft = 1)

        return [snack.Label("Ready To Create Network"),
                snack.Label("Summary"),
                grid1,
                snack.Label("IPv4 Network"),
                grid2,
                snack.Label("DHCP"),
                grid3,
                snack.Label("Forwarding"),
                grid4]

def DefineNetwork():
    screen = DefineNetworkConfigScreen()
    screen.start()

# networkconfig.py - Copyright (C) 2009 Red Hat, Inc.
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

from IPy import IP

class NetworkConfig:
    def __init__(self):
        self.__name = ""
        self.__isolated_network = True
        self.__physical_device = ""
        self.__ipv4_end = None
        self.__ipv4_start = None
        self.__ipv4_address = None
        self.set_ipv4_address("192.168.100.0/24")

    def set_name(self, name):
        self.__name = name

    def get_name(self):
        return self.__name

    def set_ipv4_address(self, address):
        self.__ipv4_address = IP(address)
        start = int(self.__ipv4_address.len() / 2)
        end   = self.__ipv4_address.len() - 2
        self.__ipv4_start = str(self.__ipv4_address[start])
        self.__ipv4_end   = str(self.__ipv4_address[end])

    def get_ipv4_address(self):
        return self.__ipv4_address.strNormal()

    def get_ipv4_address_raw(self):
        return self.__ipv4_address

    def get_ipv4_netmask(self):
        return self.__ipv4_address.netmask().strNormal()

    def get_ipv4_broadcast(self):
        return self.__ipv4_address.broadcast().strNormal()

    def get_ipv4_gateway(self):
        return str(self.__ipv4_address[1])

    def get_ipv4_max_addresses(self):
        return self.__ipv4_address.len()

    def get_ipv4_network_type(self):
        return self.__ipv4_address.iptype()

    def is_public_ipv4_network(self):
        if self.__ipv4_address.iptype() is "PUBLIC":
            return True
        return False

    def set_ipv4_start_address(self, address):
        self.__ipv4_start = address

    def get_ipv4_start_address(self):
        return self.__ipv4_start

    def set_ipv4_end_address(self, address):
        self.__ipv4_end = address

    def get_ipv4_end_address(self):
        return self.__ipv4_end

    def is_bad_address(self, address):
        return not self.__ipv4_address.overlaps(address)

    def set_isolated_network(self, isolated):
        self.__isolated_network = isolated

    def is_isolated_network(self):
        return self.__isolated_network

    def set_physical_device(self, device):
        self.__physical_device = device

    def get_physical_device(self):
        return self.__physical_device

    def get_physical_device_text(self):
        if self.__physical_device == "":
            return "any physical device"
        else:
            return "physical device %s" % self.__physical_device

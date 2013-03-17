#
# Copyright 2008 Sun Microsystems, Inc.  All rights reserved.
# Use is subject to license terms.
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
#

NETDEV_TYPE_UNKNOWN = 0
NETDEV_TYPE_BRIDGE = 1
NETDEV_TYPE_DEV = 2
NETDEV_TYPE_NETWORK = 3

class netdev(object):
    """Definition of an individual network device."""

    def __init__(self, mac="auto", type=NETDEV_TYPE_UNKNOWN,
                 source=None, driver=None):
        """
        @mac: either a MAC address, or "auto"
        @type: NETDEV_TYPE_*
        @source: bridge or net device, or network name
        @driver: device emulated for VM (e.g. vmxnet)
        """
        self.mac = mac
        self.type = type
        self.source = source
        self.driver = driver

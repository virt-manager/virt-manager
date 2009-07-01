#
# Copyright (C) 2007 Red Hat, Inc.
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

import logging
import os
import sys
import traceback
import glob

import gobject
import dbus

from virtManager.netdev import vmmNetDevice

class vmmNetDevHelper(gobject.GObject):
    __gsignals__ = {
        "netdev-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                         [str]),
        "netdev-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                           [str]),
    }

    def __init__(self, config):
        self.__gobject_init__()

        self.config = config
        self.bus = None
        self.hal_iface = None

        # Whether we have successfully connected to dbus and polled once
        # Unused for now
        self.initialized = False

        # Host network devices. name -> vmmNetDevice object
        self.netdevs = {}
        # Mapping of hal IDs to net names
        self.hal_to_netdev = {}

        self._dbus_connect()

    def list_net_device_paths(self):
        return self.netdevs.keys()

    def get_net_device(self, path):
        return self.netdevs[path]

    def _dbus_connect(self):
        # Probe for network devices
        try:
            # Get a connection to the SYSTEM bus
            self.bus = dbus.SystemBus()
            # Get a handle to the HAL service
            hal_object = self.bus.get_object('org.freedesktop.Hal',
                                             '/org/freedesktop/Hal/Manager')
            self.hal_iface = dbus.Interface(hal_object,
                                            'org.freedesktop.Hal.Manager')

            # Track device add/removes so we can detect newly inserted CD media
            self.hal_iface.connect_to_signal("DeviceAdded",
                                             self._net_phys_device_added)
            self.hal_iface.connect_to_signal("DeviceRemoved",
                                             self._net_phys_device_removed)

            bondMasters = get_bonding_masters()
            logging.debug("Bonding masters are: %s" % bondMasters)
            for bond in bondMasters:
                sysfspath = "/sys/class/net/" + bond
                mac = get_net_mac_address(bond, sysfspath)
                if mac:
                    self._net_device_added(bond, mac, sysfspath)
                    # Add any associated VLANs
                    self._net_tag_device_added(bond, sysfspath)

            # Find info about all current present physical net devices
            # This is OS portable...
            for path in self.hal_iface.FindDeviceByCapability("net"):
                self._net_phys_device_added(path)
        except:
            (_type, value, stacktrace) = sys.exc_info ()
            logging.error("Unable to connect to HAL to list network "
                          "devices: '%s'" +
                          str(_type) + " " + str(value) + "\n" +
                          traceback.format_exc (stacktrace))


    def _net_phys_device_added(self, path):
        obj = self.bus.get_object("org.freedesktop.Hal", path)
        objif = dbus.Interface(obj, "org.freedesktop.Hal.Device")

        if objif.QueryCapability("net"):
            name = objif.GetPropertyString("net.interface")
            # HAL gives back paths to like:
            # /sys/devices/pci0000:00/0000:00:1e.0/0000:01:00.0/net/eth0
            # which doesn't work so well - we want this:
            sysfspath = "/sys/class/net/" + name

            # If running a device in bridged mode, there's a reasonable
            # chance that the actual ethernet device has been renamed to
            # something else. ethN -> pethN
            psysfspath = sysfspath[0:len(sysfspath)-len(name)] + "p" + name
            if os.path.exists(psysfspath):
                logging.debug("Device %s named to p%s" % (name, name))
                name = "p" + name
                sysfspath = psysfspath

            # Ignore devices that are slaves of a bond
            if is_net_bonding_slave(name, sysfspath):
                logging.debug("Skipping device %s in bonding slave" % name)
                return

            mac = objif.GetPropertyString("net.address")

            # Add the main NIC
            self._net_device_added(name, mac, sysfspath, path)

            # Add any associated VLANs
            self._net_tag_device_added(name, sysfspath)

    def _net_phys_device_removed(self, path):
        if self.hal_to_netdev.has_key(path):
            name = self.hal_to_netdev[path]
            logging.debug("Removing physical net device %s from list." % name)

            dev = self.netdevs[name]
            self.emit("netdev-removed", dev.get_name())
            del self.netdevs[name]
            del self.hal_to_netdev[path]

    def _net_tag_device_added(self, name, sysfspath):
        for vlanpath in glob.glob(sysfspath + ".*"):
            if os.path.exists(vlanpath):
                logging.debug("Process VLAN %s" % vlanpath)
                vlanmac = get_net_mac_address(name, vlanpath)
                if vlanmac:
                    (ignore, vlanname) = os.path.split(vlanpath)

                    # If running a device in bridged mode, there's areasonable
                    # chance that the actual ethernet device has beenrenamed to
                    # something else. ethN -> pethN
                    pvlanpath = (vlanpath[0:len(vlanpath)-len(vlanname)] +
                                 "p" + vlanname)
                    if os.path.exists(pvlanpath):
                        logging.debug("Device %s named to p%s" % (vlanname,
                                                                  vlanname))
                        vlanname = "p" + vlanname
                        vlanpath = pvlanpath
                    self._net_device_added(vlanname, vlanmac, vlanpath)

    def _net_device_added(self, name, mac, sysfspath, halpath=None):
        # Race conditions mean we can occassionally see device twice
        if self.netdevs.has_key(name):
            return

        bridge = get_net_bridge_owner(name, sysfspath)
        shared = False
        if bridge is not None:
            shared = True

        logging.debug("Adding net device %s %s %s (bridge: %s)" %
                      (name, mac, sysfspath, str(bridge)))

        dev = vmmNetDevice(self.config, self, name, mac, shared, bridge)
        self._add_net_dev(name, halpath, dev)

    def _add_net_dev(self, name, halpath, dev):
        if halpath:
            self.hal_to_netdev[halpath] = name
        self.netdevs[name] = dev
        self.emit("netdev-added", dev.get_name())

gobject.type_register(vmmNetDevHelper)


def get_net_bridge_owner(name, sysfspath):
    # Now magic to determine if the device is part of a bridge
    brportpath = os.path.join(sysfspath, "brport")

    try:
        if os.path.exists(brportpath):
            brlinkpath = os.path.join(brportpath, "bridge")
            dest = os.readlink(brlinkpath)
            (ignore, bridge) = os.path.split(dest)
            return bridge
    except:
        (_type, value, stacktrace) = sys.exc_info ()
        logging.error("Unable to determine if device is shared:" +
                      str(_type) + " " + str(value) + "\n" +
                      traceback.format_exc (stacktrace))
    return None

def get_net_mac_address(name, sysfspath):
    mac = None
    addrpath = sysfspath + "/address"
    if os.path.exists(addrpath):
        df = open(addrpath, 'r')
        mac = df.readline().strip(" \n\t")
        df.close()
    return mac

def get_bonding_masters():
    masters = []
    if os.path.exists("/sys/class/net/bonding_masters"):
        f = open("/sys/class/net/bonding_masters")
        while True:
            rline = f.readline()
            if not rline:
                break
            if rline == "\x00":
                continue
            rline = rline.strip("\n\t")
            masters = rline[:].split(' ')
    return masters

def is_net_bonding_slave(name, sysfspath):
    masterpath = sysfspath + "/master"
    if os.path.exists(masterpath):
        return True
    return False

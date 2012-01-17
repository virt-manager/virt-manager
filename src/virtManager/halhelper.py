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
import glob

import dbus

from virtManager.baseclass import vmmGObject
from virtManager.netdev import vmmNetDevice
from virtManager.mediadev import vmmMediaDevice

_hal_helper = None

def get_hal_helper(init=True):
    global _hal_helper
    if not _hal_helper and init:
        _hal_helper = vmmHalHelper()
    return _hal_helper

def cleanup():
    global _hal_helper
    if _hal_helper:
        _hal_helper.cleanup()
    _hal_helper = None

def get_net_bridge_owner(name_ignore, sysfspath):
    # Now magic to determine if the device is part of a bridge
    brportpath = os.path.join(sysfspath, "brport")

    try:
        if os.path.exists(brportpath):
            brlinkpath = os.path.join(brportpath, "bridge")
            dest = os.readlink(brlinkpath)
            (ignore, bridge) = os.path.split(dest)
            return bridge
    except:
        logging.exception("Unable to determine if device is shared")

    return None

def get_net_mac_address(name_ignore, sysfspath):
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

def is_net_bonding_slave(name_ignore, sysfspath):
    masterpath = sysfspath + "/master"
    if os.path.exists(masterpath):
        return True
    return False

class vmmHalHelper(vmmGObject):
    def __init__(self):
        vmmGObject.__init__(self)

        self.bus = None
        self.hal_iface = None
        self.sigs = []

        # Error message we encountered when initializing
        self.startup_error = None

        self._dbus_connect()

    def _cleanup(self):
        self.bus = None
        self.hal_iface = None

        for sig in self.sigs:
            sig.remove()
        self.sigs = []

    def get_init_error(self):
        return self.startup_error

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
            self.sigs.append(
                self.hal_iface.connect_to_signal("DeviceAdded",
                                                 self._device_added))
            self.sigs.append(
                self.hal_iface.connect_to_signal("DeviceRemoved",
                                                 self._device_removed))
        except Exception, e:
            logging.error("Unable to connect to HAL to list network "
                          "devices: " + str(e))
            self.startup_error = str(e)

    def connect(self, name, callback, *args):
        handle_id = vmmGObject.connect(self, name, callback, *args)

        if name == "netdev-added":
            self.populate_netdevs()

        elif name == "optical-added":
            self.populate_opt_media()

        return handle_id


    ##################
    # Helper methods #
    ##################

    def dbus_dev_lookup(self, halpath):
        obj = self.bus.get_object("org.freedesktop.Hal", halpath)
        objif = dbus.Interface(obj, "org.freedesktop.Hal.Device")
        return objif

    def is_cdrom_media(self, halpath):
        obj = self.dbus_dev_lookup(halpath)
        return bool(obj.QueryCapability("volume") and
                    obj.GetPropertyBoolean("volume.is_disc") and
                    obj.GetPropertyBoolean("volume.disc.has_data"))

    def is_cdrom(self, halpath):
        obj = self.dbus_dev_lookup(halpath)
        return bool(obj.QueryCapability("storage.cdrom"))

    def is_netdev(self, halpath):
        obj = self.dbus_dev_lookup(halpath)
        return bool(obj.QueryCapability("net"))


    #############################
    # Initial device population #
    #############################

    def populate_opt_media(self):
        for path in self.hal_iface.FindDeviceByCapability("storage.cdrom"):
            # Make sure we only populate CDROM devs
            if not self.is_cdrom(path):
                continue

            devnode, media_label, media_hal_path = self._fetch_cdrom_info(path)
            self.add_optical_dev(str(devnode), str(path), media_label,
                                 media_hal_path)


    def populate_netdevs(self):
        bondMasters = get_bonding_masters()

        for bond in bondMasters:
            sysfspath = "/sys/class/net/" + bond
            mac = get_net_mac_address(bond, sysfspath)
            if mac:
                self._net_device_added(bond, mac, sysfspath)

                # Add any associated VLANs
                self._net_tag_device_added(bond, sysfspath)

        # Find info about all current present physical net devices
        for path in self.hal_iface.FindDeviceByCapability("net"):
            self._net_phys_device_added(path)


    #############################
    # Device callback listeners #
    #############################

    def _device_added(self, path):
        if self.is_cdrom_media(path):
            self._optical_media_added(path)
        elif self.is_cdrom(path):
            self._optical_added(path)
        elif self.is_netdev(path):
            self._net_phys_device_added(path)

    def _device_removed(self, path):
        self.emit("device-removed", str(path))

    def add_optical_dev(self, devpath, halpath, media_label, media_hal_path):
        obj = vmmMediaDevice(devpath, halpath, bool(media_label),
                             media_label, media_hal_path)
        obj.set_hal_media_signals(self)
        self.emit("optical-added", obj)

    def _optical_added(self, halpath):
        devpath, media_label, media_hal_path = self._fetch_cdrom_info(halpath)
        self.add_optical_dev(devpath, halpath, media_label, media_hal_path)

    def _optical_media_added(self, media_hal_path):
        media_label, devpath = self._fetch_media_info(media_hal_path)

        self.emit("optical-media-added", devpath, media_label, media_hal_path)

    def _net_phys_device_added(self, halpath):
        dbusobj = self.dbus_dev_lookup(halpath)

        name = dbusobj.GetPropertyString("net.interface")
        mac = dbusobj.GetPropertyString("net.address")

        # HAL gives back paths to like:
        # /sys/devices/pci0000:00/0000:00:1e.0/0000:01:00.0/net/eth0
        # which doesn't work so well - we want this:
        sysfspath = "/sys/class/net/" + name

        # If running a device in bridged mode, there's a reasonable
        # chance that the actual ethernet device has been renamed to
        # something else. ethN -> pethN
        psysfspath = sysfspath[0:len(sysfspath) - len(name)] + "p" + name
        if os.path.exists(psysfspath):
            logging.debug("Device %s named to p%s", name, name)
            name = "p" + name
            sysfspath = psysfspath

        # Ignore devices that are slaves of a bond
        if is_net_bonding_slave(name, sysfspath):
            logging.debug("Skipping device %s in bonding slave", name)
            return

        # Add the main NIC
        self._net_device_added(name, mac, sysfspath, halpath)

        # Add any associated VLANs
        self._net_tag_device_added(name, sysfspath)

    def _net_tag_device_added(self, name, sysfspath):
        for vlanpath in glob.glob(sysfspath + ".*"):
            if os.path.exists(vlanpath):
                logging.debug("Process VLAN %s", vlanpath)
                vlanmac = get_net_mac_address(name, vlanpath)
                if vlanmac:
                    (ignore, vlanname) = os.path.split(vlanpath)

                    # If running a device in bridged mode, there's areasonable
                    # chance that the actual ethernet device has beenrenamed to
                    # something else. ethN -> pethN
                    pvlanpath = (vlanpath[0:len(vlanpath) - len(vlanname)] +
                                 "p" + vlanname)
                    if os.path.exists(pvlanpath):
                        logging.debug("Device %s named to p%s",
                                      vlanname, vlanname)
                        vlanname = "p" + vlanname
                        vlanpath = pvlanpath
                    self._net_device_added(vlanname, vlanmac, vlanpath)

    def _net_device_added(self, name, mac, sysfspath, halpath=None):
        bridge = get_net_bridge_owner(name, sysfspath)
        shared = False
        if bridge is not None:
            shared = True

        dev = vmmNetDevice(name, mac, shared, bridge, halpath)
        self.emit("netdev-added", dev)


    ######################
    # CDROM info methods #
    ######################

    def _fetch_media_info(self, halpath):
        label = None
        devnode = None

        volif = self.dbus_dev_lookup(halpath)

        devnode = volif.GetProperty("block.device")
        label = volif.GetProperty("volume.label")
        if not label:
            label = devnode

        return (label and str(label), devnode and str(devnode))

    def _fetch_cdrom_info(self, halpath):
        devif = self.dbus_dev_lookup(halpath)

        devnode = devif.GetProperty("block.device")
        media_label = None
        media_hal_path = None

        if devnode:
            media_label, media_hal_path = self._find_media_for_devpath(devnode)

        return (devnode and str(devnode), media_label, media_hal_path)

    def _find_media_for_devpath(self, devpath):
        for path in self.hal_iface.FindDeviceByCapability("volume"):
            if not self.is_cdrom_media(path):
                continue

            label, devnode = self._fetch_media_info(path)

            if devnode == devpath:
                return (label, path)

        return None, None

vmmHalHelper.type_register(vmmHalHelper)
vmmHalHelper.signal_new(vmmHalHelper, "netdev-added", [object])
vmmHalHelper.signal_new(vmmHalHelper, "optical-added", [object])
vmmHalHelper.signal_new(vmmHalHelper, "optical-media-added", [str, str, str])
vmmHalHelper.signal_new(vmmHalHelper, "device-removed", [str])

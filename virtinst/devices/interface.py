#
# Copyright 2006-2009, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import random

from .device import Device
from ..logger import log
from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


def _random_mac(conn):
    """Generate a random MAC address.

    00-16-3E allocated to xensource
    52-54-00 used by qemu/kvm

    The OUI list is available at https://standards.ieee.org/regauth/oui/oui.txt.

    The remaining 3 fields are random, with the first bit of the first
    random field set 0.

    @return: MAC address string
    """

    if conn.is_qemu():
        oui = [0x52, 0x54, 0x00]
    else:
        # Xen
        oui = [0x00, 0x16, 0x3E]

    mac = oui + [
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff)]
    return ':'.join(["%02x" % x for x in mac])


def _default_route():
    route_file = "/proc/net/route"
    if not os.path.exists(route_file):  # pragma: no cover
        log.debug("route_file=%s does not exist", route_file)
        return None

    for line in open(route_file):
        info = line.split()
        if len(info) != 11:  # pragma: no cover
            log.debug("Unexpected field count=%s when parsing %s",
                          len(info), route_file)
            break

        try:
            route = int(info[1], 16)
            if route == 0:
                return info[0]
        except ValueError:
            continue

    return None  # pragma: no cover


def _host_default_bridge():
    dev = _default_route()
    if not dev:
        return None  # pragma: no cover

    # New style peth0 == phys dev, eth0 == bridge, eth0 == default route
    if os.path.exists("/sys/class/net/%s/bridge" % dev):
        return dev  # pragma: no cover

    # Old style, peth0 == phys dev, eth0 == netloop, xenbr0 == bridge,
    # vif0.0 == netloop attached, eth0 == default route
    try:
        defn = int(dev[-1])
    except Exception:  # pragma: no cover
        defn = -1

    if (defn >= 0 and
        os.path.exists("/sys/class/net/peth%d/brport" % defn) and
        os.path.exists("/sys/class/net/xenbr%d/bridge" % defn)):
        return "xenbr%d"  # pragma: no cover
    return None


# Cache the host default bridge lookup. It can change over the lifetime
# of a virt-manager run, but that should be rare, and this saves us
# possibly spamming logs if host lookup goes wrong
_HOST_DEFAULT_BRIDGE = -1


def _default_bridge(conn):
    if conn.is_remote():
        return None

    global _HOST_DEFAULT_BRIDGE
    if _HOST_DEFAULT_BRIDGE == -1:
        try:
            ret = _host_default_bridge()
        except Exception:  # pragma: no cover
            log.debug("Error getting host default bridge", exc_info=True)
            ret = None
        _HOST_DEFAULT_BRIDGE = ret

    ret = _HOST_DEFAULT_BRIDGE
    if conn.in_testsuite():
        ret = "testsuitebr0"
    return ret


_MAC_COUNTER = 0


def _testsuite_mac():
    # Generate predictable mac addresses for the test suite
    # For some tests, we need to make sure that different mac addresses
    # would _not_ be generated in normal operations, so we add some magic
    # here to increment the generated address with a special env variable
    global _MAC_COUNTER

    base = "00:11:22:33:44:55"
    ret = base[:-1] + str(int(base[-1]) + _MAC_COUNTER)
    _MAC_COUNTER += 1

    if "VIRTINST_TEST_SUITE_INCREMENT_MACADDR" not in os.environ:
        _MAC_COUNTER = 0
    return ret


class _VirtualPort(XMLBuilder):
    XML_NAME = "virtualport"

    type = XMLProperty("./@type")
    managerid = XMLProperty("./parameters/@managerid", is_int=True)
    typeid = XMLProperty("./parameters/@typeid", is_int=True)
    typeidversion = XMLProperty("./parameters/@typeidversion", is_int=True)
    instanceid = XMLProperty("./parameters/@instanceid")
    profileid = XMLProperty("./parameters/@profileid")
    interfaceid = XMLProperty("./parameters/@interfaceid")


class DeviceInterface(Device):
    XML_NAME = "interface"

    TYPE_BRIDGE     = "bridge"
    TYPE_VIRTUAL    = "network"
    TYPE_USER       = "user"
    TYPE_VHOSTUSER  = "vhostuser"
    TYPE_ETHERNET   = "ethernet"
    TYPE_DIRECT   = "direct"

    @staticmethod
    def generate_mac(conn):
        """
        Generate a random MAC that doesn't conflict with any VMs on
        the connection.
        """
        if conn.fake_conn_predictable():
            return _testsuite_mac()

        for ignore in range(256):
            mac = _random_mac(conn)
            try:
                DeviceInterface.check_mac_in_use(conn, mac)
                return mac
            except RuntimeError:  # pragma: no cover
                continue

        log.debug(  # pragma: no cover
                "Failed to generate non-conflicting MAC")
        return None  # pragma: no cover

    @staticmethod
    def check_mac_in_use(conn, searchmac):
        """
        Raise RuntimeError if the passed mac conflicts with a defined VM
        """
        if not searchmac:
            return

        vms = conn.fetch_all_domains()
        for vm in vms:
            for nic in vm.devices.interface:
                nicmac = nic.macaddr or ""
                if nicmac.lower() == searchmac.lower():
                    raise RuntimeError(
                            _("The MAC address '%s' is in use "
                              "by another virtual machine.") % searchmac)

    @staticmethod
    def default_bridge(conn):
        """
        Return the bridge virt-install would use as a default value,
        if one is setup on the host
        """
        return _default_bridge(conn)


    ###############
    # XML helpers #
    ###############

    def _get_source(self):
        """
        Convenience function, try to return the relevant <source> value
        per the network type.
        """
        if self.type == self.TYPE_VIRTUAL:
            return self.network
        if self.type == self.TYPE_BRIDGE:
            return self.bridge
        if self.type == self.TYPE_DIRECT:
            return self.source_dev
        return None
    def _set_source(self, newsource):
        """
        Convenience function, try to set the relevant <source> value
        per the network type
        """
        self.bridge = None
        self.network = None
        self.source_dev = None

        if self.type == self.TYPE_VIRTUAL:
            self.network = newsource
        elif self.type == self.TYPE_BRIDGE:
            self.bridge = newsource
        elif self.type == self.TYPE_DIRECT:
            self.source_dev = newsource
    source = property(_get_source, _set_source)


    ##################
    # XML properties #
    ##################

    _XML_PROP_ORDER = [
        "bridge", "network", "source_dev", "source_type", "source_path",
        "source_mode", "portgroup", "macaddr", "target_dev", "model",
        "virtualport", "filterref", "rom_bar", "rom_file", "mtu_size"]

    bridge = XMLProperty("./source/@bridge")
    network = XMLProperty("./source/@network")
    source_dev = XMLProperty("./source/@dev")

    virtualport = XMLChildProperty(_VirtualPort, is_single=True)
    type = XMLProperty("./@type")
    trustGuestRxFilters = XMLProperty("./@trustGuestRxFilters", is_yesno=True)

    macaddr = XMLProperty("./mac/@address")

    source_type = XMLProperty("./source/@type")
    source_path = XMLProperty("./source/@path")
    source_mode = XMLProperty("./source/@mode")
    portgroup = XMLProperty("./source/@portgroup")
    model = XMLProperty("./model/@type")
    target_dev = XMLProperty("./target/@dev")
    filterref = XMLProperty("./filterref/@filter")
    link_state = XMLProperty("./link/@state")

    driver_name = XMLProperty("./driver/@name")
    driver_queues = XMLProperty("./driver/@queues", is_int=True)

    rom_bar = XMLProperty("./rom/@bar", is_onoff=True)
    rom_file = XMLProperty("./rom/@file")

    mtu_size = XMLProperty("./mtu/@size", is_int=True)


    #############
    # Build API #
    #############

    def set_default_source(self):
        if self.conn.is_qemu_unprivileged() or self.conn.is_test():
            self.type = self.TYPE_USER
            return

        nettype = DeviceInterface.TYPE_BRIDGE
        source = DeviceInterface.default_bridge(self.conn)
        if not source:
            nettype = DeviceInterface.TYPE_VIRTUAL
            source = "default"

        self.type = nettype
        self.source = source


    ##################
    # Default config #
    ##################

    @staticmethod
    def default_model(guest):
        if not guest.os.is_hvm():
            return None
        if guest.supports_virtionet():
            return "virtio"
        if guest.os.is_q35():
            return "e1000e"
        if not guest.os.is_x86():
            return None

        prefs = ["e1000", "rtl8139", "ne2k_pci", "pcnet"]
        supported_models = guest.osinfo.supported_netmodels()
        for pref in prefs:
            if pref in supported_models:
                return pref
        return "e1000"

    def set_defaults(self, guest):
        if not self.type:
            self.type = self.TYPE_BRIDGE
        if not self.macaddr:
            self.macaddr = self.generate_mac(self.conn)
        if self.type == self.TYPE_BRIDGE and not self.bridge:
            self.bridge = _default_bridge(self.conn)
        if not self.model:
            self.model = self.default_model(guest)

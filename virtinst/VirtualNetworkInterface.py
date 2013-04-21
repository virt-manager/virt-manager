#
# Copyright 2006-2009  Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
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

import logging
import libvirt

from virtinst import util
from virtinst.VirtualDevice import VirtualDevice
from virtinst import XMLBuilderDomain
from virtinst.XMLBuilderDomain import _xml_property


def _compareMAC(p, q):
    """Compare two MAC addresses"""
    pa = p.split(":")
    qa = q.split(":")

    if len(pa) != len(qa):
        if p > q:
            return 1
        else:
            return -1

    for i in xrange(len(pa)):
        n = int(pa[i], 0x10) - int(qa[i], 0x10)
        if n > 0:
            return 1
        elif n < 0:
            return -1
    return 0


def _countMACaddr(vms, searchmac):
    if not searchmac:
        return

    def count_cb(ctx):
        c = 0

        for mac in ctx.xpathEval("/domain/devices/interface/mac"):
            macaddr = mac.xpathEval("attribute::address")[0].content
            if macaddr and _compareMAC(searchmac, macaddr) == 0:
                c += 1
        return c

    count = 0
    for vm in vms:
        xml = vm.XMLDesc(0)
        count += util.get_xml_path(xml, func=count_cb)
    return count


class VirtualPort(XMLBuilderDomain.XMLBuilderDomain):

    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None):
        XMLBuilderDomain.XMLBuilderDomain.__init__(self, conn, parsexml,
                                                   parsexmlnode, caps=caps)
        self._type = None
        self._managerid = None
        self._typeid = None
        self._typeidversion = None
        self._instanceid = None

    def get_type(self):
        return self._type
    def set_type(self, val):
        self._type = val
    type = _xml_property(get_type, set_type,
                                  xpath="./virtualport/@type")

    def get_managerid(self):
        return self._managerid
    def set_managerid(self, val):
        self._managerid = val
    managerid = _xml_property(get_managerid, set_managerid,
                                  xpath="./virtualport/parameters/@managerid")

    def get_typeid(self):
        return self._typeid
    def set_typeid(self, val):
        self._typeid = val
    typeid = _xml_property(get_typeid, set_typeid,
                               xpath="./virtualport/parameters/@typeid")

    def get_typeidversion(self):
        return self._typeidversion
    def set_typeidversion(self, val):
        self._typeidversion = val
    typeidversion = _xml_property(get_typeidversion, set_typeidversion,
                               xpath="./virtualport/parameters/@typeidversion")

    def get_instanceid(self):
        return self._instanceid
    def set_instanceid(self, val):
        self._instanceid = val
    instanceid = _xml_property(get_instanceid, set_instanceid,
                               xpath="./virtualport/parameters/@instanceid")

    def _get_xml_config(self):
        # FIXME: This should be implemented, currently we can only parse
        return ""


class VirtualNetworkInterface(VirtualDevice):

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_NET

    TYPE_BRIDGE     = "bridge"
    TYPE_VIRTUAL    = "network"
    TYPE_USER       = "user"
    TYPE_ETHERNET   = "ethernet"
    TYPE_DIRECT   = "direct"
    network_types = [TYPE_BRIDGE, TYPE_VIRTUAL, TYPE_USER, TYPE_ETHERNET,
                     TYPE_DIRECT]

    def get_network_type_desc(net_type):
        """
        Return human readable description for passed network type
        """
        desc = net_type.capitalize()

        if net_type == VirtualNetworkInterface.TYPE_BRIDGE:
            desc = _("Shared physical device")
        elif net_type == VirtualNetworkInterface.TYPE_VIRTUAL:
            desc = _("Virtual networking")
        elif net_type == VirtualNetworkInterface.TYPE_USER:
            desc = _("Usermode networking")

        return desc
    get_network_type_desc = staticmethod(get_network_type_desc)

    def __init__(self, macaddr=None, type=TYPE_BRIDGE, bridge=None,
                 network=None, model=None, conn=None,
                 parsexml=None, parsexmlnode=None, caps=None):
        # pylint: disable=W0622
        # Redefining built-in 'type', but it matches the XML so keep it

        VirtualDevice.__init__(self, conn, parsexml, parsexmlnode, caps)

        self._network = None
        self._bridge = None
        self._macaddr = None
        self._type = None
        self._model = None
        self._target_dev = None
        self._source_dev = None
        self._source_mode = "vepa"
        self._virtualport = VirtualPort(conn, parsexml, parsexmlnode, caps)

        # Generate _random_mac
        self._random_mac = None
        self._default_bridge = None

        if self._is_parse():
            return

        self.type = type
        self.macaddr = macaddr
        self.bridge = bridge
        self.source_dev = bridge
        self.network = network
        self.model = model

        if self.type == self.TYPE_VIRTUAL:
            if network is None:
                raise ValueError(_("A network name was not provided"))

    def _generate_default_bridge(self):
        ret = self._default_bridge
        if ret is None:
            ret = False
            default = util.default_bridge(self.conn)
            if default:
                ret = default[1]

        self._default_bridge = ret
        return ret or None

    def _generate_random_mac(self):
        if self.conn and not self._random_mac:
            found = False
            for ignore in range(256):
                self._random_mac = util.randomMAC(self.conn.getType().lower(),
                                                  conn=self.conn)
                ret = self.is_conflict_net(self.conn, self._random_mac)
                if ret[1] is not None:
                    continue
                found = True
                break

            if not found:
                logging.debug("Failed to generate non-conflicting MAC")
        return self._random_mac

    def get_source(self):
        """
        Convenince function, try to return the relevant <source> value
        per the network type.
        """
        if self.type == self.TYPE_VIRTUAL:
            return self.network
        if self.type == self.TYPE_BRIDGE:
            return self.bridge
        if self.type == self.TYPE_ETHERNET or self.type == self.TYPE_DIRECT:
            return self.source_dev
        if self.type == self.TYPE_USER:
            return None
        return self.network or self.bridge or self.source_dev

    def set_source(self, newsource):
        """
        Conveninece function, try to set the relevant <source> value
        per the network type
        """
        if self.type == self.TYPE_VIRTUAL:
            self.network = newsource
        elif self.type == self.TYPE_BRIDGE:
            self.bridge = newsource
        elif self.type == self.TYPE_ETHERNET or self.type == self.TYPE_DIRECT:
            self.source_dev = newsource
        return
    source = property(get_source, set_source)

    def _get_virtualport(self):
        return self._virtualport
    virtualport = property(_get_virtualport)

    def get_type(self):
        return self._type
    def set_type(self, val):
        if val not in self.network_types:
            raise ValueError(_("Unknown network type %s") % val)
        self._type = val
    type = _xml_property(get_type, set_type,
                         xpath="./@type")

    def get_macaddr(self):
        # Don't generate a random MAC if parsing XML, since it can be slow
        if not self._macaddr and not self._is_parse():
            return self._generate_random_mac()
        return self._macaddr
    def set_macaddr(self, val):
        util.validate_macaddr(val)
        self._macaddr = val
    macaddr = _xml_property(get_macaddr, set_macaddr,
                            xpath="./mac/@address")

    def get_network(self):
        return self._network
    def set_network(self, newnet):
        def _is_net_active(netobj):
            # Apparently the 'info' command was never hooked up for
            # libvirt virNetwork python apis.
            if not self.conn:
                return True
            return self.conn.listNetworks().count(netobj.name())

        if newnet is not None and self.conn:
            try:
                net = self.conn.networkLookupByName(newnet)
            except libvirt.libvirtError, e:
                raise ValueError(_("Virtual network '%s' does not exist: %s")
                                   % (newnet, str(e)))
            if not _is_net_active(net):
                raise ValueError(_("Virtual network '%s' has not been "
                                   "started.") % newnet)

        self._network = newnet
    network = _xml_property(get_network, set_network,
                            xpath="./source/@network")

    def get_bridge(self):
        if (not self._is_parse() and
            not self._bridge and
            self.type == self.TYPE_BRIDGE):
            return self._generate_default_bridge()
        return self._bridge
    def set_bridge(self, val):
        self._bridge = val
    bridge = _xml_property(get_bridge, set_bridge,
                           xpath="./source/@bridge")

    def get_model(self):
        return self._model
    def set_model(self, val):
        self._model = val
    model = _xml_property(get_model, set_model,
                          xpath="./model/@type")

    def get_target_dev(self):
        return self._target_dev
    def set_target_dev(self, val):
        self._target_dev = val
    target_dev = _xml_property(get_target_dev, set_target_dev,
                               xpath="./target/@dev")

    def get_source_dev(self):
        return self._source_dev
    def set_source_dev(self, val):
        self._source_dev = val
    source_dev = _xml_property(get_source_dev, set_source_dev,
                               xpath="./source/@dev")

    def get_source_mode(self):
        return self._source_mode
    def set_source_mode(self, newmode):
        self._source_mode = newmode
    source_mode = _xml_property(get_source_mode, set_source_mode,
                                xpath="./source/@mode")

    def is_conflict_net(self, conn, mac=None):
        """
        @returns: a two element tuple:
            first element is True if fatal collision occured
            second element is a string description of the collision.

            Non fatal collisions (mac addr collides with inactive guest) will
            return (False, "description of collision")
        """
        mac = mac or self.macaddr
        if mac is None:
            return (False, None)

        vms, inactive_vm = util.fetch_all_guests(conn)

        if (_countMACaddr(vms, mac) > 0 or
            _countMACaddr(inactive_vm, mac) > 0):
            return (True, _("The MAC address '%s' is in use "
                            "by another virtual machine.") % mac)

        return (False, None)

    def setup_dev(self, conn=None, meter=None):
        return self.setup(conn)

    def setup(self, conn=None):
        """
        DEPRECATED: Please use setup_dev instead
        """
        # Access self.macaddr to generate a random one
        if not self.conn and conn:
            self.conn = conn
        if not conn:
            conn = self.conn

        if self.macaddr:
            ret, msg = self.is_conflict_net(conn)
            if msg is not None:
                if ret is False:
                    logging.warning(msg)
                else:
                    raise RuntimeError(msg)

    def _get_xml_config(self):
        src_xml = ""
        model_xml = ""
        target_xml = ""
        addr_xml = ""
        if self.type == self.TYPE_BRIDGE:
            src_xml     = "      <source bridge='%s'/>\n" % self.bridge
        elif self.type == self.TYPE_VIRTUAL:
            src_xml     = "      <source network='%s'/>\n" % self.network
        elif self.type == self.TYPE_ETHERNET and self.source_dev:
            src_xml     = "      <source dev='%s'/>\n" % self.source_dev
        elif self.type == self.TYPE_DIRECT and self.source_dev:
            src_xml     = "      <source dev='%s' mode='%s'/>\n" % (self.source_dev, self.source_mode)

        if self.model:
            model_xml   = "      <model type='%s'/>\n" % self.model

        if self.address:
            addr_xml = self.indent(self.address.get_xml_config(), 6)

        if self.target_dev:
            target_xml  = "      <target dev='%s'/>\n" % self.target_dev

        xml  = "    <interface type='%s'>\n" % self.type
        xml += src_xml
        xml += "      <mac address='%s'/>\n" % self.macaddr
        xml += target_xml
        xml += model_xml
        xml += addr_xml
        xml += "    </interface>"
        return xml

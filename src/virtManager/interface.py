#
# Copyright (C) 2009 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
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

from virtinst import Interface

from virtManager import util
from virtManager.libvirtobject import vmmLibvirtObject

class vmmInterface(vmmLibvirtObject):
    def __init__(self, conn, interface, name, active):
        vmmLibvirtObject.__init__(self, conn)

        self.interface = interface  # Libvirt virInterface object
        self.name = name            # String name
        self.active = active        # bool indicating if it is running

        self._xml = None            # xml cache
        self._xml_flags = None

        (self._inactive_xml_flags,
         self._active_xml_flags) = self.conn.get_interface_flags(
                                                            self.interface)

        self.refresh_xml()

    # Routines from vmmLibvirtObject
    def _XMLDesc(self, flags):
        return self.interface.XMLDesc(flags)

    def _define(self, xml):
        return self.conn.define_interface(xml)

    def xpath(self, *args, **kwargs):
        # Must use this function for ALL XML parsing
        ret = util.xpath(self.get_xml(), *args, **kwargs)
        if ret:
            return ret
        if not self.is_active():
            return ret

        # The running config did not have the info requested
        return util.xpath(self.get_xml(inactive=True), *args, **kwargs)

    def set_active(self, state):
        self.active = state
        self.refresh_xml()

    def is_active(self):
        return self.active

    def get_name(self):
        return self.name

    def get_mac(self):
        return self.xpath("/interface/mac/@address")

    def start(self):
        self.interface.create(0)
        self.idle_add(self.refresh_xml)

    def stop(self):
        self.interface.destroy(0)
        self.idle_add(self.refresh_xml)

    def delete(self):
        self.interface.undefine()

    def is_bridge(self):
        typ = self.get_type()
        return typ == "bridge"

    def get_type(self):
        return self.xpath("/interface/@type")

    def get_pretty_type(self):
        itype = self.get_type()

        if itype == Interface.Interface.INTERFACE_TYPE_VLAN:
            return "VLAN"
        elif itype:
            return str(itype).capitalize()
        else:
            return "Interface"

    def get_startmode(self):
        return self.xpath("/interface/start/@mode") or "none"

    def set_startmode(self, newmode):
        def set_start_xml(doc, ctx):
            node = ctx.xpathEval("/interface/start[1]")
            node = (node and node[0] or None)
            iface_node = ctx.xpathEval("/interface")[0]

            if not node:
                node = iface_node.newChild(None, "start", None)

            node.setProp("mode", newmode)

            return doc.serialize()

        self._redefine(util.xml_parse_wrapper, set_start_xml)


    def get_slaves(self):
        typ = self.get_type()
        xpath = "/interface/%s/interface/@name" % typ

        def node_func(ctx):
            nodes = ctx.xpathEval(xpath)
            names = map(lambda x: x.content, nodes)
            ret = []

            for name in names:
                type_path = ("/interface/%s/interface[@name='%s']/@type" %
                             (typ, name))
                nodes = ctx.xpathEval(type_path)

                ret.append((name, nodes and nodes[0].content or "Unknown"))

            return ret

        ret = self.xpath(func=node_func)

        if not ret:
            return []
        return ret

    def get_slave_names(self):
        # Returns a list of names of all enslaved interfaces
        slaves = self.get_slaves()
        return map(lambda x: x[0], slaves)

    def get_ipv4(self):
        base_xpath = "/interface/protocol[@family='ipv4']"
        if not self.xpath(base_xpath):
            return []

        dhcp = bool(self.xpath("count(%s/dhcp)" % base_xpath))
        addr = self.xpath(base_xpath + "/ip/@address")
        if addr:
            prefix = self.xpath(base_xpath + "/ip[@address='%s']/@prefix" %
                                addr)
            if prefix:
                addr += "/%s" % prefix

        return [dhcp, addr]

    def get_ipv6(self):
        base_xpath = "/interface/protocol[@family='ipv6']"
        if not self.xpath(base_xpath):
            return []

        dhcp = bool(self.xpath("count(%s/dhcp)" % base_xpath))
        autoconf = bool(self.xpath("count(%s/autoconf)" % base_xpath))

        def addr_func(ctx):
            nodes = ctx.xpathEval(base_xpath + "/ip")
            nodes = nodes or []
            ret = []

            for node in nodes:
                addr = node.prop("address")
                pref = node.prop("prefix")

                if not addr:
                    continue

                if pref:
                    addr += "/%s" % pref
                ret.append(addr)

            return ret

        ret = self.xpath(func=addr_func)

        return [dhcp, autoconf, ret]

    def get_protocol_xml(self):
        def protocol(ctx):
            node = ctx.xpathEval("/interface/protocol")
            node = node and node[0] or None

            ret = None
            if node:
                ret = node.serialize()

            return ret

        ret = self.xpath(func=protocol)
        if ret:
            ret = "  %s\n" % ret
        return ret

    def _redefine(self, xml_func, *args):
        """
        Helper function for altering a redefining VM xml

        @param xml_func: Function to alter the running XML. Takes the
                         original XML as its first argument.
        @param args: Extra arguments to pass to xml_func
        """
        origxml = self._xml_to_redefine()
        # Sanitize origxml to be similar to what we will get back
        origxml = util.xml_parse_wrapper(origxml, lambda d, c: d.serialize())

        newxml = xml_func(origxml, *args)
        self._redefine_xml(newxml)

vmmLibvirtObject.type_register(vmmInterface)

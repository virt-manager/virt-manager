# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest

from virtinst import Interface
from tests import utils

datadir = "tests/interface-xml"


class TestInterfaces(unittest.TestCase):
    def testInterfaceBridgeIP(self):
        conn = utils.URIs.open_testdriver_cached()

        def _check_iface(name, typ, child_names):
            libvirtobj = conn.interfaceLookupByName(name)
            xmlobj = Interface(conn, parsexml=libvirtobj.XMLDesc(0))

            self.assertEqual(xmlobj.name, name)
            self.assertEqual(xmlobj.type, typ)
            self.assertEqual(
                {i.name for i in xmlobj.interfaces},
                set(child_names))

        _check_iface("eth0", "ethernet", [])
        _check_iface("bond0", "bond", ["eth-bond0-1", "eth-bond0-2"])
        _check_iface("brplain", "bridge", ["eth-brplain0", "eth-brplain1"])
        _check_iface("brempty", "bridge", [])
        _check_iface("vlaneth1.3", "vlan", ["vlaneth1"])

# Copyright (C) 2015 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest

from virtinst import URI

import tests


class TestURI(unittest.TestCase):
    """
    Test virtinst URI module
    """
    def _compare(self, uri, scheme='',
                 transport='', port='', username='', path='',
                 hostname='', query='', fragment='',
                 is_ipv6=False, host_is_ipv4_string=False):
        uriinfo = URI(uri)
        self.assertEqual(scheme, uriinfo.scheme)
        self.assertEqual(transport, uriinfo.transport)
        self.assertEqual(port, uriinfo.port)
        self.assertEqual(username, uriinfo.username)
        self.assertEqual(path, uriinfo.path)
        self.assertEqual(hostname, uriinfo.hostname)
        self.assertEqual(query, uriinfo.query)
        self.assertEqual(fragment, uriinfo.fragment)
        self.assertEqual(is_ipv6, uriinfo.is_ipv6)
        self.assertEqual(host_is_ipv4_string, uriinfo.host_is_ipv4_string)

    def testURIs(self):
        self._compare("lxc://", scheme="lxc")
        self._compare("qemu:///session", scheme="qemu", path="/session")
        self._compare("http://foobar.com:5901/my/example.path#my-frag",
            scheme="http", hostname="foobar.com",
            port="5901", path='/my/example.path',
            fragment="my-frag")
        self._compare(
            "gluster+tcp://[1:2:3:4:5:6:7:8]:24007/testvol/dir/a.img",
            scheme="gluster", transport="tcp",
            hostname="1:2:3:4:5:6:7:8", port="24007",
            path="/testvol/dir/a.img", is_ipv6=True)
        self._compare(
            "qemu+ssh://root@192.168.2.3/system?no_verify=1",
            scheme="qemu", transport="ssh", username="root",
            hostname="192.168.2.3", path="/system",
            query="no_verify=1", host_is_ipv4_string=True)
        self._compare(
            "qemu+ssh://foo%5Cbar@hostname/system",
            scheme="qemu", path="/system", transport="ssh",
            hostname="hostname", username="foo\\bar")
        self._compare(
            "qemu+ssh://user%40domain.org@hostname/system",
            scheme="qemu", path="/system", transport="ssh",
            hostname="hostname", username="user@domain.org")

    def test_magicuri_connver(self):
        uri = tests.utils.URIs.test_default + ",connver=1,libver=2"
        conn = tests.utils.URIs.openconn(uri)
        self.assertEqual(conn.conn_version(), 1)
        self.assertEqual(conn.local_libvirt_version(), 2)

        conn = tests.utils.URIs.open_testdefault_cached()
        # Add some support tests with it
        with self.assertRaises(ValueError) as cm:
            conn.support.domain_xml_inactive("foo")
        self.assertTrue("must be of type <class 'libvirt.virDomain'>" in
                str(cm.exception))

        # pylint: disable=protected-access
        from virtinst import support
        def _run(**kwargs):
            check = support._SupportCheck(**kwargs)
            return check(conn)

        self.assertFalse(_run(function="virNope.Foo"))
        self.assertFalse(_run(function="virDomain.IDontExist"))
        self.assertTrue(_run(function="virDomain.isActive"))
        self.assertFalse(_run(function="virConnect.getVersion",
            flag="SOME_FLAG_DOESNT_EXIST"))
        self.assertFalse(_run(version="1000.0.0"))
        self.assertFalse(_run(hv_version={"test": "1000.0.0"}))
        self.assertFalse(_run(hv_libvirt_version={"test": "1000.0.0"}))
        self.assertFalse(_run(hv_libvirt_version={"qemu": "1.2.3"}))
        self.assertTrue(_run(hv_libvirt_version={"qemu": "1.2.3", "all": 0}))

        dom = conn.lookupByName("test")
        self.assertTrue(conn.support.domain_xml_inactive(dom))

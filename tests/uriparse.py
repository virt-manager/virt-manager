# Copyright (C) 2015 Red Hat, Inc.
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

import unittest

from virtinst import URI


class TestURI(unittest.TestCase):
    """
    Test virtinst URI module
    """
    def _compare(self, uri, scheme='',
                 transport='', port='', username='', path='',
                 hostname='', query='', fragment='',
                 is_ipv6=False, host_is_ipv4_string=False):
        uriinfo = URI(uri)
        self.assertEquals(scheme, uriinfo.scheme)
        self.assertEquals(transport, uriinfo.transport)
        self.assertEquals(port, uriinfo.port)
        self.assertEquals(username, uriinfo.username)
        self.assertEquals(path, uriinfo.path)
        self.assertEquals(hostname, uriinfo.hostname)
        self.assertEquals(query, uriinfo.query)
        self.assertEquals(fragment, uriinfo.fragment)
        self.assertEquals(is_ipv6, uriinfo.is_ipv6)
        self.assertEquals(host_is_ipv4_string, uriinfo.host_is_ipv4_string)

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

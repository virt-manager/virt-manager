# Copyright (C) 2015 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import pytest

from virtinst import URI

import tests


############################
# Test virtinst URI module #
############################

def _compare(uri, scheme='',
             transport='', port='', username='', path='',
             hostname='', query='', fragment='',
             is_ipv6=False, host_is_ipv4_string=False):
    uriinfo = URI(uri)
    assert scheme == uriinfo.scheme
    assert transport == uriinfo.transport
    assert port == uriinfo.port
    assert username == uriinfo.username
    assert path == uriinfo.path
    assert hostname == uriinfo.hostname
    assert query == uriinfo.query
    assert fragment == uriinfo.fragment
    assert is_ipv6 == uriinfo.is_ipv6
    assert host_is_ipv4_string == uriinfo.host_is_ipv4_string


def testURIs():
    _compare("lxc://", scheme="lxc")
    _compare("qemu:///session", scheme="qemu", path="/session")
    _compare("http://foobar.com:5901/my/example.path#my-frag",
        scheme="http", hostname="foobar.com",
        port="5901", path='/my/example.path',
        fragment="my-frag")
    _compare(
        "gluster+tcp://[1:2:3:4:5:6:7:8]:24007/testvol/dir/a.img",
        scheme="gluster", transport="tcp",
        hostname="1:2:3:4:5:6:7:8", port="24007",
        path="/testvol/dir/a.img", is_ipv6=True)
    _compare(
        "qemu+ssh://root@192.168.2.3/system?no_verify=1",
        scheme="qemu", transport="ssh", username="root",
        hostname="192.168.2.3", path="/system",
        query="no_verify=1", host_is_ipv4_string=True)
    _compare(
        "qemu+ssh://foo%5Cbar@hostname/system",
        scheme="qemu", path="/system", transport="ssh",
        hostname="hostname", username="foo\\bar")
    _compare(
        "qemu+ssh://user%40domain.org@hostname/system",
        scheme="qemu", path="/system", transport="ssh",
        hostname="hostname", username="user@domain.org")


def test_magicuri_connver():
    uri = tests.utils.URIs.test_default + ",connver=1,libver=2"
    conn = tests.utils.URIs.openconn(uri)
    assert conn.conn_version() == 1
    assert conn.local_libvirt_version() == 2

    conn = tests.utils.URIs.openconn("test:///default")
    # Add some support tests with it
    with pytest.raises(ValueError,
            match=".*type <class 'libvirt.virDomain'>.*"):
        conn.support.domain_xml_inactive("foo")

    # pylint: disable=protected-access
    from virtinst import support
    def _run(**kwargs):
        check = support._SupportCheck(**kwargs)
        return check(conn)

    assert _run(function="virNope.Foo") is False
    assert _run(function="virDomain.IDontExist") is False
    assert _run(function="virDomain.isActive") is True
    assert _run(function="virConnect.getVersion",
        flag="SOME_FLAG_DOESNT_EXIST") is False
    assert _run(version="1000.0.0") is False
    assert _run(hv_version={"test": "1000.0.0"}) is False
    assert _run(hv_libvirt_version={"test": "1000.0.0"}) is False
    assert _run(hv_libvirt_version={"qemu": "1.2.3"}) is False
    assert _run(hv_libvirt_version={"qemu": "1.2.3", "all": 0}) is True

    dom = conn.lookupByName("test")
    assert conn.support.domain_xml_inactive(dom) is True

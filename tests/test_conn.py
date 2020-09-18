# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

import pytest

from virtinst import cli
from virtinst import pollhelpers
from virtinst import StoragePool
from virtinst import URI


############################
# VirtinstConnection tests #
############################

def test_misc():
    # Misc API checks
    conn = cli.getConnection("test:///default")
    conn.invalidate_caps()
    assert conn.is_open() is True
    assert conn.is_container_only() is False
    assert conn.is_openvz() is False
    assert not conn.get_uri_hostname()
    assert not conn.get_uri_port()
    assert not conn.get_uri_username()
    assert not conn.get_uri_transport()
    assert conn.close() == 0

    # Coverage for a daemon_version check
    fakeuri = "__virtinst_test__test:///default,libver=123"
    conn = cli.getConnection(fakeuri)
    assert conn.daemon_version() == 123

    # Hit a special code path that reflects default libvirt transport
    # pylint: disable=protected-access
    conn._uriobj = URI("qemu://example.com/system")
    assert conn.get_uri_transport() == "tls"

    # Hit the qemu:///embed case privileged case check
    fakeuri = "__virtinst_test__test:///default,fakeuri=qemu:///embed"
    conn = cli.getConnection(fakeuri)
    assert conn.is_privileged() == (os.getuid() == 0)

    # Hit fakuuri validation error, for old style opts
    with pytest.raises(RuntimeError):
        cli.getConnection(fakeuri + ",qemu")


def test_default_uri(monkeypatch):
    monkeypatch.setitem(os.environ, "LIBVIRT_DEFAULT_URI", "test:///default")

    # Handle connecting to None conn
    conn = cli.getConnection(None)
    assert conn.getURI() == "test:///default"
    conn.close()


def test_poll():
    # Add coverage for conn fetch_* handling, and pollhelpers
    conn = cli.getConnection("test:///default")
    objmap = {}
    def build_cb(obj, name):
        return obj

    gone, new, master = pollhelpers.fetch_nets(conn, {}, build_cb)
    assert len(gone) == 0
    assert len(new) == 1
    assert len(master) == 1
    assert master[0].name() == "default"

    objmap = dict((obj.name(), obj) for obj in master)
    gone, new, master = pollhelpers.fetch_nets(conn, objmap, build_cb)
    assert len(gone) == 0
    assert len(new) == 0
    assert len(master) == 1
    assert master[0].name() == "default"

    # coverage for some special cases in cache_new_pool
    def makepool(name, create):
        poolxml = StoragePool(conn)
        poolxml.type = "dir"
        poolxml.name = name
        poolxml.target_path = "/tmp/foo/bar/baz/%s" % name
        return poolxml.install(create=create)

    poolobj1 = makepool("conntest1", False)
    conn.fetch_all_pools()
    poolobj2 = makepool("conntest2", True)
    conn.fetch_all_vols()
    poolobj1.undefine()
    poolobj2.destroy()
    poolobj2.undefine()

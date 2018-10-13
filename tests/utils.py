# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import difflib
import os
import sys
import unittest

import libvirt

import virtinst
import virtinst.cli
import virtinst.uri


# pylint: disable=protected-access
# Access to protected member, needed to unittest stuff

class _CLIState(object):
    """
    Class containing any bits passed in from setup.py
    """
    def __init__(self):
        self.regenerate_output = False
        self.use_coverage = False
        self.debug = False
clistate = _CLIState()


def has_old_osinfo():
    # Some tests rely on newer osinfo data. Check for a new condition
    # here, and older tests will be skipped
    osname = "centos7.0"
    if not virtinst.OSDB.lookup_os(osname):
        return True
    return not virtinst.OSDB.lookup_os(osname).supports_chipset_q35()


class _URIs(object):
    def __init__(self):
        self._conn_cache = {}
        self._testdriver_cache = None
        self._testdriver_error = None
        self._testdriver_default = None

        _capspath = "%s/tests/capabilities-xml/" % os.getcwd()
        def _domcaps(path):
            return ",domcaps=" + _capspath + path
        def _caps(path):
            return ",caps=" + _capspath + path

        _testtmpl = "__virtinst_test__test://%s,predictable"
        self.test_default = _testtmpl % "/default"
        self.test_full = _testtmpl % (os.getcwd() + "/tests/testdriver.xml")
        self.test_suite = _testtmpl % (os.getcwd() + "/tests/testsuite.xml")
        self.test_remote = self.test_full + ",remote"

        self.xen = self.test_full + _caps("xen-rhel5.4.xml") + ",xen"
        self.lxc = self.test_full + _caps("lxc.xml") + ",lxc"
        self.vz = self.test_full + _caps("vz.xml") + ",vz"

        _uri_qemu = "%s,qemu" % self.test_full
        _uri_kvm = _uri_qemu + _domcaps("kvm-x86_64-domcaps.xml")
        _uri_kvm_q35 = _uri_qemu + _domcaps("kvm-x86_64-domcaps-q35.xml")
        _uri_kvm_aarch64 = _uri_qemu + _domcaps("kvm-aarch64-domcaps.xml")

        self.kvm = _uri_kvm + _caps("kvm-x86_64.xml")
        self.kvm_remote = _uri_kvm + _caps("kvm-x86_64.xml") + ",remote"
        self.kvm_nodomcaps = _uri_qemu + _caps("kvm-x86_64.xml")
        self.kvm_rhel = _uri_kvm + _caps("kvm-x86_64-rhel7.xml")
        self.kvm_q35 = _uri_kvm_q35 + _caps("kvm-x86_64.xml")
        self.kvm_session = self.kvm + ",session"

        self.kvm_armv7l = _uri_kvm + _caps("kvm-armv7l.xml")
        self.kvm_armv7l_nodomcaps = _uri_qemu + _caps("kvm-armv7l.xml")
        self.kvm_aarch64 = _uri_kvm_aarch64 + _caps("kvm-aarch64.xml")
        self.kvm_ppc64le = _uri_kvm + _caps("kvm-ppc64le.xml")
        self.kvm_s390x = _uri_kvm + _caps("kvm-s390x.xml")
        self.kvm_s390x_KVMIBM = _uri_kvm + _caps("kvm-s390x-KVMIBM.xml")



    def openconn(self, uri):
        """
        Extra super caching to speed up the test suite. We basically
        cache the first guest/pool/vol poll attempt for each URI, and save it
        across multiple reopenings of that connection. We aren't caching
        libvirt objects, just parsed XML objects. This works fine since
        generally every test uses a fresh virConnect, or undoes the
        persistent changes it makes.
        """
        virtinst.util.register_libvirt_error_handler()
        is_testdriver_xml = "/testdriver.xml" in uri

        if not (is_testdriver_xml and self._testdriver_error):
            try:
                conn = virtinst.cli.getConnection(uri)
            except libvirt.libvirtError as e:
                if not is_testdriver_xml:
                    raise
                self._testdriver_error = (
                        "error opening testdriver.xml: %s\n"
                        "libvirt is probably too old" % str(e))
                print(self._testdriver_error, file=sys.stderr)

        if is_testdriver_xml and self._testdriver_error:
            raise unittest.SkipTest(self._testdriver_error)

        uri = conn._open_uri

        # For the basic test:///default URI, skip this caching, so we have
        # an option to test the stock code
        if uri == self.test_default:
            return conn

        if uri not in self._conn_cache:
            conn.fetch_all_domains()
            conn.fetch_all_pools()
            conn.fetch_all_vols()
            conn.fetch_all_nodedevs()

            self._conn_cache[uri] = {}
            for key, value in conn._fetch_cache.items():
                self._conn_cache[uri][key] = value[:]

        # Prime the internal connection cache
        for key, value in self._conn_cache[uri].items():
            conn._fetch_cache[key] = value[:]

        def cb_cache_new_pool(poolobj):
            # Used by clonetest.py nvram-newpool test
            if poolobj.name() == "nvram-newpool":
                from virtinst import StorageVolume
                vol = StorageVolume(conn)
                vol.pool = poolobj
                vol.name = "clone-orig-vars.fd"
                vol.capacity = 1024 * 1024
                vol.install()
            conn._cache_new_pool_raw(poolobj)

        conn.cb_cache_new_pool = cb_cache_new_pool

        return conn

    def open_testdriver_cached(self):
        """
        Open plain testdriver.xml and cache the instance. Tests that
        use this are expected to clean up after themselves so driver
        state doesn't become polluted.
        """
        if not self._testdriver_cache:
            self._testdriver_cache = self.openconn(self.test_full)
        return self._testdriver_cache

    def open_testdefault_cached(self):
        if not self._testdriver_default:
            self._testdriver_default = self.openconn(self.test_default)
        return self._testdriver_default

    def _make_uri(self, base, connver=None, libver=None):
        if connver:
            base += ",connver=%s" % connver
        if libver:
            base += ",libver=%s" % libver
        return base

    def open_kvm(self, connver=None, libver=None):
        return self.openconn(self._make_uri(self.kvm, connver, libver))
    def open_kvm_rhel(self, connver=None):
        return self.openconn(self._make_uri(self.kvm_rhel, connver))
    def open_test_remote(self):
        return self.openconn(self.test_remote)

URIs = _URIs()



def test_create(testconn, xml, define_func="defineXML"):
    xml = virtinst.uri.sanitize_xml_for_test_define(xml)

    try:
        func = getattr(testconn, define_func)
        obj = func(xml)
    except Exception as e:
        raise RuntimeError(str(e) + "\n" + xml)

    try:
        obj.create()
        obj.destroy()
        obj.undefine()
    except Exception:
        try:
            obj.destroy()
        except Exception:
            pass
        try:
            obj.undefine()
        except Exception:
            pass


def diff_compare(actual_out, filename=None, expect_out=None):
    """Compare passed string output to contents of filename"""
    if not expect_out:
        if not os.path.exists(filename) or clistate.regenerate_output:
            open(filename, "w").write(actual_out)
        expect_out = open(filename).read()

    diff = "".join(difflib.unified_diff(expect_out.splitlines(1),
                                        actual_out.splitlines(1),
                                        fromfile=filename or '',
                                        tofile="Generated Output"))
    if diff:
        raise AssertionError("Conversion outputs did not match.\n%s" % diff)

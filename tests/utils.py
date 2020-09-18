# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import sys

import libvirt
import pytest

import virtinst
import virtinst.uri
from virtinst import cli
from virtinst import xmlutil


# pylint: disable=protected-access

class _TestConfig(object):
    """
    Class containing any bits passed in from setup.py
    """
    def __init__(self):
        self.regenerate_output = False
        self.debug = False
        self.skip_checkprops = False

        self.url_only = False
        self.url_iso_only = False
        self.url_skip_libosinfo = False
        self.url_force_libosinfo = False


TESTCONFIG = _TestConfig()
TESTDIR = os.path.abspath(os.path.dirname(__file__))
TOPDIR = os.path.dirname(TESTDIR)
DATADIR = os.path.join(TESTDIR, "data")
UITESTDIR = os.path.join(TESTDIR, "uitests")
UITESTDATADIR = os.path.join(UITESTDIR, "data")


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

        _capspath = DATADIR + "/capabilities/"
        def _domcaps(path):
            return ",domcaps=" + _capspath + path
        def _caps(path):
            return ",caps=" + _capspath + path

        _testtmpl = "__virtinst_test__test://%s,predictable"
        _testdriverdir = DATADIR + "/testdriver/"
        # We don't use actual test:///default, which saves state
        # for the lifetime of the process which can cause weird
        # trickling effects for the testsuite. We use our own
        # test XML which roughly matches test:///default, and then
        # fake the URI
        self.test_default = _testtmpl % (_testdriverdir + "testdefault.xml") + ",fakeuri=test:///default"

        self.test_full = _testtmpl % (_testdriverdir + "testdriver.xml")
        self.test_suite = _testtmpl % (_testdriverdir + "testsuite.xml")
        self.test_defaultpool_collision = _testtmpl % (
            _testdriverdir + "defaultpool-collision.xml")
        self.test_empty = _testtmpl % (_testdriverdir + "empty.xml")

        def _m(fakeuri):
            return self.test_full + ",fakeuri=%s" % fakeuri
        self.test_remote = _m("test+tls://fakeuri.example.com/")

        self.xen = _m("xen:///") + _caps("xen-rhel5.4.xml")
        self.lxc = _m("lxc:///") + _caps("lxc.xml")
        self.vz = _m("vz:///") + _caps("vz.xml")

        _uri_qemu = _m("qemu:///system")
        _kvm_x86_caps = _caps("kvm-x86_64.xml") + _domcaps("kvm-x86_64-domcaps.xml")
        self.kvm = _uri_qemu + _kvm_x86_caps
        self.kvm_cpu_insecure = _uri_qemu + _caps("kvm-x86_64.xml") + _domcaps("kvm-x86_64-insecure-domcaps.xml")
        self.kvm_remote = _m("qemu+tls://fakeuri.example.com/system") + _kvm_x86_caps
        self.kvm_session = _m("qemu:///session") + _kvm_x86_caps

        _uri_kvm = _uri_qemu + _kvm_x86_caps
        _uri_kvm_rhel7 = _uri_qemu + _domcaps("kvm-x86_64-rhel7-domcaps.xml")
        _uri_kvm_q35 = _uri_qemu + _domcaps("kvm-x86_64-domcaps-q35.xml")
        _uri_kvm_amd_sev = _uri_qemu + _domcaps("kvm-x86_64-domcaps-amd-sev.xml")
        _uri_kvm_aarch64 = _uri_qemu + _domcaps("kvm-aarch64-domcaps.xml")
        _uri_qemu_riscv64 = _uri_qemu + _domcaps("qemu-riscv64-domcaps.xml")

        self.kvm_nodomcaps = _uri_qemu + _caps("kvm-x86_64.xml")
        self.kvm_rhel = _uri_kvm_rhel7 + _caps("kvm-x86_64-rhel7.xml")
        self.kvm_q35 = _uri_kvm_q35 + _caps("kvm-x86_64.xml")
        self.kvm_amd_sev = _uri_kvm_amd_sev + _caps("kvm-x86_64.xml")

        self.kvm_armv7l_nodomcaps = _uri_qemu + _caps("kvm-armv7l.xml")
        self.kvm_armv7l = self.kvm_armv7l_nodomcaps + _domcaps("kvm-armv7l-domcaps.xml")
        self.kvm_aarch64 = _uri_kvm_aarch64 + _caps("kvm-aarch64.xml") + _domcaps("kvm-aarch64-domcaps.xml")
        self.kvm_ppc64le = _uri_kvm + _caps("kvm-ppc64le.xml")
        self.kvm_s390x = _uri_kvm + _caps("kvm-s390x.xml")
        self.kvm_s390x_KVMIBM = _uri_kvm + _caps("kvm-s390x-KVMIBM.xml")
        self.qemu_riscv64 = _uri_qemu_riscv64 + _caps("qemu-riscv64.xml")



    def openconn(self, uri):
        """
        Extra super caching to speed up the test suite. We basically
        cache the first guest/pool/vol poll attempt for each URI, and save it
        across multiple reopenings of that connection. We aren't caching
        libvirt objects, just parsed XML objects. This works fine since
        generally every test uses a fresh virConnect, or undoes the
        persistent changes it makes.
        """
        is_testdriver_xml = "/testdriver.xml" in uri

        if not (is_testdriver_xml and self._testdriver_error):
            try:
                conn = cli.getConnection(uri)
            except libvirt.libvirtError as e:
                if not is_testdriver_xml:
                    raise
                self._testdriver_error = (
                        "error opening testdriver.xml: %s\n"
                        "libvirt is probably too old" % str(e))
                print(self._testdriver_error, file=sys.stderr)

        if is_testdriver_xml and self._testdriver_error:
            pytest.skip(self._testdriver_error)

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

    def open_kvm(self):
        return self.openconn(self.kvm)
    def open_test_remote(self):
        return self.openconn(self.test_remote)

URIs = _URIs()



def test_create(testconn, xml, define_func="defineXML"):
    xml = virtinst.uri.sanitize_xml_for_test_define(xml)

    try:
        func = getattr(testconn, define_func)
        obj = func(xml)
    except Exception as e:
        # pylint: disable=raise-missing-from
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
        if not os.path.exists(filename) or TESTCONFIG.regenerate_output:
            open(filename, "w").write(actual_out)
        expect_out = open(filename).read()

    diff = xmlutil.diff(expect_out, actual_out,
            filename or '', "Generated output")
    if diff:
        raise AssertionError("Conversion outputs did not match.\n%s" % diff)


def run_without_testsuite_hacks(cb):
    """
    Decorator for unsetting the test suite env variable
    """
    def wrapper_cb(*args, **kwargs):
        origval = os.environ.pop("VIRTINST_TEST_SUITE", None)
        try:
            return cb(*args, **kwargs)
        finally:
            if origval:
                os.environ["VIRTINST_TEST_SUITE"] = origval
    return wrapper_cb

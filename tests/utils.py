# Copyright (C) 2013 Red Hat, Inc.
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

import difflib
import os
import logging

import libvirt

import virtinst
import virtinst.cli
from virtinst import VirtualAudio
from virtinst import VirtualDisk
from virtinst import VirtualGraphics
from virtinst import VirtualVideoDevice

# Enable this to refresh test output
REGENERATE_OUTPUT = True

# pylint: disable=W0212
# Access to protected member, needed to unittest stuff

_capsprefix  = ",caps=%s/tests/capabilities-xml/" % os.getcwd()
defaulturi = "__virtinst_test__test:///default,predictable"
testuri    = "test:///%s/tests/testdriver.xml" % os.getcwd()
fakeuri = "__virtinst_test__" + testuri + ",predictable"
uriremote = fakeuri + ",remote"
uriqemu = "%s,qemu" % fakeuri
urixen = "%s,xen" % fakeuri
urixencaps = fakeuri + _capsprefix + "rhel5.4-xen-caps-virt-enabled.xml,xen"
urixenia64 = fakeuri + _capsprefix + "xen-ia64-hvm.xml,xen"
urikvm = uriqemu + _capsprefix + "libvirt-1.1.2-qemu-caps.xml"
urilxc = fakeuri + _capsprefix + "capabilities-lxc.xml,lxc"

os.environ["VIRTINST_TEST_SCRATCHDIR"] = os.getcwd()


def get_debug():
    return ("DEBUG_TESTS" in os.environ and
            os.environ["DEBUG_TESTS"] == "1")


def _make_uri(base, connver=None, libver=None):
    if connver:
        base += ",connver=%s" % connver
    if libver:
        base += ",libver=%s" % libver
    return base


_conn_cache = {}


def openconn(uri):
    """
    Extra super caching to speed up the test suite. We basically
    cache the first guest/pool/vol poll attempt for each URI, and save it
    across multiple reopenings of that connection. We aren't caching
    libvirt objects, just parsed XML objects. This works fine since
    generally every test uses a fresh virConnect, or undoes the
    persistent changes it makes.
    """
    conn = virtinst.cli.getConnection(uri)

    if uri not in _conn_cache:
        _conn_cache[uri] = {}
    cache = _conn_cache[uri]

    def cb_fetch_all_guests():
        if "vms" not in cache:
            cache["vms"] = conn._fetch_all_guests_cached()
        return cache["vms"]

    def cb_fetch_all_pools():
        if "pools" not in cache:
            cache["pools"] = conn._fetch_all_pools_cached()
        return cache["pools"]

    def cb_fetch_all_vols():
        if "vols" not in cache:
            cache["vols"] = conn._fetch_all_vols_cached()
        return cache["vols"]

    def cb_clear_cache(pools=False):
        if pools:
            cache.pop("pools", None)

    conn.cb_fetch_all_guests = cb_fetch_all_guests
    conn.cb_fetch_all_pools = cb_fetch_all_pools
    conn.cb_fetch_all_vols = cb_fetch_all_vols
    conn.cb_clear_cache = cb_clear_cache

    return conn


def open_testdefault():
    return openconn("test:///default")


def open_testdriver():
    return openconn(testuri)


def open_testkvmdriver():
    return openconn(urikvm)


def open_plainkvm(connver=None, libver=None):
    return openconn(_make_uri(uriqemu, connver, libver))


def open_plainxen(connver=None, libver=None):
    return openconn(_make_uri(urixen, connver, libver))


def open_test_remote():
    return openconn(uriremote)

_default_conn = open_testdriver()
_conn = None


def set_conn(newconn):
    global _conn
    _conn = newconn


def reset_conn():
    set_conn(_default_conn)


def get_conn():
    return _conn
reset_conn()

# Register libvirt handler


def libvirt_callback(ignore, err):
    logging.warn("libvirt errmsg: %s", err[2])
libvirt.registerErrorHandler(f=libvirt_callback, ctx=None)


def sanitize_xml_for_define(xml):
    # Libvirt throws errors since we are defining domain
    # type='xen', when test driver can only handle type='test'
    # Sanitize the XML so we can define
    if not xml:
        return xml

    xml = xml.replace(">linux<", ">xen<")
    for t in ["xen", "qemu", "kvm"]:
        xml = xml.replace("<domain type=\"%s\">" % t,
                          "<domain type=\"test\">")
        xml = xml.replace("<domain type='%s'>" % t,
                          "<domain type='test'>")
    return xml


def test_create(testconn, xml, define_func="defineXML"):
    xml = sanitize_xml_for_define(xml)

    try:
        func = getattr(testconn, define_func)
        obj = func(xml)
    except Exception, e:
        raise RuntimeError(str(e) + "\n" + xml)

    try:
        obj.create()
        obj.destroy()
        obj.undefine()
    except:
        try:
            obj.destroy()
        except:
            pass
        try:
            obj.undefine()
        except:
            pass


def read_file(filename):
    """Helper function to read a files contents and return them"""
    f = open(filename, "r")
    out = f.read()
    f.close()

    return out


def diff_compare(actual_out, filename=None, expect_out=None):
    """Compare passed string output to contents of filename"""
    if not expect_out:
        if not os.path.exists(filename) or REGENERATE_OUTPUT:
            file(filename, "w").write(actual_out)
        expect_out = read_file(filename)

    diff = "".join(difflib.unified_diff(expect_out.splitlines(1),
                                        actual_out.splitlines(1),
                                        fromfile=filename,
                                        tofile="Generated Output"))
    if diff:
        raise AssertionError("Conversion outputs did not match.\n%s" % diff)


def get_basic_paravirt_guest(installer=None):
    g = virtinst.Guest(_conn)
    g.type = "xen"
    g.name = "TestGuest"
    g.memory = int(200 * 1024)
    g.maxmemory = int(400 * 1024)
    g.uuid = "12345678-1234-1234-1234-123456789012"
    gdev = VirtualGraphics(_conn)
    gdev.type = "vnc"
    gdev.keymap = "ja"
    g.add_device(gdev)
    g.vcpus = 5

    if installer:
        g.installer = installer
    else:
        g.installer._install_kernel = "/boot/vmlinuz"
        g.installer._install_initrd = "/boot/initrd"

    g.add_default_input_device()
    g.add_default_console_device()

    return g


def get_basic_fullyvirt_guest(typ="xen", installer=None):
    g = virtinst.Guest(_conn)
    g.type = typ
    g.name = "TestGuest"
    g.memory = int(200 * 1024)
    g.maxmemory = int(400 * 1024)
    g.uuid = "12345678-1234-1234-1234-123456789012"
    g.installer.location = "/dev/null"
    g.installer.cdrom = True
    gdev = VirtualGraphics(_conn)
    gdev.type = "sdl"
    gdev.display = ":3.4"
    gdev.xauth = "/tmp/.Xauthority"
    g.add_device(gdev)
    g.features.pae = False
    g.vcpus = 5
    if installer:
        g.installer = installer
    g.emulator = "/usr/lib/xen/bin/qemu-dm"
    g.os.arch = "i686"
    g.os.os_type = "hvm"

    g.add_default_input_device()
    g.add_default_console_device()

    return g


def make_import_installer():
    return virtinst.ImportInstaller(_conn)


def make_distro_installer(location="/dev/default-pool/default-vol"):
    inst = virtinst.DistroInstaller(_conn)
    inst.location = location
    return inst


def make_live_installer(location="/dev/null"):
    inst = virtinst.LiveCDInstaller(_conn)
    inst.location = location
    return inst


def make_pxe_installer():
    return virtinst.PXEInstaller(_conn)


def build_win_kvm(path=None, fake=True):
    g = get_basic_fullyvirt_guest("kvm")
    g.os_type = "windows"
    g.os_variant = "winxp"
    g.add_device(get_filedisk(path, fake=fake))
    g.add_device(get_blkdisk())
    g.add_device(get_virtual_network())
    g.add_device(VirtualAudio(g.conn))
    g.add_device(VirtualVideoDevice(g.conn))

    return g


def get_floppy(path=None):
    if not path:
        path = "/dev/default-pool/testvol1.img"
    d = VirtualDisk(_conn)
    d.path = path
    d.device = d.DEVICE_FLOPPY
    d.validate()
    return d


def get_filedisk(path=None, fake=True):
    if not path:
        path = "/tmp/test.img"
    d = VirtualDisk(_conn)
    d.path = path
    size = None
    if not fake:
        size = .000001
    d.set_create_storage(fake=fake, size=size)
    d.validate()
    return d


def get_blkdisk(path="/dev/disk-pool/diskvol1"):
    d = VirtualDisk(_conn)
    d.path = path
    d.validate()
    return d


def get_virtual_network():
    dev = virtinst.VirtualNetworkInterface(_conn)
    dev.macaddr = "22:22:33:44:55:66"
    dev.type = virtinst.VirtualNetworkInterface.TYPE_VIRTUAL
    dev.source = "default"
    return dev

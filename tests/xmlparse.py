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

import unittest
import glob
import traceback

import virtinst

from tests import utils

conn = utils.open_testdriver()
kvmconn = utils.open_testkvmdriver()

def sanitize_file_xml(xml):
    # s/"/'/g from generated XML, matches what libxml dumps out
    # This won't work all the time, but should be good enough for testing
    return xml.replace("'", "\"")

class XMLParseTest(unittest.TestCase):

    def _roundtrip_compare(self, filename):
        expectXML = sanitize_file_xml(file(filename).read())
        guest = virtinst.Guest(conn=conn, parsexml=expectXML)
        actualXML = guest.get_xml_config()
        utils.diff_compare(actualXML, expect_out=expectXML)

    def _alter_compare(self, actualXML, outfile):
        utils.test_create(conn, actualXML)
        utils.diff_compare(actualXML, outfile)

    def testRoundTrip(self):
        """
        Make sure parsing doesn't output different XML
        """
        exclude = ["misc-xml-escaping.xml"]
        failed = False
        error = ""
        for f in glob.glob("tests/xmlconfig-xml/*.xml"):
            if [e for e in exclude if f.endswith(e)]:
                continue

            try:
                self._roundtrip_compare(f)
            except Exception:
                failed = True
                error += "%s:\n%s\n" % (f, "".join(traceback.format_exc()))

        if failed:
            raise AssertionError("Roundtrip parse tests failed:\n%s" % error)

    def _set_and_check(self, obj, param, initval, *args):
        """
        Check expected initial value obj.param == initval, then
        set newval, and make sure it is returned properly
        """
        curval = getattr(obj, param)
        self.assertEquals(initval, curval)

        for newval in args:
            setattr(obj, param, newval)
            curval = getattr(obj, param)
            self.assertEquals(newval, curval)

    def _make_checker(self, obj):
        def check(name, initval, *args):
            return self._set_and_check(obj, name, initval, *args)
        return check

    def testAlterGuest(self):
        """
        Test changing Guest() parameters after parsing
        """
        infile  = "tests/xmlparse-xml/change-guest-in.xml"
        outfile = "tests/xmlparse-xml/change-guest-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        check = self._make_checker(guest)

        check("name", "TestGuest", "change_name")
        check("description", None, "Hey desc changed&")
        check("maxvcpus", 5, 12)
        check("vcpus", 12, 10)
        check("cpuset", "1-3", "1-8,^6", "1-5,15")
        check("maxmemory", 400, 500)
        check("memory", 200, 1000)
        check("maxmemory", 1000, 2000)
        check("uuid", "12345678-1234-1234-1234-123456789012",
                      "11111111-2222-3333-4444-555555555555")
        check("emulator", "/usr/lib/xen/bin/qemu-dm", "/usr/binnnn/fooemu")
        check("hugepage", False, True)

        check = self._make_checker(guest.clock)
        check("offset", "utc", "localtime")

        check = self._make_checker(guest.seclabel)
        check("type", "static", "static")
        check("model", "selinux", "apparmor")
        check("label", "foolabel", "barlabel")
        check("imagelabel", "imagelabel", "fooimage")

        check = self._make_checker(guest.installer)
        check("type", "kvm", "test")
        check("os_type", "hvm", "xen")
        check("arch", "i686", None)
        check("machine", "foobar", "pc-0.11")
        check("loader", None, "/foo/loader")
        check("init", None, "/sbin/init")

        check = self._make_checker(guest.installer.bootconfig)
        check("bootorder", ["hd"], ["fd"])
        check("enable_bootmenu", None, False)
        check("kernel", None)
        check("initrd", None)
        check("kernel_args", None)

        check = self._make_checker(guest.features)
        check("acpi", True, False)
        check("apic", True, False)
        check("pae", False, True)

        def feature_checker(prop, origval, newval):
            self.assertEqual(guest.features[prop], origval)
            guest.features[prop] = newval
            self.assertEqual(guest.features[prop], newval)

        feature_checker("acpi", False, False)
        feature_checker("apic", False, True)
        feature_checker("pae", True, False)

        check = self._make_checker(guest.cpu)
        check("match", "exact", "strict")
        check("model", "footest", "qemu64")
        check("vendor", "Intel", "qemuvendor")
        check("threads", 2, 1)
        check("cores", 5, 3)
        check("sockets", 4, 4)

        check = self._make_checker(guest.cpu.features[0])
        check("name", "x2apic", "foofeat")
        check("policy", "force", "disable")
        guest.cpu.remove_feature(guest.cpu.features[1])
        guest.cpu.add_feature("addfeature")

        check = self._make_checker(guest.numatune)
        check("memory_mode", "interleave", "strict", None)
        check("memory_nodeset", "1-5,^3,7", "2,4,6")

        check = self._make_checker(guest.get_devices("memballoon")[0])
        check("model", "virtio", "none")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterMinimalGuest(self):
        infile  = "tests/xmlparse-xml/change-minimal-guest-in.xml"
        outfile = "tests/xmlparse-xml/change-minimal-guest-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        check = self._make_checker(guest.features)
        check("acpi", False, True)
        check("pae", False)
        self.assertTrue(
            guest.features.get_xml_config().startswith("<features"))

        check = self._make_checker(guest.clock)
        check("offset", None, "utc")
        self.assertTrue(guest.clock.get_xml_config().startswith("<clock"))

        check = self._make_checker(guest.seclabel)
        check("model", None, "default")
        check("type", None, "static")
        check("label", None, "frob")
        self.assertTrue(
            guest.seclabel.get_xml_config().startswith("<seclabel"))

        check = self._make_checker(guest.cpu)
        check("model", None, "foobar")
        check("cores", None, 4)
        guest.cpu.add_feature("x2apic", "forbid")
        guest.cpu.set_topology_defaults(guest.vcpus)
        self.assertTrue(guest.cpu.get_xml_config().startswith("<cpu"))

        self.assertTrue(guest.installer.get_xml_config().startswith("<os"))

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterBootMulti(self):
        infile  = "tests/xmlparse-xml/change-boot-multi-in.xml"
        outfile = "tests/xmlparse-xml/change-boot-multi-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        check = self._make_checker(guest.installer.bootconfig)
        check("bootorder", ['hd', 'fd', 'cdrom', 'network'], ["cdrom"])
        check("enable_bootmenu", False, True)
        check("kernel", None, "foo.img")
        check("initrd", None, "bar.img")
        check("kernel_args", None, "ks=foo.ks")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterBootKernel(self):
        infile  = "tests/xmlparse-xml/change-boot-kernel-in.xml"
        outfile = "tests/xmlparse-xml/change-boot-kernel-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        check = self._make_checker(guest.installer.bootconfig)
        check("bootorder", [], ["network", "hd", "fd"])
        check("enable_bootmenu", None)
        check("kernel", "/boot/vmlinuz", None)

        check("initrd", "/boot/initrd", None)
        check("kernel_args", "location", None)

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterDisk(self):
        """
        Test changing VirtualDisk() parameters after parsing
        """
        infile  = "tests/xmlparse-xml/change-disk-in.xml"
        outfile = "tests/xmlparse-xml/change-disk-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        # XXX: Set size up front. VirtualDisk validation is kind of
        # convoluted. If trying to change a non-existing one and size wasn't
        # already specified, we will error out.
        disk1 = guest.disks[0]
        disk1.size = 1
        disk2 = guest.disks[2]
        disk2.size = 1
        disk3 = guest.disks[5]
        disk3.size = 1

        check = self._make_checker(disk1)
        check("path", "/tmp/test.img", "/dev/loop0")
        check("driver_name", None, "test")
        check("driver_type", None, "raw")
        check("serial", "WD-WMAP9A966149", "frob")

        check = self._make_checker(disk2)
        check("path", "/dev/loop0", None)
        check("device", "cdrom", "floppy")
        check("read_only", True, False)
        check("target", None, "fde")
        check("bus", None, "fdc")
        check("error_policy", "stop", None)

        check = self._make_checker(disk3)
        check("path", None, "/default-pool/default-vol")
        check("shareable", False, True)
        check("driver_cache", None, "writeback")
        check("driver_io", None, "threads")
        check("driver_io", "threads", "native")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testSingleDisk(self):
        xml = ("""<disk type="file" device="disk"><source file="/a.img"/>"""
               """<target dev="hda" bus="ide"/></disk>""")
        d = virtinst.VirtualDisk(parsexml=xml)
        self._set_and_check(d, "target", "hda", "hdb")
        self.assertEquals(xml.replace("hda", "hdb"), d.get_xml_config())

    def testAlterChars(self):
        infile  = "tests/xmlparse-xml/change-chars-in.xml"
        outfile = "tests/xmlparse-xml/change-chars-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        serial1     = guest.get_devices("serial")[0]
        serial2     = guest.get_devices("serial")[1]
        parallel1   = guest.get_devices("parallel")[0]
        parallel2   = guest.get_devices("parallel")[1]
        console1    = guest.get_devices("console")[0]
        console2    = guest.get_devices("console")[1]
        channel1    = guest.get_devices("channel")[0]
        channel2    = guest.get_devices("channel")[1]

        check = self._make_checker(serial1)
        check("char_type", "null")

        check = self._make_checker(serial2)
        check("char_type", "tcp")
        check("protocol", "telnet", "raw")
        check("source_mode", "bind", "connect")

        check = self._make_checker(parallel1)
        check("source_mode", "bind")
        check("source_path", "/tmp/foobar", None)
        check("char_type", "unix", "pty")

        check = self._make_checker(parallel2)
        check("char_type", "udp")
        check("bind_port", "1111", "1357")
        check("bind_host", "my.bind.host", "my.foo.host")
        check("source_mode", "connect")
        check("source_port", "2222", "7777")
        check("source_host", "my.source.host", "source.foo.host")

        check = self._make_checker(console1)
        check("char_type", "pty")
        check("target_type", None)

        check = self._make_checker(console2)
        check("char_type", "file")
        check("source_path", "/tmp/foo.img", None)
        check("source_path", None, "/root/foo")
        check("target_type", "virtio")

        check = self._make_checker(channel1)
        check("char_type", "pty")
        check("target_type", "virtio")
        check("target_name", "foo.bar.frob", "test.changed")

        check = self._make_checker(channel2)
        check("char_type", "unix")
        check("target_type", "guestfwd")
        check("target_address", "1.2.3.4", "5.6.7.8")
        check("target_port", "4567", "1199")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterControllers(self):
        infile  = "tests/xmlparse-xml/change-controllers-in.xml"
        outfile = "tests/xmlparse-xml/change-controllers-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("controller")[0]
        dev2 = guest.get_devices("controller")[1]
        dev3 = guest.get_devices("controller")[2]
        dev4 = guest.get_devices("controller")[3]

        check = self._make_checker(dev1)
        check("type", "ide")
        check("index", "3", "1")

        check = self._make_checker(dev2)
        check("type", "virtio-serial")
        check("index", "0", "7")
        check("ports", "32", "5")
        check("vectors", "17", None)

        check = self._make_checker(dev3)
        check("type", "scsi")
        check("index", "1", "2")

        check = self._make_checker(dev4)
        check("type", "usb")
        check("index", "3", "9")
        check("model", "ich9-uhci3")

        check = self._make_checker(dev4.get_master())
        check("startport", "4", "2")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterNics(self):
        infile  = "tests/xmlparse-xml/change-nics-in.xml"
        outfile = "tests/xmlparse-xml/change-nics-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("interface")[0]
        dev2 = guest.get_devices("interface")[1]
        dev3 = guest.get_devices("interface")[2]
        dev4 = guest.get_devices("interface")[3]
        dev5 = guest.get_devices("interface")[4]

        check = self._make_checker(dev1)
        check("type", "user")
        check("model", None, "testmodel")
        check("bridge", None, "br0")
        check("network", None, "route")
        check("macaddr", "22:11:11:11:11:11", "AA:AA:AA:AA:AA:AA")
        self.assertEquals(dev1.get_source(), None)

        check = self._make_checker(dev2)
        self.assertEquals(dev2.get_source(), "default")
        check("network", "default", None)
        check("bridge", None, "newbr0")
        check("type", "network", "bridge")
        check("model", "e1000", "virtio")

        check = self._make_checker(dev3)
        check("type", "bridge")
        check("bridge", "foobr0", "newfoo0")
        check("network", None, "default")
        check("macaddr", "22:22:22:22:22:22")
        check("target_dev", None, "test1")
        self.assertEquals(dev3.get_source(), "newfoo0")

        check = self._make_checker(dev4)
        check("type", "ethernet")
        check("source_dev", "eth0", "eth1")
        check("target_dev", "nic02", "nic03")
        check("target_dev", "nic03", None)
        self.assertEquals(dev4.get_source(), "eth1")

        check = self._make_checker(dev5)
        check("type", "direct")
        check("source_dev", "eth0.1")
        check("source_mode", "vepa", "bridge")

        virtualport = dev5.virtualport
        check = self._make_checker(virtualport)
        check("type", "802.1Qbg")
        check("managerid", "12", "11")
        check("typeid", "1193046", "1193047")
        check("typeidversion", "1", "2")
        check("instanceid", "09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b",
                            "09b11c53-8b5c-4eeb-8f00-d84eaa0aaa4f")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterInputs(self):
        infile  = "tests/xmlparse-xml/change-inputs-in.xml"
        outfile = "tests/xmlparse-xml/change-inputs-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("input")[0]
        dev2 = guest.get_devices("input")[1]

        check = self._make_checker(dev1)
        check("type", "mouse", "tablet")
        check("bus", "ps2", "usb")

        check = self._make_checker(dev2)
        check("type", "tablet", "mouse")
        check("bus", "usb", "xen")
        check("bus", "xen", "usb")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterGraphics(self):
        infile  = "tests/xmlparse-xml/change-graphics-in.xml"
        outfile = "tests/xmlparse-xml/change-graphics-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("graphics")[0]
        dev2 = guest.get_devices("graphics")[1]
        dev3 = guest.get_devices("graphics")[2]
        dev4 = guest.get_devices("graphics")[3]
        dev5 = guest.get_devices("graphics")[4]

        check = self._make_checker(dev1)
        check("type", "vnc")
        check("passwd", "foobar", "newpass")
        check("port", 100, 6000)
        check("listen", "0.0.0.0", "1.2.3.4")

        check = self._make_checker(dev2)
        check("type", "sdl")
        check("xauth", "/tmp/.Xauthority", "fooauth")
        check("display", "1:2", "6:1")

        check = self._make_checker(dev3)
        check("type", "rdp")

        check = self._make_checker(dev4)
        check("type", "vnc")
        check("port", -1)
        check("socket", "/tmp/foobar", "/var/lib/libvirt/socket/foo")

        check = self._make_checker(dev5)
        check("type", "spice")
        check("passwd", "foobar", "newpass")
        check("port", 100, 6000)
        check("tlsPort", 101, 6001)
        check("listen", "0.0.0.0", "1.2.3.4")
        check("channel_inputs_mode", "insecure", "secure")
        check("channel_main_mode", "secure", "any")
        check("channel_record_mode", "any", "insecure")
        check("passwdValidTo", "2010-04-09T15:51:00", "2011-01-07T19:08:00")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterVideos(self):
        infile  = "tests/xmlparse-xml/change-videos-in.xml"
        outfile = "tests/xmlparse-xml/change-videos-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("video")[0]
        dev2 = guest.get_devices("video")[1]
        dev3 = guest.get_devices("video")[2]

        check = self._make_checker(dev1)
        check("model_type", "vmvga", "vga")
        check("vram", None, "1000")
        check("heads", None, "1")

        check = self._make_checker(dev2)
        check("model_type", "cirrus", "vmvga")
        check("vram", "10240", None)
        check("heads", "3", "5")

        check = self._make_checker(dev3)
        check("model_type", "cirrus", "cirrus")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterHostdevs(self):
        infile  = "tests/xmlparse-xml/change-hostdevs-in.xml"
        outfile = "tests/xmlparse-xml/change-hostdevs-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("hostdev")[0]
        dev2 = guest.get_devices("hostdev")[1]
        dev3 = guest.get_devices("hostdev")[2]

        check = self._make_checker(dev1)
        check("type", "usb")
        check("managed", True, False)
        check("mode", "subsystem", None)
        check("vendor", "0x4321", "0x1111")
        check("product", "0x1234", "0x2222")
        check("bus", None, "1")
        check("device", None, "2")

        check = self._make_checker(dev2)
        check("type", "usb")
        check("managed", False, True)
        check("mode", "capabilities", "subsystem")
        check("bus", "0x12", "0x56")
        check("device", "0x34", "0x78")

        check = self._make_checker(dev3)
        check("type", "pci")
        check("managed", True, True)
        check("mode", "subsystem", "subsystem")
        check("domain", "0x0", "0x4")
        check("bus", "0x1", "0x5")
        check("slot", "0x2", "0x6")
        check("function", "0x3", "0x7")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterWatchdogs(self):
        infile  = "tests/xmlparse-xml/change-watchdogs-in.xml"
        outfile = "tests/xmlparse-xml/change-watchdogs-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("watchdog")[0]
        check = self._make_checker(dev1)
        check("model", "ib700", "i6300esb")
        check("action", "none", "poweroff")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterFilesystems(self):
        devtype = "filesystem"
        infile  = "tests/xmlparse-xml/change-%ss-in.xml" % devtype
        outfile = "tests/xmlparse-xml/change-%ss-out.xml" % devtype
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices(devtype)[0]
        dev2 = guest.get_devices(devtype)[1]
        dev3 = guest.get_devices(devtype)[2]
        dev4 = guest.get_devices(devtype)[3]

        check = self._make_checker(dev1)
        check("type", None, "mount")
        check("mode", None, "passthrough")
        check("driver", "handle", None)
        check("wrpolicy", None, None)
        check("source", "/foo/bar", "/new/path")
        check("target", "/bar/baz", "/new/target")

        check = self._make_checker(dev2)
        check("type", "template")
        check("mode", None, "mapped")
        check("source", "template_fedora", "template_new")
        check("target", "/bar/baz")

        check = self._make_checker(dev3)
        check("type", "mount", None)
        check("mode", "squash", None)
        check("driver", "path", "handle")
        check("wrpolicy", "immediate", None)
        check("readonly", False, True)

        check = self._make_checker(dev4)
        check("type", "mount", None)
        check("mode", "mapped", None)
        check("driver", "path", "handle")
        check("wrpolicy", None, "immediate")
        check("readonly", False, True)

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterSounds(self):
        infile  = "tests/xmlparse-xml/change-sounds-in.xml"
        outfile = "tests/xmlparse-xml/change-sounds-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("sound")[0]
        dev2 = guest.get_devices("sound")[1]
        dev3 = guest.get_devices("sound")[2]

        check = self._make_checker(dev1)
        check("model", "sb16", "ac97")

        check = self._make_checker(dev2)
        check("model", "es1370", "es1370")

        check = self._make_checker(dev3)
        check("model", "ac97", "sb16")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterAddr(self):
        infile  = "tests/xmlparse-xml/change-addr-in.xml"
        outfile = "tests/xmlparse-xml/change-addr-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("disk")[0]
        dev2 = guest.get_devices("controller")[0]
        dev3 = guest.get_devices("channel")[0]

        check = self._make_checker(dev1.address)
        check("type", "drive", "pci")
        check("type", "pci", "drive")
        check("controller", "3", "1")
        check("bus", "5", "4")
        check("unit", "33", "32")
        check = self._make_checker(dev1.alias)
        check("name", "foo2", None)

        check = self._make_checker(dev2.address)
        check("type", "pci")
        check("domain", "0x0000", "0x0001")
        check("bus", "0x00", "4")
        check("slot", "0x04", "10")
        check("function", "0x7", "0x6")
        check = self._make_checker(dev2.alias)
        check("name", None, "frob")

        check = self._make_checker(dev3.address)
        check("type", "virtio-serial")
        check("controller", "0")
        check("bus", "0")
        check("port", "2", "4")
        check = self._make_checker(dev3.alias)
        check("name", "channel0", "channel1")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterSmartCard(self):
        infile  = "tests/xmlparse-xml/change-smartcard-in.xml"
        outfile = "tests/xmlparse-xml/change-smartcard-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("smartcard")[0]
        dev2 = guest.get_devices("smartcard")[1]

        check = self._make_checker(dev1)
        check("type", None, "tcp")

        check = self._make_checker(dev2)
        check("mode", "passthrough", "host")
        check("type", "spicevmc", None)

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterRedirdev(self):
        infile  = "tests/xmlparse-xml/change-redirdev-in.xml"
        outfile = "tests/xmlparse-xml/change-redirdev-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("redirdev")[0]
        dev2 = guest.get_devices("redirdev")[1]

        check = self._make_checker(dev1)
        check("host", "foo", "bar")
        check("service", "12", "42")

        check = self._make_checker(dev2)
        check("type", "spicevmc")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testConsoleCompat(self):
        infile  = "tests/xmlparse-xml/console-compat-in.xml"
        outfile = "tests/xmlparse-xml/console-compat-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("console")[0]
        check = self._make_checker(dev1)
        check("source_path", "/dev/pts/4")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAddRemoveDevices(self):
        infile  = "tests/xmlparse-xml/add-devices-in.xml"
        outfile = "tests/xmlparse-xml/add-devices-out.xml"
        guest = virtinst.Guest(conn=conn,
                               parsexml=file(infile).read())

        rmdev = guest.get_devices("disk")[2]
        guest.remove_device(rmdev)

        adddev = virtinst.VirtualNetworkInterface(conn=conn, type="network",
                                                  network="default",
                                                  macaddr="1A:2A:3A:4A:5A:6A")
        guest.add_device(virtinst.VirtualWatchdog(conn))
        guest.add_device(adddev)

        guest.remove_device(adddev)
        guest.add_device(adddev)

        self._alter_compare(guest.get_xml_config(), outfile)

    def testChangeKVMMedia(self):
        infile  = "tests/xmlparse-xml/change-media-in.xml"
        outfile = "tests/xmlparse-xml/change-media-out.xml"
        guest = virtinst.Guest(conn=kvmconn,
                               parsexml=file(infile).read())

        disk = guest.get_devices("disk")[0]
        check = self._make_checker(disk)
        check("path", None, "/default-pool/default-vol")

        disk = guest.get_devices("disk")[1]
        check = self._make_checker(disk)
        check("path", None, "/default-pool/default-vol")
        check("path", "/default-pool/default-vol", "/disk-pool/diskvol1")

        disk = guest.get_devices("disk")[2]
        check = self._make_checker(disk)
        check("path", None, "/disk-pool/diskvol1")

        disk = guest.get_devices("disk")[3]
        check = self._make_checker(disk)
        check("path", None, "/default-pool/default-vol")

        disk = guest.get_devices("disk")[4]
        check = self._make_checker(disk)
        check("path", None, "/disk-pool/diskvol1")



        self._alter_compare(guest.get_xml_config(), outfile)

if __name__ == "__main__":
    unittest.main()

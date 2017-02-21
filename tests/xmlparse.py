# Copyright (C) 2013, 2014 Red Hat, Inc.
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

import glob
import traceback
import unittest

import virtinst

from tests import utils

conn = utils.open_testdriver()
kvmconn = utils.open_kvm()


def sanitize_file_xml(xml):
    # s/"/'/g from generated XML, matches what libxml dumps out
    # This won't work all the time, but should be good enough for testing
    return xml.replace("'", "\"")


class XMLParseTest(unittest.TestCase):
    def _roundtrip_compare(self, filename):
        expectXML = sanitize_file_xml(file(filename).read())
        guest = virtinst.Guest(conn, parsexml=expectXML)
        actualXML = guest.get_xml_config()
        utils.diff_compare(actualXML, expect_out=expectXML)

    def _alter_compare(self, actualXML, outfile, support_check=None):
        utils.diff_compare(actualXML, outfile)
        if (support_check and not conn.check_support(support_check)):
            return
        utils.test_create(conn, actualXML)

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

    def _get_test_content(self, basename, kvm=False):
        infile = "tests/xmlparse-xml/%s-in.xml" % basename
        outfile = "tests/xmlparse-xml/%s-out.xml" % basename
        guest = virtinst.Guest(kvm and kvmconn or conn,
                               parsexml=file(infile).read())
        return guest, outfile

    def testAlterGuest(self):
        """
        Test changing Guest() parameters after parsing
        """
        guest, outfile = self._get_test_content("change-guest")

        check = self._make_checker(guest)
        check("name", "TestGuest", "change_name")
        check("id", None, 1234)
        check("description", None, "Hey desc changed&")
        check("title", None, "Hey title changed!")
        check("vcpus", 5, 12)
        check("curvcpus", None, 10)
        check("cpuset", "1-3", "1-8,^6", "1-5,15")
        check("maxmemory", 409600, 512000)
        check("memory", 204800, 1024000)
        check("maxmemory", 1024000, 2048000)
        check("uuid", "12345678-1234-1234-1234-123456789012",
                      "11111111-2222-3333-4444-555555555555")
        check("emulator", "/usr/lib/xen/bin/qemu-dm", "/usr/binnnn/fooemu")
        check("type", "kvm", "test")
        check("bootloader", None, "pygrub")
        check("on_poweroff", "destroy", "restart")
        check("on_reboot", "restart", "destroy")
        check("on_crash", "destroy", "restart")
        check("on_lockfailure", "poweroff", "restart")

        check = self._make_checker(guest.clock)
        check("offset", "utc", "localtime")
        guest.clock.remove_timer(guest.clock.timers[0])
        check = self._make_checker(guest.clock.timers[0])
        check("name", "pit", "rtc")
        check("tickpolicy", "delay", "merge")
        timer = guest.clock.add_timer()
        check = self._make_checker(timer)
        check("name", None, "hpet")
        check("present", None, False)

        check = self._make_checker(guest.pm)
        check("suspend_to_mem", False, True)
        check("suspend_to_disk", None, False)

        check = self._make_checker(guest.os)
        check("os_type", "hvm", "xen")
        check("arch", "i686", None)
        check("machine", "foobar", "pc-0.11")
        check("loader", None, "/foo/loader")
        check("init", None, "/sbin/init")
        check("bootorder", ["hd"], ["fd"])
        check("enable_bootmenu", None, False)
        check("useserial", None, True)
        check("kernel", None)
        check("initrd", None)
        check("kernel_args", None)

        guest.os.set_initargs_string("foo 'bar baz' frib")
        self.assertEqual([i.val for i in guest.os.initargs],
            ["foo", "bar baz", "frib"])

        check = self._make_checker(guest.features)
        check("acpi", True, False)
        check("apic", True, True)
        check("eoi", None, True)
        check("pae", False, False)
        check("viridian", False, True)
        check("hap", False, False)
        check("privnet", False, False)
        check("hyperv_relaxed", None, True)
        check("hyperv_vapic", False, None)
        check("hyperv_spinlocks", True, True)
        check("hyperv_spinlocks_retries", 12287, 54321)
        check("vmport", False, True)
        check("kvm_hidden", None, True)
        check("pvspinlock", None, True)
        check("gic_version", None, False)

        check = self._make_checker(guest.cpu)
        check("match", "exact", "strict")
        check("model", "footest", "qemu64")
        check("vendor", "Intel", "qemuvendor")
        check("threads", 2, 1)
        check("cores", 5, 3)
        guest.cpu.sockets = 4.0
        check("sockets", 4)

        check = self._make_checker(guest.cpu.features[0])
        check("name", "x2apic")
        check("policy", "force", "disable")
        rmfeat = guest.cpu.features[3]
        guest.cpu.remove_feature(rmfeat)
        self.assertEquals(rmfeat.get_xml_config(),
                          """<feature name="foo" policy="bar"/>\n""")
        guest.cpu.add_feature("addfeature")

        check = self._make_checker(guest.numatune)
        check("memory_mode", "interleave", "strict", None)
        check("memory_nodeset", "1-5,^3,7", "2,4,6")

        check = self._make_checker(guest.memtune)
        check("hard_limit", None, 1024, 2048)
        check("soft_limit", None, 100, 200)
        check("swap_hard_limit", None, 300, 400)
        check("min_guarantee", None, 400, 500)

        check = self._make_checker(guest.blkiotune)
        check("weight", None, 100, 200)
        check("device_weight", None, 300)
        check("device_path", None, "/home/1.img")

        check = self._make_checker(guest.idmap)
        check("uid_start", None, 0)
        check("uid_target", None, 1000)
        check("uid_count", None, 10)
        check("gid_start", None, 0)
        check("gid_target", None, 1000)
        check("gid_count", None, 10)

        check = self._make_checker(guest.resource)
        check("partition", None, "/virtualmachines/production")

        check = self._make_checker(guest.get_devices("memballoon")[0])
        check("model", "virtio", "none")

        check = self._make_checker(guest.memoryBacking)
        check("hugepages", False, True)
        check("page_size", None, 1)
        check("page_unit", None, "G")
        check("page_nodeset", None, "1,5-8")
        check("nosharepages", False, True)
        check("locked", False, True)

        self._alter_compare(guest.get_xml_config(), outfile,
            support_check=conn.SUPPORT_CONN_VMPORT)

    def testSeclabel(self):
        guest, outfile = self._get_test_content("change-seclabel")

        check = self._make_checker(guest.seclabels[0])
        check("type", "static", "none")
        check("model", "selinux", "apparmor")
        check("label", "foolabel", "barlabel")
        check("imagelabel", "imagelabel", "fooimage")
        check("baselabel", None, "baselabel")
        check("relabel", None, False)

        guest.remove_child(guest.seclabels[1])

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterMinimalGuest(self):
        guest, outfile = self._get_test_content("change-minimal-guest")

        check = self._make_checker(guest.features)
        check("acpi", False, True)
        check("pae", False)
        self.assertTrue(
            guest.features.get_xml_config().startswith("<features"))

        check = self._make_checker(guest.clock)
        check("offset", None, "utc")
        self.assertTrue(guest.clock.get_xml_config().startswith("<clock"))

        seclabel = virtinst.Seclabel(guest.conn)
        guest.add_child(seclabel)
        seclabel.model = "testSecurity"
        seclabel.type = "static"
        seclabel.label = "frob"
        self.assertTrue(
            guest.seclabels[0].get_xml_config().startswith("<seclabel"))

        check = self._make_checker(guest.cpu)
        check("model", None, "foobar")
        check("model_fallback", None, "allow")
        check("cores", None, 4)
        guest.cpu.add_feature("x2apic", "forbid")
        guest.cpu.set_topology_defaults(guest.vcpus)
        self.assertTrue(guest.cpu.get_xml_config().startswith("<cpu"))

        self.assertTrue(guest.os.get_xml_config().startswith("<os"))

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterBootMulti(self):
        guest, outfile = self._get_test_content("change-boot-multi")

        check = self._make_checker(guest.os)
        check("bootorder", ['hd', 'fd', 'cdrom', 'network'], ["cdrom"])
        check("enable_bootmenu", False, True)
        check("kernel", None, "/foo.img")
        check("initrd", None, "/bar.img")
        check("dtb", None, "/baz.dtb")
        check("kernel_args", None, "ks=foo.ks")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterBootKernel(self):
        guest, outfile = self._get_test_content("change-boot-kernel")

        check = self._make_checker(guest.os)
        check("bootorder", [], ["network", "hd", "fd"])
        check("enable_bootmenu", None)
        check("kernel", "/boot/vmlinuz", None)

        check("initrd", "/boot/initrd", None)
        check("kernel_args", "location", None)

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterBootUEFI(self):
        guest, outfile = self._get_test_content("change-boot-uefi")

        check = self._make_checker(guest.os)
        check("bootorder", [], ["network", "hd", "fd"])
        check("loader_ro", None, True)
        check("loader_type", None, "pflash")
        check("nvram", None, "/tmp/nvram_store")
        check("nvram_template", None, "/tmp/template")
        check("loader", None, "OVMF_CODE.fd")

        check("kernel", "/boot/vmlinuz", None)

        check("initrd", "/boot/initrd", None)
        check("kernel_args", "location", None)

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterCpuMode(self):
        guest, outfile = self._get_test_content("change-cpumode")

        check = self._make_checker(guest.cpu)
        check("mode", "host-passthrough", "custom")
        check("mode", "custom", "host-model")
        # mode will be "custom"
        check("model", None, "qemu64")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterDisk(self):
        """
        Test changing VirtualDisk() parameters after parsing
        """
        guest, outfile = self._get_test_content("change-disk")

        def _get_disk(target):
            for disk in guest.get_devices("disk"):
                if disk.target == target:
                    return disk

        disk = _get_disk("hda")
        check = self._make_checker(disk)
        check("path", "/tmp/test.img", "/dev/null")
        disk.sync_path_props()
        check("driver_name", None, "test")
        check("driver_type", None, "raw")
        check("serial", "WD-WMAP9A966149", "frob")
        check("bus", "ide", "usb")
        check("removable", None, False, True)

        disk = guest.get_devices("disk")[1]
        check = self._make_checker(disk.seclabels[1])
        check("model", "dac")
        check("relabel", None, True)
        check("label", None, "foo-my-label")

        disk = _get_disk("hdc")
        check = self._make_checker(disk)
        check("type", "block", "dir", "file", "block")
        check("path", "/dev/null", None)
        disk.sync_path_props()
        check("device", "cdrom", "floppy")
        check("read_only", True, False)
        check("target", "hdc", "fde")
        check("bus", "ide", "fdc")
        check("error_policy", "stop", None)

        disk = _get_disk("hdd")
        check = self._make_checker(disk)
        check("type", "block")
        check("device", "lun")
        check("sgio", None, "unfiltered")

        disk = _get_disk("sda")
        check = self._make_checker(disk)
        check("path", None, "http://[1:2:3:4:5:6:7:8]:1122/my/file")
        disk.sync_path_props()

        disk = _get_disk("fda")
        check = self._make_checker(disk)
        check("path", None, "/dev/default-pool/default-vol")
        disk.sync_path_props()
        check("startup_policy", None, "optional")
        check("shareable", False, True)
        check("driver_cache", None, "writeback")
        check("driver_io", None, "threads")
        check("driver_io", "threads", "native")
        check("driver_discard", None, "unmap")
        check("iotune_ris", 1, 0)
        check("iotune_rbs", 2, 0)
        check("iotune_wis", 3, 0)
        check("iotune_wbs", 4, 0)
        check("iotune_tis", None, 5)
        check("iotune_tbs", None, 6)
        check = self._make_checker(disk.boot)
        check("order", None, 7, None)

        disk = _get_disk("vdb")
        check = self._make_checker(disk)
        check("source_pool", "defaultPool", "anotherPool")
        check("source_volume", "foobar", "newvol")

        disk = _get_disk("vdc")
        check = self._make_checker(disk)
        check("source_protocol", "rbd", "gluster")
        check("source_name", "pool/image", "new-val/vol")
        check("source_host_name", "mon1.example.org", "diff.example.org")
        check("source_host_port", 6321, 1234)
        check("path", "gluster://diff.example.org:1234/new-val/vol")

        disk = _get_disk("vdd")
        check = self._make_checker(disk)
        check("source_protocol", "nbd")
        check("source_host_transport", "unix")
        check("source_host_socket", "/var/run/nbdsock")
        check("path", "nbd+unix:///var/run/nbdsock")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testSingleDisk(self):
        xml = ("""<disk type="file" device="disk"><source file="/a.img"/>\n"""
               """<target dev="hda" bus="ide"/></disk>\n""")
        d = virtinst.VirtualDisk(conn, parsexml=xml)
        self._set_and_check(d, "target", "hda", "hdb")
        self.assertEquals(xml.replace("hda", "hdb"), d.get_xml_config())

    def testAlterChars(self):
        guest, outfile = self._get_test_content("change-chars")

        serial1     = guest.get_devices("serial")[0]
        serial2     = guest.get_devices("serial")[1]
        parallel1   = guest.get_devices("parallel")[0]
        parallel2   = guest.get_devices("parallel")[1]
        console1    = guest.get_devices("console")[0]
        console2    = guest.get_devices("console")[1]
        channel1    = guest.get_devices("channel")[0]
        channel2    = guest.get_devices("channel")[1]
        channel3    = guest.get_devices("channel")[2]

        check = self._make_checker(serial1)
        check("type", "null", "udp")
        check("bind_host", None, "example.com")
        check("bind_port", None, 66)
        check("source_host", None, "example.com.uk")
        check("source_port", None, 77)

        check = self._make_checker(serial2)
        check("type", "tcp")
        check("protocol", "telnet", "raw")
        check("source_mode", "bind", "connect")

        check = self._make_checker(parallel1)
        check("source_mode", "bind")
        check("source_path", "/tmp/foobar", None)
        check("type", "unix", "pty")

        check = self._make_checker(parallel2)
        check("type", "udp")
        check("bind_port", 1111, 1357)
        check("bind_host", "my.bind.host", "my.foo.host")
        check("source_port", 2222, 7777)
        check("source_host", "my.source.host", "source.foo.host")

        check = self._make_checker(console1)
        check("type", "pty")
        check("target_type", None)

        check = self._make_checker(console2)
        check("type", "file")
        check("source_path", "/tmp/foo.img", None)
        check("source_path", None, "/root/foo")
        check("target_type", "virtio")

        check = self._make_checker(channel1)
        check("type", "pty")
        check("target_type", "virtio", "bar", "virtio")
        check("target_name", "foo.bar.frob", "test.changed")

        check = self._make_checker(channel2)
        check("type", "unix", "foo", "unix")
        check("target_type", "guestfwd")
        check("target_address", "1.2.3.4", "5.6.7.8")
        check("target_port", 4567, 1199)

        check = self._make_checker(channel3)
        check("type", "spiceport")
        check("source_channel", "org.spice-space.webdav.0", "test.1")
        check("target_type", "virtio")
        check("target_name", "org.spice-space.webdav.0", "test.2")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterControllers(self):
        guest, outfile = self._get_test_content("change-controllers")

        dev1 = guest.get_devices("controller")[0]
        dev2 = guest.get_devices("controller")[1]
        dev3 = guest.get_devices("controller")[2]
        dev4 = guest.get_devices("controller")[3]

        check = self._make_checker(dev1)
        check("type", "ide")
        check("index", 3, 1)

        check = self._make_checker(dev2)
        check("type", "virtio-serial")
        check("index", 0, 7)
        check("ports", 32, 5)
        check("vectors", 17, None)

        check = self._make_checker(dev3)
        check("type", "scsi")
        check("index", 1, 2)

        check = self._make_checker(dev4)
        check("type", "usb", "foo", "usb")
        check("index", 3, 9)
        check("model", "ich9-ehci1", "ich9-uhci1")
        check("master_startport", 4, 2)

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterNics(self):
        guest, outfile = self._get_test_content("change-nics")

        dev1 = guest.get_devices("interface")[0]
        dev2 = guest.get_devices("interface")[1]
        dev3 = guest.get_devices("interface")[2]
        dev4 = guest.get_devices("interface")[3]
        dev5 = guest.get_devices("interface")[4]

        check = self._make_checker(dev1)
        check("type", "user")
        check("model", None, "testmodel")
        check("source", None, None,)
        check("macaddr", "22:11:11:11:11:11", "AA:AA:AA:AA:AA:AA")
        check("filterref", None, "foo")

        check = self._make_checker(dev2)
        check("source", "default", None)
        check("type", "network", "bridge")
        check("source", None, "newbr0")
        check("model", "e1000", "virtio")

        check = self._make_checker(dev3)
        check("type", "bridge")
        check("source", "foobr0", "newfoo0")
        check("macaddr", "22:22:22:22:22:22")
        check("target_dev", None, "test1")

        check = self._make_checker(dev4)
        check("type", "ethernet")
        check("target_dev", "nic02", "nic03")
        check("target_dev", "nic03", None)

        check = self._make_checker(dev5)
        check("type", "direct")
        check("source", "eth0.1")
        check("source_mode", "vepa", "bridge")
        check("portgroup", None, "sales")
        check("driver_name", None, "vhost")
        check("driver_queues", None, 5)

        virtualport = dev5.virtualport
        check = self._make_checker(virtualport)
        check("type", "802.1Qbg", "foo", "802.1Qbg")
        check("managerid", 12, 11)
        check("typeid", 1193046, 1193047)
        check("typeidversion", 1, 2)
        check("instanceid", "09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b",
                            "09b11c53-8b5c-4eeb-8f00-d84eaa0aaa4f")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterInputs(self):
        guest, outfile = self._get_test_content("change-inputs")

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
        guest, outfile = self._get_test_content("change-graphics")

        dev1 = guest.get_devices("graphics")[0]
        dev2 = guest.get_devices("graphics")[1]
        dev3 = guest.get_devices("graphics")[2]
        dev4 = guest.get_devices("graphics")[3]
        dev5 = guest.get_devices("graphics")[4]
        dev6 = guest.get_devices("graphics")[5]

        check = self._make_checker(dev1)
        check("type", "vnc")
        check("passwd", "foobar", "newpass")
        check("port", 100, 6000)
        check("listen", "0.0.0.0", "1.2.3.4")
        check("keymap", None, "en-us")

        check = self._make_checker(dev2)
        check("type", "vnc")
        check("xauth", "/tmp/.Xauthority", "fooauth")
        check("display", "1:2", "6:1")

        check = self._make_checker(dev3)
        check("type", "rdp", "vnc")
        check("listen", "1.1.2.3", None)

        check = self._make_checker(dev4)
        check("type", "vnc")
        check("port", -1)
        check("socket", "/tmp/foobar", "/var/lib/libvirt/socket/foo")

        check = self._make_checker(dev5)
        check("autoport", True, False)
        check = self._make_checker(dev5.listens[0])
        check("type", "network", "foo", "network")
        check("network", "Bobsnetwork", "mynewnet")

        check = self._make_checker(dev6.listens[0])
        check("type", "address")
        check("address", "0.0.0.0")
        check = self._make_checker(dev6)
        check("type", "spice")
        check("passwd", "foobar", "newpass")
        check("connected", None, "disconnect")
        check("port", 100, 6000)
        check("tlsPort", 101, 6001)
        check("listen", "0.0.0.0", "1.2.3.4")
        check("channel_inputs_mode", "insecure", "secure")
        check("channel_main_mode", "secure", "any")
        check("channel_record_mode", "any", "insecure")
        check("channel_display_mode", "any", "secure")
        check("channel_cursor_mode", "any", "any")
        check("channel_playback_mode", "any", "insecure")
        check("passwdValidTo", "2010-04-09T15:51:00", "2011-01-07T19:08:00")
        check("defaultMode", None, "secure")
        check("image_compression", None, "auto_glz")
        check("streaming_mode", None, "filter")
        check("clipboard_copypaste", None, True)
        check("mouse_mode", None, "client")
        check("filetransfer_enable", None, False)
        check("gl", None, True)
        check("rendernode", None, "/dev/dri/foo")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterVideos(self):
        guest, outfile = self._get_test_content("change-videos")

        dev1 = guest.get_devices("video")[0]
        dev2 = guest.get_devices("video")[1]
        dev3 = guest.get_devices("video")[2]

        check = self._make_checker(dev1)
        check("model", "vmvga", "vga")
        check("vram", None, 1000)
        check("heads", None, 1)

        check = self._make_checker(dev2)
        check("model", "cirrus", "vmvga")
        check("vram", 10240, None)
        check("heads", 3, 5)

        check = self._make_checker(dev3)
        check("model", "cirrus", "cirrus", "qxl")
        check("ram", None, 100)
        check("vgamem", None, 8192)
        check("accel3d", None, True)

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterHostdevs(self):
        infile  = "tests/xmlparse-xml/change-hostdevs-in.xml"
        outfile = "tests/xmlparse-xml/change-hostdevs-out.xml"
        guest = virtinst.Guest(conn,
                               parsexml=file(infile).read())

        dev1 = guest.get_devices("hostdev")[0]
        dev2 = guest.get_devices("hostdev")[1]
        dev3 = guest.get_devices("hostdev")[2]
        dev4 = guest.get_devices("hostdev")[3]

        check = self._make_checker(dev1)
        check("type", "usb", "foo", "usb")
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
        check("driver_name", None, "vfio")
        check("rom_bar", None, True)

        check = self._make_checker(dev4)
        check("type", "scsi")
        check("scsi_adapter", "scsi_host0", "foo")
        check("scsi_bus", 0, 1)
        check("scsi_target", 0, 2)
        check("scsi_unit", 0, 3)
        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterWatchdogs(self):
        guest, outfile = self._get_test_content("change-watchdogs")

        dev1 = guest.get_devices("watchdog")[0]
        check = self._make_checker(dev1)
        check("model", "ib700", "i6300esb")
        check("action", "none", "poweroff")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterFilesystems(self):
        guest, outfile = self._get_test_content("change-filesystems")

        dev1 = guest.get_devices("filesystem")[0]
        dev2 = guest.get_devices("filesystem")[1]
        dev3 = guest.get_devices("filesystem")[2]
        dev4 = guest.get_devices("filesystem")[3]
        dev5 = guest.get_devices("filesystem")[4]
        dev6 = guest.get_devices("filesystem")[5]
        dev7 = guest.get_devices("filesystem")[6]

        check = self._make_checker(dev1)
        check("type", None, "mount")
        check("accessmode", None, "passthrough")
        check("driver", "handle", None)
        check("wrpolicy", None, None)
        check("source", "/foo/bar", "/new/path")
        check("target", "/bar/baz", "/new/target")

        check = self._make_checker(dev2)
        check("type", "template")
        check("accessmode", None, "mapped")
        check("source", "template_fedora", "template_new")
        check("target", "/bar/baz")

        check = self._make_checker(dev3)
        check("type", "mount", None)
        check("accessmode", "squash", None)
        check("driver", "path", "handle")
        check("wrpolicy", "immediate", None)
        check("readonly", False, True)

        check = self._make_checker(dev4)
        check("type", "mount", None)
        check("accessmode", "mapped", None)
        check("driver", "path", "handle")
        check("wrpolicy", None, "immediate")
        check("readonly", False, True)

        check = self._make_checker(dev5)
        check("type", "ram")
        check("source", "1024", 123)
        check("units", "MB", "KiB")

        check = self._make_checker(dev6)
        check("type", "block")
        check("source", "/foo/bar", "/dev/new")
        check("readonly", False, True)

        check = self._make_checker(dev7)
        check("type", "file")
        check("accessmode", "passthrough", None)
        check("driver", "nbd", "loop")
        check("format", "qcow", "raw")
        check("source", "/foo/bar.img", "/foo/bar.raw")
        check("readonly", False, True)

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterSounds(self):
        infile  = "tests/xmlparse-xml/change-sounds-in.xml"
        outfile = "tests/xmlparse-xml/change-sounds-out.xml"
        guest = virtinst.Guest(conn,
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
        guest, outfile = self._get_test_content("change-addr")

        dev1 = guest.get_devices("disk")[0]
        dev2 = guest.get_devices("controller")[0]
        dev3 = guest.get_devices("channel")[0]
        dev4 = guest.get_devices("disk")[1]

        check = self._make_checker(dev1.address)
        check("type", "drive", "pci")
        check("type", "pci", "drive")
        check("controller", 3, 1)
        check("bus", 5, 4)
        check("unit", 33, 32)
        check = self._make_checker(dev1.alias)
        check("name", "foo2", None)

        check = self._make_checker(dev2.address)
        dev2.address.domain = "0x0010"
        self.assertEqual(dev2.address.domain, 16)
        check("type", "pci")
        check("domain", 16, 1)
        check("bus", 0, 4)
        check("slot", 4, 10)
        check("function", 7, 6)
        check = self._make_checker(dev2.alias)
        check("name", None, "frob")

        check = self._make_checker(dev3.address)
        check("type", "virtio-serial")
        check("controller", 0)
        check("bus", 0)
        check("port", 2, 4)
        check = self._make_checker(dev3.alias)
        check("name", "channel0", "channel1")

        dev4.address.clear()

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterSmartCard(self):
        guest, outfile = self._get_test_content("change-smartcard")

        dev1 = guest.get_devices("smartcard")[0]
        dev2 = guest.get_devices("smartcard")[1]

        check = self._make_checker(dev1)
        check("type", None, "tcp")

        check = self._make_checker(dev2)
        check("mode", "passthrough", "host")
        check("type", "spicevmc", None)

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterRedirdev(self):
        guest, outfile = self._get_test_content("change-redirdev")

        dev1 = guest.get_devices("redirdev")[0]
        dev2 = guest.get_devices("redirdev")[1]

        check = self._make_checker(dev1)
        check("bus", "usb", "baz", "usb")
        check("host", "foo", "bar")
        check("service", 12, 42)

        check = self._make_checker(dev2)
        check("type", "tcp", "spicevmc")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterTPM(self):
        guest, outfile = self._get_test_content("change-tpm")

        dev1 = guest.get_devices("tpm")[0]

        check = self._make_checker(dev1)
        check("type", "passthrough", "foo", "passthrough")
        check("model", "tpm-tis", "tpm-tis")
        check("device_path", "/dev/tpm0", "frob")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterRNG_EGD(self):
        guest, outfile = self._get_test_content("change-rng-egd")

        dev1 = guest.get_devices("rng")[0]

        check = self._make_checker(dev1)
        check("type", "egd")
        check("backend_type", "udp", "udp")

        check("connect_host", "1.2.3.4", "1.2.3.5")
        check("connect_service", "1234", "1235")
        check("bind_host", None, None)
        check("bind_service", "1233", "1236")

        check("rate_bytes", "1234", "4321")
        check("rate_period", "2000", "2001")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testAlterRNG_Random(self):
        guest, outfile = self._get_test_content("change-rng-random")

        dev1 = guest.get_devices("rng")[0]

        check = self._make_checker(dev1)
        check("type", "random", "random")
        check("model", "virtio", "virtio")
        check("device", "/dev/random", "/dev/hwrng")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testConsoleCompat(self):
        guest, outfile = self._get_test_content("console-compat")

        dev1 = guest.get_devices("console")[0]
        check = self._make_checker(dev1)
        check("source_path", "/dev/pts/4")
        check("_tty", "/dev/pts/4", "foo", "/dev/pts/4")

        self._alter_compare(guest.get_xml_config(), outfile)

    def testPanicDevice(self):
        guest, outfile = self._get_test_content("change-panic-device")

        dev1 = guest.get_devices("panic")[0]

        check = self._make_checker(dev1)
        check("type", "isa", None, "isa")
        check("iobase", "0x505", None, "0x506")
        self._alter_compare(guest.get_xml_config(), outfile)

    def testAddRemoveDevices(self):
        guest, outfile = self._get_test_content("add-devices")

        rmdev = guest.get_devices("disk")[2]
        guest.remove_device(rmdev)

        adddev = virtinst.VirtualNetworkInterface(conn=conn)
        adddev.type = "network"
        adddev.source = "default"
        adddev.macaddr = "1A:2A:3A:4A:5A:6A"
        adddev.address.set_addrstr("spapr-vio")

        guest.add_device(virtinst.VirtualWatchdog(conn))

        guest.add_device(adddev)
        guest.remove_device(adddev)
        guest.add_device(adddev)

        guest.add_device(virtinst.VirtualAudio(conn,
            parsexml="""<sound model='pcspk'/>"""))

        self._alter_compare(guest.get_xml_config(), outfile)

    def testChangeKVMMedia(self):
        guest, outfile = self._get_test_content("change-media", kvm=True)

        disk = guest.get_devices("disk")[0]
        check = self._make_checker(disk)
        check("path", None, "/dev/default-pool/default-vol")
        disk.sync_path_props()

        disk = guest.get_devices("disk")[1]
        check = self._make_checker(disk)
        check("path", None, "/dev/default-pool/default-vol")
        check("path", "/dev/default-pool/default-vol", "/dev/disk-pool/diskvol1")
        disk.sync_path_props()

        disk = guest.get_devices("disk")[2]
        check = self._make_checker(disk)
        check("path", None, "/dev/disk-pool/diskvol1")
        disk.sync_path_props()

        disk = guest.get_devices("disk")[3]
        check = self._make_checker(disk)
        check("path", None, "/dev/default-pool/default-vol")
        disk.sync_path_props()

        disk = guest.get_devices("disk")[4]
        check = self._make_checker(disk)
        check("path", None, "/dev/disk-pool/diskvol1")
        disk.sync_path_props()

        self._alter_compare(guest.get_xml_config(), outfile)

    def testChangeSnapshot(self):
        basename = "change-snapshot"
        infile = "tests/xmlparse-xml/%s-in.xml" % basename
        outfile = "tests/xmlparse-xml/%s-out.xml" % basename
        snap = virtinst.DomainSnapshot(conn, parsexml=file(infile).read())

        check = self._make_checker(snap)
        check("name", "offline-root-child1", "name-foo")
        check("state", "shutoff", "somestate")
        check("description", "offline desk", "foo\nnewline\n   indent")
        check("parent", "offline-root", "newparent")
        check("creationTime", 1375905916, 1234)
        check("memory_type", "no", "internal")

        check = self._make_checker(snap.disks[0])
        check("name", "hda", "hdb")
        check("snapshot", "internal", "no")

        utils.diff_compare(snap.get_xml_config(), outfile)


    ###################
    # Interface tests #
    ###################

    def testInterfaceBridgeIP(self):
        basename = "test-bridge-ip"
        infile = "tests/interface-xml/%s.xml" % basename
        outfile = "tests/xmlparse-xml/interface-%s-out.xml" % basename
        iface = virtinst.Interface(conn, parsexml=file(infile).read())

        self.assertEquals(len(iface.protocols), 2)
        self.assertEquals(len(iface.interfaces), 3)

        check = self._make_checker(iface)
        check("type", "bridge", "foo", "bridge")
        check("name", "test-bridge-ip", "foo-new")
        check("stp", None, True)
        check("delay", None, 2)

        check = self._make_checker(iface.protocols[0])
        check("family", "ipv4", "foo", "ipv4")
        check("dhcp_peerdns", True, False)
        check("gateway", "1.2.3.4", "5.5.5.5")
        self.assertEquals(iface.protocols[0].ips[1].address, "255.255.255.0")

        check = self._make_checker(iface.protocols[1])
        check("dhcp", True, False)
        check("autoconf", True, False)

        check = self._make_checker(iface.protocols[1].ips[1])
        check("address", "fe80::215:58ff:fe6e:5", "2002::")
        check("prefix", 64, 38)

        # Remove a child interface, verify it's data remains intact
        child_iface = iface.interfaces[1]
        iface.remove_interface(child_iface)

        check = self._make_checker(child_iface)
        check("name", "bond-brbond")
        self.assertEquals(len(child_iface.interfaces), 2)

        utils.diff_compare(iface.get_xml_config(), outfile)
        utils.test_create(conn, iface.get_xml_config(), "interfaceDefineXML")

    def testInterfaceBondArp(self):
        basename = "test-bond-arp"
        infile = "tests/interface-xml/%s.xml" % basename
        outfile = "tests/xmlparse-xml/interface-%s-out.xml" % basename
        iface = virtinst.Interface(conn, parsexml=file(infile).read())

        check = self._make_checker(iface)
        check("start_mode", "onboot", "hotplug")
        check("macaddr", "AA:AA:AA:AA:AA:AA", "AA:AA:AA:11:AA:AA")
        check("mtu", 1501, 1234)

        check("bond_mode", None, "active-backup")
        check("arp_interval", 100, 234)
        check("arp_target", "192.168.100.200", "1.2.3.4")
        check("arp_validate_mode", "backup", "active")

        utils.diff_compare(iface.get_xml_config(), outfile)
        utils.test_create(conn, iface.get_xml_config(), "interfaceDefineXML")

    def testInterfaceBondMii(self):
        basename = "test-bond-mii"
        infile = "tests/interface-xml/%s.xml" % basename
        outfile = "tests/xmlparse-xml/interface-%s-out.xml" % basename
        iface = virtinst.Interface(conn, parsexml=file(infile).read())

        check = self._make_checker(iface)
        check("mii_frequency", 123, 111)
        check("mii_downdelay", 34, 22)
        check("mii_updelay", 12, 33)
        check("mii_carrier_mode", "netif", "ioctl")

        utils.diff_compare(iface.get_xml_config(), outfile)
        utils.test_create(conn, iface.get_xml_config(), "interfaceDefineXML")

    def testInterfaceVLAN(self):
        basename = "test-vlan"
        infile = "tests/interface-xml/%s.xml" % basename
        outfile = "tests/xmlparse-xml/interface-%s-out.xml" % basename
        iface = virtinst.Interface(conn, parsexml=file(infile).read())

        check = self._make_checker(iface)
        check("tag", 123, 456)
        check("parent_interface", "eth2", "foonew")

        utils.diff_compare(iface.get_xml_config(), outfile)
        utils.test_create(conn, iface.get_xml_config(), "interfaceDefineXML")


    #################
    # Storage tests #
    #################

    def testFSPool(self):
        basename = "pool-fs"
        infile = "tests/xmlparse-xml/%s.xml" % basename
        outfile = "tests/xmlparse-xml/%s-out.xml" % basename
        pool = virtinst.StoragePool(conn, parsexml=file(infile).read())

        check = self._make_checker(pool)
        check("type", "fs", "dir")
        check("name", "pool-fs", "foo-new")
        check("uuid", "10211510-2115-1021-1510-211510211510",
                      "10211510-2115-1021-1510-211510211999")
        check("capacity", 984373075968, 200000)
        check("allocation", 756681687040, 150000)
        check("available", 227691388928, 50000)

        check("format", "auto", "ext3")
        check("source_path", "/some/source/path", "/dev/foo/bar")
        check("target_path", "/some/target/path", "/mnt/my/foo")
        check("source_name", None, "fooname")

        utils.diff_compare(pool.get_xml_config(), outfile)
        utils.test_create(conn, pool.get_xml_config(), "storagePoolDefineXML")

    def testISCSIPool(self):
        basename = "pool-iscsi"
        infile = "tests/storage-xml/%s.xml" % basename
        outfile = "tests/xmlparse-xml/%s-out.xml" % basename
        pool = virtinst.StoragePool(conn, parsexml=file(infile).read())

        check = self._make_checker(pool)
        check("iqn", "foo.bar.baz.iqn", "my.iqn")
        check = self._make_checker(pool.hosts[0])
        check("name", "some.random.hostname", "my.host")

        utils.diff_compare(pool.get_xml_config(), outfile)
        utils.test_create(conn, pool.get_xml_config(), "storagePoolDefineXML")

    def testGlusterPool(self):
        if not conn.check_support(conn.SUPPORT_CONN_POOL_GLUSTERFS):
            raise unittest.SkipTest("Gluster pools not supported with this "
                "libvirt version.")

        basename = "pool-gluster"
        infile = "tests/storage-xml/%s.xml" % basename
        outfile = "tests/xmlparse-xml/%s-out.xml" % basename
        pool = virtinst.StoragePool(conn, parsexml=file(infile).read())

        check = self._make_checker(pool)
        check("source_path", "/some/source/path", "/foo")
        check = self._make_checker(pool.hosts[0])
        check("name", "some.random.hostname", "my.host")

        utils.diff_compare(pool.get_xml_config(), outfile)
        utils.test_create(conn, pool.get_xml_config(), "storagePoolDefineXML")

    def testRBDPool(self):
        basename = "pool-rbd"
        infile = "tests/xmlparse-xml/%s.xml" % basename
        outfile = "tests/xmlparse-xml/%s-out.xml" % basename
        pool = virtinst.StoragePool(conn, parsexml=file(infile).read())

        check = self._make_checker(pool.hosts[0])
        check("name", "ceph-mon-1.example.com")
        check("port", 6789, 1234)
        check = self._make_checker(pool.hosts[1])
        check("name", "ceph-mon-2.example.com", "foo.bar")
        check("port", 6789)
        check = self._make_checker(pool.hosts[2])
        check("name", "ceph-mon-3.example.com")
        check("port", 6789, 1000)
        pool.add_host("frobber", "5555")

        utils.diff_compare(pool.get_xml_config(), outfile)
        utils.test_create(conn, pool.get_xml_config(), "storagePoolDefineXML")

    def testVol(self):
        basename = "pool-dir-vol"
        infile = "tests/xmlparse-xml/%s-in.xml" % basename
        outfile = "tests/xmlparse-xml/%s-out.xml" % basename
        vol = virtinst.StorageVolume(conn, parsexml=file(infile).read())

        check = self._make_checker(vol)
        check("type", None, "file")
        check("key", None, "fookey")
        check("capacity", 10737418240, 2000)
        check("allocation", 5368709120, 1000)
        check("format", "raw", "qcow2")
        check("target_path", None, "/foo/bar")
        check("backing_store", "/foo/bar/baz", "/my/backing")
        check("lazy_refcounts", False, True)

        check = self._make_checker(vol.permissions)
        check("mode", "0700", "0744")
        check("owner", "10736", "10000")
        check("group", "10736", "10000")
        check("label", None, "foo.label")

        utils.diff_compare(vol.get_xml_config(), outfile)


    ###################
    # <network> tests #
    ###################

    def testNetMulti(self):
        basename = "network-multi"
        infile = "tests/xmlparse-xml/%s-in.xml" % basename
        outfile = "tests/xmlparse-xml/%s-out.xml" % basename
        net = virtinst.Network(conn, parsexml=file(infile).read())

        check = self._make_checker(net)
        check("name", "ipv6_multirange", "new-foo")
        check("uuid", "41b4afe4-87bb-8087-6724-5e208a2d483a",
                      "41b4afe4-87bb-8087-6724-5e208a2d1111")
        check("bridge", "virbr3", "virbr3new")
        check("stp", True, False)
        check("delay", 0, 2)
        check("domain_name", "net7", "newdom")
        check("ipv6", None, True)
        check("macaddr", None, "52:54:00:69:eb:FF")

        check = self._make_checker(net.forward)
        check("mode", "nat", "route")
        check("dev", None, "eth22")

        check = self._make_checker(net.bandwidth)
        check("inbound_average", "1000", "3000")
        check("inbound_peak", "5000", "4000")
        check("inbound_burst", "5120", "5220")
        check("inbound_floor", None, None)
        check("outbound_average", "1000", "2000")
        check("outbound_peak", "5000", "3000")
        check("outbound_burst", "5120", "5120")

        self.assertEquals(len(net.portgroups), 2)
        check = self._make_checker(net.portgroups[0])
        check("name", "engineering", "foo")
        check("default", True, False)

        self.assertEqual(len(net.ips), 4)
        check = self._make_checker(net.ips[0])
        check("address", "192.168.7.1", "192.168.8.1")
        check("netmask", "255.255.255.0", "255.255.254.0")
        check("tftp", None, "/var/lib/tftproot")
        check("bootp_file", None, "pxeboot.img")
        check("bootp_server", None, "1.2.3.4")

        check = self._make_checker(net.ips[0].ranges[0])
        check("start", "192.168.7.128", "192.168.8.128")
        check("end", "192.168.7.254", "192.168.8.254")

        check = self._make_checker(net.ips[0].hosts[1])
        check("macaddr", "52:54:00:69:eb:91", "52:54:00:69:eb:92")
        check("name", "badbob", "newname")
        check("ip", "192.168.7.3", "192.168.8.3")

        check = self._make_checker(net.ips[1])
        check("family", "ipv6", "ipv6")
        check("prefix", 64, 63)

        r = net.add_route()
        r.family = "ipv4"
        r.address = "192.168.8.0"
        r.prefix = "24"
        r.gateway = "192.168.8.10"
        check = self._make_checker(r)
        check("netmask", None, "foo", None)

        utils.diff_compare(net.get_xml_config(), outfile)
        utils.test_create(conn, net.get_xml_config(), "networkDefineXML")


    ##############
    # Misc tests #
    ##############

    def testCPUUnknownClear(self):
        # Make sure .clear() even removes XML elements we don't know about
        basename = "clear-cpu-unknown-vals"
        infile = "tests/xmlparse-xml/%s-in.xml" % basename
        outfile = "tests/xmlparse-xml/%s-out.xml" % basename
        guest = virtinst.Guest(kvmconn, parsexml=file(infile).read())

        guest.cpu.copy_host_cpu()
        guest.cpu.clear()
        utils.diff_compare(guest.get_xml_config(), outfile)


if __name__ == "__main__":
    unittest.main()

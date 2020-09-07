# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import glob
import traceback
import unittest

import virtinst

from tests import utils


DATADIR = utils.DATADIR + "/xmlparse/"


def sanitize_file_xml(xml):
    # s/"/'/g from generated XML, matches what libxml dumps out
    # This won't work all the time, but should be good enough for testing
    return xml.replace("'", "\"")


class XMLParseTest(unittest.TestCase):
    _kvmconn = None

    @property
    def conn(self):
        return utils.URIs.open_testdefault_cached()

    @property
    def kvmconn(self):
        if not self._kvmconn:
            self._kvmconn = utils.URIs.open_kvm()
        return self._kvmconn

    def _roundtrip_compare(self, filename):
        expectXML = sanitize_file_xml(open(filename).read())
        guest = virtinst.Guest(self.conn, parsexml=expectXML)
        actualXML = guest.get_xml()
        utils.diff_compare(actualXML, expect_out=expectXML)

    def _alter_compare(self, actualXML, outfile):
        utils.diff_compare(actualXML, outfile)
        utils.test_create(self.conn, actualXML)

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
        curval = virtinst.xmlutil.get_prop_path(obj, param)
        self.assertEqual(initval, curval)

        for newval in args:
            virtinst.xmlutil.set_prop_path(obj, param, newval)
            curval = virtinst.xmlutil.get_prop_path(obj, param)
            self.assertEqual(newval, curval)

    def _make_checker(self, obj):
        def check(name, initval, *args):
            return self._set_and_check(obj, name, initval, *args)
        return check

    def _gen_outfile_path(self, basename):
        """
        Returns relative path to the file containing the expected XML
        output

        """
        return DATADIR + "{!s}-out.xml".format(basename)

    def _get_test_content(self, basename, kvm=False):
        infile = DATADIR + "%s-in.xml" % basename
        outfile = self._gen_outfile_path(basename)
        guest = virtinst.Guest(kvm and self.kvmconn or self.conn,
                               parsexml=open(infile).read())
        return guest, outfile

    def testAlterGuest(self):
        """
        Test changing Guest() parameters after parsing
        """
        guest, outfile = self._get_test_content("change-guest")

        check = self._make_checker(guest)

        # Check specific vcpu_current behaviro
        check("vcpus", 5, 10)
        assert guest.vcpu_current is None
        check("vcpu_current", None, 15)
        guest.vcpus = 12
        assert guest.vcpu_current == 12
        guest.vcpu_current = 10

        check("name", "TestGuest", "change_name")
        check("id", None, 1234)
        check("description", None, "Hey desc changed&")
        check("title", None, "Hey title changed!")
        check("vcpu_cpuset", "1-3", "1-8,^6", "1-5,15")
        check("memory", 409600, 512000)
        check("currentMemory", 204800, 1024000)
        check("memory", 1024000, 2048000)
        check("uuid", "12345678-1234-1234-1234-123456789012",
                      "11111111-2222-3333-4444-555555555555")
        check("emulator", "/usr/lib/xen/bin/qemu-dm", "/usr/binnnn/fooemu")
        check("type", "kvm", "test")
        check("bootloader", None, "pygrub")
        check("on_poweroff", "destroy", "restart")
        check("on_reboot", "restart", "destroy")
        check("on_crash", "destroy", "restart")
        check("on_lockfailure", "poweroff", "restart")

        check = self._make_checker(guest._metadata.libosinfo)  # pylint: disable=protected-access
        check("os_id", "http://fedoraproject.org/fedora/17")
        guest.set_os_name("fedora10")
        check("os_id", "http://fedoraproject.org/fedora/10")
        self.assertEqual(guest.osinfo.name, "fedora10")
        guest.set_os_name("generic")
        check("os_id", None, "frib")
        self.assertEqual(guest.osinfo.name, "generic")

        check = self._make_checker(guest.clock)
        check("offset", "utc", "localtime")
        guest.clock.remove_child(guest.clock.timers[0])
        check = self._make_checker(guest.clock.timers[0])
        check("name", "pit", "rtc")
        check("tickpolicy", "delay", "merge")
        timer = guest.clock.timers.add_new()
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
        check("vmcoreinfo", None, True)
        check("kvm_hidden", None, True)
        check("pvspinlock", None, True)
        check("gic_version", None, False)

        check = self._make_checker(guest.cpu)
        check("match", "exact", "strict")
        guest.cpu.set_model(guest, "qemu64")
        check("model", "qemu64")
        check("vendor", "Intel", "qemuvendor")
        check("topology.threads", 2, 1)
        check("topology.cores", 5, 3)
        guest.cpu.topology.sockets = 4.0
        check("topology.sockets", 4)

        check = self._make_checker(guest.cpu.features[0])
        check("name", "x2apic")
        check("policy", "force", "disable")
        rmfeat = guest.cpu.features[3]
        guest.cpu.remove_child(rmfeat)
        self.assertEqual(rmfeat.get_xml(),
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
        check = self._make_checker(guest.blkiotune.devices.add_new())
        check("weight", None, 300)
        check("path", None, "/home/1.img")

        check = self._make_checker(guest.idmap)
        check("uid_start", None, 0)
        check("uid_target", None, 1000)
        check("uid_count", None, 10)
        check("gid_start", None, 0)
        check("gid_target", None, 1000)
        check("gid_count", None, 10)

        check = self._make_checker(guest.resource)
        check("partition", None, "/virtualmachines/production")

        check = self._make_checker(guest.devices.memballoon[0])
        check("model", "virtio", "none")

        check = self._make_checker(guest.memoryBacking)
        check("hugepages", False, True)
        check("nosharepages", False, True)
        check("locked", False, True)

        page = guest.memoryBacking.pages.add_new()
        check = self._make_checker(page)
        check("size", None, 1)
        check("unit", None, "G")

        assert guest.is_full_os_container() is False
        self._alter_compare(guest.get_xml(), outfile)

    def testSeclabel(self):
        guest, outfile = self._get_test_content("change-seclabel")

        check = self._make_checker(guest.seclabels[0])
        check("type", "static", "none")
        check("model", "selinux", "apparmor")
        check("label", "foolabel", "barlabel")
        check("baselabel", None, "baselabel")
        check("relabel", None, False)

        guest.remove_child(guest.seclabels[1])

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterMinimalGuest(self):
        guest, outfile = self._get_test_content("change-minimal-guest")

        check = self._make_checker(guest.features)
        check("acpi", False, True)
        check("pae", False)
        self.assertTrue(
            guest.features.get_xml().startswith("<features"))

        check = self._make_checker(guest.clock)
        check("offset", None, "utc")
        self.assertTrue(guest.clock.get_xml().startswith("<clock"))

        seclabel = virtinst.DomainSeclabel(guest.conn)
        guest.add_child(seclabel)
        seclabel.model = "testSecurity"
        seclabel.type = "static"
        seclabel.label = "frob"
        self.assertTrue(
            guest.seclabels[0].get_xml().startswith("<seclabel"))

        check = self._make_checker(guest.cpu)
        check("model", None)
        guest.cpu.set_model(guest, "foobar")
        check("model", "foobar")
        check("model_fallback", None, "allow")
        check("topology.cores", None, 4)
        guest.cpu.add_feature("x2apic", "forbid")
        guest.cpu.set_topology_defaults(guest.vcpus)
        self.assertTrue(guest.cpu.get_xml().startswith("<cpu"))
        self.assertEqual(guest.cpu.get_xml_id(), "./cpu")
        self.assertEqual(guest.cpu.get_xml_idx(), 0)
        self.assertEqual(guest.get_xml_id(), ".")
        self.assertEqual(guest.get_xml_idx(), 0)

        self.assertTrue(guest.os.get_xml().startswith("<os"))

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterBootMulti(self):
        guest, outfile = self._get_test_content("change-boot-multi")

        check = self._make_checker(guest.os)
        check("bootorder", ['hd', 'fd', 'cdrom', 'network'], ["cdrom"])
        check("enable_bootmenu", False, True)
        check("kernel", None, "/foo.img")
        check("initrd", None, "/bar.img")
        check("dtb", None, "/baz.dtb")
        check("kernel_args", None, "ks=foo.ks")

        guest.os.set_initargs_string("foo bar")
        guest.os.set_initargs_string("baz wibble")

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterBootKernel(self):
        guest, outfile = self._get_test_content("change-boot-kernel")

        check = self._make_checker(guest.os)
        check("bootorder", [], ["network", "hd", "fd"])
        check("enable_bootmenu", None)
        check("kernel", "/boot/vmlinuz", None)

        check("initrd", "/boot/initrd", None)
        check("kernel_args", "location", None)

        self._alter_compare(guest.get_xml(), outfile)

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

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterCpuMode(self):
        xml = open(DATADIR + "change-cpumode-in.xml").read()
        outfile = DATADIR + "change-cpumode-out.xml"
        conn = utils.URIs.openconn(utils.URIs.kvm_q35)
        guest = virtinst.Guest(conn, xml)
        check = self._make_checker(guest.cpu)

        guest.cpu.model = "foo"
        check("mode", "host-passthrough")
        guest.cpu.check_security_features(guest)
        check("secure", False)
        guest.cpu.set_special_mode(guest, "host-model")
        check("mode", "host-model")
        guest.cpu.check_security_features(guest)
        check("secure", False)
        guest.cpu.set_model(guest, "qemu64")
        check("model", "qemu64")
        guest.cpu.check_security_features(guest)
        check("secure", False)

        # Test actually filling in security values, and removing them
        guest.cpu.secure = True
        guest.cpu.set_model(guest, "Skylake-Client-IBRS")
        guest.cpu.check_security_features(guest)
        check("secure", True)
        guest.cpu.set_model(guest, "EPYC-IBPB")
        guest.cpu.check_security_features(guest)
        check("secure", True)
        guest.cpu.secure = False
        guest.cpu.set_model(guest, "Skylake-Client-IBRS")
        guest.cpu.check_security_features(guest)
        check("secure", False)
        self._alter_compare(guest.get_xml(), outfile)

        # Hits a codepath when domcaps don't provide the needed info
        guest = virtinst.Guest(self.conn, xml)
        guest.cpu.check_security_features(guest)
        assert guest.cpu.secure is False

    def testAlterDisk(self):
        """
        Test changing DeviceDisk() parameters after parsing
        """
        guest, outfile = self._get_test_content("change-disk")

        def _get_disk(target):
            for disk in guest.devices.disk:
                if disk.target == target:
                    return disk

        disk = _get_disk("hda")
        check = self._make_checker(disk)
        check("path", "/tmp/test.img", "/dev/foo/null")
        disk.sync_path_props()
        check("driver_name", None, "test")
        check("driver_type", None, "raw")
        check("serial", "WD-WMAP9A966149", "frob")
        check("wwn", None, "123456789abcdefa")
        check("bus", "ide", "usb")
        check("removable", None, False, True)

        disk = guest.devices.disk[1]
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
        check("rawio", None, "yes")

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
        check("driver_detect_zeroes", None, "unmap")
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

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterDevicesBootorder(self):
        basename = "change-devices-bootorder"
        guest, outfile = self._get_test_content(basename)
        disk_1 = guest.devices.disk[0]
        disk_2 = guest.devices.disk[1]
        disk_3 = guest.devices.disk[2]
        disk_4 = guest.devices.disk[3]
        iface_1 = guest.devices.interface[0]
        iface_2 = guest.devices.interface[1]
        redirdev_1 = guest.devices.redirdev[0]

        self.assertEqual(guest.os.bootorder, ['hd'])
        self.assertEqual(disk_1.boot.order, None)
        self.assertEqual(disk_2.boot.order, 10)
        self.assertEqual(disk_3.boot.order, 10)
        self.assertEqual(disk_4.boot.order, 1)
        self.assertEqual(iface_1.boot.order, 2)
        self.assertEqual(iface_2.boot.order, None)
        self.assertEqual(redirdev_1.boot.order, 3)

        guest.reorder_boot_order(disk_1, 1)

        self.assertEqual(guest.os.bootorder, [])
        self.assertEqual(disk_1.boot.order, 1)
        self.assertEqual(disk_2.boot.order, 10)
        self.assertEqual(disk_3.boot.order, 10)
        # verify that the used algorithm preserves the order of
        # records with equal boot indices
        self.assertIs(disk_2, guest.devices.disk[1])
        self.assertIs(disk_3, guest.devices.disk[2])
        self.assertEqual(disk_4.boot.order, 2)
        self.assertEqual(iface_1.boot.order, 3)
        self.assertEqual(iface_2.boot.order, None)
        self.assertEqual(redirdev_1.boot.order, 4)

        try:
            self._alter_compare(guest.get_xml(), outfile)
        except RuntimeError as error:
            self.assertIn("unsupported configuration", str(error))

        guest.reorder_boot_order(disk_2, 10)
        self.assertEqual(disk_2.boot.order, 10)
        self.assertEqual(disk_3.boot.order, 11)
        self.assertIs(disk_2, guest.devices.disk[1])
        self.assertIs(disk_3, guest.devices.disk[2])

        outfile = self._gen_outfile_path("change-devices-bootorder-fixed")
        self._alter_compare(guest.get_xml(), outfile)

    def testSingleDisk(self):
        xml = ("""<disk type="file" device="disk"><source file="/a.img"/>\n"""
               """<target dev="hda" bus="ide"/></disk>\n""")
        d = virtinst.DeviceDisk(self.conn, parsexml=xml)
        self._set_and_check(d, "target", "hda", "hdb")
        self.assertEqual(xml.replace("hda", "hdb"), d.get_xml())

    def testAlterChars(self):
        guest, outfile = self._get_test_content("change-chars")

        serial1     = guest.devices.serial[0]
        serial2     = guest.devices.serial[1]
        parallel1   = guest.devices.parallel[0]
        parallel2   = guest.devices.parallel[1]
        console1    = guest.devices.console[0]
        console2    = guest.devices.console[1]
        channel1    = guest.devices.channel[0]
        channel2    = guest.devices.channel[1]
        channel3    = guest.devices.channel[2]

        check = self._make_checker(serial1)
        check("type", "null", "udp")
        check("source.bind_host", None, "example.com")
        check("source.bind_service", None, 66)
        check("source.connect_host", None, "example.com.uk")
        check("source.connect_service", None, 77)

        check = self._make_checker(serial2)
        check("type", "tcp")
        check("source.protocol", "telnet", "raw")
        check("source.mode", "bind", "connect")

        check = self._make_checker(parallel1)
        check("source.mode", "bind")
        check("source.path", "/tmp/foobar", None)
        check("type", "unix", "pty")

        check = self._make_checker(parallel2)
        check("type", "udp")
        check("source.bind_service", 1111, 1357)
        check("source.bind_host", "my.bind.host", "my.foo.host")
        check("source.connect_service", 2222, 7777)
        check("source.connect_host", "my.source.host", "source.foo.host")

        check = self._make_checker(console1)
        check("type", "pty")
        check("target_type", None)

        check = self._make_checker(console2)
        check("type", "file")
        check("source.path", "/tmp/foo.img", None)
        check("source.path", None, "/root/foo")
        check("target_type", "virtio")
        check("target_state", None, "connected")

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
        check("source.channel", "org.spice-space.webdav.0", "test.1")
        check("target_type", "virtio")
        check("target_name", "org.spice-space.webdav.0", "test.2")
        self.assertEqual(channel3.get_xml_id(), "./devices/channel[3]")
        self.assertEqual(channel3.get_xml_idx(), 2)

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterControllers(self):
        guest, outfile = self._get_test_content("change-controllers")

        dev1 = guest.devices.controller[0]
        dev2 = guest.devices.controller[1]
        dev3 = guest.devices.controller[2]
        dev4 = guest.devices.controller[3]

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

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterNics(self):
        guest, outfile = self._get_test_content("change-nics")

        dev1 = guest.devices.interface[0]
        dev2 = guest.devices.interface[1]
        dev3 = guest.devices.interface[2]
        dev4 = guest.devices.interface[3]
        dev5 = guest.devices.interface[4]

        check = self._make_checker(dev1)
        check("type", "user")
        check("model", None, "vmxnet3")
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

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterInputs(self):
        guest, outfile = self._get_test_content("change-inputs")

        dev1 = guest.devices.input[0]
        dev2 = guest.devices.input[1]

        check = self._make_checker(dev1)
        check("type", "mouse", "tablet")
        check("bus", "ps2", "usb")

        check = self._make_checker(dev2)
        check("type", "tablet", "mouse")
        check("bus", "usb", "xen")
        check("bus", "xen", "usb")

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterGraphics(self):
        guest, outfile = self._get_test_content("change-graphics")

        dev1 = guest.devices.graphics[0]
        dev2 = guest.devices.graphics[1]
        dev3 = guest.devices.graphics[2]
        dev4 = guest.devices.graphics[3]
        dev5 = guest.devices.graphics[4]
        dev6 = guest.devices.graphics[5]

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
        dev5.listens[0].type = "none"
        assert guest.has_listen_none() is True
        check("type", "none", "foo", "network")
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

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterVideos(self):
        guest, outfile = self._get_test_content("change-videos")

        dev1 = guest.devices.video[0]
        dev2 = guest.devices.video[1]
        dev3 = guest.devices.video[2]

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

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterHostdevs(self):
        infile  = DATADIR + "change-hostdevs-in.xml"
        outfile = DATADIR + "change-hostdevs-out.xml"
        guest = virtinst.Guest(self.conn,
                               parsexml=open(infile).read())

        dev1 = guest.devices.hostdev[0]
        dev2 = guest.devices.hostdev[1]
        dev3 = guest.devices.hostdev[2]
        dev4 = guest.devices.hostdev[3]
        dev5 = guest.devices.hostdev[4]
        dev6 = guest.devices.hostdev[5]
        dev7 = guest.devices.hostdev[6]

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

        check = self._make_checker(dev5)
        check("type", "net")
        check("net_interface", "wlan0", "eth0")

        check = self._make_checker(dev6)
        check("type", "misc")
        check("misc_char", "/dev/net/tun", "/dev/null")

        check = self._make_checker(dev7)
        check("type", "storage")
        check("storage_block", "/dev/sdf", "/dev/fd0")
        self._alter_compare(guest.get_xml(), outfile)

    def testAlterWatchdogs(self):
        guest, outfile = self._get_test_content("change-watchdogs")

        dev1 = guest.devices.watchdog[0]
        check = self._make_checker(dev1)
        check("model", "ib700", "i6300esb")
        check("action", "none", "poweroff")

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterFilesystems(self):
        guest, outfile = self._get_test_content("change-filesystems")

        dev1 = guest.devices.filesystem[0]
        dev2 = guest.devices.filesystem[1]
        dev3 = guest.devices.filesystem[2]
        dev4 = guest.devices.filesystem[3]
        dev5 = guest.devices.filesystem[4]
        dev6 = guest.devices.filesystem[5]
        dev7 = guest.devices.filesystem[6]

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
        check("source", "/foo/bar", "/dev/new")
        check("readonly", False, True)
        check("type", "block", "file")

        check = self._make_checker(dev7)
        check("type", "file")
        check("accessmode", "passthrough", None)
        check("driver", "nbd", "loop")
        check("format", "qcow", "raw")
        check("source", "/foo/bar.img", "/foo/bar.raw")
        check("readonly", False, True)

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterSounds(self):
        infile  = DATADIR + "change-sounds-in.xml"
        outfile = DATADIR + "change-sounds-out.xml"
        guest = virtinst.Guest(self.conn,
                               parsexml=open(infile).read())

        dev1 = guest.devices.sound[0]
        dev2 = guest.devices.sound[1]
        dev3 = guest.devices.sound[2]

        check = self._make_checker(dev1)
        check("model", "sb16", "ac97")

        check = self._make_checker(dev2)
        check("model", "es1370", "es1370")

        check = self._make_checker(dev3)
        check("model", "ac97", "sb16")

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterAddr(self):
        guest, outfile = self._get_test_content("change-addr")

        dev1 = guest.devices.disk[0]
        dev2 = guest.devices.controller[0]
        dev3 = guest.devices.channel[0]
        dev4 = guest.devices.disk[1]
        dev5 = guest.devices.memory[0]

        check = self._make_checker(dev1.address)
        check("type", "drive", "pci")
        check("type", "pci", "drive")
        check("controller", 3, 1)
        check("bus", 5, 4)
        check("target", None, 7)
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

        check = self._make_checker(dev5.address)
        check("type", "dimm")
        check("slot", 0, 2)
        check("base", None, "0x1000")
        # Need to remove this since the testdriver doesn't support
        # memory devices?
        guest.remove_device(dev5)

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterSmartCard(self):
        guest, outfile = self._get_test_content("change-smartcard")

        dev1 = guest.devices.smartcard[0]
        dev2 = guest.devices.smartcard[1]
        dev3 = guest.devices.smartcard[2]
        dev4 = guest.devices.smartcard[3]

        check = self._make_checker(dev1)
        check("type", None, "tcp")

        check = self._make_checker(dev2)
        check("mode", "passthrough", "host")
        check("type", "spicevmc", None)

        check = self._make_checker(dev3)
        check("type", "tcp")
        check("source.host", "127.0.0.1")
        check("source.service", 2001)
        check("source.protocol", "raw", "telnet")

        check = self._make_checker(dev4)
        check("type", "unix")
        check("source.path", "/tmp/smartcard.sock")
        check("source.mode", "bind")

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterRedirdev(self):
        guest, outfile = self._get_test_content("change-redirdev")

        dev1 = guest.devices.redirdev[0]
        dev2 = guest.devices.redirdev[1]

        check = self._make_checker(dev1)
        check("bus", "usb", "baz", "usb")
        check("source.host", "foo", "bar")
        check("source.service", 12, 42)

        check = self._make_checker(dev2)
        check("type", "tcp", "spicevmc")

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterTPM(self):
        guest, outfile = self._get_test_content("change-tpm")

        dev1 = guest.devices.tpm[0]

        check = self._make_checker(dev1)
        check("type", "passthrough", "foo", "passthrough")
        check("model", "tpm-tis", "tpm-crb", "tpm-tis")
        check("device_path", "/dev/tpm0", "frob")

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterRNG_EGD(self):
        guest, outfile = self._get_test_content("change-rng-egd")

        dev1 = guest.devices.rng[0]

        check = self._make_checker(dev1)
        check("backend_model", "egd")
        check("backend_type", "udp", "udp")

        check("source.connect_host", "1.2.3.4", "1.2.3.5")
        check("source.connect_service", 1234, 1235)
        check("source.bind_host", None, None)
        check("source.bind_service", 1233, 1236)

        check("rate_bytes", "1234", "4321")
        check("rate_period", "2000", "2001")

        self._alter_compare(guest.get_xml(), outfile)

    def testAlterRNG_Random(self):
        guest, outfile = self._get_test_content("change-rng-random")

        dev1 = guest.devices.rng[0]

        check = self._make_checker(dev1)
        check("backend_model", "random", "random")
        check("model", "virtio", "virtio")
        check("device", "/dev/random", "/dev/hwrng")

        self._alter_compare(guest.get_xml(), outfile)

    def testPanicDevice(self):
        guest, outfile = self._get_test_content("change-panic-device")

        dev1 = guest.devices.panic[0]

        check = self._make_checker(dev1)
        check("address.type", "isa", None, "isa")
        check("address.iobase", "0x505", None, "0x506")
        self._alter_compare(guest.get_xml(), outfile)

    def testQEMUXMLNS(self):
        basename = "change-xmlns-qemu"
        infile = DATADIR + "%s-in.xml" % basename
        outfile = DATADIR + "%s-out.xml" % basename
        guest = virtinst.Guest(self.kvmconn, parsexml=open(infile).read())

        check = self._make_checker(guest.xmlns_qemu.args[0])
        check("value", "-somearg", "-somenewarg")
        check = self._make_checker(guest.xmlns_qemu.args[1])
        check("value", "bar,baz=wib wob", "testval")
        guest.xmlns_qemu.args.add_new().value = "additional-arg"
        arg0 = guest.xmlns_qemu.args[0]
        guest.xmlns_qemu.remove_child(guest.xmlns_qemu.args[0])
        self.assertEqual(arg0.get_xml(),
                "<qemu:arg xmlns:qemu=\"http://libvirt.org/schemas/domain/qemu/1.0\" value=\"-somenewarg\"/>\n")

        check = self._make_checker(guest.xmlns_qemu.envs[0])
        check("name", "SOMEENV")
        check("value", "foo=bar baz,foo")
        env = guest.xmlns_qemu.envs.add_new()
        env.name = "DISPLAY"
        env.value = "1:2"

        self._alter_compare(guest.get_xml(), outfile)

    def testAddRemoveDevices(self):
        guest, outfile = self._get_test_content("add-devices")

        # Basic removal of existing device
        rmdev = guest.devices.disk[2]
        guest.remove_device(rmdev)

        # Basic device add
        d = virtinst.DeviceWatchdog(self.conn)
        d.set_defaults(guest)
        guest.add_device(d)

        # Test adding device with child properties (address value)
        adddev = virtinst.DeviceInterface(self.conn)
        adddev.type = "network"
        adddev.source = "default"
        adddev.macaddr = "1A:2A:3A:4A:5A:6A"
        adddev.address.type = "spapr-vio"
        adddev.set_defaults(guest)

        # Test adding and removing the same device
        guest.add_device(adddev)
        guest.remove_device(adddev)
        guest.add_device(adddev)

        # Test adding device built from parsed XML
        guest.add_device(virtinst.DeviceSound(self.conn,
            parsexml="""<sound model='pcspk'/>"""))

        self._alter_compare(guest.get_xml(), outfile)

    def testChangeKVMMedia(self):
        guest, outfile = self._get_test_content("change-media", kvm=True)

        disk = guest.devices.disk[0]
        check = self._make_checker(disk)
        check("path", None, "/dev/default-pool/default-vol")
        disk.sync_path_props()

        disk = guest.devices.disk[1]
        check = self._make_checker(disk)
        check("path", None, "/dev/default-pool/default-vol")
        check("path", "/dev/default-pool/default-vol", "/dev/disk-pool/diskvol1")
        disk.sync_path_props()

        disk = guest.devices.disk[2]
        check = self._make_checker(disk)
        check("path", None, "/dev/disk-pool/diskvol1")
        disk.sync_path_props()

        disk = guest.devices.disk[3]
        check = self._make_checker(disk)
        check("path", None, "/dev/default-pool/default-vol")
        disk.sync_path_props()

        disk = guest.devices.disk[4]
        check = self._make_checker(disk)
        check("path", None, "/dev/disk-pool/diskvol1")
        disk.sync_path_props()

        self._alter_compare(guest.get_xml(), outfile)

    def testGuestBootorder(self):
        guest, outfile = self._get_test_content("bootorder", kvm=True)

        self.assertEqual(guest.get_boot_order(), ['./devices/disk[1]'])
        self.assertEqual(guest.get_boot_order(legacy=True), ['hd'])

        legacy_order = ['hd', 'fd', 'cdrom', 'network']
        dev_order = ['./devices/disk[1]',
                 './devices/disk[3]',
                 './devices/disk[2]',
                 './devices/interface[1]']
        guest.set_boot_order(legacy_order, legacy=True)
        self.assertEqual(guest.get_boot_order(), dev_order)
        self.assertEqual(guest.get_boot_order(legacy=True), legacy_order)

        guest.set_boot_order(dev_order)
        self.assertEqual(guest.get_boot_order(), dev_order)
        self.assertEqual(guest.get_boot_order(legacy=True), [])

        self._alter_compare(guest.get_xml(), outfile)

    def testDiskChangeBus(self):
        guest, outfile = self._get_test_content("disk-change-bus")

        disk = guest.devices.disk[0]

        # Same bus is a no-op
        origxml = disk.get_xml()
        disk.change_bus(guest, "virtio")
        assert origxml == disk.get_xml()
        disk.change_bus(guest, "ide")

        disk = guest.devices.disk[2]
        disk.change_bus(guest, "scsi")

        self._alter_compare(guest.get_xml(), outfile)


    ##################
    # Snapshot tests #
    ##################

    def testChangeSnapshot(self):
        basename = "change-snapshot"
        infile = DATADIR + "%s-in.xml" % basename
        outfile = DATADIR + "%s-out.xml" % basename
        snap = virtinst.DomainSnapshot(self.conn, parsexml=open(infile).read())

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

        utils.diff_compare(snap.get_xml(), outfile)


    #################
    # Storage tests #
    #################

    def testFSPool(self):
        basename = "pool-fs"
        infile = DATADIR + "%s.xml" % basename
        outfile = DATADIR + "%s-out.xml" % basename
        pool = virtinst.StoragePool(self.conn, parsexml=open(infile).read())

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

        utils.diff_compare(pool.get_xml(), outfile)
        utils.test_create(self.conn, pool.get_xml(), "storagePoolDefineXML")

    def testISCSIPool(self):
        basename = "pool-iscsi"
        infile = utils.DATADIR + "/storage/%s.xml" % basename
        outfile = DATADIR + "%s-out.xml" % basename
        pool = virtinst.StoragePool(self.conn, parsexml=open(infile).read())

        check = self._make_checker(pool)
        check("iqn", "foo.bar.baz.iqn", "my.iqn")
        check = self._make_checker(pool.hosts[0])
        check("name", "some.random.hostname", "my.host")

        utils.diff_compare(pool.get_xml(), outfile)
        utils.test_create(self.conn, pool.get_xml(), "storagePoolDefineXML")

    def testGlusterPool(self):
        basename = "pool-gluster"
        infile = utils.DATADIR + "/storage/%s.xml" % basename
        outfile = DATADIR + "%s-out.xml" % basename
        pool = virtinst.StoragePool(self.conn, parsexml=open(infile).read())

        check = self._make_checker(pool)
        check("source_path", "/some/source/path", "/foo")
        check = self._make_checker(pool.hosts[0])
        check("name", "some.random.hostname", "my.host")

        utils.diff_compare(pool.get_xml(), outfile)
        utils.test_create(self.conn, pool.get_xml(), "storagePoolDefineXML")

    def testRBDPool(self):
        basename = "pool-rbd"
        infile = DATADIR + "%s.xml" % basename
        outfile = DATADIR + "%s-out.xml" % basename
        pool = virtinst.StoragePool(self.conn, parsexml=open(infile).read())

        check = self._make_checker(pool.hosts[0])
        check("name", "ceph-mon-1.example.com")
        check("port", 6789, 1234)
        check = self._make_checker(pool.hosts[1])
        check("name", "ceph-mon-2.example.com", "foo.bar")
        check("port", 6789)
        check = self._make_checker(pool.hosts[2])
        check("name", "ceph-mon-3.example.com")
        check("port", 6789, 1000)
        hostobj = pool.hosts.add_new()
        hostobj.name = "frobber"
        hostobj.port = "5555"

        utils.diff_compare(pool.get_xml(), outfile)
        utils.test_create(self.conn, pool.get_xml(), "storagePoolDefineXML")

    def testVol(self):
        basename = "pool-dir-vol"
        infile = DATADIR + "%s-in.xml" % basename
        outfile = DATADIR + "%s-out.xml" % basename
        vol = virtinst.StorageVolume(self.conn, parsexml=open(infile).read())

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

        utils.diff_compare(vol.get_xml(), outfile)


    ###################
    # <network> tests #
    ###################

    def testNetMulti(self):
        basename = "network-multi"
        infile = DATADIR + "%s-in.xml" % basename
        outfile = DATADIR + "%s-out.xml" % basename
        net = virtinst.Network(self.conn, parsexml=open(infile).read())

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
        check("virtualport_type", None, "openvswitch")

        self.assertEqual(len(net.portgroups), 2)
        check = self._make_checker(net.portgroups[0])
        check("name", "engineering", "foo")
        check("default", True, False)

        self.assertEqual(len(net.ips), 4)
        check = self._make_checker(net.ips[0])
        check("address", "192.168.7.1", "192.168.8.1")
        check("netmask", "255.255.255.0", "255.255.254.0")
        self.assertEqual(net.can_pxe(), False)
        check("tftp", None, "/var/lib/tftproot")
        check("bootp_file", None, "pxeboot.img")
        check("bootp_server", None, "1.2.3.4")
        self.assertEqual(net.can_pxe(), True)

        check = self._make_checker(net.forward)
        check("mode", "nat", "route")
        check("dev", None, "eth22")
        self.assertEqual(net.can_pxe(), True)

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

        r = net.routes.add_new()
        r.family = "ipv4"
        r.address = "192.168.8.0"
        r.prefix = "24"
        r.gateway = "192.168.8.10"
        check = self._make_checker(r)
        check("netmask", None, "foo", None)

        utils.diff_compare(net.get_xml(), outfile)
        utils.test_create(self.conn, net.get_xml(), "networkDefineXML")

    def testNetOpen(self):
        basename = "network-open"
        infile = DATADIR + "%s-in.xml" % basename
        outfile = DATADIR + "%s-out.xml" % basename
        net = virtinst.Network(self.conn, parsexml=open(infile).read())

        check = self._make_checker(net)
        check("name", "open", "new-foo")
        check("domain_name", "open", "newdom")

        check = self._make_checker(net.forward)
        check("mode", "open")
        check("dev", None)

        self.assertEqual(len(net.ips), 1)
        check = self._make_checker(net.ips[0])
        check("address", "192.168.100.1", "192.168.101.1")
        check("netmask", "255.255.255.0", "255.255.254.0")

        check = self._make_checker(net.ips[0].ranges[0])
        check("start", "192.168.100.128", "192.168.101.128")
        check("end", "192.168.100.254", "192.168.101.254")

        utils.diff_compare(net.get_xml(), outfile)
        utils.test_create(self.conn, net.get_xml(), "networkDefineXML")

    def testNetVfPool(self):
        basename = "network-vf-pool"
        infile = DATADIR + "%s-in.xml" % basename
        outfile = DATADIR + "%s-out.xml" % basename
        net = virtinst.Network(self.conn, parsexml=open(infile).read())

        check = self._make_checker(net)
        check("name", "passthrough", "new-foo")

        check = self._make_checker(net.forward)
        check("mode", "hostdev")
        check("managed", "yes")

        check = self._make_checker(net.forward.pf[0])
        check("dev", "eth3")

        utils.diff_compare(net.get_xml(), outfile)
        utils.test_create(self.conn, net.get_xml(), "networkDefineXML")


    ##############
    # Misc tests #
    ##############

    def testCPUUnknownClear(self):
        # Make sure .clear() even removes XML elements we don't know about
        basename = "clear-cpu-unknown-vals"
        infile = DATADIR + "%s-in.xml" % basename
        outfile = DATADIR + "%s-out.xml" % basename
        guest = virtinst.Guest(self.kvmconn, parsexml=open(infile).read())

        guest.cpu.copy_host_cpu(guest)
        guest.cpu.clear()
        utils.diff_compare(guest.get_xml(), outfile)

    def testDomainRoundtrip(self):
        # Make sure our XML engine doesn't mangle non-libvirt XML bits
        infile = DATADIR + "domain-roundtrip.xml"
        outfile = DATADIR + "domain-roundtrip.xml"
        guest = virtinst.Guest(self.conn, parsexml=open(infile).read())

        utils.diff_compare(guest.get_xml(), outfile)

    def testYesNoUnexpectedParse(self):
        # Make sure that if we see an unexpected yes/no or on/off value,
        # we just return it to the user and don't error. Libvirt could
        # change our assumptions and we shouldn't be too restrictive
        xml = ("<hostdev managed='foo'>\n  <rom bar='wibble'/>\n"
            "  <source><address bus='hello'/></source>\n</hostdev>")
        dev = virtinst.DeviceHostdev(self.conn, parsexml=xml)

        self.assertEqual(dev.managed, "foo")
        self.assertEqual(dev.rom_bar, "wibble")
        self.assertEqual(dev.scsi_bus, "hello")

        dev.managed = "test1"
        dev.rom_bar = "test2"
        self.assertEqual(dev.managed, "test1")
        self.assertEqual(dev.rom_bar, "test2")

        with self.assertRaises(ValueError):
            dev.scsi_bus = "goodbye"

    def testXMLCoverage(self):
        with self.assertRaises(RuntimeError) as cm:
            # Ensure we validate root element
            virtinst.DeviceDisk(self.conn, parsexml="<foo/>")
        self.assertTrue("'foo'" in str(cm.exception))

        with self.assertRaises(Exception) as cm:
            # Ensure we validate root element
            virtinst.DeviceDisk(self.conn, parsexml=-1)
        self.assertTrue("xmlParseDoc" in str(cm.exception))

        from virtinst import xmlutil
        with self.assertRaises(xmlutil.DevError):
            raise xmlutil.DevError("for coverage")

        with self.assertRaises(ValueError):
            virtinst.DeviceDisk.validate_generic_name("objtype", None)

        with self.assertRaises(ValueError):
            virtinst.DeviceDisk.validate_generic_name("objtype", "foo bar")

        # Test property __repr__ for code coverage
        assert str(virtinst.DeviceDisk.address)
        assert str(virtinst.DeviceDisk.driver_cache)

    def testReplaceChildParse(self):
        buildfile = DATADIR + "replace-child-build.xml"
        parsefile = DATADIR + "replace-child-parse.xml"

        def mkdisk(target):
            disk = virtinst.DeviceDisk(self.conn)
            disk.device = "cdrom"
            disk.bus = "scsi"
            disk.target = target
            return disk

        guest = virtinst.Guest(self.conn)
        guest.add_device(mkdisk("sda"))
        guest.add_device(mkdisk("sdb"))
        guest.add_device(mkdisk("sdc"))
        guest.add_device(mkdisk("sdd"))
        guest.add_device(mkdisk("sde"))
        guest.add_device(mkdisk("sdf"))
        guest.devices.replace_child(guest.devices.disk[2], mkdisk("sdz"))
        guest.set_defaults(guest)
        utils.diff_compare(guest.get_xml(), buildfile)

        guest = virtinst.Guest(self.conn, parsexml=guest.get_xml())
        newdisk = virtinst.DeviceDisk(self.conn,
                parsexml=mkdisk("sdw").get_xml())
        guest.devices.replace_child(guest.devices.disk[4], newdisk)
        utils.diff_compare(guest.get_xml(), parsefile)

    def testDiskBackend(self):
        # Test that calling validate() on parsed disk XML doesn't attempt
        # to verify the path exists. Assume it's a working config
        xml = ("<disk type='file' device='disk'>"
            "<source file='/A/B/C/D/NOPE'/>"
            "</disk>")
        disk = virtinst.DeviceDisk(self.conn, parsexml=xml)
        disk.validate()
        disk.is_size_conflict()
        disk.build_storage(None)
        self.assertTrue(getattr(disk, "_storage_backend").is_stub())

        # Stub backend coverage testing
        backend = getattr(disk, "_storage_backend")
        assert disk.get_parent_pool() is None
        assert disk.get_vol_object() is None
        assert disk.get_vol_install() is None
        assert disk.get_size() == 0
        assert backend.get_vol_xml() is None
        assert backend.get_dev_type() == "file"
        assert backend.get_driver_type() is None
        assert backend.get_parent_pool() is None

        disk.set_backend_for_existing_path()
        self.assertFalse(getattr(disk, "_storage_backend").is_stub())

        with self.assertRaises(ValueError):
            disk.validate()

        # Ensure set_backend_for_existing_path resolves a path
        # to its existing storage volume
        xml = ("<disk type='file' device='disk'>"
            "<source file='/dev/default-pool/default-vol'/>"
            "</disk>")
        conn = utils.URIs.open_testdriver_cached()
        disk = virtinst.DeviceDisk(conn, parsexml=xml)
        disk.set_backend_for_existing_path()
        assert disk.get_vol_object()

        # Verify set_backend_for_existing_path doesn't error
        # for a variety of disks
        dom = conn.lookupByName("test-many-devices")
        guest = virtinst.Guest(conn, parsexml=dom.XMLDesc(0))
        for disk in guest.devices.disk:
            disk.set_backend_for_existing_path()

    def testGuestXMLDeviceMatch(self):
        """
        Test Guest.find_device and Device.compare_device
        """
        uri = utils.URIs.test_suite
        conn = utils.URIs.openconn(uri)
        dom = conn.lookupByName("test-for-virtxml")
        xml = dom.XMLDesc(0)
        guest = virtinst.Guest(conn, xml)
        guest2 = virtinst.Guest(conn, xml)

        # Assert id matching works
        diskdev = guest.devices.disk[0]
        assert guest.find_device(diskdev) == diskdev

        # Assert type checking correct returns False
        ifacedev = guest.devices.interface[0]
        assert ifacedev.compare_device(diskdev, 0) is False

        # find_device should fail here
        nodev = virtinst.DeviceWatchdog(conn)
        assert guest.find_device(nodev) is None

        # Ensure parsed XML devices match correctly
        for srcdev in guest.devices.get_all():
            devxml = srcdev.get_xml()
            newdev = srcdev.__class__(conn, devxml)
            if srcdev != guest.find_device(newdev):
                raise AssertionError("guest.find_device failed for dev=%s" %
                        newdev)

        # Ensure devices from another parsed XML doc compare correctly
        for srcdev in guest.devices.get_all():
            if not guest2.find_device(srcdev):
                raise AssertionError("guest.find_device failed for dev=%s" %
                        srcdev)

    def testControllerAttachedDevices(self):
        """
        Test DeviceController.get_attached_devices
        """
        xml = open(DATADIR + "controller-attached-devices.xml").read()
        guest = virtinst.Guest(self.conn, xml)

        # virtio-serial path
        controller = [c for c in guest.devices.controller if
                c.type == "virtio-serial"][0]
        devs = controller.get_attached_devices(guest)
        assert len(devs) == 4
        assert devs[-1].DEVICE_TYPE == "console"

        # disk path
        controller = [c for c in guest.devices.controller if
                c.type == "sata"][0]
        devs = controller.get_attached_devices(guest)
        assert len(devs) == 1
        assert devs[-1].device == "cdrom"

        # Little test for DeviceAddress.pretty_desc
        assert devs[-1].address.pretty_desc() == "0:0:0:3"

    def testCPUHostModelOnly(self):
        """
        Hit the validation paths for default HOST_MODEL_ONLY
        """
        guest = virtinst.Guest(self.kvmconn)
        guest.x86_cpu_default = guest.cpu.SPECIAL_MODE_HOST_MODEL_ONLY
        guest.set_defaults(guest)
        assert guest.cpu.model == "Opteron_G4"

        # pylint: disable=protected-access
        guest.cpu.model = "idontexist"
        guest.cpu._validate_default_host_model_only(guest)
        assert guest.cpu.model is None

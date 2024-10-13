# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import pytest

import virtinst

from tests import utils


DATADIR = utils.DATADIR + "/xmlparse/"


####################
# Helper functions #
####################

def _sanitize_file_xml(xml):
    # s/"/'/g from generated XML, matches what libxml dumps out
    # This won't work all the time, but should be good enough for testing
    return xml.replace("'", "\"")


def _alter_compare(conn, actualXML, outfile):
    utils.diff_compare(actualXML, outfile)
    utils.test_create(conn, actualXML)


def _set_and_check(obj, param, initval, *args):
    """
    Check expected initial value obj.param == initval, then
    set newval, and make sure it is returned properly
    """
    curval = virtinst.xmlutil.get_prop_path(obj, param)
    assert initval == curval

    for newval in args:
        virtinst.xmlutil.set_prop_path(obj, param, newval)
        curval = virtinst.xmlutil.get_prop_path(obj, param)
        assert newval == curval


def _make_checker(obj):
    def check(name, initval, *args):
        return _set_and_check(obj, name, initval, *args)
    return check


def _gen_outfile_path(basename):
    """
    Returns relative path to the file containing the expected XML
    output

    """
    return DATADIR + "{!s}-out.xml".format(basename)


def _get_test_content(conn, basename):
    infile = DATADIR + "%s-in.xml" % basename
    outfile = _gen_outfile_path(basename)
    guest = virtinst.Guest(conn, parsexml=open(infile).read())
    return guest, outfile


##############
# Test cases #
##############

def testAlterGuest():
    """
    Test changing Guest() parameters after parsing
    """
    conn = utils.URIs.open_testdefault_cached()
    guest, outfile = _get_test_content(conn, "change-guest")

    check = _make_checker(guest)

    # Check specific vcpu_current behavior
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

    check = _make_checker(guest._metadata.libosinfo)  # pylint: disable=protected-access
    check("os_id", "http://fedoraproject.org/fedora/17")
    guest.set_os_name("fedora10")
    check("os_id", "http://fedoraproject.org/fedora/10")
    assert guest.osinfo.name == "fedora10"
    guest.set_os_name("generic")
    check("os_id", None, "frib")
    assert guest.osinfo.name == "generic"

    check = _make_checker(guest.clock)
    check("offset", "utc", "localtime")
    guest.clock.remove_child(guest.clock.timers[0])
    check = _make_checker(guest.clock.timers[0])
    check("name", "pit", "rtc")
    check("tickpolicy", "delay", "merge")
    timer = guest.clock.timers.add_new()
    check = _make_checker(timer)
    check("name", None, "hpet")
    check("present", None, False)

    check = _make_checker(guest.pm)
    check("suspend_to_mem", False, True)
    check("suspend_to_disk", None, False)

    check = _make_checker(guest.os)
    check("os_type", "hvm", "xen")
    check("arch", "i686", None)
    check("machine", "foobar", "pc-0.11")
    check("loader", None, "/foo/loader")
    check("init", None, "/sbin/init")
    check("bootorder", ["hd"], ["fd"])
    check("bootmenu_enable", None, False)
    check("bootmenu_timeout", None, 30000)
    check("bios_useserial", None, True)
    check("bios_rebootTimeout", None, -1)
    check("kernel", None)
    check("initrd", None)
    check("kernel_args", None)

    guest.os.set_initargs_string("foo 'bar baz' frib")
    assert [i.val for i in guest.os.initargs] == ["foo", "bar baz", "frib"]

    check = _make_checker(guest.features)
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
    check("ioapic_driver", None, "qemu")
    check("kvm_pv_ipi", None, False)

    check = _make_checker(guest.cpu)
    check("match", "exact", "strict")
    guest.cpu.set_model(guest, "qemu64")
    check("model", "qemu64")
    check("vendor", "Intel", "qemuvendor")
    check("topology.threads", 2, 1)
    check("topology.cores", 5, 3)
    guest.cpu.topology.sockets = 4.0
    check("topology.sockets", 4)

    check = _make_checker(guest.cpu.features[0])
    check("name", "x2apic")
    check("policy", "force", "disable")
    rmfeat = guest.cpu.features[3]
    guest.cpu.remove_child(rmfeat)
    assert rmfeat.get_xml() == """<feature name="foo" policy="bar"/>\n"""
    guest.cpu.add_feature("addfeature")

    check = _make_checker(guest.numatune)
    check("memory_mode", "interleave", "strict", None)
    check("memory_nodeset", "1-5,^3,7", "2,4,6")

    check = _make_checker(guest.memtune)
    check("hard_limit", None, 1024, 2048)
    check("soft_limit", None, 100, 200)
    check("swap_hard_limit", None, 300, 400)
    check("min_guarantee", None, 400, 500)

    check = _make_checker(guest.blkiotune)
    check("weight", None, 100, 200)
    check = _make_checker(guest.blkiotune.devices.add_new())
    check("weight", None, 300)
    check("path", None, "/home/1.img")

    check = _make_checker(guest.idmap)
    check("uid_start", None, 0)
    check("uid_target", None, 1000)
    check("uid_count", None, 10)
    check("gid_start", None, 0)
    check("gid_target", None, 1000)
    check("gid_count", None, 10)

    check = _make_checker(guest.resource)
    check("partition", None, "/virtualmachines/production")

    check = _make_checker(guest.devices.memballoon[0])
    check("model", "virtio", "none")

    check = _make_checker(guest.memoryBacking)
    check("hugepages", False, True)
    check("nosharepages", False, True)
    check("locked", False, True)

    page = guest.memoryBacking.pages.add_new()
    check = _make_checker(page)
    check("size", None, 1)
    check("unit", None, "G")

    assert guest.is_full_os_container() is False
    _alter_compare(conn, guest.get_xml(), outfile)


def testAlterCpuMode():
    conn = utils.URIs.open_testdefault_cached()
    xml = open(DATADIR + "change-cpumode-in.xml").read()
    outfile = DATADIR + "change-cpumode-out.xml"
    conn = utils.URIs.openconn(utils.URIs.kvm_x86)
    guest = virtinst.Guest(conn, xml)
    check = _make_checker(guest.cpu)

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
    _alter_compare(conn, guest.get_xml(), outfile)

    # Hits a codepath when domcaps don't provide the needed info
    emptyconn = utils.URIs.open_testdefault_cached()
    guest = virtinst.Guest(emptyconn, xml)
    guest.cpu.check_security_features(guest)
    assert guest.cpu.secure is False


def testAlterDisk():
    """
    Test changing DeviceDisk() parameters after parsing
    """
    conn = utils.URIs.open_testdefault_cached()
    guest, outfile = _get_test_content(conn, "change-disk")

    def _get_disk(target):
        for disk in guest.devices.disk:
            if disk.target == target:
                return disk

    disk = _get_disk("hda")
    check = _make_checker(disk)
    assert disk.get_source_path() == "/tmp/test.img"
    disk.set_source_path("/dev/foo/null")
    disk.sync_path_props()
    check("driver_name", None, "test")
    check("driver_type", None, "raw")
    check("serial", "WD-WMAP9A966149", "frob")
    check("wwn", None, "123456789abcdefa")
    check("bus", "ide", "usb")
    check("removable", None, False, True)

    disk = guest.devices.disk[1]
    check = _make_checker(disk.seclabels[1])
    check("model", "dac")
    check("relabel", None, True)
    check("label", None, "foo-my-label")

    disk = _get_disk("hdc")
    check = _make_checker(disk)
    check("type", "block", "dir", "file", "block")
    assert disk.get_source_path() == "/dev/null"
    disk.set_source_path(None)
    disk.sync_path_props()
    check("device", "cdrom", "floppy")
    check("read_only", True, False)
    check("target", "hdc", "fde")
    check("bus", "ide", "fdc")
    check("error_policy", "stop", None)

    disk = _get_disk("hdd")
    check = _make_checker(disk)
    check("type", "block")
    check("device", "lun")

    disk = _get_disk("sda")
    check = _make_checker(disk)
    disk.set_source_path("http://[1:2:3:4:5:6:7:8]:1122/my/file")
    disk.sync_path_props()

    disk = _get_disk("fda")
    check = _make_checker(disk)
    disk.set_source_path("/pool-dir/default-vol")
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
    check = _make_checker(disk.boot)
    check("order", None, 7, None)

    disk = _get_disk("vdb")
    check = _make_checker(disk)
    check("source.pool", "defaultPool", "anotherPool")
    check("source.volume", "foobar", "newvol")

    disk = _get_disk("vdc")
    check = _make_checker(disk)
    check("source.protocol", "rbd", "gluster")
    check("source.name", "pool/image", "new-val/vol")
    hcheck = _make_checker(disk.source.hosts[0])
    hcheck("name", "mon1.example.org", "diff.example.org")
    hcheck("port", 6321, 1234)
    assert disk.get_source_path() == "gluster://diff.example.org:1234/new-val/vol"

    disk = _get_disk("vdd")
    check = _make_checker(disk)
    hcheck = _make_checker(disk.source.hosts[0])
    check("source.protocol", "nbd")
    hcheck("transport", "unix")
    hcheck("socket", "/var/run/nbdsock")
    assert disk.get_source_path() == "nbd+unix:///var/run/nbdsock"

    _alter_compare(conn, guest.get_xml(), outfile)


def testAlterDevicesBootorder():
    conn = utils.URIs.open_testdefault_cached()
    basename = "change-devices-bootorder"
    guest, outfile = _get_test_content(conn, basename)
    disk_1 = guest.devices.disk[0]
    disk_2 = guest.devices.disk[1]
    disk_3 = guest.devices.disk[2]
    disk_4 = guest.devices.disk[3]
    iface_1 = guest.devices.interface[0]
    iface_2 = guest.devices.interface[1]
    redirdev_1 = guest.devices.redirdev[0]

    assert guest.os.bootorder == ['hd']
    assert disk_1.boot.order is None
    assert disk_2.boot.order == 10
    assert disk_3.boot.order == 10
    assert disk_4.boot.order == 1
    assert iface_1.boot.order == 2
    assert iface_2.boot.order is None
    assert redirdev_1.boot.order == 3

    guest.reorder_boot_order(disk_1, 1)

    assert guest.os.bootorder == []
    assert disk_1.boot.order == 1
    assert disk_2.boot.order == 10
    assert disk_3.boot.order == 10
    # verify that the used algorithm preserves the order of
    # records with equal boot indices
    assert disk_2 is guest.devices.disk[1]
    assert disk_3 is guest.devices.disk[2]
    assert disk_4.boot.order == 2
    assert iface_1.boot.order == 3
    assert iface_2.boot.order is None
    assert redirdev_1.boot.order == 4

    try:
        _alter_compare(conn, guest.get_xml(), outfile)
    except RuntimeError as error:
        assert "unsupported configuration" in str(error)

    guest.reorder_boot_order(disk_2, 10)
    assert disk_2.boot.order == 10
    assert disk_3.boot.order == 11
    assert disk_2 is guest.devices.disk[1]
    assert disk_3 is guest.devices.disk[2]

    outfile = _gen_outfile_path("change-devices-bootorder-fixed")
    _alter_compare(conn, guest.get_xml(), outfile)


def testSingleDisk():
    conn = utils.URIs.open_testdefault_cached()
    xml = ("""<disk type="file" device="disk"><source file="/a.img"/>\n"""
           """<target dev="hda" bus="ide"/></disk>\n""")
    conn = utils.URIs.open_testdefault_cached()
    d = virtinst.DeviceDisk(conn, parsexml=xml)
    _set_and_check(d, "target", "hda", "hdb")
    assert xml.replace("hda", "hdb") == d.get_xml()


def testAlterChars():
    conn = utils.URIs.open_testdefault_cached()
    guest, outfile = _get_test_content(conn, "change-chars")

    serial1     = guest.devices.serial[0]
    serial2     = guest.devices.serial[1]
    parallel1   = guest.devices.parallel[0]
    parallel2   = guest.devices.parallel[1]
    console1    = guest.devices.console[0]
    console2    = guest.devices.console[1]
    channel1    = guest.devices.channel[0]
    channel2    = guest.devices.channel[1]
    channel3    = guest.devices.channel[2]

    check = _make_checker(serial1)
    check("type", "null", "udp")
    check("source.bind_host", None, "example.com")
    check("source.bind_service", None, 66)
    check("source.connect_host", None, "example.com.uk")
    check("source.connect_service", None, 77)

    check = _make_checker(serial2)
    check("type", "tcp")
    check("source.protocol", "telnet", "raw")
    check("source.mode", "bind", "connect")

    check = _make_checker(parallel1)
    check("source.mode", "bind")
    check("source.path", "/tmp/foobar", None)
    check("type", "unix", "pty")

    check = _make_checker(parallel2)
    check("type", "udp")
    check("source.bind_service", 1111, 1357)
    check("source.bind_host", "my.bind.host", "my.foo.host")
    check("source.connect_service", 2222, 7777)
    check("source.connect_host", "my.source.host", "source.foo.host")

    check = _make_checker(console1)
    check("type", "pty")
    check("target_type", None)

    check = _make_checker(console2)
    check("type", "file")
    check("source.path", "/tmp/foo.img", None)
    check("source.path", None, "/root/foo")
    check("target_type", "virtio")
    check("target_state", None, "connected")

    check = _make_checker(channel1)
    check("type", "pty")
    check("target_type", "virtio", "bar", "virtio")
    check("target_name", "foo.bar.frob", "test.changed")

    check = _make_checker(channel2)
    check("type", "unix", "foo", "unix")
    check("target_type", "guestfwd")
    check("target_address", "1.2.3.4", "5.6.7.8")
    check("target_port", 4567, 1199)

    check = _make_checker(channel3)
    check("type", "spiceport")
    check("source.channel", "org.spice-space.webdav.0", "test.1")
    check("target_type", "virtio")
    check("target_name", "org.spice-space.webdav.0", "test.2")
    assert channel3.get_xml_id() == "./devices/channel[3]"
    assert channel3.get_xml_idx() == 2

    _alter_compare(conn, guest.get_xml(), outfile)


def testAlterNics():
    conn = utils.URIs.open_testdefault_cached()
    guest, outfile = _get_test_content(conn, "change-nics")

    dev1 = guest.devices.interface[0]
    dev2 = guest.devices.interface[1]
    dev3 = guest.devices.interface[2]
    dev4 = guest.devices.interface[3]
    dev5 = guest.devices.interface[4]

    check = _make_checker(dev1)
    check("type", "user")
    check("model", None, "vmxnet3")
    check("source", None, None,)
    check("macaddr", "22:11:11:11:11:11", "AA:AA:AA:AA:AA:AA")
    check("filterref", None, "foo")

    check = _make_checker(dev2)
    check("source", "default", None)
    check("type", "network", "bridge")
    check("source", None, "newbr0")
    check("model", "e1000", "virtio")

    check = _make_checker(dev3)
    check("type", "bridge")
    check("source", "foobr0", "newfoo0")
    check("macaddr", "22:22:22:22:22:22")
    check("target_dev", None, "test1")

    check = _make_checker(dev4)
    check("type", "ethernet")
    check("target_dev", "nic02", "nic03")
    check("target_dev", "nic03", None)

    check = _make_checker(dev5)
    check("type", "direct")
    check("source", "eth0.1")
    check("source_mode", "vepa", "bridge")
    check("portgroup", None, "sales")
    check("driver_name", None, "vhost")
    check("driver_queues", None, 5)

    virtualport = dev5.virtualport
    check = _make_checker(virtualport)
    check("type", "802.1Qbg", "foo", "802.1Qbg")
    check("managerid", 12, 11)
    check("typeid", 1193046, 1193047)
    check("typeidversion", 1, 2)
    check("instanceid", "09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b",
                        "09b11c53-8b5c-4eeb-8f00-d84eaa0aaa4f")

    _alter_compare(conn, guest.get_xml(), outfile)


def testQEMUXMLNS():
    kvmconn = utils.URIs.open_kvm()
    basename = "change-xmlns-qemu"
    infile = DATADIR + "%s-in.xml" % basename
    outfile = DATADIR + "%s-out.xml" % basename
    guest = virtinst.Guest(kvmconn, parsexml=open(infile).read())

    check = _make_checker(guest.xmlns_qemu.args[0])
    check("value", "-somearg", "-somenewarg")
    check = _make_checker(guest.xmlns_qemu.args[1])
    check("value", "bar,baz=wib wob", "testval")
    guest.xmlns_qemu.args.add_new().value = "additional-arg"
    arg0 = guest.xmlns_qemu.args[0]
    guest.xmlns_qemu.remove_child(guest.xmlns_qemu.args[0])
    x = "<qemu:arg xmlns:qemu=\"http://libvirt.org/schemas/domain/qemu/1.0\" value=\"-somenewarg\"/>\n"
    assert arg0.get_xml() == x

    check = _make_checker(guest.xmlns_qemu.envs[0])
    check("name", "SOMEENV")
    check("value", "foo=bar baz,foo")
    env = guest.xmlns_qemu.envs.add_new()
    env.name = "DISPLAY"
    env.value = "1:2"

    _alter_compare(kvmconn, guest.get_xml(), outfile)


def testAddRemoveDevices():
    conn = utils.URIs.open_testdefault_cached()
    guest, outfile = _get_test_content(conn, "add-devices")

    # Basic removal of existing device
    rmdev = guest.devices.disk[2]
    guest.remove_device(rmdev)

    # Basic device add
    d = virtinst.DeviceWatchdog(conn)
    d.set_defaults(guest)
    guest.add_device(d)

    # Test adding device with child properties (address value)
    adddev = virtinst.DeviceInterface(conn)
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
    guest.add_device(virtinst.DeviceSound(conn,
        parsexml="""<sound model='pcspk'/>"""))

    _alter_compare(conn, guest.get_xml(), outfile)


def testChangeKVMMedia():
    kvmconn = utils.URIs.open_kvm()
    guest, outfile = _get_test_content(kvmconn, "change-media")

    disk = guest.devices.disk[0]
    disk.set_source_path("/pool-dir/default-vol")
    disk.sync_path_props()

    disk = guest.devices.disk[1]
    disk.set_source_path("/pool-dir/default-vol")
    assert disk.get_source_path() == "/pool-dir/default-vol"
    disk.set_source_path("/dev/pool-logical/diskvol1")
    disk.sync_path_props()

    disk = guest.devices.disk[2]
    disk.set_source_path("/dev/pool-logical/diskvol1")
    disk.sync_path_props()

    disk = guest.devices.disk[3]
    disk.set_source_path("/pool-dir/default-vol")
    disk.sync_path_props()

    disk = guest.devices.disk[4]
    disk.set_source_path("/dev/pool-logical/diskvol1")
    disk.sync_path_props()

    _alter_compare(kvmconn, guest.get_xml(), outfile)


def testGuestBootorder():
    kvmconn = utils.URIs.open_kvm()
    guest, outfile = _get_test_content(kvmconn, "bootorder")

    assert guest.get_boot_order() == ['./devices/disk[1]']
    assert guest.get_boot_order(legacy=True) == ['hd']

    legacy_order = ['hd', 'fd', 'cdrom', 'network']
    dev_order = ['./devices/disk[1]',
             './devices/disk[3]',
             './devices/disk[2]',
             './devices/interface[1]']
    guest.set_boot_order(legacy_order, legacy=True)
    assert guest.get_boot_order() == dev_order
    assert guest.get_boot_order(legacy=True) == legacy_order

    guest.set_boot_order(dev_order)
    assert guest.get_boot_order() == dev_order
    assert guest.get_boot_order(legacy=True) == []

    _alter_compare(kvmconn, guest.get_xml(), outfile)


def testDiskChangeBus():
    conn = utils.URIs.open_testdefault_cached()
    guest, outfile = _get_test_content(conn, "disk-change-bus")

    disk = guest.devices.disk[0]

    # Same bus is a no-op
    origxml = disk.get_xml()
    disk.change_bus(guest, "virtio")
    assert origxml == disk.get_xml()
    disk.change_bus(guest, "ide")

    disk = guest.devices.disk[2]
    disk.change_bus(guest, "scsi")

    _alter_compare(conn, guest.get_xml(), outfile)


##################
# Snapshot tests #
##################


def testChangeSnapshot():
    conn = utils.URIs.open_testdefault_cached()
    basename = "change-snapshot"
    infile = DATADIR + "%s-in.xml" % basename
    outfile = DATADIR + "%s-out.xml" % basename
    snap = virtinst.DomainSnapshot(conn, parsexml=open(infile).read())

    check = _make_checker(snap)
    check("name", "offline-root-child1", "name-foo")
    check("state", "shutoff", "somestate")
    check("description", "offline desk", "foo\nnewline\n   indent")
    check("parent", "offline-root", "newparent")
    check("creationTime", 1375905916, 1234)
    check("memory_type", "no", "external")
    check("memory_file", None, "/some/path/to/memory.img")

    check = _make_checker(snap.disks[0])
    check("name", "hda", "hdb")
    check("snapshot", "internal", "no")

    utils.diff_compare(snap.get_xml(), outfile)


#################
# Storage tests #
#################


def testFSPool():
    conn = utils.URIs.open_testdefault_cached()
    basename = "pool-fs"
    infile = DATADIR + "%s.xml" % basename
    outfile = DATADIR + "%s-out.xml" % basename
    pool = virtinst.StoragePool(conn, parsexml=open(infile).read())

    check = _make_checker(pool)
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
    utils.test_create(conn, pool.get_xml(), "storagePoolDefineXML")


def testISCSIPool():
    conn = utils.URIs.open_testdefault_cached()
    basename = "pool-iscsi"
    infile = utils.DATADIR + "/storage/%s.xml" % basename
    outfile = DATADIR + "%s-out.xml" % basename
    pool = virtinst.StoragePool(conn, parsexml=open(infile).read())

    check = _make_checker(pool)
    check("iqn", "foo.bar.baz.iqn", "my.iqn")
    check = _make_checker(pool.hosts[0])
    check("name", "some.random.hostname", "my.host")

    utils.diff_compare(pool.get_xml(), outfile)
    utils.test_create(conn, pool.get_xml(), "storagePoolDefineXML")


def testGlusterPool():
    conn = utils.URIs.open_testdefault_cached()
    basename = "pool-gluster"
    infile = utils.DATADIR + "/storage/%s.xml" % basename
    outfile = DATADIR + "%s-out.xml" % basename
    pool = virtinst.StoragePool(conn, parsexml=open(infile).read())

    check = _make_checker(pool)
    check("source_path", "/some/source/path", "/foo")
    check = _make_checker(pool.hosts[0])
    check("name", "some.random.hostname", "my.host")

    utils.diff_compare(pool.get_xml(), outfile)
    utils.test_create(conn, pool.get_xml(), "storagePoolDefineXML")


def testRBDPool():
    conn = utils.URIs.open_testdefault_cached()
    basename = "pool-rbd"
    infile = DATADIR + "%s.xml" % basename
    outfile = DATADIR + "%s-out.xml" % basename
    pool = virtinst.StoragePool(conn, parsexml=open(infile).read())

    check = _make_checker(pool.hosts[0])
    check("name", "ceph-mon-1.example.com")
    check("port", 6789, 1234)
    check = _make_checker(pool.hosts[1])
    check("name", "ceph-mon-2.example.com", "foo.bar")
    check("port", 6789)
    check = _make_checker(pool.hosts[2])
    check("name", "ceph-mon-3.example.com")
    check("port", 6789, 1000)
    hostobj = pool.hosts.add_new()
    hostobj.name = "frobber"
    hostobj.port = "5555"

    utils.diff_compare(pool.get_xml(), outfile)
    utils.test_create(conn, pool.get_xml(), "storagePoolDefineXML")


def testVol():
    conn = utils.URIs.open_testdefault_cached()
    basename = "pool-dir-vol"
    infile = DATADIR + "%s-in.xml" % basename
    outfile = DATADIR + "%s-out.xml" % basename
    vol = virtinst.StorageVolume(conn, parsexml=open(infile).read())

    check = _make_checker(vol)
    check("type", None, "file")
    check("key", None, "fookey")
    check("capacity", 10737418240, 2000)
    check("allocation", 5368709120, 1000)
    check("format", "raw", "qcow2")
    check("target_path", None, "/foo/bar")
    check("backing_store", "/foo/bar/baz", "/my/backing")
    check("lazy_refcounts", False, True)

    check = _make_checker(vol.permissions)
    check("mode", "0700", "0744")
    check("owner", "10736", "10000")
    check("group", "10736", "10000")
    check("label", None, "foo.label")

    utils.diff_compare(vol.get_xml(), outfile)


###################
# <network> tests #
###################


def testNetMulti():
    conn = utils.URIs.open_testdefault_cached()
    basename = "network-multi"
    infile = DATADIR + "%s-in.xml" % basename
    outfile = DATADIR + "%s-out.xml" % basename
    net = virtinst.Network(conn, parsexml=open(infile).read())

    check = _make_checker(net)
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

    assert len(net.portgroups) == 2
    check = _make_checker(net.portgroups[0])
    check("name", "engineering", "foo")
    check("default", True, False)

    assert len(net.ips) == 4
    check = _make_checker(net.ips[0])
    check("address", "192.168.7.1", "192.168.8.1")
    check("netmask", "255.255.255.0", "255.255.254.0")
    assert net.can_pxe() is False
    check("tftp", None, "/var/lib/tftproot")
    check("bootp_file", None, "pxeboot.img")
    check("bootp_server", None, "1.2.3.4")
    assert net.can_pxe() is True

    check = _make_checker(net.forward)
    check("mode", "nat", "route")
    check("dev", None, "eth22")
    assert net.can_pxe() is True

    check = _make_checker(net.ips[0].ranges[0])
    check("start", "192.168.7.128", "192.168.8.128")
    check("end", "192.168.7.254", "192.168.8.254")

    check = _make_checker(net.ips[0].hosts[1])
    check("macaddr", "52:54:00:69:eb:91", "52:54:00:69:eb:92")
    check("name", "badbob", "newname")
    check("ip", "192.168.7.3", "192.168.8.3")

    check = _make_checker(net.ips[1])
    check("family", "ipv6", "ipv6")
    check("prefix", 64, 63)

    r = net.routes.add_new()
    r.family = "ipv4"
    r.address = "192.168.8.0"
    r.prefix = "24"
    r.gateway = "192.168.8.10"
    check = _make_checker(r)
    check("netmask", None, "foo", None)

    utils.diff_compare(net.get_xml(), outfile)
    utils.test_create(conn, net.get_xml(), "networkDefineXML")


def testNetOpen():
    conn = utils.URIs.open_testdefault_cached()
    basename = "network-open"
    infile = DATADIR + "%s-in.xml" % basename
    outfile = DATADIR + "%s-out.xml" % basename
    net = virtinst.Network(conn, parsexml=open(infile).read())

    check = _make_checker(net)
    check("name", "open", "new-foo")
    check("domain_name", "open", "newdom")

    check = _make_checker(net.forward)
    check("mode", "open")
    check("dev", None)

    assert len(net.ips) == 1
    check = _make_checker(net.ips[0])
    check("address", "192.168.100.1", "192.168.101.1")
    check("netmask", "255.255.255.0", "255.255.254.0")

    check = _make_checker(net.ips[0].ranges[0])
    check("start", "192.168.100.128", "192.168.101.128")
    check("end", "192.168.100.254", "192.168.101.254")

    utils.diff_compare(net.get_xml(), outfile)
    utils.test_create(conn, net.get_xml(), "networkDefineXML")


def testNetVfPool():
    conn = utils.URIs.open_testdefault_cached()
    basename = "network-vf-pool"
    infile = DATADIR + "%s-in.xml" % basename
    outfile = DATADIR + "%s-out.xml" % basename
    net = virtinst.Network(conn, parsexml=open(infile).read())

    check = _make_checker(net)
    check("name", "passthrough", "new-foo")

    check = _make_checker(net.forward)
    check("mode", "hostdev")
    check("managed", "yes")

    check = _make_checker(net.forward.pf[0])
    check("dev", "eth3")

    utils.diff_compare(net.get_xml(), outfile)
    utils.test_create(conn, net.get_xml(), "networkDefineXML")


##############
# Misc tests #
##############


def testCPUUnknownClear():
    # Make sure .clear() even removes XML elements we don't know about
    kvmconn = utils.URIs.open_kvm()
    basename = "clear-cpu-unknown-vals"
    infile = DATADIR + "%s-in.xml" % basename
    outfile = DATADIR + "%s-out.xml" % basename
    guest = virtinst.Guest(kvmconn, parsexml=open(infile).read())

    guest.cpu.set_special_mode(guest, "host-model-only")
    guest.cpu.clear()
    utils.diff_compare(guest.get_xml(), outfile)


def testDomainRoundtrip():
    conn = utils.URIs.open_testdefault_cached()
    # Make sure our XML engine doesn't mangle non-libvirt XML bits
    infile = DATADIR + "domain-roundtrip.xml"
    outfile = DATADIR + "domain-roundtrip.xml"
    guest = virtinst.Guest(conn, parsexml=open(infile).read())

    utils.diff_compare(guest.get_xml(), outfile)


def testYesNoUnexpectedParse():
    conn = utils.URIs.open_testdefault_cached()
    # Make sure that if we see an unexpected yes/no or on/off value,
    # we just return it to the user and don't error. Libvirt could
    # change our assumptions and we shouldn't be too restrictive
    xml = ("<hostdev managed='foo'>\n  <rom bar='wibble'/>\n"
        "  <source><address bus='hello'/></source>\n</hostdev>")
    dev = virtinst.DeviceHostdev(conn, parsexml=xml)

    assert dev.managed == "foo"
    assert dev.rom_bar == "wibble"
    assert dev.scsi_bus == "hello"

    dev.managed = "test1"
    dev.rom_bar = "test2"
    assert dev.managed == "test1"
    assert dev.rom_bar == "test2"

    with pytest.raises(ValueError):
        dev.scsi_bus = "goodbye"


def testXMLBuilderCoverage():
    """
    Test XMLBuilder corner cases
    """
    conn = utils.URIs.open_testdefault_cached()

    with pytest.raises(RuntimeError, match=".*'foo'.*"):
        # Ensure we validate root element
        virtinst.DeviceDisk(conn, parsexml="<foo/>")

    with pytest.raises(Exception, match=".*xmlParseDoc.*"):
        # Ensure we validate root element
        virtinst.DeviceDisk(conn, parsexml=-1)

    with pytest.raises(virtinst.xmlutil.DevError):
        raise virtinst.xmlutil.DevError("for coverage")

    with pytest.raises(ValueError):
        virtinst.DeviceDisk.validate_generic_name("objtype", None)

    with pytest.raises(ValueError):
        virtinst.DeviceDisk.validate_generic_name("objtype", "foo bar")

    # Test property __repr__ for code coverage
    assert "DeviceAddress" in str(virtinst.DeviceDisk.address)
    assert "./driver/@cache" in str(virtinst.DeviceDisk.driver_cache)

    # Conversion of 0x value into int
    xml = """
        <controller type='scsi'>
          <address type='pci' bus='0x00' slot='0x04' function='0x7'/>
        </controller>
    """
    dev = virtinst.DeviceController(conn, parsexml=xml)
    assert dev.address.slot == 4

    # Some XML formatting and get_xml_* corner cases
    conn = utils.URIs.openconn(utils.URIs.test_suite)
    xml = conn.lookupByName("test-for-virtxml").XMLDesc(0)
    guest = virtinst.Guest(conn, parsexml=xml)

    assert guest.features.get_xml().startswith("  <features")
    assert guest.clock.get_xml().startswith("  <clock")
    assert guest.seclabels[0].get_xml().startswith("<seclabel")
    assert guest.cpu.get_xml().startswith("  <cpu")
    assert guest.os.get_xml().startswith("  <os")
    assert guest.cpu.get_xml_id() == "./cpu"
    assert guest.cpu.get_xml_idx() == 0
    assert guest.get_xml_id() == "."
    assert guest.get_xml_idx() == 0

    assert guest.devices.disk[1].get_xml_id() == "./devices/disk[2]"
    assert guest.devices.disk[1].get_xml_idx() == 1


def testReplaceChildParse():
    conn = utils.URIs.open_testdefault_cached()
    buildfile = DATADIR + "replace-child-build.xml"
    parsefile = DATADIR + "replace-child-parse.xml"

    def mkdisk(target):
        disk = virtinst.DeviceDisk(conn)
        disk.device = "cdrom"
        disk.bus = "scsi"
        disk.target = target
        return disk

    guest = virtinst.Guest(conn)
    guest.add_device(mkdisk("sda"))
    guest.add_device(mkdisk("sdb"))
    guest.add_device(mkdisk("sdc"))
    guest.add_device(mkdisk("sdd"))
    guest.add_device(mkdisk("sde"))
    guest.add_device(mkdisk("sdf"))
    guest.devices.replace_child(guest.devices.disk[2], mkdisk("sdz"))
    guest.set_defaults(guest)
    utils.diff_compare(guest.get_xml(), buildfile)

    guest = virtinst.Guest(conn, parsexml=guest.get_xml())
    newdisk = virtinst.DeviceDisk(conn,
            parsexml=mkdisk("sdw").get_xml())
    guest.devices.replace_child(guest.devices.disk[4], newdisk)
    utils.diff_compare(guest.get_xml(), parsefile)


def testGuestXMLDeviceMatch():
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


def testControllerAttachedDevices():
    """
    Test DeviceController.get_attached_devices
    """
    conn = utils.URIs.open_testdefault_cached()
    xml = open(DATADIR + "controller-attached-devices.xml").read()
    guest = virtinst.Guest(conn, xml)

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


def testRefreshMachineType():
    guest = virtinst.Guest(utils.URIs.openconn(utils.URIs.kvm_x86))
    guest.os.machine = "pc-i440fx-5.2"
    guest.refresh_machine_type()
    assert guest.os.machine == "pc"

    guest = virtinst.Guest(utils.URIs.openconn(utils.URIs.kvm_x86))
    guest.os.machine = "pc-q35-XYZ"
    guest.refresh_machine_type()
    assert guest.os.machine == "q35"

    guest = virtinst.Guest(utils.URIs.openconn(utils.URIs.kvm_s390x))
    guest.os.machine = "s390-ccw-virtio-12345"
    guest.refresh_machine_type()
    assert guest.os.machine == "s390-ccw-virtio"


def testDiskSourceAbspath():
    # If an existing disk doesn't have an abspath in the XML, make sure
    # we don't convert it just by parsing
    conn = utils.URIs.open_testdefault_cached()
    xml = "<disk type='file' device='disk'><source file='foobar'/></disk>"
    disk = virtinst.DeviceDisk(conn, parsexml=xml)
    assert disk.get_source_path() == "foobar"

    # But setting a relative path should convert it
    import os
    disk.set_source_path("foobar2")
    assert disk.get_source_path() == os.path.abspath("foobar2")

    # ...unless it's a URL
    disk.set_source_path("http://example.com/foobar3")
    assert disk.get_source_path() == "http://example.com/foobar3"


def testUnknownEmulatorDomcapsLookup(monkeypatch):
    """
    Libvirt can handle defining a VM with a custom emulator, one not detected
    by `virsh capabilities`. An appropriate `virsh domcapabilities` call will
    inspect the emulator and return relevant info.

    This test ensures that for parsing XML the `virsh capabilities` failure
    isn't fatal, and we attempt to return valid `virsh domcapabilities` data
    """

    seen = False
    def fake_build_from_params(conn, emulator, arch, machine, _hvtype):
        nonlocal seen
        seen = True
        assert arch == "mips"
        assert machine == "some-unknown-machine"
        assert emulator == "/my/manual/emulator"
        return virtinst.DomainCapabilities(conn)

    monkeypatch.setattr(
        "virtinst.DomainCapabilities.build_from_params",
        fake_build_from_params)

    conn = utils.URIs.open_kvm()
    xml = open(DATADIR + "emulator-custom.xml").read()
    guest = virtinst.Guest(conn, xml)
    assert guest.lookup_domcaps()
    assert guest.lookup_domcaps()
    assert seen


def testConvertToQ35():
    conn = utils.URIs.openconn(utils.URIs.kvm_x86)

    def _test(filename_base, **kwargs):
        guest, outfile = _get_test_content(conn, filename_base)
        guest.convert_to_q35(**kwargs)
        _alter_compare(conn, guest.get_xml(), outfile)

    _test("convert-to-q35-win10")
    _test("convert-to-q35-f39", num_pcie_root_ports=5)


def testConvertToVNC():
    conn = utils.URIs.openconn(utils.URIs.kvm_x86)

    def _test(filename_base, **kwargs):
        guest, outfile = _get_test_content(conn, filename_base)
        guest.convert_to_vnc(**kwargs)
        _alter_compare(conn, guest.get_xml(), outfile)

    _test("convert-to-vnc-empty", qemu_vdagent=True)
    _test("convert-to-vnc-spice-devices")
    _test("convert-to-vnc-spice-manyopts", qemu_vdagent=True)
    _test("convert-to-vnc-has-vnc", qemu_vdagent=True)

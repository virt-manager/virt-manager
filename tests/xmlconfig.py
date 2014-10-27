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

import unittest
import os
import logging

import virtinst
from virtinst import VirtualDisk
from virtinst import VirtualAudio
from virtinst import VirtualNetworkInterface
from virtinst import VirtualHostDevice
from virtinst import (VirtualChannelDevice, VirtualConsoleDevice,
                      VirtualParallelDevice, VirtualSerialDevice)
from virtinst import VirtualVideoDevice
from virtinst import VirtualController
from virtinst import VirtualWatchdog
from virtinst import VirtualMemballoon
from virtinst import VirtualPanicDevice

from tests import utils

# pylint: disable=protected-access
# Access to protected member, needed to unittest stuff

_testconn = utils.open_testdriver()
_kvmconn = utils.open_testkvmdriver()
_plainkvm = utils.open_plainkvm()
_plainxen = utils.open_plainxen()


def qemu_uri():
    return "qemu:///system"


def xen_uri():
    return "xen:///"


def build_xmlfile(filebase):
    if not filebase:
        return None
    return os.path.join("tests/xmlconfig-xml", filebase + ".xml")


class TestXMLConfig(unittest.TestCase):

    def setUp(self):
        utils.reset_conn()
        logging.debug("Running %s", self.id())

    def _compare(self, guest, filebase, do_install, do_disk_boot=False,
                 do_create=True):
        filename = filebase and build_xmlfile(filebase) or None

        cont_xml = None
        inst_xml, boot_xml = guest.start_install(return_xml=True, dry=True)
        if do_disk_boot:
            cont_xml, boot_xml = guest.continue_install(return_xml=True,
                                                        dry=True)

        if do_disk_boot:
            actualXML = cont_xml
        elif do_install:
            actualXML = inst_xml
        else:
            actualXML = boot_xml

        if filename:
            utils.diff_compare(actualXML, filename)
        if do_create:
            utils.test_create(guest.conn, actualXML)

    def _testInstall(self, guest,
                     instxml=None, bootxml=None, contxml=None,
                     detect_distro=False):
        instname = build_xmlfile(instxml)
        bootname = build_xmlfile(bootxml)
        contname = build_xmlfile(contxml)
        meter = None

        try:
            if detect_distro:
                guest.os_variant = guest.installer.detect_distro(guest)

            guest.start_install(meter=meter)
            guest.domain.destroy()

            xmlinst = guest.get_install_xml(True, False)
            xmlboot = guest.get_install_xml(False, False)
            xmlcont = guest.get_install_xml(True, True)

            if instname:
                utils.diff_compare(xmlinst, instname)
            if contname:
                utils.diff_compare(xmlcont, contname)
            if bootname:
                utils.diff_compare(xmlboot, bootname)

            if guest.get_continue_inst():
                guest.continue_install(meter=meter)

        finally:
            try:
                guest.domain.destroy()
            except:
                pass
            try:
                guest.domain.undefine()
            except:
                pass


    def testBootParavirtDiskFile(self):
        g = utils.get_basic_paravirt_guest()
        g.add_device(utils.get_filedisk("/dev/default-pool/somerandomfilename.img"))
        self._compare(g, "boot-paravirt-disk-file", False)

    def testBootParavirtDiskFileBlktapCapable(self):
        oldblktap = virtinst.util.is_blktap_capable
        try:
            virtinst.util.is_blktap_capable = lambda ignore: True
            g = utils.get_basic_paravirt_guest()
            g.add_device(utils.get_filedisk())
            self._compare(g, "boot-paravirt-disk-drv-tap", False)
        finally:
            virtinst.util.is_blktap_capable = oldblktap

    def testBootParavirtDiskBlock(self):
        g = utils.get_basic_paravirt_guest()
        g.add_device(utils.get_blkdisk())
        self._compare(g, "boot-paravirt-disk-block", False)

    def testBootParavirtDiskDrvPhy(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_blkdisk()
        disk.driver_name = VirtualDisk.DRIVER_PHY
        g.add_device(disk)
        self._compare(g, "boot-paravirt-disk-drv-phy", False)

    def testBootParavirtDiskDrvFile(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_FILE
        g.add_device(disk)
        self._compare(g, "boot-paravirt-disk-drv-file", False)

    def testBootParavirtDiskDrvTap(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_TAP
        g.add_device(disk)
        self._compare(g, "boot-paravirt-disk-drv-tap", False)

    def testBootParavirtDiskDrvTapQCow(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_TAP
        disk.driver_type = VirtualDisk.DRIVER_TAP_QCOW
        g.add_device(disk)
        self._compare(g, "boot-paravirt-disk-drv-tap-qcow", False)

    def testBootParavirtManyDisks(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk("/dev/default-pool/test2.img")
        disk.driver_name = VirtualDisk.DRIVER_TAP
        disk.driver_type = VirtualDisk.DRIVER_TAP_QCOW

        g.add_device(utils.get_filedisk("/dev/default-pool/test1.img"))
        g.add_device(disk)
        g.add_device(utils.get_blkdisk())
        self._compare(g, "boot-paravirt-many-disks", False)

    def testBootFullyvirtDiskFile(self):
        g = utils.get_basic_fullyvirt_guest()
        g.add_device(utils.get_filedisk())
        self._compare(g, "boot-fullyvirt-disk-file", False)

    def testBootFullyvirtDiskBlock(self):
        g = utils.get_basic_fullyvirt_guest()
        g.add_device(utils.get_blkdisk())
        self._compare(g, "boot-fullyvirt-disk-block", False)



    def testInstallParavirtDiskFile(self):
        g = utils.get_basic_paravirt_guest()
        g.add_device(utils.get_filedisk())
        self._compare(g, "install-paravirt-disk-file", True)

    def testInstallParavirtDiskBlock(self):
        g = utils.get_basic_paravirt_guest()
        g.add_device(utils.get_blkdisk())
        self._compare(g, "install-paravirt-disk-block", True)

    def testInstallParavirtDiskDrvPhy(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_blkdisk()
        disk.driver_name = VirtualDisk.DRIVER_PHY
        g.add_device(disk)
        self._compare(g, "install-paravirt-disk-drv-phy", True)

    def testInstallParavirtDiskDrvFile(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_FILE
        g.add_device(disk)
        self._compare(g, "install-paravirt-disk-drv-file", True)

    def testInstallParavirtDiskDrvTap(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_TAP
        g.add_device(disk)
        self._compare(g, "install-paravirt-disk-drv-tap", True)

    def testInstallParavirtDiskDrvTapQCow(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_TAP
        disk.driver_type = VirtualDisk.DRIVER_TAP_QCOW
        g.add_device(disk)
        self._compare(g, "install-paravirt-disk-drv-tap-qcow", True)

    def testInstallParavirtManyDisks(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk("/dev/default-pool/test2.img")
        disk.driver_name = VirtualDisk.DRIVER_TAP
        disk.driver_type = VirtualDisk.DRIVER_TAP_QCOW

        g.add_device(utils.get_filedisk("/dev/default-pool/test1.img"))
        g.add_device(disk)
        g.add_device(utils.get_blkdisk())
        self._compare(g, "install-paravirt-many-disks", True)

    def testInstallFullyvirtDiskFile(self):
        g = utils.get_basic_fullyvirt_guest()
        g.add_device(utils.get_filedisk())
        self._compare(g, "install-fullyvirt-disk-file", True)

    def testInstallFullyvirtDiskBlock(self):
        g = utils.get_basic_fullyvirt_guest()
        g.add_device(utils.get_blkdisk())
        self._compare(g, "install-fullyvirt-disk-block", True)

    def testInstallFVPXE(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)
        g.add_device(utils.get_filedisk())
        self._compare(g, "install-fullyvirt-pxe", True)

    def testBootFVPXE(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)
        g.add_device(utils.get_filedisk())
        self._compare(g, "boot-fullyvirt-pxe", False)

    def testBootFVPXEAlways(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)
        g.add_device(utils.get_filedisk())

        g.os.bootorder = [
            g.os.BOOT_DEVICE_NETWORK]
        g.os.enable_bootmenu = True

        self._compare(g, "boot-fullyvirt-pxe-always", False)

    def testInstallFVPXENoDisks(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)
        self._compare(g, "install-fullyvirt-pxe-nodisks", True)

    def testBootFVPXENoDisks(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)
        self._compare(g, "boot-fullyvirt-pxe-nodisks", False)

    def testInstallFVLiveCD(self):
        i = utils.make_live_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)
        self._compare(g, "install-fullyvirt-livecd", False)

    def testDoubleInstall(self):
        # Make sure that installing twice generates the same XML, to ensure
        # we aren't polluting the device list during the install process
        i = utils.make_live_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)
        self._compare(g, "install-fullyvirt-livecd", False)
        self._compare(g, "install-fullyvirt-livecd", False)

    def testOSDeviceDefaultChange(self):
        """
        Make sure device defaults are properly changed if we change OS
        distro/variant mid process
        """
        conn = utils.open_plainkvm(connver=12005)
        utils.set_conn(conn)

        i = utils.make_distro_installer()
        g = utils.get_basic_fullyvirt_guest("kvm", installer=i)

        do_install = False
        g.installer.cdrom = True
        g.add_device(utils.get_floppy())
        g.add_device(utils.get_filedisk())
        g.add_device(utils.get_blkdisk())
        g.add_device(utils.get_virtual_network())
        g.add_device(VirtualAudio(g.conn))

        # Call get_xml_config sets first round of defaults w/o os_variant set
        g.get_install_xml(do_install)

        g.os_variant = "fedora11"
        self._compare(g, "install-f11-norheldefaults", do_install)

        try:
            virtinst.stable_defaults = True
            origemu = g.emulator
            g.emulator = "/usr/libexec/qemu-kvm"
            g.conn._support_cache = {}
            self._compare(g, "install-f11-rheldefaults", do_install)
            g.emulator = origemu
            g.conn._support_cache = {}
        finally:
            virtinst.stable_defaults = False

        # Verify main guest wasn't polluted
        self._compare(g, "install-f11-norheldefaults", do_install)

    def testInstallFVImport(self):
        i = utils.make_import_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        g.add_device(utils.get_filedisk())
        self._compare(g, "install-fullyvirt-import", False)

    def testInstallFVImportKernel(self):
        i = utils.make_import_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        g.add_device(utils.get_filedisk())
        g.os.kernel = "/kernel"
        g.os.initrd = "/initrd"
        g.os.kernel_args = "my kernel args"

        self._compare(g, "install-fullyvirt-import-kernel", False)

    def testInstallFVImportMulti(self):
        i = utils.make_import_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        g.os.enable_bootmenu = False
        g.os.bootorder = ["hd", "fd", "cdrom", "network"]
        g.add_device(utils.get_filedisk())
        self._compare(g, "install-fullyvirt-import-multiboot", False)

    def testInstallPVImport(self):
        i = utils.make_import_installer()
        g = utils.get_basic_paravirt_guest(installer=i)

        g.add_device(utils.get_filedisk())
        self._compare(g, "install-paravirt-import", False)

    def testQEMUDriverName(self):
        utils.set_conn(_plainkvm)
        g = utils.get_basic_fullyvirt_guest()
        g.add_device(utils.get_blkdisk())
        self._compare(g, "misc-qemu-driver-name", True)

        g = utils.get_basic_fullyvirt_guest()
        g.add_device(utils.get_filedisk())
        g.add_device(utils.get_blkdisk("/iscsi-pool/diskvol1"))
        self._compare(g, "misc-qemu-driver-type", True)

        g = utils.get_basic_fullyvirt_guest()
        g.add_device(utils.get_filedisk("/dev/default-pool/iso-vol"))
        self._compare(g, "misc-qemu-iso-disk", True)

        g = utils.get_basic_fullyvirt_guest()
        g.add_device(utils.get_filedisk("/dev/default-pool/iso-vol"))
        g.get_devices("disk")[0].driver_type = "qcow2"
        self._compare(g, "misc-qemu-driver-overwrite", True)

    def testXMLEscaping(self):
        g = utils.get_basic_fullyvirt_guest()
        g.description = "foooo barrrr \n baz && snarf. '' \"\" @@$\n"
        g.add_device(utils.get_filedisk("/dev/default-pool/ISO&'&s"))
        self._compare(g, "misc-xml-escaping", True)

    # OS Type/Version configurations
    def testF10(self):
        utils.set_conn(_plainkvm)
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest("kvm", installer=i)

        g.os_variant = "fedora10"
        g.add_device(utils.get_filedisk())
        g.add_device(utils.get_blkdisk())
        g.add_device(utils.get_virtual_network())
        self._compare(g, "install-f10", True)

    def testF11(self):
        utils.set_conn(_plainkvm)
        i = utils.make_distro_installer()
        g = utils.get_basic_fullyvirt_guest("kvm", installer=i)
        g.os.os_type = "hvm"

        g.os_variant = "fedora11"
        g.installer.cdrom = True
        g.add_device(utils.get_floppy())
        g.add_device(utils.get_filedisk())
        g.add_device(utils.get_blkdisk())
        g.add_device(utils.get_virtual_network())
        self._compare(g, "install-f11", False)

    def testF11AC97(self):
        def build_guest():
            i = utils.make_distro_installer()
            g = utils.get_basic_fullyvirt_guest("kvm", installer=i)

            g.os_variant = "fedora11"
            g.installer.cdrom = True
            g.add_device(utils.get_floppy())
            g.add_device(utils.get_filedisk())
            g.add_device(utils.get_blkdisk())
            g.add_device(utils.get_virtual_network())
            g.add_device(VirtualAudio(g.conn))
            return g

        utils.set_conn(utils.open_plainkvm(connver=11000))
        g = build_guest()
        self._compare(g, "install-f11-ac97", False)

        utils.set_conn(utils.open_plainkvm(libver=5000))
        g = build_guest()
        self._compare(g, "install-f11-noac97", False)

        utils.set_conn(utils.open_plainkvm(libver=7000, connver=7000))
        g = build_guest()
        self._compare(g, "install-f11-noac97", False)

    def testKVMKeymap(self):
        conn = utils.open_plainkvm(connver=10000)
        g = virtinst.VirtualGraphics(conn)
        g.type = "vnc"
        self.assertTrue(g.keymap is not None)

        conn = utils.open_plainkvm(connver=11000)
        g = virtinst.VirtualGraphics(conn)
        g.type = "vnc"
        self.assertTrue(g.keymap is None)


    def testF11Qemu(self):
        utils.set_conn(_plainkvm)
        i = utils.make_distro_installer()
        g = utils.get_basic_fullyvirt_guest("qemu", installer=i)

        g.os_variant = "fedora11"
        g.installer.cdrom = True
        g.add_device(utils.get_floppy())
        g.add_device(utils.get_filedisk())
        g.add_device(utils.get_blkdisk())
        g.add_device(utils.get_virtual_network())
        self._compare(g, "install-f11-qemu", False)

    def testF11Xen(self):
        utils.set_conn(_plainxen)
        i = utils.make_distro_installer()
        g = utils.get_basic_fullyvirt_guest("xen", installer=i)

        g.os_variant = "fedora11"
        g.installer.cdrom = True
        g.add_device(utils.get_floppy())
        g.add_device(utils.get_filedisk())
        g.add_device(utils.get_blkdisk())
        g.add_device(utils.get_virtual_network())
        self._compare(g, "install-f11-xen", False)

    def testInstallWindowsKVM(self):
        utils.set_conn(_plainkvm)
        g = utils.build_win_kvm("/dev/default-pool/winxp.img")
        self._compare(g, "winxp-kvm-stage1", True)

    def testContinueWindowsKVM(self):
        utils.set_conn(_plainkvm)
        g = utils.build_win_kvm("/dev/default-pool/winxp.img")
        self._compare(g, "winxp-kvm-stage2", True, True)

    def testBootWindowsKVM(self):
        utils.set_conn(_plainkvm)
        g = utils.build_win_kvm("/dev/default-pool/winxp.img")
        self._compare(g, "winxp-kvm-stage3", False)


    def testInstallWindowsXenNew(self):
        def make_guest():
            g = utils.get_basic_fullyvirt_guest("xen")
            g.os_variant = "winxp"
            g.add_device(utils.get_filedisk())
            g.add_device(utils.get_blkdisk())
            g.add_device(utils.get_virtual_network())
            g.add_device(VirtualAudio(g.conn))
            return g

        utils.set_conn(utils.open_plainxen(connver=3000001))
        g = make_guest()
        self._compare(g, "install-windowsxp-xenold", True)

        utils.set_conn(utils.open_plainxen(connver=3100000))
        g = make_guest()
        self._compare(g, "install-windowsxp-xennew", True)

    # Device heavy configurations
    def testManyDisks2(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        g.add_device(utils.get_filedisk())
        g.add_device(utils.get_blkdisk())

        d = VirtualDisk(g.conn)
        d.type = "block"
        d.path = "/dev/null"
        d.device = d.DEVICE_CDROM
        d.driver_type = "raw"
        d.validate()
        g.add_device(d)

        d = VirtualDisk(g.conn)
        d.type = "block"
        d.path = "/dev/null"
        d.device = d.DEVICE_DISK
        d.driver_name = "qemu"
        d.validate()
        g.add_device(d)

        d = VirtualDisk(g.conn)
        d.path = None
        d.device = d.DEVICE_CDROM
        d.bus = "scsi"
        d.validate()
        g.add_device(d)

        d = VirtualDisk(g.conn)
        d.path = None
        d.device = d.DEVICE_FLOPPY
        d.iotune_tbs = 1
        d.iotune_tis = 2
        d.validate()
        g.add_device(d)

        d = VirtualDisk(g.conn)
        d.type = "block"
        d.path = "/dev/null"
        d.device = d.DEVICE_FLOPPY
        d.driver_name = "phy"
        d.driver_cache = "none"
        d.iotune_rbs = 5555
        d.iotune_ris = 1234
        d.iotune_wbs = 3
        d.iotune_wis = 4
        d.validate()
        g.add_device(d)

        d = VirtualDisk(g.conn)
        d.type = "block"
        d.path = "/dev/null"
        d.bus = "virtio"
        d.driver_name = "qemu"
        d.driver_type = "qcow2"
        d.driver_cache = "none"
        d.driver_io = "threads"
        d.validate()
        g.add_device(d)

        self._compare(g, "boot-many-disks2", False)

    def testManyNICs(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        net1 = VirtualNetworkInterface(g.conn)
        net1.type = "user"
        net1.macaddr = "22:11:11:11:11:11"

        net2 = utils.get_virtual_network()
        net3 = utils.get_virtual_network()
        net3.model = "e1000"

        net4 = VirtualNetworkInterface(g.conn)
        net4.source = "foobr0"
        net4.macaddr = "22:22:22:22:22:22"
        net4.target_dev = "foo1"

        net5 = VirtualNetworkInterface(g.conn)
        net5.type = "ethernet"
        net5.macaddr = "00:11:00:22:00:33"
        net5.source = "testeth1"

        g.add_device(net1)
        g.add_device(net2)
        g.add_device(net3)
        g.add_device(net4)
        g.add_device(net5)
        self._compare(g, "boot-many-nics", False)

    def testManyHostdevs(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        dev1 = VirtualHostDevice(g.conn)
        dev1.type = "usb"
        dev1.product = "0x1234"
        dev1.vendor = "0x4321"

        dev2 = VirtualHostDevice(g.conn)
        dev2.type = "pci"
        dev2.bus = "0x11"
        dev2.slot = "0x2"
        dev2.function = "0x3"

        g.add_device(dev1)
        g.add_device(dev2)
        self._compare(g, "boot-many-hostdevs", False)

    def testManySounds(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        d = VirtualAudio(g.conn)
        d.model = "sb16"
        g.add_device(d)

        d = VirtualAudio(g.conn)
        d.model = "es1370"
        g.add_device(d)

        d = VirtualAudio(g.conn)
        d.model = "pcspk"
        g.add_device(d)

        d = VirtualAudio(g.conn)
        g.add_device(d)

        self._compare(g, "boot-many-sounds", False)

    def testManyChars(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        dev = VirtualSerialDevice(g.conn)
        dev.type = "null"
        g.add_device(dev)

        dev = VirtualParallelDevice(g.conn)
        dev.type = "unix"
        dev.source_path = "/dev/default-pool/foobar"
        g.add_device(dev)

        dev = VirtualSerialDevice(g.conn)
        dev.type = "tcp"
        dev.protocol = "telnet"
        dev.source_host = "my.source.host"
        dev.source_port = "1234"
        g.add_device(dev)

        dev = VirtualParallelDevice(g.conn)
        dev.type = "udp"
        dev.bind_host = "my.bind.host"
        dev.bind_port = "1111"
        dev.source_host = "my.source.host"
        dev.source_port = "2222"
        g.add_device(dev)

        dev = VirtualChannelDevice(g.conn)
        dev.type = "pty"
        dev.target_type = dev.CHANNEL_TARGET_VIRTIO
        dev.target_name = "foo.bar.frob"
        g.add_device(dev)

        dev = VirtualConsoleDevice(g.conn)
        dev.type = "pty"
        dev.target_type = dev.CONSOLE_TARGET_VIRTIO
        g.add_device(dev)

        dev = VirtualChannelDevice(g.conn)
        dev.type = "pty"
        dev.target_type = dev.CHANNEL_TARGET_GUESTFWD
        dev.target_address = "1.2.3.4"
        dev.target_port = "4567"
        g.add_device(dev)

        self._compare(g, "boot-many-chars", False)

    def testManyDevices(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        g.description = "foooo barrrr somedesc"
        g.memoryBacking.hugepages = True

        # Hostdevs
        dev1 = VirtualHostDevice(g.conn)
        dev1.type = "usb"
        dev1.vendor = "0x4321"
        dev1.product = "0x1234"
        g.add_device(dev1)

        # Sound devices
        d = VirtualAudio(g.conn)
        d.model = "sb16"
        g.add_device(d)

        d = VirtualAudio(g.conn)
        d.model = "es1370"
        g.add_device(d)

        # Disk devices
        d = VirtualDisk(g.conn)
        d.type = "block"
        d.path = "/dev/null"
        d.device = d.DEVICE_FLOPPY
        d.validate()
        g.add_device(d)

        d = VirtualDisk(g.conn)
        d.type = "block"
        d.path = "/dev/null"
        d.bus = "scsi"
        d.validate()
        g.add_device(d)

        d = VirtualDisk(g.conn)
        d.path = "/tmp"
        d.device = d.DEVICE_FLOPPY
        d.validate()
        g.add_device(d)

        d = VirtualDisk(g.conn)
        d.path = "/dev/default-pool/testvol1.img"
        d.bus = "scsi"
        d.driver_name = "qemu"
        d.address.type = "spapr-vio"
        d.validate()
        g.add_device(d)

        # Controller devices
        c1 = VirtualController(g.conn)
        c1.type = "ide"
        c1.index = "3"
        c2 = VirtualController(g.conn)
        c2.type = "virtio-serial"
        c2.ports = "32"
        c2.vectors = "17"
        g.add_device(c1)
        g.add_device(c2)

        # Network devices
        net1 = utils.get_virtual_network()
        net1.model = "e1000"

        net2 = VirtualNetworkInterface(g.conn)
        net2.type = "user"
        net2.macaddr = "22:11:11:11:11:11"
        net3 = VirtualNetworkInterface(g.conn)
        net3.type = virtinst.VirtualNetworkInterface.TYPE_VIRTUAL
        net3.macaddr = "22:22:22:22:22:22"
        net3.source = "default"
        net3.model = "spapr-vlan"
        net3.address.set_addrstr("spapr-vio")
        g.add_device(net1)
        g.add_device(net2)
        g.add_device(net3)

        # Character devices
        cdev1 = VirtualSerialDevice(g.conn)
        cdev1.type = "null"
        cdev2 = VirtualParallelDevice(g.conn)
        cdev2.type = "unix"
        cdev2.source_path = "/dev/default-pool/foobar"
        cdev3 = VirtualChannelDevice(g.conn)
        cdev3.type = "spicevmc"
        g.add_device(cdev1)
        g.add_device(cdev2)
        g.add_device(cdev3)

        # Video Devices
        vdev1 = VirtualVideoDevice(g.conn)
        vdev1.model = "vmvga"

        vdev2 = VirtualVideoDevice(g.conn)
        vdev2.model = "cirrus"
        vdev2.vram = 10 * 1024
        vdev2.heads = 3

        vdev3 = VirtualVideoDevice(g.conn)
        vdev4 = VirtualVideoDevice(g.conn)
        vdev4.model = "qxl"

        g.add_device(vdev1)
        g.add_device(vdev2)
        g.add_device(vdev3)
        g.add_device(vdev4)

        # Watchdog Devices
        wdev2 = VirtualWatchdog(g.conn)
        wdev2.model = "ib700"
        wdev2.action = "none"
        g.add_device(wdev2)

        # Memballoon Devices
        mdev1 = VirtualMemballoon(g.conn)
        mdev1.model = "virtio"
        g.add_device(mdev1)

        # Check keymap autoconfig
        gdev1 = virtinst.VirtualGraphics(g.conn)
        gdev1.type = "vnc"
        self.assertTrue(gdev1.keymap is not None)
        gdev1.keymap = "en-us"

        # Check keymap None
        gdev2 = virtinst.VirtualGraphics(g.conn)
        gdev2.type = "vnc"
        gdev2.keymap = None

        gdev3 = virtinst.VirtualGraphics(g.conn)
        gdev3.type = "sdl"
        gdev3.xauth = "/dev/default-pool/.Xauthority"
        gdev3.display = ":3.4"
        gdev4 = virtinst.VirtualGraphics(g.conn)
        gdev4.type = "spice"
        gdev4.passwdValidTo = "foobar"

        gdev5 = virtinst.VirtualGraphics(g.conn)
        gdev5.type = "sdl"
        gdev5.xauth = "fooxauth"
        gdev5.display = "foodisplay"
        g.add_device(gdev1)
        g.add_device(gdev2)
        g.add_device(gdev3)
        g.add_device(gdev4)
        g.add_device(gdev5)

        g.clock.offset = "localtime"

        g.seclabel.type = g.seclabel.TYPE_STATIC
        g.seclabel.model = "selinux"
        g.seclabel.label = "foolabel"
        g.seclabel.imagelabel = "imagelabel"

        redir1 = virtinst.VirtualRedirDevice(g.conn)
        redir1.type = "spicevmc"

        redir2 = virtinst.VirtualRedirDevice(g.conn)
        redir2.type = "tcp"
        redir2.parse_friendly_server("foobar.com:1234")
        g.add_device(redir1)
        g.add_device(redir2)

        # Panic Notifier device
        pdev = VirtualPanicDevice(g.conn)
        g.add_device(pdev)

        self._compare(g, "boot-many-devices", False)

    def testCpuset(self):
        normaltest = utils.open_testdefault()
        utils.set_conn(normaltest)
        g = utils.get_basic_fullyvirt_guest()

        # Cpuset
        cpustr = virtinst.DomainNumatune.generate_cpuset(g.conn, g.memory)
        g.cpuset = cpustr
        g.vcpus = 7

        g.cpu.model = "footest"
        g.cpu.vendor = "Intel"
        g.cpu.match = "minimum"

        g.cpu.threads = "2"
        g.cpu.sockets = "4"
        g.cpu.cores = "5"

        g.cpu.add_feature("x2apic", "force")
        g.cpu.add_feature("lahf_lm", "forbid")

        self._compare(g, "boot-cpuset", False)

        # Test CPU topology determining
        cpu = virtinst.CPU(g.conn)
        cpu.sockets = "2"
        cpu.set_topology_defaults(6)
        self.assertEquals([cpu.sockets, cpu.cores, cpu.threads], [2, 3, 1])

        cpu = virtinst.CPU(g.conn)
        cpu.cores = "4"
        cpu.set_topology_defaults(9)
        self.assertEquals([cpu.sockets, cpu.cores, cpu.threads], [2, 4, 1])

        cpu = virtinst.CPU(g.conn)
        cpu.threads = "3"
        cpu.set_topology_defaults(14)
        self.assertEquals([cpu.sockets, cpu.cores, cpu.threads], [4, 1, 3])

        cpu = virtinst.CPU(g.conn)
        cpu.sockets = 5
        cpu.cores = 2
        self.assertEquals(cpu.vcpus_from_topology(), 10)

        cpu = virtinst.CPU(g.conn)
        self.assertEquals(cpu.vcpus_from_topology(), 1)

    def testUsb2(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        for dev in virtinst.VirtualController.get_usb2_controllers(g.conn):
            g.add_device(dev)

        self._compare(g, "boot-usb2", False)


    def testFullKVMRHEL6(self):
        utils.set_conn(_plainkvm)
        i = utils.make_distro_installer(
            location="tests/cli-test-xml/fakerhel6tree")
        g = utils.get_basic_fullyvirt_guest("kvm", installer=i)
        g.add_device(utils.get_floppy())
        g.add_device(utils.get_filedisk("/dev/default-pool/rhel6.img", fake=False))
        g.add_device(utils.get_blkdisk())
        g.add_device(utils.get_virtual_network())
        g.add_device(VirtualAudio(g.conn))
        g.add_device(VirtualVideoDevice(g.conn))

        self._testInstall(g, "rhel6-kvm-stage1", "rhel6-kvm-stage2",
            detect_distro=True)

    def testFullKVMWinxp(self):
        utils.set_conn(_plainkvm)
        g = utils.build_win_kvm("/dev/default-pool/winxp.img", fake=False)
        self._testInstall(g, "winxp-kvm-stage1",
                          "winxp-kvm-stage3", "winxp-kvm-stage2")

    def testDefaultBridge(self):
        origfunc = None
        util = None
        try:
            util = getattr(virtinst, "util")
            origfunc = util.default_bridge

            def newbridge(ignore_conn):
                return "bzz0"
            util.default_bridge = newbridge

            dev1 = virtinst.VirtualNetworkInterface(utils.get_conn())
            dev1.macaddr = "22:22:33:44:55:66"

            dev2 = virtinst.VirtualNetworkInterface(utils.get_conn(),
                                    parsexml=dev1.get_xml_config())
            dev2.source = None
            dev2.source = "foobr0"
            dev2.macaddr = "22:22:33:44:55:67"

            dev3 = virtinst.VirtualNetworkInterface(utils.get_conn(),
                                    parsexml=dev1.get_xml_config())
            dev3.source = None
            dev3.macaddr = "22:22:33:44:55:68"

            utils.diff_compare(dev1.get_xml_config(), None,
                               "<interface type=\"bridge\">\n"
                               "  <source bridge=\"bzz0\"/>\n"
                               "  <mac address=\"22:22:33:44:55:66\"/>\n"
                               "</interface>\n")
            utils.diff_compare(dev2.get_xml_config(), None,
                               "<interface type=\"bridge\">\n"
                               "  <source bridge=\"foobr0\"/>\n"
                               "  <mac address=\"22:22:33:44:55:67\"/>\n"
                               "</interface>\n")
            utils.diff_compare(dev3.get_xml_config(), None,
                               "<interface type=\"bridge\">\n"
                               "  <mac address=\"22:22:33:44:55:68\"/>\n"
                               "</interface>\n")
        finally:
            if util and origfunc:
                util.default_bridge = origfunc

    def testCpustrToTuple(self):
        conn = utils.get_conn()
        base = [False] * 16

        expect = base[:]
        expect[1] = expect[2] = expect[3] = True
        self.assertEquals(tuple(expect),
                    virtinst.DomainNumatune.cpuset_str_to_tuple(conn, "1-3"))

        expect = base[:]
        expect[1] = expect[3] = expect[5] = expect[10] = expect[11] = True
        self.assertEquals(tuple(expect),
                    virtinst.DomainNumatune.cpuset_str_to_tuple(conn,
                                                                "1,3,5,10-11"))

        self.assertRaises(ValueError,
                          virtinst.DomainNumatune.cpuset_str_to_tuple,
                          conn, "16")

    def testDiskNumbers(self):
        self.assertEquals("a", VirtualDisk.num_to_target(1))
        self.assertEquals("b", VirtualDisk.num_to_target(2))
        self.assertEquals("z", VirtualDisk.num_to_target(26))
        self.assertEquals("aa", VirtualDisk.num_to_target(27))
        self.assertEquals("ab", VirtualDisk.num_to_target(28))
        self.assertEquals("az", VirtualDisk.num_to_target(52))
        self.assertEquals("ba", VirtualDisk.num_to_target(53))
        self.assertEquals("zz", VirtualDisk.num_to_target(27 * 26))
        self.assertEquals("aaa", VirtualDisk.num_to_target(27 * 26 + 1))

        self.assertEquals(VirtualDisk.target_to_num("hda"), 0)
        self.assertEquals(VirtualDisk.target_to_num("hdb"), 1)
        self.assertEquals(VirtualDisk.target_to_num("sdz"), 25)
        self.assertEquals(VirtualDisk.target_to_num("sdaa"), 26)
        self.assertEquals(VirtualDisk.target_to_num("vdab"), 27)
        self.assertEquals(VirtualDisk.target_to_num("vdaz"), 51)
        self.assertEquals(VirtualDisk.target_to_num("xvdba"), 52)
        self.assertEquals(VirtualDisk.target_to_num("xvdzz"), 26 * (25 + 1) + 25)
        self.assertEquals(VirtualDisk.target_to_num("xvdaaa"), 26 * 26 * 1 + 26 * 1 + 0)

        disk = virtinst.VirtualDisk(utils.get_conn())
        disk.bus = "ide"

        self.assertEquals("hda", disk.generate_target([]))
        self.assertEquals("hdb", disk.generate_target(["hda"]))
        self.assertEquals("hdc", disk.generate_target(["hdb", "sda"]))
        self.assertEquals("hdb", disk.generate_target(["hda", "hdd"]))

        disk.bus = "virtio-scsi"
        self.assertEquals("sdb", disk.generate_target(["sda", "sdg", "sdi"], 0))
        self.assertEquals("sdh", disk.generate_target(["sda", "sdg"], 1))

    def testFedoraTreeinfo(self):
        i = utils.make_distro_installer(
                                location="tests/cli-test-xml/fakefedoratree")
        g = utils.get_basic_fullyvirt_guest(installer=i)
        g.type = "kvm"
        v = i.detect_distro(g)
        self.assertEquals(v, "fedora17")

if __name__ == "__main__":
    unittest.main()

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
import os
import logging

import libvirt
import urlgrabber.progress as progress

import virtinst
from virtinst import VirtualDisk
from virtinst import VirtualAudio
from virtinst import VirtualNetworkInterface
from virtinst import VirtualHostDeviceUSB, VirtualHostDevicePCI
from virtinst import VirtualCharDevice
from virtinst import VirtualVideoDevice
from virtinst import VirtualController
from virtinst import VirtualWatchdog
from virtinst import VirtualInputDevice
from virtinst import VirtualMemballoon
import utils

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

    def tearDown(self):
        if os.path.exists(utils.scratch):
            os.rmdir(utils.scratch)

    def _compare(self, guest, filebase, do_install, do_disk_boot=False,
                 do_create=True):
        filename = filebase and build_xmlfile(filebase) or None

        guest._prepare_install(progress.BaseMeter())
        try:
            actualXML = guest.get_config_xml(install=do_install,
                                             disk_boot=do_disk_boot)

            if filename:
                utils.diff_compare(actualXML, filename)
            if do_create:
                utils.test_create(guest.conn, actualXML)
        finally:
            guest._cleanup_install()

    def _testInstall(self, guest,
                     instxml=None, bootxml=None, contxml=None):
        instname = build_xmlfile(instxml)
        bootname = build_xmlfile(bootxml)
        contname = build_xmlfile(contxml)
        consolecb = None
        meter = None
        removeOld = None
        wait = True
        dom = None

        old_getxml = guest.get_config_xml
        def new_getxml(install=True, disk_boot=False):
            xml = old_getxml(install, disk_boot)
            return utils.sanitize_xml_for_define(xml)
        guest.get_xml_config = new_getxml

        try:
            dom = guest.start_install(consolecb, meter, removeOld, wait)
            dom.destroy()

            # Replace kernel/initrd with known info
            if (guest.installer._install_bootconfig and
                guest.installer._install_bootconfig.kernel):
                guest.installer._install_bootconfig.kernel = "kernel"
                guest.installer._install_bootconfig.initrd = "initrd"

            xmlinst = guest.get_config_xml(True, False)
            xmlboot = guest.get_config_xml(False, False)
            xmlcont = guest.get_config_xml(True, True)

            if instname:
                utils.diff_compare(xmlinst, instname)
            if contname:
                utils.diff_compare(xmlcont, contname)
            if bootname:
                utils.diff_compare(xmlboot, bootname)

            if guest.get_continue_inst():
                guest.continue_install(consolecb, meter, wait)

        finally:
            if dom:
                try:
                    dom.destroy()
                except:
                    pass
                try:
                    dom.undefine()
                except:
                    pass


    def testBootParavirtDiskFile(self):
        g = utils.get_basic_paravirt_guest()
        g.disks.append(utils.get_filedisk("/tmp/somerandomfilename.img"))
        self._compare(g, "boot-paravirt-disk-file", False)

        # Just cram some post_install_checks in here
        try:
            g.post_install_check()
            raise AssertionError("Expected OSError, none caught.")
        except OSError:
            pass

        g.disks[0].path = "virt-install"
        self.assertEquals(g.post_install_check(), False)

        g.disks[0].driver_type = "raw"
        self.assertEquals(g.post_install_check(), False)

        g.disks[0].driver_type = "foobar"
        self.assertEquals(g.post_install_check(), True)

    def testBootParavirtDiskFileBlktapCapable(self):
        oldblktap = virtinst._util.is_blktap_capable
        try:
            virtinst._util.is_blktap_capable = lambda: True
            g = utils.get_basic_paravirt_guest()
            g.disks.append(utils.get_filedisk())
            self._compare(g, "boot-paravirt-disk-drv-tap", False)
        finally:
            virtinst._util.is_blktap_capable = oldblktap

    def testBootParavirtDiskBlock(self):
        g = utils.get_basic_paravirt_guest()
        g.disks.append(utils.get_blkdisk())
        self._compare(g, "boot-paravirt-disk-block", False)

    def testBootParavirtDiskDrvPhy(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_blkdisk()
        disk.driver_name = VirtualDisk.DRIVER_PHY
        g.disks.append(disk)
        self._compare(g, "boot-paravirt-disk-drv-phy", False)

    def testBootParavirtDiskDrvFile(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_FILE
        g.disks.append(disk)
        self._compare(g, "boot-paravirt-disk-drv-file", False)

    def testBootParavirtDiskDrvTap(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_TAP
        g.disks.append(disk)
        self._compare(g, "boot-paravirt-disk-drv-tap", False)

    def testBootParavirtDiskDrvTapQCow(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_TAP
        disk.driver_type = VirtualDisk.DRIVER_TAP_QCOW
        g.disks.append(disk)
        self._compare(g, "boot-paravirt-disk-drv-tap-qcow", False)

    def testBootParavirtManyDisks(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk("/tmp/test2.img")
        disk.driver_name = VirtualDisk.DRIVER_TAP
        disk.driver_type = VirtualDisk.DRIVER_TAP_QCOW

        g.disks.append(utils.get_filedisk("/tmp/test1.img"))
        g.disks.append(disk)
        g.disks.append(utils.get_blkdisk())
        self._compare(g, "boot-paravirt-many-disks", False)

    def testBootFullyvirtDiskFile(self):
        g = utils.get_basic_fullyvirt_guest()
        g.disks.append(utils.get_filedisk())
        self._compare(g, "boot-fullyvirt-disk-file", False)

    def testBootFullyvirtDiskBlock(self):
        g = utils.get_basic_fullyvirt_guest()
        g.disks.append(utils.get_blkdisk())
        self._compare(g, "boot-fullyvirt-disk-block", False)



    def testInstallParavirtDiskFile(self):
        g = utils.get_basic_paravirt_guest()
        g.disks.append(utils.get_filedisk())
        self._compare(g, "install-paravirt-disk-file", True)

    def testInstallParavirtDiskBlock(self):
        g = utils.get_basic_paravirt_guest()
        g.disks.append(utils.get_blkdisk())
        self._compare(g, "install-paravirt-disk-block", True)

    def testInstallParavirtDiskDrvPhy(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_blkdisk()
        disk.driver_name = VirtualDisk.DRIVER_PHY
        g.disks.append(disk)
        self._compare(g, "install-paravirt-disk-drv-phy", True)

    def testInstallParavirtDiskDrvFile(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_FILE
        g.disks.append(disk)
        self._compare(g, "install-paravirt-disk-drv-file", True)

    def testInstallParavirtDiskDrvTap(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_TAP
        g.disks.append(disk)
        self._compare(g, "install-paravirt-disk-drv-tap", True)

    def testInstallParavirtDiskDrvTapQCow(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk()
        disk.driver_name = VirtualDisk.DRIVER_TAP
        disk.driver_type = VirtualDisk.DRIVER_TAP_QCOW
        g.disks.append(disk)
        self._compare(g, "install-paravirt-disk-drv-tap-qcow", True)

    def testInstallParavirtManyDisks(self):
        g = utils.get_basic_paravirt_guest()
        disk = utils.get_filedisk("/tmp/test2.img")
        disk.driver_name = VirtualDisk.DRIVER_TAP
        disk.driver_type = VirtualDisk.DRIVER_TAP_QCOW

        g.disks.append(utils.get_filedisk("/tmp/test1.img"))
        g.disks.append(disk)
        g.disks.append(utils.get_blkdisk())
        self._compare(g, "install-paravirt-many-disks", True)

    def testInstallFullyvirtDiskFile(self):
        g = utils.get_basic_fullyvirt_guest()
        g.disks.append(utils.get_filedisk())
        self._compare(g, "install-fullyvirt-disk-file", True)

    def testInstallFullyvirtDiskBlock(self):
        g = utils.get_basic_fullyvirt_guest()
        g.disks.append(utils.get_blkdisk())
        self._compare(g, "install-fullyvirt-disk-block", True)

    def testInstallFVPXE(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)
        g.disks.append(utils.get_filedisk())
        self._compare(g, "install-fullyvirt-pxe", True)

    def testBootFVPXE(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)
        g.disks.append(utils.get_filedisk())
        self._compare(g, "boot-fullyvirt-pxe", False)

    def testBootFVPXEAlways(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)
        g.disks.append(utils.get_filedisk())

        g.installer.bootconfig.bootorder = [
            g.installer.bootconfig.BOOT_DEVICE_NETWORK]
        g.installer.bootconfig.enable_bootmenu = True

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

    def testDefaultDeviceRemoval(self):
        g = utils.get_basic_fullyvirt_guest()
        g.disks.append(utils.get_filedisk())

        inp = VirtualInputDevice(g.conn)
        cons = VirtualCharDevice.get_dev_instance(g.conn,
                                VirtualCharDevice.DEV_CONSOLE,
                                VirtualCharDevice.CHAR_PTY)
        g.add_device(inp)
        g.add_device(cons)

        g.remove_device(inp)
        g.remove_device(cons)

        self._compare(g, "boot-default-device-removal", False)

    def testOSDeviceDefaultChange(self):
        """
        Make sure device defaults are properly changed if we change OS
        distro/variant mid process
        """
        utils.set_conn(_plainkvm)

        i = utils.make_distro_installer(gtype="kvm")
        g = utils.get_basic_fullyvirt_guest("kvm", installer=i)

        do_install = False
        g.installer.cdrom = True
        g.disks.append(utils.get_floppy())
        g.disks.append(utils.get_filedisk())
        g.disks.append(utils.get_blkdisk())
        g.nics.append(utils.get_virtual_network())

        # Call get_config_xml sets first round of defaults w/o os_variant set
        g.get_xml_config(do_install)

        g.os_variant = "fedora11"
        self._compare(g, "install-f11", do_install)

    def testInstallFVImport(self):
        i = utils.make_import_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        g.disks.append(utils.get_filedisk())
        self._compare(g, "install-fullyvirt-import", False)

    def testInstallFVImportKernel(self):
        i = utils.make_import_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        g.disks.append(utils.get_filedisk())
        g.installer.bootconfig.kernel = "kernel"
        g.installer.bootconfig.initrd = "initrd"
        g.installer.bootconfig.kernel_args = "my kernel args"

        self._compare(g, "install-fullyvirt-import-kernel", False)

    def testInstallFVImportMulti(self):
        i = utils.make_import_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        g.installer.bootconfig.enable_bootmenu = False
        g.installer.bootconfig.bootorder = ["hd", "fd", "cdrom", "network"]
        g.disks.append(utils.get_filedisk())
        self._compare(g, "install-fullyvirt-import-multiboot", False)

    def testInstallPVImport(self):
        i = utils.make_import_installer("xen")
        g = utils.get_basic_paravirt_guest(installer=i)

        g.disks.append(utils.get_filedisk())
        self._compare(g, "install-paravirt-import", False)

    def testQEMUDriverName(self):
        utils.set_conn(_plainkvm)
        g = utils.get_basic_fullyvirt_guest()
        g.disks.append(utils.get_blkdisk())
        self._compare(g, "misc-qemu-driver-name", True)

        g = utils.get_basic_fullyvirt_guest()
        g.disks.append(utils.get_filedisk())
        g.disks.append(utils.get_blkdisk("/iscsi-pool/diskvol1"))
        self._compare(g, "misc-qemu-driver-type", True)

        g = utils.get_basic_fullyvirt_guest()
        g.disks.append(utils.get_filedisk("/default-pool/iso-vol"))
        self._compare(g, "misc-qemu-iso-disk", True)

        g = utils.get_basic_fullyvirt_guest()
        g.disks.append(utils.get_filedisk("/default-pool/iso-vol"))
        g.disks[0].driver_type = "qcow2"
        self._compare(g, "misc-qemu-driver-overwrite", True)

    def testXMLEscaping(self):
        g = utils.get_basic_fullyvirt_guest()
        g.description = "foooo barrrr \n baz && snarf. '' \"\" @@$\n"
        g.disks.append(utils.get_filedisk("/tmp/ISO&'&s"))
        self._compare(g, "misc-xml-escaping", True)

    # OS Type/Version configurations
    def testF10(self):
        utils.set_conn(_plainkvm)
        i = utils.make_pxe_installer(gtype="kvm")
        g = utils.get_basic_fullyvirt_guest("kvm", installer=i)

        g.os_type = "linux"
        g.os_variant = "fedora10"
        g.disks.append(utils.get_filedisk())
        g.disks.append(utils.get_blkdisk())
        g.nics.append(utils.get_virtual_network())
        self._compare(g, "install-f10", True)

    def testF11(self):
        utils.set_conn(_plainkvm)
        i = utils.make_distro_installer(gtype="kvm")
        g = utils.get_basic_fullyvirt_guest("kvm", installer=i)

        g.os_type = "linux"
        g.os_variant = "fedora11"
        g.installer.cdrom = True
        g.disks.append(utils.get_floppy())
        g.disks.append(utils.get_filedisk())
        g.disks.append(utils.get_blkdisk())
        g.nics.append(utils.get_virtual_network())
        self._compare(g, "install-f11", False)

    def testF11AC97(self):
        def build_guest():
            i = utils.make_distro_installer(gtype="kvm")
            g = utils.get_basic_fullyvirt_guest("kvm", installer=i)

            g.os_type = "linux"
            g.os_variant = "fedora11"
            g.installer.cdrom = True
            g.disks.append(utils.get_floppy())
            g.disks.append(utils.get_filedisk())
            g.disks.append(utils.get_blkdisk())
            g.nics.append(utils.get_virtual_network())
            g.add_device(VirtualAudio())
            return g

        utils.set_conn(utils.open_plainkvm(connver=11000))
        g = build_guest()
        self._compare(g, "install-f11-ac97", False)

        oldver = libvirt.getVersion
        try:
            utils.set_conn(utils.open_plainkvm(libver=5000))
            g = build_guest()
            self._compare(g, "install-f11-noac97", False)
        finally:
            libvirt.getVersion = oldver

        utils.set_conn(utils.open_plainkvm(connver=10000))
        g = build_guest()
        self._compare(g, "install-f11-noac97", False)

    def testKVMKeymap(self):
        conn = utils.open_plainkvm(connver=10000)
        g = virtinst.VirtualGraphics(conn=conn, type="vnc")
        self.assertTrue(g.keymap != None)

        conn = utils.open_plainkvm(connver=11000)
        g = virtinst.VirtualGraphics(conn=conn, type="vnc")
        self.assertTrue(g.keymap == None)


    def testF11Qemu(self):
        utils.set_conn(_plainkvm)
        i = utils.make_distro_installer(gtype="qemu")
        g = utils.get_basic_fullyvirt_guest("qemu", installer=i)

        g.os_type = "linux"
        g.os_variant = "fedora11"
        g.installer.cdrom = True
        g.disks.append(utils.get_floppy())
        g.disks.append(utils.get_filedisk())
        g.disks.append(utils.get_blkdisk())
        g.nics.append(utils.get_virtual_network())
        self._compare(g, "install-f11-qemu", False)

    def testF11Xen(self):
        utils.set_conn(_plainxen)
        i = utils.make_distro_installer(gtype="xen")
        g = utils.get_basic_fullyvirt_guest("xen", installer=i)

        g.os_type = "linux"
        g.os_variant = "fedora11"
        g.installer.cdrom = True
        g.disks.append(utils.get_floppy())
        g.disks.append(utils.get_filedisk())
        g.disks.append(utils.get_blkdisk())
        g.nics.append(utils.get_virtual_network())
        self._compare(g, "install-f11-xen", False)

    def testInstallWindowsKVM(self):
        utils.set_conn(_plainkvm)
        g = utils.build_win_kvm("/default-pool/winxp.img")
        self._compare(g, "winxp-kvm-stage1", True)

    def testContinueWindowsKVM(self):
        utils.set_conn(_plainkvm)
        g = utils.build_win_kvm("/default-pool/winxp.img")
        self._compare(g, "winxp-kvm-stage2", True, True)

    def testBootWindowsKVM(self):
        utils.set_conn(_plainkvm)
        g = utils.build_win_kvm("/default-pool/winxp.img")
        self._compare(g, "winxp-kvm-stage3", False)


    def testInstallWindowsXenNew(self):
        def make_guest():
            g = utils.get_basic_fullyvirt_guest("xen")
            g.os_type = "windows"
            g.os_variant = "winxp"
            g.disks.append(utils.get_filedisk())
            g.disks.append(utils.get_blkdisk())
            g.nics.append(utils.get_virtual_network())
            g.add_device(VirtualAudio())
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

        g.disks.append(utils.get_filedisk())
        g.disks.append(utils.get_blkdisk())
        g.disks.append(VirtualDisk(conn=g.conn, path="/dev/loop0",
                                   device=VirtualDisk.DEVICE_CDROM,
                                   driverType="raw"))
        g.disks.append(VirtualDisk(conn=g.conn, path="/dev/loop0",
                                   device=VirtualDisk.DEVICE_DISK,
                                   driverName="qemu", format="qcow2"))
        g.disks.append(VirtualDisk(conn=g.conn, path=None,
                                   device=VirtualDisk.DEVICE_CDROM,
                                   bus="scsi"))
        g.disks.append(VirtualDisk(conn=g.conn, path=None,
                                   device=VirtualDisk.DEVICE_FLOPPY))
        g.disks.append(VirtualDisk(conn=g.conn, path="/dev/loop0",
                                   device=VirtualDisk.DEVICE_FLOPPY,
                                   driverName="phy", driverCache="none"))
        disk = VirtualDisk(conn=g.conn, path="/dev/loop0",
                           bus="virtio", driverName="qemu",
                           driverType="qcow2", driverCache="none")
        disk.driver_io = "threads"
        g.disks.append(disk)

        self._compare(g, "boot-many-disks2", False)

    def testManyNICs(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        net1 = VirtualNetworkInterface(type="user",
                                       macaddr="22:11:11:11:11:11")
        net2 = utils.get_virtual_network()
        net3 = utils.get_virtual_network()
        net3.model = "e1000"
        net4 = VirtualNetworkInterface(bridge="foobr0",
                                       macaddr="22:22:22:22:22:22")
        net4.target_dev = "foo1"
        net5 = VirtualNetworkInterface(type="ethernet",
                                       macaddr="00:11:00:22:00:33")
        net5.source_dev = "testeth1"

        g.nics.append(net1)
        g.nics.append(net2)
        g.nics.append(net3)
        g.nics.append(net4)
        g.nics.append(net5)
        self._compare(g, "boot-many-nics", False)

    def testManyHostdevs(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        dev1 = VirtualHostDeviceUSB(g.conn)
        dev1.product = "0x1234"
        dev1.vendor = "0x4321"

        dev2 = VirtualHostDevicePCI(g.conn)
        dev2.bus = "0x11"
        dev2.slot = "0x2"
        dev2.function = "0x3"

        g.hostdevs.append(dev1)
        g.hostdevs.append(dev2)
        self._compare(g, "boot-many-hostdevs", False)

    def testManySounds(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        g.sound_devs.append(VirtualAudio("sb16", conn=g.conn))
        g.sound_devs.append(VirtualAudio("es1370", conn=g.conn))
        g.sound_devs.append(VirtualAudio("pcspk", conn=g.conn))
        g.sound_devs.append(VirtualAudio(conn=g.conn))

        self._compare(g, "boot-many-sounds", False)

    def testManyChars(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        dev1 = VirtualCharDevice.get_dev_instance(g.conn,
                                                  VirtualCharDevice.DEV_SERIAL,
                                                  VirtualCharDevice.CHAR_NULL)
        dev2 = VirtualCharDevice.get_dev_instance(g.conn,
                                                  VirtualCharDevice.DEV_PARALLEL,
                                                  VirtualCharDevice.CHAR_UNIX)
        dev2.source_path = "/tmp/foobar"
        dev3 = VirtualCharDevice.get_dev_instance(g.conn,
                                                  VirtualCharDevice.DEV_SERIAL,
                                                  VirtualCharDevice.CHAR_TCP)
        dev3.protocol = "telnet"
        dev3.source_host = "my.source.host"
        dev3.source_port = "1234"
        dev4 = VirtualCharDevice.get_dev_instance(g.conn,
                                                  VirtualCharDevice.DEV_PARALLEL,
                                                  VirtualCharDevice.CHAR_UDP)
        dev4.bind_host = "my.bind.host"
        dev4.bind_port = "1111"
        dev4.source_host = "my.source.host"
        dev4.source_port = "2222"

        dev5 = VirtualCharDevice.get_dev_instance(g.conn,
                                                  VirtualCharDevice.DEV_CHANNEL,
                                                  VirtualCharDevice.CHAR_PTY)
        dev5.target_type = dev5.CHAR_CHANNEL_TARGET_VIRTIO
        dev5.target_name = "foo.bar.frob"

        dev6 = VirtualCharDevice.get_dev_instance(g.conn,
                                                  VirtualCharDevice.DEV_CONSOLE,
                                                  VirtualCharDevice.CHAR_PTY)

        dev7 = VirtualCharDevice.get_dev_instance(g.conn,
                                                  VirtualCharDevice.DEV_CONSOLE,
                                                  VirtualCharDevice.CHAR_PTY)
        dev7.target_type = dev5.CHAR_CONSOLE_TARGET_VIRTIO

        dev8 = VirtualCharDevice.get_dev_instance(g.conn,
                                                  VirtualCharDevice.DEV_CHANNEL,
                                                  VirtualCharDevice.CHAR_PTY)
        dev8.target_type = dev5.CHAR_CHANNEL_TARGET_GUESTFWD
        dev8.target_address = "1.2.3.4"
        dev8.target_port = "4567"

        g.add_device(dev1)
        g.add_device(dev2)
        g.add_device(dev3)
        g.add_device(dev4)
        g.add_device(dev5)
        g.add_device(dev6)
        g.add_device(dev7)
        g.add_device(dev8)
        self._compare(g, "boot-many-chars", False)

    def testManyDevices(self):
        i = utils.make_pxe_installer()
        g = utils.get_basic_fullyvirt_guest(installer=i)

        g.description = "foooo barrrr somedesc"
        g.hugepage = True

        # Hostdevs
        dev1 = VirtualHostDeviceUSB(g.conn)
        dev1.product = "0x1234"
        dev1.vendor = "0x4321"
        g.hostdevs.append(dev1)

        # Sound devices
        g.sound_devs.append(VirtualAudio("sb16", conn=g.conn))
        g.sound_devs.append(VirtualAudio("es1370", conn=g.conn))

        # Disk devices
        g.disks.append(VirtualDisk(conn=g.conn, path="/dev/loop0",
                                   device=VirtualDisk.DEVICE_FLOPPY))
        g.disks.append(VirtualDisk(conn=g.conn, path="/dev/loop0",
                                   bus="scsi"))
        g.disks.append(VirtualDisk(conn=g.conn, path="/tmp", device="floppy"))
        d3 = VirtualDisk(conn=g.conn, path="/default-pool/testvol1.img",
                         bus="scsi", driverName="qemu")
        d3.address.type = "spapr-vio"
        g.disks.append(d3)

        # Controller devices
        c1 = VirtualController.get_class_for_type(VirtualController.CONTROLLER_TYPE_IDE)(g.conn)
        c1.index = "3"
        c2 = VirtualController.get_class_for_type(VirtualController.CONTROLLER_TYPE_VIRTIOSERIAL)(g.conn)
        c2.ports = "32"
        c2.vectors = "17"
        g.add_device(c1)
        g.add_device(c2)

        # Network devices
        net1 = utils.get_virtual_network()
        net1.model = "e1000"
        net2 = VirtualNetworkInterface(type="user",
                                       macaddr="22:11:11:11:11:11")
        net3 = VirtualNetworkInterface(type=virtinst.VirtualNetworkInterface.TYPE_VIRTUAL,
                                       macaddr="22:22:22:22:22:22", network="default")
        net3.model = "spapr-vlan"
        net3.set_address("spapr-vio")
        g.nics.append(net1)
        g.nics.append(net2)
        g.nics.append(net3)

        # Character devices
        cdev1 = VirtualCharDevice.get_dev_instance(g.conn,
                                                   VirtualCharDevice.DEV_SERIAL,
                                                   VirtualCharDevice.CHAR_NULL)
        cdev2 = VirtualCharDevice.get_dev_instance(g.conn,
                                                   VirtualCharDevice.DEV_PARALLEL,
                                                   VirtualCharDevice.CHAR_UNIX)
        cdev2.source_path = "/tmp/foobar"
        cdev3 = VirtualCharDevice.get_dev_instance(g.conn,
                                                   VirtualCharDevice.DEV_CHANNEL,
                                                   VirtualCharDevice.CHAR_SPICEVMC)
        g.add_device(cdev1)
        g.add_device(cdev2)
        g.add_device(cdev3)

        # Video Devices
        vdev1 = VirtualVideoDevice(g.conn)
        vdev1.model_type = "vmvga"

        vdev2 = VirtualVideoDevice(g.conn)
        vdev2.model_type = "cirrus"
        vdev2.vram = 10 * 1024
        vdev2.heads = 3

        vdev3 = VirtualVideoDevice(g.conn)
        vdev4 = VirtualVideoDevice(g.conn)
        vdev4.model_type = "qxl"

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
        gdev1 = virtinst.VirtualGraphics(conn=g.conn, type="vnc")
        self.assertTrue(gdev1.keymap != None)
        gdev1.keymap = "en-us"

        # Check keymap None
        gdev2 = virtinst.VirtualGraphics(conn=g.conn, type="vnc")
        gdev2.keymap = None

        gdev3 = virtinst.VirtualGraphics(conn=g.conn, type="sdl")
        gdev4 = virtinst.VirtualGraphics(conn=g.conn, type="spice")
        gdev4.passwdValidTo = "foobar"

        gdev5 = virtinst.VirtualGraphics(conn=g.conn, type="sdl")
        gdev5.xauth = "fooxauth"
        gdev5.display = "foodisplay"
        g.add_device(gdev1)
        g.add_device(gdev2)
        g.add_device(gdev3)
        g.add_device(gdev4)
        g.add_device(gdev5)

        g.clock.offset = "localtime"

        g.seclabel.type = g.seclabel.SECLABEL_TYPE_STATIC
        g.seclabel.model = "selinux"
        g.seclabel.label = "foolabel"
        g.seclabel.imagelabel = "imagelabel"

        self._compare(g, "boot-many-devices", False)

    def testCpuset(self):
        normaltest = libvirt.open("test:///default")
        utils.set_conn(normaltest)
        g = utils.get_basic_fullyvirt_guest()

        # Cpuset
        cpustr = g.generate_cpuset(g.conn, g.memory)
        g.cpuset = cpustr
        g.maxvcpus = 7

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

        g.add_usb_ich9_controllers()

        self._compare(g, "boot-usb2", False)

    #
    # Full Install tests: try to mimic virt-install as much as possible
    #

    def testFullKVMRHEL6(self):
        utils.set_conn(_plainkvm)
        i = utils.make_distro_installer(
                                  location="tests/cli-test-xml/fakerhel6tree",
                                  gtype="kvm")
        g = utils.get_basic_fullyvirt_guest("kvm", installer=i)
        g.disks.append(utils.get_floppy())
        g.disks.append(utils.get_filedisk("/default-pool/rhel6.img"))
        g.disks.append(utils.get_blkdisk())
        g.nics.append(utils.get_virtual_network())
        g.add_device(VirtualAudio())
        g.add_device(VirtualVideoDevice(g.conn))
        g.os_autodetect = True

        # Do this ugly hack to make sure the test doesn't try and use vol
        # upload
        origscratch = getattr(i, "_get_system_scratchdir")
        try:
            setattr(i, "_get_system_scratchdir",
                    lambda: i.scratchdir)
            self._testInstall(g, "rhel6-kvm-stage1", "rhel6-kvm-stage2")
        finally:
            setattr(i, "_get_system_scratchdir", origscratch)

    def testFullKVMWinxp(self):
        utils.set_conn(_plainkvm)
        g = utils.build_win_kvm("/default-pool/winxp.img")
        self._testInstall(g, "winxp-kvm-stage1",
                          "winxp-kvm-stage3", "winxp-kvm-stage2")

    def testCreateDisk(self):
        """
        Doesn't really belong here, but what the hell :)
        """
        path = "/tmp/__virtinst_create_test__.img"
        sizegigs = .001
        sizebytes = long(sizegigs * 1024L * 1024L * 1024L)

        for sparse in [True, False]:
            disk = VirtualDisk(conn=utils.get_conn(), path=path, size=sizegigs,
                               sparse=sparse)
            disk.setup()

            actualsize = long(os.path.getsize(path))
            os.unlink(path)
            self.assertEquals(sizebytes, actualsize)

    def testDefaultBridge(self):
        origfunc = None
        util = None
        try:
            i = utils.make_pxe_installer()
            g = utils.get_basic_fullyvirt_guest(installer=i)
            util = getattr(virtinst, "_util")
            origfunc = util.default_bridge2

            def newbridge(ignore_conn):
                return ["bridge", "br0"]
            util.default_bridge2 = newbridge

            dev1 = virtinst.VirtualNetworkInterface(conn=g.conn)
            dev1.macaddr = "22:22:33:44:55:66"
            g.add_device(dev1)

            dev2 = virtinst.VirtualNetworkInterface(conn=g.conn,
                                                parsexml=dev1.get_xml_config())
            dev2.source = None
            dev2.source = "foobr0"
            dev2.macaddr = "22:22:33:44:55:67"
            g.add_device(dev2)

            dev3 = virtinst.VirtualNetworkInterface(conn=g.conn,
                                                parsexml=dev1.get_xml_config())
            dev3.source = None
            dev3.macaddr = "22:22:33:44:55:68"
            g.add_device(dev3)

            self._compare(g, "boot-default-bridge", False, do_create=False)
            dev3.type = dev3.TYPE_USER
            self._compare(g, None, False)
        finally:
            if util and origfunc:
                util.default_bridge2 = origfunc

    def testCpustrToTuple(self):
        conn = utils.get_conn()
        base = [False] * 16

        expect = base[:]
        expect[1] = expect[2] = expect[3] = True
        self.assertEquals(tuple(expect),
                          virtinst.Guest.cpuset_str_to_tuple(conn, "1-3"))

        expect = base[:]
        expect[1] = expect[3] = expect[5] = expect[10] = expect[11] = True
        self.assertEquals(tuple(expect),
                    virtinst.Guest.cpuset_str_to_tuple(conn, "1,3,5,10-11"))

        self.assertRaises(ValueError,
                          virtinst.Guest.cpuset_str_to_tuple,
                          conn, "16")

    def testManyVirtio(self):
        d = VirtualDisk(conn=utils.get_conn(), bus="virtio",
                        path="/default-pool/testvol1.img")

        targetlist = []
        for ignore in range(0, (26 * 2) + 1):
            d.target = None
            d.generate_target(targetlist)
            targetlist.append(d.target)

        self.assertEquals("vdaa", targetlist[26])
        self.assertEquals("vdba", targetlist[26 * 2])

    def testFedoraTreeinfo(self):
        i = utils.make_distro_installer(
                                location="tests/cli-test-xml/fakefedoratree",
                                gtype="kvm")
        t, v = i.detect_distro()
        self.assertEquals((t, v), ("linux", "fedora17"))

if __name__ == "__main__":
    unittest.main()

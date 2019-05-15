# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import atexit
from distutils.spawn import find_executable
import io
import logging
import os
import shlex
import shutil
import sys
import traceback
import unittest

try:
    import argcomplete
except ImportError:
    argcomplete = None

from tests import virtinstall, virtclone, virtconvert, virtxml
from tests import utils

os.environ["LANG"] = "en_US.UTF-8"
os.environ["HOME"] = "/tmp"
os.environ["DISPLAY"] = ":3.4"

TMP_IMAGE_DIR = "/tmp/__virtinst_cli_"
XMLDIR = "tests/cli-test-xml"
OLD_OSINFO = utils.has_old_osinfo()
HAS_ISOINFO = find_executable("isoinfo")

# Images that will be created by virt-install/virt-clone, and removed before
# each run
new_images = [
    TMP_IMAGE_DIR + "new1.img",
    TMP_IMAGE_DIR + "new2.img",
    TMP_IMAGE_DIR + "new3.img",
    TMP_IMAGE_DIR + "exist1-clone.img",
    TMP_IMAGE_DIR + "exist2-clone.img",
]

# Images that are expected to exist before a command is run
exist_images = [
    TMP_IMAGE_DIR + "exist1.img",
    TMP_IMAGE_DIR + "exist2.img",
]

iso_links = [
    "/tmp/fake-fedora17-tree.iso",
    "/tmp/fake-centos65-label.iso",
    "/tmp/fake-no-osinfo.iso",
]

exist_files = exist_images
new_files   = new_images
clean_files = (new_images + exist_images + iso_links)

test_files = {
    'URI-TEST-FULL': utils.URIs.test_full,
    'URI-TEST-REMOTE': utils.URIs.test_remote,
    'URI-KVM': utils.URIs.kvm,
    'URI-KVM-ARMV7L': utils.URIs.kvm_armv7l,
    'URI-KVM-AARCH64': utils.URIs.kvm_aarch64,
    'URI-KVM-PPC64LE': utils.URIs.kvm_ppc64le,
    'URI-KVM-S390X': utils.URIs.kvm_s390x,
    'URI-QEMU-RISCV64': utils.URIs.qemu_riscv64,

    'NEWIMG1': "/dev/default-pool/new1.img",
    'NEWIMG2': "/dev/default-pool/new2.img",
    'NEWCLONEIMG1': new_images[0],
    'NEWCLONEIMG2': new_images[1],
    'NEWCLONEIMG3': new_images[2],
    'EXISTIMG1': "/dev/default-pool/testvol1.img",
    'EXISTIMG2': "/dev/default-pool/testvol2.img",
    'EXISTIMG3': exist_images[0],
    'EXISTIMG4': exist_images[1],
    'ISOTREE': iso_links[0],
    'ISOLABEL': iso_links[1],
    'ISO-NO-OS': iso_links[2],
    'TREEDIR': "%s/fakefedoratree" % XMLDIR,
    'COLLIDE': "/dev/default-pool/collidevol1.img",
}


def has_old_osinfo():
    if OLD_OSINFO:
        return "osinfo is too old"


def missing_isoinfo():
    if not HAS_ISOINFO:
        return "isoinfo not installed"


######################
# Test class helpers #
######################

class Command(object):
    """
    Instance of a single cli command to test
    """
    def __init__(self, cmd):
        self.cmdstr = cmd % test_files
        self.check_success = True
        self.compare_file = None
        self.input_file = None

        self.need_conn = True
        self.skip_cb = None
        self.check_version = None
        self.grep = None
        self.nogrep = None

        app, opts = self.cmdstr.split(" ", 1)
        self.app = app
        self.argv = [os.path.abspath(app)] + shlex.split(opts)
        self.env = None

    def _launch_command(self, conn):
        logging.debug(self.cmdstr)

        app = self.argv[0]

        oldenv = None
        oldstdout = sys.stdout
        oldstderr = sys.stderr
        oldstdin = sys.stdin
        oldargv = sys.argv
        try:
            if self.env:
                oldenv = os.environ.copy()
                os.environ.update(self.env)

            out = io.StringIO()

            sys.stdout = out
            sys.stderr = out
            sys.argv = self.argv
            if self.input_file:
                sys.stdin = open(self.input_file)

            exc = ""
            try:
                if "virt-install" in app:
                    ret = virtinstall.main(conn=conn)
                elif "virt-clone" in app:
                    ret = virtclone.main(conn=conn)
                elif "virt-convert" in app:
                    ret = virtconvert.main(conn=conn)
                elif "virt-xml" in app:
                    ret = virtxml.main(conn=conn)
            except SystemExit as sys_e:
                ret = sys_e.code
            except Exception:
                ret = -1
                exc = "\n" + "".join(traceback.format_exc())

            if ret != 0:
                ret = -1
            outt = out.getvalue() + exc
            if outt.endswith("\n"):
                outt = outt[:-1]
            return (ret, outt)
        finally:
            sys.stdout = oldstdout
            sys.stderr = oldstderr
            sys.stdin = oldstdin
            sys.argv = oldargv
            if oldenv:
                os.environ = oldenv


    def _get_output(self, conn):
        try:
            for i in new_files:
                if os.path.isdir(i):
                    shutil.rmtree(i)
                elif os.path.exists(i):
                    os.unlink(i)

            code, output = self._launch_command(conn)

            logging.debug("%s\n", output)
            return code, output
        except Exception as e:
            return (-1, "".join(traceback.format_exc()) + str(e))

    def _check_support(self, tests, conn, check, skipmsg):
        if check is None:
            return
        if conn is None:
            raise RuntimeError("skip check is not None, but conn is None")
        # pylint: disable=protected-access
        if conn._check_version(check):
            return

        tests.skipTest(skipmsg)
        return True

    def _check_compare_file(self, conn, tests, output):
        if self._check_support(tests, conn, self.check_version,
                "Skipping compare check due to lack of support"):
            return

        # Generate test files that don't exist yet
        filename = self.compare_file
        if (utils.clistate.regenerate_output or
            not os.path.exists(filename)):
            open(filename, "w").write(output)

        if "--print-diff" in self.argv and output.count("\n") > 3:
            # 1) Strip header
            # 2) Simplify context lines to reduce churn when
            #    libvirt or testdriver changes
            newlines = []
            for line in output.splitlines()[3:]:
                if line.startswith("@@"):
                    line = "@@"
                newlines.append(line)
            output = "\n".join(newlines)

        utils.diff_compare(output, filename)

        # Define the <domain>s generated for compare output, to ensure
        # we are generating valid XML
        if "--print-xml" in self.argv or "--print-step" in self.argv:
            for domxml in output.split("</domain>"):
                if "<domain" not in domxml:
                    continue
                domxml = domxml + "</domain>"
                try:
                    dom = conn.defineXML(domxml)
                    dom.undefine()
                except Exception as e:
                    raise AssertionError("Bad XML:\n%s\n\nError was: %s: %s" %
                            (domxml, e.__class__.__name__, str(e)))

    def _run(self, tests):
        conn = None
        for idx in reversed(range(len(self.argv))):
            if self.argv[idx] == "--connect":
                conn = utils.URIs.openconn(self.argv[idx + 1])
                break

        if not conn and self.need_conn:
            raise RuntimeError("couldn't parse URI from command %s" %
                               self.argv)

        if self.skip_cb and self.skip_cb():
            tests.skipTest("skip_cb: %s" % self.skip_cb())
            return

        code, output = self._get_output(conn)

        def _raise_error(_msg):
            raise AssertionError(
                ("Command was: %s\n" % self.cmdstr) +
                ("Error code : %d\n" % code) +
                ("Output was:\n%s" % output) +
                ("\n\n\nTESTSUITE: " + _msg + "\n"))


        if bool(code) == self.check_success:
            _raise_error("Expected command to %s, but it didn't.\n" %
                 (self.check_success and "pass" or "fail"))

        if self.grep and self.grep not in output:
            _raise_error("Didn't find grep=%s" % self.grep)
        if self.nogrep and self.nogrep in output:
            _raise_error("Found grep=%s when we shouldn't see it" %
                    self.nogrep)

        if self.compare_file:
            self._check_compare_file(conn, tests, output)

    def run(self, tests):
        err = None

        try:
            self._run(tests)
        except AssertionError as e:
            err = self.cmdstr + "\n" + str(e)
        if err:
            tests.fail(err)


class _CategoryProxy(object):
    def __init__(self, app, name, default_args, skip_cb, check_version):
        self._app = app
        self._name = name

        self.default_args = default_args
        self.skip_cb = skip_cb
        self.check_version = check_version

    def add_valid(self, *args, **kwargs):
        return self._app.add_valid(self._name, *args, **kwargs)
    def add_invalid(self, *args, **kwargs):
        return self._app.add_invalid(self._name, *args, **kwargs)
    def add_compare(self, *args, **kwargs):
        return self._app.add_compare(self._name, *args, **kwargs)


class App(object):
    def __init__(self, appname, uri=None, check_version=None):
        self.appname = appname
        self.categories = {}
        self.cmds = []
        self.check_version = check_version
        self.uri = uri

    def _default_args(self, cli, iscompare, auto_printarg):
        args = ""
        if not iscompare:
            args = "--debug"

        if "--connect " not in cli:
            uri = self.uri or utils.URIs.test_suite
            args += " --connect %s" % uri

        if self.appname in ["virt-install"]:
            if "--name " not in cli:
                args += " --name foobar"
            if "--ram " not in cli:
                args += " --ram 64"

        if iscompare and auto_printarg:
            if self.appname == "virt-install":
                if ("--print-xml" not in cli and
                    "--print-step" not in cli and
                    "--quiet" not in cli):
                    args += " --print-step all"

            elif self.appname == "virt-clone":
                if "--print-xml" not in cli:
                    args += " --print-xml"

        return args


    def add_category(self, catname, default_args,
                     skip_cb=None, check_version=None):
        obj = _CategoryProxy(self, catname, default_args,
                             skip_cb, check_version)
        self.categories[catname] = obj
        return obj

    def _add(self, catname, testargs, valid, compfile,
             skip_cb=None, check_version=None, input_file=None,
             auto_printarg=True, grep=None):

        category = self.categories[catname]
        args = category.default_args + " " + testargs
        args = (self._default_args(args, bool(compfile), auto_printarg) +
            " " + args)
        cmdstr = "./%s %s" % (self.appname, args)

        cmd = Command(cmdstr)
        cmd.check_success = valid
        if compfile:
            compfile = os.path.basename(self.appname) + "-" + compfile
            compare_XMLDIR = "%s/compare" % XMLDIR
            cmd.compare_file = "%s/%s.xml" % (compare_XMLDIR, compfile)
        cmd.skip_cb = skip_cb or category.skip_cb
        cmd.check_version = (check_version or
                             category.check_version or
                             self.check_version)
        cmd.input_file = input_file
        cmd.grep = grep
        self.cmds.append(cmd)

    def add_valid(self, cat, args, **kwargs):
        self._add(cat, args, True, None, **kwargs)
    def add_invalid(self, cat, args, **kwargs):
        self._add(cat, args, False, None, **kwargs)
    def add_compare(self, cat, args, compfile, **kwargs):
        self._add(cat, args, not compfile.endswith("-fail"),
                  compfile, **kwargs)



#
# The test matrix
#
# add_valid: A test that should pass
# add_invalid: A test that should fail
# add_compare: Get the generated XML, and compare against the passed filename
#              in tests/clitest-xml/compare/
#

######################
# virt-install tests #
######################

vinst = App("virt-install")

#############################################
# virt-install verbose XML comparison tests #
#############################################

c = vinst.add_category("xml-comparsion", "--connect %(URI-KVM)s --noautoconsole --os-variant fedora-unknown", skip_cb=has_old_osinfo)

# Singleton element test #1, for simpler strings
c.add_compare("""
--memory 1024
--vcpus 4,cores=2,threads=2,sockets=2 --cpuset=1,3-5
--cpu host-copy
--description \"foobar & baz\"
--boot uefi,smbios_mode=emulate,boot1.dev=hd,boot.dev=network,initarg1=bar=baz,initarg=foo
--security type=dynamic
--security type=none,model=dac
--numatune 1,2,3,5-7,^6
--memorybacking hugepages=on
--features apic=off
--clock offset=localtime
--resource /virtualmachines/production
--events on_crash=restart
--metadata genid_enable=yes

--disk none
--console none
--channel none
--network none
--controller usb2
--graphics spice
--video vga
--sound none
--redirdev none
--memballoon none
--smartcard none
--watchdog default
--tpm /dev/tpm0
--rng /dev/random
""", "singleton-config-1")

# Singleton element test #2, for complex strings
c.add_compare("""--pxe
--memory 512,maxmemory=1024
--vcpus 9
--cpu foobar,+x2apic,+x2apicagain,-distest,forbid=foo,forbid=bar,disable=distest2,optional=opttest,require=reqtest,match=strict,vendor=meee,\
cell.id=0,cell.cpus=1,2,3,cell.memory=1024,\
cell1.id=1,cell1.memory=256,cell1.cpus=5-8,\
numa.cell2.id=2,numa.cell2.memory=256,numa.cell2.cpus=4,\
cell0.distances.sibling0.id=0,cell0.distances.sibling0.value=10,\
cell0.distances.sibling1.id=1,cell0.distances.sibling1.value=21,\
cell1.distances.sibling0.id=0,cell1.distances.sibling0.value=21,\
cell1.distances.sibling1.id=1,cell1.distances.sibling1.value=10,\
cache.mode=emulate,cache.level=3
--cputune vcpupin0.vcpu=0,vcpupin0.cpuset=0-3
--metadata title=my-title,description=my-description,uuid=00000000-1111-2222-3333-444444444444,genid=e9392370-2917-565e-692b-d057f46512d6
--boot cdrom,fd,hd,network,menu=off,loader=/foo/bar,emulator=/new/emu,bootloader=/new/bootld,rebootTimeout=3,initargs="foo=bar baz=woo"
--idmap uid_start=0,uid_target=1000,uid_count=10,gid_start=0,gid_target=1000,gid_count=10
--security type=static,label='system_u:object_r:svirt_image_t:s0:c100,c200',relabel=yes,baselabel=baselabel
--numatune 1-3,4,mode=strict
--memtune hard_limit=10,soft_limit=20,swap_hard_limit=30,min_guarantee=40
--blkiotune weight=100,device_path=/home/test/1.img,device_weight=200
--memorybacking size=1,unit='G',nodeset=0,1,nosharepages=yes,locked=yes,discard=yes,allocation.mode=ondemand,access_mode=shared,source_type=anonymous,hugepages.page.size=12,hugepages.page1.size=1234,hugepages.page1.unit=MB,hugepages.page1.nodeset=2
--features acpi=off,eoi=on,privnet=on,hyperv_synic=on,hyperv_reset=on,hyperv_spinlocks=on,hyperv_spinlocks_retries=5678,vmport=off,pmu=off,vmcoreinfo=on
--clock offset=utc,hpet_present=no,rtc_tickpolicy=merge,timer2.name=hypervclock,timer3.name=pit,timer1.present=yes,timer3.tickpolicy=delay,timer2.present=no
--sysinfo type=smbios,bios_vendor="Acme LLC",bios_version=1.2.3,bios_date=01/01/1970,bios_release=10.22
--sysinfo type=smbios,system_manufacturer="Acme Inc.",system_product=Computer,system_version=3.2.1,system_serial=123456789,system_uuid=00000000-1111-2222-3333-444444444444,system_sku=abc-123,system_family=Server
--sysinfo type=smbios,baseBoard_manufacturer="Acme Corp.",baseBoard_product=Motherboard,baseBoard_version=A01,baseBoard_serial=1234-5678,baseBoard_asset=Tag,baseBoard_location=Chassis
--sysinfo type=smbios,chassis.manufacturer="Chassis Corp.",chassis.serial=1234chassis,chassis.asset=chasset,chassis.sku=chassku,chassis.version=4.0
--sysinfo type=smbios,oemStrings.entry2="complicated parsing, foo=bar",oemStrings.entry1=test1,oemStrings.entry0=test0
--pm suspend_to_mem=yes,suspend_to_disk=no
--resource partition=/virtualmachines/production
--events on_poweroff=destroy,on_reboot=restart,on_crash=preserve,on_lockfailure=ignore

--controller usb3
--controller scsi,model=virtio-scsi
--graphics vnc
--filesystem /foo/source,/bar/target
--memballoon virtio
--watchdog ib700,action=pause
--tpm passthrough,model=tpm-crb,path=/dev/tpm0
--rng egd,backend_host=127.0.0.1,backend_service=8000,backend_type=udp,backend_mode=bind,backend_connect_host=foo,backend_connect_service=708
--panic iobase=0x506
""", "singleton-config-2")


# Test the implied defaults for gl=yes setting virgl=on
c.add_compare("""
--memory 1024
--disk none
--boot bios.useserial=no,bios.rebootTimeout=60,cmdline=root=/foo,smbios.mode=host,bootmenu.enable=yes,loader_ro=yes,loader.type=rom,loader=/tmp/foo
--memorybacking access.mode=shared,source.type=anonymous,hugepages=on
--graphics spice,gl=yes
--rng egd,backend.type=nmdm,backend.source.master=/dev/foo1,backend.source.slave=/dev/foo2
--panic default,,address.type=isa,address.iobase=0x500,address.irq=5
--cpu topology.sockets=1,topology.cores=3,topology.threads=2
--vsock auto_cid=on
""", "singleton-config-3")



c.add_compare("""
--vcpus 4,cores=1,placement=static,\
vcpus.vcpu2.id=0,vcpus.vcpu2.enabled=no,\
vcpus.vcpu3.id=1,vcpus.vcpu3.hotpluggable=no,vcpus.vcpu3.enabled=yes,\
vcpus.vcpu.id=3,vcpus.vcpu0.enabled=yes,vcpus.vcpu0.order=3,\
vcpus.vcpu1.id=2,vcpus.vcpu1.enabled=yes
--cpu none

--disk /dev/default-pool/UPPER,cache=writeback,io=threads,perms=sh,serial=WD-WMAP9A966149,boot_order=2
--disk %(NEWIMG1)s,sparse=false,size=.001,perms=ro,error_policy=enospace,discard=unmap,detect_zeroes=unmap
--disk device=cdrom,bus=sata,read_bytes_sec=1,read_iops_sec=2,write_bytes_sec=5,write_iops_sec=6,driver.copy_on_read=on,geometry.cyls=16383,geometry.heads=16,geometry.secs=63,geometry.trans=lba
--disk size=1
--disk /iscsi-pool/diskvol1,total_bytes_sec=10,total_iops_sec=20
--disk /dev/default-pool/iso-vol,seclabel.model=dac,seclabel1.model=selinux,seclabel1.relabel=no,seclabel0.label=foo,bar,baz
--disk /dev/default-pool/iso-vol,format=qcow2,startup_policy=optional
--disk source_pool=rbd-ceph,source_volume=some-rbd-vol,size=.1,driver_type=raw
--disk pool=rbd-ceph,size=.1
--disk source_protocol=http,source_host_name=example.com,source_host_port=8000,source_name=/path/to/my/file
--disk source_protocol=nbd,source_host_transport=unix,source_host_socket=/tmp/socket,bus=scsi,logical_block_size=512,physical_block_size=512
--disk gluster://192.168.1.100/test-volume/some/dir/test-gluster.qcow2
--disk nbd+unix:///var/foo/bar/socket,bus=usb,removable=on
--disk path=http://[1:2:3:4:1:2:3:4]:5522/my/path?query=foo
--disk vol=gluster-pool/test-gluster.raw
--disk /var,device=floppy
--disk %(NEWIMG2)s,size=1,backing_store=/tmp/foo.img,backing_format=vmdk
--disk /tmp/brand-new.img,size=1,backing_store=/dev/default-pool/iso-vol,boot.order=10,boot.loadparm=5
--disk path=/dev/disk-pool/diskvol7,device=lun,bus=scsi,reservations.managed=no,reservations.source.type=unix,reservations.source.path=/var/run/test/pr-helper0.sock,reservations.source.mode=client

--network user,mac=12:34:56:78:11:22,portgroup=foo,link_state=down,rom_bar=on,rom_file=/tmp/foo
--network bridge=foobar,model=virtio,driver_name=qemu,driver_queues=3
--network bridge=ovsbr,virtualport_type=openvswitch,virtualport_profileid=demo,virtualport_interfaceid=09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b,link_state=yes
--network type=direct,source=eth5,source_mode=vepa,target=mytap12,virtualport_type=802.1Qbg,virtualport_managerid=12,virtualport_typeid=1193046,virtualport_typeidversion=1,virtualport_instanceid=09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b,boot_order=1,trustGuestRxFilters=yes,mtu.size=1500
--network user,model=virtio,address.type=spapr-vio,address.reg=0x500
--network vhostuser,source_type=unix,source_path=/tmp/vhost1.sock,source_mode=server,model=virtio
--network user,address.type=ccw,address.cssid=0xfe,address.ssid=0,address.devno=01,boot.order=15,boot.loadparm=SYSTEM1

--graphics sdl
--graphics spice,keymap=none
--graphics vnc,port=5950,listen=1.2.3.4,keymap=ja,password=foo
--graphics spice,port=5950,tlsport=5950,listen=1.2.3.4,keymap=ja
--graphics spice,image_compression=glz,streaming_mode=filter,clipboard_copypaste=yes,mouse_mode=client,filetransfer_enable=on
--graphics spice,gl=yes,listen=socket
--graphics spice,gl=yes,listen=none
--graphics spice,gl=yes,listen=none,rendernode=/dev/dri/foo
--graphics spice,listens0.type=address,listens0.address=1.2.3.4
--graphics spice,listens0.type=network,listens0.network=default
--graphics spice,listens0.type=socket,listens0.socket=/tmp/foobar

--controller usb,model=ich9-ehci1,address=0:0:4.7,index=0
--controller usb,model=ich9-uhci1,address=0:0:4.0,index=0,master=0,address.multifunction=on
--controller usb,model=ich9-uhci2,address=0:0:4.1,index=0,master=2
--controller usb,model=ich9-uhci3,address=0:0:4.2,index=0,master=4
--controller scsi,model=virtio-scsi,driver_queues=4
--controller xenbus,maxGrantFrames=64

--input type=keyboard,bus=usb
--input tablet

--serial tcp,host=:2222,mode=bind,protocol=telnet,log.file=/tmp/foo.log,log.append=yes,,target.model.name=pci-serial
--serial nmdm,source.master=/dev/foo1,source.slave=/dev/foo2,alias.name=testalias7
--parallel udp,host=0.0.0.0:1234,bind_host=127.0.0.1:1234
--parallel unix,path=/tmp/foo-socket,source.seclabel0.model=none,source.seclabel1.model=dac,source.seclabel1.relabel=yes,source.seclabel1.label=foobar,source.seclabel.relabel=no
--channel pty,target_type=guestfwd,target_address=127.0.0.1:10000
--channel pty,target_type=guestfwd,target_address=127.0.0.1,target.port=1234
--channel pty,target_type=virtio,name=org.linux-kvm.port1
--console pty,target_type=virtio
--channel spicevmc

--hostdev net_00_1c_25_10_b1_e4,boot_order=4,rom_bar=off
--host-device usb_device_781_5151_2004453082054CA1BEEE
--host-device 001.003
--hostdev 15:0.1
--host-device 2:15:0.2
--hostdev 0:15:0.3,address.type=pci,address.zpci.uid=0xffff,address.zpci.fid=0xffffffff
--host-device 0x0781:0x5151,driver_name=vfio
--host-device 04b3:4485
--host-device pci_8086_2829_scsi_host_scsi_device_lun0,rom.bar=on
--hostdev usb_5_20 --hostdev usb_5_21


--filesystem /source,/target,alias.name=testfsalias,driver.ats=on,driver.iommu=off
--filesystem template_name,/,type=template,mode=passthrough
--filesystem type=file,source=/tmp/somefile.img,target=/mount/point,accessmode=squash

--soundhw default
--sound ac97
--sound codec0.type=micro,codec1.type=duplex,codec2.type=output

--video cirrus
--video model=qxl,vgamem=1,ram=2,vram=3,heads=4,accel3d=yes,vram64=65

--smartcard passthrough,type=spicevmc
--smartcard mode=host
--smartcard default
--smartcard passthrough,type=tcp,source.mode=bind,source.host=1.2.3.4,source.service=5678,protocol.type=telnet
--smartcard host-certificates,type=spicevmc,database=/fake/path/to/database,certificate0=/path/to/fake/cert0,certificate1=/path/to/fake/cert1,certificate2=/path/to/fake/cert2

--redirdev usb,type=spicevmc
--redirdev usb,type=tcp,server=localhost:4000
--redirdev usb,type=tcp,server=127.0.0.1:4002,boot_order=3
--redirdev default
--redirdev type=unix,source.path=/tmp/foo.socket,log.file=/tmp/123.log

--rng egd,backend_host=127.0.0.1,backend_service=8000,backend_type=tcp

--panic iobase=507

--vsock cid=17

--tpm emulator,model=tpm-crb,version=2.0

--qemu-commandline env=DISPLAY=:0.1
--qemu-commandline="-display gtk,gl=on"
--qemu-commandline="-device vfio-pci,addr=05.0,sysfsdev=/sys/class/mdev_bus/0000:00:02.0/f321853c-c584-4a6b-b99a-3eee22a3919c"
--qemu-commandline="-set device.video0.driver=virtio-vga"
""", "many-devices", check_version="2.0.0")  # check_version=graphics listen=socket support




########################
# Boot install options #
########################

c = vinst.add_category("boot", "--nographics --noautoconsole --import --disk none --controller usb,model=none")
c.add_compare("--boot loader=/path/to/loader,loader_secure=yes", "boot-loader-secure")




####################################################
# CPU/RAM/numa and other singleton VM config tests #
####################################################

c = vinst.add_category("cpuram", "--hvm --nographics --noautoconsole --nodisks --pxe")
c.add_valid("--connect " + utils.URIs.xen + " --vcpus 4 --cpuset=auto")  # cpuset=auto but xen doesn't support it
c.add_valid("--ram 4000000")  # Ram overcommit
c.add_valid("--vcpus sockets=2,threads=2")  # Topology only
c.add_valid("--cpu somemodel")  # Simple --cpu
c.add_valid("--security label=foobar.label,relabel=yes")  # --security implicit static
c.add_valid("--security label=foobar.label,a1,z2,b3,type=static,relabel=no")  # static with commas 1
c.add_valid("--security label=foobar.label,a1,z2,b3")  # --security static with commas 2
c.add_invalid("--clock foo_tickpolicy=merge")  # Unknown timer
c.add_invalid("--security foobar")  # Busted --security
c.add_compare("--cpuset auto --vcpus 2", "cpuset-auto")  # --cpuset=auto actually works
c.add_compare("--memory hotplugmemorymax=2048,hotplugmemoryslots=2 --cpu cell0.cpus=0,cell0.memory=1048576 --memdev dimm,access=private,target_size=512,target_node=0,source_pagesize=4,source_nodemask=1-2 --memdev nvdimm,source_path=/path/to/nvdimm,target_size=512,target_node=0,target_label_size=128,alias.name=mymemdev3", "memory-hotplug")
c.add_compare("--memory currentMemory=100,memory=200,maxmemory=300,maxMemory=400,maxMemory.slots=1", "memory-option-backcompat")
c.add_compare("--connect " + utils.URIs.kvm_q35 + " --cpu qemu64,secure=off", "cpu-disable-sec")  # disable security features that are added by default
c.add_compare("--connect " + utils.URIs.kvm_rhel, "cpu-rhel7-default")  # default CPU for old QEMU where we cannot use host-model



########################
# Storage provisioning #
########################

c = vinst.add_category("storage", "--pxe --nographics --noautoconsole --hvm")
c.add_valid("--disk path=%(EXISTIMG1)s")  # Existing disk, no extra options
c.add_valid("--disk pool=default-pool,size=.0001 --disk pool=default-pool,size=.0001")  # Create 2 volumes in a pool
c.add_valid("--disk vol=default-pool/testvol1.img")  # Existing volume
c.add_valid("--disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s,device=cdrom")  # 3 IDE and CD
c.add_valid("--disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi")  # > 16 scsi disks
c.add_valid("--disk path=%(NEWIMG1)s,format=raw,size=.0000001")  # Managed file using format raw
c.add_valid("--disk path=%(NEWIMG1)s,format=qcow2,size=.0000001")  # Managed file using format qcow2
c.add_valid("--disk %(EXISTIMG1)s")  # Not specifying path=
c.add_valid("--disk %(NEWIMG1)s,format=raw,size=.0000001")  # Not specifying path= but creating storage
c.add_valid("--disk %(COLLIDE)s --check path_in_use=off")  # Colliding storage with --check
c.add_valid("--disk %(COLLIDE)s --force")  # Colliding storage with --force
c.add_valid("--disk /dev/default-pool/sharevol.img,perms=sh")  # Colliding shareable storage
c.add_valid("--disk path=%(EXISTIMG1)s,device=cdrom --disk path=%(EXISTIMG1)s,device=cdrom")  # Two IDE cds
c.add_valid("--disk %(EXISTIMG1)s,driver_name=qemu,driver_type=qcow2")  # Driver name and type options
c.add_valid("--disk /dev/zero")  # Referencing a local unmanaged /dev node
c.add_valid("--disk pool=default,size=.00001")  # Building 'default' pool
c.add_valid("--disk /some/new/pool/dir/new,size=.1")  # autocreate the pool
c.add_valid("--disk %(NEWIMG1)s,sparse=true,size=100000000 --check disk_size=off")  # Don't warn about fully allocated file exceeding disk space
c.add_valid("--disk %(EXISTIMG1)s,snapshot_policy=no")  # Disable snasphot for disk
c.add_invalid("--file %(NEWIMG1)s --file-size 100000 --nonsparse")  # Nonexisting file, size too big
c.add_invalid("--file %(NEWIMG1)s --file-size 100000")  # Huge file, sparse, but no prompting
c.add_invalid("--file %(NEWIMG1)s")  # Nonexisting file, no size
c.add_invalid("--file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s")  # Too many IDE
c.add_invalid("--disk pool=foopool,size=.0001")  # Specify a nonexistent pool
c.add_invalid("--disk vol=default-pool/foovol")  # Specify a nonexistent volume
c.add_invalid("--disk pool=default-pool")  # Specify a pool with no size
c.add_invalid("--disk path=%(EXISTIMG1)s,perms=ro,size=.0001,cache=FOOBAR")  # Unknown cache type
c.add_invalid("--disk path=/dev/foo/bar/baz,format=qcow2,size=.0000001")  # Unmanaged file using non-raw format
c.add_invalid("--disk path=/dev/disk-pool/newvol1.img,format=raw,size=.0000001")  # Managed disk using any format
c.add_invalid("--disk %(NEWIMG1)s")  # Not specifying path= and non existent storage w/ no size
c.add_invalid("--disk %(NEWIMG1)s,sparse=true,size=100000000000")  # Fail if fully allocated file would exceed disk space
c.add_invalid("--connect %(URI-TEST-FULL)s --disk %(COLLIDE)s")  # Colliding storage without --force
c.add_invalid("--connect %(URI-TEST-FULL)s --disk %(COLLIDE)s --prompt")  # Colliding storage with --prompt should still fail
c.add_invalid("--connect %(URI-TEST-FULL)s --disk /dev/default-pool/backingl3.img")  # Colliding storage via backing store
c.add_invalid("--disk /var,device=cdrom")  # Dir without floppy
c.add_invalid("--disk %(EXISTIMG1)s,driver_name=foobar,driver_type=foobaz")  # Unknown driver name and type options (as of 1.0.0)
c.add_invalid("--connect %(URI-TEST-FULL)s --disk source_pool=rbd-ceph,source_volume=vol1")  # Collision with existing VM, via source pool/volume
c.add_invalid("--disk source_pool=default-pool,source_volume=idontexist")  # trying to lookup non-existent volume, hit specific error code
c.add_invalid("--disk size=1 --security model=foo,type=bar")  # Libvirt will error on the invalid security params, which should trigger the code path to clean up the disk images we created.



################################################
# Invalid devices that hit virtinst code paths #
################################################

c = vinst.add_category("invalid-devices", "--noautoconsole --nodisks --pxe")
c.add_invalid("--connect %(URI-TEST-FULL)s --host-device 1d6b:2")  # multiple USB devices with identical vendorId and productId
c.add_invalid("--connect %(URI-TEST-FULL)s --host-device pci_8086_2850_scsi_host_scsi_host")  # Unsupported hostdev type
c.add_invalid("--host-device foobarhostdev")  # Unknown hostdev
c.add_invalid("--host-device 300:400")  # Parseable hostdev, but unknown digits
c.add_invalid("--graphics vnc,keymap=ZZZ")  # Invalid keymap
c.add_invalid("--graphics vnc,port=-50")  # Invalid port
c.add_invalid("--graphics spice,tlsport=5")  # Invalid port
c.add_invalid("--serial unix")  # Unix with no path
c.add_invalid("--channel pty,target_type=guestfwd")  # --channel guestfwd without target_address
c.add_invalid("--boot uefi")  # URI doesn't support UEFI bits
c.add_invalid("--connect %(URI-KVM)s --boot uefi,arch=ppc64")  # unsupported arch for UEFI
c.add_invalid("--features smm=on --machine pc")  # smm=on doesn't work for machine=pc



########################
# Install option tests #
########################

c = vinst.add_category("nodisk-install", "--nographics --noautoconsole --nodisks")
c.add_valid("--hvm --cdrom %(EXISTIMG1)s")  # Simple cdrom install
c.add_valid("--wait 0 --os-variant winxp --cdrom %(EXISTIMG1)s")  # Windows (2 stage) install
c.add_valid("--pxe --virt-type test")  # Explicit virt-type
c.add_valid("--arch i686 --pxe")  # Explicitly fullvirt + arch
c.add_valid("--location location=%(TREEDIR)s")  # Directory tree URL install
c.add_valid("--location %(TREEDIR)s --initrd-inject virt-install --extra-args ks=file:/virt-install")  # initrd-inject
c.add_valid("--hvm --location %(TREEDIR)s --extra-args console=ttyS0")  # Directory tree URL install with extra-args
c.add_valid("--paravirt --location %(TREEDIR)s")  # Paravirt location
c.add_valid("--paravirt --location %(TREEDIR)s --os-variant none")  # Paravirt location with --os-variant none
c.add_valid("--location %(TREEDIR)s --os-variant fedora12")  # URL install with manual os-variant
c.add_valid("--cdrom %(EXISTIMG2)s --os-variant win2k3 --wait 0")  # HVM windows install with disk
c.add_valid("--cdrom %(EXISTIMG2)s --os-variant win2k3 --wait 0 --print-step 2")  # HVM windows install, print 3rd stage XML
c.add_valid("--pxe --autostart")  # --autostart flag
c.add_compare("--cdrom http://example.com/path/to/some.iso", "cdrom-url")
c.add_compare("--pxe --print-step all", "simple-pxe")  # Diskless PXE install
c.add_invalid("--pxe --virt-type bogus")  # Bogus virt-type
c.add_invalid("--pxe --arch bogus")  # Bogus arch
c.add_invalid("--livecd")  # LiveCD with no media
c.add_invalid("--pxe --os-variant farrrrrrrge")  # Bogus --os-variant
c.add_invalid("--pxe --boot menu=foobar")
c.add_invalid("--cdrom %(EXISTIMG1)s --extra-args console=ttyS0")  # cdrom fail w/ extra-args
c.add_invalid("--hvm --boot kernel=%(TREEDIR)s/pxeboot/vmlinuz,initrd=%(TREEDIR)s/pxeboot/initrd.img,kernel_args='foo bar' --initrd-inject virt-install")  # initrd-inject with manual kernel/initrd
c.add_invalid("--disk none --location kernel=/dev/null,initrd=/dev/null")  # --location with manual kernel/initrd, but not URL
c.add_invalid("--os-variant winxp,install=location")  # no URL for winxp
c.add_invalid("--os-variant fedora28,install=fribber")  # unknown install= value

c = vinst.add_category("single-disk-install", "--nographics --noautoconsole --disk %(EXISTIMG1)s")
c.add_valid("--hvm --import")  # FV Import install
c.add_valid("--hvm --import --prompt --force")  # Working scenario w/ prompt shouldn't ask anything
c.add_valid("--paravirt --import")  # PV Import install
c.add_valid("--paravirt --print-xml")  # print single XML, implied import install
c.add_compare("--cdrom %(EXISTIMG2)s --os-variant win2k3 --wait 0 --vcpus cores=4 --controller usb,model=none", "w2k3-cdrom")  # HVM windows install with disk
c.add_invalid("--paravirt --import --print-xml 2")  # PV Import install, no second XML step

c = vinst.add_category("misc-install", "--nographics --noautoconsole")
c.add_compare("", "noargs-fail", auto_printarg=False)  # No arguments
c.add_valid("--panic help --disk=? --check=help", grep="path_in_use")  # Make sure introspection doesn't blow up
c.add_valid("--test-stub-command")  # --test-stub-command
c.add_valid("--nodisks --pxe", grep="VM performance may suffer")  # os variant warning
c.add_invalid("--hvm --nodisks --pxe foobar")  # Positional arguments error
c.add_invalid("--nodisks --pxe --name test")  # Colliding name
c.add_compare("--cdrom %(EXISTIMG1)s --disk size=1 --disk %(EXISTIMG2)s,device=cdrom", "cdrom-double")  # ensure --disk device=cdrom is ordered after --cdrom, this is important for virtio-win installs with a driver ISO
c.add_valid("--connect %s --pxe --disk size=1" % utils.URIs.test_defaultpool_collision)  # testdriver already has a pool using the 'default' path, make sure we don't error


#############################
# Remote URI specific tests #
#############################

c = vinst.add_category("remote", "--connect %(URI-TEST-REMOTE)s --nographics --noautoconsole")
c.add_valid("--nodisks --pxe")  # Simple pxe nodisks
c.add_valid("--pxe --disk /foo/bar/baz,size=.01")  # Creating any random path on the remote host
c.add_valid("--pxe --disk /dev/zde")  # /dev file that we just pass through to the remote VM
c.add_invalid("--pxe --disk /foo/bar/baz")  # File that doesn't exist after auto storage setup
c.add_invalid("--nodisks --location /tmp")  # Use of --location
c.add_invalid("--file /foo/bar/baz --pxe")  # Trying to use unmanaged storage without size argument



###########################
# QEMU/KVM specific tests #
###########################

c = vinst.add_category("kvm-generic", "--connect %(URI-KVM)s --noautoconsole")
c.add_compare("--os-variant fedora-unknown --file %(EXISTIMG1)s --location %(TREEDIR)s --extra-args console=ttyS0 --cpu host --channel none --console none --sound none --redirdev none", "kvm-fedoralatest-url", skip_cb=has_old_osinfo)  # Fedora Directory tree URL install with extra-args
c.add_compare("--test-media-detection %(TREEDIR)s", "test-url-detection")  # --test-media-detection
c.add_compare("--os-variant full_id=http://fedoraproject.org/fedora/20 --disk %(NEWIMG1)s,size=.01,format=vmdk --location %(TREEDIR)s --extra-args console=ttyS0 --quiet", "quiet-url", skip_cb=has_old_osinfo)  # Quiet URL install should make no noise
c.add_compare("--cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --sound --controller usb", "kvm-win2k3-cdrom")  # HVM windows install with disk
c.add_compare("--os-variant ubuntusaucy --nodisks --boot cdrom --virt-type qemu --cpu Penryn --input tablet", "qemu-plain")  # plain qemu
c.add_compare("--os-variant fedora20 --nodisks --boot network --nographics --arch i686", "qemu-32-on-64", skip_cb=has_old_osinfo)  # 32 on 64

# ppc64 tests
c.add_compare("--arch ppc64 --machine pseries --boot network --disk %(EXISTIMG1)s --disk device=cdrom --os-variant fedora20 --network none", "ppc64-pseries-f20")
c.add_compare("--arch ppc64 --boot network --disk %(EXISTIMG1)s --os-variant fedora20 --network none", "ppc64-machdefault-f20")
c.add_compare("--connect %(URI-KVM-PPC64LE)s --import --disk %(EXISTIMG1)s --os-variant fedora20 --panic default", "ppc64le-kvm-import")

# s390x tests
c.add_compare("--arch s390x --machine s390-ccw-virtio --connect %(URI-KVM-S390X)s --boot kernel=/kernel.img,initrd=/initrd.img --disk %(EXISTIMG1)s --disk %(EXISTIMG3)s,device=cdrom --os-variant fedora21", "s390x-cdrom", skip_cb=has_old_osinfo)
c.add_compare("--arch s390x --machine s390-ccw-virtio --connect " + utils.URIs.kvm_s390x_KVMIBM + " --boot kernel=/kernel.img,initrd=/initrd.img --disk %(EXISTIMG1)s --disk %(EXISTIMG3)s,device=cdrom --os-variant fedora21 --watchdog diag288,action=reset --panic default --graphics vnc", "s390x-cdrom-KVMIBM")

# qemu:///session tests
c.add_compare("--connect " + utils.URIs.kvm_session + " --disk size=8 --os-variant fedora21 --cdrom %(EXISTIMG1)s", "kvm-session-defaults", skip_cb=has_old_osinfo)

# misc KVM config tests
c.add_compare("--disk none --location %(ISO-NO-OS)s,kernel=frib.img,initrd=/frob.img", "location-manual-kernel", skip_cb=missing_isoinfo)  # --location with an unknown ISO but manually specified kernel paths
c.add_compare("--disk %(EXISTIMG1)s --location %(ISOTREE)s --nonetworks", "location-iso", skip_cb=missing_isoinfo)  # Using --location iso mounting
c.add_compare("--disk %(EXISTIMG1)s --cdrom %(ISOLABEL)s", "cdrom-centos-label")  # Using --cdrom with centos CD label, should use virtio etc.
c.add_compare("--disk %(EXISTIMG1)s --pxe --os-variant rhel5.4", "kvm-rhel5")  # RHEL5 defaults
c.add_compare("--disk %(EXISTIMG1)s --pxe --os-variant rhel6.4", "kvm-rhel6")  # RHEL6 defaults
c.add_compare("--disk %(EXISTIMG1)s --pxe --os-variant rhel7.0", "kvm-rhel7", skip_cb=has_old_osinfo)  # RHEL7 defaults
c.add_compare("--connect " + utils.URIs.kvm_nodomcaps + " --disk %(EXISTIMG1)s --pxe --os-variant rhel7.0", "kvm-cpu-default-fallback", skip_cb=has_old_osinfo)  # No domcaps, so mode=host-model isn't safe, so we fallback to host-model-only
c.add_compare("--connect " + utils.URIs.kvm_nodomcaps + " --cpu host-copy --disk none --pxe", "kvm-hostcopy-fallback")  # No domcaps so need to use capabilities for CPU host-copy
c.add_compare("--disk %(EXISTIMG1)s --pxe --os-variant centos7.0", "kvm-centos7", skip_cb=has_old_osinfo)  # Centos 7 defaults
c.add_compare("--disk %(EXISTIMG1)s --pxe --os-variant centos7.0", "kvm-centos7", skip_cb=has_old_osinfo)  # Centos 7 defaults
c.add_compare("--disk %(EXISTIMG1)s --cdrom %(EXISTIMG2)s --os-variant win10", "kvm-win10", skip_cb=has_old_osinfo)  # win10 defaults
c.add_compare("--os-variant win7 --cdrom %(EXISTIMG2)s --boot loader_type=pflash,loader=CODE.fd,nvram_template=VARS.fd --disk %(EXISTIMG1)s", "win7-uefi", skip_cb=has_old_osinfo)  # no HYPER-V with UEFI
c.add_compare("--arch i686 --boot uefi --pxe --disk none", "kvm-i686-uefi")  # i686 uefi
c.add_compare("--machine q35 --cdrom %(EXISTIMG2)s --disk %(EXISTIMG1)s", "q35-defaults")  # proper q35 disk defaults
c.add_compare("--disk size=20 --os-variant solaris10", "solaris10-defaults")  # test solaris OS defaults, triggers a couple specific code paths
c.add_compare("--disk size=1 --os-variant openbsd4.9", "openbsd-defaults")  # triggers net fallback scenario
c.add_compare("--connect " + utils.URIs.kvm_remote + " --import --disk %(EXISTIMG1)s --os-variant fedora21 --pm suspend_to_disk=yes", "f21-kvm-remote", skip_cb=has_old_osinfo)

c.add_valid("--arch aarch64 --nodisks --pxe --connect " + utils.URIs.kvm_nodomcaps)  # attempt to default to aarch64 UEFI, but it fails, but should only print warnings
c.add_invalid("--disk none --boot network --machine foobar")  # Unknown machine type
c.add_invalid("--nodisks --boot network --arch mips --virt-type kvm")  # Invalid domain type for arch
c.add_invalid("--nodisks --boot network --paravirt --arch mips")  # Invalid arch/virt combo
c.add_invalid("--disk none --location nfs:example.com/fake --nonetworks")  # Using --location nfs, no longer supported

c = vinst.add_category("kvm-q35", "--noautoconsole --connect " + utils.URIs.kvm_q35)
c.add_compare("--boot uefi --disk none", "boot-uefi")


c = vinst.add_category("kvm-arm", "--connect %(URI-KVM)s --noautoconsole", check_version="3.3.0")  # required qemu-xhci from libvirt 3.3.0
# armv7l tests
c.add_compare("--arch armv7l --machine vexpress-a9 --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,dtb=/f19-arm.dtb,extra_args=\"console=ttyAMA0 rw root=/dev/mmcblk0p3\" --disk %(EXISTIMG1)s --nographics", "arm-vexpress-plain")
c.add_compare("--arch armv7l --machine virt --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\" --disk %(EXISTIMG1)s --nographics --os-variant fedora20", "arm-virt-f20")
c.add_compare("--arch armv7l --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\",extra_args=foo --disk %(EXISTIMG1)s --os-variant fedora20", "arm-defaultmach-f20")
c.add_compare("--connect %(URI-KVM-ARMV7L)s --disk %(EXISTIMG1)s --import --os-variant fedora20", "arm-kvm-import")

# aarch64 tests
c.add_compare("--arch aarch64 --machine virt --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\" --disk %(EXISTIMG1)s", "aarch64-machvirt")
c.add_compare("--arch aarch64 --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\" --disk %(EXISTIMG1)s", "aarch64-machdefault")
c.add_compare("--arch aarch64 --cdrom %(EXISTIMG2)s --boot loader=CODE.fd,nvram.template=VARS.fd --disk %(EXISTIMG1)s --cpu none --events on_crash=preserve,on_reboot=destroy,on_poweroff=restart", "aarch64-cdrom")
c.add_compare("--connect %(URI-KVM-AARCH64)s --disk %(EXISTIMG1)s --import --os-variant fedora21", "aarch64-kvm-import")
c.add_compare("--connect %(URI-KVM-AARCH64)s --disk size=1 --os-variant fedora22 --features gic_version=host --network network=default,address.type=pci --controller type=scsi,model=virtio-scsi,address.type=pci", "aarch64-kvm-gic")


# Simple headless guests for various architectures
c = vinst.add_category("kvm-headless", "--os-variant fedora29 --import --disk %(EXISTIMG1)s --network default --graphics none")
c.add_compare("--connect %(URI-KVM-AARCH64)s --arch aarch64", "aarch64-headless")
c.add_compare("--connect %(URI-KVM-PPC64LE)s --arch ppc64le", "ppc64-headless")
c.add_compare("--connect %(URI-QEMU-RISCV64)s --arch riscv64", "riscv64-headless", check_version="5.3.0")
c.add_compare("--connect %(URI-KVM-S390X)s --arch s390x", "s390x-headless")
c.add_compare("--connect %(URI-KVM)s --arch x86_64", "x86_64-headless")


# Simple guests with graphics for various architectures
c = vinst.add_category("kvm-graphics", "--os-variant fedora29 --import --disk %(EXISTIMG1)s --network default --graphics vnc")
c.add_compare("--connect %(URI-KVM-AARCH64)s --arch aarch64", "aarch64-graphics")
c.add_compare("--connect %(URI-KVM-PPC64LE)s --arch ppc64le", "ppc64-graphics")
c.add_compare("--connect %(URI-QEMU-RISCV64)s --arch riscv64", "riscv64-graphics", check_version="5.3.0")
c.add_compare("--connect %(URI-KVM-S390X)s --arch s390x", "s390x-graphics")
c.add_compare("--connect %(URI-KVM)s --arch x86_64", "x86_64-graphics")



######################
# LXC specific tests #
######################

c = vinst.add_category("lxc", "--name foolxc --memory 64 --noautoconsole --connect " + utils.URIs.lxc)
c.add_compare("", "default")
c.add_compare("--os-variant fedora27", "default-f27")
c.add_compare("--filesystem /source,/", "fs-default")
c.add_compare("--init /usr/bin/httpd", "manual-init")



######################
# Xen specific tests #
######################

c = vinst.add_category("xen", "--noautoconsole --connect " + utils.URIs.xen)
c.add_valid("--disk %(EXISTIMG1)s --location %(TREEDIR)s --paravirt --graphics none")  # Xen PV install headless
c.add_compare("--disk %(EXISTIMG1)s --import", "xen-default")  # Xen default
c.add_compare("--disk %(EXISTIMG1)s --location %(TREEDIR)s --paravirt --controller xenbus,maxGrantFrames=64", "xen-pv")  # Xen PV
c.add_compare("--disk  /iscsi-pool/diskvol1 --cdrom %(EXISTIMG1)s --livecd --hvm", "xen-hvm")  # Xen HVM



#####################
# VZ specific tests #
#####################

c = vinst.add_category("vz", "--noautoconsole --connect " + utils.URIs.vz)
c.add_valid("--container")  # validate the special define+start logic
c.add_invalid("--container --transient")  # doesn't support --transient
c.add_compare("""
--container
--filesystem type=template,source=centos-7-x86_64,target="/"
--network network="Bridged"
""", "vz-ct-template")




#####################################
# Device option back compat testing #
#####################################

c = vinst.add_category("device-back-compat", "--nodisks --pxe --noautoconsole")
c.add_valid("--sdl")  # SDL
c.add_valid("--vnc --keymap ja --vncport 5950 --vnclisten 1.2.3.4")  # VNC w/ lots of options
c.add_valid("--sound")  # --sound with no option back compat
c.add_valid("--mac 22:22:33:44:55:AF")  # Just a macaddr
c.add_valid("--bridge mybr0 --mac 22:22:33:44:55:AF")  # Old bridge w/ mac
c.add_valid("--network bridge:mybr0,model=e1000")  # --network bridge:
c.add_valid("--network network:default --mac RANDOM")  # VirtualNetwork with a random macaddr
c.add_valid("--vnc --keymap=local")  # --keymap local
c.add_valid("--panic 0x505")  # ISA panic with iobase specified
c.add_invalid("--graphics vnc --vnclisten 1.2.3.4")  # mixing old and new
c.add_invalid("--network=FOO")  # Nonexistent network
c.add_invalid("--mac 1234")  # Invalid mac
c.add_invalid("--network user --bridge foo0")  # Mixing bridge and network
c.add_invalid("--connect %(URI-TEST-FULL)s --mac 22:22:33:12:34:AB")  # Colliding macaddr

c = vinst.add_category("storage-back-compat", "--pxe --noautoconsole")
c.add_valid("--file %(EXISTIMG1)s --nonsparse --file-size 4")  # Existing file, other opts
c.add_valid("--file %(EXISTIMG1)s")  # Existing file, no opts
c.add_valid("--file %(EXISTIMG1)s --file %(EXISTIMG1)s")  # Multiple existing files
c.add_valid("--file %(NEWIMG1)s --file-size .00001 --nonsparse")  # Nonexistent file

c = vinst.add_category("console-tests", "--nodisks")
c.add_valid("--pxe", grep="testsuite console command: ['virt-viewer'")  # mock default graphics+virt-viewer usage
c.add_valid("--pxe --destroy-on-exit", grep="Restarting guest.\n")  # destroy-on-exit
c.add_valid("--pxe --transient --destroy-on-exit", grep="Domain creation completed.")  # destroy-on-exit + transient
c.add_valid("--pxe --graphics vnc --noreboot", grep="testsuite console command: ['virt-viewer'")  # mock virt-viewer waiting, with noreboot magic
c.add_valid("--nographics --cdrom %(EXISTIMG1)s")  # console warning about cdrom + nographics
c.add_valid("--nographics --console none --location %(TREEDIR)s")  # console warning about nographics + --console none
c.add_valid("--nographics --console none --location %(TREEDIR)s")  # console warning about nographics + --console none
c.add_valid("--nographics --location %(TREEDIR)s")  # console warning about nographics + missing extra args
c.add_invalid("--pxe --noautoconsole --wait 1", grep="Installation has exceeded specified time limit")  # --wait 1 is converted to 1 second if we are in the test suite, so this should actually touch the wait machinery. however in this case it exits with failure
c.add_valid("--pxe --nographics --transient", grep="testsuite console command: ['virsh'")  # --transient handling


##################
# virt-xml tests #
##################

vixml = App("virt-xml", check_version="1.2.2")  # check_version for  input type=keyboard output change
c = vixml.add_category("misc", "")
c.add_valid("--help")  # basic --help test
c.add_valid("--sound=? --tpm=?")  # basic introspection test
c.add_valid("test-state-shutoff --edit --update --boot menu=on")  # --update with inactive VM, should work but warn
c.add_invalid("test-state-shutoff --edit --update --boot menu=on --start")
c.add_invalid("test --edit --hostdev driver_name=vfio")  # Guest has no hostdev to edit
c.add_invalid("test --edit --cpu host-passthrough --boot hd,network")  # Specified more than 1 option
c.add_invalid("test --edit")  # specified no edit option
c.add_invalid("test --edit 2 --cpu host-passthrough")  # specifying --edit number where it doesn't make sense
c.add_invalid("test-for-virtxml --edit 5 --tpm /dev/tpm")  # device edit out of range
c.add_invalid("test-for-virtxml --add-device --host-device 0x04b3:0x4485 --update")  # test driver doesn't support attachdevice...
c.add_invalid("test-for-virtxml --remove-device --host-device 1 --update")  # test driver doesn't support detachdevice...
c.add_invalid("test-for-virtxml --edit --graphics password=foo --update")  # test driver doesn't support updatdevice...
c.add_invalid("--build-xml --memory 10,maxmemory=20")  # building XML for option that doesn't support it
c.add_invalid("test --edit --boot network,cdrom --define --no-define")
c.add_compare("test --print-xml --edit --vcpus 7", "print-xml")  # test --print-xml
c.add_compare("--edit --cpu host-passthrough", "stdin-edit", input_file=(XMLDIR + "/virtxml-stdin-edit.xml"))  # stdin test
c.add_compare("--build-xml --cpu pentium3,+x2apic", "build-cpu")
c.add_compare("--build-xml --tpm path=/dev/tpm", "build-tpm")
c.add_compare("--build-xml --blkiotune weight=100,device0.path=/dev/sdf,device.weight=200", "build-blkiotune")
c.add_compare("--build-xml --idmap uid.start=0,uid.target=1000,uid.count=10,gid.start=0,gid.target=1000,gid.count=10", "build-idmap")
c.add_compare("4a64cc71-19c4-2fd0-2323-3050941ea3c3 --edit --boot network,cdrom", "edit-bootorder")  # basic bootorder test, also using UUID lookup
c.add_compare("--confirm 1 --edit --cpu host-passthrough", "prompt-response")  # prompt response, also using domid lookup
c.add_compare("--edit --print-diff --qemu-commandline clearxml=yes", "edit-clearxml-qemu-commandline", input_file=(XMLDIR + "/virtxml-qemu-commandline-clear.xml"))
c.add_compare("--connect %(URI-KVM)s test-hyperv-uefi --edit --boot uefi", "hyperv-uefi-collision")


c = vixml.add_category("simple edit diff", "test-for-virtxml --edit --print-diff --define")
c.add_compare("""--metadata name=foo-my-new-name,os_name=fedora13,uuid=12345678-12F4-1234-1234-123456789AFA,description="hey this is my
new
very,very=new desc\\\'",title="This is my,funky=new title" """, "edit-simple-metadata")
c.add_compare("""--metadata os_full_id=http://fedoraproject.org/fedora/23""", "edit-metadata-full-os")
c.add_compare("--events on_poweroff=destroy,on_reboot=restart,on_crash=preserve", "edit-simple-events")
c.add_compare("--qemu-commandline='-foo bar,baz=\"wib wob\"'", "edit-simple-qemu-commandline")
c.add_compare("--memory 500,maxmemory=1000,hugepages=off", "edit-simple-memory")
c.add_compare("--vcpus 10,maxvcpus=20,cores=5,sockets=4,threads=1", "edit-simple-vcpus")
c.add_compare("--cpu model=pentium2,+x2apic,forbid=pbe", "edit-simple-cpu")
c.add_compare("--numatune memory.nodeset=1-5,7,memory.mode=strict", "edit-simple-numatune")
c.add_compare("--blkiotune weight=500,device_path=/dev/sdf,device_weight=600", "edit-simple-blkiotune")
c.add_compare("--idmap uid_start=0,uid_target=2000,uid_count=30,gid_start=0,gid_target=3000,gid_count=40", "edit-simple-idmap")
c.add_compare("--boot loader=foo.bar,useserial=on,init=/bin/bash,nvram=/test/nvram.img,os_type=hvm,domain_type=test,loader.readonly=on,loader.secure=no,machine=", "edit-simple-boot")
c.add_compare("--security label=foo,bar,baz,UNKNOWN=val,relabel=on", "edit-simple-security")
c.add_compare("--features eoi=on,hyperv_relaxed=off,acpi=", "edit-simple-features")
c.add_compare("--clock offset=localtime,hpet_present=yes,kvmclock_present=no,kvmclock_tickpolicy=foo,rtc_tickpolicy=merge", "edit-simple-clock")
c.add_compare("--pm suspend_to_mem.enabled=yes,suspend_to_disk.enabled=no", "edit-simple-pm")
c.add_compare("--disk /dev/zero,perms=ro,startup_policy=optional", "edit-simple-disk")
c.add_compare("--disk path=", "edit-simple-disk-remove-path")
c.add_compare("--network source=br0,type=bridge,model=virtio,mac=", "edit-simple-network")
c.add_compare("--graphics tlsport=5902,keymap=ja", "edit-simple-graphics", check_version="1.3.5")  # check_version=new graphics listen output
c.add_compare("--graphics listen=none", "edit-graphics-listen-none", check_version="2.0.0")  # check_version=graphics listen=none support
c.add_compare("--controller index=15,model=lsilogic", "edit-simple-controller")
c.add_compare("--controller index=15,model=lsilogic", "edit-simple-controller")
c.add_compare("--smartcard type=spicevmc", "edit-simple-smartcard")
c.add_compare("--redirdev type=spicevmc,server=example.com:12345", "edit-simple-redirdev")
c.add_compare("--tpm backend.device.path=,backend.type=emulator,backend.version=2.0", "edit-simple-tpm", check_version="1.3.5")  # check_version=new graphics listen output
c.add_compare("--vsock model=virtio,cid.address=,cid.auto=on", "edit-simple-vsock")
c.add_compare("--rng rate_bytes=3333,rate_period=4444", "edit-simple-rng")
c.add_compare("--watchdog action=reset", "edit-simple-watchdog")
c.add_compare("--memballoon model=none", "edit-simple-memballoon")
c.add_compare("--serial pty", "edit-simple-serial")
c.add_compare("--parallel unix,path=/some/other/log", "edit-simple-parallel")
c.add_compare("--channel null", "edit-simple-channel")
c.add_compare("--console name=foo.bar.baz", "edit-simple-console")
c.add_compare("--filesystem /1/2/3,/4/5/6,mode=mapped", "edit-simple-filesystem")
c.add_compare("--video cirrus", "edit-simple-video", check_version="1.3.3")  # check_version=video primary= attribute
c.add_compare("--sound pcspk", "edit-simple-soundhw", check_version="1.3.5")  # check_version=new graphics listen output
c.add_compare("--host-device 0x04b3:0x4485,driver_name=vfio,type=usb", "edit-simple-host-device")

c = vixml.add_category("edit selection", "test-for-virtxml --print-diff --define")
c.add_invalid("--edit target=vvv --disk /dev/null")  # no match found
c.add_invalid("--edit seclabel2.model=dac --disk /dev/null")  # no match found
c.add_valid("--edit seclabel.model=dac --disk /dev/null")  # match found
c.add_compare("--edit 3 --sound pcspk", "edit-pos-num", check_version="1.3.5")  # check_version=new graphics listen output
c.add_compare("--edit -1 --video qxl", "edit-neg-num", check_version="1.2.11")  # check_version=video ram output change
c.add_compare("--edit all --host-device driver.name=vfio", "edit-all")
c.add_compare("--edit ich6 --sound pcspk", "edit-select-sound-model", check_version="1.3.5")  # check_version=new graphics listen output
c.add_compare("--edit target=hda --disk /dev/null", "edit-select-disk-target")
c.add_compare("--edit /tmp/foobar2 --disk shareable=off,readonly=on", "edit-select-disk-path")
c.add_compare("--edit mac=00:11:7f:33:44:55 --network target=nic55", "edit-select-network-mac")
c.add_compare("--edit target=hda --disk boot_order=1", "edit-select-disk-bootorder")
c.add_compare("--edit path=/dev/null --disk path=,target=fdb,boot_order=12", "edit-disk-unset")  # --disk matching, using empty value to unset path

c = vixml.add_category("edit and start selection", "test-state-shutoff --print-diff --start")
c.add_compare("--define --edit target=vda --disk boot_order=1", "start-select-disk-bootorder")
c.add_invalid("--define --no-define --edit target=vda --disk boot_order=1")
c.add_compare("--edit target=vda --disk boot_order=1", "start-select-disk-bootorder2")
c.add_compare("--no-define --edit target=vda --disk boot_order=1", "start-select-disk-bootorder2")

c = vixml.add_category("edit selection 2", "test-collide --print-diff --define")
c.add_compare("--edit target=hda --disk boot_order=1", "edit-select-disk-bootorder2")

c = vixml.add_category("edit clear", "test-for-virtxml --print-diff --define")
c.add_invalid("--edit --memory 200,clearxml=yes")  # clear isn't wired up for memory
c.add_compare("--edit --disk path=/foo/bar,size=2,target=fda,bus=fdc,device=floppy,clearxml=yes", "edit-clear-disk")
c.add_compare("--edit --cpu host-passthrough,clearxml=yes", "edit-clear-cpu")
c.add_compare("--edit --clock offset=utc,clearxml=yes", "edit-clear-clock")
c.add_compare("--edit --video clearxml=yes,model=virtio,accel3d=yes", "edit-video-virtio")
c.add_compare("--edit --graphics clearxml=yes,type=spice,gl=on,listen=none", "edit-graphics-spice-gl", check_version="2.0.0")  # check_version=graphics listen=none support

c = vixml.add_category("add/rm devices", "test-for-virtxml --print-diff --define")
c.add_valid("--add-device --security model=dac")  # --add-device works for seclabel
c.add_invalid("--add-device --pm suspend_to_disk=yes")  # --add-device without a device
c.add_invalid("--remove-device --clock utc")  # --remove-device without a dev
c.add_compare("--add-device --host-device usb_device_4b3_4485_noserial", "add-host-device")
c.add_compare("--add-device --sound pcspk", "add-sound")
c.add_compare("--add-device --disk %(EXISTIMG1)s,bus=virtio,target=vdf", "add-disk-basic")
c.add_compare("--add-device --disk %(EXISTIMG1)s", "add-disk-notarget")  # filling in acceptable target
c.add_compare("--add-device --disk %(NEWIMG1)s,size=.01", "add-disk-create-storage")
c.add_compare("--add-device --disk size=.01", "add-disk-default-storage")
c.add_compare("--remove-device --sound ich6", "remove-sound-model", check_version="1.3.5")  # check_version=new graphics listen output
c.add_compare("--remove-device --disk 3", "remove-disk-index")
c.add_compare("--remove-device --disk /dev/null", "remove-disk-path")
c.add_compare("--remove-device --video all", "remove-video-all", check_version="1.3.3")  # check_version=video primary= attribute
c.add_compare("--remove-device --host-device 0x04b3:0x4485", "remove-hostdev-name", check_version="1.2.11")  # check_version=video ram output change

c = vixml.add_category("add/rm devices and start", "test-state-shutoff --print-diff --start")
c.add_invalid("--add-device --pm suspend_to_disk=yes")  # --add-device without a device
c.add_invalid("--remove-device --clock utc")  # --remove-device without a dev
# one test in combination with --define
c.add_compare("--define --add-device --host-device usb_device_4b3_4485_noserial", "add-host-device-start")
# all other test cases without
c.add_compare("--add-device --disk %(EXISTIMG1)s,bus=virtio,target=vdf", "add-disk-basic-start")
c.add_compare("--add-device --disk %(NEWIMG1)s,size=.01", "add-disk-create-storage-start")
c.add_compare("--remove-device --disk /dev/null", "remove-disk-path-start")

c = vixml.add_category("add/rm devices OS KVM", "--connect %(URI-KVM)s test --print-diff --define")
c.add_compare("--add-device --disk %(EXISTIMG1)s", "kvm-add-disk-os-from-xml")  # Guest OS (none) from XML
c.add_compare("--add-device --disk %(EXISTIMG1)s --os-variant fedora28", "kvm-add-disk-os-from-cmdline")  # Guest OS (fedora) provided on command line
c.add_compare("--add-device --network default", "kvm-add-network-os-from-xml")  # Guest OS information taken from the guest XML
c.add_compare("--add-device --network default --os-variant full_id=http://fedoraproject.org/fedora/28", "kvm-add-network-os-from-cmdline")  # Guest OS information provided on the command line



####################
# virt-clone tests #
####################

_CLONE_UNMANAGED = "%s/clone-disk.xml" % XMLDIR
_CLONE_MANAGED = "%s/clone-disk-managed.xml" % XMLDIR
_CLONE_NOEXIST = "%s/clone-disk-noexist.xml" % XMLDIR

vclon = App("virt-clone")
c = vclon.add_category("remote", "--connect %(URI-TEST-REMOTE)s")
c.add_valid("-o test --auto-clone")  # Auto flag, no storage
c.add_valid("--original-xml " + _CLONE_MANAGED + " --auto-clone")  # Auto flag w/ managed storage
c.add_invalid("--original-xml " + _CLONE_UNMANAGED + " --auto-clone")  # Auto flag w/ local storage, which is invalid for remote connection


c = vclon.add_category("misc", "")
c.add_compare("--connect %(URI-KVM)s -o test-clone --auto-clone --clone-running", "clone-auto1", check_version="1.2.15")
c.add_compare("--connect %(URI-TEST-FULL)s -o test-clone-simple --name newvm --auto-clone --clone-running", "clone-auto2", check_version="1.2.15")
c.add_valid("-o test --auto-clone")  # Auto flag, no storage
c.add_valid("--original-xml " + _CLONE_MANAGED + " --auto-clone")  # Auto flag w/ managed storage
c.add_valid("--original-xml " + _CLONE_UNMANAGED + " --auto-clone")  # Auto flag w/ local storage
c.add_valid("--connect %(URI-TEST-FULL)s -o test-clone --auto-clone --clone-running")  # Auto flag, actual VM, skip state check
c.add_valid("--connect %(URI-TEST-FULL)s -o test-clone-simple -n newvm --preserve-data --file %(EXISTIMG1)s")  # Preserve data shouldn't complain about existing volume
c.add_valid("-n clonetest --original-xml " + _CLONE_UNMANAGED + " --file %(EXISTIMG3)s --file %(EXISTIMG4)s --check path_exists=off")  # Skip existing file check
c.add_invalid("--auto-clone")  # Just the auto flag
c.add_invalid("--connect %(URI-TEST-FULL)s -o test-many-devices --auto-clone")  # VM is running, but --clone-running isn't passed
c.add_invalid("--connect %(URI-TEST-FULL)s -o test-clone-simple -n newvm --file %(EXISTIMG1)s --clone-running")  # Should complain about overwriting existing file


c = vclon.add_category("general", "-n clonetest")
c.add_valid("-o test --auto-clone")  # Auto flag, no storage
c.add_valid("-o test --file %(NEWCLONEIMG1)s --file %(NEWCLONEIMG2)s")  # Nodisk, but with spurious files passed
c.add_valid("-o test --file %(NEWCLONEIMG1)s --file %(NEWCLONEIMG2)s --prompt")  # Working scenario w/ prompt shouldn't ask anything
c.add_valid("--original-xml " + _CLONE_UNMANAGED + " --file %(NEWCLONEIMG1)s --file %(NEWCLONEIMG2)s")  # XML File with 2 disks
c.add_valid("--original-xml " + _CLONE_UNMANAGED + " --file virt-install --file %(EXISTIMG1)s --preserve")  # XML w/ disks, overwriting existing files with --preserve
c.add_valid("--original-xml " + _CLONE_UNMANAGED + " --file %(NEWCLONEIMG1)s --file %(NEWCLONEIMG2)s --file %(NEWCLONEIMG3)s --force-copy=hdc")  # XML w/ disks, force copy a readonly target
c.add_valid("--original-xml " + _CLONE_UNMANAGED + " --file %(NEWCLONEIMG1)s --file %(NEWCLONEIMG2)s --force-copy=fda")  # XML w/ disks, force copy a target with no media
c.add_valid("--original-xml " + _CLONE_MANAGED + " --file %(NEWIMG1)s")  # XML w/ managed storage, specify managed path
c.add_valid("--original-xml " + _CLONE_NOEXIST + " --file %(EXISTIMG1)s --preserve")  # XML w/ managed storage, specify managed path across pools# Libvirt test driver doesn't support cloning across pools# XML w/ non-existent storage, with --preserve
c.add_valid("--connect %(URI-TEST-FULL)s -o test -n test-clone --auto-clone --replace")  # Overwriting existing VM
c.add_invalid("-o test foobar")  # Positional arguments error
c.add_invalid("-o idontexist")  # Non-existent vm name
c.add_invalid("-o idontexist --auto-clone")  # Non-existent vm name with auto flag,
c.add_invalid("-o test -n test")  # Colliding new name
c.add_invalid("--original-xml " + _CLONE_UNMANAGED + "")  # XML file with several disks, but non specified
c.add_invalid("--original-xml " + _CLONE_UNMANAGED + " --file virt-install --file %(EXISTIMG1)s")  # XML w/ disks, overwriting existing files with no --preserve
c.add_invalid("--original-xml " + _CLONE_UNMANAGED + " --file %(NEWCLONEIMG1)s --file %(NEWCLONEIMG2)s --force-copy=hdc")  # XML w/ disks, force copy but not enough disks passed
c.add_invalid("--original-xml " + _CLONE_MANAGED + " --file /tmp/clonevol")  # XML w/ managed storage, specify unmanaged path (should fail)
c.add_invalid("--original-xml " + _CLONE_NOEXIST + " --file %(EXISTIMG1)s")  # XML w/ non-existent storage, WITHOUT --preserve
c.add_valid("--original-xml " + _CLONE_MANAGED + " --auto-clone --force-copy fda")  # force copy empty floppy drive




######################
# virt-convert tests #
######################

_OVF_IMG = "%s/tests/virtconv-files/ovf_input/test1.ovf" % os.getcwd()
_VMX_IMG = "%s/tests/virtconv-files/vmx_input/test1.vmx" % os.getcwd()

vconv = App("virt-convert")
c = vconv.add_category("misc", "--connect %(URI-KVM)s --dry")
c.add_invalid(_VMX_IMG + " --input-format foo")  # invalid input format
c.add_invalid("%(EXISTIMG1)s")  # invalid input file

c.add_compare(_VMX_IMG + " --disk-format qcow2 --print-xml", "vmx-compare")
c.add_compare(_OVF_IMG + " --disk-format none --destination /tmp --print-xml", "ovf-compare")


#################################
# argparse/autocomplete testing #
#################################

ARGCOMPLETE_CMDS = []


def _add_argcomplete_cmd(line, grep, nogrep=None):
    env = {
        "_ARGCOMPLETE": "1",
        "COMP_TYPE": "9",
        "COMP_POINT": str(len(line)),
        "COMP_LINE": line,
        "_ARGCOMPLETE_COMP_WORDBREAKS": "\"'><;|&(:",
    }
    cmd = Command(line)
    cmd.grep = grep
    if nogrep:
        cmd.nogrep = nogrep
    cmd.env = env
    cmd.need_conn = False
    def have_argcomplete():
        if not argcomplete:
            return "argcomplete not installed"
    cmd.skip_cb = have_argcomplete
    ARGCOMPLETE_CMDS.append(cmd)

_add_argcomplete_cmd("virt-install --di", "--disk")
_add_argcomplete_cmd("virt-install --disk ", "driver.copy_on_read=")  # will list all --disk subprops
_add_argcomplete_cmd("virt-install --disk a", "address.base")
_add_argcomplete_cmd("virt-install --disk address.u", "address.unit")
_add_argcomplete_cmd("virt-install --disk address.unit=foo,sg", "sgio")
_add_argcomplete_cmd("virt-install --disk path=fooo,", "driver.cache")  # will list all --disk subprops
_add_argcomplete_cmd("virt-install --disk source.seclab", "source.seclabel.relabel")  # completer should strip out regexes from results
_add_argcomplete_cmd("virt-install --check d", "disk_size")
_add_argcomplete_cmd("virt-install --location k", "kernel")
_add_argcomplete_cmd("virt-install --os-variant nam", "name")
_add_argcomplete_cmd("virt-install --test-stub", None,
        nogrep="--test-stub-command")
_add_argcomplete_cmd("virt-install --un", "--unattended")
_add_argcomplete_cmd("virt-install --unattended ", "profile=")  # will list all --unattended subprops
_add_argcomplete_cmd("virt-install --unattended p", "profile=")
_add_argcomplete_cmd("virt-install --unattended a", "admin-password=")
_add_argcomplete_cmd("virt-install --unattended u", "user-password=")
_add_argcomplete_cmd("virt-install --unattended prod", "product-key")
_add_argcomplete_cmd("virt-clone --preserve", "--preserve-data")
_add_argcomplete_cmd("virt-xml --sound mode", "model")
_add_argcomplete_cmd("virt-convert --dest", "--destination")


#########################
# Test runner functions #
#########################

newidx = 0
curtest = 0


def setup():
    """
    Create initial test files/dirs
    """
    for i in iso_links:
        src = "%s/%s" % (os.path.abspath(XMLDIR), os.path.basename(i))
        os.symlink(src, i)
    for i in exist_files:
        open(i, "a")


def cleanup():
    """
    Cleanup temporary files used for testing
    """
    for i in clean_files:
        os.system("chmod 777 %s > /dev/null 2>&1" % i)
        os.system("rm -rf %s > /dev/null 2>&1" % i)


class CLITests(unittest.TestCase):
    def setUp(self):
        global curtest
        curtest += 1
        # Only run this for first test
        if curtest == 1:
            setup()

    def tearDown(self):
        # Only run this on the last test
        if curtest == newidx:
            cleanup()


def maketest(cmd):
    def cmdtemplate(self, _cmdobj):
        _cmdobj.run(self)
    return lambda s: cmdtemplate(s, cmd)

_cmdlist = []
_cmdlist += vinst.cmds
_cmdlist += vclon.cmds
_cmdlist += vconv.cmds
_cmdlist += vixml.cmds
_cmdlist += ARGCOMPLETE_CMDS

# Generate numbered names like testCLI%d
for _cmd in _cmdlist:
    newidx += 1
    _name = "testCLI%.4d" % newidx
    if _cmd.compare_file:
        _base = os.path.splitext(os.path.basename(_cmd.compare_file))[0]
        _name += _base.replace("-", "_")
    else:
        _name += _cmd.app.replace("-", "_")
    setattr(CLITests, _name, maketest(_cmd))

atexit.register(cleanup)

# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import atexit
import io
import os
import shlex
import shutil
import sys
import traceback

import pytest

try:
    import argcomplete
except ImportError:
    argcomplete = None

from gi.repository import Libosinfo

from virtinst import log
from virtinst import OSDB
from virtinst.install import unattended

from tests import setup_logging
from tests import virtinstall, virtclone, virtxml
from tests import utils

os.environ["LANG"] = "en_US.UTF-8"
os.environ["HOME"] = "/tmp"
os.environ["DISPLAY"] = ":3.4"

TMP_IMAGE_DIR = "/tmp/__virtinst_cli_"
_ABSXMLDIR = utils.DATADIR + "/cli"
XMLDIR = os.path.relpath(_ABSXMLDIR, utils.TOPDIR)
MEDIA_DIR = os.path.relpath(utils.DATADIR + "/fakemedia", utils.TOPDIR)
UNATTENDED_DIR = XMLDIR + "/unattended"
OLD_OSINFO = utils.has_old_osinfo()
NO_OSINFO_UNATTEND = not unattended.OSInstallScript.have_new_libosinfo()
HAS_ISOINFO = shutil.which("isoinfo")

# We use this check as a surrogate for a released libosinfo with a bug
# fix we need to get full test coverage
LIBOSINFO_SUPPORT_LOCAL_TREE = hasattr(Libosinfo.Tree, "create_from_treeinfo")

# Images that will be created by virt-install/virt-clone, and removed before
# each run
NEW_FILES = [
    TMP_IMAGE_DIR + "new1.img",
    TMP_IMAGE_DIR + "new2.img",
    TMP_IMAGE_DIR + "new3.img",
    TMP_IMAGE_DIR + "exist1-clone.img",
    TMP_IMAGE_DIR + "exist2-clone.img",
]

# Images that are expected to exist before a command is run
EXIST_FILES = [
    TMP_IMAGE_DIR + "exist1.img",
    TMP_IMAGE_DIR + "exist2.img",
]


TEST_DATA = {
    'URI-TEST-FULL': utils.URIs.test_full,
    'URI-TEST-REMOTE': utils.URIs.test_remote,
    'URI-KVM': utils.URIs.kvm,
    'URI-KVM-ARMV7L': utils.URIs.kvm_armv7l,
    'URI-KVM-AARCH64': utils.URIs.kvm_aarch64,
    'URI-KVM-PPC64LE': utils.URIs.kvm_ppc64le,
    'URI-KVM-S390X': utils.URIs.kvm_s390x,
    'URI-QEMU-RISCV64': utils.URIs.qemu_riscv64,

    'XMLDIR': XMLDIR,
    'NEWIMG1': "/dev/default-pool/new1.img",
    'NEWIMG2': "/dev/default-pool/new2.img",
    'NEWCLONEIMG1': NEW_FILES[0],
    'NEWCLONEIMG2': NEW_FILES[1],
    'NEWCLONEIMG3': NEW_FILES[2],
    'EXISTIMG1': "/dev/default-pool/testvol1.img",
    'EXISTIMG2': "/dev/default-pool/testvol2.img",
    'EXISTIMG3': EXIST_FILES[0],
    'EXISTIMG4': EXIST_FILES[1],
    'ISOTREE': "%s/fake-fedora17-tree.iso" % MEDIA_DIR,
    'ISOLABEL': "%s/fake-centos65-label.iso" % MEDIA_DIR,
    'ISO-NO-OS': "%s/fake-no-osinfo.iso" % MEDIA_DIR,
    'ISO-WIN7': "%s/fake-win7.iso" % MEDIA_DIR,
    'ISO-F26-NETINST': "%s/fake-f26-netinst.iso" % MEDIA_DIR,
    'ISO-F29-LIVE': "%s/fake-f29-live.iso" % MEDIA_DIR,
    'TREEDIR': "%s/fakefedoratree" % MEDIA_DIR,
    'COLLIDE': "/dev/default-pool/collidevol1.img",
    'ADMIN-PASSWORD-FILE': "%s/admin-password.txt" % UNATTENDED_DIR,
    'USER-PASSWORD-FILE': "%s/user-password.txt" % UNATTENDED_DIR,
}


def has_old_osinfo():
    if OLD_OSINFO:
        return "osinfo is too old"


def missing_isoinfo():
    if not HAS_ISOINFO:
        return "isoinfo not installed"


def no_osinfo_unattend_cb():
    if NO_OSINFO_UNATTEND:
        return "osinfo is too old for unattended testing"


def no_osinfo_unattended_win_drivers_cb():
    win7 = OSDB.lookup_os("win7")
    devs = win7.get_pre_installable_devices("x86_64")
    devids = [d.get_id() for d in devs]
    if "http://pcisig.com/pci/1af4/1005" not in devids:
        return "osinfo is too old for this win7 unattended test"


######################
# Test class helpers #
######################

class SkipChecks:
    """
    Class to track all 'skip' style checks we might do. All checks
    can be callable functions, or version strings to check against libvirt

    :param prerun_check: If check resolves, skip before running the command
    :param precompare_check: If check resolves, skip after running the command
        but before comparing output
    :param predefine_check: If check resolves, skip after comparing output
        but before defining it
    """
    def __init__(self, parent_skip_checks,
                 precompare_check=None,
                 predefine_check=None,
                 prerun_check=None):
        p = parent_skip_checks

        self.precompare_check = precompare_check or (p and p.precompare_check)
        self.predefine_check = predefine_check or (
                p and p.predefine_check)
        self.prerun_check = prerun_check or (p and p.prerun_check)

    def _check(self, conn, check):
        if check is None:
            return

        if callable(check):
            msg = check()
            skip = bool(msg)
        else:
            skip = not conn.support._check_version(check)  # pylint: disable=protected-access
            msg = "Skipping check due to version < %s" % check

        if skip:
            raise pytest.skip(msg)

    def prerun_skip(self, conn):
        self._check(conn, self.prerun_check)

    def precompare_skip(self, conn):
        self._check(conn, self.precompare_check)

    def predefine_skip(self, conn):
        self._check(conn, self.predefine_check)


class Command(object):
    """
    Instance of a single cli command to test
    """
    def __init__(self, cmd, input_file=None, need_conn=True, grep=None,
                 nogrep=None, skip_checks=None, compare_file=None, env=None,
                 check_success=True, input_text=None, **kwargs):
        # Options that alter what command we run
        self.cmdstr = cmd % TEST_DATA
        app, opts = self.cmdstr.split(" ", 1)
        self.app = app
        self.argv = [os.path.abspath(app)] + shlex.split(opts)
        self.env = env
        self.input_file = input_file
        self.input_text = input_text
        self.need_conn = need_conn

        # Options that alter the results we check for
        self.check_success = check_success
        self.compare_file = compare_file
        self.grep = grep
        self.nogrep = nogrep

        # Options that determine when we skip tests
        self.skip_checks = SkipChecks(skip_checks, **kwargs)


    def _launch_command(self, conn):
        log.debug(self.cmdstr)

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
            elif self.input_text:
                sys.stdin = io.StringIO(self.input_text + "\n")
            else:
                sys.stdin = io.StringIO()
                sys.stdin.close()

            exc = ""
            try:
                if "virt-install" in app:
                    ret = virtinstall.main(conn=conn)
                elif "virt-clone" in app:
                    ret = virtclone.main(conn=conn)
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
            # Reset logging
            setup_logging()


    def _get_output(self, conn):
        try:
            cleanup(clean_all=False)

            code, output = self._launch_command(conn)

            log.debug("%s\n", output)
            return code, output
        except Exception as e:
            return (-1, "".join(traceback.format_exc()) + str(e))

    def _check_compare_file(self, conn, output):
        self.skip_checks.precompare_skip(conn)

        # Generate test files that don't exist yet
        filename = self.compare_file
        if (utils.TESTCONFIG.regenerate_output or
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

        self.skip_checks.predefine_skip(conn)

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
                    # pylint: disable=raise-missing-from
                    raise AssertionError("Bad XML:\n%s\n\nError was: %s: %s" %
                            (domxml, e.__class__.__name__, str(e)))

    def _run(self):
        conn = None
        for idx in reversed(range(len(self.argv))):
            if self.argv[idx] == "--connect":
                conn = utils.URIs.openconn(self.argv[idx + 1])
                break

        if not conn and self.need_conn:
            raise RuntimeError("couldn't parse URI from command %s" %
                               self.argv)

        self.skip_checks.prerun_skip(conn)
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
            self._check_compare_file(conn, output)

    def run(self):
        self._run()


class _CategoryProxy(object):
    """
    Category of an App. Let's us register chunks of suboptions per logical
    grouping of tests. So we may have a virt-install 'storage' group which
    specifies default install options like --pxe but leaves storage
    specification up to each individual test.
    """
    def __init__(self, app, name, default_args, **kwargs):
        self._app = app
        self._name = name

        self.default_args = default_args
        self.skip_checks = SkipChecks(self._app.skip_checks, **kwargs)

    def add_valid(self, *args, **kwargs):
        return self._app.add_valid(self._name, *args, **kwargs)
    def add_invalid(self, *args, **kwargs):
        return self._app.add_invalid(self._name, *args, **kwargs)
    def add_compare(self, *args, **kwargs):
        return self._app.add_compare(self._name, *args, **kwargs)


class App(object):
    """
    Represents a top level app test suite, like virt-install or virt-xml
    """
    def __init__(self, appname, uri=None, **kwargs):
        self.appname = appname
        self.categories = {}
        self.cmds = []
        self.skip_checks = SkipChecks(None, **kwargs)
        self.uri = uri

    def _default_args(self, cli, iscompare):
        args = ""
        if not iscompare:
            args = "--debug"

        if "--connect " not in cli:
            uri = self.uri or utils.URIs.test_suite
            args += " --connect %s" % uri

        if self.appname in ["virt-install"]:
            # Excluding 'lxc' is a hack. We need to remove this, but it
            # will take some work
            if "--ram " not in cli and "lxc" not in cli:
                args += " --ram 64"

        if iscompare:
            if self.appname == "virt-install":
                if ("--print-xml" not in cli and
                    "--print-step" not in cli and
                    "--quiet" not in cli):
                    args += " --print-step all"

            elif self.appname == "virt-clone":
                if "--print-xml" not in cli:
                    args += " --print-xml"
                    args += " --__test-nodry"

        return args


    def add_category(self, catname, default_args, *args, **kwargs):
        obj = _CategoryProxy(self, catname, default_args, *args, **kwargs)
        self.categories[catname] = obj
        return obj

    def _add(self, catname, testargs, compbase, **kwargs):
        category = self.categories[catname]
        args = category.default_args + " " + testargs

        use_default_args = kwargs.pop("use_default_args", True)
        if use_default_args:
            args = category.default_args + " " + testargs
            defargs = self._default_args(args, bool(compbase))
            args += " " + defargs
        else:
            args = testargs

        cmdstr = "./%s %s" % (self.appname, args)

        kwargs["skip_checks"] = category.skip_checks
        if compbase:
            compare_XMLDIR = "%s/compare" % XMLDIR
            kwargs["compare_file"] = "%s/%s-%s.xml" % (
                    compare_XMLDIR, os.path.basename(self.appname), compbase)

        cmd = Command(cmdstr, **kwargs)
        self.cmds.append(cmd)

    def add_valid(self, cat, args, **kwargs):
        self._add(cat, args, None, check_success=True, **kwargs)
    def add_invalid(self, cat, args, **kwargs):
        self._add(cat, args, None, check_success=False, **kwargs)
    def add_compare(self, cat, args, compbase, **kwargs):
        self._add(cat, args, compbase,
                  check_success=not compbase.endswith("-fail"),
                  **kwargs)



#
# The test matrix
#
# add_valid: A test that should pass
# add_invalid: A test that should fail
# add_compare: Get the generated XML, and compare against the passed filename
#              in tests/data/cli/compare/
#

######################
# virt-install tests #
######################

vinst = App("virt-install")

#############################################
# virt-install verbose XML comparison tests #
#############################################

c = vinst.add_category("xml-comparsion", "--connect %(URI-KVM)s --noautoconsole --os-variant fedora-unknown", prerun_check=has_old_osinfo)

# Singleton element test #1, for simpler strings
c.add_compare("""
--memory 1024
--uuid 12345678-12F4-1234-1234-123456789AFA
--vcpus 4,cores=2,threads=2,sockets=2 --cpuset=1,3-5
--cpu host-copy
--description \"foobar & baz\"
--boot uefi,smbios_mode=emulate,boot1.dev=hd,boot.dev=network,initarg1=bar=baz,initarg=foo
--seclabel type=dynamic
--security type=none,model=dac
--numatune 1,2,3,5-7,^6
--memorybacking hugepages=on
--features apic=off
--clock offset=localtime
--resource /virtualmachines/production
--events on_crash=restart
--metadata genid_enable=yes
--sysinfo host

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
--vsock default
""", "singleton-config-1")

# Singleton element test #2, for complex strings
c.add_compare("""--pxe
--memory 512,maxmemory=1024
--vcpus 9
--cpu foobar,+x2apic,+x2apicagain,-distest,forbid=foo,forbid=bar,disable=distest2,optional=opttest,require=reqtest,match=strict,vendor=meee,mode=custom,\
cell.id=0,cell.cpus=1,2,3,cell.memory=1024,\
cell1.id=1,cell1.memory=256,cell1.cpus=5-8,\
numa.cell2.id=2,numa.cell2.memory=256,numa.cell2.cpus=4,numa.cell2.memAccess=shared,numa.cell2.discard=no,\
cell0.distances.sibling0.id=0,cell0.distances.sibling0.value=10,\
cell0.distances.sibling1.id=1,cell0.distances.sibling1.value=21,\
numa.cell1.distances.sibling0.id=0,numa.cell1.distances.sibling0.value=21,\
cell1.distances.sibling1.id=1,cell1.distances.sibling1.value=10,\
cache.mode=emulate,cache.level=3
--cputune vcpupin0.vcpu=0,vcpupin0.cpuset=0-3,cachetune0.vcpus=0-3,cachetune0.cache0.level=3,cachetune0.cache0.id=0,cachetune0.cache0.type=both,cachetune0.cache0.size=3,cachetune0.cache0.unit=MiB,memorytune0.vcpus=0-3,memorytune0.node0.id=0,memorytune0.node0.bandwidth=60
--iothreads iothreads=2,iothreadids.iothread1.id=1,iothreadids.iothread2.id=2
--metadata title=my-title,description=my-description,uuid=00000000-1111-2222-3333-444444444444,genid=e9392370-2917-565e-692b-d057f46512d6
--boot cdrom,fd,hd,network,menu=off,loader=/foo/bar,emulator=/new/emu,bootloader=/new/bootld,rebootTimeout=3,initargs="foo=bar baz=woo",initdir=/my/custom/cwd,inituser=tester,initgroup=1000,firmware=efi
--idmap uid_start=0,uid_target=1000,uid_count=10,gid_start=0,gid_target=1000,gid_count=10
--seclabel type=static,label='system_u:object_r:svirt_image_t:s0:c100,c200',relabel=yes,baselabel=baselabel
--seclabel type=dynamic,label=012:345
--keywrap cipher0.name=aes,cipher0.state=on
--numatune 1-3,4,mode=strict,\
memnode0.cellid=1,memnode0.mode=strict,memnode0.nodeset=2
--memtune hard_limit=10,soft_limit=20,swap_hard_limit=30,min_guarantee=40
--blkiotune weight=100,device_path=/home/test/1.img,device_weight=200,read_bytes_sec=10000,write_bytes_sec=10000,read_iops_sec=20000,write_iops_sec=20000
--memorybacking size=1,unit='G',nodeset=0,1,nosharepages=yes,locked=yes,discard=yes,allocation.mode=immediate,access_mode=shared,source_type=file,hugepages.page.size=12,hugepages.page1.size=1234,hugepages.page1.unit=MB,hugepages.page1.nodeset=2
--features acpi=off,eoi=on,privnet=on,hyperv_synic=on,hyperv_reset=on,hyperv_spinlocks=on,hyperv_spinlocks_retries=5678,vmport=off,pmu=off,vmcoreinfo=on,kvm_hidden=off,hyperv_vapic=on
--clock offset=utc,hpet_present=no,rtc_tickpolicy=merge,timer2.name=hypervclock,timer3.name=pit,timer1.present=yes,timer3.tickpolicy=delay,timer2.present=no,timer4.name=rtc,timer5.name=tsc,timer6.name=tsc,timer4.track=wall,timer5.frequency=10,timer6.mode=emulate,timer7.name=rtc,timer7.tickpolicy=catchup,timer7.catchup.threshold=123,timer7.catchup.slew=120,timer7.catchup.limit=10000
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
--memballoon virtio,autodeflate=on,stats.period=10
--watchdog ib700,action=pause
--tpm passthrough,model=tpm-crb,path=/dev/tpm0,backend.encryption.secret=11111111-2222-3333-4444-5555555555
--rng egd,backend_host=127.0.0.1,backend_service=8000,backend_type=udp,backend_mode=bind,backend_connect_host=foo,backend_connect_service=708,rate.bytes=1234,rate.period=1000,model=virtio
--panic iobase=0x506
--iommu model=intel,driver.aw_bits=48,driver.caching_mode=on,driver.eim=off,driver.intremap=off,driver.iotlb=off
""", "singleton-config-2")


# Test the implied defaults for gl=yes setting virgl=on
c.add_compare("""
--vcpus vcpu.current=3,maxvcpus=4,vcpu.placement=auto
--memory hotplugmemorymax=2048,hotplugmemoryslots=2
--disk none
--features apic.eoi=off,hap=on,hyperv.synic.state=on,hyperv.reset.state=off,hyperv.spinlocks.state=on,hyperv.spinlocks.retries=5678,pae=on,pmu.state=on,pvspinlock.state=off,smm.state=off,viridian=on,vmcoreinfo.state=on,vmport.state=off,kvm.hidden.state=on,hyperv.vapic.state=off,hyperv.relaxed.state=off,gic.version=host,kvm.hint-dedicated.state=on
--clock rtc_present=no,pit_present=yes,pit_tickpolicy=catchup,tsc_present=no,platform_present=no,hypervclock_present=no,platform_tickpolicy=foo,hpet_tickpolicy=bar,tsc_tickpolicy=wibble,kvmclock_tickpolicy=wobble,hypervclock_tickpolicy=woo
--boot bios.useserial=no,bios.rebootTimeout=60,cmdline=root=/foo,smbios.mode=host,bootmenu.enable=yes,loader_ro=yes,loader.type=rom,loader=/tmp/foo
--memorybacking access.mode=shared,source.type=anonymous,hugepages=on
--graphics spice,gl=yes
--rng type=egd,backend.type=nmdm,backend.source.master=/dev/foo1,backend.source.slave=/dev/foo2
--panic default,,address.type=isa,address.iobase=0x500,address.irq=5
--cpu topology.sockets=1,topology.cores=3,topology.threads=2,cell0.cpus=0,cell0.memory=1048576
 --memdev dimm,access=private,target.size=512,target.node=0,source.pagesize=4,source.nodemask=1-2
 --memdev nvdimm,source.path=/path/to/nvdimm,target.size=512,target.node=0,target.label_size=128,alias.name=mymemdev3,address.type=dimm,address.base=0x100000000,address.slot=1
--vsock auto_cid=on
--memballoon default

--sysinfo bios.vendor="Acme LLC",bios.version=1.2.3,bios.date=01/01/1970,bios.release=10.22,system.manufacturer="Acme Inc.",system.product=Computer,system.version=3.2.1,system.serial=123456789,system.uuid=00000000-1111-2222-3333-444444444444,system.sku=abc-123,system.family=Server,baseBoard.manufacturer="Acme Corp.",baseBoard.product=Motherboard,baseBoard.version=A01,baseBoard.serial=1234-5678,baseBoard.asset=Tag,baseBoard.location=Chassis
--sysinfo type=fwcfg,entry0.name=foo,entry0.file=bar,entry0=baz
""", "singleton-config-3", predefine_check="5.7.0")



c.add_compare("""
--vcpus vcpus=4,cores=1,placement=static,\
vcpus.vcpu2.id=0,vcpus.vcpu2.enabled=no,\
vcpus.vcpu3.id=1,vcpus.vcpu3.hotpluggable=no,vcpus.vcpu3.enabled=yes,\
vcpus.vcpu.id=3,vcpus.vcpu0.enabled=yes,vcpus.vcpu0.order=3,\
vcpus.vcpu1.id=2,vcpus.vcpu1.enabled=yes
--cpu none
--iothreads 5

--disk type=block,source.dev=/dev/default-pool/UPPER,cache=writeback,io=threads,perms=sh,serial=WD-WMAP9A966149,wwn=123456789abcdefa,boot_order=2,driver.iothread=3
--disk source.file=%(NEWIMG1)s,sparse=false,size=.001,perms=ro,error_policy=enospace,discard=unmap,detect_zeroes=unmap,address.type=drive,address.controller=0,address.target=2,address.unit=0
--disk device=cdrom,bus=sata,read_bytes_sec=1,read_iops_sec=2,write_bytes_sec=5,write_iops_sec=6,driver.copy_on_read=on,geometry.cyls=16383,geometry.heads=16,geometry.secs=63,geometry.trans=lba
--disk size=1
--disk /iscsi-pool/diskvol1,total_bytes_sec=10,total_iops_sec=20,bus=scsi,device=lun,sgio=unfiltered,rawio=yes
--disk /dev/default-pool/iso-vol,seclabel.model=dac,seclabel1.model=selinux,seclabel1.relabel=no,seclabel0.label=foo,bar,baz,iotune.read_bytes_sec=1,iotune.read_iops_sec=2,iotune.write_bytes_sec=5,iotune.write_iops_sec=6
--disk /dev/default-pool/iso-vol,format=qcow2,startup_policy=optional,iotune.total_bytes_sec=10,iotune.total_iops_sec=20,
--disk source_pool=rbd-ceph,source_volume=some-rbd-vol,size=.1,driver_type=raw
--disk pool=rbd-ceph,size=.1,driver.name=qemu,driver.type=raw,driver.discard=unmap,driver.detect_zeroes=unmap,driver.io=native,driver.error_policy=stop
--disk source_protocol=http,source_host_name=example.com,source_host_port=8000,source_name=/path/to/my/file
--disk source.protocol=http,source.host0.name=exampl2.com,source.host.port=8000,source.name=/path/to/my/file
--disk source.protocol=nbd,source.host.transport=unix,source.host.socket=/tmp/socket
--disk source.protocol=nbd,source_host_transport=unix,source_host_socket=/tmp/socket,bus=scsi,logical_block_size=512,physical_block_size=512,blockio.logical_block_size=512,blockio.physical_block_size=512,target.dev=sdz
--disk gluster://192.168.1.100/test-volume/some/dir/test-gluster.qcow2
--disk nbd+unix:///var/foo/bar/socket,bus=usb,removable=on,address.type=usb,address.bus=0,address.port=2
--disk path=http://[1:2:3:4:1:2:3:4]:5522/my/path?query=foo
--disk vol=gluster-pool/test-gluster.raw
--disk /var,device=floppy,snapshot=no,perms=rw
--disk %(NEWIMG2)s,size=1,backing_store=/tmp/foo.img,backing_format=vmdk,bus=usb,target.removable=yes
--disk /tmp/brand-new.img,size=1,backing_store=/dev/default-pool/iso-vol,boot.order=10,boot.loadparm=5
--disk path=/dev/disk-pool/diskvol7,device=lun,bus=scsi,reservations.managed=no,reservations.source.type=unix,reservations.source.path=/var/run/test/pr-helper0.sock,reservations.source.mode=client,\
source.reservations.managed=no,source.reservations.source.type=unix,source.reservations.source.path=/var/run/test/pr-helper0.sock,source.reservations.source.mode=client
--disk vol=iscsi-direct/unit:0:0:1
--disk size=.0001,format=raw
--disk size=.0001,pool=disk-pool
--disk path=%(EXISTIMG1)s,type=dir
--disk path=/fooroot.img,size=.0001
--disk source.dir=/
--disk type=nvme,source.type=pci,source.managed=no,source.namespace=2,source.address.domain=0x0001,source.address.bus=0x02,source.address.slot=0x00,source.address.function=0x0

--network user,mac=12:34:56:78:11:22,portgroup=foo,link_state=down,rom_bar=on,rom_file=/tmp/foo
--network bridge=foobar,model=virtio,driver_name=qemu,driver_queues=3,filterref=foobar,rom.bar=off,rom.file=/some/rom,source.portgroup=foo
--network bridge=ovsbr,virtualport.type=openvswitch,virtualport_profileid=demo,virtualport_interfaceid=09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b,link.state=yes,driver.name=qemu,driver.queues=3,filterref.filter=filterbar,target.dev=mytargetname,virtualport.parameters.profileid=demo,virtualport.parameters.interfaceid=09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b
--network type=direct,source=eth5,source_mode=vepa,source.mode=vepa,target=mytap12,virtualport_type=802.1Qbg,virtualport_managerid=12,virtualport_typeid=1193046,virtualport_typeidversion=1,virtualport_instanceid=09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b,boot_order=1,trustGuestRxFilters=yes,mtu.size=1500,virtualport.parameters.managerid=12,virtualport.parameters.typeid=1193046,virtualport.parameters.typeidversion=1,virtualport.parameters.instanceid=09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b,boot_order=1,trustGuestRxFilters=yes,mtu.size=1500
--network user,model=virtio,address.type=spapr-vio,address.reg=0x500,link.state=no
--network vhostuser,source_type=unix,source_path=/tmp/vhost1.sock,source_mode=server,model=virtio,source.type=unix,source.path=/tmp/vhost1.sock,address.type=pci,address.bus=0x00,address.slot=0x10,address.function=0x0,address.domain=0x0000
--network user,address.type=ccw,address.cssid=0xfe,address.ssid=0,address.devno=01,boot.order=15,boot.loadparm=SYSTEM1
--network model=vmxnet3

--graphics sdl
--graphics spice,keymap=none
--graphics vnc,port=5950,listen=1.2.3.4,keymap=ja,password=foo
--graphics vnc,port=5950,listen=1.2.3.4,keymap=ja,password=foo,websocket=15950
--graphics vnc,port=5950,listen=1.2.3.4,keymap=ja,password=foo,websocket=-1
--graphics spice,port=5950,tlsport=5950,listen=1.2.3.4,keymap=ja
--graphics spice,image_compression=glz,streaming_mode=filter,clipboard_copypaste=yes,mouse_mode=client,filetransfer_enable=on,zlib.compression=always
--graphics spice,gl=yes,listen=socket,image.compression=glz,streaming.mode=filter,clipboard.copypaste=yes,mouse.mode=client,filetransfer.enable=on,tlsPort=6000,passwd=testpass,passwdValidTo=2010-04-09T15:51:00,passwordValidTo=2010-04-09T15:51:01,defaultMode=insecure
--graphics spice,gl=yes,listen=none
--graphics spice,gl.enable=yes,listen=none,rendernode=/dev/dri/foo,gl.rendernode=/dev/dri/foo2
--graphics spice,listens0.type=address,listens0.address=1.2.3.4,connected=disconnect
--graphics spice,listens0.type=network,listens0.network=default
--graphics spice,listens0.type=socket,listens0.socket=/tmp/foobar

--controller usb,model=ich9-ehci1,address=0:0:4.7,index=0
--controller usb,model=ich9-uhci1,address=0:0:4.0,index=0,master=0,address.multifunction=on
--controller usb,model=ich9-uhci2,address=0:0:4.1,index=0,master.startport=2
--controller usb,model=ich9-uhci3,address=0:0:4.2,index=0,master=4
--controller scsi,,model=virtio-scsi,driver_queues=4,driver.queues=4,driver.iothread=2,vectors=15
--controller xenbus,maxGrantFrames=64

--input type=keyboard,bus=usb
--input tablet
--input mouse

--serial char_type=tcp,host=:2222,mode=bind,protocol=telnet,log.file=/tmp/foo.log,log.append=yes,,target.model.name=pci-serial
--serial nmdm,source.master=/dev/foo1,source.slave=/dev/foo2,alias.name=testalias7
--parallel type=udp,host=0.0.0.0:1234,bind_host=127.0.0.1:1234
--parallel udp,source.connect_host=127.0.0.2,source.connect_service=8888,source.bind_host=127.0.0.1,source.bind_service=7777
--parallel unix,path=/tmp/foo-socket,source.seclabel0.model=none,source.seclabel1.model=dac,source.seclabel1.relabel=yes,source.seclabel1.label=foobar,source.seclabel.relabel=no
--channel pty,target_type=guestfwd,target_address=127.0.0.1:10000
--channel pty,target_type=guestfwd,target.address=127.0.0.1,target.port=1234
--channel pty,target_type=virtio,name=org.linux-kvm.port1
--channel pty,target.type=virtio,target.name=org.linux-kvm.port2
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
--hostdev wlan0,type=net
--hostdev /dev/vdz,type=storage
--hostdev /dev/pty7,type=misc


--filesystem /source,/target,alias.name=testfsalias,driver.ats=on,driver.iommu=off,driver.packed=on
--filesystem template_name,/,type=template,mode=passthrough
--filesystem type=file,source=/tmp/somefile.img,target=/mount/point,accessmode=squash,driver.format=qcow2,driver.type=path,driver.wrpolicy=immediate
--filesystem type-mount,source.dir=/,target=/
--filesystem type=template,source.name=foo,target=/
--filesystem type=file,source.file=foo.img,target=/
--filesystem type=volume,model=virtio,multidevs=remap,readonly=on,space_hard_limit=1234,space_soft_limit=500,source.pool=pool1,source.volume=vol,driver.name=virtiofs,driver.queue=3,binary.path=/foo/virtiofsd,binary.xattr=off,binary.cache.mode=always,binary.lock.posix=off,binary.lock.flock=on,target.dir=/foo
--filesystem type=block,source.dev=/dev/foo,target.dir=/
--filesystem type=ram,source.usage=1024,source.units=MiB,target=/

--soundhw default
--sound ac97
--sound codec0.type=micro,codec1.type=duplex,codec2.type=output

--video cirrus
--video model=qxl,vgamem=1,ram=2,vram=3,heads=4,accel3d=yes,vram64=65
--video model=qxl,model.vgamem=1,model.ram=2,model.vram=3,model.heads=4,model.acceleration.accel3d=yes,model.vram64=65

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

--rng device=/dev/urandom,backend.protocol.type=,backend.log.file=,backend.log.append=

--panic iobase=507

--vsock cid=17

--tpm emulator,model=tpm-crb,version=2.0

--qemu-commandline env=DISPLAY=:0.1
--qemu-commandline="-display gtk,gl=on"
--qemu-commandline="-device vfio-pci,addr=05.0,sysfsdev=/sys/class/mdev_bus/0000:00:02.0/f321853c-c584-4a6b-b99a-3eee22a3919c"
--qemu-commandline="-set device.video0.driver=virtio-vga"
--qemu-commandline args="-foo bar"

--xml /domain/@foo=bar
--xml xpath.set=./baz,xpath.value=wib
--xml ./deleteme/deleteme2/deleteme3=foo
--xml ./t1/t2/@foo=123
--xml ./devices/graphics[1]/ab=cd
--xml ./devices/graphics[2]/@ef=hg
--xml xpath.create=./barenode
--xml xpath.delete=./deleteme/deleteme2
""", "many-devices", predefine_check="5.3.0")




########################
# Boot install options #
########################

c = vinst.add_category("boot", "--nographics --noautoconsole --import --disk none --controller usb,model=none")
c.add_compare("--boot loader=/path/to/loader,loader_secure=yes", "boot-loader-secure")




####################################################
# CPU/RAM/numa and other singleton VM config tests #
####################################################

c = vinst.add_category("cpuram", "--hvm --nographics --noautoconsole --nodisks --pxe")
c.add_valid("--ram 4000000")  # Ram overcommit
c.add_valid("--vcpus sockets=2,threads=2")  # Topology only
c.add_valid("--cpuset 1,2,3")  # cpuset backcompat with no --vcpus specified
c.add_valid("--cpu somemodel")  # Simple --cpu
c.add_valid("--noapic --noacpi")  # feature backcompat
c.add_valid("--security label=foobar.label,relabel=yes")  # --security implicit static
c.add_valid("--security label=foobar.label,a1,z2,b3,type=static,relabel=no")  # static with commas 1
c.add_valid("--security label=foobar.label,a1,z2,b3")  # --security static with commas 2
c.add_invalid("--clock foo_tickpolicy=merge")  # Unknown timer
c.add_invalid("--security foobar")  # Busted --security
c.add_compare("--cpuset auto --vcpus 2", "cpuset-auto")  # --cpuset=auto actually works
c.add_compare("--memory hotplugmemorymax=2048,hotplugmemoryslots=2 --cpu cell0.cpus=0,cell0.memory=1048576 --memdev dimm,access=private,target_size=512,target_node=0,source_pagesize=4,source_nodemask=1-2 --memdev nvdimm,source_path=/path/to/nvdimm,target_size=512,target_node=0,target_label_size=128,alias.name=mymemdev3", "memory-hotplug", precompare_check="5.3.0")
c.add_compare("--memory currentMemory=100,memory=200,maxmemory=300,maxMemory=400,maxMemory.slots=1", "memory-option-backcompat", precompare_check="5.3.0")
c.add_compare("--connect " + utils.URIs.kvm_q35 + " --cpu qemu64,secure=off", "cpu-disable-sec")  # disable security features that are added by default
c.add_compare("--connect " + utils.URIs.kvm_rhel, "cpu-rhel7-default", precompare_check="5.1.0")  # default CPU for old QEMU where we cannot use host-model



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
c.add_valid("--connect %(URI-KVM)s --disk /dev/default-pool/sharevol.img,perms=sh")  # Colliding shareable storage
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
c.add_invalid("--disk device=disk", grep="requires a path")  # --disk device=disk, but no path
c.add_invalid("--disk pool=disk-pool,size=1,format=qcow2", grep="Format attribute not supported")  # format= invalid for disk pool
c.add_invalid("--disk pool=foopool,size=.0001")  # Specify a nonexistent pool
c.add_invalid("--disk vol=default-pool/foovol")  # Specify a nonexistent volume
c.add_invalid("--disk vol=default-pool-no-slash")  # Wrong vol= format
c.add_invalid("--disk perms=badformat")  # Wrong perms= format
c.add_invalid("--disk size=badformat")  # Wrong size= format
c.add_invalid("--disk pool=default-pool")  # Specify a pool with no size
c.add_invalid("--disk path=%(EXISTIMG1)s,perms=ro,size=.0001,cache=FOOBAR")  # Unknown cache type
c.add_invalid("--disk path=/dev/foo/bar/baz,format=qcow2,size=.0000001")  # Unmanaged file using non-raw format
c.add_invalid("--disk path=/dev/disk-pool/newvol1.img,format=raw,size=.0000001")  # Managed disk using any format
c.add_invalid("--disk %(NEWIMG1)s")  # Not specifying path= and non existent storage w/ no size
c.add_invalid("--disk %(NEWIMG1)s,sparse=true,size=100000000000")  # Fail if fully allocated file would exceed disk space
c.add_invalid("--connect %(URI-TEST-FULL)s --disk %(COLLIDE)s")  # Colliding storage without --force
c.add_invalid("--connect %(URI-TEST-FULL)s --disk %(COLLIDE)s --prompt")  # Colliding storage with --prompt should still fail
c.add_invalid("--connect %(URI-TEST-FULL)s --disk /dev/default-pool/backingl3.img")  # Colliding storage via backing store
c.add_invalid("--disk %(EXISTIMG1)s,driver_name=foobar,driver_type=foobaz")  # Unknown driver name and type options (as of 1.0.0)
c.add_invalid("--connect %(URI-TEST-FULL)s --disk source_pool=rbd-ceph,source_volume=vol1")  # Collision with existing VM, via source pool/volume
c.add_invalid("--disk source.pool=default-pool,source.volume=idontexist")  # trying to lookup non-existent volume, hit specific error code
c.add_invalid("--disk size=1 --security model=foo,type=bar")  # Libvirt will error on the invalid security params, which should trigger the code path to clean up the disk images we created.
c.add_invalid("--disk size=1 --file foobar")  # --disk and --file collision



################################################
# Invalid devices that hit virtinst code paths #
################################################

c = vinst.add_category("invalid-devices", "--noautoconsole --nodisks --pxe")
c.add_invalid("--connect %(URI-TEST-FULL)s --host-device 1d6b:2")  # multiple USB devices with identical vendorId and productId
c.add_invalid("--connect %(URI-TEST-FULL)s --host-device pci_8086_2850_scsi_host_scsi_host")  # Unsupported hostdev type
c.add_invalid("--host-device foobarhostdev")  # Unknown hostdev
c.add_invalid("--host-device 300:400")  # Parseable hostdev, but unknown digits
c.add_invalid("--controller address=foobar")  # Invalid address= value
c.add_invalid("--graphics vnc,port=-50")  # Invalid port
c.add_invalid("--graphics spice,tlsport=5")  # Invalid port
c.add_invalid("--vnc --sdl")  # Multi graphics collision
c.add_invalid("--serial unix")  # Unix with no path
c.add_invalid("--channel pty,target_type=guestfwd")  # --channel guestfwd without target_address
c.add_invalid("--boot uefi")  # URI doesn't support UEFI bits
c.add_invalid("--connect %(URI-KVM)s --boot uefi,arch=ppc64")  # unsupported arch for UEFI
c.add_invalid("--features smm=on --machine pc")  # smm=on doesn't work for machine=pc
c.add_invalid("--graphics type=vnc,keymap", grep="Option 'keymap' had no value set.")
c.add_invalid("--xml FOOXPATH", grep="form of XPATH=VALUE")  # failure parsing xpath value
c.add_invalid("--xml /@foo=bar", grep="/@foo xmlXPathEval")  # failure processing xpath



########################
# Install option tests #
########################

c = vinst.add_category("nodisk-install", "--nographics --noautoconsole --nodisks")
c.add_valid("--hvm --cdrom %(EXISTIMG1)s")  # Simple cdrom install
c.add_valid("--pxe --ram 16", grep="Requested memory 16 MiB is abnormally low")  # catch low memory error
c.add_valid("--os-variant winxp --ram 32 --cdrom %(EXISTIMG1)s", grep="32 MiB is less than the recommended 64 MiB")  # Windows. Catch memory warning
c.add_valid("--pxe --virt-type test")  # Explicit virt-type
c.add_valid("--arch i686 --pxe")  # Explicitly fullvirt + arch
c.add_valid("--location location=%(TREEDIR)s")  # Directory tree URL install
c.add_valid("--location %(TREEDIR)s --initrd-inject virt-install --extra-args ks=file:/virt-install")  # initrd-inject
c.add_valid("--hvm --location %(TREEDIR)s --extra-args console=ttyS0")  # Directory tree URL install with extra-args
c.add_valid("--paravirt --location %(TREEDIR)s")  # Paravirt location
c.add_valid("--location %(TREEDIR)s --os-variant fedora12")  # URL install with manual os-variant
c.add_valid("--cdrom %(EXISTIMG2)s --os-variant win2k3")  # HVM windows install with disk
c.add_valid("--cdrom %(EXISTIMG2)s --os-variant win2k3 --print-step 2")  # HVM windows install, print 3rd stage XML
c.add_valid("--pxe --autostart")  # --autostart flag
c.add_compare("--cdrom http://example.com/path/to/some.iso", "cdrom-url")
c.add_compare("--pxe --print-step all --os-variant none", "simple-pxe")  # Diskless PXE install
c.add_compare("--location ftp://example.com --os-variant auto", "fake-ftp")  # fake ftp:// install using urlfetcher.py mocking
c.add_compare("--location https://foobar.com --os-variant detect=no", "fake-http")  # fake https:// install using urlfetcher.py mocking, but also hit --os-variant detect=no
c.add_compare("--location https://foobar.com --os-variant detect=yes,name=win7", "os-detect-success-fallback")  # os detection succeeds, so fallback should be ignored
c.add_compare("--pxe --os-variant detect=yes,name=win7", "os-detect-fail-fallback")  # os detection succeeds, so fallback should be ignored
c.add_compare("--connect %(URI-KVM)s --install fedora26", "osinfo-url")  # getting URL from osinfo
c.add_invalid("--pxe --os-variant detect=yes,require=yes", grep="An --os-variant is required")  # No os-variant detected, but require=yes
c.add_invalid("--pxe --virt-type bogus")  # Bogus virt-type
c.add_invalid("--pxe --arch bogus")  # Bogus arch
c.add_invalid("--livecd")  # LiveCD with no media
c.add_invalid("--pxe --os-variant farrrrrrrge")  # Bogus --os-variant
c.add_invalid("--pxe --boot menu=foobar")
c.add_invalid("--cdrom %(EXISTIMG1)s --extra-args console=ttyS0")  # cdrom fail w/ extra-args
c.add_invalid("--hvm --boot kernel=%(TREEDIR)s/pxeboot/vmlinuz,initrd=%(TREEDIR)s/pxeboot/initrd.img,kernel_args='foo bar' --initrd-inject virt-install")  # initrd-inject with manual kernel/initrd
c.add_invalid("--disk none --location kernel=/dev/null,initrd=/dev/null")  # --location with manual kernel/initrd, but not URL
c.add_invalid("--install winxp", grep="does not have a URL location")  # no URL for winxp
c.add_invalid("--arch i686 --install fedora26", grep="does not have a URL location for the architecture 'i686")  # there's no URL for i686
c.add_invalid("-c foo --cdrom bar", grep="Cannot use -c")  # check for ambiguous -c and --cdrom collision
c.add_invalid("-c qemu:///system", grep="looks like a libvirt URI")  # error for the ambiguous -c vs --connect
c.add_invalid("--location /", grep="Error validating install location")  # detect_distro failure
c.add_invalid("--os-variant id=foo://bar", grep="Unknown libosinfo ID")  # bad full id
c.add_invalid("--location http://testsuitefail.com", grep="installable distribution")  # will trigger a particular mock failure



c = vinst.add_category("single-disk-install", "--nographics --noautoconsole --disk %(EXISTIMG1)s")
c.add_valid("--hvm --import")  # FV Import install
c.add_valid("--hvm --install no_install=yes")  # import install equivalent
c.add_valid("--hvm --import --prompt --force")  # Working scenario w/ prompt shouldn't ask anything
c.add_valid("--paravirt --import")  # PV Import install
c.add_valid("--paravirt --print-xml 1")  # print single XML, implied import install
c.add_valid("--hvm --import --wait 0", grep="Treating --wait 0 as --noautoconsole")  # --wait 0 is the same as --noautoconsole
c.add_compare("-c %(EXISTIMG2)s --osinfo win2k3 --vcpus cores=4 --controller usb,model=none", "w2k3-cdrom")  # HVM windows install with disk
c.add_compare("--connect %(URI-KVM)s --install fedora26 --os-variant fedora27 --disk size=20", "osinfo-url-with-disk")  # filling in defaults, but with disk specified, and making sure we don't overwrite --os-variant
c.add_compare("--connect %(URI-KVM)s --pxe --os-variant short-id=debianbuster --disk none", "osinfo-multiple-short-id", prerun_check=lambda: not OSDB.lookup_os("debianbuster"))  # test plumbing for multiple short ids
c.add_invalid("--hvm --import --wait 2", grep="exceeded specified time limit")  # --wait positive number, but test suite hack
c.add_invalid("--hvm --import --wait -1", grep="exceeded specified time limit")  # --wait -1, but test suite hack
c.add_invalid("--hvm --import --wait", grep="exceeded specified time limit")  # --wait aka --wait -1, but test suite hack
c.add_invalid("--connect test:///default --name foo --ram 64 --disk none --sdl --hvm --import", use_default_args=False, grep="exceeded specified time limit")  # --sdl doesn't have a console callback, triggers implicit --wait -1
c.add_invalid("--paravirt --import --print-xml 2")  # PV Import install, no second XML step
c.add_invalid("--paravirt --import --print-xml 7")  # Invalid --print-xml arg
c.add_invalid("--location kernel=foo,initrd=bar")  # location kernel/initrd without any url
c.add_invalid("--location http://example.com,kernel=foo")  # location without kernel+initrd specified as pair

c = vinst.add_category("misc-install", "--nographics --noautoconsole")
c.add_compare("--connect %s" % (utils.URIs.test_suite), "noargs-fail", use_default_args=False)  # No arguments
c.add_compare("--connect %s --os-variant fedora26" % (utils.URIs.test_suite), "osvariant-noargs-fail", use_default_args=False)  # No arguments
c.add_compare("--connect %s --os-variant fedora26 --pxe --print-xml" % (utils.URIs.test_suite), "osvariant-defaults-pxe", use_default_args=False)  # No arguments
c.add_compare("--disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init", "cloud-init-default")  # default --cloud-init behavior is root-password-generate=yes,disable=yes
c.add_compare("--disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init root-password-generate=yes,disable=no", "cloud-init-options")  # --cloud-init root-password-generate
c.add_compare("--disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init root-password-file=%(ADMIN-PASSWORD-FILE)s,disable=no", "cloud-init-options")  # --cloud-init root-password-file
c.add_compare("--disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init ssh-key=%(XMLDIR)s/cloudinit/ssh-key.txt", "cloud-init-options")  # --cloud-init ssh-key
c.add_compare("--disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init user-data=%(XMLDIR)s/cloudinit/user-data.txt,meta-data=%(XMLDIR)s/cloudinit/meta-data.txt", "cloud-init-options")  # --cloud-init user-data=,meta-data=
c.add_valid("--panic help --disk=? --check=help", grep="path_in_use")  # Make sure introspection doesn't blow up
c.add_valid("--connect test:///default --test-stub-command", use_default_args=False)  # --test-stub-command
c.add_valid("--nodisks --pxe", grep="VM performance may suffer")  # os variant warning
c.add_invalid("--hvm --nodisks --pxe foobar")  # Positional arguments error
c.add_invalid("--nodisks --pxe --name test")  # Colliding name
c.add_compare("--os-type linux --cdrom %(EXISTIMG1)s --disk size=1 --disk %(EXISTIMG2)s,device=cdrom", "cdrom-double")  # ensure --disk device=cdrom is ordered after --cdrom, this is important for virtio-win installs with a driver ISO
c.add_valid("--connect %s --pxe --disk size=1" % utils.URIs.test_defaultpool_collision)  # testdriver already has a pool using the 'default' path, make sure we don't error
c.add_compare("--connect %(URI-KVM)s --reinstall test-clone-simple --pxe", "reinstall-pxe")  # compare --reinstall with --pxe
c.add_compare("--connect %(URI-KVM)s --reinstall test-clone-simple --location http://example.com", "reinstall-location")  # compare --reinstall with --location
c.add_compare("--reinstall test-cdrom --cdrom %(ISO-WIN7)s --unattended", "reinstall-cdrom")  # compare --reinstall with --cdrom handling
c.add_invalid("--reinstall test --cdrom %(ISO-WIN7)s", grep="already active")  # trying to reinstall an active VM should fail
c.add_invalid("--reinstall test", grep="install method must be specified")  # missing install method


####################
# Unattended tests #
####################

c = vinst.add_category("unattended-install", "--connect %(URI-KVM)s --nographics --noautoconsole --disk none", prerun_check=no_osinfo_unattend_cb)
c.add_compare("--install fedora26 --unattended profile=desktop,admin-password-file=%(ADMIN-PASSWORD-FILE)s,user-password-file=%(USER-PASSWORD-FILE)s,product-key=1234,user-login=foobar,reg-login=regtest", "osinfo-url-unattended", prerun_check=lambda: not unattended.OSInstallScript.have_libosinfo_installation_url())  # unattended install for fedora, using initrd injection
c.add_compare("--location %(TREEDIR)s --unattended", "osinfo-unattended-treeapis", prerun_check=lambda: not LIBOSINFO_SUPPORT_LOCAL_TREE)  # unattended install using treeobj libosinfo APIs
c.add_compare("--cdrom %(ISO-WIN7)s --unattended profile=desktop,admin-password-file=%(ADMIN-PASSWORD-FILE)s", "osinfo-win7-unattended", prerun_check=no_osinfo_unattended_win_drivers_cb)  # unattended install for win7
c.add_compare("--os-variant fedora26 --unattended profile=jeos,admin-password-file=%(ADMIN-PASSWORD-FILE)s --location %(ISO-F26-NETINST)s", "osinfo-netinst-unattended")  # triggering the special netinst checking code
c.add_compare("--os-variant silverblue29 --location http://example.com", "network-install-resources")  # triggering network-install resources override
c.add_compare("--connect %(URI-TEST-REMOTE)s --os-variant win7 --cdrom %(EXISTIMG1)s --unattended", "unattended-remote-cdrom")
c.add_valid("--pxe --os-variant fedora26 --unattended", grep="Using unattended profile 'desktop'")  # filling in default 'desktop' profile
c.add_invalid("--os-variant fedora26 --unattended profile=jeos --location http://example.foo", grep="admin-password")  # will trigger admin-password required error
c.add_invalid("--os-variant fedora26 --unattended profile=jeos --location http://example.foo", grep="admin-password")  # will trigger admin-password required error
c.add_invalid("--os-variant fedora26 --unattended profile=jeos --location http://example.foo", grep="admin-password")  # will trigger admin-password required error
c.add_invalid("--os-variant debian9 --unattended profile=desktop,admin-password-file=%(ADMIN-PASSWORD-FILE)s --location http://example.foo", grep="user-password")  # will trigger user-password required error
c.add_invalid("--os-variant debian9 --unattended profile=FRIBBER,admin-password-file=%(ADMIN-PASSWORD-FILE)s --location http://example.foo", grep="Available profiles")  # will trigger unknown profile error
c.add_invalid("--os-variant fedora29 --unattended profile=desktop,admin-password-file=%(ADMIN-PASSWORD-FILE)s --cdrom %(ISO-F29-LIVE)s", grep="media does not support")  # live media doesn't support installscript
c.add_invalid("--os-variant msdos --unattended profile=desktop --location http://example.com")  # msdos doesn't support unattended install
c.add_invalid("--os-variant winxp --unattended profile=desktop --cdrom %(ISO-WIN7)s")  # winxp doesn't support expected injection method 'cdrom'
c.add_invalid("--install fedora29 --unattended user-login=root", grep="as user-login")  # will trigger an invalid user-login error


#############################
# Remote URI specific tests #
#############################

c = vinst.add_category("remote", "--connect %(URI-TEST-REMOTE)s --nographics --noautoconsole")
c.add_valid("--nodisks --pxe")  # Simple pxe nodisks
c.add_valid("--cdrom %(EXISTIMG1)s --disk none --livecd --dry")  # remote cdrom install
c.add_compare("--pxe "
"--pxe --disk /foo/bar/baz,size=.01 "  # Creating any random path on the remote host
"--disk /dev/zde ", "remote-storage")  # /dev file that we just pass through to the remote VM
c.add_invalid("--pxe --disk /foo/bar/baz")  # File that doesn't exist after auto storage setup
c.add_invalid("--nodisks --location /tmp")  # Use of --location
c.add_invalid("--file /foo/bar/baz --pxe")  # Trying to use unmanaged storage without size argument



###########################
# QEMU/KVM specific tests #
###########################

c = vinst.add_category("kvm-generic", "--connect %(URI-KVM)s --autoconsole none")
c.add_compare("--os-variant fedora-unknown --file %(EXISTIMG1)s --location %(TREEDIR)s --extra-args console=ttyS0 --cpu host --channel none --console none --sound none --redirdev none --boot cmdline='foo bar baz'", "kvm-fedoralatest-url", prerun_check=has_old_osinfo)  # Fedora Directory tree URL install with extra-args
c.add_compare("--test-media-detection %(TREEDIR)s --arch x86_64 --hvm", "test-url-detection")  # --test-media-detection
c.add_compare("--os-variant http://fedoraproject.org/fedora/20 --disk %(EXISTIMG1)s,device=floppy --disk %(NEWIMG1)s,size=.01,format=vmdk --location %(TREEDIR)s --extra-args console=ttyS0 --quiet", "quiet-url", prerun_check=has_old_osinfo)  # Quiet URL install should make no noise
c.add_compare("--cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --sound --controller usb", "kvm-win2k3-cdrom")  # HVM windows install with disk
c.add_compare("--os-variant name=ubuntusaucy --nodisks --boot cdrom --virt-type qemu --cpu Penryn --input tablet --boot uefi --graphics vnc", "qemu-plain")  # plain qemu
c.add_compare("--os-variant fedora20 --nodisks --boot network --graphics default --arch i686 --rng none", "qemu-32-on-64", prerun_check=has_old_osinfo)  # 32 on 64

# ppc64 tests
c.add_compare("--arch ppc64 --machine pseries --boot network --disk %(EXISTIMG1)s --disk device=cdrom --os-variant fedora20 --network none", "ppc64-pseries-f20")
c.add_compare("--arch ppc64 --boot network --disk %(EXISTIMG1)s --os-variant fedora20 --network none", "ppc64-machdefault-f20")
c.add_compare("--connect %(URI-KVM-PPC64LE)s --import --disk %(EXISTIMG1)s --os-variant fedora20 --panic default", "ppc64le-kvm-import")
c.add_compare("--arch ppc64 --machine pseries --boot network --disk %(EXISTIMG1)s --graphics vnc --network none --tpm /dev/tpm0", "ppc64-pseries-tpm")  # default TPM for ppc64

# s390x tests
c.add_compare("--arch s390x --machine s390-ccw-virtio --connect %(URI-KVM-S390X)s --boot kernel=/kernel.img,initrd=/initrd.img --disk %(EXISTIMG1)s --disk %(EXISTIMG3)s,device=cdrom --os-variant fedora21", "s390x-cdrom", prerun_check=has_old_osinfo)
c.add_compare("--arch s390x --machine s390-ccw-virtio --connect " + utils.URIs.kvm_s390x_KVMIBM + " --boot kernel=/kernel.img,initrd=/initrd.img --disk %(EXISTIMG1)s --disk %(EXISTIMG3)s,device=cdrom --os-variant fedora21 --watchdog diag288,action=reset --panic default --graphics vnc", "s390x-cdrom-KVMIBM")

# qemu:///session tests
c.add_compare("--connect " + utils.URIs.kvm_session + " --disk size=8 --os-variant fedora21 --cdrom %(EXISTIMG1)s", "kvm-session-defaults", prerun_check=has_old_osinfo)
c.add_valid("--connect " + utils.URIs.kvm_session + " --install fedora21", prerun_check=has_old_osinfo)  # hits some get_search_paths and media_upload code paths

# misc KVM config tests
c.add_compare("--disk none --location %(ISO-NO-OS)s,kernel=frib.img,initrd=/frob.img", "location-manual-kernel", prerun_check=missing_isoinfo)  # --location with an unknown ISO but manually specified kernel paths
c.add_compare("--disk %(EXISTIMG1)s --location %(ISOTREE)s --nonetworks", "location-iso", prerun_check=missing_isoinfo)  # Using --location iso mounting
c.add_compare("--disk %(EXISTIMG1)s --cdrom %(ISOLABEL)s", "cdrom-centos-label")  # Using --cdrom with centos CD label, should use virtio etc.
c.add_compare("--disk %(EXISTIMG1)s --install bootdev=network --os-variant rhel5.4 --cloud-init none", "kvm-rhel5")  # RHEL5 defaults
c.add_compare("--disk %(EXISTIMG1)s --install kernel=%(ISO-WIN7)s,initrd=%(ISOLABEL)s,kernel_args='foo bar' --os-variant rhel6.4 --unattended none", "kvm-rhel6")  # RHEL6 defaults. ISO paths are just to point at existing files
c.add_compare("--disk %(EXISTIMG1)s --location https://example.com --install kernel_args='test overwrite',kernel_args_overwrite=yes --os-variant rhel7.0", "kvm-rhel7", precompare_check=no_osinfo_unattend_cb)  # RHEL7 defaults
c.add_compare("--connect " + utils.URIs.kvm_nodomcaps + " --disk %(EXISTIMG1)s --pxe --os-variant rhel7.0", "kvm-cpu-default-fallback", prerun_check=has_old_osinfo)  # No domcaps, so mode=host-model isn't safe, so we fallback to host-model-only
c.add_compare("--connect " + utils.URIs.kvm_nodomcaps + " --cpu host-copy --disk none --pxe", "kvm-hostcopy-fallback")  # No domcaps so need to use capabilities for CPU host-copy
c.add_compare("--disk %(EXISTIMG1)s --pxe --os-variant centos7.0", "kvm-centos7", prerun_check=has_old_osinfo)  # Centos 7 defaults
c.add_compare("--disk %(EXISTIMG1)s --pxe --os-variant centos7.0", "kvm-centos7", prerun_check=has_old_osinfo)  # Centos 7 defaults
c.add_compare("--disk %(EXISTIMG1)s --cdrom %(EXISTIMG2)s --os-variant win10", "kvm-win10", prerun_check=has_old_osinfo)  # win10 defaults
c.add_compare("--os-variant win7 --cdrom %(EXISTIMG2)s --boot loader_type=pflash,loader=CODE.fd,nvram_template=VARS.fd --disk %(EXISTIMG1)s", "win7-uefi", prerun_check=has_old_osinfo)  # no HYPER-V with UEFI
c.add_compare("--arch i686 --boot uefi --install kernel=http://example.com/httpkernel,initrd=ftp://example.com/ftpinitrd --disk none", "kvm-i686-uefi")  # i686 uefi. piggy back it for --install testing too
c.add_compare("--machine q35 --cdrom %(EXISTIMG2)s --disk %(EXISTIMG1)s", "q35-defaults")  # proper q35 disk defaults
c.add_compare("--disk size=1 --os-variant openbsd4.9", "openbsd-defaults")  # triggers net fallback scenario
c.add_compare("--connect " + utils.URIs.kvm_remote + " --import --disk %(EXISTIMG1)s --os-variant fedora21 --pm suspend_to_disk=yes", "f21-kvm-remote", prerun_check=has_old_osinfo)
c.add_compare("--connect %(URI-KVM)s --os-variant fedora26 --graphics spice --controller usb,model=none", "graphics-usb-disable")

c.add_valid("--arch aarch64 --nodisks --pxe --connect " + utils.URIs.kvm_nodomcaps)  # attempt to default to aarch64 UEFI, but it fails, but should only print warnings
c.add_invalid("--disk none --boot network --machine foobar")  # Unknown machine type
c.add_invalid("--nodisks --boot network --arch mips --virt-type kvm")  # Invalid domain type for arch
c.add_invalid("--nodisks --boot network --paravirt --arch mips")  # Invalid arch/virt combo
c.add_invalid("--disk none --location nfs:example.com/fake --nonetworks")  # Using --location nfs, no longer supported


c = vinst.add_category("kvm-x86_64-launch-security", "--disk none --noautoconsole")
c.add_compare("--boot uefi --machine q35 --launchSecurity type=sev,reducedPhysBits=1,policy=0x0001,cbitpos=47,dhCert=BASE64CERT,session=BASE64SESSION --connect " + utils.URIs.kvm_amd_sev, "x86_64-launch-security-sev-full")  # Full cmdline
c.add_compare("--boot uefi --machine q35 --launchSecurity sev --connect " + utils.URIs.kvm_amd_sev, "x86_64-launch-security-sev")  # Fill in platform data from domcaps
c.add_valid("--boot uefi --machine q35 --launchSecurity sev,reducedPhysBits=1,cbitpos=47 --connect " + utils.URIs.kvm_amd_sev)  # Default policy == 0x0003 will be used
c.add_invalid("--launchSecurity policy=0x0001 --connect " + utils.URIs.kvm_amd_sev)  # Missing launchSecurity 'type'
c.add_invalid("--launchSecurity sev --connect " + utils.URIs.kvm_amd_sev)  # Fail if loader isn't UEFI
c.add_invalid("--boot uefi --launchSecurity sev --connect " + utils.URIs.kvm_amd_sev)  # Fail if machine type isn't Q35
c.add_invalid("--boot uefi --machine q35 --launchSecurity sev,policy=0x0001 --connect " + utils.URIs.kvm_q35)  # Fail with no SEV capabilities


c = vinst.add_category("kvm-q35", "--noautoconsole --connect " + utils.URIs.kvm_q35)
c.add_compare("--boot uefi --disk none", "boot-uefi")


c = vinst.add_category("kvm-arm", "--connect %(URI-KVM)s --noautoconsole", precompare_check="3.3.0")  # required qemu-xhci from libvirt 3.3.0
# armv7l tests
c.add_compare("--arch armv7l --machine vexpress-a9 --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,dtb=/f19-arm.dtb,extra_args=\"console=ttyAMA0 rw root=/dev/mmcblk0p3\" --disk %(EXISTIMG1)s --nographics", "arm-vexpress-plain")
c.add_compare("--arch armv7l --machine virt --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\" --disk %(EXISTIMG1)s --nographics --os-variant fedora20", "arm-virt-f20")
c.add_compare("--arch armv7l --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\",extra_args=foo --disk %(EXISTIMG1)s --os-variant fedora20", "arm-defaultmach-f20")
c.add_compare("--connect %(URI-KVM-ARMV7L)s --disk %(EXISTIMG1)s --import --os-variant fedora20", "arm-kvm-import")

# aarch64 tests
c.add_compare("--arch aarch64 --machine virt --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\" --disk %(EXISTIMG1)s", "aarch64-machvirt")
c.add_compare("--arch aarch64 --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\" --disk %(EXISTIMG1)s", "aarch64-machdefault")
c.add_compare("--arch aarch64 --cdrom %(EXISTIMG2)s --boot loader=CODE.fd,nvram.template=VARS.fd --disk %(EXISTIMG1)s --cpu none --events on_crash=preserve,on_reboot=destroy,on_poweroff=restart", "aarch64-cdrom")
c.add_compare("--connect %(URI-KVM-AARCH64)s --disk %(EXISTIMG1)s --import --os-variant fedora21 --panic default", "aarch64-kvm-import")  # the --panic is a no-op
c.add_compare("--connect %(URI-KVM-AARCH64)s --disk size=1 --os-variant fedora22 --features gic_version=host --network network=default,address.type=pci --controller type=scsi,model=virtio-scsi,address.type=pci", "aarch64-kvm-gic")
c.add_compare("--connect %(URI-KVM-AARCH64)s --arch aarch64 --disk none --pxe --boot firmware=efi", "aarch64-firmware-no-override")


# Simple headless guests for various architectures
c = vinst.add_category("kvm-headless", "--os-variant fedora29 --import --disk %(EXISTIMG1)s --network default --graphics none")
c.add_compare("--connect %(URI-KVM-AARCH64)s --arch aarch64", "aarch64-headless")
c.add_compare("--connect %(URI-KVM-PPC64LE)s --arch ppc64le", "ppc64-headless")
c.add_compare("--connect %(URI-QEMU-RISCV64)s --arch riscv64", "riscv64-headless", precompare_check="5.3.0")
c.add_compare("--connect %(URI-KVM-S390X)s --arch s390x", "s390x-headless")
c.add_compare("--connect %(URI-KVM)s --arch x86_64", "x86_64-headless")


# Simple guests with graphics for various architectures
c = vinst.add_category("kvm-graphics", "--os-variant fedora29 --import --disk %(EXISTIMG1)s --network default --graphics vnc")
c.add_compare("--connect %(URI-KVM-AARCH64)s --arch aarch64", "aarch64-graphics")
c.add_compare("--connect %(URI-KVM-PPC64LE)s --arch ppc64le", "ppc64-graphics")
c.add_compare("--connect %(URI-QEMU-RISCV64)s --arch riscv64", "riscv64-graphics", precompare_check="5.3.0", )
c.add_compare("--connect %(URI-KVM-S390X)s --arch s390x", "s390x-graphics")
c.add_compare("--connect %(URI-KVM)s --arch x86_64", "x86_64-graphics")



######################
# LXC specific tests #
######################

c = vinst.add_category("lxc", "--name foolxc --noautoconsole --connect " + utils.URIs.lxc)
c.add_invalid("--filesystem /,not/abs")  # filesystem target is not absolute
c.add_compare("", "default")
c.add_compare("--os-variant fedora27", "default-f27")
c.add_compare("--filesystem /source,/ --memory 128", "fs-default")
c.add_compare("--init /usr/bin/httpd", "manual-init")



######################
# Xen specific tests #
######################

c = vinst.add_category("xen", "--noautoconsole --connect " + utils.URIs.xen)
c.add_valid("--disk %(EXISTIMG1)s --location %(TREEDIR)s --paravirt --graphics none")  # Xen PV install headless
c.add_compare("--disk %(EXISTIMG1)s --import", "xen-default")  # Xen default
c.add_compare("--disk %(EXISTIMG1)s --location %(TREEDIR)s --paravirt --controller xenbus,maxGrantFrames=64 --input default", "xen-pv", precompare_check="5.3.0")  # Xen PV
c.add_compare("--disk  /iscsi-pool/diskvol1 --cdrom %(EXISTIMG1)s --livecd --hvm", "xen-hvm")  # Xen HVM
c.add_compare("--disk  /iscsi-pool/diskvol1 --cdrom %(EXISTIMG1)s --install no_install=yes --hvm", "xen-hvm")  # Ensure --livecd and --install no_install are essentially identical



#####################
# VZ specific tests #
#####################

c = vinst.add_category("vz", "--noautoconsole --connect " + utils.URIs.vz)
c.add_valid("--container")  # validate the special define+start logic
c.add_valid("--hvm --cdrom %(EXISTIMG1)s --disk none")  # hit more install vz logic
c.add_valid("--hvm --import --disk %(EXISTIMG1)s --noreboot")  # hit more install vz logic
c.add_invalid("--container --transient")  # vz doesn't support --transient
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
c.add_valid("--mac 22:11:11:11:11:11 --check mac_in_use=off")  # colliding mac, but check is skipped
c.add_invalid("--mac 22:11:11:11:11:11")  # Colliding macaddr will error
c.add_invalid("--graphics vnc --vnclisten 1.2.3.4")  # mixing old and new
c.add_invalid("--network=FOO")  # Nonexistent network
c.add_invalid("--mac 1234")  # Invalid mac
c.add_invalid("--network user --bridge foo0")  # Mixing bridge and network

c = vinst.add_category("storage-back-compat", "--pxe --noautoconsole")
c.add_valid("--file %(EXISTIMG1)s --nonsparse --file-size 4")  # Existing file, other opts
c.add_valid("--file %(EXISTIMG1)s")  # Existing file, no opts
c.add_valid("--file %(EXISTIMG1)s --file %(EXISTIMG1)s")  # Multiple existing files
c.add_valid("--file %(NEWIMG1)s --file-size .00001 --nonsparse")  # Nonexistent file

c = vinst.add_category("console-tests", "--nodisks")
c.add_valid("--pxe", grep="graphical console command: virt-viewer")  # mock default graphics+virt-viewer usage
c.add_valid("--pxe --graphics spice,gl=on", grep="--attach")  # using virt-viewer --attach option for gl
c.add_valid("--pxe --graphics listen=none", grep="--attach")  # using virt-viewer --attach option for listen 'none'
c.add_valid("--pxe --destroy-on-exit", grep="Restarting guest.\n")  # destroy-on-exit
c.add_valid("--pxe --transient --destroy-on-exit", grep="Domain creation completed.")  # destroy-on-exit + transient
c.add_valid("--pxe --graphics vnc --noreboot", grep="graphical console command: virt-viewer")  # mock virt-viewer waiting, with noreboot magic
c.add_valid("--nographics --cdrom %(EXISTIMG1)s")  # console warning about cdrom + nographics
c.add_valid("--nographics --console none --location %(TREEDIR)s", grep="Directory tree installs typically")  # warning about directory trees not working well
c.add_valid("--pxe --nographics --transient", grep="text console command: virsh")  # --transient handling
c.add_valid("--pxe --nographics --autoconsole graphical", grep="graphical console command: virt-viewer")  # force --autoconsole graphical
c.add_valid("--pxe --autoconsole text", grep="text console command: virsh")  # force --autoconsole text
c.add_valid("--connect %(URI-KVM)s --install fedora28 --cloud-init", grep="Password for first root login")  # make sure we print the root login password
c.add_valid("--pxe", grep="User stopped the VM", env={"VIRTINST_TESTSUITE_HACK_DESTROY": "1"})  # fake the user destroying the VM, we should print a specific message and not reboot the VM
c.add_invalid("--pxe --autoconsole badval")  # bad --autoconsole value
c.add_invalid("--pxe --autoconsole text --wait -1", grep="exceeded specified time limit")  # hits a specific code path where we skip console waitpid


##################
# virt-xml tests #
##################

_VIRTXMLDIR = XMLDIR + "/virtxml/"

vixml = App("virt-xml")
c = vixml.add_category("misc", "")
c.add_valid("--help")  # basic --help test
c.add_valid("--sound=? --tpm=?")  # basic introspection test
c.add_valid("test-state-shutoff --edit --update --boot menu=on", grep="The VM is not running")  # --update with inactive VM, should work but warn
c.add_valid("test-state-shutoff --edit --boot menu=on", grep="XML did not change after domain define")  # menu=on is discarded because <bootloader> is specified
c.add_valid("test-for-virtxml --edit --graphics password=foo --update --confirm", input_text="no\nno\n")  # prompt exiting
c.add_valid("test-for-virtxml --edit --cpu host-passthrough --no-define --start --confirm", input_text="no")  # transient prompt exiting
c.add_valid("test-for-virtxml --edit --metadata name=test-for-virtxml", grep="requested changes will have no effect")
c.add_invalid("test --edit 2 --events on_poweroff=destroy", grep="'--edit 2' doesn't make sense with --events")
c.add_invalid("test --os-variant fedora26 --edit --cpu host-passthrough", grep="--os-variant is not supported")
c.add_invalid("test-for-virtxml --os-variant fedora26 --remove-device --disk 1", grep="--os-variant is not supported")
c.add_invalid("--build-xml --os-variant fedora26 --disk path=foo", grep="--os-variant is not supported")
c.add_invalid("domain-idontexist --edit --cpu host-passthrough --start", grep="Could not find domain")
c.add_invalid("test-state-shutoff --edit --update --boot menu=on --start", grep="Cannot use --update")
c.add_invalid("test --edit --update --events on_poweroff=destroy", grep="Don't know how to --update for --events")
c.add_invalid("--edit --cpu host-passthrough --confirm", input_file=(_VIRTXMLDIR + "virtxml-stdin-edit.xml"), grep="Can't use --confirm with stdin")
c.add_invalid("--edit --cpu host-passthrough --update", input_file=(_VIRTXMLDIR + "virtxml-stdin-edit.xml"), grep="Can't use --update with stdin")
c.add_invalid("--edit --cpu host-passthrough", grep="A domain must be specified")
c.add_invalid("test-state-shutoff --cpu mode=idontexist --start --edit --no-define --confirm", grep="Failed starting domain", input_text="yes")
c.add_invalid("test --cpu host-passthrough", grep="One of --edit, ")  # conflicting --edit options
c.add_invalid("test --edit --add-device --disk path=foo", grep="Conflicting options --edit, --add-device")
c.add_invalid("test --edit 0 --disk path=", grep="Invalid --edit option '0'")
c.add_invalid("test --edit --hostdev driver_name=vfio")  # Guest has no hostdev to edit
c.add_invalid("test --edit --cpu host-passthrough --boot hd,network")  # Specified more than 1 option
c.add_invalid("test --edit")  # specified no edit option
c.add_invalid("test --edit 2 --cpu host-passthrough")  # specifying --edit number where it doesn't make sense
c.add_invalid("test-for-virtxml --edit 5 --tpm /dev/tpm")  # device edit out of range
c.add_invalid("test-for-virtxml --add-device --host-device 0x04b3:0x4485 --update --confirm", input_text="yes")  # test driver doesn't support attachdevice...
c.add_invalid("test-for-virtxml --remove-device --host-device 1 --update --confirm", input_text="foo\nyes\n")  # test driver doesn't support detachdevice...
c.add_invalid("test-for-virtxml --edit --graphics password=foo,keymap= --update --confirm", input_text="yes")  # test driver doesn't support updatdevice...
c.add_invalid("--build-xml --memory 10,maxmemory=20")  # building XML for option that doesn't support it
c.add_invalid("test-state-shutoff --edit sparse=no --disk path=blah", grep="Don't know how to match device type 'disk' property 'sparse'")
c.add_invalid("test --edit --boot network,cdrom --define --no-define")
c.add_invalid("test --add-device --xml ./@foo=bar", grep="--xml can only be used with --edit")
c.add_compare("test --print-xml --edit --vcpus 7", "print-xml")  # test --print-xml
c.add_compare("--edit --cpu host-passthrough", "stdin-edit", input_file=(_VIRTXMLDIR + "virtxml-stdin-edit.xml"))  # stdin test
c.add_compare("--build-xml --cpu pentium3,+x2apic", "build-cpu")
c.add_compare("--build-xml --tpm path=/dev/tpm", "build-tpm")
c.add_compare("--build-xml --blkiotune weight=100,device0.path=/dev/sdf,device.weight=200,device0.read_bytes_sec=10000,device0.write_bytes_sec=10000,device0.read_iops_sec=20000,device0.write_iops_sec=20000", "build-blkiotune")
c.add_compare("--build-xml --idmap clearxml=no,uid.start=0,uid.target=1000,uid.count=10,gid.start=0,gid.target=1000,gid.count=10", "build-idmap")
c.add_compare("--connect %(URI-KVM)s --build-xml --disk %(EXISTIMG1)s", "build-disk-plain")
c.add_compare("--connect %(URI-KVM)s test-many-devices --build-xml --disk %(EXISTIMG1)s", "build-disk-domain")
c.add_compare("4a64cc71-19c4-2fd0-2323-3050941ea3c3 --edit --boot network,cdrom", "edit-bootorder")  # basic bootorder test, also using UUID lookup
c.add_compare("--confirm 1 --edit --cpu host-passthrough", "prompt-response", input_text="yes")  # prompt response, also using domid lookup
c.add_compare("--edit --print-diff --qemu-commandline clearxml=yes", "edit-clearxml-qemu-commandline", input_file=(_VIRTXMLDIR + "virtxml-qemu-commandline-clear.xml"))
c.add_compare("--print-diff --remove-device --serial 1", "remove-console-dup", input_file=(_VIRTXMLDIR + "virtxml-console-dup.xml"))
c.add_compare("--connect %(URI-KVM)s test-hyperv-uefi --edit --boot uefi", "hyperv-uefi-collision")
c.add_compare("--connect %(URI-KVM)s test-many-devices --edit --cpu host-copy", "edit-cpu-host-copy")


c = vixml.add_category("simple edit diff", "test-for-virtxml --edit --print-diff --define")
c.add_compare("""--xml ./@foo=bar --xml xpath.delete=./currentMemory --xml ./new/element/test=1""", "edit-xpaths")
c.add_compare("""--metadata name=foo-my-new-name,os_name=fedora13,uuid=12345678-12F4-1234-1234-123456789AFA,description="hey this is my
new
very,very=new desc\\\'",title="This is my,funky=new title" """, "edit-simple-metadata")
c.add_compare("""--metadata os_full_id=http://fedoraproject.org/fedora/23""", "edit-metadata-full-os")
c.add_compare("--events on_poweroff=destroy,on_reboot=restart,on_crash=preserve", "edit-simple-events")
c.add_compare("--qemu-commandline='-foo bar,baz=\"wib wob\"'", "edit-simple-qemu-commandline")
c.add_compare("--memory 500,maxmemory=1000,hugepages=off", "edit-simple-memory")
c.add_compare("--vcpus 10,maxvcpus=20,cores=5,sockets=4,threads=1", "edit-simple-vcpus")
c.add_compare("--cpu model=pentium2,+x2apic,forbid=pbe", "edit-simple-cpu")
c.add_compare("--numatune memory.nodeset=1-5,7,memory.mode=strict,memory.placement=auto", "edit-simple-numatune")
c.add_compare("--blkiotune weight=500,device_path=/dev/sdf,device_weight=600", "edit-simple-blkiotune")
c.add_compare("--idmap uid_start=0,uid_target=2000,uid_count=30,gid_start=0,gid_target=3000,gid_count=40", "edit-simple-idmap")
c.add_compare("--boot loader=foo.bar,useserial=on,init=/bin/bash,nvram=/test/nvram.img,os_type=hvm,domain_type=test,loader.readonly=on,loader.secure=no,machine=", "edit-simple-boot")
c.add_compare("--security label=foo,bar,baz,UNKNOWN=val,relabel=on", "edit-simple-security")
c.add_compare("--features eoi=on,hyperv_relaxed=off,acpi=", "edit-simple-features")
c.add_compare("--clock offset=localtime,hpet_present=yes,kvmclock_present=no,kvmclock_tickpolicy=foo,rtc_tickpolicy=merge", "edit-simple-clock")
c.add_compare("--pm suspend_to_mem.enabled=yes,suspend_to_disk.enabled=no", "edit-simple-pm")
c.add_compare("--disk /dev/zero,perms=ro,source.startupPolicy=optional", "edit-simple-disk")
c.add_compare("--disk path=", "edit-simple-disk-remove-path")
c.add_compare("--network source=br0,type=bridge,model=virtio,mac=", "edit-simple-network")
c.add_compare("--graphics tlsport=5902,keymap=ja", "edit-simple-graphics")
c.add_compare("--graphics listen=none", "edit-graphics-listen-none")
c.add_compare("--controller index=15,model=lsilogic", "edit-simple-controller")
c.add_compare("--controller index=15,model=lsilogic", "edit-simple-controller")
c.add_compare("--smartcard type=spicevmc", "edit-simple-smartcard")
c.add_compare("--redirdev type=spicevmc,server=example.com:12345", "edit-simple-redirdev")
c.add_compare("--tpm backend.device.path=,backend.type=emulator,backend.version=2.0", "edit-simple-tpm")
c.add_compare("--vsock model=virtio,cid.address=,cid.auto=on", "edit-simple-vsock")
c.add_compare("--rng rate_bytes=3333,rate_period=4444,backend.source.connect_host=,backend.source.connect_service=,backend.source.host=,backend.source.service=,backend.source.bind_host=,backend.source.bind_service=,backend.source.mode=,backend.type=unix,backend.source.mode=connect,backend.source.path=/tmp/unix,backend.source.seclabel.model=dac,backend.source.seclabel.label=foo,backend.source.seclabel.relabel=yes", "edit-simple-rng")
c.add_compare("--watchdog action=reset", "edit-simple-watchdog")
c.add_compare("--memballoon model=none", "edit-simple-memballoon")
c.add_compare("--serial pty", "edit-simple-serial")
c.add_compare("--parallel unix,path=/some/other/log", "edit-simple-parallel")
c.add_compare("--channel null", "edit-simple-channel")
c.add_compare("--console name=foo.bar.baz", "edit-simple-console")
c.add_compare("--filesystem /1/2/3,/4/5/6,mode=mapped", "edit-simple-filesystem")
c.add_compare("--video cirrus", "edit-simple-video")
c.add_compare("--sound pcspk", "edit-simple-soundhw")
c.add_compare("--host-device 0x04b3:0x4485,driver_name=vfio,type=usb", "edit-simple-host-device")

c = vixml.add_category("edit selection", "test-for-virtxml --print-diff --define")
c.add_invalid("--edit target=vvv --disk /dev/null")  # no match found
c.add_invalid("--edit seclabel2.model=dac --disk /dev/null")  # no match found
c.add_valid("--edit seclabel.model=dac --disk /dev/null")  # match found
c.add_compare("--edit 3 --sound pcspk", "edit-pos-num")
c.add_compare("--edit -1 --video qxl", "edit-neg-num")
c.add_compare("--edit all --host-device driver.name=vfio", "edit-all")
c.add_compare("--edit ich6 --sound pcspk", "edit-select-sound-model")
c.add_compare("--edit target=hda --disk /dev/null", "edit-select-disk-target")
c.add_compare("--edit /tmp/foobar2 --disk shareable=off,readonly=on", "edit-select-disk-path")
c.add_compare("--edit mac=00:11:7f:33:44:55 --network target=nic55", "edit-select-network-mac")
c.add_compare("--edit target=hda --disk boot_order=1", "edit-select-disk-bootorder")
c.add_compare("--edit path=/dev/null --disk path=,target=fdb,boot_order=12", "edit-disk-unset")  # --disk matching, using empty value to unset path
c.add_compare("--edit --memballoon none", "edit-disable-memballoon")

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
c.add_compare("--edit --graphics clearxml=yes,type=spice,gl=on,listen=none", "edit-graphics-spice-gl")

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
c.add_compare("--remove-device --sound ich6", "remove-sound-model")
c.add_compare("--remove-device --disk 3", "remove-disk-index")
c.add_compare("--remove-device --disk /dev/null", "remove-disk-path")
c.add_compare("--remove-device --video all", "remove-video-all")
c.add_compare("--remove-device --host-device 0x04b3:0x4485", "remove-hostdev-name")
c.add_compare("--remove-device --memballoon all", "remove-memballoon")

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
c.add_compare("--add-device --network default --os-variant http://fedoraproject.org/fedora/28", "kvm-add-network-os-from-cmdline")  # Guest OS information provided on the command line



####################
# virt-clone tests #
####################

_CLONEXMLDIR = XMLDIR + "/virtclone"
_CLONE_UNMANAGED = "--original-xml %s/clone-disk.xml" % _CLONEXMLDIR
_CLONE_MANAGED = "--original-xml %s/clone-disk-managed.xml" % _CLONEXMLDIR
_CLONE_NOEXIST = "--original-xml %s/clone-disk-noexist.xml" % _CLONEXMLDIR
_CLONE_NVRAM = "--original-xml %s/clone-nvram-auto.xml" % _CLONEXMLDIR
_CLONE_NVRAM_NEWPOOL = "--original-xml %s/clone-nvram-newpool.xml" % _CLONEXMLDIR
_CLONE_NVRAM_MISSING = "--original-xml %s/clone-nvram-missing.xml" % _CLONEXMLDIR
_CLONE_EMPTY = "--original-xml %s/clone-empty.xml" % _CLONEXMLDIR
_CLONE_NET_RBD = "--original-xml %s/clone-net-rbd.xml" % _CLONEXMLDIR
_CLONE_NET_HTTP = "--original-xml %s/clone-net-http.xml" % _CLONEXMLDIR


vclon = App("virt-clone")
c = vclon.add_category("remote", "--connect %(URI-TEST-REMOTE)s")
c.add_valid(_CLONE_EMPTY + " --auto-clone")  # Auto flag, no storage
c.add_valid(_CLONE_MANAGED + " --auto-clone")  # Auto flag w/ managed storage
c.add_invalid(_CLONE_UNMANAGED + " --auto-clone")  # Auto flag w/ local storage, which is invalid for remote connection
c.add_invalid(_CLONE_UNMANAGED + " --auto-clone")  # Auto flag w/ local storage, which is invalid for remote connection


c = vclon.add_category("misc", "")
c.add_compare("--connect %(URI-KVM)s -o test-clone --auto-clone", "clone-auto1")
c.add_compare("--connect %(URI-TEST-FULL)s -o test-clone-simple --name newvm --auto-clone", "clone-auto2")
c.add_compare("--connect %(URI-KVM)s " + _CLONE_NVRAM + " --auto-clone", "clone-nvram")  # hits a particular nvram code path
c.add_compare("--connect %(URI-KVM)s " + _CLONE_NVRAM + " --auto-clone --nvram /nvram/my-custom-path", "clone-nvram-path")  # hits a particular nvram code path
c.add_compare("--connect %(URI-KVM)s " + _CLONE_NVRAM_NEWPOOL + " --auto-clone", "nvram-newpool")  # hits a particular nvram code path
c.add_compare("--connect %(URI-KVM)s " + _CLONE_NVRAM_MISSING + " --auto-clone", "nvram-missing")  # hits a particular nvram code path
c.add_compare("--connect %(URI-KVM)s " + _CLONE_NVRAM_MISSING + " --auto-clone --preserve", "nvram-missing-preserve")  # hits a particular nvram code path
c.add_compare("--connect %(URI-KVM)s -o test-clone -n test-newclone --mac 12:34:56:1A:B2:C3 --mac 12:34:56:1A:B7:C3 --uuid 12345678-12F4-1234-1234-123456789AFA --file /dev/disk-pool/newclone1.img --file /dev/default-pool/newclone2.img --skip-copy=hdb --force-copy=sdb --file /dev/default-pool/newclone3.img", "clone-manual")
c.add_compare("--connect %(URI-KVM)s -o test-clone -n test-newclone --mac 12:34:56:1A:B2:C3 --mac 12:34:56:1A:B7:C3 --uuid 12345678-12F4-1234-1234-123456789AFA --file /dev/disk-pool/newclone1.img --file /dev/default-pool/newclone2.img --skip-copy=hdb --force-copy=sdb --file /dev/default-pool/newclone3.img", "clone-manual")
c.add_compare(_CLONE_EMPTY + " --auto-clone --print-xml", "empty")  # Auto flag, no storage
c.add_compare("--connect %(URI-KVM)s -o test-clone-simple --auto -f /foo.img --print-xml", "cross-pool")  # cross pool cloning which fails with test driver but let's confirm the XML
c.add_compare(_CLONE_MANAGED + " --auto-clone", "auto-managed")  # Auto flag w/ managed storage
c.add_compare(_CLONE_UNMANAGED + " --auto-clone", "auto-unmanaged")  # Auto flag w/ local storage
c.add_valid("--connect %(URI-TEST-FULL)s -o test-clone --auto-clone --nonsparse")  # Auto flag, actual VM, skip state check
c.add_valid("--connect %(URI-TEST-FULL)s -o test-clone-simple -n newvm --preserve-data --file %(EXISTIMG1)s")  # Preserve data shouldn't complain about existing volume
c.add_valid("-n clonetest " + _CLONE_UNMANAGED + " --file %(EXISTIMG3)s --file %(EXISTIMG4)s --check path_exists=off")  # Skip existing file check
c.add_valid("-n clonetest " + _CLONE_UNMANAGED + " --auto-clone --mac 22:11:11:11:11:11 --check all=off")  # Colliding mac but we skip the check
c.add_invalid("-n clonetest " + _CLONE_UNMANAGED + " --auto-clone --mac 22:11:11:11:11:11", grep="--check mac_in_use=off")  # Colliding mac should fail
c.add_invalid("--auto-clone")  # Just the auto flag
c.add_invalid(_CLONE_EMPTY + " --file foo")  # Didn't specify new name
c.add_invalid(_CLONE_EMPTY + " --auto-clone -n test")  # new name raises error
c.add_invalid("-o test --auto-clone", grep="shutoff")  # VM is running
c.add_invalid("--connect %(URI-TEST-FULL)s -o test-clone-simple -n newvm --file %(EXISTIMG1)s")  # Should complain about overwriting existing file
c.add_invalid("--connect %(URI-TEST-REMOTE)s -o test-clone-simple --auto-clone --file /dev/default-pool/testvol9.img --check all=off", grep="Clone onto existing storage volume")  # hit a specific error message
c.add_invalid("--connect %(URI-TEST-FULL)s -o test-clone-full --auto-clone", grep="not enough free space")  # catch failure of clone path setting
c.add_invalid(_CLONE_NET_HTTP + " --auto-clone", grep="'http' is not cloneable")
c.add_invalid(_CLONE_NET_RBD + " --auto-clone", grep="'rbd' requires managed storage")  # connection doesn't have the referenced rbd volume
c.add_invalid(_CLONE_NET_RBD + " --connect %(URI-TEST-FULL)s --auto-clone", grep="Cloning rbd volumes is not yet supported")


c = vclon.add_category("general", "-n clonetest")
c.add_valid(_CLONE_EMPTY + " --auto-clone --replace")  # --replace but it doesn't matter, should be safely ignored
c.add_valid(_CLONE_EMPTY + " --file %(NEWCLONEIMG1)s --file %(NEWCLONEIMG2)s")  # Nodisk, but with spurious files passed
c.add_valid(_CLONE_EMPTY + " --file %(NEWCLONEIMG1)s --file %(NEWCLONEIMG2)s --prompt")  # Working scenario w/ prompt shouldn't ask anything
c.add_valid(_CLONE_UNMANAGED + " --file %(NEWCLONEIMG1)s --file %(NEWCLONEIMG2)s")  # XML File with 2 disks
c.add_valid(_CLONE_UNMANAGED + " --file %(NEWCLONEIMG1)s --skip-copy=hda")  # XML w/ disks, skipping one disk target
c.add_compare(_CLONE_UNMANAGED + " --file virt-install --file %(EXISTIMG1)s --preserve", "unmanaged-preserve")  # XML w/ disks, overwriting existing files with --preserve
c.add_valid(_CLONE_UNMANAGED + " --file %(NEWCLONEIMG1)s --file %(NEWCLONEIMG2)s --file %(NEWCLONEIMG3)s --force-copy=hdc")  # XML w/ disks, force copy a readonly target
c.add_valid(_CLONE_UNMANAGED + " --file %(NEWCLONEIMG1)s --file %(NEWCLONEIMG2)s --force-copy=fda")  # XML w/ disks, force copy a target with no media
c.add_valid(_CLONE_MANAGED + " --file %(NEWIMG1)s")  # XML w/ managed storage, specify managed path
c.add_valid(_CLONE_MANAGED + " --file %(NEWIMG1)s --reflink")  # XML w/ managed storage, specify managed path, use --reflink option
c.add_valid(_CLONE_NOEXIST + " --file %(EXISTIMG1)s --preserve")  # XML w/ managed storage, specify managed path across pools
c.add_compare("--connect %(URI-TEST-FULL)s -o test-clone -n test --auto-clone --replace", "replace")  # Overwriting existing running VM
c.add_valid(_CLONE_MANAGED + " --auto-clone --force-copy fda")  # force copy empty floppy drive
c.add_invalid(_CLONE_EMPTY + " foobar")  # Positional arguments error
c.add_invalid("-o idontexist")  # Non-existent vm name
c.add_invalid("-o idontexist --auto-clone")  # Non-existent vm name with auto flag,
c.add_invalid(_CLONE_EMPTY + " -n test")  # Colliding new name
c.add_invalid(_CLONE_UNMANAGED + "")  # XML file with several disks, but non specified
c.add_invalid(_CLONE_UNMANAGED + " --file virt-install", grep="overwrite the existing path 'virt-install'")  # XML w/ disks, overwriting existing files with no --preserve
c.add_invalid(_CLONE_MANAGED + " --file /tmp/clonevol", grep="matching name 'default-vol'")  # will attempt to clone across pools, which test driver doesn't support
c.add_invalid(_CLONE_NOEXIST + " --auto-clone", grep="'/i/really/dont/exist' does not exist.")  # XML w/ non-existent storage, WITHOUT --preserve




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

    def have_argcomplete():
        if not argcomplete:
            return "argcomplete not installed"

    cmd = Command(line, grep=grep, nogrep=nogrep, env=env, need_conn=False,
            prerun_check=have_argcomplete)
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
_add_argcomplete_cmd("virt-install --install i", "initrd")
_add_argcomplete_cmd("virt-install --test-stub", None,
        nogrep="--test-stub-command")
_add_argcomplete_cmd("virt-install --unattended ", "profile=")  # will list all --unattended subprops
_add_argcomplete_cmd("virt-install --unattended a", "admin-password-file=")
_add_argcomplete_cmd("virt-clone --preserve", "--preserve-data")
_add_argcomplete_cmd("virt-xml --sound mode", "model")


##############
# Misc tests #
##############


@utils.run_without_testsuite_hacks
def test_virtinstall_no_testsuite():
    """
    Run virt-install stub command without the testsuite hacks, to test
    some code paths like proper logging etc.
    """
    cmd = Command(
            "virt-install --connect %s "
            "--test-stub-command --noautoconsole" %
            (utils.URIs.test_suite))
    cmd.run()


#########################
# Test runner functions #
#########################

_CURTEST = 0


def setup():
    """
    Create initial test files/dirs
    """
    global _CURTEST
    _CURTEST += 1
    if _CURTEST != 1:
        return

    for i in EXIST_FILES:
        open(i, "a")


def cleanup(clean_all=True):
    """
    Cleanup temporary files used for testing
    """
    clean_files = NEW_FILES
    if clean_all:
        clean_files += EXIST_FILES

    for i in clean_files:
        if not os.path.exists(i):
            continue
        if os.path.isdir(i):
            shutil.rmtree(i)
        else:
            os.unlink(i)


def _create_testfunc(cmd, do_setup):
    def cmdtemplate():
        if do_setup:
            setup()
        cmd.run()
    return cmdtemplate


def _make_testcases():
    """
    Turn all the registered cli strings into test functions that
    the test runner can scoop up
    """
    cmdlist = []
    cmdlist += vinst.cmds
    cmdlist += vclon.cmds
    cmdlist += vixml.cmds
    cmdlist += ARGCOMPLETE_CMDS

    newidx = 0
    for cmd in cmdlist:
        newidx += 1
        # Generate numbered names like testCLI%d
        name = "testCLI%.4d" % newidx

        if cmd.compare_file:
            base = os.path.splitext(os.path.basename(cmd.compare_file))[0]
            name += base.replace("-", "_")
        else:
            name += os.path.basename(cmd.app.replace("-", "_"))

        do_setup = newidx == 1
        testfunc = _create_testfunc(cmd, do_setup)
        globals()[name] = testfunc


_make_testcases()
atexit.register(cleanup)

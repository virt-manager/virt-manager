# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import atexit
import io
import os
import re
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

os.environ["HOME"] = "/tmp"
os.environ["DISPLAY"] = ":3.4"

TMP_IMAGE_DIR = "/tmp/__virtinst_cli_"
_ABSXMLDIR = utils.DATADIR + "/cli"
XMLDIR = os.path.relpath(_ABSXMLDIR, utils.TOPDIR)
MEDIA_DIR = os.path.relpath(utils.DATADIR + "/fakemedia", utils.TOPDIR)
UNATTENDED_DIR = XMLDIR + "/unattended"
OLD_OSINFO = utils.has_old_osinfo()
NO_OSINFO_UNATTEND = not unattended.OSInstallScript.have_new_libosinfo()
HAS_xorriso = shutil.which("xorriso")

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

    TMP_IMAGE_DIR + "test-clone1.file",
    TMP_IMAGE_DIR + "other-serial-clone.file",
    TMP_IMAGE_DIR + "serial-exists-clone-1.file",
]

# Images that are expected to exist before a command is run
EXIST_FILES = [
    TMP_IMAGE_DIR + "exist1.img",
    TMP_IMAGE_DIR + "exist2.img",

    TMP_IMAGE_DIR + "serial-exists-clone.file",
]


TEST_DATA = {
    'URI-TEST-FULL': utils.URIs.test_full,
    'URI-TEST-REMOTE': utils.URIs.test_remote,
    'URI-KVM-X86': utils.URIs.kvm_x86,
    'URI-KVM-X86-NODOMCAPS': utils.URIs.kvm_x86_nodomcaps,
    'URI-KVM-ARMV7L': utils.URIs.kvm_armv7l,
    'URI-KVM-AARCH64': utils.URIs.kvm_aarch64,
    'URI-KVM-LOONGARCH64': utils.URIs.kvm_loongarch64,
    'URI-KVM-PPC64LE': utils.URIs.kvm_ppc64le,
    'URI-KVM-S390X': utils.URIs.kvm_s390x,
    'URI-QEMU-RISCV64': utils.URIs.qemu_riscv64,

    'XMLDIR': XMLDIR,
    'NEWIMG1': "/pool-dir/new1.img",
    'NEWIMG2': "/pool-dir/new2.img",
    'NEWCLONEIMG1': NEW_FILES[0],
    'NEWCLONEIMG2': NEW_FILES[1],
    'NEWCLONEIMG3': NEW_FILES[2],
    'EXISTIMG1': "/pool-dir/testvol1.img",
    'EXISTIMG2': "/pool-dir/testvol2.img",
    'EXISTIMG3': EXIST_FILES[0],
    'EXISTIMG4': EXIST_FILES[1],
    'ISOTREE': "%s/fake-fedora17-tree.iso" % MEDIA_DIR,
    'ISOLABEL': "%s/fake-centos65-label.iso" % MEDIA_DIR,
    'ISO-NO-OS': "%s/fake-no-osinfo.iso" % MEDIA_DIR,
    'ISO-WIN7': "%s/fake-win7.iso" % MEDIA_DIR,
    'ISO-F26-NETINST': "%s/fake-f26-netinst.iso" % MEDIA_DIR,
    'ISO-F29-LIVE': "%s/fake-f29-live.iso" % MEDIA_DIR,
    'TREEDIR': "%s/fakefedoratree" % MEDIA_DIR,
    'COLLIDE': "/pool-dir/collidevol1.img",
    'ADMIN-PASSWORD-FILE': "%s/admin-password.txt" % UNATTENDED_DIR,
    'USER-PASSWORD-FILE': "%s/user-password.txt" % UNATTENDED_DIR,
}


def has_old_osinfo():
    if OLD_OSINFO:
        return "osinfo is too old"


def missing_xorriso():
    if not HAS_xorriso:
        return "xorriso not installed"


def no_osinfo_unattend_cb():
    if NO_OSINFO_UNATTEND:
        return "osinfo is too old for unattended testing"


def no_osinfo_unattended_win_drivers_cb():
    win7 = OSDB.lookup_os("win7")
    devs = win7.get_pre_installable_devices("x86_64")
    devids = [d.get_id() for d in devs]
    if "http://pcisig.com/pci/1af4/1005" not in devids:
        return "osinfo is too old for this win7 unattended test"


def no_osinfo_linux2020_virtio():
    linux2020 = OSDB.lookup_os("linux2020")
    if not linux2020 or not linux2020.supports_virtiogpu():
        return "osinfo is too old: missing linux2020 with virtio-gpu"


def no_osinfo_win11():
    win11 = OSDB.lookup_os("win11")
    if not win11:
        return "osinfo is too old: no win11 entry"


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

        # Strip the test directory out of the saved output
        search = '"%s/' % utils.TOPDIR
        if search in output:
            output = output.replace(search, "\"TESTSUITE_SCRUBBED/")

        utils.diff_compare(output, self.compare_file)

        self.skip_checks.predefine_skip(conn)

        # Define the <domain>s generated for compare output, to ensure
        # we are generating valid XML
        if "--print-xml" in self.argv or "--print-step" in self.argv:
            for domxml in output.split("</domain>"):
                if "<domain" not in domxml:
                    continue
                domxml = "<domain" + domxml.split("<domain", 1)[1]
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

        if self.grep and not re.search(self.grep, output):
            _raise_error("Didn't find regex grep=%s" % self.grep)
        if self.nogrep and re.search(self.nogrep, output):
            _raise_error("Found regex grep=%s when we shouldn't see it" %
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
        if "grep" not in kwargs:
            raise RuntimeError("grep= must be passed for add_invalid")
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

c = vinst.add_category("xml-comparsion", "--connect %(URI-KVM-X86)s --noautoconsole --os-variant fedora-unknown", prerun_check=has_old_osinfo)


# many-devices, the main XML coverage tester
c.add_compare("""
--boot firmware=efi,\
firmware.feature0.enabled=true,firmware.feature0.name=secure-boot,\
firmware.feature1.enabled=off,firmware.feature1.name=enrolled-keys,\
emulator=/new/emu,bootloader=/new/bootld,bootloader_args='--append single',rebootTimeout=3,\
initargs="foo=bar baz=woo",initdir=/my/custom/cwd,inituser=tester,initgroup=1000,\
bios.useserial=no,bios.rebootTimeout=60,cmdline=root=/foo,\
bootmenu.enable=yes,bootmenu.timeout=5000,\
acpi.table=/path/to/slic.dat,acpi.table.type=slic,\
initenv0.name=MYENV,initenv0='some value',initenv1.name=FOO,initenv1=bar,\
initdir=/my/custom/cwd,inituser=tester,initgroup=1000


--vcpus vcpus=9,vcpu.placement=static,\
vcpus.vcpu2.id=0,vcpus.vcpu2.enabled=no,\
vcpus.vcpu3.id=1,vcpus.vcpu3.hotpluggable=no,vcpus.vcpu3.enabled=yes,\
vcpus.vcpu.id=3,vcpus.vcpu0.enabled=yes,vcpus.vcpu0.order=3,\
vcpus.vcpu1.id=2,vcpus.vcpu1.enabled=yes


--cpu foobar,+x2apic,+x2apicagain,-distest,forbid=foo,forbid=bar,disable=distest2,optional=opttest,require=reqtest,match=strict,vendor=meee,mode=custom,check=partial,\
topology.sockets=1,topology.dies=1,topology.cores=3,topology.threads=3,\
model.fallback=allow,model.vendor_id=GenuineIntel,\
cell.id=0,cell.cpus=1,2,3,cell.memory=1024,\
cell1.id=1,cell1.memory=256,cell1.cpus=5-8,\
numa.cell2.id=2,numa.cell2.memory=256,numa.cell2.unit=KiB,numa.cell2.cpus=4,numa.cell2.memAccess=shared,numa.cell2.discard=no,\
cell0.distances.sibling0.id=0,cell0.distances.sibling0.value=10,\
cell0.distances.sibling1.id=1,cell0.distances.sibling1.value=21,\
numa.cell1.distances.sibling0.id=0,numa.cell1.distances.sibling0.value=21,\
numa.cell2.cache0.level=1,numa.cell2.cache0.associativity=direct,numa.cell2.cache0.policy=writeback,\
numa.cell2.cache0.size.value=256,numa.cell2.cache0.size.unit=KiB,numa.cell2.cache0.line.value=256,numa.cell2.cache0.line.unit=KiB,\
cell1.distances.sibling1.id=1,cell1.distances.sibling1.value=10,\
numa.interconnects.latency0.initiator=0,numa.interconnects.latency0.target=0,numa.interconnects.latency0.type=access,numa.interconnects.latency0.value=5,\
numa.interconnects.latency1.initiator=0,numa.interconnects.latency1.target=2,numa.interconnects.latency1.cache=1,numa.interconnects.latency1.type=access,numa.interconnects.latency1.value=10,numa.interconnects.latency1.unit=ns,\
numa.interconnects.bandwidth0.initiator=0,numa.interconnects.bandwidth0.target=0,numa.interconnects.bandwidth0.type=access,numa.interconnects.bandwidth0.value=204800,\
numa.interconnects.bandwidth1.initiator=0,numa.interconnects.bandwidth1.target=2,numa.interconnects.bandwidth1.cache=1,numa.interconnects.bandwidth1.type=access,numa.interconnects.bandwidth1.value=409600,numa.interconnects.bandwidth1.unit=KiB,\
cache.mode=emulate,cache.level=3,\
maxphysaddr.mode=emulate,maxphysaddr.bits=46


--numatune 1,2,3,5-7,^6,mode=strict,\
memnode0.cellid=1,memnode0.mode=strict,memnode0.nodeset=2


--cputune shares=2048,period=1000000,quota=-1,global_period=1000000,global_quota=-1,emulator_period=1000000,emulator_quota=-1,iothread_period=1000000,iothread_quota=-1,\
vcpupin0.vcpu=0,vcpupin0.cpuset=0-3,emulatorpin.cpuset=1,7,iothreadpin0.iothread=1,iothreadpin0.cpuset=1,7,\
emulatorsched.scheduler=rr,emulatorsched.priority=99,vcpusched0.vcpus=0-3,^2,vcpusched0.scheduler=fifo,vcpusched0.priority=95,iothreadsched0.iothreads=1,2,iothreadsched0.scheduler=fifo,iothreadsched0.priority=90,\
cachetune0.vcpus=0-3,\
cachetune0.cache0.level=3,cachetune0.cache0.id=0,cachetune0.cache0.type=both,cachetune0.cache0.size=3,cachetune0.cache0.unit=MiB,\
cachetune0.cache1.level=3,cachetune0.cache1.id=1,cachetune0.cache1.type=both,cachetune0.cache1.size=3,cachetune0.cache1.unit=MiB,\
cachetune0.monitor0.level=3,cachetune0.monitor0.vcpus=2,\
cachetune0.monitor1.level=3,cachetune0.monitor1.vcpus=0-3,^2,\
cachetune1.vcpus=4-5,\
cachetune1.monitor0.level=3,cachetune1.monitor0.vcpus=4,\
cachetune1.monitor1.level=3,cachetune1.monitor1.vcpus=5,\
memorytune0.vcpus=0-3,memorytune0.node0.id=0,memorytune0.node0.bandwidth=60


--memtune hard_limit=10,soft_limit=20,swap_hard_limit=30,min_guarantee=40


--blkiotune weight=100,device_path=/home/test/1.img,device_weight=200,read_bytes_sec=10000,write_bytes_sec=10000,read_iops_sec=20000,write_iops_sec=20000


--memorybacking size=1,unit='G',nodeset=0,1,nosharepages=yes,locked=yes,discard=yes,allocation.mode=immediate,access_mode=shared,source_type=file,hugepages.page.size=12,hugepages.page1.size=1234,hugepages.page1.unit=MB,hugepages.page1.nodeset=2,allocation.threads=8


--iothreads iothreads=5,iothreadids.iothread0.id=1,iothreadids.iothread1.id=2,iothreadids.iothread1.thread_pool_min=8,iothreadids.iothread1.thread_pool_max=16,defaultiothread.thread_pool_min=4,defaultiothread.thread_pool_max=32


--metadata title=my-title,description=my-description,uuid=00000000-1111-2222-3333-444444444444,genid=e9392370-2917-565e-692b-d057f46512d6,genid_enable=yes


--features apic.eoi=off,hap=on,pae=on,pmu.state=on,pvspinlock.state=off,smm.state=off,viridian=on,vmcoreinfo.state=on,vmport.state=off,kvm.hidden.state=on,gic.version=host,kvm.hint-dedicated.state=on,kvm.poll-control.state=on,ioapic.driver=qemu,acpi=off,eoi=on,privnet=on,vmport=off,pmu=off,vmcoreinfo=on,kvm_hidden=off,smm=off,\
hyperv.relaxed.state=off,\
hyperv.vapic.state=off,hyperv_vapic=on,\
hyperv.spinlocks.state=on,hyperv_spinlocks=on,\
hyperv.spinlocks.retries=5678,hyperv_spinlocks_retries=5678,\
hyperv.vpindex.state=on,\
hyperv.runtime.state=on,\
hyperv.synic.state=on,hyperv_synic=on,\
hyperv.stimer.state=on,\
hyperv.stimer.direct.state=on,\
hyperv.reset.state=off,hyperv_reset=on,\
hyperv.frequencies.state=on,\
hyperv.reenlightenment.state=on,\
hyperv.tlbflush.state=on,\
hyperv.ipi.state=on,\
hyperv.evmcs.state=on,\
hyperv.avic.state=on,\
kvm.pv-ipi.state=on,\
msrs.unknown=ignore


--clock offset=utc,hpet_present=no,rtc_tickpolicy=merge,timer2.name=hypervclock,timer3.name=pit,timer1.present=yes,timer3.tickpolicy=delay,timer2.present=no,timer4.name=rtc,timer5.name=tsc,timer6.name=tsc,timer4.track=wall,timer5.frequency=10,timer6.mode=emulate,timer7.name=rtc,timer7.tickpolicy=catchup,timer7.catchup.threshold=123,timer7.catchup.slew=120,timer7.catchup.limit=10000,rtc_present=no,pit_present=yes,pit_tickpolicy=catchup,tsc_present=no,platform_present=no,hypervclock_present=no,platform_tickpolicy=foo,hpet_tickpolicy=bar,tsc_tickpolicy=wibble,kvmclock_tickpolicy=wobble,hypervclock_tickpolicy=woo


--keywrap cipher0.name=aes,cipher0.state=on


--pm suspend_to_mem=yes,suspend_to_disk=no


--resource /virtualmachines/production,fibrechannel.appid=myapplication


--events on_poweroff=destroy,on_reboot=restart,on_crash=preserve,on_lockfailure=ignore


--idmap uid_start=0,uid_target=1000,uid_count=10,gid_start=0,gid_target=1000,gid_count=10


--sysinfo type=smbios,bios_vendor="Acme LLC",bios_version=1.2.3,bios_date=01/01/1970,bios_release=10.22
--sysinfo type=smbios,system_manufacturer="Acme Inc.",system_product=Computer,system_version=3.2.1,system_serial=123456789,system_uuid=00000000-1111-2222-3333-444444444444,system_sku=abc-123,system_family=Server
--sysinfo type=smbios,baseBoard_manufacturer="Acme Corp.",baseBoard_product=Motherboard,baseBoard_version=A01,baseBoard_serial=1234-5678,baseBoard_asset=Tag,baseBoard_location=Chassis
--sysinfo type=smbios,chassis.manufacturer="Chassis Corp.",chassis.serial=1234chassis,chassis.asset=chasset,chassis.sku=chassku,chassis.version=4.0
--sysinfo type=smbios,oemStrings.entry2="complicated parsing, foo=bar",oemStrings.entry1=test1,oemStrings.entry0=test0
--sysinfo bios.vendor="Acme LLC",bios.version=1.2.3,bios.date=01/01/1970,bios.release=10.22,system.manufacturer="Acme Inc.",system.product=Computer,system.version=3.2.1,system.serial=123456789,system.uuid=00000000-1111-2222-3333-444444444444,system.sku=abc-123,system.family=Server,baseBoard.manufacturer="Acme Corp.",baseBoard.product=Motherboard,baseBoard.version=A01,baseBoard.serial=1234-5678,baseBoard.asset=Tag,baseBoard.location=Chassis


--disk type=block,source.dev=/pool-dir/UPPER,cache=writeback,io=threads,perms=sh,serial=WD-WMAP9A966149,wwn=123456789abcdefa,boot_order=2,driver.iothread=3,driver.queues=8
--disk source.file=%(NEWIMG1)s,sparse=false,size=.001,perms=ro,error_policy=enospace,detect_zeroes=unmap,address.type=drive,address.controller=0,address.target=2,address.unit=0
--disk device=cdrom,bus=sata,read_bytes_sec=1,read_iops_sec=2,write_bytes_sec=5,write_iops_sec=6,driver.copy_on_read=on,geometry.cyls=16383,geometry.heads=16,geometry.secs=63,geometry.trans=lba,discard=ignore
--disk size=1
--disk /pool-iscsi/diskvol1,total_bytes_sec=10,total_iops_sec=20,bus=scsi,device=lun,sgio=filtered,rawio=yes
--disk /pool-dir/iso-vol,seclabel.model=dac,seclabel1.model=selinux,seclabel1.relabel=no,seclabel0.label=foo,bar,baz,iotune.read_bytes_sec=1,iotune.read_iops_sec=2,iotune.write_bytes_sec=5,iotune.write_iops_sec=6
--disk /pool-dir/iso-vol,format=qcow2,startup_policy=optional,iotune.total_bytes_sec=10,iotune.total_iops_sec=20,
--disk source_pool=pool-rbd-ceph,source_volume=some-rbd-vol,size=.1,driver_type=raw,driver_name=qemu
--disk pool=pool-rbd-ceph,size=.1,driver.name=qemu,driver.type=raw,driver.discard=unmap,driver.detect_zeroes=unmap,driver.io=native,driver.error_policy=stop
--disk source_protocol=http,source_host_name=example.com,source_host_port=8000,source_name=/path/to/my/file
--disk source.protocol=http,source.host0.name=exampl2.com,source.host.port=8000,source.name=/path/to/my/file
--disk source.protocol=nbd,source.host.transport=unix,source.host.socket=/tmp/socket,snapshot_policy=no
--disk source.protocol=nbd,source_host_transport=unix,source_host_socket=/tmp/socket,bus=scsi,logical_block_size=512,physical_block_size=512,blockio.logical_block_size=512,blockio.physical_block_size=512,target.dev=sdz,rotation_rate=5000
--disk gluster://192.168.1.100/test-volume/some/dir/test-gluster.qcow2
--disk nbd+unix:///var/foo/bar/socket,bus=usb,removable=on,address.type=usb,address.bus=0,address.port=2
--disk path=http://[1:2:3:4:1:2:3:4]:5522/my/path?query=foo
--disk vol=pool-gluster/test-gluster.raw
--disk /var,device=floppy,snapshot=no,perms=rw
--disk %(NEWIMG2)s,size=1,backing_store=/tmp/foo.img,backing_format=vmdk,bus=usb,target.removable=yes
--disk /tmp/brand-new.img,size=1,backing_store=/pool-dir/iso-vol,boot.order=10,boot.loadparm=5
--disk path=/dev/pool-logical/diskvol7,device=lun,bus=scsi,reservations.managed=no,reservations.source.type=unix,reservations.source.path=/var/run/test/pr-helper0.sock,reservations.source.mode=client,\
source.reservations.managed=no,source.reservations.source.type=unix,source.reservations.source.path=/var/run/test/pr-helper0.sock,source.reservations.source.mode=client,target.rotation_rate=6000
--disk vol=pool-iscsi-direct/unit:0:0:1
--disk size=.0001,format=raw,transient=on,transient.shareBacking=yes
--disk size=.0001,pool=pool-logical
--disk path=%(EXISTIMG1)s,type=dir
--disk path=file:///fooroot.img,size=.0001,transient=on
--disk source.dir=/
--disk type=nvme,source.type=pci,source.managed=no,source.namespace=2,source.address.domain=0x0001,source.address.bus=0x02,source.address.slot=0x00,source.address.function=0x0
--disk /tmp/disk1.qcow2,size=16,driver.type=qcow2,driver.metadata_cache.max_size=2048,driver.metadata_cache.max_size.unit=KiB
--disk /tmp/disk2.qcow2,size=16,driver.type=qcow2,driver.discard=unmap,driver.discard_no_unref=on
--disk /tmp/disk3.qcow2,size=16,driver.type=qcow2,blockio.discard_granularity=4096


--network user,mac=12:34:56:78:11:22,portgroup=foo,link_state=down,rom_bar=on,rom_file=/tmp/foo
--network bridge=foobar,model=virtio,driver_name=qemu,driver_queues=3,filterref=foobar,rom.bar=off,rom.file=/some/rom,source.portgroup=foo
--network bridge=ovsbr,virtualport.type=openvswitch,virtualport_profileid=demo,virtualport_interfaceid=09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b,link.state=yes,driver.name=qemu,driver.queues=3,filterref.filter=filterbar,target.dev=mytargetname,virtualport.parameters.profileid=demo,virtualport.parameters.interfaceid=09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b
--network type=direct,source=eth5,source_mode=vepa,source.mode=vepa,target=mytap12,virtualport_type=802.1Qbg,virtualport_managerid=12,virtualport_typeid=1193046,virtualport_typeidversion=1,virtualport_instanceid=09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b,boot_order=1,trustGuestRxFilters=yes,mtu.size=1500,virtualport.parameters.managerid=12,virtualport.parameters.typeid=1193046,virtualport.parameters.typeidversion=1,virtualport.parameters.instanceid=09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b,boot_order=1,trustGuestRxFilters=yes,mtu.size=1500
--network user,model=virtio,address.type=spapr-vio,address.reg=0x500,link.state=no
--network vhostuser,source_type=unix,source_path=/tmp/vhost1.sock,source_mode=server,model=virtio,source.type=unix,source.path=/tmp/vhost1.sock,address.type=pci,address.bus=0x00,address.slot=0x10,address.function=0x0,address.domain=0x0000
--network user,address.type=ccw,address.cssid=0xfe,address.ssid=0,address.devno=01,boot.order=15,boot.loadparm=SYSTEM1
--network model=vmxnet3
--network backend.type=passt,backend.logFile=/tmp/foo.log,portForward0.proto=tcp,portForward0.address=192.168.10.10,portForward0.dev=eth0,portForward0.range0.start=4000,portForward0.range0.end=5000,portForward0.range0.to=10000,portForward0.range0.exclude=no,portForward0.range1.start=6000,portForward1.proto=tcp,portForward1.range0.start=2022,portForward1.range0.to=22
--network passt,portForward=8080:80
--network passt,portForward=8080
--network passt,portForward0=7000-8000/udp,portForward1=127.0.0.1:2222:22
--network passt,portForward0=2001:db8:ac10:fd01::1:10:3000-4000:30,portForward1=127.0.0.1:5000-6000:5
--network type=hostdev,source.address.type=pci,source.address.domain=0x0,source.address.bus=0x00,source.address.slot=0x07,source.address.function=0x0
--network hostdev=pci_0000_00_09_0
--network hostdev=0:0:4.0


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
--controller pci,index=0,model=pcie-root-port,target.chassis=1,target.port=1,target.hotplug=off
--controller pci,index=1,model=pci-root,target.index=1
--controller pci,index=2,model=pci-bridge,target.chassisNr=1
--controller pci,index=3,model=pci-expander-bus,target.busNr=252,target.node=1
--controller usb3
--controller scsi,model=virtio-scsi
--controller usb2


--input type=keyboard,bus=usb
--input tablet
--input mouse
--input mouse,bus=virtio,model=virtio-non-transitional
--input passthrough,source.evdev=/dev/input/event1,bus=virtio
--input evdev,source.dev=/dev/input/event1234,source.repeat=on,source.grab=all,source.grabToggle=ctrl-ctrl
--input mouse,model=FOOBAR,xpath0.set=./@bus=usb,xpath2.set=./address/@type=usb,xpath6.set=./willbeoverwritten=foo,xpath6.create=./randomelement,xpath7.create=./deleteme,xpath8.delete=./deleteme,xpath9.set=./@model=,xpath10.set=./@type,xpath10.value=keyboard


--serial char_type=tcp,host=:2222,mode=bind,protocol=telnet,log.file=/tmp/foo.log,log.append=yes,,target.model.name=pci-serial,source.tls=on
--serial nmdm,source.master=/dev/foo1,source.slave=/dev/foo2,alias.name=testalias7
--serial spiceport,source.channel=org.qemu.console.serial.0


--parallel type=udp,host=0.0.0.0:1234,bind_host=127.0.0.1:1234
--parallel udp,source.connect_host=127.0.0.2,source.connect_service=8888,source.bind_host=127.0.0.1,source.bind_service=7777
--parallel unix,path=/tmp/foo-socket,source.seclabel0.model=none,source.seclabel1.model=dac,source.seclabel1.relabel=yes,source.seclabel1.label=foobar,source.seclabel.relabel=no


--channel pty,target_type=guestfwd,target_address=127.0.0.1:10000
--channel pty,target_type=guestfwd,target.address=127.0.0.1,target.port=1234
--channel pty,target_type=virtio,name=org.linux-kvm.port1
--channel pty,target.type=virtio,target.name=org.linux-kvm.port2
--channel spicevmc
--channel qemu-vdagent,source.clipboard.copypaste=on,source.mouse.mode=client


--console pty,target_type=virtio


--hostdev net_00_1c_25_10_b1_e4,boot_order=4,rom_bar=off
--host-device usb_device_781_5151_2004453082054CA1BEEE
--host-device 001.003
--hostdev 15:0.1
--host-device 2:15:0.2
--hostdev 0:15:0.3,address.type=pci,address.zpci.uid=0xffff,address.zpci.fid=0xffffffff
--host-device 0x062a:0x0001,driver_name=vfio
--host-device 0483:2016
--host-device pci_8086_2829_scsi_host_scsi_device_lun0,rom.bar=on
--hostdev usb_5_20 --hostdev usb_5_21
--hostdev wlan0,type=net
--hostdev /dev/vdz,type=storage
--hostdev /dev/pty7,type=misc


--filesystem /source,/target,alias.name=testfsalias,driver.ats=on,driver.iommu=off,driver.packed=on,driver.page_per_vq=off
--filesystem template_name,/,type=template,mode=passthrough
--filesystem type=file,source=/tmp/somefile.img,target=/mount/point,accessmode=squash,driver.format=qcow2,driver.type=path,driver.wrpolicy=immediate
--filesystem type-mount,source.dir=/,target=/
--filesystem type=template,source.name=foo,target=/
--filesystem type=file,source.file=foo.img,target=/
--filesystem type=volume,model=virtio,multidevs=remap,readonly=on,space_hard_limit=1234,space_soft_limit=500,source.pool=pool1,source.volume=vol,driver.name=virtiofs,driver.queue=3,binary.path=/foo/virtiofsd,binary.xattr=off,binary.cache.mode=always,binary.lock.posix=off,binary.lock.flock=on,target.dir=/foo,binary.sandbox.mode=chroot,source.socket=/tmp/foo.sock
--filesystem type=block,source.dev=/dev/foo,target.dir=/
--filesystem type=ram,source.usage=1024,source.units=MiB,target=/
--filesystem /foo/source,/bar/target,fmode=0123,dmode=0345
--filesystem /foo1,/bar1,driver.type=virtiofs


--soundhw default
--sound ac97
--sound codec0.type=micro,codec1.type=duplex,codec2.type=output
--sound model=usb,multichannel=yes
--sound model=virtio,streams=4


--audio id=1,type=spice
--audio id=2,type=pulseaudio


--video cirrus
--video model=qxl,vgamem=1,ram=2,vram=3,heads=4,accel3d=yes,vram64=65
--video model=qxl,model.vgamem=1,model.ram=2,model.vram=3,model.heads=4,model.acceleration.accel3d=yes,model.vram64=65
--video model=virtio,model.blob=on


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


--rng /dev/random
--rng device=/dev/urandom,backend.protocol.type=,backend.log.file=,backend.log.append=,backend.source.clipboard.copypaste=,backend.source.mouse.mode=,backend.source.channel=,backend.source.tls=
--rng type=egd,backend.type=nmdm,backend.source.master=/dev/foo1,backend.source.slave=/dev/foo2
--rng egd,backend_host=127.0.0.1,backend_service=8000,backend_type=udp,backend_mode=bind,backend_connect_host=foo,backend_connect_service=708,rate.bytes=1234,rate.period=1000,model=virtio


--panic iobase=507,,address.type=isa,address.iobase=0x500,address.irq=5


--shmem shmem0,role=master,model.type=ivshmem-plain,size=8,size.unit=M
--shmem name=my_shmem0,role=peer,model.type=ivshmem-plain,size=4,size.unit=M
--shmem name=shmem_server,model.type=ivshmem-doorbell,size=2,size.unit=M,server.path=/tmp/socket-shmemm,msi.vectors=32,msi.ioeventfd=on


--vsock cid=17


--tpm passthrough,model=tpm-crb,path=/dev/tpm0,backend.encryption.secret=11111111-2222-3333-4444-5555555555,backend.persistent_state=yes,backend.active_pcr_banks.sha1=on,backend.active_pcr_banks.sha256=yes,backend.active_pcr_banks.sha384=yes,backend.active_pcr_banks.sha512=yes,version=2.0

--tpm model=tpm-tis,backend.type=emulator,backend.version=2.0,backend.debug=3,backend.source.type=dir,backend.source.path=/some/dir


--watchdog ib700,action=pause


--memballoon virtio,autodeflate=on,stats.period=10,freePageReporting=on


--iommu model=intel,driver.aw_bits=48,driver.caching_mode=on,driver.eim=off,driver.intremap=off,driver.iotlb=off


--seclabel type=static,label='system_u:object_r:svirt_image_t:s0:c100,c200',relabel=yes,baselabel=baselabel
--seclabel type=dynamic,label=012:345


--launchSecurity type=sev,reducedPhysBits=1,policy=0x0001,cbitpos=47,dhCert=BASE64CERT,session=BASE64SESSION,kernelHashes=yes


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


""", "many-devices", predefine_check="8.4.0")

# Need to extract from the many-devices test as it was fixed in libvirt 10.4.0
c.add_compare("""
--hostdev mdev_8e37ee90_2b51_45e3_9b25_bf8283c03110,address.type=ccw,address.cssid=0xfe,address.ssid=0x1,address.devno=0x0008
--hostdev mdev_11f92c9d_b0b0_4016_b306_a8071277f8b9
--hostdev mdev_4b20d080_1b54_4048_85b3_a6a62d165c01,address.type=pci,address.domain=0x0000,address.bus=0x01,address.slot=0x01,address.function=0x0,address.zpci.uid=0x0001,address.zpci.fid=0x00000001
""", "mdev-devices", prerun_check="10.4.0")


# Specific XML test cases #1
c.add_compare(
"--memory 512,maxmemory=1024 "  # special --memory XXX,maxmemory= handling
"--description \"foobar & baz\" "  # compat --description handling
"--uuid 12345678-12F4-1234-1234-123456789AFA "  # compat --uuid handling
"--vcpus sockets=2,threads=2,dies=1,sockets=2 "  # --vcpus determine count from topology
"--cpuset 1,3-5 "  # setting compat --cpuset when --vcpus is present
"--seclabel relabel=yes "  # lets libvirt fill in type and model
"--sysinfo host "  # special `--sysinfo host` handling
"--noapic --noacpi "  # feature backcompat
"--boot uefi,cdrom,fd,hd,network,menu=on "  # uefi for default devices, + old style bootorder
"--launchSecurity sev "  # sev defaults

# Disabling all the default device setup
"""
--cpu none
--disk none
--console none
--channel none
--network none
--sound none
--redirdev none
--memballoon none
--smartcard none
--tpm none
--rng none
--input none
""", "singleton-config-1")


# Specific XML test cases #2
c.add_compare("--pxe "
"--ram 4000000 "  # Ram overcommit
"--cpu host-copy "  # test host-copy back compat
"--seclabel type=dynamic "  # test a fallback case when guessing model=
"--sysinfo emulate "  # special `--sysinfo emulate` handling
"--cpuset 1,3-5 "  # setting compat --cpuset when --vcpus is not present
# --boot loader settings here, or they will conflict with firmware=efi
# in other test cases
"--boot loader_ro=yes,loader.type=rom,loader=/tmp/foo,loader_secure=no,loader.stateless=yes"

# 'default' handling for solo devices
"""
--tpm default
--panic default
--memballoon default
--watchdog default
--vsock default
""", "singleton-config-2", predefine_check="7.2.0")


# Specific XML test cases #3
c.add_compare(""
" --cpu qemu64,secure=off "  # disable security features that are added by default
"--sysinfo type=fwcfg,entry0.name=foo,entry0.file=bar,entry0=baz "  # --sysinfo type=fwcfg options
"--boot smbios.mode=emulate,boot1.dev=hd,boot.dev=network,initarg1=bar=baz,initarg=foo "  # --boot option conflicts
"--memory currentMemory=100,memory=200,maxmemory=300,maxMemory=400,maxMemory.slots=1 "  # --memory option backcompat handling
"--graphics spice,gl=yes "  # gl=on enables --video virtio 3d accel
"--cpuset auto "  # confirm `--cpuset auto` works
"--vcpus vcpu.current=2,maxvcpus=4 "  # special current + max handling
"--vsock auto_cid=on "  # --vsock auto cid must be specified on its own
"--tpm /dev/tpm0 "  # --tpm PATH compat handling
"", "singleton-config-3", predefine_check="5.7.0")



# --memdev setup has a lot of interconnected validation, it's easier to keep this separate
c.add_compare("--pxe "
"--memory hotplugmemorymax=4096,hotplugmemoryslots=3 "
"--cpu cell0.cpus=0,cell0.memory=1048576 "

"--memdev dimm,access=private,target_size=256,target_node=0,"
"source_pagesize=4,source_nodemask=1-2,discard=on "
"--memdev dimm,access=private,target_size=256,target_node=0,"
"source.pagesize=4,source.nodemask=1-2,discard=on "

"--memdev nvdimm,source_path=/path/to/nvdimm,"
"target_size=512,target_node=0,target_label_size=128,alias.name=mymemdev3,"
"target.block=2048,target.requested=1048576,target.current=524288,"
"address.type=dimm,address.base=0x100000000,address.slot=1,"
"source.pmem=on,source.alignsize=2048,target.readonly=on "

"--memdev virtio-mem,target_node=0,target.block=2048,"
"target_size=512,target.requested=524288,target.address_base=0x180000000 "

"--memdev virtio-pmem,source.path=/tmp/virtio_pmem,"
"target_size=512,target.address_base=0x1a0000000 "

"", "memory-hotplug", precompare_check="5.3.0")



# Hitting test driver specific output
c.add_compare("--connect " + utils.URIs.test_suite + " "
"--cpu host-passthrough,migratable=on,maxphysaddr.mode=passthrough "  # migratable=on is only accepted with host-passthrough
"--seclabel label=foobar.label,a1,z2,b3,relabel=yes,type=dynamic "  # fills in default model=testModel
"--tpm default "  # --tpm default when domcaps missing
"",
"testdriver-edgecases")


# Test various storage corner cases
c.add_compare(
"--disk path=%(EXISTIMG1)s "  # Existing disk, no extra options
"--disk pool=pool-dir,size=.0001 --disk pool=pool-dir,size=.0001 "  # Create 2 volumes in a pool
"--disk path=%(EXISTIMG1)s,bus=ide --disk path=%(EXISTIMG1)s,bus=ide --disk path=%(EXISTIMG1)s,bus=ide --disk path=%(EXISTIMG1)s,device=cdrom,bus=ide "  # 3 IDE and CD
"--disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi "  # > 16 scsi disks
"--disk path=%(NEWIMG1)s,format=raw,size=.0000001 "  # Managed file using format raw
"--disk %(NEWIMG2)s,format=qcow2,size=.0000001 "  # Managed file using format qcow2
"--disk /dev/zero "  # Referencing a local unmanaged /dev node
"--disk pool=default,size=.00001 "  # Building 'default' pool
"--disk /some/new/pool/dir/new,size=.1 "  # autocreate the pool
"--disk /pool-dir/sharevol.img,perms=sh "  # Colliding shareable storage
"", "storage-creation")




########################
# Storage provisioning #
########################

c = vinst.add_category("storage", "--pxe --nographics --noautoconsole --hvm --osinfo detect=yes,require=no")
c.add_valid("--disk %(COLLIDE)s --check path_in_use=off")  # Colliding storage with --check
c.add_valid("--disk %(COLLIDE)s --force")  # Colliding storage with --force
c.add_valid("--disk %(NEWIMG1)s,sparse=true,size=100000000 --check disk_size=off")  # Don't warn about fully allocated file exceeding disk space
c.add_invalid("--disk /dev/zero --nodisks", grep="Cannot specify storage and use --nodisks")
c.add_invalid("--file %(NEWIMG1)s --file-size 100000 --nonsparse", grep="There is not enough free space")  # Nonexisting file, size too big
c.add_invalid("--file %(NEWIMG1)s --file-size 100000", grep="The requested volume capacity will exceed the")  # Huge file, sparse, but no prompting
c.add_invalid("--file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s", grep="Only 4 disks")  # Too many IDE
c.add_invalid("--disk device=disk", grep="requires a path")  # --disk device=disk, but no path
c.add_invalid("--disk pool=pool-logical,size=1,format=qcow2", grep="Format attribute not supported")  # format= invalid for disk pool
c.add_invalid("--disk pool=foopool,size=.0001", grep="no storage pool with matching name")  # Specify a nonexistent pool
c.add_invalid("--disk vol=pool-dir/foovol", grep="no storage vol with matching")  # Specify a nonexistent volume
c.add_invalid("--disk vol=pool-dir-no-slash", grep="Storage volume must be specified as vol=poolname/volname")  # Wrong vol= format
c.add_invalid("--disk perms=badformat", grep="Unknown 'perms' value")  # Wrong perms= format
c.add_invalid("--disk size=badformat", grep="could not convert string")  # Wrong size= format
c.add_invalid("--disk pool=pool-dir", grep="Size must be specified for non existent")  # Specify a pool with no size
c.add_invalid("--disk path=/dev/foo/bar/baz,format=qcow2,size=.0000001", grep="Use libvirt APIs to manage the parent")  # Unmanaged file using non-raw format
c.add_invalid("--disk path=/dev/pool-logical/newvol1.img,format=raw,size=.0000001", grep="Format attribute not supported for this volume type")  # Managed disk using any format
c.add_invalid("--disk %(NEWIMG1)s", grep="Size must be specified")  # Not specifying path= and non existent storage w/ no size
c.add_invalid("--disk %(NEWIMG1)s,sparse=true,size=100000000000", grep="The requested volume capacity will exceed")  # Fail if fully allocated file would exceed disk space
c.add_invalid("--connect %(URI-TEST-FULL)s --disk %(COLLIDE)s --prompt", grep="already in use by other guests")  # Colliding storage with --prompt should still fail
c.add_invalid("--connect %(URI-TEST-FULL)s --disk /pool-dir/backingl3.img", grep="already in use by other guests")  # Colliding storage via backing store
c.add_invalid("--connect %(URI-TEST-FULL)s --disk source_pool=pool-rbd-ceph,source_volume=vol1", grep="already in use by other guests")  # Collision with existing VM, via source pool/volume
c.add_invalid("--disk source.pool=pool-dir,source.volume=idontexist", grep="no storage vol with matching name 'idontexist'")  # trying to lookup non-existent volume, hit specific error code
c.add_invalid("--disk size=1 --seclabel model=foo,type=bar", grep="not appear to have been successful")  # Libvirt will error on the invalid security params, which should trigger the code path to clean up the disk images we created.
c.add_invalid("--disk size=1 --file foobar", grep="Cannot mix --file")  # --disk and --file collision



################################################
# Invalid devices that hit virtinst code paths #
################################################

c = vinst.add_category("invalid-devices", "--noautoconsole --nodisks --pxe --osinfo require=no")
c.add_invalid("--clock foo_tickpolicy=merge", grep="Unknown --clock options:.*'foo_tickpolicy'")  # Bad suboption
c.add_invalid("--connect %(URI-TEST-FULL)s --host-device 1d6b:2", grep="corresponds to multiple node devices")
c.add_invalid("--connect %(URI-TEST-FULL)s --host-device pci_8086_2850_scsi_host_scsi_host", grep="Unsupported node device type 'scsi_host'")  # Unsupported hostdev type
c.add_invalid("--host-device foobarhostdev", grep="Unknown hostdev address string format")  # Unknown hostdev
c.add_invalid("--host-device 300:400", grep="Did not find a matching node device")  # Parseable hostdev, but unknown digits
c.add_invalid("--controller address=foobar", grep="Expected PCI format string for 'foobar'")  # Invalid address= value
c.add_invalid("--graphics vnc,port=-50", grep="above 5900")  # Invalid port
c.add_invalid("--graphics spice,tlsport=5", grep="TLS Port must be")  # Invalid port
c.add_invalid("--vnc --sdl", grep="Can't specify more than one of VNC, SDL")  # Multi graphics option collision
c.add_invalid("--boot uefi", grep="Libvirt version does not support UEFI")  # URI doesn't support UEFI bits
c.add_invalid("--graphics type=vnc,keymap", grep="Option 'keymap' had no value set.")
c.add_invalid("--xml FOOXPATH", grep="form of XPATH=VALUE")  # failure parsing xpath value
c.add_invalid("--xml /@foo=bar", grep="/@foo xmlXPathEval")  # failure processing xpath



########################
# Install option tests #
########################

c = vinst.add_category("nodisk-install", "--nographics --noautoconsole --nodisks")
c.add_valid("--os-variant generic --pxe --ram 16", grep="Requested memory 16 MiB is abnormally low")  # catch low memory error
c.add_valid("--os-variant winxp --ram 32 --cdrom %(EXISTIMG1)s", grep="32 MiB is less than the recommended 64 MiB")  # Windows. Catch memory warning
c.add_valid("--osinfo generic --pxe --autostart")  # --autostart flag
c.add_valid("--cdrom %(EXISTIMG2)s --os-variant win2k3 --print-step 2")  # HVM windows install, print 3rd stage XML
c.add_valid("--memory 512 --osinfo generic --boot cdrom")  # --boot XXX should imply --install no_install
c.add_compare("--location location=%(TREEDIR)s --initrd-inject virt-install --extra-args ks=file:/virt-install", "initrd-inject")  # initrd-inject
c.add_compare("--cdrom http://example.com/path/to/some.iso --os-variant detect=yes,require=no", "cdrom-url")
c.add_compare("--pxe --print-step all --os-variant none", "simple-pxe")  # Diskless PXE install
c.add_compare("--location ftp://example.com --os-variant auto", "fake-ftp")  # fake ftp:// install using urlfetcher.py mocking
c.add_compare("--location https://foobar.com --os-variant detect=no,require=no", "fake-http")  # fake https:// install using urlfetcher.py mocking, but also hit --os-variant detect=no
c.add_compare("--location https://foobar.com --os-variant detect=yes,name=win7", "os-detect-success-fallback")  # os detection succeeds, so fallback should be ignored
c.add_compare("--pxe --os-variant detect=yes,name=win7", "os-detect-fail-fallback")  # os detection fails, so we use fallback name=
c.add_compare("--connect %(URI-KVM-X86)s --install fedora26", "osinfo-url")  # getting URL from osinfo
c.add_valid("--location https://foobar.com --os-variant detect=yes,name=win7", nogrep="Please file a bug against virt-install")  # os detection succeeds, the fallback warning shouldn't be printed
c.add_valid("--pxe --os-variant detect=yes,name=win7", grep="Please file a bug against virt-install")  # os detection fails, so fallback warning should be printed
c.add_valid("--cdrom http://example.com/path/to/some.iso --os-variant detect=yes,require=no", grep="Please file a bug against virt-install")  # detection fails with require=no, we should print the error about using fallback name=
c.add_invalid("--pxe --os-variant detect=yes,require=yes", grep="--os-variant/--osinfo OS name is required")  # No os-variant detected, but require=yes
c.add_invalid("--pxe --osinfo detect=yes", grep="--os-variant/--osinfo OS name is required")  # --osinfo detect=on failed, but with implied require=yes
c.add_invalid("--pxe --virt-type foobar", grep="Host does not support domain type")
c.add_invalid("--pxe --os-variant farrrrrrrge", grep="Unknown OS name")
c.add_invalid("--pxe --boot menu=foobar", grep="menu must be 'yes' or 'no'")
c.add_invalid("--cdrom %(EXISTIMG1)s --extra-args console=ttyS0", grep="Kernel arguments are only supported with")  # cdrom fail w/ extra-args
c.add_invalid("--hvm --boot kernel=%(TREEDIR)s/pxeboot/vmlinuz,initrd=%(TREEDIR)s/pxeboot/initrd.img,kernel_args='foo bar' --initrd-inject virt-install", grep="Install method does not support initrd inject")
c.add_invalid("--install winxp", grep="does not have a URL location")  # no URL for winxp
c.add_invalid("--boot arch=i686 --install fedora26", grep="does not have a URL location for the architecture 'i686")  # there's no URL for i686
c.add_invalid("-c foo --cdrom bar", grep="Cannot use -c")  # check for ambiguous -c and --cdrom collision
c.add_invalid("-c qemu:///system", grep="looks like a libvirt URI")  # error for the ambiguous -c vs --connect
c.add_invalid("--location /", grep="Error validating install location")  # detect_distro failure
c.add_invalid("--os-variant id=foo://bar", grep="Unknown libosinfo ID")  # bad full id
c.add_invalid("--location http://testsuitefail.com", grep="installable distribution")  # will trigger a particular mock failure
c.add_invalid("--cdrom %(EXISTIMG2)s", grep="expected virt-install to detect")  # hits the missing --osinfo error
c.add_invalid("--pxe", grep="linux2018, linux2016", nogrep="expected virt-install to detect")  # hits missing --osinfo error but doesn't trigger the bit about detectable media


c = vinst.add_category("single-disk-install", "--nographics --noautoconsole --disk %(EXISTIMG1)s")
c.add_valid("--osinfo generic --hvm --install no_install=yes")  # import install equivalent
c.add_valid("--osinfo generic --hvm --import --prompt --force")  # Working scenario w/ prompt shouldn't ask anything
c.add_valid("--paravirt --import")  # PV Import install
c.add_valid("--paravirt --print-xml 1")  # print single XML, implied import install
c.add_valid("--osinfo generic --hvm --import --wait 0", grep="Treating --wait 0 as --noautoconsole")  # --wait 0 is the same as --noautoconsole
c.add_compare("-c %(EXISTIMG2)s --osinfo win2k3 --vcpus cores=4 --controller usb,model=none", "w2k3-cdrom")  # HVM windows install with disk
c.add_compare("--connect %(URI-KVM-X86)s --install fedora26 --os-variant fedora27 --disk size=20", "osinfo-url-with-disk")  # filling in defaults, but with disk specified, and making sure we don't overwrite --os-variant
c.add_compare("--connect %(URI-KVM-X86)s --pxe --os-variant short-id=debianbuster --disk none", "osinfo-multiple-short-id", prerun_check=lambda: not OSDB.lookup_os("debianbuster"))  # test plumbing for multiple short ids
c.add_invalid("--osinfo generic --hvm --import --wait 2", grep="exceeded specified time limit")  # --wait positive number, but test suite hack
c.add_invalid("--osinfo generic --hvm --import --wait -1", grep="exceeded specified time limit")  # --wait -1, but test suite hack
c.add_invalid("--osinfo generic --hvm --import --wait", grep="exceeded specified time limit")  # --wait aka --wait -1, but test suite hack
c.add_invalid("--connect test:///default --name foo --ram 64 --disk none --sdl --osinfo generic --hvm --import", use_default_args=False, grep="exceeded specified time limit")  # --sdl doesn't have a console callback, triggers implicit --wait -1
c.add_invalid("--paravirt --import --print-xml 2", grep="does not have XML step 2")  # PV Import install, no second XML step
c.add_invalid("--paravirt --import --print-xml 7", grep="Unknown XML step request '7'")  # Invalid --print-xml arg
c.add_invalid("--location kernel=foo,initrd=bar", grep="location kernel/initrd may only be specified with a location URL/path")
c.add_invalid("--location http://example.com,kernel=foo", grep="location kernel/initrd must be specified as a pair")
c.add_valid("--pxe --os-variant generic --os-type linux", grep="--os-type is deprecated")
c.add_invalid("--os-variant solaris10 --unattended", grep="not support unattended")


c = vinst.add_category("misc-install", "--nographics --noautoconsole")
c.add_compare("--connect %s --os-variant generic" % (utils.URIs.test_suite), "noargs-fail", use_default_args=False)  # No arguments
c.add_compare("--connect %s --os-variant fedora26" % (utils.URIs.test_suite), "osvariant-noargs-fail", use_default_args=False)  # No arguments
c.add_compare("--connect %s --os-variant fedora26 --pxe --print-xml" % (utils.URIs.test_suite), "osvariant-defaults-pxe", use_default_args=False)  # No arguments
c.add_valid("--disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init", env={"VIRTINST_TEST_SUITE_CLOUDINIT": "1"})  # default --cloud-init, but without implied --print-xml, to hit some specific code paths
c.add_compare("--connect %(URI-KVM-X86)s --disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init --tpm default", "cloud-init-default", env={"VIRTINST_TEST_SUITE_CLOUDINIT": "1"})  # default --cloud-init behavior is root-password-generate=yes,disable=yes, forcing tpm
c.add_compare("--connect %(URI-KVM-X86)s --disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init root-password-generate=yes,disable=no --sysinfo system.serial=foobar --boot uefi", "cloud-init-options1", env={"VIRTINST_TEST_SUITE_PRINT_CLOUDINIT": "1"})  # --cloud-init root-password-generate, with --sysinfo override, with uefi
c.add_compare("--disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init root-password-file=%(ADMIN-PASSWORD-FILE)s,root-ssh-key=%(XMLDIR)s/cloudinit/ssh-key.txt,clouduser-ssh-key=%(XMLDIR)s/cloudinit/ssh-key2.txt --boot smbios.mode=none", "cloud-init-options2", env={"VIRTINST_TEST_SUITE_PRINT_CLOUDINIT": "1"})  # --cloud-init root-password-file with smbios.mode override
c.add_compare("--disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init ssh-key=%(XMLDIR)s/cloudinit/ssh-key.txt", "cloud-init-options3", env={"VIRTINST_TEST_SUITE_PRINT_CLOUDINIT": "1"})  # --cloud-init ssh-key
c.add_compare("--disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init user-data=%(XMLDIR)s/cloudinit/user-data.txt,meta-data=%(XMLDIR)s/cloudinit/meta-data.txt", "cloud-init-options4", env={"VIRTINST_TEST_SUITE_PRINT_CLOUDINIT": "1"})  # --cloud-init user-data=,meta-data=
c.add_compare("--disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init user-data=%(XMLDIR)s/cloudinit/user-data.txt,meta-data=%(XMLDIR)s/cloudinit/meta-data.txt,network-config=%(XMLDIR)s/cloudinit/network-config.txt", "cloud-init-options5", env={"VIRTINST_TEST_SUITE_PRINT_CLOUDINIT": "1"})  # --cloud-init user-data=,meta-data=,network-config=
c.add_valid("--panic help --disk=? --check=help", grep="path_in_use")  # Make sure introspection doesn't blow up
c.add_valid("--connect test:///default --test-stub-command", use_default_args=False)  # --test-stub-command
c.add_valid("--nodisks --pxe --osinfo generic", grep="VM performance may suffer")  # os variant warning
c.add_valid("--nodisks --pxe", env={"VIRTINSTALL_OSINFO_DISABLE_REQUIRE": "1"}, grep="Skipping fatal error")
c.add_invalid("--hvm --nodisks --pxe foobar", grep="unrecognized arguments: foobar")  # Positional arguments error
c.add_invalid("--nodisks --pxe --name test --osinfo require=no", grep="Guest name 'test' is already")  # Colliding name
c.add_compare("--osinfo generic --cdrom %(EXISTIMG1)s --disk size=1 --disk %(EXISTIMG2)s,device=cdrom", "cdrom-double")  # ensure --disk device=cdrom is ordered after --cdrom, this is important for virtio-win installs with a driver ISO
c.add_valid("--connect %s --pxe --disk size=1 --osinfo generic" % utils.URIs.test_defaultpool_collision)  # testdriver already has a pool using the 'default' path, make sure we don't error
c.add_compare("--connect %(URI-KVM-X86)s --reinstall test-clone-simple --pxe --osinfo generic", "reinstall-pxe")  # compare --reinstall with --pxe
c.add_compare("--connect %(URI-KVM-X86)s --reinstall test-clone-simple --location http://example.com", "reinstall-location")  # compare --reinstall with --location
c.add_compare("--reinstall test-cdrom --cdrom %(ISO-WIN7)s --unattended", "reinstall-cdrom")  # compare --reinstall with --cdrom handling
c.add_invalid("--reinstall test --cdrom %(ISO-WIN7)s", grep="already active")  # trying to reinstall an active VM should fail
c.add_invalid("--reinstall test --osinfo none", grep="install method must be specified")  # missing install method
c.add_valid("--osinfo list", grep="osinfo-query os")  # --osinfo list
c.add_valid(f"--cdrom {MEDIA_DIR}/fake-win-multi.iso --disk none ")  # verify media that matches multi OS doesn't blow up.


####################
# Unattended tests #
####################

c = vinst.add_category("unattended-install", "--connect %(URI-KVM-X86)s --nographics --noautoconsole --disk none", prerun_check=no_osinfo_unattend_cb)
c.add_compare("--install fedora26 --unattended profile=desktop,admin-password-file=%(ADMIN-PASSWORD-FILE)s,user-password-file=%(USER-PASSWORD-FILE)s,product-key=1234,user-login=foobar,reg-login=regtest", "osinfo-url-unattended", prerun_check=lambda: not unattended.OSInstallScript.have_libosinfo_installation_url())  # unattended install for fedora, using initrd injection
c.add_compare("--location %(TREEDIR)s --unattended", "osinfo-unattended-treeapis", prerun_check=lambda: not LIBOSINFO_SUPPORT_LOCAL_TREE)  # unattended install using treeobj libosinfo APIs
c.add_compare("--cdrom %(ISO-WIN7)s --unattended profile=desktop,admin-password-file=%(ADMIN-PASSWORD-FILE)s", "osinfo-win7-unattended", prerun_check=no_osinfo_unattended_win_drivers_cb)  # unattended install for win7
c.add_compare("--os-variant fedora26 --unattended profile=jeos,admin-password-file=%(ADMIN-PASSWORD-FILE)s --location %(ISO-F26-NETINST)s", "osinfo-netinst-unattended", prerun_check=missing_xorriso)  # triggering the special netinst checking code
c.add_compare("--os-variant silverblue29 --location http://example.com", "network-install-resources")  # triggering network-install resources override
c.add_compare("--connect %(URI-TEST-REMOTE)s --os-variant win7 --cdrom %(EXISTIMG1)s --unattended", "unattended-remote-cdrom")
c.add_valid("--pxe --os-variant fedora26 --unattended", grep="Using unattended profile 'desktop'")  # filling in default 'desktop' profile

c.add_invalid("--os-variant fedora26 --unattended profile=jeos --location http://example.foo", grep="admin-password")  # will trigger admin-password required error
c.add_invalid("--os-variant debian9 --unattended profile=desktop,admin-password-file=%(ADMIN-PASSWORD-FILE)s --location http://example.foo", grep="user-password")  # will trigger user-password required error
c.add_invalid("--os-variant debian9 --unattended profile=FRIBBER,admin-password-file=%(ADMIN-PASSWORD-FILE)s --location http://example.foo", grep="Available profiles")  # will trigger unknown profile error
c.add_invalid("--os-variant fedora29 --unattended profile=desktop,admin-password-file=%(ADMIN-PASSWORD-FILE)s --cdrom %(ISO-F29-LIVE)s", grep="media does not support")  # live media doesn't support installscript
c.add_invalid("--os-variant winxp --unattended profile=desktop --cdrom %(ISO-WIN7)s", grep=" OS 'winxp' does not support required injection method 'cdrom'")
c.add_invalid("--install fedora29 --unattended user-login=root", grep="as user-login")  # will trigger an invalid user-login error


#############################
# Remote URI specific tests #
#############################

c = vinst.add_category("remote", "--connect %(URI-TEST-REMOTE)s --nographics --noautoconsole --osinfo generic")
c.add_valid("--nodisks --pxe")  # Simple pxe nodisks
c.add_valid("--cdrom %(EXISTIMG1)s --disk none --livecd --dry")  # remote cdrom install
c.add_compare("--pxe "
"--pxe --disk /foo/bar/baz,size=.01 "  # Creating any random path on the remote host
"--disk /dev/zde ", "remote-storage")  # /dev file that we just pass through to the remote VM
c.add_invalid("--nodisks --location /tmp", grep="Cannot access install tree on remote connection: /tmp")
c.add_invalid("--file /foo/bar/baz --pxe", grep="Size must be specified for non existent volume 'baz'")



###########################
# QEMU/KVM specific tests #
###########################

c = vinst.add_category("kvm-generic", "--connect %(URI-KVM-X86)s --autoconsole none")
c.add_compare("--os-variant fedora-unknown --file %(EXISTIMG1)s --location %(TREEDIR)s --extra-args console=ttyS0 --cpu host --channel none --console none --sound none --redirdev none --boot cmdline='foo bar baz'", "kvm-fedoralatest-url", prerun_check=has_old_osinfo)  # Fedora Directory tree URL install with extra-args
c.add_compare("--test-media-detection %(TREEDIR)s --arch x86_64 --hvm", "test-url-detection")  # --test-media-detection
c.add_compare("--os-variant http://fedoraproject.org/fedora/20 --disk %(EXISTIMG1)s,device=floppy --disk %(NEWIMG1)s,size=.01,format=vmdk --location %(TREEDIR)s --extra-args console=ttyS0 --quiet", "quiet-url", prerun_check=has_old_osinfo)  # Quiet URL install should make no noise
c.add_compare("--cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --sound --controller usb", "kvm-win2k3-cdrom")  # HVM windows install with disk
c.add_compare("--os-variant name=ubuntusaucy --nodisks --boot cdrom --virt-type qemu --cpu Penryn --input tablet --boot uefi --graphics vnc", "qemu-plain")  # plain qemu
c.add_compare("--os-variant fedora20 --nodisks --boot network --graphics default --arch i686 --rng none", "qemu-32-on-64", prerun_check=has_old_osinfo)  # 32 on 64
c.add_compare("--osinfo linux2020 --pxe", "linux2020", prerun_check=no_osinfo_linux2020_virtio)
c.add_compare("--check disk_size=off --osinfo win11 --cdrom %(EXISTIMG1)s", "win11", prerun_check=no_osinfo_win11)
c.add_compare("--check disk_size=off --osinfo win11 --cdrom %(EXISTIMG1)s --boot uefi=off", "win11-no-uefi")
c.add_compare("--osinfo generic --disk none --location %(ISO-NO-OS)s,kernel=frib.img,initrd=/frob.img", "location-manual-kernel", prerun_check=missing_xorriso)  # --location with an unknown ISO but manually specified kernel paths
c.add_compare("--disk %(EXISTIMG1)s --location %(ISOTREE)s --nonetworks", "location-iso", prerun_check=missing_xorriso)  # Using --location iso mounting
c.add_compare("--disk %(EXISTIMG1)s --location %(ISOTREE)s --nonetworks --cloud-init user-data=%(XMLDIR)s/cloudinit/user-data.txt,meta-data=%(XMLDIR)s/cloudinit/meta-data.txt", "location-iso-and-cloud-init", prerun_check=missing_xorriso)  # Using --location iso mounting and --cloud-init at the same time
c.add_compare("--disk %(EXISTIMG1)s --cdrom %(ISOLABEL)s", "cdrom-centos-label")  # Using --cdrom with centos CD label, should use virtio etc.
c.add_compare("--disk %(EXISTIMG1)s --install bootdev=network --os-variant rhel5.4 --cloud-init none", "kvm-rhel5")  # RHEL5 defaults
c.add_compare("--disk %(EXISTIMG1)s --install kernel=%(ISO-WIN7)s,initrd=%(ISOLABEL)s,kernel_args='foo bar' --os-variant rhel6.4 --unattended none", "kvm-rhel6")  # RHEL6 defaults. ISO paths are just to point at existing files
c.add_compare("--disk %(EXISTIMG1)s --location https://example.com --install kernel_args='test overwrite',kernel_args_overwrite=yes --os-variant rhel7.0", "kvm-rhel7", precompare_check=no_osinfo_unattend_cb)  # RHEL7 defaults
c.add_compare("--connect " + utils.URIs.kvm_x86_nodomcaps + " --disk %(EXISTIMG1)s --pxe --os-variant rhel7.0", "kvm-cpu-default-fallback", prerun_check=has_old_osinfo)  # No domcaps, so mode=host-model isn't safe, so we fallback to host-model-only
c.add_compare("--connect " + utils.URIs.kvm_x86_cpu_insecure + " --disk %(EXISTIMG1)s --pxe --os-variant rhel7.0", "kvm-cpu-hostmodel-fallback", prerun_check=has_old_osinfo)  # domcaps too old for default host-passthrough, falls back to host-model
c.add_compare("--disk %(EXISTIMG1)s --pxe --os-variant centos7.0 --controller num_pcie_root_ports=0", "kvm-centos7", prerun_check=has_old_osinfo)  # Centos 7 defaults
c.add_compare("--disk %(EXISTIMG1)s --cdrom %(EXISTIMG2)s --os-variant win10 --controller num_pcie_root_ports=2", "kvm-win10", prerun_check=has_old_osinfo)  # win10 defaults
c.add_compare("--os-variant win7 --cdrom %(EXISTIMG2)s --boot loader_type=pflash,loader=CODE.fd,nvram_template=VARS.fd --disk %(EXISTIMG1)s", "win7-uefi", prerun_check=has_old_osinfo)  # no HYPER-V with UEFI
c.add_compare("--osinfo generic --arch i686 --boot uefi --install kernel=http://example.com/httpkernel,initrd=ftp://example.com/ftpinitrd --disk none", "kvm-i686-uefi")  # i686 uefi. piggy back it for --install testing too
c.add_compare("--osinfo generic --machine q35 --cdrom %(EXISTIMG2)s --disk %(EXISTIMG1)s", "q35-defaults")  # proper q35 disk defaults
c.add_compare("--disk size=1 --os-variant openbsd4.9", "openbsd-defaults")  # triggers net fallback scenario
c.add_compare("--connect " + utils.URIs.kvm_x86_remote + " --import --disk %(EXISTIMG1)s --os-variant fedora21 --pm suspend_to_disk=yes", "f21-kvm-remote", prerun_check=has_old_osinfo)
c.add_compare("--connect %(URI-KVM-X86)s --os-variant fedora26 --graphics spice --controller usb,model=none", "graphics-usb-disable")
c.add_compare("--osinfo generic --boot uefi --disk size=1", "boot-uefi")
c.add_compare("--osinfo generic --boot uefi --disk size=1 --tpm none --connect " + utils.URIs.kvm_x86_oldfirmware, "boot-uefi-oldcaps")
c.add_compare("--osinfo linux2020 --boot uefi=on --launchSecurity sev --connect " + utils.URIs.kvm_amd_sev, "amd-sev", prerun_check=no_osinfo_linux2020_virtio)

c.add_invalid("--disk none --location nfs:example.com/fake --nonetworks", grep="NFS URL installs are no longer supported")
c.add_invalid("--disk none --boot network --machine foobar", grep="domain type None with machine 'foobar'")
c.add_invalid("--nodisks --boot network --arch mips --virt-type kvm", grep="any virtualization options for architecture 'mips'")
c.add_invalid("--nodisks --boot network --paravirt --arch mips", grep=" 'xen' for architecture 'mips'")
c.add_invalid("--osinfo generic --launchSecurity sev --connect " + utils.URIs.kvm_amd_sev, grep="SEV launch security requires a Q35 UEFI machine")
c.add_invalid("--disk none --cloud-init --unattended --install fedora30", grep="Cannot use --unattended and --cloud-init at the same time")



#########################
# qemu:///session tests #
#########################

c.add_compare("--connect " + utils.URIs.kvm_x86_session + " --disk size=8 --os-variant fedora21 --cdrom %(EXISTIMG1)s", "kvm-session-defaults", prerun_check=has_old_osinfo)
c.add_valid("--connect " + utils.URIs.kvm_x86_session + " --install fedora21", prerun_check=has_old_osinfo)  # hits some get_search_paths and media_upload code paths




###############
# ppc64 tests #
###############

c.add_compare("--machine pseries --boot arch=ppc64,network --disk %(EXISTIMG1)s --disk device=cdrom --os-variant fedora20 --network none", "ppc64-pseries-f20")
c.add_compare("--arch ppc64 --boot network --disk %(EXISTIMG1)s --os-variant fedora20 --network none --graphics vnc", "ppc64-machdefault-f20")
c.add_compare("--connect %(URI-KVM-PPC64LE)s --import --disk %(EXISTIMG1)s --os-variant fedora20 --panic default --tpm default --graphics none", "ppc64le-kvm-import")




###############
# s390x tests #
###############

c.add_compare("--arch s390x --machine s390-ccw-virtio --connect %(URI-KVM-S390X)s --boot kernel=/kernel.img,initrd=/initrd.img --disk %(EXISTIMG1)s --disk %(EXISTIMG3)s,device=cdrom --os-variant fedora30 --panic default --graphics vnc", "s390x-cdrom", prerun_check=has_old_osinfo)
c.add_compare("--connect %(URI-KVM-S390X)s --arch s390x --nographics --import --disk %(EXISTIMG1)s --os-variant fedora30", "s390x-headless")
c.add_compare("--connect %(URI-KVM-S390X)s --arch s390x --import --disk none --osinfo fedora30", "s390x-default")



###############
# riscv tests #
###############

c.add_compare("--connect %(URI-QEMU-RISCV64)s --arch riscv64 --osinfo fedora29 --import --disk %(EXISTIMG1)s --network default --graphics none", "riscv64-headless")
c.add_compare("--connect %(URI-QEMU-RISCV64)s --arch riscv64 --osinfo fedora29 --import --disk %(EXISTIMG1)s --network default --graphics spice", "riscv64-graphics")
c.add_compare("--connect %(URI-QEMU-RISCV64)s --arch riscv64 --osinfo fedora29 --import --disk %(EXISTIMG1)s --boot kernel=/kernel.img,initrd=/initrd.img,cmdline='root=/dev/vda2'", "riscv64-kernel-boot")
c.add_compare("--connect %(URI-QEMU-RISCV64)s --arch riscv64 --osinfo fedora29 --import --disk %(EXISTIMG1)s --cloud-init", "riscv64-cloud-init")
c.add_compare("--connect %(URI-QEMU-RISCV64)s --arch riscv64 --osinfo fedora29 --cdrom %(ISO-F26-NETINST)s", "riscv64-cdrom")
c.add_compare("--connect %(URI-QEMU-RISCV64)s --arch riscv64 --osinfo fedora29 --unattended", "riscv64-unattended")



################
# armv7l tests #
################

c.add_compare("--arch armv7l --osinfo generic --machine vexpress-a9 --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,dtb=/f19-arm.dtb,extra_args=\"console=ttyAMA0 rw root=/dev/mmcblk0p3\" --disk %(EXISTIMG1)s --nographics", "arm-vexpress-plain")
c.add_compare("--arch armv7l --machine virt --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\" --disk %(EXISTIMG1)s --graphics vnc --os-variant fedora20", "arm-virt-f20")
c.add_compare("--arch armv7l --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\",extra_args=foo --disk %(EXISTIMG1)s --os-variant fedora20", "arm-defaultmach-f20")
c.add_compare("--connect %(URI-KVM-ARMV7L)s --disk %(EXISTIMG1)s --import --os-variant fedora20", "arm-kvm-import")



#################
# aarch64 tests #
#################

c.add_valid("--arch aarch64 --osinfo fedora19 --nodisks --pxe --connect " + utils.URIs.kvm_x86_nodomcaps, grep="Libvirt version does not support UEFI")  # attempt to default to aarch64 UEFI, but it fails, but should only print warnings
c.add_invalid("--arch aarch64 --nodisks --pxe --connect " + utils.URIs.kvm_x86, grep="OS name is required")  # catch missing osinfo for non-x86
c.add_compare("--arch aarch64 --osinfo fedora19 --machine virt --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\" --disk %(EXISTIMG1)s", "aarch64-machvirt")
c.add_compare("--arch aarch64 --osinfo fedora19 --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,kernel_args=\"console=ttyAMA0,1234 rw root=/dev/vda3\" --disk %(EXISTIMG1)s", "aarch64-machdefault")
c.add_compare("--arch aarch64 --cdrom %(ISO-F26-NETINST)s --boot loader=CODE.fd,nvram.template=VARS.fd --disk %(EXISTIMG1)s --cpu none --events on_crash=preserve,on_reboot=destroy,on_poweroff=restart", "aarch64-cdrom")  # cdrom test, but also --cpu none override, --events override, and headless
c.add_compare("--connect %(URI-KVM-AARCH64)s --disk %(EXISTIMG1)s --import --os-variant fedora21 --panic default --graphics vnc", "aarch64-kvm-import")  # --import test, but also test --panic no-op, and --graphics
c.add_compare("--connect %(URI-KVM-AARCH64)s --disk size=1 --os-variant fedora22 --features gic_version=host --network network=default,address.type=pci --controller type=scsi,model=virtio-scsi,address.type=pci", "aarch64-kvm-gic")
c.add_compare("--connect %(URI-KVM-AARCH64)s --osinfo fedora30 --arch aarch64 --disk none --pxe --boot firmware=efi", "aarch64-firmware-no-override")
c.add_compare("--connect %(URI-KVM-AARCH64)s --disk %(EXISTIMG1)s --os-variant fedora28 --cloud-init", "aarch64-cloud-init")



#####################
# loongarch64 tests #
#####################

c.add_compare("--connect %(URI-KVM-LOONGARCH64)s --arch loongarch64 --osinfo fedora29 --import --disk %(EXISTIMG1)s --network default --graphics none", "loongarch64-headless")
c.add_compare("--connect %(URI-KVM-LOONGARCH64)s --arch loongarch64 --osinfo fedora29 --import --disk %(EXISTIMG1)s --network default --graphics spice", "loongarch64-graphics")
c.add_compare("--connect %(URI-KVM-LOONGARCH64)s --arch loongarch64 --osinfo fedora29 --import --disk %(EXISTIMG1)s --boot kernel=/kernel.img,initrd=/initrd.img,cmdline='root=/dev/vda2'", "loongarch64-kernel-boot")
c.add_compare("--connect %(URI-KVM-LOONGARCH64)s --arch loongarch64 --osinfo fedora29 --import --disk %(EXISTIMG1)s --cloud-init", "loongarch64-cloud-init")
c.add_compare("--connect %(URI-KVM-LOONGARCH64)s --arch loongarch64 --osinfo fedora29 --cdrom %(ISO-F26-NETINST)s", "loongarch64-cdrom")
c.add_compare("--connect %(URI-KVM-LOONGARCH64)s --arch loongarch64 --osinfo fedora29 --unattended", "loongarch64-unattended")



#############################
# x86 Launch security tests #
#############################

c = vinst.add_category("kvm-x86_64-launch-security", "--disk none --noautoconsole --osinfo generic --connect %(URI-KVM-X86)s")
c.add_compare("--boot uefi --machine q35 --launchSecurity type=sev-snp,policy=0x24", "x86_64-launch-security-sev-snp", prerun_check="10.5.0")
c.add_compare("--boot uefi --machine q35 --launchSecurity type=sev-snp,vcek=on,kernelHashes=on,authorKey=on,idBlock=Tm93IHN0YW5kIGFzaWRlLCB3b3J0aHkgYWR2ZXJzYXJ5IU5vdyBzdGFuZCBhc2lkZSwgd29ydGh5IGFkdmVyc2FyeSFOb3cgc3RhbmQgYXNpZGUsIHdvcnRoeSBhZHZl,hostData=V2UgYXJlIHRoZSBLbmlnaHRzIHdobyBzYXkgbmkhISE=,policy=0x24,guestVisibleWorkarounds=V2UgYXJlIHRoZSBLbmlnaA==,idAuth=WqQal12JgC5d14GG1/KEoI/fmZworLx889hoh+uB4fV3t+OPl8ShZgTmEW/U1U6eLjy0h9runhhUTqiB5X9I2BNaVneOCyPwkFDJu6ZavwDsBB6irYE4+Z07y7XulR7DikP9nHiybTU4mey0s4MNTlTSdk2AYq4QOdvQmjU8W3PITSVwjoW/kMIfgGj03uUGT//VMx9DuWNLH0OefR/1gTL0G8eoVUKEN3+6NaU0Nh26wOylf3/7UBB3BexTplgeIzZ3lwAASANmEVEiBrnkZzNo3jABEDxLzS3qMwXZT46ke18S6oIGIsJww7eAdTuwEhp1P+ulCuJw6ub6oThxWKfm1s4edHYznRTTPuxzExatmjo4XqQc3Y95bF3NDG0i0gL3IVl+M3UWxtPxeVap7mvYbFt5FFIrr7pYpvuYj3GIctz6LwTaCz90cCDS4Gi76vp7P2elDPpj9uSLv93RLDTo+nDbmlgjJxdjru5SfDI6NCu2Y2JLjELAC9Q/htSohNSuh1GXVwD5tWauiyryvrN2llUxsB/4zW6qJMD/1GPSOiJ1Zwpi0xWx7LsEaLMFZoVXDIsQPrGhC44chrKbIsKU+g+pnCMz22DmeNaVx2uHiCa/Y12T+bdX6g7x6SIpYFLE3nVTSChx9MxWaqjS05/g8oiMJWnc+DaG/X8JwGEZgCOoYjuCJddtr/E79L1D2zDL5hJzVKRB6tJAusDzQOfixO1bIaPCUCD+qWTowGASZtY8U+8BRmQIfydPE4DG/q6nQoO4BHV7u6wwvx0Q6OFEF8FJmZFaQCvRtNRMTHhIR9H2usKYWI4mlVx2cHo6xNs3/PSbjfDIApqIInzZ/kirCiFiMoP3oq6MUydsRCW/IHagj5srnTKTFCQIvlPBWZofJYK9xG0rap1Q9uSkzjeTrfYbYvNQJrDLgIB+C4O8jzp8YZwwQz35ANhfJXxuOwp5900Wd+1ezsYUjglJUwZJX/SVguKGdjkPGuz/RWt3mzZ4FQ+o8hRRRyTMmdjh0HHVndtwTiS2coZwJ2lfLZ2pj3R1SFrTKShPludHPp0nwKLvJ6Um7GvFGAGjXOPXDzpXTzIb6aQ7ZN0SQI1dwzZJHDBwfODaufiHwWguo6ZXpUK7uxYLIY3ukHpmORHeJ+dlA/GsA/igMT1IpD1y4e89njgbql3IeYO4OoQQyROgpKZv8IYK+OS1OxsnJv5n23VDThVNgmPUOmXHhc7F2uP0I5rwtRgfH+Of9ekdnlKQBrxPzDi1GfRobOvnTBVA8TDCzMcLG3vMj8mUndU7ef9ZAASPSoMJ2hbNpipvcwmOHoz0CwfknDE7OzUMCQqqgt4ZnGuJzTkzOypb8qnCbu60+zlnv+vRfNqrEo2a3GGiFQ/mnOqEetSOVmUNeur89tkKVmkXhEWEDDD3EbuyrHfuOntPq46IOzmTIBH7qWJ8VeX6M9bsCZ4iYP8K7BGSG0yGKvp1rssrJ2K+a3a+SAZPZ+0ComJ8ZQ9McB++aQfI+P/+cM4TkZRh8MG6uylaU5VGEjNspcImsP5yLQO4xatDQArk8gkcRyVAsffZkVdGdnc7JxKyJsJvVNKp4PB8c3E5rU4wvx4oqjN/Fvw+fMvpKZVRp5sAvP1KIOowa8WDKgoZG4RWw8ubwW2HD99WYabt9H/V5ZnLGADXvEw8GuzeWoqaNF6YVSGTq7/GS42HNZnZZjpPz+Z15xySp2jxBgvYTF2kXEzozH1gecvNywILaxvdcu+8u6TpPo0o/hCG40OcAbzq2gzB9AAlUyrs0RHz3OleU1y6MXQohkFemTHrKUxRlhIdZnBZ3SGlcV0XieGChZH6FIRB5sTSwLLLm55B7vJcJZEG3wwj62zKilNmPivLUafl9A1BIcLap6cu+ZgU4iWnKwbGwJlrQ/jmQ6TZm+z+eHNYM+XEnI6/1jN5LWOqFN91YRe3DIgdmiQxo5/4s+jfRTFh4PRhDP7U3W8cCh6MQSmIMHo/+NfNlFGaMlUbAZPUOYRe99yCvyrqTPx0tZask9P5to9mVseHaBOLMXsgqECUKcHrfIDaHwR42Zq6EGWgC71EpkEwVRZZs18NMiDaZ55xmu17wurX8WqowhEH3HCXm8kfcWD+qFvjzinCMa9/9U8IsBUGL25iQ/iRZ/SegWkB2udULYFpaLeO0BanZIvGHT8dQbHDlqFxa6sEES6L5XxksD5xd187o37mlKtFPHd0xD+jyEIARscRlbpadDPPrPwryLB6q1WlG3s59ocAXuguCupt7WRgz11hJzolbckkOgTnLjdnOlc2qPAoDSbU1oMgLQgAQWO+iVdBliiNX6Gne4oslvLLIOS0X7D7QV8/KhRf1R0fg/uzcUsbLWPPfRY3jhyIkDHw005pVsfs8DWggNyQ2OHKQtoI0CVqevI4HQJFwZR0MTzKkM/rYkdBRDt0Zr0a9A0CjN7wF6zsebPKmEZb68MMj+FAVC7ZhXHIMnU2VvoYww0Gbn/4eFTMbKbmSL6bTKvZghq+y6jxKJkPSaQi9T0jMsxZ5FjICMg3ZfFDsqmLneMUdRyo1M9s4d3/WJhsyw8I/0nxadGXDZLiVt3jyVzPZ9m477WnOfp8bsgLnkiDQGGopEedcLS6rr5wgkyxBkjgH7bvaOLDp7FuZJ0HB2goG0xMkamm+rELKy9hnB8836iOLRq7lSAJMLVBqYw52Bfjrk7+1fjmMP+7F0Tslt3gWN2aQyN6dNtEGz14kzPleWxUdoTuv2gC2+nPN5O/kK7XHdAL8/vcmHmt50EUTXZXwvzz209Z6WzGvLqTTtPUMYvl2oyMJmVcdQfUrupeN+bOX772ZngCs4ugGYGK3Z4enFSpgCdC7mNNIvq8iKbunGyztJkxBcHQ5h8men8ddb7FMhByA1N+RZCOKxiK7DN4XrdRa2eIRfAD9/Ait9SsNplJs/c3rYGqLmFyCAQN7ngn4HutsXOcNVSqyRVv9pOnyHPHCo+MLFbIwn4xmXAPYcPnBvvdHU+opicWxFwCZNWuJYUjiNj9R4WceVaO+7DaYuN7hJM46Tc7GP3OwXoQPuHMDX64i1j8eFjUPEStjfGAEBBWYlTWFEla6/7lXJ3EPzz92iS/xMZFsmV1BKOL6RnxgzPGSbaMtsKIM0m8p+qBRJmIOTF3J1N9rRMUh3DJsLBkHWim30mMLY6xub0Su0+dUk2vS0fxrHTvU8lTPYfkB8WOj8fCyYFuWavZ8G6uzQZY4maSgIs79YwBz2juNkEx7Zhtq2864m1xIQcuHRsWhk6+mueei4de/xH3K71WBC0za4zjXe9gu9V22Ruz/vzTGu8VVGbqXMsSRx5A4dioXKCeyi3XRZORyMlhWTp3/nLZI2S9N76BiZbpMUU4aiL8/ROtnSJOwY/QRgCfljfytypND+OuLazrsDJLsLlrG4Q/74URtQOCnzEd214uSGXWeGC5u4iqKt0eDygz59BH+MHH3e4JczFTu5GazI6nQvS0jHRkSYMNCnnJPO1BvTVWVkfjoWfJPEmBTXZBEsl+homiRCy4RJ+W2E9mDT5yI/fIKD7acokiihhEx4n86fLtvIkswPvMggPCQ7zhV9/GiNwLekDZJMiQgzfXFYWAvJgOKLJafgHy1z8wwMC0b5gfQzduT8tTlSCgP6PaUPwm9+iyEGCCO1CiQ1u9PbQ2k1rOdgQkCQ+A0TMn4Pk8J3cVCf0ZbHcAQzkk/fqnAHO7ggpuB+Fq2sm8alz7S/AdaTnc25GCw8pMq4mkgqzABC4CgnZrz/oMbV7zUUcDMPEpLkPKLTaj83Z3k83Hjk85xfUygCca0ujFO0Y5zXk9yj1WpZPRLfnO/ais+gz8sghE71kXDupW0VvwaG7qgq20Yyfj1ylZsdyEsHEyem2gGyWhFGkhlue0C8Eo8BHkJxew4LLIdfHCVUeZ9JCu/AjGFsIZUHzMQ3iZ+sleb1R/cqRl/btYUDI63NnCDtp4BMImvs6cP5plpkblLBWjok8SHh7AGyXU+MsRC2YyJeIDiTBAd+tIOMU9s/X4Ede7qxarBz3t1ZbxV/+UU3ncWXk07DA5yCxLq1WwDH7sp81vkkURScwLBtkwEhY2ANGF6DEG20HJN4R+o68C3+jhkjSTxCbV2z1HqbkvXMWEUxWdx8ECU6KD6QVG4e+WxJt+HWm8c/nKfScvU66jREny+96r/tai2DGyuwbHcREjBMErvpBaXmm+HHZZ5sKSzKvoZzXddda2lw5rkpGxJMcCXqwfkUmGDYhkETNafut/1VNXzEzJklS1Nzd55FJVT2UBZxXHtR+gEEbCTkw8RPgRzcynsjy4vOCKVBYrIXtBRrwBXo1yjZ0DosnnakBHRSmGVG1tSSppUU5b9TOJgQR2h9HMRlFSRbVNEItm91j0EQLoOCXzBEsAVJdwig75HIEHuIZimGbyOBTWasbmJPQtfx1+ElN5yBbe+wMprubuXe76IkhaUDO0wMLeQmfOnLOpkJeC8rA0Qm6f6wW/kPWkb+r1+2TDeEflwRHNspV2LwGpX5ctU5ruU7bcM82eatMqfkL7e4tnvjYmYJHxo8RHDICOxUqrSdZJZ/SpSEY66IXXs75sjYPGH/R1av+KzX71EhDpt+vEr3aOXd66uZ5NwWJIOC7A7mUDV7ObkpgtWiHxwMbpI2fllWsha+rLNJR5EwXWlItHJL6B7oBeUsJs62v6ZLHeJN81DHaOJOGvBR+Mv/V+tqrItLAtPfPrthwWvK96KDHsMKdlx0423FuPEf7AiYkupYi1GyoKQvMDNE5bQFrsDtaKbYCJKfoJJxdyVdZmDbtNnUpAvWwbj7gmfZ85QB0aPUzftWdSLNLL+xshCfQlO6ROril3Ir/7ITXE/1LKRS9719Fl6keYRVdExNiDotimnYWiVPZ20wDiWlmslOY8luWiXnWTm0xIvzbS16s7B8BpNZgbZ5BUX+eai7mmdvALDfPGtXIYtk4sPR54kvLyamIY5ZtshvW6gO57lpg5QM5TPyoAq2okufwC4IqAscnOoARO1aKxKGA9h+1DdV0eYIXqRCoW2mPRgYNBeimgbvAWu+bGJoCkF1U6+1psHFDd5fpsQPpft+WWxPMdffEP4yaQoXRFadjEL5Cq7Ib0ZFoj9d6a5UV35wo3SxnyWEsVb0hOGM2R/Fr4spYp3ms67XXZOvKvn3oOCOFx/8ySX1ErvpMqISioQgMK+PB4qqrISAOop0jGvUlxBZwN+meSXnA7CGG1ZzudB5pHx1za+vyb+U971iozFQ0/0CTe3hggNXo6OfBT+aaz8xsmV3TaJW83+Lvhn0XWuWt0Ztn59WTqyyqDeRFP07Z4awbaOzChJIMJTeretlit6azPH0f7K5CXdy60hQksJAgpTyAix2VBD7rcna4p5xvrxqbakUh//WLGegceJnpA9p3OuF7PUrrd54vuA7mad6fKBw==", "x86_64-launch-security-sev-snp-full", prerun_check="10.5.0")
c.add_invalid("--machine pc --launchSecurity type=sev-snp,policy=0x24", grep="SEV-SNP launch security requires a Q35 UEFI machine", prerun_check="10.5.0")


######################
# LXC specific tests #
######################

c = vinst.add_category("lxc", "--name foolxc --noautoconsole --connect " + utils.URIs.lxc)
c.add_invalid("--filesystem /,not/abs", grep="must be an absolute path")
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
c.add_compare("--disk %(EXISTIMG1)s --machine xenpvh --boot os_type=xenpvh --import", "xenpvh")  # Xen default
c.add_compare("--disk %(EXISTIMG1)s --location %(TREEDIR)s --paravirt --controller xenbus,maxGrantFrames=64 --input default", "xen-pv", precompare_check="5.3.0")  # Xen PV
c.add_compare("--osinfo generic --disk  /pool-iscsi/diskvol1 --cdrom %(EXISTIMG1)s --livecd --hvm", "xen-hvm")  # Xen HVM
c.add_compare("--osinfo generic --disk  /pool-iscsi/diskvol1 --cdrom %(EXISTIMG1)s --install no_install=yes --hvm", "xen-hvm")  # Ensure --livecd and --install no_install are essentially identical



#####################
# VZ specific tests #
#####################

c = vinst.add_category("vz", "--noautoconsole --connect " + utils.URIs.vz)
c.add_valid("--container")  # validate the special define+start logic
c.add_valid("--osinfo generic --hvm --cdrom %(EXISTIMG1)s --disk none")  # hit more install vz logic
c.add_valid("--osinfo generic --hvm --import --disk %(EXISTIMG1)s --noreboot")  # hit more install vz logic
c.add_invalid("--container --transient", grep="Domain type 'vz' doesn't support transient installs.")
c.add_compare("""
--container
--filesystem type=template,source=centos-7-x86_64,target="/"
--network network="Bridged"
""", "vz-ct-template")



########################
# bhyve specific tests #
########################

c = vinst.add_category("bhyve", "--name foobhyve --noautoconsole --connect " + utils.URIs.bhyve)
c.add_compare("--osinfo generic --boot uefi --disk none --ram 256 --pxe", "bhyve-uefi")
c.add_compare("--os-variant fedora27", "bhyve-default-f27")



###########################
# qemu hvf specific tests #
###########################

c = vinst.add_category("bhyve", "--name foohvf --noautoconsole --connect " + utils.URIs.hvf_x86)
c.add_compare("--os-variant fedora27", "hvf-default-f27")



#####################################
# Device option back compat testing #
#####################################

c = vinst.add_category("device-back-compat", "--nodisks --pxe --noautoconsole --paravirt")
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
c.add_invalid("--mac 22:11:11:11:11:11", grep="in use by another virtual machine")  # Colliding macaddr will error
c.add_invalid("--graphics vnc --vnclisten 1.2.3.4", grep="Cannot mix --graphics and old style graphical options")
c.add_invalid("--network user --bridge foo0", grep="Cannot use --bridge and --network at the same time")

c = vinst.add_category("storage-back-compat", "--pxe --noautoconsole --osinfo generic")
c.add_valid("--file %(EXISTIMG1)s --nonsparse --file-size 4")  # Existing file, other opts
c.add_valid("--file %(EXISTIMG1)s")  # Existing file, no opts
c.add_valid("--file %(EXISTIMG1)s --file %(EXISTIMG1)s")  # Multiple existing files
c.add_valid("--file %(NEWIMG1)s --file-size .00001 --nonsparse")  # Nonexistent file


c = vinst.add_category("console-tests", "--nodisks --os-variant generic")
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
c.add_valid("--pxe", grep="User stopped the VM", env={"VIRTINST_TESTSUITE_HACK_DESTROY": "1"})  # fake the user destroying the VM, we should print a specific message and not reboot the VM
c.add_valid("--connect %(URI-KVM-X86)s --install fedora28 --cloud-init", grep="Password for first root login")  # make sure we print the root login password
c.add_invalid("--pxe --autoconsole badval", grep="Unknown autoconsole type 'badval'")
c.add_invalid("--pxe --autoconsole text --wait -1", grep="exceeded specified time limit")  # hits a specific code path where we skip console waitpid

c = vinst.add_category("hyperv", "--disk none --osinfo win11 --import")
c.add_compare("--connect %(URI-KVM-X86)s --features hyperv.vpindex.state=off", "hyperv_disable_vpindex")  # disable feature that is required by others to test they are not enabled by default
c.add_compare("--connect %(URI-KVM-X86-NODOMCAPS)s", "hyperv_no_domcaps")  # don't use domain capabilities to enable only some features by version check


##################
# virt-xml tests #
##################

_VIRTXMLDIR = XMLDIR + "/virtxml/"

vixml = App("virt-xml")
c = vixml.add_category("misc", "")
c.add_valid("--help")  # basic --help test
c.add_valid("--sound=? --tpm=?")  # basic introspection test
c.add_valid("--os-variant list", grep="ubuntu10.10, ubuntumaverick")
c.add_valid("test-state-shutoff --edit --update --boot menu=on", grep="The VM is not running")  # --update with inactive VM, should work but warn
c.add_valid("test-state-shutoff --edit --boot menu=on", grep="XML did not change after domain define")  # menu=on is discarded because <bootloader> is specified
c.add_valid("test-for-virtxml --edit --graphics password=foo --update --confirm", input_text="no\nno\n")  # prompt exiting
c.add_valid("test-for-virtxml --edit --cpu host-passthrough --no-define --start --confirm", input_text="no")  # transient prompt exiting
c.add_valid("test-for-virtxml --edit --metadata name=test-for-virtxml", grep="requested changes will have no effect")
c.add_valid("--print-diff test-for-virtxml --remove-device --disk boot.order=5", grep="boot order=\"5")
c.add_invalid("test --edit 2 --events on_poweroff=destroy", grep="'--edit 2' doesn't make sense with --events")
c.add_invalid("test --os-variant fedora26 --edit --cpu host-passthrough", grep="--os-variant/--osinfo is not supported")
c.add_invalid("test-for-virtxml --os-variant fedora26 --remove-device --disk 1", grep="--os-variant/--osinfo is not supported")
c.add_invalid("--build-xml --os-variant fedora26 --disk path=foo", grep="--os-variant/--osinfo is not supported")
c.add_invalid("domain-idontexist --edit --cpu host-passthrough --start", grep="Could not find domain")
c.add_invalid("test-state-shutoff --edit --update --boot menu=on --start", grep="Cannot use --update")
c.add_invalid("test --edit --update --events on_poweroff=destroy", grep="Don't know how to --update for --events")
c.add_invalid("--edit --cpu host-passthrough --confirm", input_file=(_VIRTXMLDIR + "virtxml-stdin-edit.xml"), grep="Can't use --confirm with stdin")
c.add_invalid("--edit --cpu host-passthrough --update", input_file=(_VIRTXMLDIR + "virtxml-stdin-edit.xml"), grep="Can't use --update with stdin")
c.add_invalid("--edit --cpu host-passthrough", grep="A domain must be specified")
c.add_invalid("test-state-shutoff --cpu mode=idontexist --start --edit --no-define --confirm", grep="Failed starting domain 'test-state-shutoff'", input_text="yes")
c.add_invalid("test --cpu host-passthrough", grep="One of --edit, ")  # conflicting --edit options
c.add_invalid("test --edit --add-device --disk path=foo", grep="Conflicting options --edit, --add-device")
c.add_invalid("test --edit 0 --disk path=", grep="Invalid --edit option '0'")
c.add_invalid("test --edit --hostdev driver_name=vfio", grep='No --hostdev objects found in the XML')
c.add_invalid("test --edit --cpu host-passthrough --boot hd,network", grep="Only one change operation may be specified")
c.add_invalid("test --edit", grep="No change specified.")
c.add_invalid("test --edit 2 --cpu host-passthrough", grep="'--edit 2' requested but there's only 1 --cpu object in the XML")
c.add_invalid("test-for-virtxml --edit 5 --tpm /dev/tpm", grep="'--edit 5' requested but there's only 1 --tpm object in the XML")
c.add_invalid("test-for-virtxml --add-device --host-device 0x04b3:0x4485 --update --confirm", input_text="yes", grep="not supported")
c.add_invalid("test-for-virtxml --remove-device --host-device 1 --update --confirm", input_text="foo\nyes\n", grep="not supported by the connection driver: virDomainDetachDevice")
c.add_invalid("test-for-virtxml --edit --graphics password=foo,keymap= --update --confirm", input_text="yes", grep="(not supported by the connection driver: virDomainUpdateDeviceFlags|persistent update of device 'graphics' is not supported)")
c.add_invalid("--build-xml --memory 10,maxmemory=20", grep="--build-xml not supported for --memory")
c.add_invalid("test-state-shutoff --edit sparse=no --disk path=blah", grep="Don't know how to match device type 'disk' property 'sparse'")
c.add_invalid("test --add-device --xml ./@foo=bar", grep="Cannot use --add-device with --xml")
c.add_invalid("test-for-virtxml --edit --boot refresh-machine-type=yes", grep="Don't know how to refresh")
c.add_compare("test --print-xml --edit --vcpus 7", "print-xml")  # test --print-xml
c.add_compare("--edit --cpu host-passthrough", "stdin-edit", input_file=(_VIRTXMLDIR + "virtxml-stdin-edit.xml"))  # stdin test
c.add_compare("--connect %(URI-KVM-X86)s --edit --print-diff --define --boot refresh-machine-type=yes", "refresh-machine-type", input_file=(_VIRTXMLDIR + "virtxml-refresh-machine-in.xml"))  # refresh-machine-type test. we need to use stdin XML since we can't get the libvirt testdriver to start with the machine XML we need
c.add_compare("--build-xml --cpu pentium3,+x2apic", "build-cpu")
c.add_compare("--build-xml --tpm path=/dev/tpm", "build-tpm")
c.add_compare("--build-xml --blkiotune weight=100,device0.path=/dev/sdf,device.weight=200,device0.read_bytes_sec=10000,device0.write_bytes_sec=10000,device0.read_iops_sec=20000,device0.write_iops_sec=20000", "build-blkiotune")
c.add_compare("--build-xml --idmap clearxml=no,uid.start=0,uid.target=1000,uid.count=10,gid.start=0,gid.target=1000,gid.count=10", "build-idmap")
c.add_compare("--build-xml --memdev nvdimm,source.path=/path/to/nvdimm,target.size=2,target.node=0,target.label_size=1,alias.name=mymemdev3,uuid=11111111-2222-aaaa-bbbb-ccccddddeeee", "build-memdev")  # --memdev uuid= is tough to test with libvirt's validation, so we test it here with XML building
c.add_compare("--connect %(URI-KVM-X86)s --build-xml --disk %(EXISTIMG1)s", "build-disk-plain")
c.add_compare("--connect %(URI-KVM-X86)s test-many-devices --build-xml --disk %(EXISTIMG1)s", "build-disk-domain")
c.add_compare("--build-xml --sound hda,audio.id=2", "build-sound")
c.add_compare("4a64cc71-19c4-2fd0-2323-3050941ea3c3 --edit --boot network,cdrom", "edit-bootorder")  # basic bootorder test, also using UUID lookup
c.add_compare("--confirm 1 --edit --cpu host-passthrough", "prompt-response", input_text="yes")  # prompt response, also using domid lookup
c.add_compare("--edit --print-diff --qemu-commandline clearxml=yes", "edit-clearxml-qemu-commandline", input_file=(_VIRTXMLDIR + "virtxml-qemu-commandline-clear.xml"))
c.add_compare("--print-diff --remove-device --serial 1", "remove-console-dup", input_file=(_VIRTXMLDIR + "virtxml-console-dup.xml"))
c.add_compare("--print-diff --define --connect %(URI-KVM-X86)s test --edit --boot uefi", "edit-boot-uefi")
c.add_compare("--print-diff --define --connect %(URI-KVM-X86)s test-alternate-devs --edit --boot uefi=off", "edit-boot-uefi-off")
c.add_compare("--print-diff --define --connect %(URI-KVM-X86)s test-many-devices --edit --cpu host-copy", "edit-cpu-host-copy", precompare_check="10.1.0")
c.add_compare("--connect %(URI-KVM-X86)s test-many-devices --build-xml --disk source.pool=pool-disk,source.volume=sdfg1", "build-pool-logical-disk")
c.add_compare("test --add-device --network default --update --confirm", "update-succeed", env={"VIRTXML_TESTSUITE_UPDATE_IGNORE_FAIL": "1", "VIRTINST_TEST_SUITE_INCREMENT_MACADDR": "1"}, input_text="yes\nyes\n")  # test hotplug success
c.add_compare("test --add-device --network default --update --confirm --no-define", "update-nodefine-succeed", env={"VIRTXML_TESTSUITE_UPDATE_IGNORE_FAIL": "1"}, input_text="yes\n")  # test hotplug success without define

# --convert-* tests
c.add_compare("--connect %(URI-KVM-X86)s --print-diff --define --edit --convert-to-q35", "convert-to-q35", input_file=(_VIRTXMLDIR + "convert-to-q35-win10-in.xml"))
c.add_compare("--connect %(URI-KVM-X86)s --print-diff --define --edit --convert-to-q35 num_pcie_root_ports=7", "convert-to-q35-numports", input_file=(_VIRTXMLDIR + "convert-to-q35-win10-in.xml"))
c.add_compare("--connect %(URI-KVM-X86)s test --print-diff --define --edit --convert-to-vnc", "convert-to-vnc")
c.add_compare("--connect %(URI-KVM-X86)s test --print-diff --define --edit --convert-to-vnc qemu-vdagent=on", "convert-to-vnc-vdagent")

# Regression testing for historical --add-device/--remove-device/--edit multi option handling
# Single `--edit` with multiple options are processed in sequence
c.add_compare("test --print-diff --define --edit --boot emulator=/foo --boot bootmenu.enable=yes", "multi-edit-boot-backcompat")
c.add_compare("test-for-virtxml --print-diff --define --edit --network model=foo --network model=virtio --network boot.order=7", "multi-edit-device-backcompat")
# Single `--add-device` with multiple options will add multiple devices
c.add_compare("test --print-diff --define --add-device --sound model=ich9 --sound model=ac97", "multi-add-device-backcompat")
# Single `--remove-device` with multiple options will only remove the last device
c.add_compare("test-for-virtxml --print-diff --define --remove-device --network type=network --network type=bridge", "multi-remove-device-backcompat")

c.add_invalid("test --print-diff --define --add-device --sound model=ac97 --video model=virtio", grep="Only one change operation may be specified")
c.add_invalid("test-for-virtxml --print-diff --define --remove-device --sound model=ich6 --video model=vmvga", grep="Only one change operation may be specified")
c.add_invalid("test-for-virtxml --print-diff --define --edit --sound model=ac97 --video model=virtio", grep="Only one change operation may be specified")



c = vixml.add_category("simple edit diff", "test-for-virtxml --edit --print-diff --define")
c.add_compare("""--xml ./@foo=bar --xml xpath.delete=./currentMemory --xml ./new/element/test=1""", "edit-xpaths")
c.add_compare("""--metadata name=foo-my-new-name,os_name=fedora13,uuid=12345678-12F4-1234-1234-123456789AFA,description="hey this is my
new
very,very=new desc\\\'",title="This is my,funky=new title" """, "edit-simple-metadata")
c.add_compare("""--metadata os_full_id=http://fedoraproject.org/fedora/23""", "edit-metadata-full-os")
c.add_compare("--events on_poweroff=destroy,on_reboot=restart,on_crash=preserve", "edit-simple-events")
c.add_compare("--qemu-commandline='-foo bar,baz=\"wib wob\"'", "edit-simple-qemu-commandline")
c.add_compare("--memory 500,maxmemory=1000,hugepages=off", "edit-simple-memory")
c.add_compare("--memorybacking hugepages=on,access.mode=shared,source.type=file", "edit-simple-memorybacking")
c.add_compare("--vcpus 10,maxvcpus=20,cores=5,sockets=4,threads=1,placement=auto", "edit-simple-vcpus")
c.add_compare("--cpu model=pentium2,+x2apic,forbid=pbe", "edit-simple-cpu")
c.add_compare("--numatune memory.nodeset=1-5,7,memory.mode=strict,memory.placement=auto", "edit-simple-numatune")
c.add_compare("--blkiotune weight=500,device_path=/dev/sdf,device_weight=600", "edit-simple-blkiotune")
c.add_compare("--idmap uid_start=0,uid_target=2000,uid_count=30,gid_start=0,gid_target=3000,gid_count=40", "edit-simple-idmap")
c.add_compare("--boot loader=foo.bar,useserial=on,init=/bin/bash,nvram=/test/nvram.img,os_type=hvm,domain_type=test,loader.readonly=on,loader.secure=no,machine=,smbios_mode=emulate", "edit-simple-boot")
c.add_compare("--seclabel label=foo,bar,baz,UNKNOWN=val,relabel=on", "edit-simple-security")
c.add_compare("--features eoi=on,hyperv_relaxed=off,acpi=", "edit-simple-features", precompare_check="8.0.0")
c.add_compare("--clock offset=localtime,hpet_present=yes,kvmclock_present=no,kvmclock_tickpolicy=foo,rtc_tickpolicy=merge", "edit-simple-clock")
c.add_compare("--pm suspend_to_mem.enabled=yes,suspend_to_disk.enabled=no", "edit-simple-pm")
c.add_compare("--disk /dev/zero,perms=ro,source.startupPolicy=optional", "edit-simple-disk")
c.add_compare("--disk path=", "edit-simple-disk-remove-path")
c.add_compare("--disk xpath1.delete=./source,xpath2.set=./boot/@order,xpath2.value=6,xpath3.create=./fakeelement", "edit-device-xpath")
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
c.add_invalid("--edit target=vvv --disk /dev/null", grep="No matching objects found for --edit target=vvv")
c.add_invalid("--edit seclabel2.model=dac --disk /dev/null", grep="No matching objects found for --edit seclabel2.model=dac")
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
c.add_compare("--edit address.devno=0x0002 --hostdev address.devno=0x0008", "edit-hostdev-mdev")

c = vixml.add_category("edit and start selection", "test-state-shutoff --print-diff --start")
c.add_compare("--define --edit target=vda --disk boot_order=1", "start-select-disk-bootorder")
c.add_invalid("--define --no-define --edit target=vda --disk boot_order=1", grep="argument --no-define: not allowed with argument --define")
c.add_compare("--edit target=vda --disk boot_order=1", "start-select-disk-bootorder2")
c.add_compare("--no-define --edit target=vda --disk boot_order=1", "start-select-disk-bootorder2")

c = vixml.add_category("edit selection 2", "test-collide --print-diff --define")
c.add_compare("--edit target=hda --disk boot_order=1", "edit-select-disk-bootorder2")

c = vixml.add_category("edit clear", "test-for-virtxml --print-diff --define")
c.add_invalid("--edit --memory 200,clearxml=yes", grep="Don't know how to clearxml for --memory")
c.add_compare("--edit --disk path=/foo/bar,size=2,target=fda,bus=fdc,device=floppy,clearxml=yes", "edit-clear-disk")
c.add_compare("--edit --cpu host-passthrough,clearxml=yes", "edit-clear-cpu")
c.add_compare("--edit --clock offset=utc,clearxml=yes", "edit-clear-clock")
c.add_compare("--edit --video clearxml=yes,model=virtio,accel3d=yes", "edit-video-virtio")
c.add_compare("--edit --graphics clearxml=yes,type=spice,gl=on,listen=none", "edit-graphics-spice-gl")

c = vixml.add_category("add/rm devices", "test-for-virtxml --print-diff --define")
c.add_compare("--add-device --seclabel model=dac", "add-seclabel")
c.add_compare("--add-device --host-device usb_device_483_2016_noserial", "add-host-device")
c.add_compare("--add-device --sound pcspk", "add-sound")
c.add_compare("--add-device --audio type=none,id=1", "add-audio", predefine_check="7.4.0")
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
c.add_compare("--add-device --hostdev mdev_8e37ee90_2b51_45e3_9b25_bf8283c03110", "add-hostdev-mdev", prerun_check="10.4.0")
c.add_compare("--remove-device --hostdev mdev_b1ae8bf6_38b0_4c81_9d44_78ce3f520496", "remove-hostdev-mdev")

c = vixml.add_category("edit/remove spice graphics", "test-spice --print-diff --define")
c.add_compare("--edit --graphics type=vnc", "change-spice-to-vnc")
c.add_compare("--remove-device --graphics type=spice", "remove-spice-graphics")

c = vixml.add_category("add/rm devices and start", "test-state-shutoff --print-diff --start")
c.add_invalid("--add-device --pm suspend_to_disk=yes", grep="Cannot use --add-device with --pm")  # --add-device without a device
c.add_invalid("--remove-device --clock utc", grep="Cannot use --remove-device with --clock")  # --remove-device without a dev
# one test in combination with --define
c.add_compare("--define --add-device --host-device usb_device_4b3_4485_noserial", "add-host-device-start")
# all other test cases without
c.add_compare("--add-device --disk %(EXISTIMG1)s,bus=virtio,target=vdf", "add-disk-basic-start")
c.add_compare("--add-device --disk %(NEWIMG1)s,size=.01", "add-disk-create-storage-start")
c.add_compare("--remove-device --disk /dev/null", "remove-disk-path-start")
c.add_compare("--add-device --hostdev mdev_8e37ee90_2b51_45e3_9b25_bf8283c03110", "add-hostdev-mdev-start", prerun_check="10.4.0")

c = vixml.add_category("add/rm devices OS KVM", "--connect %(URI-KVM-X86)s test --print-diff --define")
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
_CLONE_SERIAL = "--original-xml %s/clone-serial.xml" % _CLONEXMLDIR


vclon = App("virt-clone")
c = vclon.add_category("remote", "--connect %(URI-TEST-REMOTE)s")
c.add_valid(_CLONE_EMPTY + " --auto-clone")  # Auto flag, no storage
c.add_valid(_CLONE_MANAGED + " --auto-clone")  # Auto flag w/ managed storage
c.add_invalid(_CLONE_UNMANAGED + " --auto-clone", grep="does not exist")  # Auto flag w/ local storage, which is invalid for remote connection


c = vclon.add_category("misc", "")
c.add_compare("--connect %(URI-KVM-X86)s -o test-clone --auto-clone", "clone-auto1")
c.add_compare("--connect %(URI-TEST-FULL)s -o test-clone-simple --name newvm --auto-clone --reflink", "clone-auto2")
c.add_compare("--connect %(URI-KVM-X86)s " + _CLONE_NVRAM + " --auto-clone", "clone-nvram")  # hits a particular nvram code path
c.add_compare("--connect %(URI-KVM-X86)s " + _CLONE_NVRAM + " --auto-clone --nvram /nvram/my-custom-path", "clone-nvram-path")  # hits a particular nvram code path
c.add_compare("--connect %(URI-KVM-X86)s " + _CLONE_NVRAM_NEWPOOL + " --auto-clone", "nvram-newpool")  # hits a particular nvram code path
c.add_compare("--connect %(URI-KVM-X86)s " + _CLONE_NVRAM_MISSING + " --auto-clone", "nvram-missing")  # hits a particular nvram code path
c.add_compare("--connect %(URI-KVM-X86)s " + _CLONE_NVRAM_MISSING + " --auto-clone --preserve", "nvram-missing-preserve")  # hits a particular nvram code path
c.add_compare("--connect %(URI-KVM-X86)s -o test-clone -n test-newclone --mac 12:34:56:1A:B2:C3 --mac 12:34:56:1A:B7:C3 --uuid 12345678-12F4-1234-1234-123456789AFA --file /dev/pool-logical/newclone1.img --file /pool-dir/newclone2.img --skip-copy=hdb --force-copy=sdb --file /pool-dir/newclone3.img", "clone-manual")
c.add_compare("--connect %(URI-KVM-X86)s -o test-clone -n test-newclone --mac 12:34:56:1A:B2:C3 --mac 12:34:56:1A:B7:C3 --uuid 12345678-12F4-1234-1234-123456789AFA --file /dev/pool-logical/newclone1.img --file /pool-dir/newclone2.img --skip-copy=hdb --force-copy=sdb --file /pool-dir/newclone3.img", "clone-manual")
c.add_compare(_CLONE_EMPTY + " --auto-clone --print-xml", "empty")  # Auto flag, no storage
c.add_compare("--connect %(URI-KVM-X86)s -o test-clone-simple --auto -f /foo.img --print-xml", "pool-test-cross-pool")  # cross pool cloning which fails with test driver but let's confirm the XML
c.add_compare(_CLONE_MANAGED + " --auto-clone", "auto-managed")  # Auto flag w/ managed storage
c.add_compare(_CLONE_UNMANAGED + " --auto-clone", "auto-unmanaged")  # Auto flag w/ local storage
c.add_compare(_CLONE_SERIAL + " --auto-clone", "serial")  # Auto flag w/ serial console
c.add_valid("--connect %(URI-TEST-FULL)s -o test-clone --auto-clone --nonsparse")  # Auto flag, actual VM, skip state check
c.add_valid("--connect %(URI-TEST-FULL)s -o test-clone-simple -n newvm --preserve-data --file %(EXISTIMG1)s")  # Preserve data shouldn't complain about existing volume
c.add_valid("-n clonetest " + _CLONE_UNMANAGED + " --file %(EXISTIMG3)s --file %(EXISTIMG4)s --check path_exists=off")  # Skip existing file check
c.add_valid("-n clonetest " + _CLONE_UNMANAGED + " --auto-clone --mac 22:11:11:11:11:11 --check all=off")  # Colliding mac but we skip the check
c.add_invalid("-n clonetest " + _CLONE_UNMANAGED + " --auto-clone --mac 22:11:11:11:11:11", grep="--check mac_in_use=off")  # Colliding mac should fail
c.add_invalid("--auto-clone", grep="An original machine name is required")  # No clone VM specified
c.add_invalid(_CLONE_EMPTY + " --file foo", grep="use '--name NEW_VM_NAME'")  # Didn't specify new name
c.add_invalid(_CLONE_EMPTY + " --auto-clone -n test", grep="Invalid name for new guest")  # new name raises error, already in use
c.add_invalid("-o test --auto-clone", grep="shutoff")  # VM is running
c.add_invalid("--connect %(URI-TEST-FULL)s -o test-clone-simple -n newvm --file %(EXISTIMG1)s", grep="Clone onto existing storage volume is not currently supported")  # Should complain about overwriting existing file
c.add_invalid("--connect %(URI-TEST-REMOTE)s -o test-clone-simple --auto-clone --file /pool-dir/testvol9.img --check all=off", grep="Clone onto existing storage volume")  # hit a specific error message
c.add_invalid("--connect %(URI-TEST-FULL)s -o test-clone-full --auto-clone", grep="not enough free space")  # catch failure of clone path setting
c.add_invalid(_CLONE_NET_HTTP + " --auto-clone", grep="'http' is not cloneable")
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
c.add_compare("--connect %(URI-TEST-FULL)s -o test-clone -n test --auto-clone --replace", "replace")  # Overwriting existing running VM
c.add_valid(_CLONE_MANAGED + " --auto-clone --force-copy fda")  # force copy empty floppy drive
c.add_invalid("-o idontexist --auto-clone", grep="Domain 'idontexist' was not found")  # Non-existent vm name
c.add_invalid(_CLONE_UNMANAGED, grep="Either --auto-clone or --file")  # XML file with several disks, but non specified
c.add_invalid(_CLONE_UNMANAGED + " --file virt-install", grep="overwrite the existing path")  # XML w/ disks, overwriting existing files with no --preserve
c.add_invalid(_CLONE_MANAGED + " --file /tmp/clonevol", grep="matching name 'default-vol'")  # will attempt to clone across pools, which test driver doesn't support
c.add_valid(_CLONE_NOEXIST + " --file %(EXISTIMG1)s --preserve")  # XML w/ non-existent storage, but using --preserve flag shouldn't raise an error
c.add_invalid(_CLONE_NOEXIST + " --file %(EXISTIMG1)s", grep="StoragePool.install testsuite mocked failure")  # XML w/ non-existent storage, WITHOUT --preserve, so it _should_ error




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
    cmdlist += vixml.cmds
    cmdlist += vclon.cmds
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

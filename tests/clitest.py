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

import atexit
import logging
import os
import shlex
import subprocess
import sys
import time
import traceback
import unittest
import StringIO

import virtinst.cli

from tests import virtinstall, virtimage, virtclone, virtconvert
from tests import utils

os.environ["VIRTCONV_TEST_NO_DISK_CONVERSION"] = "1"
os.environ["LANG"] = "en_US.UTF-8"

testuri = "test:///%s/tests/testdriver.xml" % os.getcwd()

# There is a hack in virtinst/cli.py to find this magic string and
# convince virtinst we are using a remote connection.
fakeuri     = "__virtinst_test__" + testuri + ",predictable"
capsprefix  = ",caps=%s/tests/capabilities-xml/" % os.getcwd()
remoteuri   = fakeuri + ",remote"
kvmuri      = fakeuri + capsprefix + "libvirt-0.7.6-qemu-caps.xml,qemu"
xenuri      = fakeuri + capsprefix + "rhel5.4-xen-caps-virt-enabled.xml,xen"
xenia64uri  = fakeuri + capsprefix + "xen-ia64-hvm.xml,xen"
lxcuri      = fakeuri + capsprefix + "capabilities-lxc.xml,lxc"

# Location
image_prefix = "/tmp/__virtinst_cli_"
xmldir = "tests/cli-test-xml"
treedir = "%s/faketree" % xmldir
vcdir = "%s/virtconv" % xmldir
ro_dir = image_prefix + "clitest_rodir"
ro_img = "%s/cli_exist3ro.img" % ro_dir
ro_noexist_img = "%s/idontexist.img" % ro_dir
compare_xmldir = "%s/compare" % xmldir
virtconv_out = "/tmp/__virtinst_tests__virtconv-outdir"

# Images that will be created by virt-install/virt-clone, and removed before
# each run
new_images = [
    image_prefix + "new1.img",
    image_prefix + "new2.img",
    image_prefix + "new3.img",
    image_prefix + "exist1-clone.img",
    image_prefix + "exist2-clone.img",
]

# Images that are expected to exist before a command is run
exist_images = [
    image_prefix + "exist1.img",
    image_prefix + "exist2.img",
    ro_img,
]

# Images that need to exist ahead of time for virt-image
virtimage_exist = ["/tmp/__virtinst__cli_root.raw"]

# Images created by virt-image
virtimage_new = ["/tmp/__virtinst__cli_scratch.raw"]

# virt-convert output dirs
virtconv_dirs = [virtconv_out]

exist_files = exist_images + virtimage_exist
new_files   = new_images + virtimage_new + virtconv_dirs
clean_files = (new_images + exist_images +
               virtimage_exist + virtimage_new + virtconv_dirs + [ro_dir])

promptlist = []

test_files = {
    'TESTURI'           : testuri,
    'DEFAULTURI'        : "__virtinst_test__test:///default,predictable",
    'REMOTEURI'         : remoteuri,
    'KVMURI'            : kvmuri,
    'XENURI'            : xenuri,
    'XENIA64URI'        : xenia64uri,
    'LXCURI'            : lxcuri,
    'CLONE_DISK_XML'    : "%s/clone-disk.xml" % xmldir,
    'CLONE_STORAGE_XML' : "%s/clone-disk-managed.xml" % xmldir,
    'CLONE_NOEXIST_XML' : "%s/clone-disk-noexist.xml" % xmldir,
    'IMAGE_XML'         : "%s/image.xml" % xmldir,
    'IMAGE_NOGFX_XML'   : "%s/image-nogfx.xml" % xmldir,
    'NEWIMG1'           : new_images[0],
    'NEWIMG2'           : new_images[1],
    'NEWIMG3'           : new_images[2],
    'EXISTIMG1'         : exist_images[0],
    'EXISTIMG2'         : exist_images[1],
    'ROIMG'             : ro_img,
    'ROIMGNOEXIST'      : ro_noexist_img,
    'POOL'              : "default-pool",
    'VOL'               : "testvol1.img",
    'DIR'               : os.getcwd(),
    'TREEDIR'           : treedir,
    'MANAGEDEXIST1'     : "/dev/default-pool/testvol1.img",
    'MANAGEDEXIST2'     : "/dev/default-pool/testvol2.img",
    'MANAGEDEXISTUPPER' : "/dev/default-pool/UPPER",
    'MANAGEDNEW1'       : "/dev/default-pool/clonevol",
    'MANAGEDNEW2'       : "/dev/default-pool/clonevol",
    'MANAGEDDISKNEW1'   : "/dev/disk-pool/newvol1.img",
    'COLLIDE'           : "/dev/default-pool/collidevol1.img",
    'SHARE'             : "/dev/default-pool/sharevol.img",

    'VIRTCONV_OUT'      : "%s/test.out" % virtconv_out,
    'VC_IMG1'           : "%s/virtimage/test1.virt-image" % vcdir,
    'VC_IMG2'           : "tests/image-xml/image-format.xml",
    'VMX_IMG1'          : "%s/vmx/test1.vmx" % vcdir,
}



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

        app, opts = self.cmdstr.split(" ", 1)
        self.argv = [os.path.abspath(app)] + shlex.split(opts)

    def _launch_command(self):
        logging.debug(self.cmdstr)

        uri = None
        conn = None
        app = self.argv[0]

        for idx in reversed(range(len(self.argv))):
            if self.argv[idx] == "--connect":
                uri = self.argv[idx + 1]
                break

        if uri:
            conn = open_conn(uri)

        oldstdout = sys.stdout
        oldstderr = sys.stderr
        oldargv = sys.argv
        try:
            out = StringIO.StringIO()
            sys.stdout = out
            sys.stderr = out
            sys.argv = self.argv

            try:
                if app.count("virt-install"):
                    ret = virtinstall.main(conn=conn)
                elif app.count("virt-clone"):
                    ret = virtclone.main(conn=conn)
                elif app.count("virt-image"):
                    ret = virtimage.main(conn=conn)
                elif app.count("virt-convert"):
                    ret = virtconvert.main()
            except SystemExit, sys_e:
                ret = sys_e.code

            if ret != 0:
                ret = -1
            outt = out.getvalue()
            if outt.endswith("\n"):
                outt = outt[:-1]
            return (ret, outt)
        finally:
            sys.stdout = oldstdout
            sys.stderr = oldstderr
            sys.argv = oldargv


    def _get_output(self):
        try:
            for i in new_files:
                os.system("rm %s > /dev/null 2>&1" % i)

            code, output = self._launch_command()

            logging.debug(output + "\n")
            return code, output
        except Exception, e:
            return (-1, "".join(traceback.format_exc()) + str(e))

    def run(self):
        filename = self.compare_file
        err = None

        try:
            code, output = self._get_output()

            if bool(code) == self.check_success:
                raise AssertionError(
                    ("Expected command to %s, but failed.\n" %
                     (self.check_success and "pass" or "fail")) +
                     ("Command was: %s\n" % self.cmdstr) +
                     ("Error code : %d\n" % code) +
                     ("Output was:\n%s" % output))

            if filename:
                # Generate test files that don't exist yet
                if not os.path.exists(filename):
                    file(filename, "w").write(output)

                utils.diff_compare(output, filename)

        except AssertionError, e:
            err = self.cmdstr + "\n" + str(e)

        return err


class PromptCheck(object):
    """
    Individual question/response pair for automated --prompt tests
    """
    def __init__(self, prompt, response=None):
        self.prompt = prompt
        self.response = response
        if self.response:
            self.response = self.response % test_files

    def check(self, proc):
        out = proc.stdout.readline()

        if not out.count(self.prompt):
            out += "\nContent didn't contain prompt '%s'" % (self.prompt)
            return False, out

        if self.response:
            proc.stdin.write(self.response + "\n")

        return True, out


class PromptTest(Command):
    """
    Fully automated --prompt test
    """
    def __init__(self, cmdstr):
        Command.__init__(self, cmdstr)

        self.prompt_list = []

    def add(self, *args, **kwargs):
        self.prompt_list.append(PromptCheck(*args, **kwargs))

    def _launch_command(self):
        proc = subprocess.Popen(self.argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT)

        out = "Running %s\n" % self.cmdstr

        for p in self.prompt_list:
            ret, content = p.check(proc)
            out += content
            if not ret:
                # Since we didn't match output, process might be hung
                proc.kill()
                break

        exited = False
        for ignore in range(30):
            if proc.poll() is not None:
                exited = True
                break
            time.sleep(.1)

        if not exited:
            proc.kill()
            out += "\nProcess was killed by test harness"

        return proc.wait(), out



class App(object):
    def __init__(self, appname):
        self.appname = appname
        self.categories = {}
        self.cmds = []

    def _default_args(self, cli, iscompare):
        args = ""
        if not iscompare:
            args = "--debug"

        if self.appname != "virt-convert" and not iscompare:
            if "--connect " not in cli:
                args += " --connect %(TESTURI)s"

        if self.appname in ["virt-install"]:
            if "--name " not in cli:
                args += " --name foobar"
            if "--ram " not in cli:
                args += " --ram 64"

        if iscompare:
            if self.appname == "virt-install":
                if (not cli.count("--print-xml") and
                    not cli.count("--print-step") and
                    not cli.count("--quiet")):
                    args += " --print-step all"

            elif self.appname == "virt-image":
                if not cli.count("--print"):
                    args += " --print"

            elif self.appname == "virt-clone":
                if not cli.count("--print-xml"):
                    args += " --print-xml"

            if self.appname != "virt-convert" and not "--connect " in cli:
                args += " --connect %s" % fakeuri

        return args


    def add_category(self, catname, default_args):
        self.categories[catname] = default_args

    def _add(self, catname, testargs, valid, compfile):
        args = self.categories[catname] + " " + testargs
        args = self._default_args(args, bool(compfile)) + " " + args
        cmdstr = "./%s %s" % (self.appname, args)

        cmd = Command(cmdstr)
        cmd.check_success = valid
        if compfile:
            cmd.compare_file = "%s/%s.xml" % (compare_xmldir, compfile)
        self.cmds.append(cmd)

    def add_valid(self, cat, args):
        self._add(cat, args, True, None)
    def add_invalid(self, cat, args):
        self._add(cat, args, False, None)
    def add_compare(self, cat, args, compfile):
        self._add(cat, args, not compfile.endswith("-fail"), compfile)



#
# The test matrix
#
# add_valid: A test that should pass
# add_invalid: A test that should fail
# add_compare: Get the generated XML, and compare against the passed filename
#              in tests/clitest-xml/compare/
#

vinst = App("virt-install")
vinst.add_category("cpuram", "--hvm --nographics --noautoconsole --nodisks --pxe")
vinst.add_valid("cpuram", "--vcpus 32")  # Max VCPUS
vinst.add_valid("cpuram", "--vcpus 4 --cpuset=1,3-5")  # Cpuset
vinst.add_valid("cpuram", "--vcpus 4 --cpuset=1,3-5,")  # Cpuset with trailing comma
vinst.add_valid("cpuram", "--vcpus 4 --cpuset=auto")  # Cpuset with trailing comma
vinst.add_valid("cpuram", "--ram 100000000000")  # Ram overcommit
vinst.add_valid("cpuram", "--vcpus 5,maxvcpus=10 --check-cpu")  # maxvcpus, --check-cpu shouldn't error
vinst.add_valid("cpuram", "--vcpus 4,cores=2,threads=2,sockets=2")  # Topology
vinst.add_valid("cpuram", "--vcpus 4,cores=1")  # Topology auto-fill
vinst.add_valid("cpuram", "--vcpus sockets=2,threads=2")  # Topology only
vinst.add_valid("cpuram", "--cpu somemodel")  # Simple --cpu
vinst.add_valid("cpuram", "--cpu foobar,+x2apic,+x2apicagain,-distest,forbid=foo,forbid=bar,disable=distest2,optional=opttest,require=reqtest,match=strict,vendor=meee")  # Crazy --cpu
vinst.add_valid("cpuram", "--numatune 1,2,3,5-7,^6")  # Simple --numatune
vinst.add_invalid("cpuram", "--vcpus 32 --cpuset=969-1000")  # Bogus cpuset
vinst.add_invalid("cpuram", "--vcpus 32 --cpuset=autofoo")  # Bogus cpuset
vinst.add_invalid("cpuram", "--vcpus 20 --check-cpu")  # Over host vcpus w/ --check-cpu
vinst.add_invalid("cpuram", "--vcpus foo=bar")  # vcpus unknown option
vinst.add_invalid("cpuram", "--cpu host")  # --cpu host, but no host CPU in caps
vinst.add_invalid("cpuram", "--numatune 1-3,4,mode=strict")  # Non-escaped numatune


vinst.add_category("smartcard", "--noautoconsole --nodisks --pxe")
vinst.add_valid("smartcard", "--smartcard host")  # --smartcard host
vinst.add_valid("smartcard", "--smartcard none")  # --smartcard none,
vinst.add_valid("smartcard", "--smartcard passthrough,type=spicevmc")  # --smartcard mode with type
vinst.add_invalid("smartcard", "--smartcard")  # Missing argument
vinst.add_invalid("smartcard", "--smartcard foo")  # Invalid argument
vinst.add_invalid("smartcard", "--smartcard passthrough,type=foo")  # Invalid type
vinst.add_invalid("smartcard", "--smartcard host,foobar=baz")  # --smartcard bogus


vinst.add_category("tpm", "--noautoconsole --nodisks --pxe")
vinst.add_valid("tpm", "--tpm passthrough")  # --tpm passthrough
vinst.add_valid("tpm", "--tpm passthrough,model=tpm-tis")  # --tpm backend type with model
vinst.add_valid("tpm", "--tpm passthrough,model=tpm-tis,path=/dev/tpm0")  # --tpm backend type with model and device path
vinst.add_invalid("tpm", "--tpm")  # Missing argument
vinst.add_invalid("tpm", "--tpm foo")  # Invalid argument
vinst.add_invalid("tpm", "--tpm passthrough,model=foo")  # Invalid model


vinst.add_category("xen", "--connect %(XENURI)s --noautoconsole")
vinst.add_compare("xen", "--disk %(EXISTIMG1)s --import", "xen-default")  # Xen default
vinst.add_compare("xen", "--disk %(EXISTIMG1)s --location %(TREEDIR)s --paravirt", "xen-pv")  # Xen PV
vinst.add_compare("xen", "--disk %(EXISTIMG1)s --cdrom %(EXISTIMG1)s --livecd --hvm", "xen-hvm")  # Xen HVM
vinst.add_compare("xen", "--connect %(XENIA64URI)s --disk %(EXISTIMG1)s --import", "xen-ia64-default")  # ia64 default
vinst.add_compare("xen", "--connect %(XENIA64URI)s --disk %(EXISTIMG1)s --location %(TREEDIR)s --paravirt", "xen-ia64-pv")  # ia64 pv
vinst.add_compare("xen", "--connect %(XENIA64URI)s --disk %(EXISTIMG1)s --location %(TREEDIR)s --hvm", "xen-ia64-hvm")  # ia64 hvm
vinst.add_valid("xen", "--nodisks --cdrom %(EXISTIMG1)s --livecd --hvm")  # HVM
vinst.add_valid("xen", "--nodisks --boot hd --paravirt")  # PV
vinst.add_valid("xen", "--nodisks --boot hd --paravirt --arch i686")  # 32 on 64 xen


vinst.add_category("kvm", "--connect %(KVMURI)s --noautoconsole")
vinst.add_compare("kvm", "--os-variant fedora14 --file %(EXISTIMG1)s --location %(TREEDIR)s --extra-args console=ttyS0 --cpu host", "kvm-f14-url")  # F14 Directory tree URL install with extra-args
vinst.add_compare("kvm", "--os-variant fedora14 --disk %(NEWIMG1)s,size=.01 --location %(TREEDIR)s --extra-args console=ttyS0 --quiet", "quiet-url")  # Quiet URL install should make no noise
vinst.add_compare("kvm", "--cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --sound", "kvm-win2k3-cdrom")  # HVM windows install with disk
vinst.add_compare("kvm", "--os-variant fedora14 --nodisks --boot hd --paravirt", "kvm-xenner")  # xenner
vinst.add_compare("kvm", "--os-variant fedora14 --nodisks --boot cdrom --virt-type qemu --cpu Penryn", "qemu-plain")  # plain qemu
vinst.add_compare("kvm", "--os-variant fedora14 --nodisks --boot network --nographics --arch i686", "qemu-32-on-64")  # 32 on 64
vinst.add_compare("kvm", "--os-variant fedora14 --nodisks --boot fd --graphics spice --machine pc", "kvm-machine")  # kvm machine type 'pc'
vinst.add_compare("kvm", "--os-variant fedora14 --nodisks --boot fd --graphics sdl --arch sparc --machine SS-20", "qemu-sparc")  # exotic arch + machine type
vinst.add_valid("kvm", "--cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --sound")  # HVM windows install with disk
vinst.add_valid("kvm", "--os-variant fedora14 --file %(EXISTIMG1)s --location %(TREEDIR)s --extra-args console=ttyS0 --sound")  # F14 Directory tree URL install with extra-args
vinst.add_invalid("kvm", "--nodisks --boot network --machine foobar")  # Unknown machine type
vinst.add_invalid("kvm", "--nodisks --boot network --arch mips --virt-type kvm")  # Invalid domain type for arch
vinst.add_invalid("kvm", "--nodisks --boot network --paravirt --arch mips")  # Invalid arch/virt combo


vinst.add_category("misc", "--nographics --noautoconsole")
vinst.add_compare("misc", "", "noargs-fail")  # No arguments
vinst.add_compare("misc", "--hvm --nodisks --pxe --print-step all", "simple-pxe")  # Diskless PXE install
vinst.add_compare("misc", "--hvm --cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --vcpus cores=4", "w2k3-cdrom")  # HVM windows install with disk
vinst.add_compare("misc", """--hvm --pxe --controller usb,model=ich9-ehci1,address=0:0:4.7,index=0 --controller usb,model=ich9-uhci1,address=0:0:4.0,index=0,master=0 --controller usb,model=ich9-uhci2,address=0:0:4.1,index=0,master=2 --controller usb,model=ich9-uhci3,address=0:0:4.2,index=0,master=4 --disk %(MANAGEDEXISTUPPER)s,cache=writeback,io=threads,perms=sh,serial=WD-WMAP9A966149 --disk %(NEWIMG1)s,sparse=false,size=.001,perms=ro,error_policy=enospace --disk device=cdrom,bus=sata --serial tcp,host=:2222,mode=bind,protocol=telnet --filesystem /source,/target,mode=squash --network user,mac=12:34:56:78:11:22 --network bridge=foobar,model=virtio --channel spicevmc --smartcard passthrough,type=spicevmc --tpm passthrough,model=tpm-tis,path=/dev/tpm0 --security type=static,label='system_u:object_r:svirt_image_t:s0:c100,c200',relabel=yes  --numatune \\"1-3,5\\",mode=preferred --boot loader=/foo/bar """, "many-devices")  # Lot's of devices
vinst.add_compare("misc", "--connect %(DEFAULTURI)s --hvm --nodisks --pxe --cpuset auto --vcpus 2", "cpuset-auto")  # --cpuset=auto actually works
vinst.add_valid("misc", "--hvm --disk path=virt-install,device=cdrom")  # Specifying cdrom media via --disk
vinst.add_valid("misc", "--hvm --import --disk path=virt-install")  # FV Import install
vinst.add_valid("misc", "--hvm --import --disk path=virt-install --prompt --force")  # Working scenario w/ prompt shouldn't ask anything
vinst.add_valid("misc", "--paravirt --import --disk path=virt-install")  # PV Import install
vinst.add_valid("misc", "--paravirt --import --disk path=virt-install --print-xml")  # PV Import install, print single XML
vinst.add_valid("misc", "--hvm --import --disk path=virt-install,device=floppy")  # Import a floppy disk
vinst.add_valid("misc", "--hvm --nodisks --pxe --autostart")  # --autostart flag
vinst.add_valid("misc", "--hvm --nodisks --pxe --description \"foobar & baz\"")  # --description
vinst.add_valid("misc", "--hvm --cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0")  # HVM windows install with disk
vinst.add_valid("misc", "--hvm --cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --print-step 3")  # HVM windows install, print 3rd stage XML
vinst.add_valid("misc", "--hvm --nodisks --pxe --watchdog default")  # --watchdog dev default
vinst.add_valid("misc", "--hvm --nodisks --pxe --watchdog ib700,action=pause")  # --watchdog opts
vinst.add_valid("misc", "--hvm --nodisks --pxe --sound")  # --sound option
vinst.add_valid("misc", "--hvm --nodisks --pxe --soundhw default --soundhw ac97")  # --soundhw option
vinst.add_valid("misc", "--hvm --nodisks --pxe --security type=dynamic")  # --security dynamic
vinst.add_valid("misc", "--hvm --nodisks --pxe --security label=foobar.label,relabel=yes")  # --security implicit static
vinst.add_valid("misc", "--hvm --nodisks --pxe --security label=foobar.label,a1,z2,b3,type=static,relabel=no")  # --security static with commas 1
vinst.add_valid("misc", "--hvm --nodisks --pxe --security label=foobar.label,a1,z2,b3")  # --security static with commas 2
vinst.add_valid("misc", "--hvm --pxe --filesystem /foo/source,/bar/target")  # --filesystem simple
vinst.add_valid("misc", "--hvm --pxe --filesystem template_name,/,type=template")  # --filesystem template
vinst.add_valid("misc", "--hvm --nodisks --nonetworks --cdrom %(EXISTIMG1)s")  # no networks
vinst.add_valid("misc", "--hvm --nodisks --pxe --memballoon virtio")  # --memballoon use virtio
vinst.add_valid("misc", "--hvm --nodisks --pxe --memballoon none")  # --memballoon disabled
vinst.add_invalid("misc", "--hvm --nodisks --pxe foobar")  # Positional arguments error
vinst.add_invalid("misc", "--nodisks --pxe --nonetworks")  # pxe and nonetworks
vinst.add_invalid("misc", "--nodisks --pxe --name test")  # Colliding name
vinst.add_invalid("misc", "--hvm --nodisks --pxe --watchdog default,action=foobar")  # Busted --watchdog
vinst.add_invalid("misc", "--hvm --nodisks --pxe --soundhw default --soundhw foobar")  # Busted --soundhw
vinst.add_invalid("misc", "--hvm --nodisks --pxe --security type=foobar")  # Busted --security
vinst.add_invalid("misc", "--paravirt --import --disk path=virt-install --print-step 2")  # PV Import install, no second XML step
vinst.add_invalid("misc", "--hvm --nodisks --pxe --print-xml")  # 2 stage install with --print-xml
vinst.add_invalid("misc", "--hvm --nodisks --pxe --memballoon foobar")  # Busted --memballoon


vinst.add_category("char", "--hvm --nographics --noautoconsole --nodisks --pxe")
vinst.add_valid("char", "--serial pty --parallel null")  # Simple devs
vinst.add_valid("char", "--serial file,path=/tmp/foo --parallel unix,path=/tmp/foo --parallel null")  # Some with options
vinst.add_valid("char", "--parallel udp,host=0.0.0.0:1234,bind_host=127.0.0.1:1234")  # UDP
vinst.add_valid("char", "--serial tcp,mode=bind,host=0.0.0.0:1234")  # TCP
vinst.add_valid("char", "--parallel unix,path=/tmp/foo-socket")  # Unix
vinst.add_valid("char", "--serial tcp,host=:1234,protocol=telnet")  # TCP w/ telnet
vinst.add_valid("char", "--channel pty,target_type=guestfwd,target_address=127.0.0.1:10000")  # --channel guestfwd
vinst.add_valid("char", "--channel pty,target_type=virtio,name=org.linux-kvm.port1")  # --channel virtio
vinst.add_valid("char", "--channel pty,target_type=virtio")  # --channel virtio without name=
vinst.add_valid("char", "--console pty,target_type=virtio")  # --console virtio
vinst.add_valid("char", "--console pty,target_type=xen")  # --console xen
vinst.add_invalid("char", "--parallel foobah")  # Bogus device type
vinst.add_invalid("char", "--serial unix")  # Unix with no path
vinst.add_invalid("char", "--serial null,path=/tmp/foo")  # Path where it doesn't belong
vinst.add_invalid("char", "--serial udp,host=:1234,frob=baz")  # Nonexistent argument
vinst.add_invalid("char", "--channel pty,target_type=guestfwd")  # --channel guestfwd without target_address
vinst.add_invalid("char", "--console pty,target_type=abcd")  # --console unknown type


vinst.add_category("controller", "--noautoconsole --nodisks --pxe")
vinst.add_valid("controller", "--controller usb,model=ich9-ehci1,address=0:0:4.7")
vinst.add_valid("controller", "--controller usb,model=ich9-ehci1,address=0:0:4.7,index=0")
vinst.add_valid("controller", "--controller usb,model=ich9-ehci1,address=0:0:4.7,index=1")
vinst.add_valid("controller", "--controller usb2")
vinst.add_invalid("controller", "--controller")  # Missing argument
vinst.add_invalid("controller", "--controller foo")  # Invalid argument
vinst.add_invalid("controller", "--controller usb,model=ich9-ehci1,address=0:0:4.7,index=bar,master=foo")  # Invalid values
vinst.add_invalid("controller", "--controller host,foobar=baz")  # --bogus


vinst.add_category("lxc", "--connect %(LXCURI)s --noautoconsole --name foolxc --ram 64")
vinst.add_compare("lxc", "", "default")
vinst.add_compare("lxc", "--filesystem /source,/", "fs-default")
vinst.add_compare("lxc", "--init /usr/bin/httpd", "manual-init")


vinst.add_category("graphics", "--noautoconsole --nodisks --pxe")
vinst.add_valid("graphics", "--sdl")  # SDL
vinst.add_valid("graphics", "--graphics sdl")  # --graphics SDL
vinst.add_valid("graphics", "--graphics none")  # --graphics none,
vinst.add_valid("graphics", "--vnc --keymap ja --vncport 5950 --vnclisten 1.2.3.4")  # VNC w/ lots of options
vinst.add_valid("graphics", "--graphics vnc,port=5950,listen=1.2.3.4,keymap=ja,password=foo")  # VNC w/ lots of options, new way
vinst.add_valid("graphics", "--graphics spice,port=5950,tlsport=5950,listen=1.2.3.4,keymap=ja")  # SPICE w/ lots of options
vinst.add_valid("graphics", "--vnc --video vga")  # --video option
vinst.add_valid("graphics", "--graphics spice --video qxl")  # --video option
vinst.add_valid("graphics", "--vnc --keymap local")  # --keymap local,
vinst.add_valid("graphics", "--vnc --keymap none")  # --keymap none
vinst.add_invalid("graphics", "--vnc --keymap ZZZ")  # Invalid keymap
vinst.add_invalid("graphics", "--vnc --vncport -50")  # Invalid port
vinst.add_invalid("graphics", "--graphics spice,tlsport=-50")  # Invalid port
vinst.add_invalid("graphics", "--vnc --video foobar")  # Invalid --video
vinst.add_invalid("graphics", "--graphics vnc,foobar=baz")  # --graphics bogus
vinst.add_invalid("graphics", "--graphics vnc --vnclisten 1.2.3.4")  # mixing old and new


vinst.add_category("remote", "--connect %(REMOTEURI)s --nographics --noautoconsole")
vinst.add_valid("remote", "--nodisks --pxe")  # Simple pxe nodisks
vinst.add_valid("remote", "--nodisks --cdrom %(MANAGEDEXIST1)s")  # Managed CDROM install
vinst.add_valid("remote", "--pxe --file %(MANAGEDEXIST1)s")  # Using existing managed storage
vinst.add_valid("remote", "--pxe --disk vol=%(POOL)s/%(VOL)s")  # Using existing managed storage 2
vinst.add_valid("remote", "--pxe --disk pool=%(POOL)s,size=.04")  # Creating storage on managed pool
vinst.add_invalid("remote", "--nodisks --location /tmp")  # Use of --location
vinst.add_invalid("remote", "--file %(EXISTIMG1)s --pxe")  # Trying to use unmanaged storage


vinst.add_category("network", "--pxe --nographics --noautoconsole --nodisks")
vinst.add_valid("network", "--mac 22:22:33:44:55:AF")  # Just a macaddr
vinst.add_valid("network", "--network=user")  # user networking
vinst.add_valid("network", "--bridge mybr0")  # Old bridge option
vinst.add_valid("network", "--bridge mybr0 --mac 22:22:33:44:55:AF")  # Old bridge w/ mac
vinst.add_valid("network", "--network bridge:mybr0,model=e1000")  # --network bridge:
vinst.add_valid("network", "--network network:default --mac RANDOM")  # VirtualNetwork with a random macaddr
vinst.add_valid("network", "--network network:default --mac 00:11:22:33:44:55")  # VirtualNetwork with a random macaddr
vinst.add_valid("network", "--network network=default,mac=22:00:11:00:11:00")  # Using '=' as the net type delimiter
vinst.add_valid("network", "--network=user,model=e1000")  # with NIC model
vinst.add_valid("network", "--network=network:default,model=e1000 --network=user,model=virtio,mac=22:22:33:44:55:AF")  # several networks
vinst.add_invalid("network", "--network=FOO")  # Nonexistent network
vinst.add_invalid("network", "--network=network:default --mac 1234")  # Invalid mac
vinst.add_invalid("network", "--network user --bridge foo0")  # Mixing bridge and network
vinst.add_invalid("network", "--mac 22:22:33:12:34:AB")  # Colliding macaddr


vinst.add_category("storage", "--pxe --nographics --noautoconsole --hvm")
vinst.add_valid("storage", "--file %(EXISTIMG1)s --nonsparse --file-size 4")  # Existing file, other opts
vinst.add_valid("storage", "--file %(EXISTIMG1)s")  # Existing file, no opts
vinst.add_valid("storage", "--file %(EXISTIMG1)s --file virt-image --file virt-clone")  # Multiple existing files
vinst.add_valid("storage", "--file %(NEWIMG1)s --file-size .00001 --nonsparse")  # Nonexistent file
vinst.add_valid("storage", "--disk path=%(EXISTIMG1)s,perms=ro,size=.0001,cache=writethrough,io=threads")  # Existing disk, lots of opts
vinst.add_valid("storage", "--disk path=%(EXISTIMG1)s,perms=rw")  # Existing disk, rw perms
vinst.add_valid("storage", "--disk path=%(EXISTIMG1)s,device=floppy")  # Existing floppy
vinst.add_valid("storage", "--disk path=%(EXISTIMG1)s")  # Existing disk, no extra options
vinst.add_valid("storage", "--disk pool=%(POOL)s,size=.0001 --disk pool=%(POOL)s,size=.0001")  # Create 2 volumes in a pool
vinst.add_valid("storage", "--disk vol=%(POOL)s/%(VOL)s")  # Existing volume
vinst.add_valid("storage", "--disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s,device=cdrom")  # 3 IDE and CD
vinst.add_valid("storage", " --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi")  # > 16 scsi disks
vinst.add_valid("storage", "--disk path=%(NEWIMG1)s,format=raw,size=.0000001")  # Unmanaged file using format 'raw'
vinst.add_valid("storage", "--disk path=%(MANAGEDNEW1)s,format=raw,size=.0000001")  # Managed file using format raw
vinst.add_valid("storage", "--disk path=%(MANAGEDNEW1)s,format=qcow2,size=.0000001")  # Managed file using format qcow2
vinst.add_valid("storage", "--disk path=%(ROIMG)s,perms=ro")  # Using ro path as a disk with readonly flag
vinst.add_valid("storage", "--disk path=%(ROIMG)s,device=cdrom")  # Using RO path with cdrom dev
vinst.add_valid("storage", "--disk %(EXISTIMG1)s")  # Not specifying path=
vinst.add_valid("storage", "--disk %(NEWIMG1)s,format=raw,size=.0000001")  # Not specifying path= but creating storage
vinst.add_valid("storage", "--disk %(COLLIDE)s --force")  # Colliding storage with --force
vinst.add_valid("storage", "--disk %(SHARE)s,perms=sh")  # Colliding shareable storage
vinst.add_valid("storage", "--disk path=%(EXISTIMG1)s,device=cdrom --disk path=%(EXISTIMG1)s,device=cdrom")  # Two IDE cds
vinst.add_valid("storage", "--disk %(DIR)s,device=floppy")  # Dir with a floppy dev
vinst.add_valid("storage", "--disk %(EXISTIMG1)s,driver_name=qemu,driver_type=qcow2")  # Driver name and type options
vinst.add_valid("storage", "--disk /dev/hda")  # Using a storage pool source as a disk
vinst.add_valid("storage", "--disk pool=default,size=.00001")  # Building 'default' pool
vinst.add_invalid("storage", "--file %(NEWIMG1)s --file-size 100000 --nonsparse")  # Nonexisting file, size too big
vinst.add_invalid("storage", "--file %(NEWIMG1)s --file-size 100000")  # Huge file, sparse, but no prompting
vinst.add_invalid("storage", "--file %(NEWIMG1)s")  # Nonexisting file, no size
vinst.add_invalid("storage", "--file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s")  # Too many IDE
vinst.add_invalid("storage", "--file-size .0001")  # Size, no file
vinst.add_invalid("storage", "--disk pool=foopool,size=.0001")  # Specify a nonexistent pool
vinst.add_invalid("storage", "--disk vol=%(POOL)s/foovol")  # Specify a nonexistent volume
vinst.add_invalid("storage", "--disk pool=%(POOL)s")  # Specify a pool with no size
vinst.add_invalid("storage", "--disk path=%(EXISTIMG1)s,perms=ro,size=.0001,cache=FOOBAR")  # Unknown cache type
vinst.add_invalid("storage", "--disk path=%(NEWIMG1)s,format=qcow2,size=.0000001")  # Unmanaged file using non-raw format
vinst.add_invalid("storage", "--disk path=%(MANAGEDNEW1)s,format=frob,size=.0000001")  # Managed file using unknown format
vinst.add_invalid("storage", "--disk path=%(MANAGEDDISKNEW1)s,format=raw,size=.0000001")  # Managed disk using any format
vinst.add_invalid("storage", "--disk %(NEWIMG1)s")  # Not specifying path= and non existent storage w/ no size
vinst.add_invalid("storage", "--disk %(COLLIDE)s")  # Colliding storage without --force
vinst.add_invalid("storage", "--disk %(DIR)s,device=cdrom")  # Dir without floppy
vinst.add_invalid("storage", "--disk %(EXISTIMG1)s,driver_name=foobar,driver_type=foobaz")  # Unknown driver name and type options (as of 1.0.0)


vinst.add_category("redirdev", "--noautoconsole --nographics --nodisks --pxe")
vinst.add_valid("redirdev", "--redirdev usb,type=spicevmc")
vinst.add_valid("redirdev", "--redirdev usb,type=tcp,server=localhost:4000")
vinst.add_valid("redirdev", "--redirdev usb,type=tcp,server=127.0.0.1:4002")  # Different host server
vinst.add_invalid("redirdev", "--redirdev")  # Missing argument
vinst.add_invalid("redirdev", "--redirdev pci")  # Unsupported bus
vinst.add_invalid("redirdev", "--redirdev usb,type=spicevmc,server=foo:12")  # Invalid argument


vinst.add_category("hostdev", "--noautoconsole --nographics --nodisks --pxe")
vinst.add_valid("hostdev", "--host-device usb_device_781_5151_2004453082054CA1BEEE")  # Host dev by libvirt name
vinst.add_valid("hostdev", "--host-device 001.003 --host-device 15:0.1 --host-device 2:15:0.2 --host-device 0:15:0.3 --host-device 0x0781:0x5151")  # Many hostdev parsing types
vinst.add_invalid("hostdev", "--host-device 1d6b:2")  # multiple USB devices with identical vendorId and productId
vinst.add_invalid("hostdev", "--host-device pci_8086_2850_scsi_host_scsi_host")  # Unsupported hostdev type
vinst.add_invalid("hostdev", "--host-device foobarhostdev")  # Unknown hostdev
vinst.add_invalid("hostdev", "--host-device 300:400")  # Parseable hostdev, but unknown digits


vinst.add_category("install", "--nographics --noautoconsole --nodisks")
vinst.add_valid("install", "--hvm --cdrom %(EXISTIMG1)s")  # Simple cdrom install
vinst.add_valid("install", "--hvm --cdrom %(MANAGEDEXIST1)s")  # Cdrom install with managed storage
vinst.add_valid("install", "--hvm --wait 0 --os-variant winxp --cdrom %(EXISTIMG1)s")  # Windows (2 stage) install
vinst.add_valid("install", "--hvm --pxe --virt-type test")  # Explicit virt-type
vinst.add_valid("install", "--arch i686 --pxe")  # Explicity fullvirt + arch
vinst.add_valid("install", "--arch i486 --pxe")  # Convert i*86 -> i686
vinst.add_valid("install", "--hvm --location %(TREEDIR)s")  # Directory tree URL install
vinst.add_valid("install", "--hvm --location %(TREEDIR)s --initrd-inject virt-install --extra-args ks=file:/virt-install")  # initrd-inject
vinst.add_valid("install", "--hvm --location %(TREEDIR)s --extra-args console=ttyS0")  # Directory tree URL install with extra-args
vinst.add_valid("install", "--hvm --cdrom %(TREEDIR)s")  # Directory tree CDROM install
vinst.add_valid("install", "--paravirt --location %(TREEDIR)s")  # Paravirt location
vinst.add_valid("install", "--hvm --cdrom %(ROIMG)s")  # Using ro path as a cd media
vinst.add_valid("install", "--paravirt --location %(TREEDIR)s --os-variant none")  # Paravirt location with --os-variant none
vinst.add_valid("install", "--hvm --location %(TREEDIR)s --os-variant fedora12")  # URL install with manual os-variant
vinst.add_valid("install", "--hvm --pxe --boot menu=on")  # Boot menu
vinst.add_valid("install", "--hvm --pxe --boot kernel=/tmp/foo1.img,initrd=/tmp/foo2.img,kernel_args='ro quiet console=/dev/ttyS0' ")  # Kernel params
vinst.add_valid("install", "--hvm --pxe --boot cdrom,fd,hd,network,menu=off")  # Boot order
vinst.add_valid("install", "--hvm --boot network,hd,menu=on")  # Boot w/o other install option
vinst.add_invalid("install", "--hvm --pxe --virt-type bogus")  # Bogus virt-type
vinst.add_invalid("install", "--hvm --pxe --arch bogus")  # Bogus arch
vinst.add_invalid("install", "--paravirt --pxe")  # PXE w/ paravirt
vinst.add_invalid("install", "--import")  # Import with no disks
vinst.add_invalid("install", "--livecd")  # LiveCD with no media
vinst.add_invalid("install", "--hvm --pxe --os-variant farrrrrrrge# Boot menu w/ bogus value ")  # Bogus --os-variant
vinst.add_invalid("install", "--hvm --pxe --boot menu=foobar")
vinst.add_invalid("install", "--hvm --cdrom %(EXISTIMG1)s --extra-args console=ttyS0")  # cdrom fail w/ extra-args
vinst.add_invalid("install", "--hvm --boot kernel=%(TREEDIR)s/pxeboot/vmlinuz,initrd=%(TREEDIR)s/pxeboot/initrd.img --initrd-inject virt-install")  # initrd-inject with manual kernel/initrd




vimag = App("virt-image")
vimag.add_category("graphics", "--name test-image --boot 0 %(IMAGE_XML)s")
vimag.add_valid("graphics", "--sdl")  # SDL
vimag.add_valid("graphics", "--vnc --keymap ja --vncport 5950 --vnclisten 1.2.3.4")  # VNC w/ lots of options


vimag.add_category("misc", "")
vimag.add_compare("misc", "--name foobar --ram 64 --os-variant winxp --boot 0 %(IMAGE_XML)s", "image-boot0")
vimag.add_compare("misc", "--name foobar --ram 64 --network user,model=e1000 --boot 1 %(IMAGE_XML)s", "image-boot1")
vimag.add_compare("misc", "--name foobar --ram 64 --boot 0 %(IMAGE_NOGFX_XML)s", "image-nogfx")
vimag.add_valid("misc", "--name test --replace %(IMAGE_XML)s")  # Colliding VM name w/ --replace
vimag.add_invalid("misc", "%(IMAGE_XML)s")  # No name specified, and no prompt flag
vimag.add_invalid("misc", "--name test %(IMAGE_XML)s")  # Colliding VM name without --replace


vimag.add_category("network", "--name test-image --boot 0 --nographics %(IMAGE_XML)s")
vimag.add_valid("network", "--network=user")  # user networking
vimag.add_valid("network", "--network network:default --mac RANDOM")  # VirtualNetwork with a random macaddr
vimag.add_valid("network", "--network network:default --mac 00:11:22:33:44:55")  # VirtualNetwork with a random macaddr
vimag.add_valid("network", "--network=user,model=e1000")  # with NIC model
vimag.add_valid("network", "--network=network:default,model=e1000 --network=user,model=virtio")  # several networks
vimag.add_invalid("network", "--network=FOO")  # Nonexistent network
vimag.add_invalid("network", "--network=network:default --mac 1234")  # Invalid mac


vimag.add_category("general", "--name test-image %(IMAGE_XML)s")
vimag.add_valid("general", "")  # All default values
vimag.add_valid("general", "--print")  # Print default
vimag.add_valid("general", "--boot 0")  # Manual boot idx 0
vimag.add_valid("general", "--boot 1")  # Manual boot idx 1
vimag.add_valid("general", "--name foobar --ram 64 --os-variant winxp")  # Lots of options
vimag.add_valid("general", "--name foobar --ram 64 --os-variant none")  # OS variant 'none'
vimag.add_invalid("general", "--boot 10")  # Out of bounds index




vconv = App("virt-convert")
vconv.add_category("misc", "")
vconv.add_compare("misc", "%(VC_IMG1)s %(VIRTCONV_OUT)s", "convert-default")  # virt-image to default (virt-image) w/ no convert
vconv.add_valid("misc", "%(VC_IMG1)s -D none %(VIRTCONV_OUT)s")  # virt-image to default (virt-image) w/ no convert
vconv.add_valid("misc", "%(VC_IMG1)s -o virt-image -D none %(VIRTCONV_OUT)s")  # virt-image to virt-image w/ no convert
vconv.add_valid("misc", "%(VC_IMG1)s -o vmx -D none %(VIRTCONV_OUT)s")  # virt-image to vmx w/ no convert
vconv.add_valid("misc", "%(VC_IMG1)s -o vmx -D raw %(VIRTCONV_OUT)s")  # virt-image to vmx w/ raw
vconv.add_valid("misc", "%(VC_IMG1)s -o vmx -D vmdk %(VIRTCONV_OUT)s")  # virt-image to vmx w/ vmdk
vconv.add_valid("misc", "%(VC_IMG1)s -o vmx -D qcow2 %(VIRTCONV_OUT)s")  # virt-image to vmx w/ qcow2
vconv.add_valid("misc", "%(VMX_IMG1)s -o vmx -D none %(VIRTCONV_OUT)s")  # vmx to vmx no convert
vconv.add_valid("misc", "%(VC_IMG2)s -o vmx -D vmdk %(VIRTCONV_OUT)s")  # virt-image with exotic formats specified
vconv.add_invalid("misc", "%(VC_IMG1)s -o virt-image -D foobarfmt %(VIRTCONV_OUT)s")  # virt-image to virt-image with invalid format
vconv.add_invalid("misc", "%(VC_IMG1)s -o ovf %(VIRTCONV_OUT)s")  # virt-image to ovf (has no output formatter)




vclon = App("virt-clone")
vclon.add_category("remote", "--connect %(REMOTEURI)s")
vclon.add_valid("remote", "-o test --auto-clone")  # Auto flag, no storage
vclon.add_valid("remote", "--original-xml %(CLONE_STORAGE_XML)s --auto-clone")  # Auto flag w/ managed storage,
vclon.add_invalid("remote", "--original-xml %(CLONE_DISK_XML)s --auto-clone")  # Auto flag w/ storage,


vclon.add_category("misc", "")
vclon.add_compare("misc", "--connect %(KVMURI)s -o test-for-clone --auto-clone --clone-running", "clone-auto1")
vclon.add_compare("misc", "-o test-clone-simple --name newvm --auto-clone --clone-running", "clone-auto2")
vclon.add_valid("misc", "-o test --auto-clone")  # Auto flag, no storage
vclon.add_valid("misc", "--original-xml %(CLONE_DISK_XML)s --auto-clone")  # Auto flag w/ storage,
vclon.add_valid("misc", "--original-xml %(CLONE_STORAGE_XML)s --auto-clone")  # Auto flag w/ managed storage,
vclon.add_valid("misc", "-o test-for-clone --auto-clone --clone-running")  # Auto flag, actual VM, skip state check
vclon.add_valid("misc", "-o test-clone-simple -n newvm --preserve-data --file /dev/default-pool/default-vol --clone-running --force")  # Preserve data shouldn't complain about existing volume
vclon.add_invalid("misc", "--auto-clone# Auto flag, actual VM, without state skip ")  # Just the auto flag
vclon.add_invalid("misc", "-o test-for-clone --auto-clone")


vclon.add_category("general", "-n clonetest")
vclon.add_valid("general", "-o test")  # Nodisk guest
vclon.add_valid("general", "-o test --file %(NEWIMG1)s --file %(NEWIMG2)s")  # Nodisk, but with spurious files passed
vclon.add_valid("general", "-o test --file %(NEWIMG1)s --file %(NEWIMG2)s --prompt")  # Working scenario w/ prompt shouldn't ask anything
vclon.add_valid("general", "--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s")  # XML File with 2 disks
vclon.add_valid("general", "--original-xml %(CLONE_DISK_XML)s --file virt-install --file %(EXISTIMG1)s --preserve")  # XML w/ disks, overwriting existing files with --preserve
vclon.add_valid("general", "--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s --file %(NEWIMG3)s --force-copy=hdc")  # XML w/ disks, force copy a readonly target
vclon.add_valid("general", "--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s --force-copy=fda")  # XML w/ disks, force copy a target with no media
vclon.add_valid("general", "--original-xml %(CLONE_STORAGE_XML)s --file %(MANAGEDNEW1)s")  # XML w/ managed storage, specify managed path
vclon.add_valid("general", "--original-xml %(CLONE_NOEXIST_XML)s --file %(EXISTIMG1)s --preserve")  # XML w/ managed storage, specify managed path across pools# Libvirt test driver doesn't support cloning across pools# XML w/ non-existent storage, with --preserve
vclon.add_valid("general", "-o test -n test-many-devices --replace")  # Overwriting existing VM
vclon.add_invalid("general", "-o test foobar")  # Positional arguments error
vclon.add_invalid("general", "-o idontexist")  # Non-existent vm name
vclon.add_invalid("general", "-o idontexist --auto-clone")  # Non-existent vm name with auto flag,
vclon.add_invalid("general", "-o test -n test")  # Colliding new name
vclon.add_invalid("general", "--original-xml %(CLONE_DISK_XML)s")  # XML file with several disks, but non specified
vclon.add_invalid("general", "--original-xml %(CLONE_DISK_XML)s --file virt-install --file %(EXISTIMG1)s")  # XML w/ disks, overwriting existing files with no --preserve
vclon.add_invalid("general", "--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s --force-copy=hdc")  # XML w/ disks, force copy but not enough disks passed
vclon.add_invalid("general", "--original-xml %(CLONE_STORAGE_XML)s --file /tmp/clonevol")  # XML w/ managed storage, specify unmanaged path (should fail)
vclon.add_invalid("general", "--original-xml %(CLONE_NOEXIST_XML)s --file %(EXISTIMG1)s")  # XML w/ non-existent storage, WITHOUT --preserve
vclon.add_invalid("general", "--original-xml %(CLONE_DISK_XML)s --file %(ROIMG)s --file %(ROIMG)s --force")  # XML w/ managed storage, specify RO image without preserve
vclon.add_invalid("general", "--original-xml %(CLONE_DISK_XML)s --file %(ROIMG)s --file %(ROIMGNOEXIST)s --force")  # XML w/ managed storage, specify RO non existent





##########################
# Automated prompt tests #
##########################

# Basic virt-install prompting
p1 = PromptTest("virt-install --connect %(TESTURI)s --prompt --quiet "
               "--noautoconsole")
p1.add("fully virtualized", "yes")
p1.add("What is the name", "foo")
p1.add("How much RAM", "64")
p1.add("use as the disk", "%(NEWIMG1)s")
p1.add("large would you like the disk", ".00001")
p1.add("CD-ROM/ISO or URL", "%(EXISTIMG1)s")
promptlist.append(p1)

# Basic virt-install kvm prompting, existing disk
p2 = PromptTest("virt-install --connect %(KVMURI)s --prompt --quiet "
               "--noautoconsole --name foo --ram 64 --pxe --hvm")
p2.add("use as the disk", "%(EXISTIMG1)s")
p2.add("overwrite the existing path")
p2.add("want to use this disk", "yes")
promptlist.append(p2)

# virt-install with install and --file-size and --hvm specified
p3 = PromptTest("virt-install --connect %(TESTURI)s --prompt --quiet "
               "--noautoconsole --pxe --file-size .00001 --hvm")
p3.add("What is the name", "foo")
p3.add("How much RAM", "64")
p3.add("enter the path to the file", "%(NEWIMG1)s")
promptlist.append(p3)

# Basic virt-image prompting
p4 = PromptTest("virt-image --connect %(TESTURI)s %(IMAGE_XML)s "
               "--prompt --quiet --noautoconsole")
# prompting for virt-image currently disabled
#promptlist.append(p4)

# Basic virt-clone prompting
p5 = PromptTest("virt-clone --connect %(TESTURI)s --prompt --quiet "
               "--clone-running")
p5.add("original virtual machine", "test-clone-simple")
p5.add("cloned virtual machine", "test-clone-new")
p5.add("use as the cloned disk", "%(MANAGEDNEW1)s")
promptlist.append(p5)

# virt-clone prompt with input XML
p6 = PromptTest("virt-clone --connect %(TESTURI)s --prompt --quiet "
               "--original-xml %(CLONE_DISK_XML)s --clone-running")
p6.add("cloned virtual machine", "test-clone-new")
p6.add("use as the cloned disk", "%(NEWIMG1)s")
p6.add("use as the cloned disk", "%(NEWIMG2)s")
promptlist.append(p6)

# Basic virt-clone prompting with disk failure handling
p7 = PromptTest("virt-clone --connect %(TESTURI)s --prompt --quiet "
               "--clone-running -o test-clone-simple -n test-clone-new")
p7.add("use as the cloned disk", "/root")
p7.add("'/root' must be a file or a device")
p7.add("use as the cloned disk", "%(MANAGEDNEW1)s")
promptlist.append(p7)



#########################
# Test runner functions #
#########################


def open_conn(uri):
    #if uri not in _conns:
    #    _conns[uri] = virtinst.cli.getConnection(uri)
    #return _conns[uri]
    return virtinst.cli.getConnection(uri)


newidx = 0
curtest = 0
old_bridge = virtinst.util.default_bridge


def setup():
    """
    Create initial test files/dirs
    """
    os.system("mkdir %s" % ro_dir)

    for i in exist_files:
        os.system("touch %s" % i)

    # Set ro_img to readonly
    os.system("chmod 444 %s" % ro_img)
    os.system("chmod 555 %s" % ro_dir)

    virtinst.util.default_bridge = lambda ignore: None


def cleanup():
    """
    Cleanup temporary files used for testing
    """
    for i in clean_files:
        os.system("chmod 777 %s > /dev/null 2>&1" % i)
        os.system("rm -rf %s > /dev/null 2>&1" % i)

    virtinst.util.default_bridge = old_bridge


class CLITests(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)

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
    def cmdtemplate(self, c):
        err = c.run()
        if err:
            self.fail(err)
    return lambda s: cmdtemplate(s, cmd)

_cmdlist = promptlist
_cmdlist += vinst.cmds
_cmdlist += vclon.cmds
_cmdlist += vimag.cmds
_cmdlist += vconv.cmds

for _cmd in _cmdlist:
    newidx += 1
    setattr(CLITests, "testCLI%d" % newidx, maketest(_cmd))

atexit.register(cleanup)

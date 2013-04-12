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

from tests.scriptimports import virtinstall, virtimage, virtclone, virtconvert
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
    'MANAGEDEXIST1'     : "/default-pool/testvol1.img",
    'MANAGEDEXIST2'     : "/default-pool/testvol2.img",
    'MANAGEDEXISTUPPER' : "/default-pool/UPPER",
    'MANAGEDNEW1'       : "/default-pool/clonevol",
    'MANAGEDNEW2'       : "/default-pool/clonevol",
    'MANAGEDDISKNEW1'   : "/disk-pool/newvol1.img",
    'COLLIDE'           : "/default-pool/collidevol1.img",
    'SHARE'             : "/default-pool/sharevol.img",

    'VIRTCONV_OUT'      : "%s/test.out" % virtconv_out,
    'VC_IMG1'           : "%s/virtimage/test1.virt-image" % vcdir,
    'VC_IMG2'           : "tests/image-xml/image-format.xml",
    'VMX_IMG1'          : "%s/vmx/test1.vmx" % vcdir,
}


# CLI test matrix
#
# Any global args for every invocation should be added to default_args
# function, so that individual tests can easily overwrite them.
#
# Format:
#
# "appname" {
#  "categoryfoo" : { Some descriptive test catagory name (e.g. storage)
#
#    "args" : Args to be applied to all invocations in category
#
#    "valid" : { # Argument strings that should succeed
#      "--option --string --number1" # Some option string to test. The
#          resulting cmdstr would be:
#          $ appname globalargs categoryfoo_args --option --string --number1
#    }
#
#    "invalid" : { # Argument strings that should fail
#      "--opt1 --opt2",
#    }
#  } # End categoryfoo
#
#}


def default_args(app, cli, testtype):
    args = ""
    iscompare = testtype in ["compare"]

    if not iscompare:
        args = "--debug"

    if app in ["virt-install", "virt-clone", "virt-image"] and not iscompare:
        if "--connect " not in cli:
            args += " --connect %(TESTURI)s"

    if app in ["virt-install"]:
        if "--name " not in cli:
            args += " --name foobar"
        if "--ram " not in cli:
            args += " --ram 64"

    if testtype in ["compare"]:
        if app == "virt-install":
            if (not cli.count("--print-xml") and
                not cli.count("--print-step") and
                not cli.count("--quiet")):
                args += " --print-step all"

        elif app == "virt-image":
            if not cli.count("--print"):
                args += " --print"

        elif app == "virt-clone":
            if not cli.count("--print-xml"):
                args += " --print-xml"

        if app != "virt-convert" and not "--connect " in cli:
            args += " --connect %s" % fakeuri

    return args

args_dict = {


  "virt-install" : {
    "storage" : {
      "args": "--pxe --nographics --noautoconsole --hvm",

      "valid"  : [
        # Existing file, other opts
        "--file %(EXISTIMG1)s --nonsparse --file-size 4",
        # Existing file, no opts
        "--file %(EXISTIMG1)s",
        # Multiple existing files
        "--file %(EXISTIMG1)s --file virt-image --file virt-clone",
        # Nonexistent file
        "--file %(NEWIMG1)s --file-size .00001 --nonsparse",

        # Existing disk, lots of opts
        "--disk path=%(EXISTIMG1)s,perms=ro,size=.0001,cache=writethrough,io=threads",
        # Existing disk, rw perms
        "--disk path=%(EXISTIMG1)s,perms=rw",
        # Existing floppy
        "--disk path=%(EXISTIMG1)s,device=floppy",
        # Existing disk, no extra options
        "--disk path=%(EXISTIMG1)s",
        # Create 2 volumes in a pool
        "--disk pool=%(POOL)s,size=.0001 --disk pool=%(POOL)s,size=.0001",
        # Existing volume
        "--disk vol=%(POOL)s/%(VOL)s",
        # 3 IDE and CD
        "--disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s,device=cdrom",
        # > 16 scsi disks
        " --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi",
        # Unmanaged file using format 'raw'
        "--disk path=%(NEWIMG1)s,format=raw,size=.0000001",
        # Managed file using format raw
        "--disk path=%(MANAGEDNEW1)s,format=raw,size=.0000001",
        # Managed file using format qcow2
        "--disk path=%(MANAGEDNEW1)s,format=qcow2,size=.0000001",
        # Using ro path as a disk with readonly flag
        "--disk path=%(ROIMG)s,perms=ro",
        # Using RO path with cdrom dev
        "--disk path=%(ROIMG)s,device=cdrom",
        # Not specifying path=
        "--disk %(EXISTIMG1)s",
        # Not specifying path= but creating storage
        "--disk %(NEWIMG1)s,format=raw,size=.0000001",
        # Colliding storage with --force
        "--disk %(COLLIDE)s --force",
        # Colliding shareable storage
        "--disk %(SHARE)s,perms=sh",
        # Two IDE cds
        "--disk path=%(EXISTIMG1)s,device=cdrom --disk path=%(EXISTIMG1)s,device=cdrom",
        # Dir with a floppy dev
        "--disk %(DIR)s,device=floppy",
        # Driver name and type options
        "--disk %(EXISTIMG1)s,driver_name=qemu,driver_type=qcow2",
        # Using a storage pool source as a disk
        "--disk /dev/hda",
        # Building 'default' pool
        "--disk pool=default,size=.00001",
      ],

      "invalid": [
        # Nonexisting file, size too big
        "--file %(NEWIMG1)s --file-size 100000 --nonsparse",
        # Huge file, sparse, but no prompting
        "--file %(NEWIMG1)s --file-size 100000",
        # Nonexisting file, no size
        "--file %(NEWIMG1)s",
        # Too many IDE
        "--file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s",
        # Size, no file
        "--file-size .0001",
        # Specify a nonexistent pool
        "--disk pool=foopool,size=.0001",
        # Specify a nonexistent volume
        "--disk vol=%(POOL)s/foovol",
        # Specify a pool with no size
        "--disk pool=%(POOL)s",
        # Unknown cache type
        "--disk path=%(EXISTIMG1)s,perms=ro,size=.0001,cache=FOOBAR",
        # Unmanaged file using non-raw format
        "--disk path=%(NEWIMG1)s,format=qcow2,size=.0000001",
        # Managed file using unknown format
        "--disk path=%(MANAGEDNEW1)s,format=frob,size=.0000001",
        # Managed disk using any format
        "--disk path=%(MANAGEDDISKNEW1)s,format=raw,size=.0000001",
        # Not specifying path= and non existent storage w/ no size
        "--disk %(NEWIMG1)s",
        # Colliding storage without --force
        "--disk %(COLLIDE)s",
        # Dir without floppy
        "--disk %(DIR)s,device=cdrom",
        # Unknown driver name and type options (as of 1.0.0)
        "--disk %(EXISTIMG1)s,driver_name=foobar,driver_type=foobaz",
      ]
     }, # category "storage"

     "install" : {
      "args": "--nographics --noautoconsole --nodisks",

      "valid" : [
        # Simple cdrom install
        "--hvm --cdrom %(EXISTIMG1)s",
        # Cdrom install with managed storage
        "--hvm --cdrom %(MANAGEDEXIST1)s",
        # Windows (2 stage) install
        "--hvm --wait 0 --os-variant winxp --cdrom %(EXISTIMG1)s",
        # Explicit virt-type
        "--hvm --pxe --virt-type test",
        # Explicity fullvirt + arch
        "--arch i686 --pxe",
        # Convert i*86 -> i686
        "--arch i486 --pxe",
        # Directory tree URL install
        "--hvm --location %(TREEDIR)s",
        # initrd-inject
        "--hvm --location %(TREEDIR)s --initrd-inject virt-install --extra-args ks=file:/virt-install",
        # Directory tree URL install with extra-args
        "--hvm --location %(TREEDIR)s --extra-args console=ttyS0",
        # Directory tree CDROM install
        "--hvm --cdrom %(TREEDIR)s",
        # Paravirt location
        "--paravirt --location %(TREEDIR)s",
        # Using ro path as a cd media
        "--hvm --cdrom %(ROIMG)s",
        # Paravirt location with --os-variant none
        "--paravirt --location %(TREEDIR)s --os-variant none",
        # URL install with manual os-variant
        "--hvm --location %(TREEDIR)s --os-variant fedora12",
        # Boot menu
        "--hvm --pxe --boot menu=on",
        # Kernel params
        """--hvm --pxe --boot kernel=/tmp/foo1.img,initrd=/tmp/foo2.img,kernel_args="ro quiet console=/dev/ttyS0" """,
        # Boot order
        "--hvm --pxe --boot cdrom,fd,hd,network,menu=off",
        # Boot w/o other install option
        "--hvm --boot network,hd,menu=on",
      ],

      "invalid": [
        # Bogus virt-type
        "--hvm --pxe --virt-type bogus",
        # Bogus arch
        "--hvm --pxe --arch bogus",
        # PXE w/ paravirt
        "--paravirt --pxe",
        # Import with no disks
        "--import",
        # LiveCD with no media
        "--livecd",
        # Bogus --os-variant
        "--hvm --pxe --os-variant farrrrrrrge"
        # Boot menu w/ bogus value
        "--hvm --pxe --boot menu=foobar",
        # cdrom fail w/ extra-args
        "--hvm --cdrom %(EXISTIMG1)s --extra-args console=ttyS0",
        # initrd-inject with manual kernel/initrd
        "--hvm --boot kernel=%(TREEDIR)s/pxeboot/vmlinuz,initrd=%(TREEDIR)s/pxeboot/initrd.img --initrd-inject virt-install",
      ],
     }, # category "install"

     "graphics": {
      "args": "--noautoconsole --nodisks --pxe",

      "valid": [
        # SDL
        "--sdl",
        # --graphics SDL
        "--graphics sdl",
        # --graphics none,
        "--graphics none",
        # VNC w/ lots of options
        "--vnc --keymap ja --vncport 5950 --vnclisten 1.2.3.4",
        # VNC w/ lots of options, new way
        "--graphics vnc,port=5950,listen=1.2.3.4,keymap=ja,password=foo",
        # SPICE w/ lots of options
        "--graphics spice,port=5950,tlsport=5950,listen=1.2.3.4,keymap=ja",
        # --video option
        "--vnc --video vga",
        # --video option
        "--graphics spice --video qxl",
        # --keymap local,
        "--vnc --keymap local",
        # --keymap none
        "--vnc --keymap none",
      ],

      "invalid": [
        # Invalid keymap
        "--vnc --keymap ZZZ",
        # Invalid port
        "--vnc --vncport -50",
        # Invalid port
        "--graphics spice,tlsport=-50",
        # Invalid --video
        "--vnc --video foobar",
        # --graphics bogus
        "--graphics vnc,foobar=baz",
        # mixing old and new
        "--graphics vnc --vnclisten 1.2.3.4",
      ],

     }, # category "graphics"

     "smartcard": {
      "args": "--noautoconsole --nodisks --pxe",

      "valid": [
        # --smartcard host
        "--smartcard host",
        # --smartcard none,
        "--smartcard none",
        # --smartcard mode with type
        "--smartcard passthrough,type=spicevmc",
        # --smartcard mode with type
        # XXX Requires implementing more opts
        #"--smartcard passthrough,type=tcp",
      ],

      "invalid": [
        # Missing argument
        "--smartcard",
        # Invalid argument
        "--smartcard foo",
        # Invalid type
        "--smartcard passthrough,type=foo",
        # --smartcard bogus
        "--smartcard host,foobar=baz",
      ],

     }, # category "smartcard"

    "char" : {
     "args": "--hvm --nographics --noautoconsole --nodisks --pxe",

     "valid": [
        # Simple devs
        "--serial pty --parallel null",
        # Some with options
        "--serial file,path=/tmp/foo --parallel unix,path=/tmp/foo --parallel null",
        # UDP
        "--parallel udp,host=0.0.0.0:1234,bind_host=127.0.0.1:1234",
        # TCP
        "--serial tcp,mode=bind,host=0.0.0.0:1234",
        # Unix
        "--parallel unix,path=/tmp/foo-socket",
        # TCP w/ telnet
        "--serial tcp,host=:1234,protocol=telnet",
        # --channel guestfwd
        "--channel pty,target_type=guestfwd,target_address=127.0.0.1:10000",
        # --channel virtio
        "--channel pty,target_type=virtio,name=org.linux-kvm.port1",
        # --channel virtio without name=
        "--channel pty,target_type=virtio",
        # --console virtio
        "--console pty,target_type=virtio",
        # --console xen
        "--console pty,target_type=xen",
     ],
     "invalid" : [
        # Bogus device type
        "--parallel foobah",
        # Unix with no path
        "--serial unix",
        # Path where it doesn't belong
        "--serial null,path=/tmp/foo",
        # Nonexistent argument
        "--serial udp,host=:1234,frob=baz",
        # --channel guestfwd without target_address
        "--channel pty,target_type=guestfwd",
        # --console unknown type
        "--console pty,target_type=abcd",
     ],

     }, # category 'char'

     "cpuram" : {
      "args" : "--hvm --nographics --noautoconsole --nodisks --pxe",

      "valid" : [
        # Max VCPUS
        "--vcpus 32",
        # Cpuset
        "--vcpus 4 --cpuset=1,3-5",
        # Cpuset with trailing comma
        "--vcpus 4 --cpuset=1,3-5,",
        # Cpuset with trailing comma
        "--vcpus 4 --cpuset=auto",
        # Ram overcommit
        "--ram 100000000000",
        # maxvcpus, --check-cpu shouldn't error
        "--vcpus 5,maxvcpus=10 --check-cpu",
        # Topology
        "--vcpus 4,cores=2,threads=2,sockets=2",
        # Topology auto-fill
        "--vcpus 4,cores=1",
        # Topology only
        "--vcpus sockets=2,threads=2",
        # Simple --cpu
        "--cpu somemodel",
        # Crazy --cpu
        "--cpu foobar,+x2apic,+x2apicagain,-distest,forbid=foo,forbid=bar,disable=distest2,optional=opttest,require=reqtest,match=strict,vendor=meee",
        # Simple --numatune
        "--numatune 1,2,3,5-7,^6",
      ],

      "invalid" : [
        # Bogus cpuset
        "--vcpus 32 --cpuset=969-1000",
        # Bogus cpuset
        "--vcpus 32 --cpuset=autofoo",
        # Over max vcpus
        "--vcpus 10000",
        # Over host vcpus w/ --check-cpu
        "--vcpus 20 --check-cpu",
        # maxvcpus less than cpus
        "--vcpus 5,maxvcpus=1",
        # vcpus unknown option
        "--vcpus foo=bar",
        # --cpu host, but no host CPU in caps
        "--cpu host",
        # Non-escaped numatune
        "--numatune 1-3,4,mode=strict",
      ],

    }, # category 'cpuram'

     "misc": {
      "args": "--nographics --noautoconsole",

      "valid": [
        # Specifying cdrom media via --disk
        "--hvm --disk path=virt-install,device=cdrom",
        # FV Import install
        "--hvm --import --disk path=virt-install",
        # Working scenario w/ prompt shouldn't ask anything
        "--hvm --import --disk path=virt-install --prompt --force",
        # PV Import install
        "--paravirt --import --disk path=virt-install",
        # PV Import install, print single XML
        "--paravirt --import --disk path=virt-install --print-xml",
        # Import a floppy disk
        "--hvm --import --disk path=virt-install,device=floppy",
        # --autostart flag
        "--hvm --nodisks --pxe --autostart",
        # --description
        "--hvm --nodisks --pxe --description \"foobar & baz\"",
        # HVM windows install with disk
        "--hvm --cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0",
        # HVM windows install, print 3rd stage XML
        "--hvm --cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --print-step 3",
        # --watchdog dev default
        "--hvm --nodisks --pxe --watchdog default",
        # --watchdog opts
        "--hvm --nodisks --pxe --watchdog ib700,action=pause",
        # --sound option
        "--hvm --nodisks --pxe --sound",
        # --soundhw option
        "--hvm --nodisks --pxe --soundhw default --soundhw ac97",
        # --security dynamic
        "--hvm --nodisks --pxe --security type=dynamic",
        # --security implicit static
        "--hvm --nodisks --pxe --security label=foobar.label,relabel=yes",
        # --security static with commas 1
        "--hvm --nodisks --pxe --security label=foobar.label,a1,z2,b3,type=static,relabel=no",
        # --security static with commas 2
        "--hvm --nodisks --pxe --security label=foobar.label,a1,z2,b3",
        # --filesystem simple
        "--hvm --pxe --filesystem /foo/source,/bar/target",
        # --filesystem template
        "--hvm --pxe --filesystem template_name,/,type=template",
        # no networks
        "--hvm --nodisks --nonetworks --cdrom %(EXISTIMG1)s",
        # --memballoon use virtio
        "--hvm --nodisks --pxe --memballoon virtio",
        # --memballoon disabled
        "--hvm --nodisks --pxe --memballoon none",
      ],

      "invalid": [
        # Positional arguments error
        "--hvm --nodisks --pxe foobar",
        # pxe and nonetworks
        "--nodisks --pxe --nonetworks",
        # Colliding name
        "--nodisks --pxe --name test",
        # Busted --watchdog
        "--hvm --nodisks --pxe --watchdog default,action=foobar",
        # Busted --soundhw
        "--hvm --nodisks --pxe --soundhw default --soundhw foobar",
        # Busted --security
        "--hvm --nodisks --pxe --security type=foobar",
        # PV Import install, no second XML step
        "--paravirt --import --disk path=virt-install --print-step 2",
        # 2 stage install with --print-xml
        "--hvm --nodisks --pxe --print-xml",
        # Busted --memballoon
        "--hvm --nodisks --pxe --memballoon foobar",
      ],

      "compare": [
        # No arguments
        ("", "noargs-fail"),
        # Diskless PXE install
        ("--hvm --nodisks --pxe --print-step all", "simple-pxe"),
        # HVM windows install with disk
        ("--hvm --cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --vcpus cores=4", "w2k3-cdrom"),
        # Lot's of devices
        ("--hvm --pxe "
         "--controller usb,model=ich9-ehci1,address=0:0:4.7,index=0 "
         "--controller usb,model=ich9-uhci1,address=0:0:4.0,index=0,master=0 "
         "--controller usb,model=ich9-uhci2,address=0:0:4.1,index=0,master=2 "
         "--controller usb,model=ich9-uhci3,address=0:0:4.2,index=0,master=4 "
         "--disk %(MANAGEDEXISTUPPER)s,cache=writeback,io=threads,perms=sh,serial=WD-WMAP9A966149 "
         "--disk %(NEWIMG1)s,sparse=false,size=.001,perms=ro,error_policy=enospace "
         "--disk device=cdrom,bus=sata "
         "--serial tcp,host=:2222,mode=bind,protocol=telnet "
         "--filesystem /source,/target,mode=squash "
         "--network user,mac=12:34:56:78:11:22 "
         "--network bridge=foobar,model=virtio "
         "--channel spicevmc "
         "--smartcard passthrough,type=spicevmc "
         "--security type=static,label='system_u:object_r:svirt_image_t:s0:c100,c200',relabel=yes "
         """ --numatune \\"1-3,5\\",mode=preferred """
         "--boot loader=/foo/bar ",
         "many-devices"),
        # --cpuset=auto actually works
        ("--connect %(DEFAULTURI)s --hvm --nodisks --pxe --cpuset auto "
         "--vcpus 2",
         "cpuset-auto"),
      ],

     }, # category "misc"

     "network": {
      "args": "--pxe --nographics --noautoconsole --nodisks",

      "valid": [
        # Just a macaddr
        "--mac 22:22:33:44:55:AF",
        # user networking
        "--network=user",
        # Old bridge option
        "--bridge mybr0",
        # Old bridge w/ mac
        "--bridge mybr0 --mac 22:22:33:44:55:AF",
        # --network bridge:
        "--network bridge:mybr0,model=e1000",
        # VirtualNetwork with a random macaddr
        "--network network:default --mac RANDOM",
        # VirtualNetwork with a random macaddr
        "--network network:default --mac 00:11:22:33:44:55",
        # Using '=' as the net type delimiter
        "--network network=default,mac=22:00:11:00:11:00",
        # with NIC model
        "--network=user,model=e1000",
        # several networks
        "--network=network:default,model=e1000 --network=user,model=virtio,mac=22:22:33:44:55:AF",
      ],
      "invalid": [
        # Nonexistent network
        "--network=FOO",
        # Invalid mac
        "--network=network:default --mac 1234",
        # Mixing bridge and network
        "--network user --bridge foo0",
        # Colliding macaddr
        "--mac 22:22:33:12:34:AB",
      ],

     }, # category "network"

     "controller": {
      "args": "--noautoconsole --nodisks --pxe",

      "valid": [
        "--controller usb,model=ich9-ehci1,address=0:0:4.7",
        "--controller usb,model=ich9-ehci1,address=0:0:4.7,index=0",
        "--controller usb,model=ich9-ehci1,address=0:0:4.7,index=1,master=0",
        "--controller usb2",
      ],

      "invalid": [
        # Missing argument
        "--controller",
        # Invalid argument
        "--controller foo",
        # Invalid values
        "--controller usb,model=ich9-ehci1,address=0:0:4.7,index=bar,master=foo",
        # --bogus
        "--controller host,foobar=baz",
      ],

     }, # category "controller"

     "hostdev" : {
      "args": "--noautoconsole --nographics --nodisks --pxe",

      "valid" : [
        # Host dev by libvirt name
        "--host-device usb_device_781_5151_2004453082054CA1BEEE",
        # Many hostdev parsing types
        "--host-device 001.003 --host-device 15:0.1 --host-device 2:15:0.2 --host-device 0:15:0.3 --host-device 0x0781:0x5151 --host-device 1d6b:2",
      ],

      "invalid" : [
        # Unsupported hostdev type
        "--host-device pci_8086_2850_scsi_host_scsi_host",
        # Unknown hostdev
        "--host-device foobarhostdev",
        # Parseable hostdev, but unknown digits
        "--host-device 300:400",
      ],
     }, # category "hostdev"

     "redirdev" : {
      "args": "--noautoconsole --nographics --nodisks --pxe",

      "valid" : [
        "--redirdev usb,type=spicevmc",
        "--redirdev usb,type=tcp,server=localhost:4000",
        # Different host server
        "--redirdev usb,type=tcp,server=127.0.0.1:4002",
      ],

      "invalid" : [
        # Missing argument
        "--redirdev",
        # Unsupported bus
        "--redirdev pci",
        # Invalid argument
        "--redirdev usb,type=spicevmc,server=foo:12",
        # Missing argument
        "--redirdev usb,type=tcp,server=",
        # Invalid address
        "--redirdev usb,type=tcp,server=localhost:p4000",
        # Missing address
        "--redirdev usb,type=tcp,server=localhost:",
        # Missing host
        "--redirdev usb,type=tcp,server=:399",
      ],
     }, # category "redirdev"

     "remote" : {
      "args": "--connect %(REMOTEURI)s --nographics --noautoconsole",

      "valid" : [
        # Simple pxe nodisks
        "--nodisks --pxe",
        # Managed CDROM install
        "--nodisks --cdrom %(MANAGEDEXIST1)s",
        # Using existing managed storage
        "--pxe --file %(MANAGEDEXIST1)s",
        # Using existing managed storage 2
        "--pxe --disk vol=%(POOL)s/%(VOL)s",
        # Creating storage on managed pool
        "--pxe --disk pool=%(POOL)s,size=.04",
      ],
      "invalid": [
        # Use of --location
        "--nodisks --location /tmp",
        # Trying to use unmanaged storage
        "--file %(EXISTIMG1)s --pxe",
      ],

     }, # category "remote"


"kvm" : {
  "args": "--connect %(KVMURI)s --noautoconsole",

  "valid" : [
    # HVM windows install with disk
    "--cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --sound",
    # F14 Directory tree URL install with extra-args
    "--os-variant fedora14 --file %(EXISTIMG1)s --location %(TREEDIR)s --extra-args console=ttyS0 --sound"
  ],

  "invalid" : [
    # Unknown machine type
    "--nodisks --boot network --machine foobar",
    # Invalid domain type for arch
    "--nodisks --boot network --arch mips --virt-type kvm",
    # Invalid arch/virt combo
    "--nodisks --boot network --paravirt --arch mips",
  ],

  "compare" : [
    # F14 Directory tree URL install with extra-args
    ("--os-variant fedora14 --file %(EXISTIMG1)s --location %(TREEDIR)s --extra-args console=ttyS0 --cpu host", "kvm-f14-url"),
    # Quiet URL install should make no noise
    ("--os-variant fedora14 --disk %(NEWIMG1)s,size=.01 --location %(TREEDIR)s --extra-args console=ttyS0 --quiet", "quiet-url"),
    # HVM windows install with disk
    ("--cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --sound", "kvm-win2k3-cdrom"),

    # xenner
    ("--os-variant fedora14 --nodisks --boot hd --paravirt", "kvm-xenner"),
    # plain qemu
    ("--os-variant fedora14 --nodisks --boot cdrom --virt-type qemu "
     "--cpu Penryn",
     "qemu-plain"),
    # 32 on 64
    ("--os-variant fedora14 --nodisks --boot network --nographics --arch i686",
     "qemu-32-on-64"),
    # kvm machine type 'pc'
    ("--os-variant fedora14 --nodisks --boot fd --graphics spice --machine pc", "kvm-machine"),
    # exotic arch + machine type
    ("--os-variant fedora14 --nodisks --boot fd --graphics sdl --arch sparc --machine SS-20",
     "qemu-sparc"),
  ],

}, # category "kvm"

"xen" : {
  "args": "--connect %(XENURI)s --noautoconsole",

  "valid"   : [
    # HVM
    "--nodisks --cdrom %(EXISTIMG1)s --livecd --hvm",
    # PV
    "--nodisks --boot hd --paravirt",
    # 32 on 64 xen
    "--nodisks --boot hd --paravirt --arch i686",
  ],

  "invalid" : [
  ],

  "compare" : [
    # Xen default
    ("--disk %(EXISTIMG1)s --import", "xen-default"),
    # Xen PV
    ("--disk %(EXISTIMG1)s --location %(TREEDIR)s --paravirt", "xen-pv"),
    # Xen HVM
    ("--disk %(EXISTIMG1)s --cdrom %(EXISTIMG1)s --livecd --hvm", "xen-hvm"),
    # ia64 default
    ("--connect %(XENIA64URI)s --disk %(EXISTIMG1)s --import",
     "xen-ia64-default"),
    # ia64 pv
    ("--connect %(XENIA64URI)s --disk %(EXISTIMG1)s --location %(TREEDIR)s --paravirt", "xen-ia64-pv"),
    # ia64 hvm
    ("--connect %(XENIA64URI)s --disk %(EXISTIMG1)s --location %(TREEDIR)s --hvm", "xen-ia64-hvm"),
  ],

},

"lxc" : {
  "args": "--connect %(LXCURI)s --noautoconsole --name foolxc --ram 64",

  "valid" : [],
  "invalid" : [],

  "compare" : [
    ("", "default"),
    ("--filesystem /source,/", "fs-default"),
    ("--init /usr/bin/httpd", "manual-init"),
  ],

}, # lxc

}, # virt-install




  "virt-clone": {
    "general" : {
      "args": "-n clonetest",

      "valid"  : [
        # Nodisk guest
        "-o test",
        # Nodisk, but with spurious files passed
        "-o test --file %(NEWIMG1)s --file %(NEWIMG2)s",
        # Working scenario w/ prompt shouldn't ask anything
        "-o test --file %(NEWIMG1)s --file %(NEWIMG2)s --prompt",

        # XML File with 2 disks
        "--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s",
        # XML w/ disks, overwriting existing files with --preserve
        "--original-xml %(CLONE_DISK_XML)s --file virt-install --file %(EXISTIMG1)s --preserve",
        # XML w/ disks, force copy a readonly target
        "--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s --file %(NEWIMG3)s --force-copy=hdc",
        # XML w/ disks, force copy a target with no media
        "--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s --force-copy=fda",
        # XML w/ managed storage, specify managed path
        "--original-xml %(CLONE_STORAGE_XML)s --file %(MANAGEDNEW1)s",
        # XML w/ managed storage, specify managed path across pools
        # XXX: Libvirt test driver doesn't support cloning across pools
        #"--original-xml %(CLONE_STORAGE_XML)s --file /cross-pool/clonevol",
        # XML w/ non-existent storage, with --preserve
        "--original-xml %(CLONE_NOEXIST_XML)s --file %(EXISTIMG1)s --preserve",
        # Overwriting existing VM
        "-o test -n test-many-devices --replace",
      ],

      "invalid": [
        # Positional arguments error
        "-o test foobar",
        # Non-existent vm name
        "-o idontexist",
        # Non-existent vm name with auto flag,
        "-o idontexist --auto-clone",
        # Colliding new name
        "-o test -n test",
        # XML file with several disks, but non specified
        "--original-xml %(CLONE_DISK_XML)s",
        # XML w/ disks, overwriting existing files with no --preserve
        "--original-xml %(CLONE_DISK_XML)s --file virt-install --file %(EXISTIMG1)s",
        # XML w/ disks, force copy but not enough disks passed
        "--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s --force-copy=hdc",
        # XML w/ managed storage, specify unmanaged path (should fail)
        "--original-xml %(CLONE_STORAGE_XML)s --file /tmp/clonevol",
        # XML w/ non-existent storage, WITHOUT --preserve
        "--original-xml %(CLONE_NOEXIST_XML)s --file %(EXISTIMG1)s",
        # XML w/ managed storage, specify RO image without preserve
        "--original-xml %(CLONE_DISK_XML)s --file %(ROIMG)s --file %(ROIMG)s --force",
        # XML w/ managed storage, specify RO non existent
        "--original-xml %(CLONE_DISK_XML)s --file %(ROIMG)s --file %(ROIMGNOEXIST)s --force",
      ]
     }, # category "general"

    "misc" : {
      "args": "",

      "valid" : [
        # Auto flag, no storage
        "-o test --auto-clone",
        # Auto flag w/ storage,
        "--original-xml %(CLONE_DISK_XML)s --auto-clone",
        # Auto flag w/ managed storage,
        "--original-xml %(CLONE_STORAGE_XML)s --auto-clone",
        # Auto flag, actual VM, skip state check
        "-o test-for-clone --auto-clone --clone-running",
      ],

      "invalid" : [
        # Just the auto flag
        "--auto-clone"
        # Auto flag, actual VM, without state skip
        "-o test-for-clone --auto-clone",
      ],

      "compare" : [
        ("--connect %(KVMURI)s -o test-for-clone --auto-clone --clone-running", "clone-auto1"),
        ("-o test-clone-simple --name newvm --auto-clone --clone-running",
         "clone-auto2"),
      ],
    }, # category "misc"

     "remote" : {
      "args": "--connect %(REMOTEURI)s",

      "valid"  : [
        # Auto flag, no storage
        "-o test --auto-clone",
        # Auto flag w/ managed storage,
        "--original-xml %(CLONE_STORAGE_XML)s --auto-clone",
      ],
      "invalid": [
        # Auto flag w/ storage,
        "--original-xml %(CLONE_DISK_XML)s --auto-clone",
      ],
    }, # categort "remote"


}, # app 'virt-clone'




  'virt-image': {
    "general" : {
      "args" : "--name test-image %(IMAGE_XML)s",

      "valid": [
        # All default values
        "",
        # Print default
        "--print",
        # Manual boot idx 0
        "--boot 0",
        # Manual boot idx 1
        "--boot 1",
        # Lots of options
        "--name foobar --ram 64 --os-variant winxp",
        # OS variant 'none'
        "--name foobar --ram 64 --os-variant none",
      ],

      "invalid": [
        # Out of bounds index
        "--boot 10",
      ],
     }, # category 'general'

    "graphics" : {
      "args" : "--name test-image --boot 0 %(IMAGE_XML)s",

      "valid": [
        # SDL
        "--sdl",
        # VNC w/ lots of options
        "--vnc --keymap ja --vncport 5950 --vnclisten 1.2.3.4",
      ],

      "invalid": [],
    },

    "misc": {
     "args" : "",

      "valid" : [
        # Colliding VM name w/ --replace
        "--name test --replace %(IMAGE_XML)s",
      ],
      "invalid" : [
        # No name specified, and no prompt flag
        "%(IMAGE_XML)s",
        # Colliding VM name without --replace
        "--name test %(IMAGE_XML)s",
      ],

      "compare" : [
        ("--name foobar --ram 64 --os-variant winxp --boot 0 %(IMAGE_XML)s",
         "image-boot0"),
        ("--name foobar --ram 64 --network user,model=e1000 --boot 1 "
         "%(IMAGE_XML)s",
         "image-boot1"),
        ("--name foobar --ram 64 --boot 0 "
         "%(IMAGE_NOGFX_XML)s",
         "image-nogfx"),
      ]

     }, # category 'misc'

     "network": {
      "args": "--name test-image --boot 0 --nographics %(IMAGE_XML)s",

      "valid": [
        # user networking
        "--network=user",
        # VirtualNetwork with a random macaddr
        "--network network:default --mac RANDOM",
        # VirtualNetwork with a random macaddr
        "--network network:default --mac 00:11:22:33:44:55",
        # with NIC model
        "--network=user,model=e1000",
        # several networks
        "--network=network:default,model=e1000 --network=user,model=virtio",
      ],
      "invalid": [
        # Nonexistent network
        "--network=FOO",
        # Invalid mac
        "--network=network:default --mac 1234",
      ],

     }, # category "network"


  }, # app 'virt-image'


  "virt-convert" : {
    "misc" : {
     "args": "",

     "valid": [
        # virt-image to default (virt-image) w/ no convert
        "%(VC_IMG1)s -D none %(VIRTCONV_OUT)s",
        # virt-image to virt-image w/ no convert
        "%(VC_IMG1)s -o virt-image -D none %(VIRTCONV_OUT)s",
        # virt-image to vmx w/ no convert
        "%(VC_IMG1)s -o vmx -D none %(VIRTCONV_OUT)s",
        # virt-image to vmx w/ raw
        "%(VC_IMG1)s -o vmx -D raw %(VIRTCONV_OUT)s",
        # virt-image to vmx w/ vmdk
        "%(VC_IMG1)s -o vmx -D vmdk %(VIRTCONV_OUT)s",
        # virt-image to vmx w/ qcow2
        "%(VC_IMG1)s -o vmx -D qcow2 %(VIRTCONV_OUT)s",
        # vmx to vmx no convert
        "%(VMX_IMG1)s -o vmx -D none %(VIRTCONV_OUT)s",
        # virt-image with exotic formats specified
        "%(VC_IMG2)s -o vmx -D vmdk %(VIRTCONV_OUT)s"
     ],

     "invalid": [
        # virt-image to virt-image with invalid format
        "%(VC_IMG1)s -o virt-image -D foobarfmt %(VIRTCONV_OUT)s",
        # virt-image to ovf (has no output formatter)
        "%(VC_IMG1)s -o ovf %(VIRTCONV_OUT)s",
     ],

     "compare": [
        # virt-image to default (virt-image) w/ no convert
        ("%(VC_IMG1)s %(VIRTCONV_OUT)s", "convert-default"),
     ],
    }, # category 'misc'

  }, # app 'virt-convert'
}

_conns = {}
def open_conn(uri):
    #if uri not in _conns:
    #    _conns[uri] = virtinst.cli.getConnection(uri)
    #return _conns[uri]
    return virtinst.cli.getConnection(uri)

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

def build_cmd_list():
    cmdlist = promptlist

    for app in args_dict:
        unique = {}

        # Build default command line dict
        for option in args_dict.get(app):
            # Default is a unique cmd string
            unique[option] = args_dict[app][option]

        # Build up unique command line cases
        for category in unique.keys():
            catdict = unique[category]
            category_args = catdict["args"]

            for testtype in ["valid", "invalid", "compare"]:
                for optstr in catdict.get(testtype) or []:
                    if testtype == "compare":
                        optstr, filename = optstr
                        filename = "%s/%s.xml" % (compare_xmldir, filename)

                    args = category_args + " " + optstr
                    args = default_args(app, args, testtype) + " " + args
                    cmdstr = "./%s %s" % (app, args)

                    cmd = Command(cmdstr)
                    if testtype == "compare":
                        cmd.check_success = not filename.endswith("fail.xml")
                        cmd.compare_file = filename
                    else:
                        cmd.check_success = bool(testtype == "valid")

                    cmdlist.append(cmd)

    return cmdlist

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

_cmdlist = build_cmd_list()
for _cmd in _cmdlist:
    newidx += 1
    setattr(CLITests, "testCLI%d" % newidx, maketest(_cmd))

atexit.register(cleanup)

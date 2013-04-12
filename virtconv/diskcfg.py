#
# Copyright 2013 Red Hat, Inc.
# Copyright 2008 Sun Microsystems, Inc.  All rights reserved.
# Use is subject to license terms.
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
#

import subprocess
import shutil
import errno
import sys
import os
import re
import logging


DISK_FORMAT_NONE = 0
DISK_FORMAT_RAW = 1
DISK_FORMAT_VMDK = 2
DISK_FORMAT_VDISK = 3
DISK_FORMAT_QCOW = 4
DISK_FORMAT_QCOW2 = 5
DISK_FORMAT_COW = 6
DISK_FORMAT_VDI = 7

DISK_TYPE_DISK = 0
DISK_TYPE_CDROM = 1
DISK_TYPE_ISO = 2

CSUM_SHA1 = 0
CSUM_SHA256 = 1

disk_suffixes = {
    DISK_FORMAT_RAW: ".raw",
    DISK_FORMAT_VMDK: ".vmdk",
    DISK_FORMAT_VDISK: ".vdisk",
    DISK_FORMAT_QCOW: ".qcow",
    DISK_FORMAT_QCOW2: ".qcow2",
    DISK_FORMAT_COW: ".cow",
    DISK_FORMAT_VDI: ".vdi",
}

qemu_formats = {
    DISK_FORMAT_RAW: "raw",
    DISK_FORMAT_VMDK: "vmdk",
    DISK_FORMAT_VDISK: "vdisk",
    DISK_FORMAT_QCOW: "qcow",
    DISK_FORMAT_QCOW2: "qcow2",
    DISK_FORMAT_COW: "cow",
    DISK_FORMAT_VDI: "vdi",
}

disk_format_names = {
    "none": DISK_FORMAT_NONE,
    "raw": DISK_FORMAT_RAW,
    "vmdk": DISK_FORMAT_VMDK,
    "vdisk": DISK_FORMAT_VDISK,
    "qcow": DISK_FORMAT_QCOW,
    "qcow2": DISK_FORMAT_QCOW2,
    "cow": DISK_FORMAT_COW,
    "vdi": DISK_FORMAT_VDI,
}

checksum_types = {
    CSUM_SHA1 : "sha1",
    CSUM_SHA256 : "sha256",
}

def ensuredirs(path):
    """
    Make sure that all the containing directories of the given file
    path exist.
    """
    try:
        os.makedirs(os.path.dirname(path))
    except OSError, e:
        if e.errno != errno.EEXIST:
            raise

def run_cmd(cmd):
    """
    Return the exit status and output to stdout and stderr.
    """
    logging.debug("Running command: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            close_fds=True)
    ret = proc.wait()
    return ret, proc.stdout.readlines(), proc.stderr.readlines()

def run_vdiskadm(args):
    """Run vdiskadm, returning the output."""
    ret, stdout, stderr = run_cmd([ "/usr/sbin/vdiskadm" ] + args)

    if ret != 0:
        raise RuntimeError("Disk conversion failed with "
            "exit status %d: %s" % (ret, "".join(stderr)))
    if len(stderr):
        print >> sys.stderr, stderr

    return stdout

class disk(object):
    """Definition of an individual disk instance."""

    def __init__(self, path=None, fmt=DISK_FORMAT_NONE, bus="ide",
                 typ=DISK_TYPE_DISK):
        self.path = path
        self.format = fmt
        self.bus = bus
        self.type = typ
        self.clean = []
        self.csum_dict = {}

    def cleanup(self):
        """
        Remove any generated output.
        """

        for path in self.clean:
            if os.path.isfile(path):
                os.remove(path)
            if os.path.isdir(path):
                os.removedirs(path)

        self.clean = []

    def copy_file(self, infile, outfile):
        """Copy an individual file."""
        self.clean += [ outfile ]
        ensuredirs(outfile)
        shutil.copy(infile, outfile)

    def out_file(self, out_format):
        """Return the relative path of the output file."""
        if not out_format:
            return self.path

        relout = self.path.replace(disk_suffixes[self.format],
                                   disk_suffixes[out_format])
        return re.sub(r'\s', '_', relout)

    def vdisk_convert(self, absin, absout):
        """
        Import the given disk into vdisk, including any sub-files as
        necessary.
        """

        stdout = run_vdiskadm([ "import", "-fnp", absin, absout ])

        for item in stdout:
            ignore, path = item.strip().split(':', 1)
            self.clean += [ os.path.join(absout, path) ]

        run_vdiskadm([ "import", "-fp", absin, absout ])

    def qemu_convert(self, absin, absout, out_format):
        """
        Use qemu-img to convert the given disk.  Note that at least some
        version of qemu-img cannot handle multi-file VMDKs, so this can
        easily go wrong.
        Gentoo, Debian, and Ubuntu (potentially others) install kvm-img
        with kvm and qemu-img with qemu. Both would work.
        """

        self.clean += [ absout ]

        ret, ignore, stderr = run_cmd(["qemu-img", "convert", "-O",
            qemu_formats[out_format], absin, absout])
        if ret == 127:
            ret, ignore, stderr = run_cmd(["kvm-img", "convert", "-O",
                qemu_formats[out_format], absin, absout])
        if ret != 0:
            raise RuntimeError("Disk conversion failed with "
                "exit status %d: %s" % (ret, "".join(stderr)))
        if len(stderr):
            print >> sys.stderr, stderr

    def copy(self, indir, outdir, out_format):
        """
        If needed, copy top-level disk files to outdir.  If the copy is
        done, then self.path is updated as needed.

        Returns (input_in_outdir, need_conversion)
        """

        need_conversion = (out_format != DISK_FORMAT_NONE and
            self.format != out_format)

        if os.path.isabs(self.path):
            return True, need_conversion

        relin = self.path
        absin = os.path.join(indir, relin)
        relout = self.out_file(self.format)
        absout = os.path.join(outdir, relout)

        #
        # If we're going to use vdiskadm, it's much smarter; don't
        # attempt any copies.
        #
        if out_format == DISK_FORMAT_VDISK:
            return False, True

        #
        # If we're using the same directory, just account for any spaces
        # in the disk filename and we're done.
        #
        if indir == outdir:
            if relin != relout:
                # vdisks cannot have spaces
                if self.format == DISK_FORMAT_VDISK:
                    raise RuntimeError("Disk conversion failed: "
                        "invalid vdisk '%s'" % self.path)
                self.clean += [ absout ]
                self.copy_file(absin, absout)
                self.path = relout
            return True, need_conversion

        #
        # If we're not performing any conversion, just copy the file.
        # XXX: This can go wrong for multi-part disks!
        #
        if not need_conversion:
            self.clean += [ absout ]
            self.copy_file(absin, absout)
            self.path = relout
            return True, False

        #
        # We're doing a conversion step, so we can rely upon convert()
        # to place something in outdir.
        #
        return False, True

    def convert(self, indir, outdir, output_format):
        """
        Convert a disk into the requested format if possible, in the
        given output directory.  Raises RuntimeError or other failures.
        """

        if self.type != DISK_TYPE_DISK:
            return

        out_format = disk_format_names[output_format]

        if not (out_format == DISK_FORMAT_NONE or
            out_format == DISK_FORMAT_VDISK or
            out_format == DISK_FORMAT_RAW or
            out_format == DISK_FORMAT_VMDK or
            out_format == DISK_FORMAT_QCOW or
            out_format == DISK_FORMAT_QCOW2 or
            out_format == DISK_FORMAT_COW):
            raise NotImplementedError(_("Cannot convert to disk format %s") %
                output_format)

        indir = os.path.normpath(os.path.abspath(indir))
        outdir = os.path.normpath(os.path.abspath(outdir))

        input_in_outdir, need_conversion = self.copy(indir, outdir, out_format)

        if not need_conversion:
            assert(input_in_outdir)
            return

        if os.path.isabs(self.path):
            raise NotImplementedError(_("Cannot convert disk with absolute"
                " path %s") % self.path)

        if input_in_outdir:
            indir = outdir

        relin = self.path
        absin = os.path.join(indir, relin)
        relout = self.out_file(out_format)
        absout = os.path.join(outdir, relout)

        ensuredirs(absout)

        if os.getenv("VIRTCONV_TEST_NO_DISK_CONVERSION"):
            self.format = out_format
            self.path = self.out_file(self.format)
            return

        if out_format == DISK_FORMAT_VDISK:
            self.vdisk_convert(absin, absout)
        else:
            self.qemu_convert(absin, absout, out_format)

        self.format = out_format
        self.path = relout

def disk_formats():
    """
    Return a list of supported disk formats.
    """
    return disk_format_names.keys()

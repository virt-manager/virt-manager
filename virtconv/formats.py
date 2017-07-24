# Copyright (C) 2013 Red Hat, Inc.
#
# Copyright 2008 Sun Microsystems, Inc.  All rights reserved.
# Use is subject to license terms.
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
#

from __future__ import print_function

from distutils.spawn import find_executable
import logging
import os
import re
import shutil
import subprocess
import tempfile

from virtinst import StoragePool


class parser_class(object):
    """
    Base class for particular config file format definitions of
    a VM instance.

    Warning: this interface is not (yet) considered stable and may
    change at will.
    """
    @staticmethod
    def identify_file(input_file):
        """
        Return True if the given file is of this format.
        """
        raise NotImplementedError

    @staticmethod
    def export_libvirt(conn, input_file):
        """
        Import a configuration file and turn it into a libvirt Guest object
        """
        raise NotImplementedError


def _get_parsers():
    from .vmx import vmx_parser
    from .ovf import ovf_parser
    return [vmx_parser, ovf_parser]


def _is_test():
    return bool(os.getenv("VIRTINST_TEST_SUITE"))


def _find_parser_by_name(input_name):
    """
    Return the parser of the given name.
    """
    parsers = [p for p in _get_parsers() if p.name == input_name]
    if len(parsers):
        return parsers[0]
    raise RuntimeError(_("No parser found for type '%s'") % input_name)


def _find_parser_by_file(input_file):
    """
    Return the parser that is capable of comprehending the given file.
    """
    for p in _get_parsers():
        if p.identify_file(input_file):
            return p
    raise RuntimeError(_("Don't know how to parse file %s") % input_file)


def _run_cmd(cmd):
    """
    Return the exit status and output to stdout and stderr.
    """
    logging.debug("Running command: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            close_fds=True)
    stdout, stderr = proc.communicate()
    ret = proc.wait()

    logging.debug("stdout=%s", stdout)
    logging.debug("stderr=%s", stderr)

    if ret == 0:
        return

    out = stdout
    if stderr:
        if out:
            out += "\n"
        out += stderr
    raise RuntimeError("%s: failed with exit status %d: %s" %
        (" ".join(cmd), ret, out))


def _find_input(input_file, parser, print_cb):
    """
    Given the input file, determine if its a directory, archive, etc
    """
    force_clean = []

    try:
        ext = os.path.splitext(input_file)[1]
        tempdir = None
        binname = None
        pkg = None
        if ext and ext[1:] in ["zip", "gz", "ova",
                "tar", "bz2", "bzip2", "7z", "xz"]:
            basedir = "/var/tmp"
            if _is_test():
                tempdir = os.path.join(basedir, "virt-convert-tmp")
            else:
                tempdir = tempfile.mkdtemp(
                    prefix="virt-convert-tmp", dir=basedir)

            base = os.path.basename(input_file)

            if (ext[1:] == "zip"):
                binname = "unzip"
                pkg = "unzip"
                cmd = ["unzip", "-o", "-d", tempdir, input_file]
            elif (ext[1:] == "7z"):
                binname = "7z"
                pkg = "p7zip"
                cmd = ["7z", "-o" + tempdir, "e", input_file]
            elif (ext[1:] == "ova" or ext[1:] == "tar"):
                binname = "tar"
                pkg = "tar"
                cmd = ["tar", "xf", input_file, "-C", tempdir]
            elif (ext[1:] == "gz"):
                binname = "gzip"
                pkg = "gzip"
                cmd = ["tar", "zxf", input_file, "-C", tempdir]
            elif (ext[1:] == "bz2" or ext[1:] == "bzip2"):
                binname = "bzip2"
                pkg = "bzip2"
                cmd = ["tar", "jxf", input_file, "-C", tempdir]
            elif (ext[1:] == "xz"):
                binname = "xz"
                pkg = "xz"
                cmd = ["tar", "Jxf", input_file, "-C", tempdir]
            if not find_executable(binname):
                raise RuntimeError(_("%s appears to be an archive, "
                    "but '%s' is not installed. "
                    "Please either install '%s', or extract the archive "
                    "yourself and point virt-convert at "
                    "the extracted directory.") % (base, pkg, pkg))

            print_cb(_("%s appears to be an archive, running: %s") %
                (base, " ".join(cmd)))

            _run_cmd(cmd)
            force_clean.append(tempdir)
            input_file = tempdir

        if not os.path.isdir(input_file):
            if not parser:
                parser = _find_parser_by_file(input_file)
            return input_file, parser, force_clean

        parsers = parser and [parser] or _get_parsers()
        for root, ignore, files in os.walk(input_file):
            for p in parsers:
                for f in [f for f in files if f.endswith(p.suffix)]:
                    path = os.path.join(root, f)
                    if p.identify_file(path):
                        return path, p, force_clean

        raise RuntimeError("Could not find parser for file %s" % input_file)
    except Exception:
        for f in force_clean:
            shutil.rmtree(f)
        raise


class VirtConverter(object):
    """
    Public interface for actually performing the conversion
    """
    def __init__(self, conn, input_file, print_cb=-1, input_name=None):
        self.conn = conn
        self._err_clean = []
        self._force_clean = []

        # pylint: disable=redefined-variable-type
        if print_cb == -1 or print_cb is None:
            def cb(msg):
                if print_cb == -1:
                    print(msg)
            self.print_cb = cb
        else:
            self.print_cb = print_cb

        parser = None
        if input_name:
            parser = _find_parser_by_name(input_name)

        input_file = os.path.abspath(input_file)
        logging.debug("converter __init__ with input=%s parser=%s",
            input_file, parser)

        (self._input_file,
         self.parser,
         self._force_clean) = _find_input(input_file, parser, self.print_cb)
        self._top_dir = os.path.dirname(os.path.abspath(self._input_file))

        logging.debug("converter not input_file=%s parser=%s",
            self._input_file, self.parser)

        cwd = os.getcwd()
        try:
            os.chdir(self._top_dir)
            self._guest = self.parser.export_libvirt(self.conn,
                self._input_file)
            self._guest.add_default_devices()
        finally:
            os.chdir(cwd)

    def __del__(self):
        for f in self._force_clean:
            shutil.rmtree(f)

    def get_guest(self):
        return self._guest

    def cleanup(self):
        """
        Remove any generated output.
        """
        for path in self._err_clean:
            if os.path.isfile(path):
                os.remove(path)
            if os.path.isdir(path):
                shutil.rmtree(path)

    def _copy_file(self, absin, absout, dry):
        self.print_cb("Copying %s to %s" % (os.path.basename(absin), absout))
        if not dry:
            shutil.copy(absin, absout)

    def _qemu_convert(self, absin, absout, disk_format, dry):
        """
        Use qemu-img to convert the given disk.  Note that at least some
        version of qemu-img cannot handle multi-file VMDKs, so this can
        easily go wrong.
        Gentoo, Debian, and Ubuntu (potentially others) install kvm-img
        with kvm and qemu-img with qemu. Both would work.
        """
        binnames = ["qemu-img", "kvm-img"]

        decompress_cmd = None

        if _is_test():
            executable = "/usr/bin/qemu-img"
        else:
            for binname in binnames:
                executable = find_executable(binname)
                if executable:
                    break

        if executable is None:
            raise RuntimeError(_("None of %s tools found.") % binnames)

        base = os.path.basename(absin)
        ext = os.path.splitext(base)[1]
        if (ext and ext[1:] == "gz"):
            if not find_executable("gzip"):
                raise RuntimeError("'gzip' is needed to decompress the file, "
                    "but not found.")
            decompress_cmd = ["gzip", "-d", absin]
            base = os.path.splitext(base)[0]
            absin = absin[0:-3]
            self.print_cb("Running %s" % " ".join(decompress_cmd))
        cmd = [executable, "convert", "-O", disk_format, base, absout]
        self.print_cb("Running %s" % " ".join(cmd))
        if dry:
            return

        cmd[4] = absin
        if decompress_cmd is not None:
            _run_cmd(decompress_cmd)
        _run_cmd(cmd)

    def convert_disks(self, disk_format, destdir=None, dry=False):
        """
        Convert a disk into the requested format if possible, in the
        given output directory.  Raises RuntimeError or other failures.
        """
        if disk_format == "none":
            disk_format = None

        if destdir is None:
            destdir = StoragePool.get_default_dir(self.conn, build=not dry)

        guest = self.get_guest()
        for disk in guest.get_devices("disk"):
            if disk.device != "disk":
                continue

            if disk_format and disk.driver_type == disk_format:
                logging.debug("path=%s is already in requested format=%s",
                    disk.path, disk_format)
                disk_format = None

            basepath = os.path.splitext(os.path.basename(disk.path))[0]
            newpath = re.sub(r'\s', '_', basepath)
            if disk_format:
                newpath += ("." + disk_format)
            newpath = os.path.join(destdir, newpath)
            if os.path.exists(newpath) and not _is_test():
                raise RuntimeError(_("New path name '%s' already exists") %
                    newpath)

            if not disk_format or disk_format == "none":
                self._copy_file(disk.path, newpath, dry)
            else:
                self._qemu_convert(disk.path, newpath, disk_format, dry)
            disk.driver_type = disk_format
            disk.path = newpath
            self._err_clean.append(newpath)

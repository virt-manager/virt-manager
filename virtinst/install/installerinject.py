#
# Copyright 2006-2009, 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import shutil
import subprocess
import tempfile

from ..logger import log


def _run_initrd_commands(initrd, tempdir):
    log.debug("Appending to the initrd.")

    find_proc = subprocess.Popen(['find', '.', '-print0'],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 cwd=tempdir)
    cpio_proc = subprocess.Popen(['cpio', '--create', '--null', '--quiet',
                                  '--format=newc', '--owner=root:root'],
                                 stdin=find_proc.stdout,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 cwd=tempdir)
    f = open(initrd, 'ab')
    gzip_proc = subprocess.Popen(['gzip'], stdin=cpio_proc.stdout,
                                 stdout=f, stderr=subprocess.PIPE)
    cpio_proc.wait()
    find_proc.wait()
    gzip_proc.wait()
    f.close()

    finderr = find_proc.stderr.read()
    cpioerr = cpio_proc.stderr.read()
    gziperr = gzip_proc.stderr.read()
    if finderr:  # pragma: no cover
        log.debug("find stderr=%s", finderr)
    if cpioerr:  # pragma: no cover
        log.debug("cpio stderr=%s", cpioerr)
    if gziperr:  # pragma: no cover
        log.debug("gzip stderr=%s", gziperr)

    if (cpio_proc.returncode != 0 or
        find_proc.returncode != 0 or
        gzip_proc.returncode != 0):  # pragma: no cover
        raise RuntimeError("Failed to inject files into initrd")


def _run_iso_commands(iso, tempdir, cloudinit=False):
    # These three programs all behave similarly for our needs, and
    # different distros only have some available. xorriso is apparently
    # the actively maintained variant that should be available everywhere
    # and without any license issues. Some more info here:
    # https://wiki.debian.org/genisoimage
    programs = ["xorrisofs", "genisoimage", "mkisofs"]
    for program in programs:
        if shutil.which(program):
            break

    cmd = [program,
           "-o", iso,
           "-J",
           "-input-charset", "utf8",
           "-rational-rock"]
    if cloudinit:
        cmd.extend(["-V", "cidata"])
    cmd.append(tempdir)
    log.debug("Running iso build command: %s", cmd)
    output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    log.debug("cmd output: %s", output)


def _perform_generic_injections(injections, scratchdir, media, cb, **kwargs):
    if not injections:
        return

    tempdir = tempfile.mkdtemp(dir=scratchdir)
    try:
        os.chmod(tempdir, 0o775)

        for filename in injections:
            if type(filename) is tuple:
                filename, dst = filename
            else:
                dst = os.path.basename(filename)

            log.debug("Injecting src=%s dst=%s into media=%s",
                    filename, dst, media)
            shutil.copy(filename, os.path.join(tempdir, dst))

        return cb(media, tempdir, **kwargs)
    finally:
        shutil.rmtree(tempdir)


def perform_initrd_injections(initrd, injections, scratchdir):
    """
    Insert files into the root directory of the initial ram disk
    """
    _perform_generic_injections(injections, scratchdir, initrd,
            _run_initrd_commands)


def perform_cdrom_injections(injections, scratchdir, cloudinit=False):
    """
    Insert files into the root directory of a generated cdrom
    """
    if cloudinit:
        iso_suffix = "-cloudinit.iso"
    else:
        iso_suffix = "-unattended.iso"
    fileobj = tempfile.NamedTemporaryFile(
        prefix="virtinst-", suffix=iso_suffix,
        dir=scratchdir, delete=False)
    iso = fileobj.name

    try:
        _perform_generic_injections(injections, scratchdir, iso,
            _run_iso_commands, cloudinit=cloudinit)
    except Exception:  # pragma: no cover
        os.unlink(iso)
        raise

    return iso

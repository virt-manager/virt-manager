#
# Copyright 2006-2009, 2013, 2014 Red Hat, Inc.
# Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import os
import shutil
import subprocess
import tempfile


def _rhel4_initrd_inject(initrd, injections):
    try:
        file_proc = subprocess.Popen(["file", "-z", initrd],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        s = bytes("ext2 filesystem", "ascii")
        if s not in file_proc.communicate()[0]:
            return False
    except Exception:
        logging.exception("Failed to file command for rhel4 initrd detection")
        return False

    logging.debug("Is RHEL4 initrd")

    # Uncompress the initrd
    newinitrd = open(initrd + ".new", "wb")
    gzip_proc = subprocess.Popen(["gzip", "-d", "-f", "-c", initrd],
                                 stdout=newinitrd,
                                 stderr=subprocess.PIPE)
    gzip_proc.wait()
    newinitrd.close()

    debugfserr = bytes()
    for filename in injections:
        # We have an ext2 filesystem, use debugfs to inject files
        cmd = ["debugfs", "-w", "-R",
               "write %s %s" % (filename, os.path.basename(filename)),
               newinitrd.name]
        logging.debug("Copying %s to the initrd with cmd=%s", filename, cmd)

        debugfs_proc = subprocess.Popen(cmd,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
        debugfs_proc.wait()
        debugfserr += debugfs_proc.stderr.read() or bytes()

    gziperr = gzip_proc.stderr.read()
    if gziperr:
        logging.debug("gzip stderr=%s", gziperr)
    if debugfserr:
        logging.debug("debugfs stderr=%s", debugfserr)

    # Recompress the initrd
    gzip_proc = subprocess.Popen(["gzip"],
                                 stdin=open(newinitrd.name, "rb"),
                                 stdout=open(initrd, "wb"),
                                 stderr=subprocess.PIPE)
    gzip_proc.wait()
    gziperr = gzip_proc.stderr.read()
    if gziperr:
        logging.debug("gzip stderr=%s", gziperr)
    os.unlink(newinitrd.name)

    return True


def perform_initrd_injections(initrd, injections, scratchdir):
    """
    Insert files into the root directory of the initial ram disk
    """
    if not injections:
        return

    if _rhel4_initrd_inject(initrd, injections):
        return

    tempdir = tempfile.mkdtemp(dir=scratchdir)
    os.chmod(tempdir, 0o775)

    for filename in injections:
        logging.debug("Copying %s to the initrd.", filename)
        shutil.copy(filename, tempdir)

    logging.debug("Appending to the initrd.")
    find_proc = subprocess.Popen(['find', '.', '-print0'],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 cwd=tempdir)
    cpio_proc = subprocess.Popen(['cpio', '-o', '--null', '-Hnewc', '--quiet'],
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
    shutil.rmtree(tempdir)

    finderr = find_proc.stderr.read()
    cpioerr = cpio_proc.stderr.read()
    gziperr = gzip_proc.stderr.read()
    if finderr:
        logging.debug("find stderr=%s", finderr)
    if cpioerr:
        logging.debug("cpio stderr=%s", cpioerr)
    if gziperr:
        logging.debug("gzip stderr=%s", gziperr)

#
# Copyright 2019 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import os
import shutil
import subprocess
import tempfile


def _run_iso_commands(iso, tempdir):
    cmd = ["mkisofs",
           "-o", iso,
           "-J",
           "-input-charset", "utf8",
           "-rational-rock",
           tempdir]
    logging.debug("Running mkisofs: %s", cmd)
    output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    logging.debug("cmd output: %s", output)


def perform_cdrom_injections(injections, scratchdir):
    """
    Insert files into the root directory of a floppy
    """
    if not injections:
        return

    fileobj = tempfile.NamedTemporaryFile(
        dir=scratchdir, prefix="virtinst-unattended-iso", delete=False)
    iso = fileobj.name

    tempdir = tempfile.mkdtemp(dir=scratchdir)
    try:
        os.chmod(tempdir, 0o775)

        for filename in injections:
            if type(filename) is tuple:
                filename, dst = filename
            else:
                dst = os.path.basename(filename)

            logging.debug("Injecting src=%s dst=%s", filename, dst)
            shutil.copy(filename, os.path.join(tempdir, dst))

        _run_iso_commands(iso, tempdir)
    finally:
        shutil.rmtree(tempdir)

    return iso

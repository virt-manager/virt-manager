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


def perform_cdrom_injections(injections, scratchdir):
    """
    Insert files into the root directory of a floppy
    """
    if not injections:
        return

    tempdir = tempfile.mkdtemp(dir=scratchdir)
    os.chmod(tempdir, 0o775)

    tempfiles = []
    iso = os.path.join(tempdir, "unattended.iso")
    for filename in injections:
        shutil.copy(filename, tempdir)

    tempfiles = os.listdir(tempdir)

    cmd = ["mkisofs",
           "-o", iso,
           "-J",
           "-input-charset", "utf8",
           "-rational-rock",
           tempdir]
    logging.debug("Running mkisofs: %s", cmd)
    output = subprocess.check_output(cmd)
    logging.debug("cmd output: %s", output)

    for f in tempfiles:
        os.unlink(os.path.join(tempdir, f))

    return iso

#
# Copyright 2019 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import os
import subprocess
import tempfile


def perform_floppy_injections(injections, scratchdir):
    """
    Insert files into the root directory of a floppy
    """
    if not injections:
        return

    tempdir = tempfile.mkdtemp(dir=scratchdir)
    os.chmod(tempdir, 0o775)

    img = os.path.join(tempdir, "unattended.img")

    cmd = ["mkfs.msdos", "-C", img, "1440"]
    logging.debug("Running mkisofs: %s", cmd)
    output = subprocess.check_output(cmd)
    logging.debug("cmd output: %s", output)

    for filename in injections:
        logging.debug("Copying %s to the floppy.", filename)
        cmd = ["mcopy", "-i", img, filename, "::"]
        output = subprocess.check_output(cmd)
        logging.debug("cmd output: %s", output)

    return img

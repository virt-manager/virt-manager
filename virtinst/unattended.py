#
# Common code for unattended installations
#
# Copyright 2019 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from . import util
from .osdict import OSInstallScript


class UnattendedData():
    profile = None
    admin_password = None
    user_password = None


def generate_install_script(guest, unattended_data):
    from gi.repository import Gio as gio

    rawscript = guest.osinfo.get_install_script(unattended_data.profile)
    script = OSInstallScript(rawscript, guest.osinfo)

    # For all tree based installations we're going to perform initrd injection
    # and install the systems via network.
    script.set_preferred_injection_method("initrd")
    script.set_installation_source("network")

    config = script.get_config(unattended_data, guest.os.arch, guest.name)

    scratch = os.path.join(util.get_cache_dir(), "unattended")
    if not os.path.exists(scratch):
        os.makedirs(scratch, 0o751)

    script.generate_output(config, gio.File.new_for_path(scratch))
    path = os.path.join(scratch, script.get_expected_filename())
    cmdline = script.generate_cmdline(config)

    return path, cmdline

#
# Common code for unattended installations
#
# Copyright 2019 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from . import util


class UnattendedData():
    profile = None
    admin_password = None
    user_password = None


def generate_install_script(guest, unattended_data):
    from gi.repository import Gio as gio

    script = guest.osinfo.get_install_script(unattended_data.profile)

    # For all tree based installations we're going to perform initrd injection
    # and install the systems via network.
    guest.osinfo.set_install_script_preferred_injection_method(
            script, "initrd")
    guest.osinfo.set_install_script_installation_source(script, "network")

    config = guest.osinfo.get_install_script_config(
            script, unattended_data, guest.os.arch, guest.name)

    scratch = os.path.join(util.get_cache_dir(), "unattended")
    if not os.path.exists(scratch):
        os.makedirs(scratch, 0o751)

    guest.osinfo.generate_install_script_output(script, config,
            gio.File.new_for_path(scratch))

    path = os.path.join(scratch, script.get_expected_filename())
    cmdline = guest.osinfo.generate_install_script_cmdline(script, config)

    return path, cmdline

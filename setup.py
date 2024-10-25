#!/usr/bin/env python3
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.


import sys
import glob
import importlib.util
import os
from pathlib import Path
import shutil
import sysconfig
import subprocess

import setuptools
import setuptools.command.install
import setuptools.command.install_egg_info
try:
    # Use the setuptools build command with setuptools >= 62.4.0
    import setuptools.command.build
    BUILD_COMMAND_CLASS = setuptools.command.build.build
except ImportError:
    # Use distutils with an older setuptools version
    #
    # Newer setuptools will transparently support 'import distutils' though.
    # That can be overridden with SETUPTOOLS_USE_DISTUTILS env variable
    import distutils.command.build  # pylint: disable=wrong-import-order,deprecated-module,import-error
    BUILD_COMMAND_CLASS = distutils.command.build.build  # pylint: disable=c-extension-no-member


class my_egg_info(setuptools.command.install_egg_info.install_egg_info):
    """
    Disable egg_info installation, seems pointless for a non-library
    """
    def run(self):
        pass


###################
# Custom commands #
###################

class my_rpm(setuptools.Command):
    user_options = []
    description = "Build RPMs and output to the source directory."

    def initialize_options(self):
        pass
    def finalize_options(self):
        pass

    def run(self):
        self.run_command('sdist')
        srcdir = os.path.dirname(__file__)
        cmd = [
            "rpmbuild", "-ta",
            "--define", "_rpmdir %s" % srcdir,
            "--define", "_srcrpmdir %s" % srcdir,
            "--define", "_specdir /tmp",
            "dist/virt-manager-%s.tar.gz" % BuildConfig.version,
        ]
        subprocess.check_call(cmd)


class TestCommand(setuptools.Command):
    user_options = []
    description = "DEPRECATED: Use `pytest`. See CONTRIBUTING.md"
    def finalize_options(self):
        pass
    def initialize_options(self):
        pass
    def run(self):
        sys.exit("ERROR: `test` is deprecated. Call `pytest` instead. "
                 "See CONTRIBUTING.md for more info.")


setuptools.setup(
    name="virt-manager",
    version=BuildConfig.version,
    url="https://virt-manager.org",
    license="GPLv2+",

    # stop setuptools 61+ thinking we want to include everything automatically
    py_modules=[],

    cmdclass={
        'install_egg_info': my_egg_info,

        'rpm': my_rpm,
        'test': TestCommand,
    },

    packages=[],
)

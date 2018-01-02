# Copyright (C) 2013, 2014 Red Hat, Inc.
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

import atexit
import imp
import logging
import os

# Need to do this before any tests or virtinst import
os.environ["VIRTINST_TEST_SUITE"] = "1"
os.environ["VIRTINST_TEST_URL_DIR"] = os.path.abspath(
    "tests/cli-test-xml/fakefedoratree/")

# pylint: disable=wrong-import-position
from virtcli import cliconfig
# This sets all the cli bits back to their defaults
imp.reload(cliconfig)

from tests import utils

virtinstall = None
virtclone = None
virtconvert = None
virtxml = None


def _setup_logging():
    rootLogger = logging.getLogger()
    for handler in rootLogger.handlers:
        rootLogger.removeHandler(handler)

    logging.basicConfig(level=logging.DEBUG,
                        format="%(levelname)-8s %(message)s")

    if utils.get_debug():
        rootLogger.setLevel(logging.DEBUG)
    else:
        rootLogger.setLevel(logging.ERROR)


def _setup_cli_imports():
    _cleanup_imports = []

    def _cleanup_imports_cb():
        for f in _cleanup_imports:
            if os.path.exists(f):
                os.unlink(f)

    def _import(name, path):
        _cleanup_imports.append(path + "c")
        return imp.load_source(name, path)

    global virtinstall
    global virtclone
    global virtconvert
    global virtxml
    atexit.register(_cleanup_imports_cb)
    virtinstall = _import("virtinstall", "virt-install")
    virtclone = _import("virtclone", "virt-clone")
    virtconvert = _import("virtconvert", "virt-convert")
    virtxml = _import("virtxml", "virt-xml")


_setup_logging()
_setup_cli_imports()

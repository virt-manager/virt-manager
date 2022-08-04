#
# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
#

"""
Configuration variables that can be set at build time
"""

import os
import sys

if (sys.version_info.major != 3 or
    sys.version_info.minor < 4):  # pragma: no cover
    print("python 3.4 or later is required, your's is %s" %
            sys.version_info)
    sys.exit(1)

import configparser

_cfg = configparser.ConfigParser()
_filepath = os.path.abspath(__file__)
_srcdir = os.path.abspath(os.path.join(os.path.dirname(_filepath), ".."))
_cfgpath = os.path.join(os.path.dirname(_filepath), "build.cfg")
if os.path.exists(_cfgpath):
    _cfg.read(_cfgpath)  # pragma: no cover

_istest = "VIRTINST_TEST_SUITE" in os.environ
_running_from_srcdir = os.path.exists(
    os.path.join(_srcdir, "tests", "test_cli.py"))


def _split_list(commastr):
    return [d for d in commastr.split(",") if d]


def _get_param(name, default):  # pragma: no cover
    if _istest:
        return default
    try:
        return _cfg.get("config", name)
    except (configparser.NoOptionError, configparser.NoSectionError):
        return default


__version__ = "4.1.0"


class _BuildConfig(object):
    def __init__(self):
        self.cfgpath = _cfgpath
        self.version = __version__

        self.default_graphics = _get_param("default_graphics", "spice")
        self.default_hvs = _split_list(_get_param("default_hvs", ""))

        self.prefix = None
        self.gettext_dir = None
        self.ui_dir = None
        self.icon_dir = None
        self.gsettings_dir = None
        self.running_from_srcdir = _running_from_srcdir
        self._set_paths_by_prefix(_get_param("prefix", "/usr"))


    def _set_paths_by_prefix(self, prefix):
        self.prefix = prefix
        self.gettext_dir = os.path.join(prefix, "share", "locale")

        if self.running_from_srcdir:
            self.ui_dir = os.path.join(_srcdir, "ui")
            self.icon_dir = os.path.join(_srcdir, "data")
            self.gsettings_dir = self.icon_dir
        else:  # pragma: no cover
            self.ui_dir = os.path.join(prefix, "share", "virt-manager", "ui")
            self.icon_dir = os.path.join(prefix, "share", "virt-manager",
                "icons")
            self.gsettings_dir = os.path.join(prefix, "share",
                "glib-2.0", "schemas")


BuildConfig = _BuildConfig()

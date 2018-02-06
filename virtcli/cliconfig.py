#
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
#

"""
Configuration variables that can be set at build time
"""

import ConfigParser
import os


_cfg = ConfigParser.ConfigParser()
_filepath = os.path.abspath(__file__)
_srcdir = os.path.abspath(os.path.join(os.path.dirname(_filepath), ".."))
_cfgpath = os.path.join(os.path.dirname(_filepath), "cli.cfg")
if os.path.exists(_cfgpath):
    _cfg.read(_cfgpath)

_istest = "VIRTINST_TEST_SUITE" in os.environ
_running_from_srcdir = os.path.exists(
    os.path.join(_srcdir, "tests", "clitest.py"))


def _split_list(commastr):
    return [d for d in commastr.split(",") if d]


def _get_param(name, default):
    if _istest:
        return default
    try:
        return _cfg.get("config", name)
    except (ConfigParser.NoOptionError, ConfigParser.NoSectionError):
        return default


def _setup_gsettings_path(schemadir):
    """
    If running from the virt-manager.git srcdir, compile our gsettings
    schema and use it directly
    """
    import subprocess
    from distutils.spawn import find_executable

    exe = find_executable("glib-compile-schemas")
    if not exe:
        raise RuntimeError("You must install glib-compile-schemas to run "
            "virt-manager from git.")

    ret = subprocess.call([exe, "--strict", schemadir])
    if ret != 0:
        raise RuntimeError("Failed to compile local gsettings schemas")


__version__ = "1.5.0"


class _CLIConfig(object):
    def __init__(self):
        self.cfgpath = _cfgpath
        self.version = __version__

        self.default_qemu_user = _get_param("default_qemu_user", "root")
        self.stable_defaults = bool(int(_get_param("stable_defaults", "0")))

        self.preferred_distros = _split_list(
            _get_param("preferred_distros", ""))
        self.hv_packages = _split_list(_get_param("hv_packages", ""))
        self.askpass_package = _split_list(_get_param("askpass_packages", ""))
        self.libvirt_packages = _split_list(_get_param("libvirt_packages", ""))
        self.default_graphics = _get_param("default_graphics", "spice")
        self.default_hvs = _split_list(_get_param("default_hvs", ""))

        self.prefix = None
        self.gettext_dir = None
        self.ui_dir = None
        self.icon_dir = None
        self.gsettings_dir = None
        self.set_paths_by_prefix(_get_param("prefix", "/usr"),
            check_source_dir=True)

    def set_paths_by_prefix(self, prefix, check_source_dir=False):
        self.prefix = prefix
        self.gettext_dir = os.path.join(prefix, "share", "locale")

        if _running_from_srcdir and check_source_dir:
            self.ui_dir = os.path.join(_srcdir, "ui")
            self.icon_dir = os.path.join(_srcdir, "data")
            self.gsettings_dir = self.icon_dir
            _setup_gsettings_path(self.gsettings_dir)
        else:
            self.ui_dir = os.path.join(prefix, "share", "virt-manager", "ui")
            self.icon_dir = os.path.join(prefix, "share", "virt-manager",
                "icons")
            self.gsettings_dir = os.path.join(prefix, "share",
                "glib-2.0", "schemas")


CLIConfig = _CLIConfig()

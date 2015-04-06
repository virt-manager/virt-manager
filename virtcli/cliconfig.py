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

    os.environ["GSETTINGS_SCHEMA_DIR"] = schemadir
    ret = subprocess.call([exe, "--strict", schemadir])
    if ret != 0:
        raise RuntimeError("Failed to compile local gsettings schemas")


##############
# Public API #
##############

__version__ = "1.1.0"

cfgpath = _cfgpath
prefix = _get_param("prefix", "/usr")
gettext_dir = os.path.join(prefix, "share", "locale")
install_asset_dir = os.path.join(prefix, "share", "virt-manager")
if _running_from_srcdir:
    asset_dir = _srcdir
    icon_dir = os.path.join(_srcdir, "data")
    _setup_gsettings_path(icon_dir)
else:
    asset_dir = install_asset_dir
    icon_dir = os.path.join(asset_dir, "icons")

default_qemu_user = _get_param("default_qemu_user", "root")
stable_defaults = bool(int(_get_param("stable_defaults", "0")))

preferred_distros = _split_list(_get_param("preferred_distros", ""))
hv_packages = _split_list(_get_param("hv_packages", ""))
askpass_package = _split_list(_get_param("askpass_packages", ""))
libvirt_packages = _split_list(_get_param("libvirt_packages", ""))
default_graphics = _get_param("default_graphics", "spice")
with_bhyve = bool(int(_get_param("with_bhyve", "0")))

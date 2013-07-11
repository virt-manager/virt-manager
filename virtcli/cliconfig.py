#
# Copyright (C) 2013 Red Hat, Inc.
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


cfg = ConfigParser.ConfigParser()
_filepath = os.path.abspath(__file__)
_srcdir = os.path.abspath(os.path.join(os.path.dirname(_filepath), ".."))
cfgpath = os.path.join(os.path.dirname(_filepath), "cli.cfg")
if os.path.exists(cfgpath):
    cfg.read(cfgpath)


def _split_list(commastr):
    return [d for d in commastr.split(",") if d]


def _get_param(name, default):
    if not cfg.sections():
        return default
    return cfg.get("config", name)


def _setup_gsettings_path(schemadir):
    """
    If running from the virt-manager.git srcdir, compile our gsettings
    schema and use it directly
    """
    import subprocess

    os.environ["GSETTINGS_SCHEMA_DIR"] = schemadir
    ret = subprocess.call(["glib-compile-schemas", "--strict", schemadir])
    if ret != 0:
        raise RuntimeError("Failed to compile local gsettings schemas")


__version__ = "0.10.0"

__snapshot__ = 0

_usr_version = _get_param("pkgversion", "")
if _usr_version is not None and _usr_version != "":
    __version__ = _usr_version

# We should map this into the config somehow but I question if anyone cares
prefix = _get_param("prefix", "/usr")
gettext_dir = os.path.join(prefix, "share", "locale")
install_asset_dir = os.path.join(prefix, "share", "virt-manager")
if os.getcwd() == _srcdir:
    asset_dir = _srcdir
    icon_dir = os.path.join(_srcdir, "data")
    _setup_gsettings_path(icon_dir)
else:
    asset_dir = install_asset_dir
    icon_dir = os.path.join(asset_dir, "icons")

default_qemu_user = _get_param("default_qemu_user", "root")
rhel_enable_unsupported_opts = not bool(int(
    _get_param("hide_unsupported_rhel_options", "0")))

preferred_distros = _split_list(_get_param("preferred_distros", ""))
hv_packages = _split_list(_get_param("hv_packages", ""))
askpass_package = _split_list(_get_param("askpass_packages", ""))
libvirt_packages = _split_list(_get_param("libvirt_packages", ""))
default_graphics = _get_param("default_graphics", "spice")

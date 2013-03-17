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

def get_param(name, default):
    if not cfg.sections():
        return default
    return cfg.get("config", name)

__version__ = "0.9.4"


# We should map this into the config somehow but I question if anyone cares
prefix = "/usr"
if os.getcwd() == _srcdir:
    asset_dir = _srcdir
    # XXX: This gettext bit likely doesn't work either, maybe nothing we can do
    gettext_dir = os.path.join(_srcdir, "po")
    # XXX: This wants data/icons/hicolor...
    icon_dir = os.path.join(_srcdir, "data", "icons")
else:
    asset_dir = os.path.join(prefix, "share", "virt-manager")
    gettext_dir = os.path.join(prefix, "share", "locale")
    icon_dir = os.path.join(asset_dir, "icons")

with_tui = bool(int(get_param("with_tui", "1")))

default_qemu_user = get_param("default_qemu_user", "root")
rhel_enable_unsupported_opts = not bool(int(
    get_param("hide_unsupported_rhel_options", "0")))

preferred_distros = _split_list(get_param("preferred_distros", ""))
hv_packages = _split_list(get_param("hv_packages", ""))
askpass_package = _split_list(get_param("askpass_packages", ""))
libvirt_packages = _split_list(get_param("libvirt_packages", ""))
default_graphics = get_param("default_graphics", "vnc")

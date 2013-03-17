#
# Copyright (C) 2011 Red Hat, Inc.
# Copyright (C) 2011 Cole Robinson <crobinso@redhat.com>
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

_is_gui = True

class stubclass(object):
    def __init__(self, *args, **kwargs):
        ignore = args
        ignore = kwargs

    def __getattr__(self, attr):
        def stub(*args, **kwargs):
            ignore = args
            ignore = kwargs
        return stub

    def __setattr__(self, attr, val):
        ignore = attr
        ignore = val

def is_gui(isgui=None):
    global _is_gui
    if isgui is not None:
        _is_gui = isgui
    return _is_gui

def get_running_config():
    if _is_gui:
        import virtManager.util
        return virtManager.util.running_config
    else:
        return stubclass()

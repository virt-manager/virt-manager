#
# Copyright (C) 2010 Red Hat, Inc.
# Copyright (C) 2010 Cole Robinson <crobinso@redhat.com>
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

import os

import gtk
import gobject

import virtManager.config
from virtManager.error import vmmErrorDialog

class vmmGObject(gobject.GObject):

    @staticmethod
    def type_register(*args, **kwargs):
        gobject.type_register(*args, **kwargs)

    def __init__(self):
        gobject.GObject.__init__(self)
        self.config = virtManager.config.running_config

    def get_hal_helper(self):
        from virtManager import halhelper
        return halhelper.get_hal_helper()

class vmmGObjectUI(vmmGObject):
    def __init__(self, filename, windowname):
        vmmGObject.__init__(self)

        self.windowname = windowname
        self.window = None
        self.topwin = None
        self.gladefile = None

        if filename:
            self.gladefile = os.path.join(self.config.get_glade_dir(),
                                          filename)
            self.window = gtk.glade.XML(self.gladefile,
                                        self.windowname,
                                        domain="virt-manager")
            self.topwin = self.window.get_widget(self.windowname)
            self.topwin.hide()

        self.err = vmmErrorDialog(self.topwin)

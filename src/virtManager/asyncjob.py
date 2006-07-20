#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import threading
import gtk
import gtk.glade
import gobject

# Displays a progress bar while executing the "callback" method.

class asyncJob(gobject.GObject):
    def __init__(self, config, callback, args=None, title="Progress"):
        self.__gobject_init__()
        self.config = config
        self.callback = callback
        self.args = args
        self.pbar_glade = gtk.glade.XML(self.config.get_glade_file(), "vmm-progress")
        self.pbar_win = self.pbar_glade.get_widget("vmm-progress")
        self.pbar = self.pbar_glade.get_widget("pbar")
        self.pbar_win.set_title(title)
        self.pbar_win.hide()
        self.bg_thread = threading.Thread(target=self.callback, args=self.args)

    def run(self):
        self.timer = gobject.timeout_add (100, self.pulse_pbar)
        self.pbar_win.present()
        self.bg_thread.start()
        gtk.main()
        gobject.source_remove(self.timer)
        self.timer = 0
        self.pbar_win.destroy()

    def pulse_pbar(self):
        print "About to frobnicate the pbar"
        if(self.bg_thread.isAlive()):
            self.pbar.pulse()
        else:
            gtk.main_quit()

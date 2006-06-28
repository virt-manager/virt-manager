#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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

import gtk.glade

class vmmAbout:
    def __init__(self, config):
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-about")
        self.window.get_widget("vmm-about").hide()

        self.window.signal_autoconnect({
            "on_vmm_about_delete_event": self.close,
            })

    def show(self):
        dialog = self.window.get_widget("vmm-about")
        dialog.set_version("0.1")
        dialog.show_all()
        dialog.present()

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-about").hide()
        return 1

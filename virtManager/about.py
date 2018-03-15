#
# Copyright (C) 2006, 2013 Red Hat, Inc.
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.
#

import logging

from .baseclass import vmmGObjectUI


class vmmAbout(vmmGObjectUI):
    @classmethod
    def show_instance(cls, parentobj):
        try:
            if not cls._instance:
                cls._instance = cls()
            cls._instance.show(parentobj.topwin)
        except Exception as e:
            parentobj.err.show_err(
                    _("Error launching 'About' dialog: %s") % str(e))

    def __init__(self):
        vmmGObjectUI.__init__(self, "about.ui", "vmm-about")
        self._cleanup_on_app_close()

        self.builder.connect_signals({
            "on_vmm_about_delete_event": self.close,
            "on_vmm_about_response": self.close,
        })

    def show(self, parent):
        logging.debug("Showing about")
        self.topwin.set_version(self.config.get_appversion())
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing about")
        self.topwin.hide()
        return 1

    def _cleanup(self):
        pass

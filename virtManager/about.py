# Copyright (C) 2006, 2013 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging

from .baseclass import vmmGObjectUI


class vmmAbout(vmmGObjectUI):
    @classmethod
    def show_instance(cls, parentobj):
        try:
            if not cls._instance:
                cls._instance = vmmAbout()
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

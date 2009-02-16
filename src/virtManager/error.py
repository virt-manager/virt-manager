# Error dialog with extensible "details" button.
#
# Copyright (C) 2007 Red Hat, Inc.
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

import gtk
import gtk.glade

import logging

class vmmErrorDialog (gtk.MessageDialog):
    def __init__ (self, parent=None, flags=0, typ=gtk.MESSAGE_INFO,
                  buttons=gtk.BUTTONS_NONE, message_format=None,
                  message_details=None, default_title=_("Error")):
        gtk.MessageDialog.__init__ (self,
                                    parent, flags, typ, buttons,
                                    message_format)

        self.val_err_box = None

        self.message_format = message_format
        self.message_details = message_details
        self.buffer = None
        self.default_title = default_title
        self.set_title(self.default_title)
        self.set_property("text", self.message_format)
        self.connect("response", self.response_cb)
        self.connect("delete-event", self.hide_on_delete)

        if not message_details is None:
            # Expander section with details.
            expander = gtk.Expander (_("Details"))
            self.buffer = gtk.TextBuffer ()
            self.buffer.set_text (self.message_details)
            sw = gtk.ScrolledWindow ()
            sw.set_shadow_type (gtk.SHADOW_IN)
            sw.set_size_request (400, 240)
            sw.set_policy (gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
            details = gtk.TextView (self.buffer)
            details.set_editable (False)
            details.set_overwrite (False)
            details.set_cursor_visible (False)
            details.set_wrap_mode (gtk.WRAP_WORD)
            sw.add (details)
            details.show ()
            expander.add (sw)
            sw.show ()
            self.vbox.pack_start (expander)
            expander.show ()

    def response_cb(self, src, ignore):
        src.hide()

    def show_err(self, summary, details, title=None, async=True):
        self.hide()

        if title is None:
            title = self.default_title
        self.set_title(title)
        self.set_property("text", summary)
        self.buffer.set_text(details)
        logging.debug("Uncaught Error: %s : %s" % (summary, details))

        if async:
            self.show()
        else:
            self.run()

    def val_err(self, text1, text2=None, title=None):
        def response_destroy(src, ignore):
            src.destroy()

        if self.val_err_box:
            self.val_err_box.destroy()

        self.val_err_box = gtk.MessageDialog(self.parent,
                                             gtk.DIALOG_DESTROY_WITH_PARENT,
                                             gtk.MESSAGE_ERROR,
                                             gtk.BUTTONS_OK, text1)

        if title is None:
            title = _("Input Error")
        logging.debug("Validation Error: %s" % text1)
        self.val_err_box.set_title(title)
        if text2 is not None:
            self.val_err_box.format_secondary_text(text2)

        self.val_err_box.show()
        self.val_err_box.connect("response", response_destroy)
        return False


    def _show_warning(self, buttons, text1, text2):
        message_box = gtk.MessageDialog(self.parent, \
                                        gtk.DIALOG_DESTROY_WITH_PARENT, \
                                        gtk.MESSAGE_WARNING, \
                                        buttons, text1)
        if text2 != None:
            message_box.format_secondary_text(text2)
        if message_box.run() in [ gtk.RESPONSE_YES, gtk.RESPONSE_OK ]:
            res = True
        else:
            res = False
        message_box.destroy()
        return res

    def yes_no(self, text1, text2=None):
        return self._show_warning(gtk.BUTTONS_YES_NO, text1, text2)

    def ok_cancel(self, text1, text2=None):
        return self._show_warning(gtk.BUTTONS_OK_CANCEL, text1, text2)


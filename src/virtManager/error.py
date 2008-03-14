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
import pango

class vmmErrorDialog (gtk.MessageDialog):
    def __init__ (self, parent=None, flags=0, type=gtk.MESSAGE_INFO,
                  buttons=gtk.BUTTONS_NONE, message_format=None,
                  message_details=None, default_title=_("Error")):
        gtk.MessageDialog.__init__ (self,
                                    parent, flags, type, buttons,
                                    message_format)
        self.message_format = message_format
        self.message_details = message_details
        self.buffer = None
        self.default_title = default_title
        self.set_title(self.default_title)
        self.set_property("text", self.message_format)

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

    def show_err(self, summary, details, title=None):
        if title is None:
            title = self.default_title
        self.set_title(title)
        self.set_property("text", summary)
        self.buffer.set_text(details)
        self.run()
        self.hide()

    def val_err(self, text1, text2=None, title=None):
        message_box = gtk.MessageDialog(self.parent, 0, gtk.MESSAGE_ERROR,\
                                        gtk.BUTTONS_OK, text1)
        if title is None:
            title = _("Input Error")
        message_box.set_title(title)
        if text2 is not None:
            message_box.format_secondary_text(text2)
        message_box.run()
        message_box.destroy()
        return False

    def yes_no(self, text1, text2=None):
        message_box = gtk.MessageDialog(self.parent, 0, gtk.MESSAGE_WARNING, \
                                        gtk.BUTTONS_YES_NO, text1)
        if text2 != None:
            message_box.format_secondary_text(text2)
        if message_box.run()== gtk.RESPONSE_YES:
            res = True
        else:
            res = False
        message_box.destroy()
        return res


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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import gtk
import gtk.glade
import pango

class vmmErrorDialog (gtk.MessageDialog):
    def __init__ (self, parent=None, flags=0, type=gtk.MESSAGE_INFO,
                  buttons=gtk.BUTTONS_NONE, message_format=None,
                  message_details=None):
        gtk.MessageDialog.__init__ (self,
                                    parent, flags, type, buttons,
                                    message_format)

        if not message_details is None:
            # Expander section with details.
            expander = gtk.Expander (_("Details"))
            buffer = gtk.TextBuffer ()
            buffer.set_text (message_details)
            sw = gtk.ScrolledWindow ()
            sw.set_shadow_type (gtk.SHADOW_IN)
            sw.set_size_request (400, 240)
            sw.set_policy (gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
            details = gtk.TextView (buffer)
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

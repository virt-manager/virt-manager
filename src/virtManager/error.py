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

import virtManager.util as util

def safe_set_text(self, text):
    # pygtk < 2.10 doesn't support test property
    if not util.safe_set_prop(self, "text", text):
        self.set_markup(text)


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

    def set_parent(self, parent):
        self.set_transient_for(parent)

    def response_cb(self, src, ignore):
        src.hide()

    def show_err(self, summary, details, title=None, async=True):
        self.hide()

        if title is None:
            title = self.default_title
        self.set_title(title)
        safe_set_text(self, summary)
        self.buffer.set_text(details)
        logging.debug("Uncaught Error: %s : %s" % (summary, details))

        if async:
            self.show()
        else:
            self.run()

    def _show_ok(self, dialog_type, text1, text2, title, async=True):
        def response_destroy(src, ignore):
            src.destroy()

        if self.val_err_box:
            self.val_err_box.destroy()

        self.val_err_box = gtk.MessageDialog(self.get_transient_for(),
                                             gtk.DIALOG_DESTROY_WITH_PARENT,
                                             dialog_type,
                                             gtk.BUTTONS_OK, text1)

        self.val_err_box.set_title(title)
        if text2 is not None:
            self.val_err_box.format_secondary_text(text2)

        self.val_err_box.connect("response", response_destroy)
        if async:
            self.val_err_box.show()
        else:
            self.val_err_box.run()

        return False

    def val_err(self, text1, text2=None, title=None, async=True):
        logging.debug("Validation Error: %s" % text1)
        if title is None:
            title = _("Input Error")
        return self._show_ok(gtk.MESSAGE_ERROR, text1, text2, title, async)

    def show_info(self, text1, text2=None, title=None, async=True):
        if title is None:
            title = ""
        return self._show_ok(gtk.MESSAGE_INFO, text1, text2, title, async)

    def _show_warning(self, buttons, text1, text2):
        message_box = gtk.MessageDialog(self.get_transient_for(),
                                        gtk.DIALOG_DESTROY_WITH_PARENT,
                                        gtk.MESSAGE_WARNING,
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

    def ok(self, text1, text2=None):
        return self._show_warning(gtk.BUTTONS_OK, text1, text2)

    def warn_chkbox(self, text1, text2=None, chktext=None, buttons=None):
        chkbox = vmmCheckDialog(self.get_transient_for(),
                                gtk.MESSAGE_WARNING, buttons)
        return chkbox.show_chkbox(text1, text2, chktext)

    def err_chkbox(self, text1, text2=None, chktext=None, buttons=None):
        chkbox = vmmCheckDialog(self.get_transient_for(),
                                gtk.MESSAGE_ERROR, buttons)
        return chkbox.show_chkbox(text1, text2, chktext)

class vmmCheckDialog (gtk.MessageDialog):
    def __init__ (self, parent=None, typ=gtk.MESSAGE_INFO,
                  buttons=None):
        if not buttons:
            if typ == gtk.MESSAGE_WARNING:
                buttons = gtk.BUTTONS_OK_CANCEL
            else:
                buttons = gtk.BUTTONS_OK

        gtk.MessageDialog.__init__ (self, parent, 0, typ, buttons)

        self.connect("response", self.response_cb)
        self.connect("delete-event", self.hide_on_delete)
        self.set_title("")

        self.chk_vbox = gtk.VBox(False, False)
        self.chk_vbox.set_spacing(0)

        self.chk_align = gtk.Alignment()
        self.chk_align.set_padding(0, 0, 62, 0)
        self.chk_align.add(self.chk_vbox)

        self.chk_align.show_all()
        self.vbox.pack_start(self.chk_align)

    def response_cb(self, src, ignore):
        src.hide()

    def show_chkbox(self, text1, text2=None, chktext=None):
        chkbox = None
        res = None

        self.hide()
        for c in self.chk_vbox.get_children():
            self.chk_vbox.remove(c)

        safe_set_text(self, text1)

        if text2:
            self.format_secondary_text(text2)

        if chktext:
            chkbox = gtk.CheckButton(chktext)
            self.chk_vbox.add(chkbox)
            chkbox.show()

        res = self.run() in [ gtk.RESPONSE_YES, gtk.RESPONSE_OK ]
        if chktext:
            res = [res, chkbox.get_active()]

        return res

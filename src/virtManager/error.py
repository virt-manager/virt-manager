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

import logging

import virtManager.util as util

def safe_set_text(self, text):
    # pygtk < 2.10 doesn't support text property
    if not util.safe_set_prop(self, "text", text):
        self.set_markup(text)


class vmmErrorDialog (gtk.MessageDialog):
    def __init__ (self, parent=None):
        typ = gtk.MESSAGE_ERROR
        message_format = _("Unexpected Error")
        message_details = _("An unexpected error occurred")
        buttons = gtk.BUTTONS_CLOSE
        default_title = _("Error")
        flags = 0

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

    def show_err(self, summary, details, title=None,
                 async=True, debug=True):
        self.hide()

        if title is None:
            title = self.default_title
        self.set_title(title)
        safe_set_text(self, summary)
        self.buffer.set_text(details)

        if debug:
            logging.debug("Uncaught Error: %s : %s" % (summary, details))

        if async:
            self.show()
        else:
            self.run()

    ###################################
    # Simple one shot message dialogs #
    ###################################

    def _simple_dialog(self, dialog_type, buttons, text1,
                       text2, title, async=True):
        message_box = gtk.MessageDialog(self.get_transient_for(),
                                        gtk.DIALOG_DESTROY_WITH_PARENT,
                                        dialog_type, buttons,
                                        text1)
        if title is not None:
            message_box.set_title(title)

        if text2 is not None:
            message_box.format_secondary_text(text2)

        def response_destroy(src, ignore):
            src.destroy()

        if self.val_err_box:
            self.val_err_box.destroy()
        self.val_err_box = message_box

        self.val_err_box.connect("response", response_destroy)
        res = False
        if async:
            self.val_err_box.show()
        else:
            res = self.val_err_box.run()
            res = bool(res in [gtk.RESPONSE_YES, gtk.RESPONSE_OK])

        return res

    def val_err(self, text1, text2=None, title=_("Input Error"), async=True):
        logging.debug("Validation Error: %s" % text1)
        dtype = gtk.MESSAGE_ERROR
        buttons = gtk.BUTTONS_OK
        self._simple_dialog(dtype, buttons, text1, text2, title, async)
        return False

    def show_info(self, text1, text2=None, title="", async=True):
        dtype = gtk.MESSAGE_INFO
        buttons = gtk.BUTTONS_OK
        self._simple_dialog(dtype, buttons, text1, text2, title, async)
        return False

    def yes_no(self, text1, text2=None, title=None):
        dtype = gtk.MESSAGE_WARNING
        buttons = gtk.BUTTONS_YES_NO
        return self._simple_dialog(dtype, buttons, text1, text2, title)

    def ok_cancel(self, text1, text2=None, title=None):
        dtype = gtk.MESSAGE_WARNING
        buttons = gtk.BUTTONS_OK_CANCEL
        return self._simple_dialog(dtype, buttons, text1, text2, title)

    def ok(self, text1, text2=None, title=None):
        dtype = gtk.MESSAGE_WARNING
        buttons = gtk.BUTTONS_OK
        return self._simple_dialog(dtype, buttons, text1, text2, title)


    ##########################################
    # One shot dialog with a checkbox prompt #
    ##########################################

    def warn_chkbox(self, text1, text2=None, chktext=None, buttons=None):
        dtype = gtk.MESSAGE_WARNING
        buttons = buttons or gtk.BUTTONS_OK_CANCEL
        chkbox = _vmmCheckDialog(self.get_transient_for(), dtype, buttons)
        return chkbox.show_chkbox(text1, text2, chktext)

    def err_chkbox(self, text1, text2=None, chktext=None, buttons=None):
        dtype = gtk.MESSAGE_ERROR
        buttons = buttons or gtk.BUTTONS_OK
        chkbox = _vmmCheckDialog(self.get_transient_for(), dtype, buttons)
        return chkbox.show_chkbox(text1, text2, chktext)

class _vmmCheckDialog (gtk.MessageDialog):
    def __init__ (self, parent, typ, buttons):
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

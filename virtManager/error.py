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

# pylint: disable=E0611
from gi.repository import Gtk
# pylint: enable=E0611

import logging
import traceback

from virtManager.baseclass import vmmGObject


def _launch_dialog(dialog, primary_text, secondary_text, title,
                   widget=None, modal=True):
    dialog.set_property("text", primary_text)
    dialog.format_secondary_text(secondary_text or None)
    dialog.set_title(title)

    if widget:
        dialog.get_content_area().add(widget)

    res = False
    if modal:
        res = dialog.run()
        res = bool(res in [Gtk.ResponseType.YES, Gtk.ResponseType.OK])
        dialog.destroy()
    else:
        def response_destroy(src, ignore):
            src.destroy()
        dialog.connect("response", response_destroy)
        dialog.show()

    return res


class vmmErrorDialog(vmmGObject):
    def __init__(self, parent=None):
        vmmGObject.__init__(self)
        self._parent = parent
        self._simple = None

    def _cleanup(self):
        pass

    def set_parent(self, parent):
        self._parent = parent
    def get_parent(self):
        return self._parent

    def show_err(self, summary, details=None, title="",
                 modal=False, debug=True,
                 dialog_type=Gtk.MessageType.ERROR,
                 buttons=Gtk.ButtonsType.CLOSE,
                 text2=None):
        if details is None:
            details = summary
            tb = "".join(traceback.format_exc()).strip()
            if tb != "None":
                details += "\n\n" + tb

        # Make sure we have consistent details for error dialogs
        if (dialog_type == Gtk.MessageType.ERROR and not summary in details):
            details = summary + "\n\n" + details

        if debug:
            logging.debug("error dialog message:\nsummary=%s\ndetails=%s",
                          summary, details)

        dialog = _errorDialog(parent=self.get_parent(),
                              flags=0,
                              message_type=dialog_type,
                              buttons=buttons)

        return dialog.show_dialog(primary_text=summary,
                                  secondary_text=text2,
                                  details=details, title=title,
                                  modal=modal)

    ###################################
    # Simple one shot message dialogs #
    ###################################

    def _simple_dialog(self, dialog_type, buttons, text1,
                       text2, title, widget=None, modal=True):

        dialog = Gtk.MessageDialog(self.get_parent(),
                                   flags=Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                   message_type=dialog_type,
                                   buttons=buttons)
        if self._simple:
            self._simple.destroy()
        self._simple = dialog

        return _launch_dialog(self._simple,
                              text1, text2 or "", title or "",
                              widget=widget,
                              modal=modal)

    def val_err(self, text1, text2=None, title=_("Input Error"), modal=True):
        logtext = "Validation Error: %s" % text1
        if text2:
            logtext += " %s" % text2

        if isinstance(text1, Exception) or isinstance(text2, Exception):
            logging.exception(logtext)
        else:
            self._logtrace(logtext)

        dtype = Gtk.MessageType.ERROR
        buttons = Gtk.ButtonsType.OK
        self._simple_dialog(dtype, buttons,
                            str(text1),
                            text2 and str(text2) or "",
                            str(title), None, modal)
        return False

    def show_info(self, text1, text2=None, title="", widget=None, modal=True):
        dtype = Gtk.MessageType.INFO
        buttons = Gtk.ButtonsType.OK
        self._simple_dialog(dtype, buttons, text1, text2, title, widget, modal)
        return False

    def yes_no(self, text1, text2=None, title=None):
        dtype = Gtk.MessageType.WARNING
        buttons = Gtk.ButtonsType.YES_NO
        return self._simple_dialog(dtype, buttons, text1, text2, title)

    def ok_cancel(self, text1, text2=None, title=None):
        dtype = Gtk.MessageType.WARNING
        buttons = Gtk.ButtonsType.OK_CANCEL
        return self._simple_dialog(dtype, buttons, text1, text2, title)

    def ok(self, text1, text2=None, title=None):
        dtype = Gtk.MessageType.WARNING
        buttons = Gtk.ButtonsType.OK
        return self._simple_dialog(dtype, buttons, text1, text2, title)


    ##########################################
    # One shot dialog with a checkbox prompt #
    ##########################################

    def warn_chkbox(self, text1, text2=None, chktext=None, buttons=None):
        dtype = Gtk.MessageType.WARNING
        buttons = buttons or Gtk.ButtonsType.OK_CANCEL
        chkbox = _errorDialog(parent=self.get_parent(),
                              flags=0,
                              message_type=dtype,
                              buttons=buttons)
        return chkbox.show_dialog(primary_text=text1,
                                  secondary_text=text2,
                                  chktext=chktext)

    def err_chkbox(self, text1, text2=None, chktext=None, buttons=None):
        dtype = Gtk.MessageType.ERROR
        buttons = buttons or Gtk.ButtonsType.OK
        chkbox = _errorDialog(parent=self.get_parent(),
                              flags=0,
                              message_type=dtype,
                              buttons=buttons)
        return chkbox.show_dialog(primary_text=text1,
                                  secondary_text=text2,
                                  chktext=chktext)


class _errorDialog (Gtk.MessageDialog):
    """
    Custom error dialog with optional check boxes or details drop down
    """
    # pylint: disable=E1101
    # pylint can't detect functions we inheirit from Gtk, ex:
    # Instance of '_errorDialog' has no 'set_title' member

    def __init__(self, *args, **kwargs):
        Gtk.MessageDialog.__init__(self, *args, **kwargs)
        self.set_title("")

        self.chk_vbox = None
        self.chk_align = None
        self.init_chkbox()

        self.buffer = None
        self.buf_expander = None
        self.init_details()

    def init_chkbox(self):
        # Init check items
        self.chk_vbox = Gtk.VBox(False, False)
        self.chk_vbox.set_spacing(0)

        self.chk_align = Gtk.Alignment()
        self.chk_align.set_padding(0, 0, 0, 0)
        self.chk_align.add(self.chk_vbox)

        self.chk_align.show_all()
        self.vbox.pack_start(self.chk_align, False, False, 0)

    def init_details(self):
        # Init details buffer
        self.buffer = Gtk.TextBuffer()
        self.buf_expander = Gtk.Expander.new(_("Details"))
        sw = Gtk.ScrolledWindow()
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.set_size_request(400, 240)
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        details = Gtk.TextView.new_with_buffer(self.buffer)
        details.set_editable(False)
        details.set_overwrite(False)
        details.set_cursor_visible(False)
        details.set_wrap_mode(Gtk.WrapMode.WORD)
        details.set_border_width(6)
        sw.add(details)
        self.buf_expander.add(sw)
        self.vbox.pack_start(self.buf_expander, False, False, 0)
        self.buf_expander.show_all()

    def show_dialog(self, primary_text, secondary_text="",
                    title="", details="", chktext="",
                    modal=True):
        chkbox = None
        res = None

        # Hide starting widgets
        self.hide()
        self.buf_expander.hide()
        for c in self.chk_vbox.get_children():
            self.chk_vbox.remove(c)

        if details:
            self.buffer.set_text(details)
            title = title or ""
            self.buf_expander.show()

        if chktext:
            chkbox = Gtk.CheckButton(chktext)
            self.chk_vbox.add(chkbox)
            chkbox.show()

        res = _launch_dialog(self,
                             primary_text, secondary_text or "",
                             title,
                             modal=modal)

        if chktext:
            res = [res, chkbox.get_active()]

        return res

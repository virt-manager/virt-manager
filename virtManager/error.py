# Error dialog with extensible "details" button.
#
# Copyright (C) 2007, 2013-2014 Red Hat, Inc.
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

import logging
import traceback

from gi.repository import Gtk

from .baseclass import vmmGObject


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

        # Callback to lookup the parent window if none is specified.
        # Used by engine.py for properly parenting windows
        self._find_parent_cb = None

        # Allows the error owner to easily override default modality
        self._modal_default = False

    def _cleanup(self):
        self._find_parent_cb = None

    def set_modal_default(self, val):
        self._modal_default = val
    def set_find_parent_cb(self, cb):
        self._find_parent_cb = cb
    def set_parent(self, parent):
        self._parent = parent
    def get_parent(self):
        parent = self._parent
        if parent is None and self._find_parent_cb:
            parent = self._find_parent_cb()
        return parent

    def show_err(self, summary, details=None, title="",
                 modal=None, debug=True,
                 dialog_type=Gtk.MessageType.ERROR,
                 buttons=Gtk.ButtonsType.CLOSE,
                 text2=None):
        if modal is None:
            modal = self._modal_default

        if details is None:
            details = summary
            tb = "".join(traceback.format_exc()).strip()
            if tb != "None":
                details += "\n\n" + tb
        else:
            details = str(details)

        if debug:
            debugmsg = "error dialog message:\nsummary=%s" % summary
            if details and details != summary:
                debugmsg += "\ndetails=%s" % details
            logging.debug(debugmsg)

        # Make sure we have consistent details for error dialogs
        if (dialog_type == Gtk.MessageType.ERROR and summary not in details):
            details = summary + "\n\n" + details

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
        logtext = _("Validation Error: %s") % text1
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

    def show_info(self, text1, text2=None, title="", widget=None, modal=True,
                  buttons=Gtk.ButtonsType.OK):
        dtype = Gtk.MessageType.INFO
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

    def chkbox_helper(self, getcb, setcb, text1, text2=None,
                      default=True,
                      chktext=_("Don't ask me again")):
        """
        Helper to prompt user about proceeding with an operation
        Returns True if the 'yes' or 'ok' button was selected, False otherwise

        @default: What value to return if getcb tells us not to prompt
        """
        do_prompt = getcb()
        if not do_prompt:
            return default

        # pylint: disable=unpacking-non-sequence
        res = self.warn_chkbox(text1=text1, text2=text2,
                               chktext=chktext,
                               buttons=Gtk.ButtonsType.YES_NO)
        response, skip_prompt = res
        setcb(not skip_prompt)

        return response

    def browse_local(self, conn, dialog_name, start_folder=None,
                     _type=None, dialog_type=None,
                     confirm_func=None, browse_reason=None,
                     choose_button=None, default_name=None):
        """
        Helper function for launching a filechooser

        @dialog_name: String to use in the title bar of the filechooser.
        @conn: vmmConnection used by calling class
        @start_folder: Folder the filechooser is viewing at startup
        @_type: File extension to filter by (e.g. "iso", "png")
        @dialog_type: Maps to FileChooserDialog 'action'
        @confirm_func: Optional callback function if file is chosen.
        @browse_reason: The vmmConfig.CONFIG_DIR* reason we are browsing.
            If set, this will override the 'folder' parameter with the gsettings
            value, and store the user chosen path.
        """
        import os

        # Initial setup
        overwrite_confirm = False

        if dialog_type is None:
            dialog_type = Gtk.FileChooserAction.OPEN
        if dialog_type == Gtk.FileChooserAction.SAVE:
            if choose_button is None:
                choose_button = Gtk.STOCK_SAVE
                overwrite_confirm = True

        if choose_button is None:
            choose_button = Gtk.STOCK_OPEN

        fcdialog = Gtk.FileChooserDialog(title=dialog_name,
                                    parent=self.get_parent(),
                                    action=dialog_type,
                                    buttons=(Gtk.STOCK_CANCEL,
                                             Gtk.ResponseType.CANCEL,
                                             choose_button,
                                             Gtk.ResponseType.ACCEPT))
        fcdialog.set_default_response(Gtk.ResponseType.ACCEPT)

        if default_name:
            fcdialog.set_current_name(default_name)

        # If confirm is set, warn about a file overwrite
        if confirm_func:
            overwrite_confirm = True
            fcdialog.connect("confirm-overwrite", confirm_func)
        fcdialog.set_do_overwrite_confirmation(overwrite_confirm)

        # Set file match pattern (ex. *.png)
        if _type is not None:
            pattern = _type
            name = None
            if type(_type) is tuple:
                pattern = _type[0]
                name = _type[1]

            f = Gtk.FileFilter()
            f.add_pattern("*." + pattern)
            if name:
                f.set_name(name)
            fcdialog.set_filter(f)

        # Set initial dialog folder
        if browse_reason:
            start_folder = self.config.get_default_directory(
                conn, browse_reason)

        if start_folder is not None:
            if os.access(start_folder, os.R_OK):
                fcdialog.set_current_folder(start_folder)

        # Run the dialog and parse the response
        ret = None
        if fcdialog.run() == Gtk.ResponseType.ACCEPT:
            ret = fcdialog.get_filename()
        fcdialog.destroy()

        # Store the chosen directory in gsettings if necessary
        if ret and browse_reason and not ret.startswith("/dev"):
            self.config.set_default_directory(
                os.path.dirname(ret), browse_reason)
        return ret


class _errorDialog (Gtk.MessageDialog):
    """
    Custom error dialog with optional check boxes or details drop down
    """
    def __init__(self, *args, **kwargs):
        Gtk.MessageDialog.__init__(self, *args, **kwargs)

        self.set_title("")
        for child in self.get_message_area().get_children():
            if hasattr(child, "set_max_width_chars"):
                child.set_max_width_chars(40)

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
        self.vbox.pack_start(  # pylint: disable=no-member
            self.chk_align, False, False, 0)

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
        self.vbox.pack_start(  # pylint: disable=no-member
            self.buf_expander, False, False, 0)
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

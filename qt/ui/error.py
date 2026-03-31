import sys
import traceback
import textwrap

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QCheckBox, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt

from .lib.i18n import _, ngettext


class vmmErrorDialog:
    _instance = None

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = vmmErrorDialog()
        return cls._instance

    def __init__(self, parent=None):
        self._parent = parent
        self._modal_default = False

    def set_modal_default(self, val):
        self._modal_default = val

    def get_parent(self):
        return self._parent

    def show_err(
        self,
        summary,
        details=None,
        title="",
        modal=None,
        debug=True,
        dialog_type=None,
        buttons=None,
        text2=None,
    ):
        if modal is None:
            modal = self._modal_default

        if details is None:
            details = summary
            if sys.exc_info()[0] is not None:
                details += "\n\n" + "".join(traceback.format_exc()).strip()
        else:
            details = str(details)

        if debug:
            logtext = f"error dialog message:\nsummary={summary}"
            if details and details != summary:
                if details.startswith(summary):
                    det = details[len(summary):].strip()
                else:
                    det = details
                logtext += f"\ndetails={det}"
            print(logtext)

        dtype = QMessageBox.Icon.Critical
        if dialog_type == QMessageBox.Icon.Warning:
            dtype = QMessageBox.Icon.Warning
        elif dialog_type == QMessageBox.Icon.Information:
            dtype = QMessageBox.Icon.Information

        msg = QMessageBox(
            dtype, title or _("Error"), summary,
            QMessageBox.StandardButton.Ok, self._parent
        )
        if text2 or details:
            msg.setDetailedText(details if details else text2)
        msg.exec()
        return False

    def val_err(self, text1, text2=None, title="Input Error", modal=True):
        logtext = f"Validation Error: {text1}"
        if text2:
            logtext += f" {text2}"
        print(logtext)
        
        msg = QMessageBox(QMessageBox.Icon.Critical, _(title), str(text1), QMessageBox.StandardButton.Ok, self._parent)
        if text2:
            msg.setInformativeText(str(text2))
        msg.exec()
        return False

    def show_info(self, text1, text2=None, title="", widget=None, modal=True, buttons=None):
        msg = QMessageBox(QMessageBox.Icon.Information, title or _("Information"), text1, QMessageBox.StandardButton.Ok, self._parent)
        if text2:
            msg.setInformativeText(text2)
        msg.exec()
        return False

    def yes_no(self, text1, text2=None, title=None):
        msg = QMessageBox(QMessageBox.Icon.Question, title or _("Confirm"), text1, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self._parent)
        if text2:
            msg.setInformativeText(text2)
        return msg.exec() == QMessageBox.StandardButton.Yes

    def ok_cancel(self, text1, text2=None, title=None):
        msg = QMessageBox(QMessageBox.Icon.Warning, title or _("Confirm"), text1, QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, self._parent)
        if text2:
            msg.setInformativeText(text2)
        return msg.exec() == QMessageBox.StandardButton.Ok

    def confirm_unapplied_changes(self):
        return self.yes_no(
            _("There are unapplied changes. Would you like to apply them now?")
        )

    def warn_chkbox(self, text1, text2=None, chktext=None, buttons=None):
        return self._show_chkbox_dialog(QMessageBox.Icon.Warning, text1, text2, chktext, buttons)

    def err_chkbox(self, text1, text2=None, chktext=None, buttons=None):
        return self._show_chkbox_dialog(QMessageBox.Icon.Critical, text1, text2, chktext, buttons)

    def _show_chkbox_dialog(self, icon, text1, text2, chktext, buttons):
        msg = QMessageBox(icon, _("Confirm"), text1, QMessageBox.StandardButton.Ok, self._parent)
        if text2:
            msg.setInformativeText(text2)
        msg.setCheckBox(QCheckBox(chktext) if chktext else None)
        result = msg.exec()
        if chktext:
            return [result == QMessageBox.StandardButton.Ok, msg.checkBox().isChecked()]
        return result == QMessageBox.StandardButton.Ok

    def chkbox_helper(self, getcb, setcb, text1, text2=None, default=True, chktext=None):
        if chktext is None:
            chktext = _("Don't ask again")
        do_prompt = getcb()
        if not do_prompt:
            return default

        result = self.warn_chkbox(text1, text2, chktext, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if isinstance(result, list):
            response, skip_prompt = result
            setcb(not skip_prompt)
            return response
        return result

    def browse_local(
        self,
        dialog_name,
        start_folder=None,
        _type=None,
        dialog_type=None,
        choose_label=None,
        default_name=None,
        confirm_overwrite=False,
    ):
        if dialog_type is None:
            dialog_type = QFileDialog.AcceptMode.AcceptOpen

        dlg = QFileDialog(self._parent, dialog_name)
        
        if dialog_type == QFileDialog.AcceptMode.AcceptOpen:
            dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        elif dialog_type == QFileDialog.AcceptMode.AcceptSave:
            dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
            dlg.setFileMode(QFileDialog.FileMode.AnyFile)
        
        if _type:
            if isinstance(_type, tuple):
                pattern = _type[0]
            else:
                pattern = f"*.{_type}"
            dlg.setNameFilter(f"{_type} ({pattern})")

        if start_folder and start_folder:
            dlg.setDirectory(start_folder)
        
        if default_name:
            dlg.selectFile(default_name)

        result = []
        if dlg.exec() == QFileDialog.AcceptOpen.Accept:
            result = dlg.selectedFiles()

        return result[0] if result else None

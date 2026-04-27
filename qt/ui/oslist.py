from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTreeWidget, QTreeWidgetItem, QCheckBox, QScrollArea,
    QCompleter
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from .lib.i18n import _


class vmmOSList(QWidget):
    os_selected = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._filter_name = None
        self._filter_eol = True
        self._selected_os = None
        self._all_os = []
        
        self._init_ui()
        self._load_os_list()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(_("Type to start searching..."))
        self._search_entry.textChanged.connect(self._search_changed)
        layout.addWidget(self._search_entry)

        self._eol_check = QCheckBox(_("Include end-of-life OSes"))
        self._eol_check.stateChanged.connect(self._eol_toggled)
        layout.addWidget(self._eol_check)

        self._os_list = QTreeWidget()
        self._os_list.setHeaderLabels([_("Name")])
        self._os_list.itemDoubleClicked.connect(self._os_selected)
        layout.addWidget(self._os_list)

    def _load_os_list(self):
        try:
            import virtinst
            all_os = virtinst.OSDB.list_os(sortkey="label")
            
            for os in all_os:
                item = QTreeWidgetItem(self._os_list)
                item.setText(0, f"{os.label} ({os.name})")
                item.setData(0, Qt.ItemDataRole.UserRole, os)
                self._all_os.append(item)
        except Exception:
            pass

    def _refilter(self):
        filter_text = self._filter_name.lower() if self._filter_name else ""
        
        for item in self._all_os:
            osobj = item.data(0, Qt.ItemDataRole.UserRole)
            show = True
            
            if self._filter_eol and osobj.eol:
                show = False
            
            if filter_text:
                label = osobj.label.lower()
                name = osobj.name.lower()
                if label.find(filter_text) == -1 and name.find(filter_text) == -1:
                    show = False
            
            item.setHidden(not show)

    def _search_changed(self, text):
        self._filter_name = text.strip().lower()
        self._refilter()

    def _eol_toggled(self, state):
        self._filter_eol = (state == 0)
        self._refilter()

    def _os_selected(self, item, column):
        osobj = item.data(0, Qt.ItemDataRole.UserRole)
        self._selected_os = osobj
        self._search_entry.setText(osobj.label)
        self.os_selected.emit(osobj)

    def reset_state(self):
        self._selected_os = None
        self._search_entry.clear()
        self._filter_name = None
        self._refilter()
        self.os_selected.emit(None)

    def select_os(self, vmosobj):
        self._filter_name = None
        
        if vmosobj.eol and not self._eol_check.isChecked():
            self._eol_check.setChecked(True)
        
        for item in self._all_os:
            osobj = item.data(0, Qt.ItemDataRole.UserRole)
            if osobj.name == vmosobj.name:
                self._os_list.setCurrentItem(item)
                self._selected_os = osobj
                self._search_entry.setText(osobj.label)
                self.os_selected.emit(osobj)
                break

    def get_selected_os(self):
        return self._selected_os

    def set_sensitive(self, sensitive):
        self._search_entry.setEnabled(sensitive)
        if not sensitive:
            self.reset_state()

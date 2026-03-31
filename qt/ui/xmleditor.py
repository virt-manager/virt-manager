from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel, QTabWidget, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from .lib.i18n import _


PAGE_DETAILS = 0
PAGE_XML = 1


class vmmXMLEditor(QWidget):
    def __init__(self, details_widget, config=None):
        super().__init__()
        
        self._details_widget = details_widget
        self._config = config
        self._curpage = PAGE_DETAILS
        self._srcxml = ""
        self._xml_notebook = None
        self._xml_text = None
        self._details_changed = False
        
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self._notebook = QTabWidget()
        self._notebook.setTabPosition(QTabWidget.TabPosition.North)
        
        self._details_page = QWidget()
        details_layout = QVBoxLayout(self._details_page)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addWidget(self._details_widget)
        
        self._xml_page = QWidget()
        xml_layout = QVBoxLayout(self._xml_page)
        xml_layout.setContentsMargins(4, 4, 4, 4)
        
        warning_label = QLabel(_("XML editing is disabled. Enable in Preferences to turn on."))
        warning_label.setStyleSheet("background-color: #fff3cd; padding: 8px; border: 1px solid #ffc107; border-radius: 4px;")
        xml_layout.addWidget(warning_label)
        
        self._xml_text = QTextEdit()
        self._xml_text.setReadOnly(True)
        font = QFont("monospace")
        font.setPointSize(10)
        self._xml_text.setFont(font)
        xml_layout.addWidget(self._xml_text)
        
        self._notebook.addTab(self._details_page, _("Details"))
        self._notebook.addTab(self._xml_page, _("XML"))
        self._notebook.currentChanged.connect(self._page_changed)
        
        main_layout.addWidget(self._notebook)

    def _page_changed(self, index):
        if index == PAGE_XML:
            if self._details_changed:
                return
            self._xml_text.setText(self._srcxml)
        self._curpage = index

    def reset_state(self):
        self._xml_text.setText("")
        self._notebook.setCurrentIndex(PAGE_DETAILS)
        return True

    def get_xml(self):
        return self._xml_text.toPlainText()

    def set_xml(self, xml):
        self._srcxml = xml or ""
        self._xml_text.setText(self._srcxml)

    def set_xml_from_libvirtobject(self, libvirtobject):
        if not self.is_xml_selected():
            return
        xml = ""
        if libvirtobject:
            xml = libvirtobject.get_xml_to_define()
        self.set_xml(xml)

    def is_xml_selected(self):
        return self._curpage == PAGE_XML

    def cleanup(self):
        return True

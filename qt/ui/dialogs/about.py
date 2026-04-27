"""
About dialog for Qt frontend.

Application about dialog.
"""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt

from ..lib.i18n import _


class AboutDialog(QDialog):
    """
    About dialog for the application.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("About virt-manager"))
        self.setMinimumWidth(400)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("<h1>virt-manager</h1>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        version = QLabel(_("Qt/KDE Frontend v2.0.0"))
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        
        desc = QLabel(
            _("A graphical interface for managing virtual machines.\n\n"
            "Built with PyQt6 for KDE Plasma.")
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        layout.addSpacing(20)
        
        copyright_text = QLabel(_("Copyright 2006-2024 Red Hat"))
        copyright_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(copyright_text)
        
        layout.addSpacing(20)
        
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

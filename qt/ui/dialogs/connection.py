"""
Connection dialog for Qt frontend.

Dialog for adding/editing hypervisor connections.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel,
    QDialogButtonBox, QCheckBox
)
from PyQt6.QtCore import Qt

from ..lib.i18n import _


class ConnectionDialog(QDialog):
    """
    Connection dialog.
    
    Allows adding a new hypervisor connection with URI selection
    and connection options.
    """
    
    # Common connection URIs
    CONNECTION_PRESETS = [
        ("QEMU/KVM (User)", "qemu:///session"),
        ("QEMU/KVM (System)", "qemu:///system"),
        ("Xen", "xen:///"),
        ("LXC", "lxc:///"),
        ("Test", "test:///default"),
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Add Connection"))
        self.setMinimumWidth(450)
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup the UI."""
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(_("My VM Host"))
        form.addRow(_("Name:"), self._name_edit)
        
        self._preset_combo = QComboBox()
        self._preset_combo.addItem(_("Select a connection type..."), "")
        for name, uri in self.CONNECTION_PRESETS:
            self._preset_combo.addItem(name, uri)
        self._preset_combo.addItem(_("Custom..."), "custom")
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow(_("Type:"), self._preset_combo)
        
        self._uri_edit = QLineEdit()
        self._uri_edit.setPlaceholderText("qemu:///system")
        form.addRow(_("URI:"), self._uri_edit)
        
        layout.addLayout(form)
        
        self._autoconnect = QCheckBox(_("Auto-connect on startup"))
        self._autoconnect.setChecked(True)
        layout.addWidget(self._autoconnect)
        
        self._remote_group = QLabel(_("Remote connection options..."))
        self._remote_group.setStyleSheet("color: gray; padding: 8px 0;")
        layout.addWidget(self._remote_group)
        
        layout.addStretch()
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _on_preset_changed(self, index: int) -> None:
        """Handle preset selection."""
        data = self._preset_combo.currentData()
        
        if data == "custom":
            self._uri_edit.clear()
            self._uri_edit.setFocus()
        elif data:
            self._uri_edit.setText(data)
            
            name = self._preset_combo.currentText().split("(")[0].strip()
            if not self._name_edit.text():
                self._name_edit.setText(name)
    
    def _on_accept(self) -> None:
        """Validate and accept."""
        uri = self._uri_edit.text().strip()
        
        if not uri:
            self._uri_edit.setFocus()
            return
        
        self.accept()
    
    def get_uri(self) -> str:
        """Get the connection URI."""
        return self._uri_edit.text().strip()
    
    def get_autoconnect(self) -> bool:
        """Get autoconnect setting."""
        return self._autoconnect.isChecked()
    
    def get_name(self) -> str:
        """Get the connection name."""
        return self._name_edit.text().strip()

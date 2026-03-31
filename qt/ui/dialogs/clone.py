"""
Clone VM dialog for Qt frontend.

Dialog for cloning a virtual machine.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout,
    QLineEdit, QCheckBox, QDialogButtonBox,
    QLabel, QGroupBox
)
from PyQt6.QtCore import Qt

from ..lib.i18n import _


class CloneDialog(QDialog):
    """
    Dialog for cloning a virtual machine.
    """
    
    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self._vm = vm
        self.setWindowTitle(_("Clone VM - ") + vm.name)
        self.setMinimumWidth(450)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel(_("Clone: ") + self._vm.name))
        
        group = QGroupBox(_("New VM Settings"))
        form = QFormLayout(group)
        
        self._name_edit = QLineEdit()
        self._name_edit.setText(self._vm.name + "-clone")
        form.addRow(_("Name:"), self._name_edit)
        
        self._clone_disks = QCheckBox(_("Clone disk images"))
        self._clone_disks.setChecked(True)
        form.addRow("", self._clone_disks)
        
        self._clone_mac = QCheckBox(_("Regenerate MAC addresses"))
        self._clone_mac.setChecked(True)
        form.addRow("", self._clone_mac)
        
        layout.addWidget(group)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_clone_config(self):
        return {
            "name": self._name_edit.text(),
            "clone_disks": self._clone_disks.isChecked(),
            "clone_mac": self._clone_mac.isChecked(),
        }


class MigrateDialog(QDialog):
    """
    Dialog for migrating a virtual machine.
    """
    
    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self._vm = vm
        self.setWindowTitle(_("Migrate VM - ") + vm.name)
        self.setMinimumWidth(450)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel(_("Migrate: ") + self._vm.name))
        
        group = QGroupBox(_("Migration Settings"))
        form = QFormLayout(group)
        
        self._dest_uri = QLineEdit()
        self._dest_uri.setPlaceholderText("qemu+ssh://host/system")
        form.addRow(_("Destination URI:"), self._dest_uri)
        
        self._live_migrate = QCheckBox()
        form.addRow(_("Live migration:"), self._live_migrate)
        
        self._migrate_shared = QCheckBox()
        self._migrate_shared.setChecked(True)
        form.addRow(_("Shared disk:"), self._migrate_shared)
        
        layout.addWidget(group)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_migrate_config(self):
        return {
            "dest_uri": self._dest_uri.text(),
            "live": self._live_migrate.isChecked(),
            "shared": self._migrate_shared.isChecked(),
        }

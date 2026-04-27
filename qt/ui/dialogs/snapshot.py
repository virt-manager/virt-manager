"""
Snapshot dialog for Qt frontend.

Dialog for managing VM snapshots.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton,
    QDialogButtonBox, QLabel, QMessageBox, QInputDialog,
    QFormLayout, QGroupBox, QCheckBox, QTextEdit
)
from PyQt6.QtCore import Qt

from ..lib.i18n import _, ngettext


class SnapshotDialog(QDialog):
    """
    Dialog for managing VM snapshots.
    """
    
    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self._vm = vm
        self.setWindowTitle(_("Snapshots - %s") % self._vm.get_name())
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self._setup_ui()
        self._refresh()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        header = QLabel(_("Snapshots for: %s") % self._vm.get_name())
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(header)
        
        self._snap_table = QTableWidget()
        self._snap_table.setColumnCount(5)
        self._snap_table.setHorizontalHeaderLabels([
            _("Name"), _("Created"), _("State"), _("Parent"), _("Description")
        ])
        self._snap_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._snap_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._snap_table.setSortingEnabled(True)
        self._snap_table.horizontalHeader().setStretchLastSection(True)
        self._snap_table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._snap_table)
        
        self._details_group = QGroupBox(_("Snapshot Details"))
        self._details_layout = QFormLayout(self._details_group)
        self._details_name = QLabel("-")
        self._details_created = QLabel("-")
        self._details_state = QLabel("-")
        self._details_parent = QLabel("-")
        self._details_desc = QLabel("-")
        self._details_desc.setWordWrap(True)
        self._details_layout.addRow(_("Name:"), self._details_name)
        self._details_layout.addRow(_("Created:"), self._details_created)
        self._details_layout.addRow(_("State:"), self._details_state)
        self._details_layout.addRow(_("Parent:"), self._details_parent)
        self._details_layout.addRow(_("Description:"), self._details_desc)
        layout.addWidget(self._details_group)
        
        btn_layout = QHBoxLayout()
        
        self._create_btn = QPushButton(_("Create"))
        self._create_btn.clicked.connect(self._on_create)
        btn_layout.addWidget(self._create_btn)
        
        self._revert_btn = QPushButton(_("Revert to"))
        self._revert_btn.clicked.connect(self._on_revert)
        self._revert_btn.setEnabled(False)
        btn_layout.addWidget(self._revert_btn)
        
        self._delete_btn = QPushButton(_("Delete"))
        self._delete_btn.clicked.connect(self._on_delete)
        self._delete_btn.setEnabled(False)
        btn_layout.addWidget(self._delete_btn)
        
        btn_layout.addStretch()
        
        self._refresh_btn = QPushButton(_("Refresh"))
        self._refresh_btn.clicked.connect(self._refresh)
        btn_layout.addWidget(self._refresh_btn)
        
        layout.addLayout(btn_layout)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(_("Close"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
    
    def _on_selection_changed(self):
        snap = self._get_selected_snapshot()
        has_selection = snap is not None
        self._revert_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)
        
        if snap:
            self._update_snapshot_details(snap)
        else:
            self._details_name.setText("-")
            self._details_created.setText("-")
            self._details_state.setText("-")
            self._details_parent.setText("-")
            self._details_desc.setText("-")
    
    def _update_snapshot_details(self, snap):
        self._details_name.setText(snap.getName())
        
        try:
            import time
            xml = snap.getXMLDesc(0)
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            ctime = root.findtext("creationTime", "")
            if ctime:
                ts = int(ctime)
                self._details_created.setText(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)))
            
            state_elem = root.find(".//state")
            state_map = {
                'running': _('Running'),
                'shutoff': _('Shutoff'),
                'paused': _('Paused'),
                'disk-snapshot': _('Disk Snapshot'),
                'memory-snapshot': _('Memory Snapshot'),
                'metadata': _('Metadata Only'),
            }
            if state_elem is not None:
                state_text = state_elem.text or 'unknown'
                self._details_state.setText(state_map.get(state_text, state_text))
            else:
                self._details_state.setText("-")
            
            parent_elem = root.find(".//parent/name")
            if parent_elem is not None:
                self._details_parent.setText(parent_elem.text)
            else:
                self._details_parent.setText(_("None (root)"))
            
            desc_elem = root.find(".//description")
            if desc_elem is not None and desc_elem.text:
                self._details_desc.setText(desc_elem.text)
            else:
                self._details_desc.setText(_("No description"))
        except Exception:
            self._details_created.setText("-")
            self._details_state.setText("-")
            self._details_parent.setText("-")
            self._details_desc.setText("-")
    
    def _refresh(self):
        self._snap_table.setRowCount(0)
        
        if not self._vm or not self._vm.domain:
            return
        
        try:
            import time
            snapshots = self._vm.domain.listAllSnapshots()
            
            for snap in snapshots:
                row = self._snap_table.rowCount()
                self._snap_table.insertRow(row)
                
                self._snap_table.setItem(row, 0, QTableWidgetItem(snap.getName()))
                
                try:
                    xml = snap.getXMLDesc(0)
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(xml)
                    
                    ctime = root.findtext("creationTime", "")
                    if ctime:
                        ts = int(ctime)
                        ctime_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                        self._snap_table.setItem(row, 1, QTableWidgetItem(ctime_str))
                    else:
                        self._snap_table.setItem(row, 1, QTableWidgetItem(""))
                    
                    state_elem = root.find(".//state")
                    state_text = state_elem.text if state_elem is not None else ""
                    state_map = {
                        'running': _("Running"),
                        'shutoff': _("Shutoff"),
                        'paused': _("Paused"),
                        'disk-snapshot': _("Disk Snapshot"),
                        'memory-snapshot': _("Memory Snapshot"),
                        'metadata': _("Metadata"),
                    }
                    self._snap_table.setItem(row, 2, QTableWidgetItem(state_map.get(state_text, state_text or "-")))
                    
                    parent_elem = root.find(".//parent/name")
                    parent_text = parent_elem.text if parent_elem is not None else "-"
                    self._snap_table.setItem(row, 3, QTableWidgetItem(parent_text or "-"))
                    
                    desc_elem = root.find(".//description")
                    desc_text = desc_elem.text[:50] + "..." if desc_elem is not None and desc_elem.text and len(desc_elem.text) > 50 else (desc_elem.text or "")
                    self._snap_table.setItem(row, 4, QTableWidgetItem(desc_text))
                except Exception:
                    for col in range(1, 5):
                        self._snap_table.setItem(row, col, QTableWidgetItem(""))
        except Exception:
            pass
    
    def _get_selected_snapshot(self):
        selected = self._snap_table.selectedItems()
        if not selected:
            return None
        
        row = selected[0].row()
        name = self._snap_table.item(row, 0).text()
        
        try:
            return self._vm.domain.snapshotLookupByName(name)
        except Exception:
            return None
    
    def _on_create(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(_("Create Snapshot"))
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        form = QFormLayout()
        
        name_edit = QTextEdit()
        name_edit.setMaximumHeight(30)
        name_edit.setPlaceholderText(_("Optional snapshot name"))
        form.addRow(_("Name:"), name_edit)
        
        desc_edit = QTextEdit()
        desc_edit.setPlaceholderText(_("Optional description"))
        form.addRow(_("Description:"), desc_edit)
        
        layout.addLayout(form)
        
        memory_chk = QCheckBox(_("Include VM memory (save running state)"))
        memory_chk.setChecked(True)
        layout.addWidget(memory_chk)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dialog.accept)
        btns.rejected.connect(dialog.reject)
        layout.addWidget(btns)
        
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        
        name = name_edit.toPlainText().strip()
        desc = desc_edit.toPlainText().strip()
        include_memory = memory_chk.isChecked()
        
        try:
            import xml.etree.ElementTree as ET
            snap_elem = ET.Element("domainsnapshot")
            
            if name:
                name_elem = ET.SubElement(snap_elem, "name")
                name_elem.text = name
            
            if desc:
                desc_elem = ET.SubElement(snap_elem, "description")
                desc_elem.text = desc
            
            xml_str = ET.tostring(snap_elem, encoding='unicode')
            self._vm.domain.snapshotCreateXML(xml_str)
            self._refresh()
            QMessageBox.information(self, _("Success"), _("Snapshot created successfully"))
        except Exception as e:
            QMessageBox.critical(self, _("Error"), _("Failed to create snapshot: %s") % str(e))
    
    def _on_revert(self):
        snap = self._get_selected_snapshot()
        if not snap:
            return
        
        try:
            import xml.etree.ElementTree as ET
            xml_str = snap.getXMLDesc(0)
            root = ET.fromstring(xml_str)
            state_elem = root.find(".//state")
            state_text = state_elem.text if state_elem is not None else ""
            
            if state_text == 'running':
                msg = _("This will shut down the VM and restore it to the snapshot state.")
            elif state_text == 'paused':
                msg = _("This will restore the VM to the paused snapshot state.")
            else:
                msg = _("This will restore the VM disk state to the snapshot.")
            
            reply = QMessageBox.question(
                self, _("Revert to Snapshot"),
                _("Revert to snapshot '%s'?\n\n%s") % (snap.getName(), msg),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self._vm.domain.revertToSnapshot(snap)
                QMessageBox.information(self, _("Success"), _("VM reverted to snapshot"))
        except Exception as e:
            QMessageBox.critical(self, _("Error"), _("Failed to revert: %s") % str(e))
    
    def _on_delete(self):
        snap = self._get_selected_snapshot()
        if not snap:
            return
        
        reply = QMessageBox.question(
            self, _("Delete Snapshot"),
            _("Delete snapshot '%s'?\n\n%s") % (snap.getName(), _("This cannot be undone.")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                snap.delete(0)
                self._refresh()
            except Exception as e:
                QMessageBox.critical(self, _("Error"), _("Failed to delete snapshot: %s") % str(e))

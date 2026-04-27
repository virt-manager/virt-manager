from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QComboBox, QFormLayout, QMessageBox
)
from PyQt6.QtCore import Qt

from ..lib.i18n import _, ngettext


class vmmCreateVolume(QDialog):
    def __init__(self, conn, parent_pool, engine):
        super().__init__()
        self.conn = conn
        self.parent_pool = parent_pool
        self.engine = engine
        
        self.setWindowTitle(_("Create Storage Volume"))
        self.setModal(True)
        self.setMinimumSize(500, 350)
        
        self._init_ui()
        self._reset_state()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        name_layout = QFormLayout()
        name_box = QHBoxLayout()
        self._name_entry = QLineEdit()
        self._name_suffix = QLabel(".qcow2")
        name_box.addWidget(self._name_entry)
        name_box.addWidget(self._name_suffix)
        name_layout.addRow(_("Name:"), name_box)
        layout.addLayout(name_layout)
        
        cap_layout = QFormLayout()
        self._capacity = QLineEdit("20")
        cap_unit = QLabel(_("GB"))
        cap_box = QHBoxLayout()
        cap_box.addWidget(self._capacity)
        cap_box.addWidget(cap_unit)
        cap_layout.addRow(_("Capacity:"), cap_box)
        layout.addLayout(cap_layout)
        
        self._nonsparse = QCheckBox(_("Pre-allocate storage (non-sparse)"))
        layout.addWidget(self._nonsparse)
        
        format_layout = QFormLayout()
        self._format_combo = QComboBox()
        self._format_combo.addItems([_("raw"), _("qcow2")])
        self._format_combo.setCurrentIndex(1)
        format_layout.addRow(_("Format:"), self._format_combo)
        layout.addLayout(format_layout)
        
        backing_layout = QFormLayout()
        self._backing_store = QLineEdit()
        backing_browse = QPushButton(_("Browse..."))
        backing_browse.clicked.connect(self._browse_backing)
        backing_box = QHBoxLayout()
        backing_box.addWidget(self._backing_store)
        backing_box.addWidget(backing_browse)
        backing_layout.addRow(_("Backing Store:"), backing_box)
        layout.addLayout(backing_layout)
        
        self._pool_info = QLabel()
        layout.addWidget(self._pool_info)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        create_btn = QPushButton(_("Create"))
        create_btn.clicked.connect(self._finish)
        create_btn.setDefault(True)
        button_layout.addWidget(create_btn)
        
        layout.addLayout(button_layout)

    def _reset_state(self):
        self._name_entry.setText("vol")
        self._capacity.setText("20")
        self._nonsparse.setChecked(False)
        self._format_combo.setCurrentIndex(1)
        self._backing_store.clear()
        
        if self.parent_pool:
            avail = self.parent_pool.get_pretty_available()
            self._pool_info.setText(_("Pool '%s' available: %s") % (self.parent_pool.get_name(), avail))

    def _browse_backing(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, _("Choose backing file"))
        if path:
            self._backing_store.setText(path)

    def _finish(self):
        name = self._name_entry.text().strip()
        if not name:
            QMessageBox.warning(self, _("Error"), _("Please enter a volume name"))
            return
        
        try:
            capacity_gb = float(self._capacity.text())
        except ValueError:
            QMessageBox.warning(self, _("Error"), _("Invalid capacity value"))
            return
        
        fmt = self._format_combo.currentText()
        backing = self._backing_store.text().strip()
        nonsparse = self._nonsparse.isChecked()
        
        suffix = f".{fmt}" if fmt != "raw" else ""
        full_name = name + suffix
        
        try:
            from virtinst import StorageVolume
            
            conn = self.conn.get_backend()
            vol = StorageVolume(conn)
            vol.pool = self.parent_pool.get_backend()
            vol.name = full_name
            vol.capacity = capacity_gb * 1024 * 1024 * 1024
            
            if nonsparse:
                vol.allocation = vol.capacity
            
            if backing:
                vol.backing_store = backing
            if fmt != "auto":
                vol.format = fmt
            
            vol.validate()
            
            xml = vol.get_xml()
            
            from .asyncjob import vmmAsyncJob
            
            def async_create(job, vol_xml):
                conn = self.conn.get_backend()
                newpool = conn.storagePoolLookupByName(self.parent_pool.get_name())
                newvol = newpool.createXML(vol_xml, 0)
                return newvol
            
            def finish_cb(error, details):
                if error:
                    QMessageBox.critical(self, _("Error"), _("Error creating volume: %s\n%s") % (error, details))
                else:
                    self.parent_pool.refresh()
                    self.accept()
            
            vmmAsyncJob(
                async_create,
                [xml],
                finish_cb,
                [],
                _("Creating storage volume"),
                _("Creating..."),
                self
            ).run()
            
        except Exception as e:
            QMessageBox.critical(self, _("Error"), _("Error creating volume: %s") % e)

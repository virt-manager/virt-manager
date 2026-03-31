import os

from ..lib.i18n import _, ngettext
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QComboBox, QGroupBox, QFormLayout,
    QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt


POOL_TYPES = [
    ("dir", _("Filesystem Directory")),
    ("fs", _("Filesystem Partition")),
    ("netfs", _("Network NFS")),
    ("logical", _("LVM Volume Group")),
    ("disk", _("Physical Disk Device")),
    ("iscsi", _("iSCSI Target")),
    ("scsi", _("SCSI Device")),
    ("mpath", _("Multipath Device")),
    ("rbd", _("RADOS Block Device")),
    ("sheepdog", _("Sheepdog Device")),
    ("gluster", _("GlusterFS")),
]


class vmmCreatePool(QDialog):
    def __init__(self, conn, engine):
        super().__init__()
        self.conn = conn
        self.engine = engine
        
        self.setWindowTitle(_("Create Storage Pool"))
        self.setModal(True)
        self.setMinimumSize(600, 400)
        
        self._init_ui()
        self._reset_state()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        name_layout = QFormLayout()
        self._name_entry = QLineEdit()
        name_layout.addRow(_("Name:"), self._name_entry)
        layout.addLayout(name_layout)
        
        type_layout = QFormLayout()
        self._type_combo = QComboBox()
        for typ, desc in POOL_TYPES:
            self._type_combo.addItem(desc, typ)
        self._type_combo.currentIndexChanged.connect(self._pool_type_changed)
        type_layout.addRow(_("Type:"), self._type_combo)
        layout.addLayout(type_layout)
        
        self._target_group = QGroupBox(_("Target Path"))
        target_layout = QFormLayout(self._target_group)
        self._target_path = QLineEdit()
        target_browse = QPushButton(_("Browse..."))
        target_browse.clicked.connect(self._browse_target)
        target_layout.addRow(_("Path:"), self._target_path)
        target_layout.addRow("", target_browse)
        layout.addWidget(self._target_group)
        
        self._source_group = QGroupBox(_("Source Path"))
        source_layout = QFormLayout(self._source_group)
        self._source_path = QLineEdit()
        source_browse = QPushButton(_("Browse..."))
        source_browse.clicked.connect(self._browse_source)
        source_layout.addRow(_("Path:"), self._source_path)
        source_layout.addRow("", source_browse)
        layout.addWidget(self._source_group)
        
        self._host_group = QGroupBox(_("Host"))
        host_layout = QFormLayout(self._host_group)
        self._host_entry = QLineEdit()
        host_layout.addRow(_("Hostname:"), self._host_entry)
        layout.addWidget(self._host_group)
        
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
        self._name_entry.setText("pool")
        self._type_combo.setCurrentIndex(0)
        self._target_path.clear()
        self._source_path.clear()
        self._host_entry.clear()

    def _pool_type_changed(self, index):
        pool_type = self._type_combo.currentData()
        
        self._target_group.setVisible(pool_type in ["dir", "fs", "netfs", "logical", "disk"])
        self._source_group.setVisible(pool_type in ["fs", "netfs", "logical", "disk", "iscsi"])
        self._host_group.setVisible(pool_type in ["netfs", "iscsi", "rbd", "gluster"])

    def _browse_target(self):
        path = QFileDialog.getExistingDirectory(self, _("Choose target directory"))
        if path:
            self._target_path.setText(path)

    def _browse_source(self):
        path = QFileDialog.getExistingDirectory(self, _("Choose source path"))
        if path:
            self._source_path.setText(path)

    def _finish(self):
        name = self._name_entry.text().strip()
        if not name:
            QMessageBox.warning(self, _("Error"), _("Please enter a pool name"))
            return
        
        pool_type = self._type_combo.currentData()
        target = self._target_path.text().strip() if self._target_group.isVisible() else None
        source = self._source_path.text().strip() if self._source_group.isVisible() else None
        host = self._host_entry.text().strip() if self._host_group.isVisible() else None
        
        try:
            from virtinst import StoragePool
            
            conn = self.conn.get_backend()
            pool = StoragePool(conn)
            pool.name = name
            pool.type = pool_type
            
            if target:
                pool.target_path = target
            if source:
                pool.source_path = source
            if host:
                hostobj = pool.hosts.add_new()
                hostobj.name = host
            
            pool.validate()
            
            xml = pool.get_xml()
            
            from .asyncjob import vmmAsyncJob
            
            def async_create(job, pool_xml, pool_type):
                conn = self.conn.get_backend()
                poolobj = conn.storagePoolDefineXML(pool_xml, 0)
                if pool_type in ["dir", "fs", "netfs"]:
                    os.makedirs(target or "/var/lib/libvirt/images", exist_ok=True)
                poolobj.create(0)
                poolobj.setAutostart(True)
            
            def finish_cb(error, details):
                if error:
                    QMessageBox.critical(self, _("Error"), _("Error creating pool: %s\n%s") % (error, details))
                else:
                    self.accept()
            
            vmmAsyncJob(
                async_create,
                [xml, pool_type],
                finish_cb,
                [],
                _("Creating storage pool"),
                _("Creating..."),
                self
            ).run()
            
        except Exception as e:
            QMessageBox.critical(self, _("Error"), _("Error creating pool: %s") % e)

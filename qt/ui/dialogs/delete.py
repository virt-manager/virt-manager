from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QCheckBox, QScrollArea, QWidget,
    QGridLayout, QGroupBox, QMessageBox, QProgressBar
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from ..lib.i18n import _


STORAGE_ROW_CONFIRM = 0
STORAGE_ROW_CANT_DELETE = 1
STORAGE_ROW_PATH = 2
STORAGE_ROW_TARGET = 3
STORAGE_ROW_TOOLTIP = 4


class _DiskData:
    @staticmethod
    def from_disk(disk):
        return _DiskData(
            disk.target,
            disk.get_source_path(),
            disk.read_only,
            disk.shareable,
            disk.device in ["cdrom", "floppy"],
        )

    def __init__(self, label, path, ro, shared, is_media):
        self.label = label
        self.path = path
        self.ro = ro
        self.shared = shared
        self.is_media = is_media


class vmmDeleteDialog(QDialog):
    def __init__(self, vm, conn, engine):
        super().__init__()
        self.vm = vm
        self.conn = conn
        self.engine = engine
        
        self.setWindowTitle(_("Delete Virtual Machine"))
        self.setModal(True)
        self.setMinimumSize(600, 400)
        
        self._init_ui()
        self._populate_storage()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        header = QLabel(f"<span size='large'>{_('Delete')} '{self.vm.get_name()}'</span>")
        layout.addWidget(header)
        
        if self.vm.is_active():
            warn_box = QGroupBox()
            warn_layout = QVBoxLayout(warn_box)
            warn_label = QLabel(_("Warning: The virtual machine is running. It will be powered off before deletion."))
            warn_label.setStyleSheet("color: #721c24; background-color: #f8d7da; padding: 8px; border-radius: 4px;")
            warn_layout.addWidget(warn_label)
            layout.addWidget(warn_box)
        
        self._remove_storage_check = QCheckBox(_("Delete associated storage files"))
        self._remove_storage_check.setChecked(True)
        self._remove_storage_check.toggled.connect(self._toggle_remove_storage)
        layout.addWidget(self._remove_storage_check)
        
        self._storage_scroll = QScrollArea()
        self._storage_scroll.setWidgetResizable(True)
        self._storage_list = QTreeWidget()
        self._storage_list.setHeaderLabels([_("Delete"), _("Target"), _("Storage Path"), _("Info")])
        self._storage_list.setColumnWidth(0, 50)
        self._storage_list.setColumnWidth(1, 80)
        self._storage_scroll.setWidget(self._storage_list)
        layout.addWidget(self._storage_scroll)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton(_("Delete"))
        ok_btn.clicked.connect(self._finish)
        ok_btn.setDefault(True)
        button_layout.addWidget(ok_btn)
        
        layout.addLayout(button_layout)

    def _populate_storage(self):
        self._storage_list.clear()
        
        for disk in self.vm.xmlobj.devices.disk:
            diskdata = _DiskData.from_disk(disk)
            if not diskdata.path:
                continue
            
            item = QTreeWidgetItem(self._storage_list)
            item.setText(STORAGE_ROW_PATH, diskdata.path)
            item.setText(STORAGE_ROW_TARGET, diskdata.label)
            item.setCheckState(STORAGE_ROW_CONFIRM, Qt.CheckState.Checked)
            
            can_delete = self._can_delete(diskdata.path)
            if not can_delete:
                item.setCheckState(STORAGE_ROW_CONFIRM, Qt.CheckState.Unchecked)
                item.setToolTip(STORAGE_ROW_PATH, _("Cannot delete this storage"))
                item.setForeground(STORAGE_ROW_PATH, Qt.GlobalColor.gray)

    def _can_delete(self, path):
        import os
        import stat
        
        if self.conn.is_remote():
            return False
        if not os.path.exists(path):
            return False
        if not os.access(os.path.dirname(path), os.W_OK):
            return False
        if stat.S_ISBLK(os.stat(path)[stat.ST_MODE]):
            return False
        return True

    def _toggle_remove_storage(self, checked):
        if not checked:
            for i in range(self._storage_list.topLevelItemCount()):
                item = self._storage_list.topLevelItem(i)
                item.setCheckState(STORAGE_ROW_CONFIRM, Qt.CheckState.Unchecked)

    def _finish(self):
        paths = self._get_paths_to_delete()
        
        if paths:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle(_("Confirm Delete"))
            msg.setText(_("Are you sure you want to delete the storage?"))
            msg.setInformativeText(_("The following paths will be deleted:") + "\n\n" + "\n".join(paths))
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if msg.exec() != QMessageBox.StandardButton.Yes:
                return
        
        from .asyncjob import vmmAsyncJob
        
        def async_delete(job, vm, paths):
            if vm.is_active():
                vm.destroy()
            for path in paths:
                try:
                    conn = self.conn.get_backend()
                    try:
                        vol = conn.storageVolLookupByPath(path)
                        vol.delete(0)
                    except Exception:
                        import os
                        os.unlink(path)
                except Exception:
                    pass
            vm.delete()
        
        self.hide()
        
        def finish_cb(error, details):
            if error:
                err = QMessageBox()
                err.setIcon(QMessageBox.Icon.Critical)
                err.setText(f"{_('Error')}: {error}")
                err.exec()
            self.accept()
        
        vmmAsyncJob(
            async_delete,
            [self.vm, paths],
            finish_cb,
            [],
            _("Deleting virtual machine"),
            _("Deleting..."),
            self
        ).run()


class vmmDeleteStorage(QDialog):
    def __init__(self, vm, disk, engine):
        super().__init__()
        self.vm = vm
        self.disk = disk
        self.engine = engine
        
        self.setWindowTitle(_("Remove Disk Device"))
        self.setModal(True)
        self.setMinimumSize(500, 200)
        
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        header = QLabel(f"<span size='large'>{_('Remove disk device')} '{self.disk.target}'</span>")
        layout.addWidget(header)
        
        self._remove_storage_check = QCheckBox(_("Delete associated storage file"))
        self._remove_storage_check.setChecked(False)
        self._remove_storage_check.toggled.connect(self._toggle_remove_storage)
        layout.addWidget(self._remove_storage_check)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton(_("Remove"))
        ok_btn.clicked.connect(self._finish)
        ok_btn.setDefault(True)
        button_layout.addWidget(ok_btn)
        
        layout.addLayout(button_layout)

    def _toggle_remove_storage(self, checked):
        if checked and self.disk and self.disk.target:
            warning_msg = QMessageBox()
            warning_msg.setIcon(QMessageBox.Icon.Warning)
            warning_msg.setWindowTitle(_("Warning"))
            warning_msg.setText(_("Are you sure you want to delete the storage file?"))
            warning_msg.setInformativeText(
                _("This will permanently delete the storage file and all data on it.")
            )
            warning_msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if warning_msg.exec() == QMessageBox.StandardButton.No:
                self._remove_storage_check.setChecked(False)

    def _finish(self):
        try:
            self.vm.remove_device(self.disk)
            try:
                self.vm.detach_device(self.disk)
            except Exception:
                pass
        except Exception as e:
            err = QMessageBox()
            err.setIcon(QMessageBox.Icon.Critical)
            err.setText(f"{_('Error removing device')}: {e}")
            err.exec()
            return
        
        self.accept()

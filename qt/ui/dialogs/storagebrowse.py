from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QHeaderView,
    QMenu
)
from PyQt6.QtCore import Qt

from ..lib.i18n import _


class vmmStorageBrowser(QDialog):
    REASON_IMAGE = "image"
    REASON_ISO_MEDIA = "isomedia"
    REASON_FLOPPY_MEDIA = "floppymedia"
    REASON_FS = "fs"

    def __init__(self, conn, engine):
        super().__init__()
        self.conn = conn
        self.engine = engine
        self._browse_reason = self.REASON_IMAGE
        self._finish_cb = None
        self._vol_sensitive_cb = None
        
        self.setWindowTitle(_("Storage Browser"))
        self.setModal(True)
        self.setMinimumSize(700, 500)
        
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        self._pool_list = QTreeWidget()
        self._pool_list.setHeaderLabels([_("Storage Pools"), _("State")])
        self._pool_list.setColumnWidth(0, 300)
        self._pool_list.itemClicked.connect(self._pool_selected)
        layout.addWidget(self._pool_list)
        
        self._vol_list = QTreeWidget()
        self._vol_list.setHeaderLabels([_("Volumes"), _("Size"), _("Format"), _("Used By")])
        self._vol_list.setColumnWidth(0, 200)
        self._vol_list.setColumnWidth(1, 80)
        self._vol_list.setColumnWidth(2, 80)
        self._vol_list.itemDoubleClicked.connect(self._volume_chosen)
        self._vol_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._vol_list.customContextMenuRequested.connect(self._vol_context_menu)
        layout.addWidget(self._vol_list)
        
        button_layout = QHBoxLayout()
        
        if not self.conn.is_remote():
            browse_local = QPushButton(_("Browse Local..."))
            browse_local.clicked.connect(self._browse_local)
            button_layout.addWidget(browse_local)
        else:
            button_layout.addWidget(QLabel(_("Cannot use local storage on remote connection")))
        
        button_layout.addStretch()
        
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        self._choose_btn = QPushButton(_("Choose Volume"))
        self._choose_btn.clicked.connect(self._volume_chosen)
        self._choose_btn.setEnabled(False)
        button_layout.addWidget(self._choose_btn)
        
        layout.addLayout(button_layout)
        
        self._populate_pools()

    def set_finish_cb(self, callback):
        self._finish_cb = callback

    def set_vm_name(self, name):
        self._vm_name = name

    def set_browse_reason(self, reason):
        self._browse_reason = reason

    def _populate_pools(self):
        self._pool_list.clear()
        
        for pool in self.conn.list_pools():
            item = QTreeWidgetItem(self._pool_list)
            item.setText(0, pool.get_name())
            item.setText(1, pool.run_status())
            item.setData(0, Qt.ItemDataRole.UserRole, pool)

    def _pool_selected(self, item, column):
        pool = item.data(0, Qt.ItemDataRole.UserRole)
        if not pool:
            return
        
        self._vol_list.clear()
        
        if not pool.is_active():
            return
        
        for vol in pool.get_volumes():
            try:
                vol_item = QTreeWidgetItem(self._vol_list)
                vol_item.setText(0, vol.get_pretty_name(pool.get_type()))
                vol_item.setText(1, vol.get_pretty_capacity())
                vol_item.setText(2, vol.get_format() or "")
                vol_item.setData(0, Qt.ItemDataRole.UserRole, vol)
            except Exception:
                continue

    def _volume_chosen(self, item=None, column=None):
        selected = self._vol_list.selectedItems()
        if not selected:
            return
        
        vol = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if not vol:
            return
        
        try:
            path = vol.get_target_path()
            if self._finish_cb:
                self._finish_cb(self, path)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, _("Error"), f"{_('Error selecting volume')}: {e}")

    def _vol_context_menu(self, pos):
        menu = QMenu(self)
        copy_action = menu.addAction(_("Copy Volume Path"))
        action = menu.exec(self._vol_list.mapToGlobal(pos))
        if action == copy_action:
            selected = self._vol_list.selectedItems()
            if selected:
                vol = selected[0].data(0, Qt.ItemDataRole.UserRole)
                if vol:
                    from PyQt6.QtWidgets import QApplication
                    clipboard = QApplication.clipboard()
                    try:
                        clipboard.setText(vol.get_target_path())
                    except Exception:
                        pass

    def _browse_local(self):
        from PyQt6.QtWidgets import QFileDialog
        
        if self._browse_reason == self.REASON_IMAGE:
            path, _ = QFileDialog.getOpenFileName(self, _("Locate existing storage"))
        elif self._browse_reason == self.REASON_ISO_MEDIA:
            path, _ = QFileDialog.getOpenFileName(self, _("Locate ISO media"))
        elif self._browse_reason == self.REASON_FS:
            path = QFileDialog.getExistingDirectory(self, _("Locate directory volume"))
        else:
            path, _ = QFileDialog.getOpenFileName(self, _("Locate storage"))
        
        if path:
            if self._finish_cb:
                self._finish_cb(self, path)
            self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        self.conn.schedule_priority_tick(pollpool=True)

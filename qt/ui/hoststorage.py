from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QCheckBox, QGroupBox, QWidget,
    QFormLayout, QScrollArea
)
from PyQt6.QtCore import Qt

from .lib.i18n import _


class vmmHostStorage(QWidget):
    def __init__(self, conn, engine):
        super().__init__()
        self.conn = conn
        self.engine = None
        
        self._addpool = None
        self._addvol = None
        
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        self._pool_list = QTreeWidget()
        self._pool_list.setHeaderLabels([_("Storage Pools"), _("State"), _("Size")])
        self._pool_list.setColumnWidth(0, 250)
        self._pool_list.itemClicked.connect(self._pool_selected)
        layout.addWidget(self._pool_list)
        
        self._vol_list = QTreeWidget()
        self._vol_list.setHeaderLabels([_("Volumes"), _("Size"), _("Format"), _("Used By")])
        self._vol_list.setColumnWidth(0, 200)
        self._vol_list.itemDoubleClicked.connect(self._vol_activated)
        layout.addWidget(self._vol_list)
        
        button_layout = QHBoxLayout()
        
        pool_add = QPushButton(_("Add Pool..."))
        pool_add.clicked.connect(self._pool_add)
        button_layout.addWidget(pool_add)
        
        self._pool_start = QPushButton(_("Start"))
        self._pool_start.clicked.connect(self._pool_start)
        button_layout.addWidget(self._pool_start)
        
        self._pool_stop = QPushButton(_("Stop"))
        self._pool_stop.clicked.connect(self._pool_stop)
        button_layout.addWidget(self._pool_stop)
        
        self._pool_delete = QPushButton(_("Delete"))
        self._pool_delete.clicked.connect(self._pool_delete)
        button_layout.addWidget(self._pool_delete)
        
        self._pool_refresh = QPushButton(_("Refresh"))
        self._pool_refresh.clicked.connect(self._pool_refresh)
        button_layout.addWidget(self._pool_refresh)
        
        button_layout.addStretch()
        
        vol_add = QPushButton(_("Add Volume..."))
        vol_add.clicked.connect(self._vol_add)
        button_layout.addWidget(vol_add)
        
        self._vol_delete = QPushButton(_("Delete Volume"))
        self._vol_delete.clicked.connect(self._vol_delete)
        self._vol_delete.setEnabled(False)
        button_layout.addWidget(self._vol_delete)
        
        layout.addLayout(button_layout)
        
        self._populate_pools()

    def _populate_pools(self):
        self._pool_list.clear()
        
        for pool in self.conn.list_pools():
            item = QTreeWidgetItem(self._pool_list)
            item.setText(0, pool.get_name())
            item.setText(1, pool.run_status())
            
            cap = pool.get_capacity()
            alloc = pool.get_allocation()
            if cap and alloc is not None:
                percent = int((float(alloc) / float(cap)) * 100)
                item.setText(2, f"{percent}%")
            
            item.setData(0, Qt.ItemDataRole.UserRole, pool)
            
            if pool.is_active():
                item.setCheckColumn(0)

    def _pool_selected(self, item, column):
        pool = item.data(0, Qt.ItemDataRole.UserRole)
        if not pool:
            return
        
        self._vol_list.clear()
        
        active = pool.is_active()
        self._pool_start.setEnabled(not active)
        self._pool_stop.setEnabled(active)
        self._pool_delete.setEnabled(not active)
        self._pool_refresh.setEnabled(active)
        self._vol_delete.setEnabled(False)
        
        if not active:
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

    def _vol_activated(self, item, column):
        self._vol_delete.setEnabled(True)

    def _pool_add(self):
        from .createnet import vmmCreateNetwork
        from PyQt6.QtWidgets import QApplication
        parent = QApplication.topLevelWidgets()[0] if QApplication.topLevelWidgets() else None
        
        dialog = vmmCreateNetwork(self.conn, self.engine)
        dialog.exec()

    def _pool_start(self):
        item = self._pool_list.currentItem()
        if not item:
            return
        pool = item.data(0, Qt.ItemDataRole.UserRole)
        if pool:
            try:
                pool.start()
                self._populate_pools()
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, _("Error"), f"{_('Error starting pool')}: {e}")

    def _pool_stop(self):
        item = self._pool_list.currentItem()
        if not item:
            return
        pool = item.data(0, Qt.ItemDataRole.UserRole)
        if pool:
            try:
                pool.stop()
                self._populate_pools()
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, _("Error"), f"{_('Error stopping pool')}: {e}")

    def _pool_delete(self):
        item = self._pool_list.currentItem()
        if not item:
            return
        pool = item.data(0, Qt.ItemDataRole.UserRole)
        if pool:
            from PyQt6.QtWidgets import QMessageBox
            result = QMessageBox.question(
                self, _("Delete Pool"),
                _("Are you sure you want to permanently delete the pool %s?") % pool.get_name()
            )
            if result == QMessageBox.StandardButton.Yes:
                try:
                    pool.delete()
                    self._populate_pools()
                except Exception as e:
                    QMessageBox.critical(self, _("Error"), f"{_('Error deleting pool')}: {e}")

    def _pool_refresh(self):
        item = self._pool_list.currentItem()
        if not item:
            return
        pool = item.data(0, Qt.ItemDataRole.UserRole)
        if pool:
            try:
                pool.refresh()
                self._pool_selected(item, 0)
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, _("Error"), f"{_('Error refreshing pool')}: {e}")

    def _vol_add(self):
        item = self._pool_list.currentItem()
        if not item:
            return
        pool = item.data(0, Qt.ItemDataRole.UserRole)
        if pool and pool.is_active():
            from .createvol import vmmCreateVolume
            dialog = vmmCreateVolume(self.conn, pool, self.engine)
            dialog.exec()
            self._pool_selected(item, 0)

    def _vol_delete(self):
        pool_item = self._pool_list.currentItem()
        vol_item = self._vol_list.currentItem()
        if not pool_item or not vol_item:
            return
        
        pool = pool_item.data(0, Qt.ItemDataRole.UserRole)
        vol = vol_item.data(0, Qt.ItemDataRole.UserRole)
        
        if vol:
            from PyQt6.QtWidgets import QMessageBox
            result = QMessageBox.question(
                self, _("Delete Volume"),
                _("Are you sure you want to permanently delete the volume %s?") % vol.get_name()
            )
            if result == QMessageBox.StandardButton.Yes:
                try:
                    vol.delete()
                    pool.refresh()
                    self._pool_selected(pool_item, 0)
                except Exception as e:
                    QMessageBox.critical(self, _("Error"), f"{_('Error deleting volume')}: {e}")

    def refresh_page(self):
        self._populate_pools()
        self.conn.schedule_priority_tick(pollpool=True)

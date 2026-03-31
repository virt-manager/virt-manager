"""
Storage management window for Qt frontend.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QSplitter,
    QHeaderView, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSlot

from .lib.i18n import _


class StorageWindow(QWidget):
    """
    Storage management window.
    
    Shows storage pools and volumes with management options.
    """
    
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._selected_pool = None
        self._setup_ui()
        self._refresh()
    
    def _setup_ui(self):
        self.setWindowTitle(_("Storage"))
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        header = QLabel(_("Storage Pools"))
        header.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(header)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        self._pool_table = QTableWidget()
        self._pool_table.setColumnCount(3)
        self._pool_table.setHorizontalHeaderLabels([_("Name"), _("State"), _("Capacity")])
        self._pool_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pool_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._pool_table.horizontalHeader().setStretchLastSection(True)
        self._pool_table.itemSelectionChanged.connect(self._on_pool_selected)
        splitter.addWidget(self._pool_table)
        
        self._vol_table = QTableWidget()
        self._vol_table.setColumnCount(3)
        self._vol_table.setHorizontalHeaderLabels([_("Name"), _("Size"), _("Path")])
        self._vol_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._vol_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._vol_table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self._vol_table)
        
        splitter.setSizes([400, 400])
        
        btn_layout = QHBoxLayout()
        
        self._start_btn = QPushButton(_("Start"))
        self._start_btn.clicked.connect(self._on_start_pool)
        btn_layout.addWidget(self._start_btn)
        
        self._stop_btn = QPushButton(_("Stop"))
        self._stop_btn.clicked.connect(self._on_stop_pool)
        btn_layout.addWidget(self._stop_btn)
        
        self._refresh_btn = QPushButton(_("Refresh"))
        self._refresh_btn.clicked.connect(self._refresh)
        btn_layout.addWidget(self._refresh_btn)
        
        self._create_vol_btn = QPushButton(_("Create Volume"))
        self._create_vol_btn.clicked.connect(self._on_create_volume)
        btn_layout.addWidget(self._create_vol_btn)
        
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
    
    def _refresh(self):
        self._pool_table.setRowCount(0)
        self._vol_table.setRowCount(0)
        self._selected_pool = None
        
        if not self._conn or not self._conn.backend:
            return
        
        try:
            pools = self._conn.backend.listAllStoragePools()
            for pool in pools:
                try:
                    wrapper = self._conn._pool_cache.get(pool.name()) if hasattr(self._conn, '_pool_cache') else None
                    row = self._pool_table.rowCount()
                    self._pool_table.insertRow(row)
                    self._pool_table.setItem(row, 0, QTableWidgetItem(pool.name()))
                    info = pool.info()
                    state_map = {0: _("Inactive"), 1: _("Initializing"), 2: _("Running"), 3: _("Degraded"), 4: _("Failed")}
                    self._pool_table.setItem(row, 1, QTableWidgetItem(state_map.get(info[0], _("Unknown"))))
                    self._pool_table.setItem(row, 2, QTableWidgetItem(self._format_size(info[1])))
                except Exception:
                    pass
        except Exception as e:
            pass
    
    def _on_pool_selected(self):
        selected = self._pool_table.selectedItems()
        if not selected:
            self._selected_pool = None
            self._vol_table.setRowCount(0)
            return
        
        row = selected[0].row()
        pool_name = self._pool_table.item(row, 0).text()
        
        try:
            pool = self._conn.backend.storagePoolLookupByName(pool_name)
            self._selected_pool = pool
            
            self._vol_table.setRowCount(0)
            vols = pool.listAllVolumes()
            for vol in vols:
                row = self._vol_table.rowCount()
                self._vol_table.insertRow(row)
                self._vol_table.setItem(row, 0, QTableWidgetItem(vol.name()))
                info = vol.info()
                self._vol_table.setItem(row, 1, QTableWidgetItem(self._format_size(info[1])))
                try:
                    self._vol_table.setItem(row, 2, QTableWidgetItem(vol.path()))
                except Exception:
                    self._vol_table.setItem(row, 2, QTableWidgetItem(""))
        except Exception:
            self._selected_pool = None
    
    def _on_start_pool(self):
        if not self._selected_pool:
            return
        try:
            self._selected_pool.create(0)
            self._refresh()
        except Exception as e:
            QMessageBox.critical(self, _("Error"), f"{_('Failed to start pool')}: {e}")
    
    def _on_stop_pool(self):
        if not self._selected_pool:
            return
        try:
            self._selected_pool.destroy()
            self._refresh()
        except Exception as e:
            QMessageBox.critical(self, _("Error"), f"{_('Failed to stop pool')}: {e}")
    
    def _on_create_volume(self):
        if not self._selected_pool:
            return
        
        path, _ = QFileDialog.getSaveFileName(self, _("Volume Path"))
        if not path:
            return
        
        try:
            import libvirt
            vol_xml = f"""
            <volume type='file'>
                <name>{path.split('/')[-1]}</name>
                <allocation>0</allocation>
                <capacity unit='G'>10</capacity>
                <target>
                    <path>{path}</path>
                </target>
            </volume>
            """
            self._selected_pool.createXML(vol_xml, 0)
            self._on_pool_selected()
        except Exception as e:
            QMessageBox.critical(self, _("Error"), f"{_('Failed to create volume')}: {e}")
    
    def _format_size(self, bytes_val):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"


class NetworkWindow(QWidget):
    """
    Network management window.
    """
    
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._setup_ui()
        self._refresh()
    
    def _setup_ui(self):
        self.setWindowTitle(_("Networks"))
        self.resize(600, 400)
        
        layout = QVBoxLayout(self)
        
        header = QLabel(_("Virtual Networks"))
        header.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(header)
        
        self._net_table = QTableWidget()
        self._net_table.setColumnCount(3)
        self._net_table.setHorizontalHeaderLabels([_("Name"), _("State"), _("Bridge")])
        self._net_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._net_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._net_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._net_table)
        
        btn_layout = QHBoxLayout()
        
        self._start_btn = QPushButton(_("Start"))
        self._start_btn.clicked.connect(self._on_start_network)
        btn_layout.addWidget(self._start_btn)
        
        self._stop_btn = QPushButton(_("Stop"))
        self._stop_btn.clicked.connect(self._on_stop_network)
        btn_layout.addWidget(self._stop_btn)
        
        self._refresh_btn = QPushButton(_("Refresh"))
        self._refresh_btn.clicked.connect(self._refresh)
        btn_layout.addWidget(self._refresh_btn)
        
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
    
    def _refresh(self):
        self._net_table.setRowCount(0)
        
        if not self._conn or not self._conn.backend:
            return
        
        try:
            networks = self._conn.backend.listAllNetworks()
            for net in networks:
                row = self._net_table.rowCount()
                self._net_table.insertRow(row)
                self._net_table.setItem(row, 0, QTableWidgetItem(net.name()))
                self._net_table.setItem(row, 1, QTableWidgetItem(_("Active") if net.isActive() else _("Inactive")))
                
                try:
                    xml = net.XMLDesc(0)
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(xml)
                    bridge = root.find("bridge")
                    bridge_name = bridge.get("name", "") if bridge is not None else ""
                    self._net_table.setItem(row, 2, QTableWidgetItem(bridge_name))
                except Exception:
                    self._net_table.setItem(row, 2, QTableWidgetItem(""))
        except Exception:
            pass
    
    def _get_selected_network(self):
        selected = self._net_table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        name = self._net_table.item(row, 0).text()
        try:
            return self._conn.backend.networkLookupByName(name)
        except Exception:
            return None
    
    def _on_start_network(self):
        net = self._get_selected_network()
        if net:
            try:
                net.create()
                self._refresh()
            except Exception as e:
                QMessageBox.critical(self, _("Error"), f"{_('Failed to start network')}: {e}")
    
    def _on_stop_network(self):
        net = self._get_selected_network()
        if net:
            try:
                net.destroy()
                self._refresh()
            except Exception as e:
                QMessageBox.critical(self, _("Error"), f"{_('Failed to stop network')}: {e}")

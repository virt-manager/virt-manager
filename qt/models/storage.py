"""
Storage model for Qt frontend.
"""

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt


class StoragePoolModel(QAbstractTableModel):
    """
    Model for storage pool list.
    """
    
    COL_NAME = 0
    COL_STATE = 1
    COL_CAPACITY = 2
    COL_ALLOCATION = 3
    COL_AVAILABLE = 4
    COL_COUNT = 5
    
    def __init__(self, uri=None, parent=None):
        super().__init__(parent)
        self._uri = uri
        self._pools = []
    
    def set_pools(self, pools):
        self.beginResetModel()
        self._pools = pools
        self.endResetModel()
    
    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._pools)
    
    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return self.COL_COUNT
    
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation != Qt.Orientation.Horizontal:
            return None
        
        headers = {
            self.COL_NAME: "Name",
            self.COL_STATE: "State",
            self.COL_CAPACITY: "Capacity",
            self.COL_ALLOCATION: "Used",
            self.COL_AVAILABLE: "Available",
        }
        return headers.get(section, "")
    
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        
        row = index.row()
        if row < 0 or row >= len(self._pools):
            return None
        
        pool = self._pools[row]
        
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == self.COL_NAME:
                return pool.name
            elif index.column() == self.COL_STATE:
                return pool.state_str
            elif index.column() == self.COL_CAPACITY:
                return self._format_size(pool.capacity)
            elif index.column() == self.COL_ALLOCATION:
                return self._format_size(pool.allocation)
            elif index.column() == self.COL_AVAILABLE:
                return self._format_size(pool.available)
        
        return None
    
    def _format_size(self, bytes_val):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"
    
    def get_pool(self, index):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._pools):
            return None
        return self._pools[row]


class StorageVolumeModel(QAbstractTableModel):
    """
    Model for storage volume list.
    """
    
    COL_NAME = 0
    COL_PATH = 1
    COL_CAPACITY = 2
    COL_ALLOCATION = 3
    COL_COUNT = 4
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._volumes = []
    
    def set_volumes(self, volumes):
        self.beginResetModel()
        self._volumes = volumes
        self.endResetModel()
    
    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._volumes)
    
    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return self.COL_COUNT
    
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation != Qt.Orientation.Horizontal:
            return None
        
        headers = {
            self.COL_NAME: "Name",
            self.COL_PATH: "Path",
            self.COL_CAPACITY: "Capacity",
            self.COL_ALLOCATION: "Allocation",
        }
        return headers.get(section, "")
    
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        
        row = index.row()
        if row < 0 or row >= len(self._volumes):
            return None
        
        vol = self._volumes[row]
        
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == self.COL_NAME:
                return vol.name
            elif index.column() == self.COL_PATH:
                return vol.path
            elif index.column() == self.COL_CAPACITY:
                return self._format_size(vol.capacity)
            elif index.column() == self.COL_ALLOCATION:
                return self._format_size(vol.allocation)
        
        return None
    
    def _format_size(self, bytes_val):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"
    
    def get_volume(self, index):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._volumes):
            return None
        return self._volumes[row]


class NetworkModel(QAbstractTableModel):
    """
    Model for network list.
    """
    
    COL_NAME = 0
    COL_STATE = 1
    COL_BRIDGE = 2
    COL_COUNT = 3
    
    def __init__(self, uri=None, parent=None):
        super().__init__(parent)
        self._uri = uri
        self._networks = []
    
    def set_networks(self, networks):
        self.beginResetModel()
        self._networks = networks
        self.endResetModel()
    
    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._networks)
    
    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return self.COL_COUNT
    
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation != Qt.Orientation.Horizontal:
            return None
        
        headers = {
            self.COL_NAME: "Name",
            self.COL_STATE: "State",
            self.COL_BRIDGE: "Bridge",
        }
        return headers.get(section, "")
    
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        
        row = index.row()
        if row < 0 or row >= len(self._networks):
            return None
        
        net = self._networks[row]
        
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == self.COL_NAME:
                return net.name
            elif index.column() == self.COL_STATE:
                return net.state_str
            elif index.column() == self.COL_BRIDGE:
                return net.bridge_name
        
        return None
    
    def get_network(self, index):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._networks):
            return None
        return self._networks[row]


class SnapshotModel(QAbstractTableModel):
    """
    Model for snapshot list.
    """
    
    COL_NAME = 0
    COL_TIME = 1
    COL_COUNT = 2
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshots = []
    
    def set_snapshots(self, snapshots):
        self.beginResetModel()
        self._snapshots = snapshots
        self.endResetModel()
    
    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._snapshots)
    
    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return self.COL_COUNT
    
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation != Qt.Orientation.Horizontal:
            return None
        
        headers = {
            self.COL_NAME: "Name",
            self.COL_TIME: "Created",
        }
        return headers.get(section, "")
    
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        
        row = index.row()
        if row < 0 or row >= len(self._snapshots):
            return None
        
        snap = self._snapshots[row]
        
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == self.COL_NAME:
                return snap.name
            elif index.column() == self.COL_TIME:
                import time
                try:
                    ts = int(snap.creation_time)
                    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                except Exception:
                    return snap.creation_time
        
        return None
    
    def get_snapshot(self, index):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._snapshots):
            return None
        return self._snapshots[row]

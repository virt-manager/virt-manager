"""
VM model for Qt frontend.

Provides a table model of VMs with sorting, filtering, and stats.
"""

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QSortFilterProxyModel

from ..core.engine import get_engine
from ..core.signals import get_signals


class VmModel(QAbstractTableModel):
    """
    Model for VM list.
    
    Provides data for displaying VMs with their stats in a table view.
    """
    
    # Column indices
    COL_NAME = 0
    COL_STATE = 1
    COL_VCPUS = 2
    COL_MEMORY = 3
    COL_CPU = 4
    COL_DISK = 5
    COL_NETWORK = 6
    
    # Total columns
    COL_COUNT = 7
    
    # Roles
    ROLE_UUID = Qt.ItemDataRole.UserRole + 1
    ROLE_URI = Qt.ItemDataRole.UserRole + 2
    ROLE_STATE = Qt.ItemDataRole.UserRole + 3
    ROLE_OBJECT = Qt.ItemDataRole.UserRole + 4
    
    # Role names
    ROLE_NAMES = {
        ROLE_UUID: b"uuid",
        ROLE_URI: b"uri",
        ROLE_STATE: b"state",
        ROLE_OBJECT: b"vm_object",
    }
    
    def __init__(self, uri: str = None, parent=None):
        super().__init__(parent)
        self._uri = uri
        self._engine = get_engine()
        self._signals = get_signals()
        self._vms: list = []
        
        self._setup_signals()
        self._refresh()
    
    def _setup_signals(self) -> None:
        """Connect to engine signals."""
        self._signals.vm_added.connect(self._on_vm_added)
        self._signals.vm_removed.connect(self._on_vm_removed)
        self._signals.vm_state_changed.connect(self._on_state_changed)
        self._signals.vm_stats_updated.connect(self._on_stats_updated)
    
    def _get_vm_key(self, vm) -> tuple:
        """Get sort key for a VM."""
        return (vm.conn.uri, vm.uuid)
    
    def _refresh(self) -> None:
        """Refresh VM list."""
        self.beginResetModel()
        self._vms = []
        
        for uri, conn in self._engine.get_connections().items():
            if self._uri and uri != self._uri:
                continue
            
            for vm in conn.list_vms():
                self._vms.append(vm)
        
        self._vms.sort(key=lambda v: v.name.lower())
        self.endResetModel()
    
    def _find_vm_index(self, uri: str, uuid: str) -> int:
        """Find VM index by URI and UUID."""
        for i, vm in enumerate(self._vms):
            if vm.uuid == uuid and vm.conn.uri == uri:
                return i
        return -1
    
    def _on_vm_added(self, uri: str, uuid: str) -> None:
        """Handle VM added."""
        if self._uri and uri != self._uri:
            return
        
        conn = self._engine.get_connections().get(uri)
        if not conn:
            return
        
        vm = conn.get_vm(uuid)
        if not vm:
            return
        
        key = self._get_vm_key(vm)
        insert_pos = 0
        for i, v in enumerate(self._vms):
            if self._get_vm_key(v) > key:
                break
            insert_pos = i + 1
        
        self.beginInsertRows(QModelIndex(), insert_pos, insert_pos)
        self._vms.insert(insert_pos, vm)
        self.endInsertRows()
    
    def _on_vm_removed(self, uri: str, uuid: str) -> None:
        """Handle VM removed."""
        idx = self._find_vm_index(uri, uuid)
        if idx >= 0:
            self.beginRemoveRows(QModelIndex(), idx, idx)
            self._vms.pop(idx)
            self.endRemoveRows()
    
    def _on_state_changed(self, uri: str, uuid: str) -> None:
        """Handle VM state changed."""
        idx = self._find_vm_index(uri, uuid)
        if idx >= 0:
            top_left = self.index(idx, 0)
            bottom_right = self.index(idx, self.COL_COUNT - 1)
            self.dataChanged.emit(top_left, bottom_right)
    
    def _on_stats_updated(self, uri: str, uuid: str) -> None:
        """Handle VM stats updated."""
        idx = self._find_vm_index(uri, uuid)
        if idx >= 0:
            top_left = self.index(idx, self.COL_CPU)
            bottom_right = self.index(idx, self.COL_COUNT - 1)
            self.dataChanged.emit(top_left, bottom_right)
    
    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of VMs."""
        if parent.isValid():
            return 0
        return len(self._vms)
    
    def columnCount(self, parent=QModelIndex()) -> int:
        """Return number of columns."""
        if parent.isValid():
            return 0
        return self.COL_COUNT
    
    def headerData(
        self, section: int, orientation: Qt.Orientation,
        role=Qt.ItemDataRole.DisplayRole
    ):
        """Return header data."""
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        
        if orientation != Qt.Orientation.Horizontal:
            return None
        
        headers = {
            self.COL_NAME: "Name",
            self.COL_STATE: "State",
            self.COL_VCPUS: "vCPUs",
            self.COL_MEMORY: "Memory",
            self.COL_CPU: "CPU",
            self.COL_DISK: "Disk I/O",
            self.COL_NETWORK: "Network",
        }
        return headers.get(section, "")
    
    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        """Return data for index and role."""
        if not index.isValid():
            return None
        
        row = index.row()
        if row < 0 or row >= len(self._vms):
            return None
        
        vm = self._vms[row]
        
        if role == Qt.ItemDataRole.DisplayRole:
            return self._get_display_data(index.column(), vm)
        
        if role == Qt.ItemDataRole.DecorationRole:
            return self._get_decoration(index.column(), vm)
        
        if role == Qt.ItemDataRole.UserRole:
            return self._get_user_role_data(index.column(), vm)
        
        if role >= Qt.ItemDataRole.UserRole:
            role_idx = role - Qt.ItemDataRole.UserRole
            if role_idx == 1:
                return vm.uuid
            if role_idx == 2:
                return vm.conn.uri
        
        return None
    
    def _get_display_data(self, col: int, vm) -> str:
        """Get display string for column."""
        if col == self.COL_NAME:
            return vm.name
        if col == self.COL_STATE:
            return vm.state_str
        if col == self.COL_VCPUS:
            return str(vm.vcpus)
        if col == self.COL_MEMORY:
            return f"{vm.memory_mb} MB"
        if col == self.COL_CPU:
            return f"{vm.get_cpu_percent():.1f}%"
        if col == self.COL_DISK:
            rate = vm.get_disk_rate()
            if rate < 1024:
                return f"{rate:.0f} KB/s"
            return f"{rate/1024:.1f} MB/s"
        if col == self.COL_NETWORK:
            rate = vm.get_network_rate()
            if rate < 1024:
                return f"{rate:.0f} B/s"
            if rate < 1024 * 1024:
                return f"{rate/1024:.1f} KB/s"
            return f"{rate/1024/1024:.1f} MB/s"
        return ""
    
    def _get_decoration(self, col: int, vm) -> str:
        """Get decoration (icon) for column."""
        if col == self.COL_NAME:
            return self._state_icon(vm.state)
        return None
    
    def _get_user_role_data(self, col: int, vm) -> any:
        """Get user role data for column."""
        if col == self.COL_NAME:
            return vm.uuid
        if col == self.COL_STATE:
            return vm.state
        if col == self.COL_CPU:
            return vm.get_cpu_percent()
        if col == self.COL_MEMORY:
            return vm.memory_mb
        return None
    
    def _state_icon(self, state: int) -> str:
        """Get icon name for VM state."""
        icons = {
            vm.STATE_RUNNING: "media-playback-start",
            vm.STATE_PAUSED: "media-playback-pause",
            vm.STATE_SHUTOFF: "system-shutdown",
            vm.STATE_SHUTDOWN: "system-suspend",
            vm.STATE_CRASHED: "dialog-error",
        }
        return icons.get(state, "help-about")
    
    def roleNames(self) -> dict:
        """Return role names."""
        return self.ROLE_NAMES
    
    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Return item flags."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
    
    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Sort by column."""
        self.layoutAboutToBeChanged.emit()
        
        reverse = order == Qt.SortOrder.DescendingOrder
        
        if column == self.COL_NAME:
            self._vms.sort(key=lambda v: v.name.lower(), reverse=reverse)
        elif column == self.COL_STATE:
            self._vms.sort(key=lambda v: v.state, reverse=reverse)
        elif column == self.COL_VCPUS:
            self._vms.sort(key=lambda v: v.vcpus, reverse=reverse)
        elif column == self.COL_MEMORY:
            self._vms.sort(key=lambda v: v.memory_mb, reverse=reverse)
        elif column == self.COL_CPU:
            self._vms.sort(key=lambda v: v.get_cpu_percent(), reverse=reverse)
        elif column == self.COL_DISK:
            self._vms.sort(key=lambda v: v.get_disk_rate(), reverse=reverse)
        elif column == self.COL_NETWORK:
            self._vms.sort(key=lambda v: v.get_network_rate(), reverse=reverse)
        
        self.layoutChanged.emit()
    
    def get_vm(self, index: QModelIndex):
        """Get VM at index."""
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._vms):
            return None
        return self._vms[row]
    
    def get_vm_by_uuid(self, uri: str, uuid: str):
        """Get VM by URI and UUID."""
        conn = self._engine.get_connections().get(uri)
        if conn:
            return conn.get_vm(uuid)
        return None

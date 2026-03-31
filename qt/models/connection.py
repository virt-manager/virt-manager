"""
Connection model for Qt frontend.

Provides a list model of connections with state information.
"""

from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt, pyqtSignal, QObject

from ..core.engine import get_engine
from ..core.signals import get_signals


class ConnectionModel(QAbstractListModel):
    """
    Model for connection list.
    
    Provides data for displaying connections in a list view.
    """
    
    # Roles
    ROLE_URI = Qt.ItemDataRole.UserRole + 1
    ROLE_STATE = Qt.ItemDataRole.UserRole + 2
    ROLE_STATE_STR = Qt.ItemDataRole.UserRole + 3
    ROLE_VM_COUNT = Qt.ItemDataRole.UserRole + 4
    ROLE_HOSTNAME = Qt.ItemDataRole.UserRole + 5
    
    # Data roles mapping
    ROLE_NAMES = {
        ROLE_URI: b"uri",
        ROLE_STATE: b"state",
        ROLE_STATE_STR: b"state_str",
        ROLE_VM_COUNT: b"vm_count",
        ROLE_HOSTNAME: b"hostname",
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = get_engine()
        self._signals = get_signals()
        
        self._setup_signals()
        self._refresh()
    
    def _setup_signals(self) -> None:
        """Connect to engine signals."""
        self._signals.connection_added.connect(self._on_connection_added)
        self._signals.connection_removed.connect(self._on_connection_removed)
        self._signals.connection_state_changed.connect(self._on_state_changed)
        self._signals.vm_added.connect(self._on_vm_changed)
        self._signals.vm_removed.connect(self._on_vm_changed)
    
    def _on_connection_added(self, uri: str) -> None:
        """Handle new connection."""
        idx = list(self._engine.get_connections().keys()).index(uri)
        self.beginInsertRows(QModelIndex(), idx, idx)
        self.endInsertRows()
    
    def _on_connection_removed(self, uri: str) -> None:
        """Handle connection removal."""
        conns = list(self._engine.get_connections().keys())
        if uri in conns:
            idx = conns.index(uri)
            self.beginRemoveRows(QModelIndex(), idx, idx)
            self.endRemoveRows()
    
    def _on_state_changed(self, uri: str) -> None:
        """Handle connection state change."""
        conns = list(self._engine.get_connections().keys())
        if uri in conns:
            idx = self.index(conns.index(uri))
            self.dataChanged.emit(idx, idx)
    
    def _on_vm_changed(self, uri: str, uuid: str = "") -> None:
        """Handle VM add/remove."""
        conns = list(self._engine.get_connections().keys())
        if uri in conns:
            idx = self.index(conns.index(uri))
            self.dataChanged.emit(idx, idx)
    
    def _refresh(self) -> None:
        """Refresh connection list."""
        self.beginResetModel()
        self.endResetModel()
    
    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of connections."""
        if parent.isValid():
            return 0
        return len(self._engine.get_connections())
    
    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        """Return data for index and role."""
        if not index.isValid():
            return None
        
        uri = list(self._engine.get_connections().keys())[index.row()]
        conn = self._engine.get_connections().get(uri)
        
        if not conn:
            return None
        
        if role == Qt.ItemDataRole.DisplayRole:
            return conn.uri
        
        if role == self.ROLE_URI:
            return conn.uri
        
        if role == self.ROLE_STATE:
            return conn.state
        
        if role == self.ROLE_STATE_STR:
            if conn.is_active:
                return "Connected"
            elif conn.is_connecting:
                return "Connecting..."
            return "Disconnected"
        
        if role == self.ROLE_VM_COUNT:
            return len(conn.get_vms())
        
        if role == self.ROLE_HOSTNAME:
            try:
                return conn.backend.get_uri_hostname() if conn.backend else ""
            except Exception:
                return ""
        
        return None
    
    def roleNames(self) -> dict:
        """Return role names for QML."""
        return self.ROLE_NAMES
    
    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Return item flags."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
    
    def get_connection(self, index: QModelIndex):
        """Get connection at index."""
        if not index.isValid():
            return None
        uri = list(self._engine.get_connections().keys())[index.row()]
        return self._engine.get_connections().get(uri)
    
    def get_connection_by_uri(self, uri: str):
        """Get connection by URI."""
        return self._engine.get_connections().get(uri)
    
    def connect_to(self, uri: str) -> bool:
        """Connect to a URI."""
        if uri not in self._engine.get_connections():
            self._engine.add_connection(uri)
        
        conn = self._engine.get_connections().get(uri)
        if conn:
            conn.connect_async()
            return True
        return False
    
    def disconnect_from(self, uri: str) -> None:
        """Disconnect from a URI."""
        conn = self._engine.get_connections().get(uri)
        if conn:
            conn.close()
    
    def remove_connection(self, uri: str) -> None:
        """Remove a connection."""
        self._engine.remove_connection(uri)

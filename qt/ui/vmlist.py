"""
VM list view for Qt frontend.

Displays VMs in a table with sorting and inline stats.
"""

from PyQt6.QtWidgets import QTableView, QHeaderView, QMenu
from PyQt6.QtCore import Qt, pyqtSignal, QSortFilterProxyModel
from PyQt6.QtGui import QAction

from ..models.vm import VmModel
from .lib.i18n import _


class VmListView(QTableView):
    """
    VM list table view.
    
    Displays VMs with columns for name, state, resources, and stats.
    """
    
    vm_selected = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSortRole(Qt.ItemDataRole.UserRole)
        
        self.setModel(self._proxy)
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup the table view."""
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        
        self.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.doubleClicked.connect(self._on_double_click)
    
    def setModel(self, model) -> None:
        """Set the VM model."""
        self._proxy.setSourceModel(model)
        super().setModel(self._proxy)
    
    def _on_selection_changed(self, selected, deselected) -> None:
        """Handle selection changes."""
        self.vm_selected.emit()
    
    def _on_double_click(self, index) -> None:
        """Handle double-click to open details."""
        self.vm_selected.emit()
    
    def get_selected_vm(self):
        """Get the selected VM and its URI."""
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None, None
        
        proxy_index = indexes[0]
        source_index = self._proxy.mapToSource(proxy_index)
        vm = source_index.model().get_vm(source_index)
        
        if vm:
            return vm, vm.conn.uri
        
        return None, None
    
    def contextMenuEvent(self, event) -> None:
        """Show context menu."""
        vm, uri = self.get_selected_vm()
        if not vm:
            return
        
        menu = QMenu(self)
        
        if vm.state == vm.STATE_SHUTOFF:
            start_action = QAction(_("Start"), menu)
            start_action.triggered.connect(vm.start)
            menu.addAction(start_action)
        elif vm.state == vm.STATE_RUNNING:
            shutdown_action = QAction(_("Shutdown"), menu)
            shutdown_action.triggered.connect(vm.shutdown)
            menu.addAction(shutdown_action)

            pause_text = _("Resume") if vm.is_paused else _("Pause")
            pause_action = QAction(pause_text, menu)
            pause_action.triggered.connect(
                vm.resume if vm.is_paused else vm.pause
            )
            menu.addAction(pause_action)

        if vm.state in (vm.STATE_SHUTOFF, vm.STATE_CRASHED):
            menu.addSeparator()
            delete_action = QAction(_("Delete"), menu)
            delete_action.triggered.connect(vm.delete)
            menu.addAction(delete_action)
        
        menu.exec(event.globalPos())

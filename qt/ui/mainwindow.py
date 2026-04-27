"""
Main window for Qt frontend.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QStatusBar, QMenuBar, QToolBar,
    QMessageBox, QSplitter, QLabel, QListView, QPushButton,
    QHeaderView, QMenu, QDialog
)
from PyQt6.QtCore import Qt, QSize, pyqtSlot
from PyQt6.QtGui import QIcon, QKeySequence, QAction

from .lib.i18n import _
from .vmlist import VmListView
from .models.vm import VmModel
from .details.details import vmmDetails


class MainWindow(QMainWindow):
    """
    Main application window.
    """

    def __init__(self):
        super().__init__()
        self._engine = None
        self._selected_vm = None
        self._selected_uri = None
        self._vm_model = None
        self._details_widget = None
        self._tray = None
        self._setup_ui()

    def set_engine(self, engine):
        """Set the engine instance."""
        self._engine = engine
        self._vm_model = VmModel()
        self._vm_table.setModel(self._vm_model)

    def _setup_ui(self) -> None:
        """Setup the user interface."""
        self.setWindowTitle(_("virt-manager"))
        self.resize(1050, 700)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        sidebar = self._create_sidebar()
        splitter.addWidget(sidebar)

        self._content = QStackedWidget()
        splitter.addWidget(self._content)

        self._vm_table = VmListView()
        self._vm_table.vm_selected.connect(self._on_vm_selected)
        self._content.addWidget(self._vm_table)

        self._details_container = QWidget()
        self._details_layout = QVBoxLayout(self._details_container)
        self._details_layout.setContentsMargins(0, 0, 0, 0)
        self._content.addWidget(self._details_container)

        splitter.setSizes([250, 800])

        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage(_("Ready"))

        self._setup_toolbar()
        self._setup_menubar()

    def _create_sidebar(self) -> QWidget:
        """Create the connection sidebar."""
        sidebar = QWidget()
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 8, 8, 8)

        header = QLabel(_("Connections"))
        header.setStyleSheet("font-weight: bold; font-size: 14px; padding: 4px;")
        layout.addWidget(header)

        self._conn_list = QListView()
        layout.addWidget(self._conn_list)

        btn_layout = QHBoxLayout()

        add_btn = QPushButton(_("Add"))
        add_btn.clicked.connect(self._on_add_connection)
        btn_layout.addWidget(add_btn)

        rem_btn = QPushButton(_("Remove"))
        rem_btn.clicked.connect(self._on_remove_connection)
        btn_layout.addWidget(rem_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

        sidebar.setMinimumWidth(200)
        sidebar.setMaximumWidth(350)

        return sidebar

    def _setup_toolbar(self) -> None:
        """Setup toolbar."""
        toolbar = QToolBar(_("Main Toolbar"))
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(22, 22))
        self.addToolBar(toolbar)

        self._action_start = QAction(QIcon.fromTheme("media-playback-start"), _("Start"), self)
        self._action_start.triggered.connect(self._on_start_vm)
        self._action_start.setEnabled(False)
        toolbar.addAction(self._action_start)

        self._action_shutdown = QAction(QIcon.fromTheme("system-shutdown"), _("Shutdown"), self)
        self._action_shutdown.triggered.connect(self._on_shutdown_vm)
        self._action_shutdown.setEnabled(False)
        toolbar.addAction(self._action_shutdown)

        self._action_pause = QAction(QIcon.fromTheme("media-playback-pause"), _("Pause"), self)
        self._action_pause.triggered.connect(self._on_pause_vm)
        self._action_pause.setEnabled(False)
        toolbar.addAction(self._action_pause)

        toolbar.addSeparator()

        self._action_delete = QAction(QIcon.fromTheme("edit-delete"), _("Delete"), self)
        self._action_delete.triggered.connect(self._on_delete_vm)
        self._action_delete.setEnabled(False)
        toolbar.addAction(self._action_delete)

        toolbar.addSeparator()

        new_vm = QAction(QIcon.fromTheme("document-new"), _("New VM"), self)
        new_vm.triggered.connect(self._on_new_vm)
        toolbar.addAction(new_vm)

    def _setup_menubar(self) -> None:
        """Setup menu bar."""
        menubar = QMenuBar()
        self.setMenuBar(menubar)

        file_menu = menubar.addMenu(_("File"))

        new_vm_action = QAction(_("New VM"), self)
        new_vm_action.triggered.connect(self._on_new_vm)
        file_menu.addAction(new_vm_action)

        add_conn_action = QAction(_("Add Connection..."), self)
        add_conn_action.setShortcut(QKeySequence("Ctrl+N"))
        add_conn_action.triggered.connect(self._on_add_connection)
        file_menu.addAction(add_conn_action)

        storage_action = QAction(_("Storage"), self)
        storage_action.triggered.connect(self._on_open_storage)
        file_menu.addAction(storage_action)

        network_action = QAction(_("Networks"), self)
        network_action.triggered.connect(self._on_open_network)
        file_menu.addAction(network_action)

        conn_details_action = QAction(_("Connection Details"), self)
        conn_details_action.triggered.connect(self._on_open_host)
        file_menu.addAction(conn_details_action)

        file_menu.addSeparator()

        prefs_action = QAction(_("Preferences..."), self)
        prefs_action.triggered.connect(self._on_preferences)
        file_menu.addAction(prefs_action)

        file_menu.addSeparator()

        about_action = QAction(_("About"), self)
        about_action.triggered.connect(self._on_about)
        file_menu.addAction(about_action)

        file_menu.addSeparator()

        quit_action = QAction(_("Quit"), self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        vm_menu = menubar.addMenu(_("VM"))
        vm_menu.addAction(self._action_start)
        vm_menu.addAction(self._action_shutdown)
        vm_menu.addAction(self._action_pause)
        vm_menu.addSeparator()
        vm_menu.addAction(self._action_delete)
        vm_menu.addSeparator()

        add_hw_action = QAction(_("Add Hardware..."), self)
        add_hw_action.triggered.connect(self._on_add_hardware)
        vm_menu.addAction(add_hw_action)

        snapshot_action = QAction(_("Snapshots..."), self)
        snapshot_action.triggered.connect(self._on_snapshots)
        vm_menu.addAction(snapshot_action)

        vm_menu.addSeparator()

        clone_action = QAction(_("Clone..."), self)
        clone_action.triggered.connect(self._on_clone_vm)
        vm_menu.addAction(clone_action)

        migrate_action = QAction(_("Migrate..."), self)
        migrate_action.triggered.connect(self._on_migrate_vm)
        vm_menu.addAction(migrate_action)

    def _show_vm_context_menu(self, pos):
        """Show context menu for VM."""
        vm, uri = self._vm_table.get_selected_vm()
        if not vm:
            return
            
        menu = QMenu(self)

        start_action = QAction(_("Start"), menu)
        start_action.triggered.connect(self._on_start_vm)
        menu.addAction(start_action)

        shutdown_action = QAction(_("Shutdown"), menu)
        shutdown_action.triggered.connect(self._on_shutdown_vm)
        menu.addAction(shutdown_action)

        menu.exec(self._vm_table.mapToGlobal(pos))

    def _on_vm_selected(self) -> None:
        """Handle VM selection."""
        vm, uri = self._vm_table.get_selected_vm()

        if not vm:
            self._selected_vm = None
            self._selected_uri = None
            self._update_actions(None)
            self._content.setCurrentIndex(0)
            return

        self._selected_vm = vm.uuid
        self._selected_uri = uri

        self._update_actions(vm)
        
        # Update details widget
        if self._details_widget:
            self._details_widget.deleteLater()
        
        conn = self._engine.get_connection(uri)
        self._details_widget = vmmDetails(vm, conn, self._engine)
        self._details_layout.addWidget(self._details_widget)
        
        self._content.setCurrentIndex(1)

    def _update_actions(self, vm) -> None:
        """Update action states based on selection."""
        has_selection = vm is not None

        self._action_start.setEnabled(has_selection)
        self._action_shutdown.setEnabled(has_selection)
        self._action_pause.setEnabled(has_selection)
        self._action_delete.setEnabled(has_selection)

    @pyqtSlot()
    def _on_add_connection(self) -> None:
        """Open add connection dialog."""
        from .dialogs.createconn import ConnectionDialog
        dialog = ConnectionDialog(self._engine)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            uri = dialog.get_uri()
            if uri and self._engine:
                self._engine.add_connection(uri)

    @pyqtSlot()
    def _on_remove_connection(self) -> None:
        """Remove selected connection."""
        if not self._selected_uri:
            return

        reply = QMessageBox.question(
            self,
            _("Remove Connection"),
            _("Remove connection to '%s'?\n\nThis will disconnect from the host.") % self._selected_uri,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes and self._engine:
            self._engine.remove_connection(self._selected_uri)
            self._selected_uri = None
            self._selected_vm = None

    @pyqtSlot()
    def _on_new_vm(self) -> None:
        """Open new VM wizard."""
        from .dialogs.createvm import CreateVmDialog
        dialog = CreateVmDialog(self)
        dialog.exec()

    @pyqtSlot()
    def _on_start_vm(self) -> None:
        """Start the selected VM."""
        if self._engine and self._selected_uri and self._selected_vm:
            conn = self._engine.get_connection(self._selected_uri)
            if conn:
                conn.start_vm(self._selected_vm)

    @pyqtSlot()
    def _on_shutdown_vm(self) -> None:
        """Shutdown the selected VM."""
        if self._engine and self._selected_uri and self._selected_vm:
            conn = self._engine.get_connection(self._selected_uri)
            if conn:
                conn.shutdown_vm(self._selected_vm)

    @pyqtSlot()
    def _on_pause_vm(self) -> None:
        """Pause the selected VM."""
        if self._engine and self._selected_uri and self._selected_vm:
            conn = self._engine.get_connection(self._selected_uri)
            if conn:
                conn.pause_vm(self._selected_vm)

    @pyqtSlot()
    def _on_delete_vm(self) -> None:
        """Delete the selected VM."""
        if not self._selected_vm:
            return

        conn = self._engine.get_connection(self._selected_uri)
        if not conn:
            return
            
        vm = conn.get_vm(self._selected_vm)
        if not vm:
            return

        from .dialogs.delete import vmmDeleteDialog
        dialog = vmmDeleteDialog(vm, conn, self._engine)
        dialog.exec()

    @pyqtSlot()
    def _on_preferences(self) -> None:
        """Open preferences dialog."""
        from .dialogs.preferences import PreferencesDialog
        dialog = PreferencesDialog(self)
        dialog.exec()

    @pyqtSlot()
    def _on_about(self) -> None:
        """Show about dialog."""
        from .dialogs.about import AboutDialog
        dialog = AboutDialog(self)
        dialog.exec()

    @pyqtSlot()
    def _on_open_storage(self) -> None:
        """Open storage management window."""
        if not self._engine:
            return
        # Get first connection
        conns = self._engine.get_connections()
        if conns:
            conn = list(conns.values())[0]
            from .storage import StorageWindow
            win = StorageWindow(conn)
            win.show()

    @pyqtSlot()
    def _on_open_network(self) -> None:
        """Open network management window."""
        if not self._engine:
            return
        conns = self._engine.get_connections()
        if conns:
            conn = list(conns.values())[0]
            from .storage import NetworkWindow
            win = NetworkWindow(conn)
            win.show()

    @pyqtSlot()
    def _on_open_host(self) -> None:
        """Open connection details window."""
        if not self._engine:
            return
        conns = self._engine.get_connections()
        if conns:
            conn = list(conns.values())[0]
            from .host import vmmHost
            win = vmmHost(conn, self._engine)
            win.show()

    @pyqtSlot()
    def _on_add_hardware(self) -> None:
        """Open add hardware dialog."""
        if not self._selected_vm or not self._engine:
            return
        conn = self._engine.get_connection(self._selected_uri)
        if conn:
            vm = conn.get_vm(self._selected_vm)
            if vm and vm.domain:
                from .dialogs.addhardware import vmmAddHardware
                dialog = vmmAddHardware(conn, vm, self._engine)
                dialog.exec()

    @pyqtSlot()
    def _on_snapshots(self) -> None:
        """Open snapshot dialog."""
        if not self._selected_vm or not self._engine:
            return
        conn = self._engine.get_connection(self._selected_uri)
        if conn:
            vm = conn.get_vm(self._selected_vm)
            if vm and vm.domain:
                from .dialogs.snapshot import SnapshotDialog
                dialog = SnapshotDialog(vm, self)
                dialog.exec()

    @pyqtSlot()
    def _on_clone_vm(self) -> None:
        """Open clone dialog."""
        if not self._selected_vm or not self._engine:
            return
        conn = self._engine.get_connection(self._selected_uri)
        if conn:
            vm = conn.get_vm(self._selected_vm)
            if vm and vm.domain:
                from .dialogs.clone import CloneDialog
                dialog = CloneDialog(vm, self)
                dialog.exec()

    @pyqtSlot()
    def _on_migrate_vm(self) -> None:
        """Open migrate dialog."""
        if not self._selected_vm or not self._engine:
            return
        conn = self._engine.get_connection(self._selected_uri)
        if conn:
            vm = conn.get_vm(self._selected_vm)
            if vm and vm.domain:
                from .dialogs.clone import MigrateDialog
                dialog = MigrateDialog(vm, self)
                dialog.exec()

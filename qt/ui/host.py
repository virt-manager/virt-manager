from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QFormLayout, QGroupBox, QLineEdit, QCheckBox,
    QMessageBox
)
from PyQt6.QtCore import Qt

from .lib.i18n import _


class vmmHost(QWidget):
    def __init__(self, conn, engine):
        super().__init__()
        self.conn = conn
        self.engine = engine
        
        self._window_size = None
        self._init_ui()
        self._refresh_resources()
        self._refresh_conn_state()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        self._tab_widget = QTabWidget()

        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)

        details_group = QGroupBox(_("Connection Details"))
        details_layout = QFormLayout(details_group)

        self._conn_name = QLineEdit(self.conn.get_pretty_desc())
        self._conn_name.setReadOnly(True)
        details_layout.addRow(_("Name:"), self._conn_name)

        self._conn_URI = QLabel(self.conn.get_uri())
        details_layout.addRow(_("URI:"), self._conn_URI)

        self._autoconnect = QCheckBox(_("Auto connect when virt-manager starts"))
        details_layout.addRow("", self._autoconnect)

        overview_layout.addWidget(details_group)

        perf_group = QGroupBox(_("Performance"))
        perf_layout = QVBoxLayout(perf_group)

        perf_form = QFormLayout()

        self._cpu_usage = QLabel("0 %")
        perf_form.addRow(_("CPU Usage:"), self._cpu_usage)

        self._memory_usage = QLabel("0 MiB / 0 MiB")
        perf_form.addRow(_("Memory Usage:"), self._memory_usage)

        perf_layout.addLayout(perf_form)

        overview_layout.addWidget(perf_group)
        overview_layout.addStretch()

        self._tab_widget.addTab(overview_tab, _("Overview"))

        networks_tab = QWidget()
        networks_layout = QVBoxLayout(networks_tab)

        try:
            from .hostnets import vmmHostNets
            self._hostnets = vmmHostNets(self.conn, self.engine)
            networks_layout.addWidget(self._hostnets)
        except Exception as e:
            networks_layout.addWidget(QLabel(_("Error loading networks: %s") % e))

        self._tab_widget.addTab(networks_tab, _("Networks"))

        storage_tab = QWidget()
        storage_layout = QVBoxLayout(storage_tab)

        try:
            from .hoststorage import vmmHostStorage
            self._hoststorage = vmmHostStorage(self.conn, self.engine)
            storage_layout.addWidget(self._hoststorage)
        except Exception as e:
            storage_layout.addWidget(QLabel(_("Error loading storage: %s") % e))

        self._tab_widget.addTab(storage_tab, _("Storage"))

        main_layout.addWidget(self._tab_widget)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        main_layout.addLayout(button_layout)
        
        self._tab_widget.currentChanged.connect(self._page_changed)

    def _refresh_resources(self):
        try:
            vm_memory = self.conn.stats_memory()
            host_memory = self.conn.host_memory_size()
            
            cpu_percent = self.conn.host_cpu_time_percentage()
            self._cpu_usage.setText(f"{cpu_percent} %")
            
            from virtinst import humanize
            vm_mem_str = humanize(humanize.BYTES, vm_memory * 1024)
            host_mem_str = humanize(humanize.BYTES, host_memory * 1024 * 1024)
            self._memory_usage.setText(f"{vm_mem_str} / {host_mem_str}")
        except Exception:
            pass

    def _refresh_conn_state(self):
        self._conn_name.setText(self.conn.get_pretty_desc())
        self._conn_URI.setText(self.conn.get_uri())

    def _page_changed(self, index):
        if index == 1:
            if hasattr(self, '_hostnets'):
                self._hostnets.refresh_page()
        elif index == 2:
            if hasattr(self, '_hoststorage'):
                self._hoststorage.refresh_page()

    def cleanup(self):
        if hasattr(self, '_hostnets'):
            self._hostnets.cleanup()
        if hasattr(self, '_hoststorage'):
            self._hoststorage.cleanup()

    def show(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

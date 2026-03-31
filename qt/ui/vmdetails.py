"""
VM details panel for Qt frontend.

Displays detailed information about a selected VM.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QTableWidget, QTableWidgetItem,
    QScrollArea, QGroupBox, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont

from .lib.i18n import _


class VmDetailsPanel(QWidget):
    """
    VM details panel.
    
    Shows overview, hardware, and stats for a selected VM.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._vm = None
        self._uri = None
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        
        self._header = self._create_header()
        layout.addWidget(self._header)
        
        self._tabs = QTabWidget()
        
        self._overview_tab = self._create_overview_tab()
        self._tabs.addTab(self._overview_tab, _("Overview"))
        
        self._hardware_tab = self._create_hardware_tab()
        self._tabs.addTab(self._hardware_tab, _("Hardware"))
        
        self._stats_tab = self._create_stats_tab()
        self._tabs.addTab(self._stats_tab, _("Stats"))
        
        layout.addWidget(self._tabs)
        
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_stats)
    
    def _create_header(self) -> QWidget:
        """Create VM header widget."""
        header = QWidget()
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(0, 0, 0, 0)
        
        self._name_label = QLabel()
        self._name_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        h_layout.addWidget(self._name_label)
        
        h_layout.addStretch()
        
        self._state_label = QLabel()
        self._state_label.setStyleSheet(
            "padding: 4px 12px; "
            "background-color: #4a9eff; "
            "color: white; "
            "border-radius: 4px;"
        )
        h_layout.addWidget(self._state_label)
        
        return header
    
    def _create_overview_tab(self) -> QWidget:
        """Create overview tab."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        
        info_group = QGroupBox(_("VM Information"))
        info_layout = QVBoxLayout(info_group)
        
        self._info_rows = {}
        for label_text in [_("UUID"), _("State"), _("vCPUs"), _("Memory"), _("Max Memory"), _("Connection")]:
            row = QHBoxLayout()
            label = QLabel(label_text + ":")
            label.setStyleSheet("font-weight: bold;")
            value = QLabel("-")
            self._info_rows[label_text.lower().replace(" ", "_")] = value
            row.addWidget(label)
            row.addWidget(value, 1)
            info_layout.addLayout(row)
        
        layout.addWidget(info_group)
        layout.addStretch()
        
        scroll.setWidget(content)
        return scroll
    
    def _create_hardware_tab(self) -> QWidget:
        """Create hardware tab."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        
        content = QWidget()
        layout = QVBoxLayout(content)
        
        self._hw_table = QTableWidget()
        self._hw_table.setColumnCount(3)
        self._hw_table.setHorizontalHeaderLabels([_("Type"), _("Details"), _("Device")])
        self._hw_table.horizontalHeader().setStretchLastSection(True)
        self._hw_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._hw_table)
        
        layout.addStretch()
        
        scroll.setWidget(content)
        return scroll
    
    def _create_stats_tab(self) -> QWidget:
        """Create stats tab."""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        
        cpu_group = QGroupBox(_("CPU Usage"))
        cpu_layout = QVBoxLayout(cpu_group)
        self._cpu_bar = QProgressBar()
        self._cpu_bar.setRange(0, 100)
        self._cpu_bar.setTextVisible(True)
        cpu_layout.addWidget(self._cpu_bar)
        layout.addWidget(cpu_group)
        
        mem_group = QGroupBox(_("Memory Usage"))
        mem_layout = QVBoxLayout(mem_group)
        self._mem_bar = QProgressBar()
        self._mem_bar.setRange(0, 100)
        self._mem_bar.setTextVisible(True)
        mem_layout.addWidget(self._mem_bar)
        layout.addWidget(mem_group)
        
        io_group = QGroupBox(_("I/O"))
        io_layout = QVBoxLayout(io_group)
        
        disk_row = QHBoxLayout()
        disk_row.addWidget(QLabel(_("Disk:") + " "))
        self._disk_label = QLabel("-")
        disk_row.addWidget(self._disk_label, 1)
        io_layout.addLayout(disk_row)
        
        net_row = QHBoxLayout()
        net_row.addWidget(QLabel(_("Network:") + " "))
        self._net_label = QLabel("-")
        net_row.addWidget(self._net_label, 1)
        io_layout.addLayout(net_row)
        
        layout.addWidget(io_group)
        layout.addStretch()
        
        return content
    
    @pyqtSlot(object, str)
    def set_vm(self, vm, uri: str) -> None:
        """Set the VM to display."""
        self._vm = vm
        self._uri = uri
        
        if vm is None:
            self._name_label.setText(_("No VM Selected"))
            self._state_label.setText("")
            self._update_timer.stop()
            return
        
        self._name_label.setText(vm.name)
        self._update_ui()
        self._update_hardware()
        
        if vm.is_running:
            self._update_timer.start(2000)
        else:
            self._update_timer.stop()
    
    def _update_ui(self) -> None:
        """Update basic UI."""
        if not self._vm:
            return
        
        state_text = self._vm.state_str
        self._state_label.setText(state_text)
        
        state_style = {
            "Running": "background-color: #4caf50;",
            "Paused": "background-color: #ff9800;",
            "Shut Off": "background-color: #9e9e9e;",
            "Shutting Down": "background-color: #ff5722;",
            "Crashed": "background-color: #f44336;",
        }.get(state_text, "background-color: #607d8b;")
        
        self._state_label.setStyleSheet(
            f"padding: 4px 12px; color: white; border-radius: 4px; {state_style}"
        )
        
        self._info_rows["uuid"].setText(self._vm.uuid)
        self._info_rows["state"].setText(self._vm.state_str)
        self._info_rows["vcpus"].setText(str(self._vm.vcpus))
        self._info_rows["memory"].setText(f"{self._vm.memory_mb} MB")
        self._info_rows["max_memory"].setText(f"{self._vm.max_memory // 1024} MB")
        self._info_rows["connection"].setText(self._uri)
    
    def _update_hardware(self) -> None:
        """Update hardware table."""
        self._hw_table.setRowCount(0)
        
        if not self._vm:
            return
        
        try:
            xml = self._vm.get_xml()
            if xml:
                self._hw_table.setRowCount(1)
                self._hw_table.setItem(0, 0, QTableWidgetItem(_("XML Available")))
                self._hw_table.setItem(0, 1, QTableWidgetItem(_("%s bytes") % len(xml)))
        except Exception as e:
            self._hw_table.setRowCount(1)
            self._hw_table.setItem(0, 0, QTableWidgetItem(_("Error")))
            self._hw_table.setItem(0, 1, QTableWidgetItem(str(e)))
    
    def _update_stats(self) -> None:
        """Update statistics display."""
        if not self._vm:
            return
        
        cpu = self._vm.get_cpu_percent()
        self._cpu_bar.setValue(int(cpu))
        self._cpu_bar.setFormat(_("CPU: %.1f%%") % cpu)
        
        mem_percent = min(100, self._vm.memory / max(1, self._vm.max_memory) * 100)
        self._mem_bar.setValue(int(mem_percent))
        self._mem_bar.setFormat(_("Memory: %s MB (%.1f%%)") % (self._vm.memory_mb, mem_percent))
        
        disk_rate = self._vm.get_disk_rate()
        if disk_rate < 1024:
            self._disk_label.setText(_("%.0f KB/s") % disk_rate)
        else:
            self._disk_label.setText(_("%.1f MB/s") % (disk_rate/1024))
        
        net_rate = self._vm.get_network_rate()
        if net_rate < 1024:
            self._net_label.setText(_("%.0f B/s") % net_rate)
        elif net_rate < 1024 * 1024:
            self._net_label.setText(_("%.1f KB/s") % (net_rate/1024))
        else:
            self._net_label.setText(_("%.1f MB/s") % (net_rate/1024/1024))
    
    def clear(self) -> None:
        """Clear the panel."""
        self._vm = None
        self._uri = None
        self._name_label.setText(_("No VM Selected"))
        self._state_label.setText("")
        self._update_timer.stop()

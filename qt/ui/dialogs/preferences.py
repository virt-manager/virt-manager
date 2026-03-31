"""
Preferences dialog for Qt frontend.

Application settings configuration.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout,
    QSpinBox, QCheckBox, QComboBox,
    QDialogButtonBox, QGroupBox, QTabWidget, QWidget
)

from ..lib.i18n import _
from ...core.config import get_config


class PreferencesDialog(QDialog):
    """
    Preferences dialog.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Preferences"))
        self.setMinimumWidth(450)
        self._config = get_config()
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self) -> None:
        """Setup the preferences UI."""
        layout = QVBoxLayout(self)
        
        tabs = QTabWidget()
        
        tabs.addTab(self._create_general_tab(), _("General"))
        tabs.addTab(self._create_stats_tab(), _("Stats"))
        tabs.addTab(self._create_console_tab(), _("Console"))
        
        layout.addWidget(tabs)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _create_general_tab(self) -> QWidget:
        """Create general settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        ui_group = QGroupBox(_("Interface"))
        ui_layout = QVBoxLayout(ui_group)
        
        self._system_tray = QCheckBox(_("Show system tray icon"))
        ui_layout.addWidget(self._system_tray)
        
        self._toolbar = QCheckBox(_("Show toolbar"))
        self._toolbar.setChecked(True)
        ui_layout.addWidget(self._toolbar)
        
        layout.addWidget(ui_group)
        layout.addStretch()
        return tab

    def _create_stats_tab(self) -> QWidget:
        """Create stats settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        polling_group = QGroupBox(_("Stats Polling"))
        polling_layout = QFormLayout(polling_group)
        
        self._poll_interval = QSpinBox()
        self._poll_interval.setRange(1, 60)
        self._poll_interval.setSuffix(" seconds")
        polling_layout.addRow(_("Update interval:"), self._poll_interval)
        
        self._history_length = QSpinBox()
        self._history_length.setRange(10, 300)
        self._history_length.setSuffix(" samples")
        polling_layout.addRow(_("History length:"), self._history_length)
        
        layout.addWidget(polling_group)
        
        enable_group = QGroupBox(_("Enable Polling"))
        enable_layout = QVBoxLayout(enable_group)
        
        self._enable_cpu = QCheckBox(_("CPU usage"))
        self._enable_cpu.setChecked(True)
        enable_layout.addWidget(self._enable_cpu)
        
        self._enable_memory = QCheckBox(_("Memory usage"))
        self._enable_memory.setChecked(True)
        enable_layout.addWidget(self._enable_memory)
        
        self._enable_disk = QCheckBox(_("Disk I/O"))
        self._enable_disk.setChecked(True)
        enable_layout.addWidget(self._enable_disk)
        
        self._enable_network = QCheckBox(_("Network traffic"))
        self._enable_network.setChecked(True)
        enable_layout.addWidget(self._enable_network)
        
        layout.addWidget(enable_group)
        layout.addStretch()
        return tab

    def _create_console_tab(self) -> QWidget:
        """Create console settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        scaling_group = QGroupBox(_("Scaling"))
        scaling_layout = QFormLayout(scaling_group)
        
        self._scaling = QComboBox()
        self._scaling.addItem(_("Never"), 0)
        self._scaling.addItem(_("Fullscreen only"), 1)
        self._scaling.addItem(_("Always"), 2)
        scaling_layout.addRow(_("Console scaling:"), self._scaling)
        
        layout.addWidget(scaling_group)
        
        misc_group = QGroupBox(_("Miscellaneous"))
        misc_layout = QVBoxLayout(misc_group)
        
        self._auto_redirect = QCheckBox(_("Auto-redirect USB devices"))
        misc_layout.addWidget(self._auto_redirect)
        
        self._autoconnect = QCheckBox(_("Auto-connect to console on VM start"))
        self._autoconnect.setChecked(True)
        misc_layout.addWidget(self._autoconnect)
        
        layout.addWidget(misc_group)
        layout.addStretch()
        return tab

    def _load_settings(self) -> None:
        """Load current settings."""
        self._system_tray.setChecked(self._config.is_system_tray_enabled())
        self._toolbar.setChecked(self._config.is_toolbar_visible())
        
        self._poll_interval.setValue(self._config.get_stats_interval())
        self._history_length.setValue(self._config.get_stats_history_length())
        
        self._enable_cpu.setChecked(self._config.is_stats_enabled("cpu"))
        self._enable_memory.setChecked(self._config.is_stats_enabled("memory"))
        self._enable_disk.setChecked(self._config.is_stats_enabled("disk"))
        self._enable_network.setChecked(self._config.is_stats_enabled("network"))
        
        self._scaling.setCurrentIndex(self._config.get_console_scaling())
        self._auto_redirect.setChecked(self._config.is_auto_usbredir())
        self._autoconnect.setChecked(self._config.get("console/autoconnect", True))

    def _on_accept(self) -> None:
        """Save settings and accept."""
        self._config.set_system_tray_enabled(self._system_tray.isChecked())
        self._config.set_toolbar_visible(self._toolbar.isChecked())
        
        self._config.set_stats_interval(self._poll_interval.value())
        self._config.set("stats/history-length", self._history_length.value())
        
        self._config.set_stats_enabled("cpu", self._enable_cpu.isChecked())
        self._config.set_stats_enabled("memory", self._enable_memory.isChecked())
        self._config.set_stats_enabled("disk", self._enable_disk.isChecked())
        self._config.set_stats_enabled("network", self._enable_network.isChecked())
        
        self._config.set_console_scaling(self._scaling.currentData())
        self._config.set_auto_usbredir(self._auto_redirect.isChecked())
        self._config.set("console/autoconnect", self._autoconnect.isChecked())
        
        self.accept()

"""
Create VM wizard for Qt frontend.

Step-by-step wizard for creating new virtual machines.
"""

from PyQt6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QFormLayout,
    QLineEdit, QSpinBox, QComboBox, QCheckBox, QLabel, QTextEdit
)
from PyQt6.QtCore import Qt

from ..lib.i18n import _, ngettext


class CreateVmDialog(QWizard):
    """
    Create VM wizard.
    
    Multi-step wizard for VM creation:
    1. Name and OS
    2. Resources (CPU, Memory)
    3. Storage
    4. Network
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Create New Virtual Machine"))
        self.setMinimumSize(600, 500)
        
        self._name_value = ""
        self._os_value = ""
        self._distro_value = ""
        self._vcpus_value = 2
        self._memory_value = 4096
        self._disk_value = 50
        self._network_value = "nat"
        
        self._setup_pages()
    
    def _setup_pages(self) -> None:
        """Setup wizard pages."""
        self.addPage(self._create_os_page())
        self.addPage(self._create_resources_page())
        self.addPage(self._create_storage_page())
        self.addPage(self._create_network_page())
    
    def _create_os_page(self) -> QWizardPage:
        """Create OS selection page."""
        page = QWizardPage()
        page.setTitle(_("Operating System"))
        page.setSubTitle(_("Select the guest operating system"))
        
        layout = QVBoxLayout(page)
        
        form = QFormLayout()
        
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("my-virtual-machine")
        self._name_edit.textChanged.connect(lambda t: setattr(self, "_name_value", t))
        form.addRow(_("Name:"), self._name_edit)
        
        self._os_combo = QComboBox()
        self._os_combo.addItem(_("Generic"), "generic")
        self._os_combo.addItem(_("Linux"), "linux")
        self._os_combo.addItem(_("Windows"), "windows")
        self._os_combo.addItem(_("Other"), "other")
        self._os_combo.currentIndexChanged.connect(
            lambda i: setattr(self, "_os_value", self._os_combo.currentData())
        )
        form.addRow(_("Type:"), self._os_combo)
        
        self._distro_combo = QComboBox()
        self._distro_combo.addItem(_("Auto-detect"), "auto")
        self._distro_combo.addItem(_("Ubuntu 22.04"), "ubuntu22")
        self._distro_combo.addItem(_("Ubuntu 24.04"), "ubuntu24")
        self._distro_combo.addItem(_("Debian 12"), "debian12")
        self._distro_combo.addItem(_("Fedora 39"), "fedora39")
        self._distro_combo.addItem(_("CentOS Stream 9"), "centos9")
        self._distro_combo.addItem(_("Windows 10"), "win10")
        self._distro_combo.addItem(_("Windows 11"), "win11")
        self._distro_combo.addItem(_("Windows Server 2022"), "ws2022")
        self._distro_combo.currentIndexChanged.connect(
            lambda i: setattr(self, "_distro_value", self._distro_combo.currentText())
        )
        form.addRow(_("Distribution:"), self._distro_combo)
        
        layout.addLayout(form)
        layout.addStretch()
        
        return page
    
    def _create_resources_page(self) -> QWizardPage:
        """Create resources configuration page."""
        page = QWizardPage()
        page.setTitle(_("Resources"))
        page.setSubTitle(_("Configure CPU and memory"))
        
        layout = QVBoxLayout(page)
        
        cpu_group = QWizardPage()
        cpu_layout = QFormLayout()
        
        self._cpu_spin = QSpinBox()
        self._cpu_spin.setRange(1, 64)
        self._cpu_spin.setValue(2)
        self._cpu_spin.valueChanged.connect(
            lambda v: setattr(self, "_vcpus_value", v)
        )
        cpu_layout.addRow(_("vCPUs:"), self._cpu_spin)
        
        topology_check = QCheckBox(_("Custom topology"))
        cpu_layout.addRow("", topology_check)
        
        layout.addWidget(QLabel(_("CPU")))
        layout.addLayout(cpu_layout)
        
        mem_group = QWizardPage()
        mem_layout = QFormLayout()
        
        self._mem_spin = QSpinBox()
        self._mem_spin.setRange(256, 131072)
        self._mem_spin.setSingleStep(256)
        self._mem_spin.setValue(4096)
        self._mem_spin.setSuffix(" MB")
        self._mem_spin.valueChanged.connect(
            lambda v: setattr(self, "_memory_value", v)
        )
        mem_layout.addRow(_("Memory:"), self._mem_spin)
        
        layout.addWidget(QLabel(_("Memory")))
        layout.addLayout(mem_layout)
        layout.addStretch()
        
        return page
    
    def _create_storage_page(self) -> QWizardPage:
        """Create storage configuration page."""
        page = QWizardPage()
        page.setTitle(_("Storage"))
        page.setSubTitle(_("Configure virtual disk"))
        
        layout = QVBoxLayout(page)
        
        form = QFormLayout()
        
        self._disk_combo = QComboBox()
        self._disk_combo.addItem(_("Create disk image"), "create")
        self._disk_combo.addItem(_("Use existing disk image"), "existing")
        self._disk_combo.addItem(_("Do not configure disk"), "none")
        form.addRow(_("Disk:"), self._disk_combo)
        
        self._size_spin = QSpinBox()
        self._size_spin.setRange(1, 10000)
        self._size_spin.setValue(50)
        self._size_spin.setSuffix(" GB")
        self._size_spin.valueChanged.connect(
            lambda v: setattr(self, "_disk_value", v)
        )
        form.addRow(_("Size:"), self._size_spin)
        
        self._pool_combo = QComboBox()
        self._pool_combo.addItem(_("Default"), "default")
        form.addRow(_("Storage Pool:"), self._pool_combo)
        
        self._format_combo = QComboBox()
        self._format_combo.addItem(_("qcow2 (Recommended)"), "qcow2")
        self._format_combo.addItem(_("raw"), "raw")
        form.addRow(_("Format:"), self._format_combo)
        
        layout.addLayout(form)
        layout.addStretch()
        
        return page
    
    def _create_network_page(self) -> QWizardPage:
        """Create network configuration page."""
        page = QWizardPage()
        page.setTitle(_("Network"))
        page.setSubTitle(_("Configure network connectivity"))
        
        layout = QVBoxLayout(page)
        
        form = QFormLayout()
        
        self._net_combo = QComboBox()
        self._net_combo.addItem(_("NAT (Default)"), "nat")
        self._net_combo.addItem(_("Bridge to host"), "bridge")
        self._net_combo.addItem(_("No network"), "none")
        self._net_combo.addItem(_("Specify shared device name..."), "custom")
        self._net_combo.currentIndexChanged.connect(
            lambda i: setattr(self, "_network_value", self._net_combo.currentData())
        )
        form.addRow(_("Network:"), self._net_combo)
        
        self._mac_edit = QLineEdit()
        self._mac_edit.setPlaceholderText(_("Auto-generate"))
        form.addRow(_("MAC Address:"), self._mac_edit)
        
        layout.addLayout(form)
        layout.addStretch()
        
        return page
    
    def get_config(self) -> dict:
        """Get the VM configuration."""
        return {
            "name": self._name_value or "vm",
            "os": self._os_value,
            "distro": self._distro_value,
            "vcpus": self._vcpus_value,
            "memory": self._memory_value,
            "disk_size": self._disk_value,
            "disk_format": self._format_combo.currentData(),
            "network": self._network_value,
        }

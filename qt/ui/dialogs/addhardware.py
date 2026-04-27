from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog,
    QTreeWidget, QTreeWidgetItem, QFormLayout, QComboBox,
    QLineEdit, QCheckBox, QGroupBox, QScrollArea, QMessageBox,
    QSpinBox, QDoubleSpinBox, QTextEdit, QFileDialog, QGridLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ..lib.i18n import _, ngettext


class vmmAddHardware(QDialog):
    def __init__(self, conn, vm, engine):
        super().__init__()
        self.conn = conn
        self.vm = vm
        self.engine = engine
        self._hw_type = None
        self._config_widget = None
        
        self.setWindowTitle(_("Add Hardware"))
        self.setModal(True)
        self.setMinimumSize(600, 500)
        
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        hw_list = QTreeWidget()
        hw_list.setHeaderLabels([_("Hardware Type")])
        hw_list.setColumnWidth(0, 300)
        
        hw_categories = [
            (_("Storage"), [
                (_("Storage"), "drive-harddisk", self._add_storage),
            ]),
            (_("Network"), [
                (_("Network"), "network-idle", self._add_network),
            ]),
            (_("Input"), [
                (_("Keyboard"), "input-keyboard", self._add_keyboard),
                (_("Mouse"), "input-mouse", self._add_mouse),
                (_("Tablet"), "input-tablet", self._add_tablet),
            ]),
            (_("Graphics"), [
                (_("Graphics"), "video-display", self._add_graphics),
            ]),
            (_("Sound"), [
                (_("Sound"), "audio-card", self._add_sound),
            ]),
            (_("Video"), [
                (_("Video"), "video-display", self._add_video),
            ]),
            (_("Serial"), [
                (_("Serial"), "accessories-text-editor", self._add_serial),
                (_("Parallel"), "accessories-text-editor", self._add_parallel),
                (_("Console"), "accessories-text-editor", self._add_console),
            ]),
            (_("Channel"), [
                (_("Channel"), "network-idle", self._add_channel),
            ]),
            (_("USB"), [
                (_("USB Host"), "computer", self._add_usb_host),
            ]),
            (_("PCI"), [
                (_("PCI Host"), "computer", self._add_pci_host),
            ]),
            (_("Security"), [
                (_("Smartcard"), "security-high", self._add_smartcard),
                (_("TPM"), "security-high", self._add_tpm),
            ]),
            (_("Random"), [
                (_("RNG"), "drive-harddisk", self._add_rng),
            ]),
            (_("Filesystem"), [
                (_("Filesystem"), "folder", self._add_filesystem),
            ]),
            (_("VSOCK"), [
                (_("VSOCK"), "network-idle", self._add_vsock),
            ]),
        ]
        
        self._hw_handlers = {}
        for category, hw_list_items in hw_categories:
            cat_item = QTreeWidgetItem(hw_list)
            cat_item.setText(0, category)
            cat_item.setExpanded(False)
            for hw_type, icon, handler in hw_list_items:
                item = QTreeWidgetItem(cat_item)
                item.setText(0, hw_type)
                self._hw_handlers[hw_type] = handler
        
        hw_list.currentItemChanged.connect(self._hw_selected)
        layout.addWidget(hw_list, 1)
        
        self._details_widget = QWidget()
        self._details_layout = QVBoxLayout(self._details_widget)
        layout.addWidget(self._details_widget, 2)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        finish_btn = QPushButton(_("Finish"))
        finish_btn.clicked.connect(self._finish)
        finish_btn.setDefault(True)
        button_layout.addWidget(finish_btn)
        
        layout.addLayout(button_layout)

    def _hw_selected(self, current, previous):
        while self._details_layout.count():
            item = self._details_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not current:
            return
        
        hw_type = current.text(0)
        if hw_type not in self._hw_handlers:
            return
        
        self._hw_type = hw_type
        handler = self._hw_handlers[hw_type]
        handler()

    def _create_config_widget(self, title):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        header = QLabel(_("<b>Configure %s</b>") % title)
        header.setStyleSheet("padding: 8px;")
        layout.addWidget(header)
        self._config_scroll = QScrollArea()
        self._config_scroll.setWidgetResizable(True)
        self._config_scroll_widget = QWidget()
        self._config_scroll_layout = QVBoxLayout(self._config_scroll_widget)
        self._config_scroll.setWidget(self._config_scroll_widget)
        layout.addWidget(self._config_scroll)
        self._config_layout = QFormLayout()
        self._config_scroll_layout.addLayout(self._config_layout)
        self._config_widget = widget
        self._details_layout.addWidget(widget)

    def _add_storage(self):
        self._create_config_widget(_("Storage"))
        
        type_combo = QComboBox()
        type_combo.addItems([_("Disk Device"), _("CDROM Device"), _("Floppy Device")])
        self._config_layout.addRow(_("Device Type:"), type_combo)
        
        self._storage_cache_combo = QComboBox()
        self._storage_cache_combo.addItems([_("default"), _("none"), _("writethrough"), _("writeback"), _("directsync"), _("unsafe")])
        self._config_layout.addRow(_("Cache Mode:"), self._storage_cache_combo)
        
        bus_combo = QComboBox()
        bus_combo.addItems([_("Auto"), _("IDE"), _("SATA"), _("USB"), _("SCSI"), _("VirtIO")])
        self._config_layout.addRow(_("Bus:"), bus_combo)
        
        dev_entry = QLineEdit()
        self._config_layout.addRow(_("Device Target:"), dev_entry)

    def _add_network(self):
        self._create_config_widget(_("Network"))
        
        type_combo = QComboBox()
        type_combo.addItems([_("Virtual Network"), _("Bridge to LAN"), _("Direct attachment"), _("PCI Passthrough"), _("USB Passthrough")])
        self._config_layout.addRow(_("Network Source:"), type_combo)
        
        mac_entry = QLineEdit()
        self._config_layout.addRow(_("MAC Address:"), mac_entry)
        
        model_combo = QComboBox()
        model_combo.addItems([_("Auto"), "rtl8139", "e1000", "e1000e", "virtio", "ne2k_pci", "pcnet"])
        self._config_layout.addRow(_("Device Model:"), model_combo)

    def _add_keyboard(self):
        self._create_config_widget(_("Keyboard"))
        
        layout_combo = QComboBox()
        layout_combo.addItems(["en-us", "en-gb", "de", "fr", "it", "es", "pt-br", "ja", "ru"])
        self._config_layout.addRow(_("Layout:"), layout_combo)

    def _add_mouse(self):
        self._create_config_widget(_("Mouse"))
        
        type_combo = QComboBox()
        type_combo.addItems([_("PS2 Mouse"), _("USB Mouse"), _("Tablet"), _("Wheel")])
        self._config_layout.addRow(_("Type:"), type_combo)

    def _add_tablet(self):
        self._create_config_widget(_("Tablet"))
        
        bus_combo = QComboBox()
        bus_combo.addItems([_("USB"), _("VirtIO")])
        self._config_layout.addRow(_("Bus:"), bus_combo)

    def _add_graphics(self):
        self._create_config_widget(_("Graphics"))
        
        type_combo = QComboBox()
        type_combo.addItems([_("VNC"), _("Spice")])
        self._config_layout.addRow(_("Type:"), type_combo)
        
        port_combo = QComboBox()
        port_combo.addItems([_("Auto"), _("Specify")])
        self._config_layout.addRow(_("Port:"), port_combo)
        
        listen_entry = QLineEdit("127.0.0.1")
        self._config_layout.addRow(_("Listen Address:"), listen_entry)

    def _add_sound(self):
        self._create_config_widget(_("Sound"))
        
        model_combo = QComboBox()
        model_combo.addItems(["AC97", "ich6", "ich9", "ES1370", "pcspk", "usb"])
        self._config_layout.addRow(_("Sound Model:"), model_combo)

    def _add_video(self):
        self._create_config_widget(_("Video"))
        
        model_combo = QComboBox()
        model_combo.addItems(["VGA", "Cirrus", "VMVGA", "Xen", "VBox", "QXL", "Virtio", "GOP", "None"])
        self._config_layout.addRow(_("Model:"), model_combo)
        
        ram_spin = QSpinBox()
        ram_spin.setRange(0, 512)
        ram_spin.setSuffix(" MB")
        self._config_layout.addRow(_("VRAM:"), ram_spin)

    def _add_serial(self):
        self._create_config_widget(_("Serial"))
        
        type_combo = QComboBox()
        type_combo.addItems([_("Pseudo TTY"), _("Device"), _("Pipe"), _("Socket"), "TCP", "UDP"])
        self._config_layout.addRow(_("Type:"), type_combo)

    def _add_parallel(self):
        self._create_config_widget(_("Parallel"))
        
        type_combo = QComboBox()
        type_combo.addItems([_("Pseudo TTY"), _("Device"), _("Pipe"), _("Socket")])
        self._config_layout.addRow(_("Type:"), type_combo)

    def _add_console(self):
        self._create_config_widget(_("Console"))
        
        type_combo = QComboBox()
        type_combo.addItems([_("Pseudo TTY"), _("Device"), _("Socket")])
        self._config_layout.addRow(_("Type:"), type_combo)

    def _add_channel(self):
        self._create_config_widget(_("Channel"))
        
        type_combo = QComboBox()
        type_combo.addItems([_("Spice Agent"), _("QEMU Agent"), _("GuestFwd"), _("Device")])
        self._config_layout.addRow(_("Type:"), type_combo)

    def _add_usb_host(self):
        self._create_config_widget(_("USB Host Device"))
        
        vendor_spin = QSpinBox()
        vendor_spin.setRange(0, 65535)
        vendor_spin.setPrefix(_("Vendor: 0x"))
        self._config_layout.addRow("", vendor_spin)
        
        product_spin = QSpinBox()
        product_spin.setRange(0, 65535)
        product_spin.setPrefix(_("Product: 0x"))
        self._config_layout.addRow("", product_spin)

    def _add_pci_host(self):
        self._create_config_widget(_("PCI Host Device"))
        
        domain_spin = QSpinBox()
        domain_spin.setRange(0, 65535)
        domain_spin.setPrefix(_("Domain: 0x"))
        self._config_layout.addRow("", domain_spin)
        
        bus_spin = QSpinBox()
        bus_spin.setRange(0, 255)
        bus_spin.setPrefix(_("Bus: 0x"))
        self._config_layout.addRow("", bus_spin)
        
        slot_spin = QSpinBox()
        slot_spin.setRange(0, 31)
        slot_spin.setPrefix(_("Slot: 0x"))
        self._config_layout.addRow("", slot_spin)
        
        func_spin = QSpinBox()
        func_spin.setRange(0, 7)
        func_spin.setPrefix(_("Function: 0x"))
        self._config_layout.addRow("", func_spin)

    def _add_smartcard(self):
        self._create_config_widget(_("Smartcard"))
        
        mode_combo = QComboBox()
        mode_combo.addItems([_("Passthrough"), _("Host"), _("Controller")])
        self._config_layout.addRow(_("Mode:"), mode_combo)

    def _add_tpm(self):
        self._create_config_widget(_("TPM"))
        
        version_combo = QComboBox()
        version_combo.addItems(["1.2", "2.0"])
        self._config_layout.addRow(_("Version:"), version_combo)
        
        type_combo = QComboBox()
        type_combo.addItems([_("Passthrough"), _("Emulator"), "SysFS"])
        self._config_layout.addRow(_("Type:"), type_combo)

    def _add_rng(self):
        self._create_config_widget(_("Random Number Generator"))
        
        type_combo = QComboBox()
        type_combo.addItems([_("Random"), "EGD", _("Host Device")])
        self._config_layout.addRow(_("Type:"), type_combo)

    def _add_filesystem(self):
        self._create_config_widget(_("Filesystem"))
        
        type_combo = QComboBox()
        type_combo.addItems([_("Mount"), _("Template"), _("RAM"), _("Device")])
        self._config_layout.addRow(_("Type:"), type_combo)
        
        source_entry = QLineEdit()
        self._config_layout.addRow(_("Source Path:"), source_entry)
        
        target_entry = QLineEdit()
        self._config_layout.addRow(_("Target Path:"), target_entry)

    def _add_vsock(self):
        self._create_config_widget(_("VSOCK"))
        
        cid_combo = QComboBox()
        cid_combo.addItems([_("Auto"), _("Address"), _("None")])
        self._config_layout.addRow(_("CID Mode:"), cid_combo)
        
        cid_spin = QSpinBox()
        cid_spin.setRange(0, 0xFFFFFFFF)
        self._config_layout.addRow(_("CID Value:"), cid_spin)

    def _finish(self):
        if not self._hw_type:
            QMessageBox.information(self, _("Add Hardware"), _("Please select hardware type to add"))
            return
        
        QMessageBox.information(
            self, _("Add Hardware"), 
            _("Adding %s hardware...\n\nThis will modify the VM configuration.") % self._hw_type
        )
        self.accept()

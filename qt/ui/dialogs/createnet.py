import ipaddress

from ..lib.i18n import _, ngettext
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QComboBox, QGroupBox, QFormLayout,
    QScrollArea, QWidget, QListWidget, QListWidgetItem, QMessageBox,
    QGridLayout, QTabWidget, QWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class vmmCreateNetwork(QDialog):
    def __init__(self, conn, engine):
        super().__init__()
        self.conn = conn
        self.engine = engine
        
        self.setWindowTitle(_("Create Virtual Network"))
        self.setModal(True)
        self.setMinimumSize(700, 500)
        
        self._init_ui()
        self._reset_state()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        name_layout = QFormLayout()
        self._name_entry = QLineEdit()
        name_layout.addRow(_("Name:"), self._name_entry)
        layout.addLayout(name_layout)
        
        forward_mode_group = QGroupBox(_("Network Forward Mode"))
        forward_layout = QFormLayout(forward_mode_group)
        
        self._forward_mode_combo = QComboBox()
        self._forward_mode_combo.addItems([_("NAT"), _("Routed"), _("Open"), _("Isolated")])
        self._forward_mode_combo.currentIndexChanged.connect(self._forward_mode_changed)
        forward_layout.addRow(_("Mode:"), self._forward_mode_combo)
        
        self._forward_device_combo = QComboBox()
        self._forward_device_combo.addItems([_("Any physical device"), _("Specify physical device...")])
        forward_layout.addRow(_("Device:"), self._forward_device_combo)
        
        layout.addWidget(forward_mode_group)
        
        self._ipv4_group = QGroupBox(_("IPv4 Settings"))
        ipv4_layout = QVBoxLayout(self._ipv4_group)
        
        self._ipv4_enable = QCheckBox(_("Enable IPv4"))
        self._ipv4_enable.setChecked(True)
        ipv4_layout.addWidget(self._ipv4_enable)
        
        ipv4_form = QFormLayout()
        self._ipv4_network = QLineEdit("192.168.100.0/24")
        ipv4_form.addRow(_("Network:"), self._ipv4_network)
        
        self._dhcpv4_enable = QCheckBox(_("Enable DHCPv4"))
        self._dhcpv4_enable.setChecked(True)
        ipv4_form.addRow(_("DHCP:"), self._dhcpv4_enable)
        
        dhcp4_layout = QHBoxLayout()
        self._dhcpv4_start = QLineEdit("192.168.100.128")
        self._dhcpv4_end = QLineEdit("192.168.100.254")
        dhcp4_layout.addWidget(QLabel(_("Start:")))
        dhcp4_layout.addWidget(self._dhcpv4_start)
        dhcp4_layout.addWidget(QLabel(_("End:")))
        dhcp4_layout.addWidget(self._dhcpv4_end)
        ipv4_form.addRow("", dhcp4_layout)
        
        ipv4_layout.addLayout(ipv4_form)
        layout.addWidget(self._ipv4_group)
        
        self._ipv6_group = QGroupBox(_("IPv6 Settings"))
        self._ipv6_group.setCheckable(True)
        self._ipv6_group.setChecked(False)
        ipv6_layout = QVBoxLayout(self._ipv6_group)
        
        ipv6_form = QFormLayout()
        self._ipv6_network = QLineEdit()
        ipv6_form.addRow(_("Network:"), self._ipv6_network)
        
        self._dhcpv6_enable = QCheckBox(_("Enable DHCPv6"))
        ipv6_form.addRow(_("DHCP:"), self._dhcpv6_enable)
        
        dhcp6_layout = QHBoxLayout()
        self._dhcpv6_start = QLineEdit()
        self._dhcpv6_end = QLineEdit()
        dhcp6_layout.addWidget(QLabel(_("Start:")))
        dhcp6_layout.addWidget(self._dhcpv6_start)
        dhcp6_layout.addWidget(QLabel(_("End:")))
        dhcp6_layout.addWidget(self._dhcpv6_end)
        ipv6_form.addRow("", dhcp6_layout)
        
        ipv6_layout.addLayout(ipv6_form)
        layout.addWidget(self._ipv6_group)
        
        self._xml_text = None
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        create_btn = QPushButton(_("Create"))
        create_btn.clicked.connect(self._finish)
        create_btn.setDefault(True)
        button_layout.addWidget(create_btn)
        
        layout.addLayout(button_layout)

    def _reset_state(self):
        self._name_entry.setText("network")
        self._forward_mode_combo.setCurrentIndex(0)
        self._ipv4_enable.setChecked(True)
        self._ipv4_network.setText("192.168.100.0/24")
        self._dhcpv4_enable.setChecked(True)
        self._dhcpv4_start.setText("192.168.100.128")
        self._dhcpv4_end.setText("192.168.100.254")
        self._ipv6_group.setChecked(False)
        self._ipv6_network.clear()
        self._dhcpv6_enable.setChecked(False)
        self._dhcpv6_start.clear()
        self._dhcpv6_end.clear()

    def _forward_mode_changed(self, index):
        mode_map = {0: "nat", 1: "route", 2: "open", 3: "isolated"}
        mode = mode_map.get(index, "nat")
        self._forward_device_combo.setEnabled(mode in ["nat", "route"])

    def _finish(self):
        name = self._name_entry.text().strip()
        if not name:
            QMessageBox.warning(self, _("Error"), _("Please enter a network name"))
            return
        
        mode_map = {0: "nat", 1: "route", 2: "open", 3: "isolated"}
        mode = mode_map.get(self._forward_mode_combo.currentIndex(), "nat")
        
        try:
            from virtinst import Network
            import libvirt
            
            conn = self.conn.get_backend()
            conn.networkLookupByName(name)
            QMessageBox.warning(self, _("Error"), _("Name '%s' already in use by another network.") % name)
            return
        except libvirt.libvirtError:
            pass
        
        try:
            from virtinst import Network
            
            conn = self.conn.get_backend()
            net = Network(conn)
            net.name = name
            
            if mode != "isolated":
                net.forward.mode = mode
            
            if self._ipv4_enable.isChecked():
                ip_str = self._ipv4_network.text()
                try:
                    ip = ipaddress.ip_network(ip_str, strict=False)
                    ipobj = net.ips.add_new()
                    ipobj.address = str(ip.network_address + 1)
                    ipobj.netmask = str(ip.netmask)
                    
                    if self._dhcpv4_enable.isChecked():
                        dhcpobj = ipobj.ranges.add_new()
                        dhcpobj.start = self._dhcpv4_start.text()
                        dhcpobj.end = self._dhcpv4_end.text()
                except Exception as e:
                    QMessageBox.warning(self, _("Error"), _("Invalid IPv4 network: %s") % e)
                    return
            
            if self._ipv6_group.isChecked():
                ip_str = self._ipv6_network.text()
                if ip_str:
                    try:
                        ip = ipaddress.ip_network(ip_str, strict=False)
                        ipobj = net.ips.add_new()
                        ipobj.family = "ipv6"
                        ipobj.address = str(ip.network_address + 1)
                        ipobj.prefix = str(ip.prefixlen)
                        
                        if self._dhcpv6_enable.isChecked():
                            dhcpobj = ipobj.ranges.add_new()
                            dhcpobj.start = self._dhcpv6_start.text()
                            dhcpobj.end = self._dhcpv6_end.text()
                    except Exception as e:
                        QMessageBox.warning(self, _("Error"), _("Invalid IPv6 network: %s") % e)
                        return
            
            xml = net.get_xml()
            
            from .asyncjob import vmmAsyncJob
            
            def async_create(job, net_xml):
                conn = self.conn.get_backend()
                netobj = conn.networkDefineXML(net_xml)
                netobj.create()
                netobj.setAutostart(True)
            
            def finish_cb(error, details):
                if error:
                    QMessageBox.critical(self, _("Error"), _("Error creating network: %s\n%s") % (error, details))
                else:
                    self.accept()
            
            vmmAsyncJob(
                async_create,
                [xml],
                finish_cb,
                [],
                _("Creating virtual network"),
                _("Creating..."),
                self
            ).run()
            
        except Exception as e:
            QMessageBox.critical(self, _("Error"), _("Error creating network: %s") % e)

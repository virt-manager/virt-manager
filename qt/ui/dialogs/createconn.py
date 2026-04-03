import glob
import os
import urllib.parse

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QFormLayout, QGroupBox,
    QMessageBox
)
from PyQt6.QtCore import Qt

from ..lib.i18n import _


(HV_QEMU, HV_XEN, HV_LXC, HV_QEMU_SESSION, HV_BHYVE, HV_VZ, HV_CUSTOM) = range(7)


def _default_uri():
    if os.path.exists("/var/lib/xen"):
        if os.path.exists("/dev/xen/evtchn") or os.path.exists("/proc/xen"):
            return "xen:///"
    
    if (
        os.path.exists("/usr/bin/qemu")
        or os.path.exists("/usr/bin/qemu-kvm")
        or os.path.exists("/usr/bin/kvm")
        or os.path.exists("/usr/libexec/qemu-kvm")
        or glob.glob("/usr/bin/qemu-system-*")
    ):
        return "qemu:///system"
    
    if os.path.exists("/usr/lib/libvirt/libvirt_lxc") or os.path.exists("/usr/lib64/libvirt/libvirt_lxc"):
        return "lxc:///"
    return None


class ConnectionDialog(QDialog):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        
        self.setWindowTitle(_("Open Connection"))
        self.setModal(True)
        self.setMinimumSize(500, 300)
        
        self._init_ui()
        self._populate_uri()

    def get_uri(self):
        hv = self._hypervisor_combo.currentData()
        if hv == HV_CUSTOM:
            return self._uri_entry.text()
        return self._generate_uri()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        hypervisor_group = QGroupBox(_("Hypervisor"))
        hyper_layout = QVBoxLayout(hypervisor_group)
        
        self._hypervisor_combo = QComboBox()
        self._hypervisor_combo.addItem(_("QEMU/KVM"), HV_QEMU)
        self._hypervisor_combo.addItem(_("QEMU/KVM (user session)"), HV_QEMU_SESSION)
        self._hypervisor_combo.addItem(_("Xen"), HV_XEN)
        self._hypervisor_combo.addItem(_("Libvirt-LXC"), HV_LXC)
        self._hypervisor_combo.addItem(_("Bhyve"), HV_BHYVE)
        self._hypervisor_combo.addItem(_("Virtuozzo"), HV_VZ)
        self._hypervisor_combo.addItem(_("Custom URI..."), HV_CUSTOM)
        self._hypervisor_combo.currentIndexChanged.connect(self._hypervisor_changed)
        hyper_layout.addWidget(self._hypervisor_combo)
        
        self._session_warning = QLabel(
            _("Warning: User session connections have limited functionality.\n"
            "System mode is recommended for full virtualization features.")
        )
        self._session_warning.setStyleSheet("color: #856404; background-color: #fff3cd; padding: 8px; border-radius: 4px;")
        self._session_warning.setWordWrap(True)
        self._session_warning.setVisible(False)
        hyper_layout.addWidget(self._session_warning)
        
        layout.addWidget(hypervisor_group)
        
        self._remote_group = QGroupBox(_("Connection"))
        remote_layout = QFormLayout(self._remote_group)
        
        self._connect_remote = QCheckBox(_("Connect to remote host"))
        self._connect_remote.toggled.connect(self._remote_toggled)
        remote_layout.addRow("", self._connect_remote)
        
        self._username = QLineEdit()
        remote_layout.addRow(_("Username:"), self._username)
        
        self._hostname = QLineEdit()
        remote_layout.addRow(_("Hostname:"), self._hostname)
        
        remote_layout.addRow(_("Auto connect:"), QCheckBox())
        
        layout.addWidget(self._remote_group)
        
        uri_group = QGroupBox(_("Connection URI"))
        uri_layout = QVBoxLayout(uri_group)
        
        self._uri_label = QLabel()
        self._uri_label.setWordWrap(True)
        font = self._uri_label.font()
        font.setFamily("monospace")
        self._uri_label.setFont(font)
        uri_layout.addWidget(self._uri_label)
        
        self._uri_entry = QLineEdit()
        self._uri_entry.setVisible(False)
        uri_layout.addWidget(self._uri_entry)
        
        layout.addWidget(uri_group)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        connect_btn = QPushButton(_("Connect"))
        connect_btn.clicked.connect(self._open_conn)
        connect_btn.setDefault(True)
        button_layout.addWidget(connect_btn)
        
        layout.addLayout(button_layout)
        
        self._remote_toggled(False)

    def _default_uri(self):
        return _default_uri()

    def _hypervisor_changed(self, index):
        hv = self._hypervisor_combo.currentData()
        
        is_session = hv == HV_QEMU_SESSION
        is_custom = hv == HV_CUSTOM
        show_remote = not is_session and not is_custom
        
        self._session_warning.setVisible(is_session)
        self._connect_remote.setVisible(show_remote)
        self._username.setVisible(show_remote)
        self._hostname.setVisible(show_remote)
        
        self._uri_label.setVisible(not is_custom)
        self._uri_entry.setVisible(is_custom)
        
        if is_custom:
            self._uri_entry.setFocus()
        
        self._populate_uri()

    def _remote_toggled(self, checked):
        self._hostname.setEnabled(checked)
        self._username.setEnabled(checked)
        
        if checked and not self._username.text():
            self._username.setText("root")
        
        self._populate_uri()

    def _username_changed(self, text):
        self._populate_uri()

    def _hostname_changed(self, text):
        self._populate_uri()

    def _populate_uri(self):
        uri = self._generate_uri()
        self._uri_label.setText(uri)

    def _generate_uri(self):
        hv = self._hypervisor_combo.currentData()
        host = self._hostname.text().strip()
        user = self._username.text()
        is_remote = self._connect_remote.isChecked()
        
        hvstr = ""
        if hv == HV_XEN:
            hvstr = "xen"
        elif hv in (HV_QEMU, HV_QEMU_SESSION):
            hvstr = "qemu"
        elif hv == HV_BHYVE:
            hvstr = "bhyve"
        elif hv == HV_VZ:
            hvstr = "vz"
        else:
            hvstr = "lxc"
        
        addrstr = ""
        if user:
            addrstr += urllib.parse.quote(user) + "@"
        
        if host.count(":") > 1:
            host = f"[{host}]"
        addrstr += host
        
        if is_remote:
            hoststr = f"+ssh://{addrstr}/"
        else:
            hoststr = ":///"
        
        uri = hvstr + hoststr
        if hv in (HV_QEMU, HV_BHYVE, HV_VZ):
            uri += "system"
        elif hv == HV_QEMU_SESSION:
            uri += "session"
        
        return uri

    def _validate(self):
        is_remote = self._connect_remote.isChecked()
        host = self._hostname.text()
        
        if is_remote and not host:
            QMessageBox.warning(self, _("Error"), _("A hostname is required for remote connections."))
            return False
        return True

    def _open_conn(self):
        if not self._validate():
            return
        
        hv = self._hypervisor_combo.currentData()
        if hv == HV_CUSTOM:
            uri = self._uri_entry.text()
        else:
            uri = self._generate_uri()
        
        from ...core.connmanager import vmmConnectionManager
        conn_manager = vmmConnectionManager.get_instance()
        
        conn = conn_manager.add_conn(uri)
        
        try:
            if not conn.is_active():
                conn.open()
        except Exception as e:
            QMessageBox.critical(self, _("Error"), _("Failed to connect: ") + str(e))
            return
        
        self.accept()

    def show(self, parent=None):
        if parent:
            self.setParent(parent)
        self.exec()

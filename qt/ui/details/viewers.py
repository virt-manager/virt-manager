from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from ..lib.i18n import _


try:
    import socket
    import struct
    HAS_VNC = True
except ImportError:
    HAS_VNC = False


class VNCViewer(QWidget):
    def __init__(self, host, port, vm=None, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = port
        self._vm = vm
        self._socket = None
        self._connected = False
        
        self._init_ui()
        self._connect()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self._label = QLabel(_("Connecting to %s:%s...") % (self._host, self._port))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("""
            background-color: #2d2d2d;
            color: #ffffff;
            padding: 20px;
            font-size: 14px;
        """)
        layout.addWidget(self._label)
        
        self._error_label = QLabel()
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setStyleSheet("color: #ff6b6b; padding: 10px;")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

    def _connect(self):
        if not HAS_VNC:
            self._show_error(_("VNC support requires the 'socket' module"))
            return
        
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(5)
            self._socket.connect((self._host, self._port))
            self._connected = True
            self._label.setText(_("Connected! VNC data streaming..."))
            self._label.setStyleSheet("""
                background-color: #1a1a1a;
                color: #00ff00;
                padding: 20px;
                font-size: 14px;
            """)
        except Exception as e:
            self._show_error(_("Failed to connect: %s") % e)

    def _show_error(self, msg):
        self._label.setText(_("Connection Failed"))
        self._label.setStyleSheet("""
            background-color: #2d2d2d;
            color: #ff6b6b;
            padding: 20px;
            font-size: 14px;
        """)
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    def cleanup(self):
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def take_screenshot(self, path):
        """Save screenshot to file."""
        raise NotImplementedError(_("Screenshot not supported for VNC viewer"))

    def send_key(self, key):
        """Send key combination to VM."""
        raise NotImplementedError(_("Key sending not supported for VNC viewer"))


class SpiceViewer(QWidget):
    def __init__(self, host, port, vm=None, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = port
        self._vm = vm
        
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self._label = QLabel(_("SPICE viewer for %s:%s") % (self._host, self._port) + "\n\n"
                           + _("Note: Full SPICE support requires spice-gtk or similar.") + "\n"
                           + _("For now, use virt-viewer or a web-based SPICE client."))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("""
            background-color: #1a1a2e;
            color: #eaeaea;
            padding: 40px;
            font-size: 14px;
        """)
        layout.addWidget(self._label)

    def cleanup(self):
        self._vm = None

    def take_screenshot(self, path):
        """Save screenshot to file."""
        raise NotImplementedError(_("Screenshot not supported for SPICE viewer"))

    def send_key(self, key):
        """Send key combination to VM."""
        raise NotImplementedError(_("Key sending not supported for SPICE viewer"))


def open_viewer(vm, ginfo):
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
    from PyQt6.QtCore import Qt
    
    ginfo_host = getattr(ginfo, 'host', None) or 'localhost'
    ginfo_port = getattr(ginfo, 'port', None) or 5900
    
    dialog = QDialog()
    dialog.setWindowTitle(_("Console - %s") % vm.get_name())
    dialog.setMinimumSize(640, 480)
    
    layout = QVBoxLayout(dialog)
    
    viewer = None
    if getattr(ginfo, 'type', None) == 'spice':
        viewer = SpiceViewer(ginfo_host, ginfo_port, vm)
    else:
        viewer = VNCViewer(ginfo_host, ginfo_port, vm)
    
    layout.addWidget(viewer)
    
    button_layout = QHBoxLayout()
    button_layout.addStretch()
    
    close_btn = QPushButton(_("Close"))
    close_btn.clicked.connect(dialog.accept)
    button_layout.addWidget(close_btn)
    
    layout.addLayout(button_layout)
    
    dialog.finished.connect(lambda: viewer.cleanup() if hasattr(viewer, 'cleanup') else None)
    
    return dialog

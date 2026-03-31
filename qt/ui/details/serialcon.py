from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from ..lib.i18n import _


class SerialConsole(QWidget):
    def __init__(self, vm, device=None, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._device = device
        self._connected = False
        self._socket = None
        
        self._init_ui()
        self._connect()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        info_layout = QHBoxLayout()
        info_layout.addWidget(QLabel(_("Serial Console - %s") % self._vm.get_name()))
        info_layout.addStretch()
        
        self._connect_btn = QPushButton(_("Disconnect"))
        self._connect_btn.clicked.connect(self._toggle_connection)
        info_layout.addWidget(self._connect_btn)
        
        layout.addLayout(info_layout)
        
        self._terminal = QTextEdit()
        self._terminal.setReadOnly(True)
        font = QFont("monospace")
        font.setPointSize(10)
        self._terminal.setFont(font)
        self._terminal.setStyleSheet("background-color: #000000; color: #00ff00;")
        layout.addWidget(self._terminal)
        
        input_layout = QHBoxLayout()
        self._input = QTextEdit()
        self._input.setMaximumHeight(30)
        self._input.setFont(font)
        input_layout.addWidget(self._input)
        
        send_btn = QPushButton(_("Send"))
        send_btn.clicked.connect(self._send_input)
        input_layout.addWidget(send_btn)
        
        layout.addLayout(input_layout)

    def _connect(self):
        self._terminal.append(_("Connecting to serial console..."))
        self._connected = True
        self._terminal.append(_("Connected (serial console requires PTY allocation)"))

    def _disconnect(self):
        self._terminal.append(_("Disconnecting..."))
        self._connected = False
        self._connect_btn.setText(_("Connect"))

    def _toggle_connection(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _send_input(self):
        text = self._input.toPlainText()
        if text and self._connected:
            self._terminal.append(f"> {text}")
            self._input.clear()

    def cleanup(self):
        self._disconnect()

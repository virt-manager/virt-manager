"""
Console window for Qt frontend.

SPICE/VNC console integration for VM display.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QMenuBar, QMenu, QToolBar, QStatusBar,
    QFileDialog, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence

from .lib.i18n import _


class ConsoleWindow(QWidget):
    """
    Console window for VM display.
    
    Provides SPICE/VNC console integration for graphical VM access.
    """

    def __init__(self, vm, conn, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._conn = conn
        self._viewer = None
        self._fullscreen = False
        self._setup_ui()
        self._connect_console()
    
    def _setup_ui(self) -> None:
        """Setup the console UI."""
        self.setWindowTitle(_("Console - %s") % self._vm.get_name())
        self.resize(800, 600)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        toolbar = QToolBar()
        main_layout.addWidget(toolbar)
        
        self._fullscreen_action = QAction(_("Fullscreen"), self)
        self._fullscreen_action.setShortcut(QKeySequence("F11"))
        self._fullscreen_action.triggered.connect(self._toggle_fullscreen)
        toolbar.addAction(self._fullscreen_action)
        
        toolbar.addSeparator()
        
        self._screenshot_action = QAction(_("Screenshot"), self)
        self._screenshot_action.triggered.connect(self._take_screenshot)
        toolbar.addAction(self._screenshot_action)
        
        toolbar.addSeparator()
        
        send_menu = QMenu(_("Send Key"), self)
        send_menu.addAction(_("Ctrl+Alt+Del"), lambda: self._send_key("ctrl-alt-del"))
        send_menu.addAction(
            _("Ctrl+Alt+Backspace"),
            lambda: self._send_key("ctrl-alt-backspace")
        )
        send_menu.addAction(_("Ctrl+Alt+F1"), lambda: self._send_key("ctrl-alt-f1"))
        send_menu.addAction(_("Ctrl+Alt+F2"), lambda: self._send_key("ctrl-alt-f2"))
        send_menu.addAction(_("Ctrl+Alt+F3"), lambda: self._send_key("ctrl-alt-f3"))
        send_menu.addAction(_("Print"), lambda: self._send_key("print"))
        toolbar.addAction(send_menu.menuAction())
        
        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self._content_widget, 1)
        
        self._status_label = QLabel()
        self._status_label.setStyleSheet("background-color: #333; color: #fff; padding: 2px 8px;")
        main_layout.addWidget(self._status_label)
        
        self._viewer_container = None
        self._show_connecting()
    
    def _show_connecting(self):
        """Show connecting message."""
        for i in reversed(range(self._content_layout.count())):
            widget = self._content_layout.itemAt(i).widget()
            if widget:
                widget.setVisible(False)
        
        connecting_label = QLabel(_("Connecting to console..."))
        connecting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        connecting_label.setStyleSheet("background-color: #2d2d2d; color: #fff; padding: 100px; font-size: 16px;")
        self._content_layout.addWidget(connecting_label)
        self._status_label.setText(_("Connecting..."))
    
    def _connect_console(self):
        """Connect to VM console."""
        try:
            if not self._vm or not self._vm.domain:
                self._show_error(_("VM not found"))
                return
            
            gfx_info = self._get_graphics_info()
            if not gfx_info:
                self._show_error(_("No graphics device configured for this VM"))
                return
            
            self._show_viewer(gfx_info)
            
        except Exception as e:
            self._show_error(_("Failed to connect: %s") % str(e))
    
    def _get_graphics_info(self):
        """Get graphics device info from VM."""
        try:
            xml = self._vm.domain.XMLDesc(0)
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            
            for gfx in root.findall(".//devices/graphics"):
                gfx_type = gfx.get('type', 'vnc')
                listen = gfx.get('listen', '0.0.0.0')
                port = gfx.get('port')
                passwd = gfx.find('auth')
                if passwd is not None:
                    passwd = passwd.get('passwd')
                
                return {
                    'type': gfx_type,
                    'host': gfx.get('address') or listen,
                    'port': int(port) if port else (5900 if gfx_type == 'vnc' else 5900),
                    'password': passwd,
                }
        except Exception:
            pass
        return None
    
    def _show_viewer(self, gfx_info):
        """Show the appropriate viewer for graphics type."""
        for i in reversed(range(self._content_layout.count())):
            widget = self._content_layout.itemAt(i).widget()
            if widget:
                widget.setVisible(False)
                if widget != self._status_label:
                    widget.deleteLater()
        
        if gfx_info['type'] == 'spice':
            from .details.viewers import SpiceViewer
            self._viewer = SpiceViewer(gfx_info['host'], gfx_info['port'], self._vm)
        else:
            from .details.viewers import VNCViewer
            self._viewer = VNCViewer(gfx_info['host'], gfx_info['port'], self._vm)
        
        self._content_layout.addWidget(self._viewer, 1)
        self._status_label.setText(_("Connected: %s:%d") % (gfx_info['host'], gfx_info['port']))
    
    def _show_error(self, message):
        """Show error message."""
        for i in reversed(range(self._content_layout.count())):
            widget = self._content_layout.itemAt(i).widget()
            if widget and widget != self._status_label:
                widget.deleteLater()
        
        error_label = QLabel(f"<span style='color: #ff6b6b; font-size: 16px;'>{message}</span>")
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_label.setStyleSheet("background-color: #2d2d2d; padding: 100px;")
        self._content_layout.addWidget(error_label)
        self._status_label.setText(_("Error"))
    
    def _toggle_fullscreen(self):
        """Toggle fullscreen mode."""
        if self._fullscreen:
            self.showNormal()
            self._fullscreen = False
        else:
            self.showFullScreen()
            self._fullscreen = True
    
    def _take_screenshot(self):
        """Take a screenshot of the console."""
        if not self._viewer:
            QMessageBox.information(self, _("Screenshot"), _("Console not connected"))
            return
        
        default_name = f"{self._vm.get_name()}_screenshot.png"
        path, _ = QFileDialog.getSaveFileName(
            self, _("Save Screenshot"), default_name,
            _("PNG Image (*.png)")
        )
        
        if path:
            try:
                self._viewer.take_screenshot(path)
                QMessageBox.information(self, _("Screenshot"), _("Screenshot saved to: %s") % path)
            except Exception as e:
                QMessageBox.critical(self, _("Error"), _("Failed to save screenshot: %s") % str(e))
    
    def _send_key(self, key):
        """Send key combination to VM."""
        if not self._viewer:
            return
        
        try:
            self._viewer.send_key(key)
        except Exception as e:
            QMessageBox.warning(self, _("Warning"), _("Failed to send key: %s") % str(e))
    
    def cleanup(self):
        """Cleanup console resources."""
        if self._viewer:
            self._viewer.cleanup()
            self._viewer = None

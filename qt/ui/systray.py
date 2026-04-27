"""
System tray integration for Qt frontend.
"""

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtCore import QObject, pyqtSlot
from PyQt6.QtGui import QIcon, QAction

from .lib.i18n import _


class SystemTray(QObject):
    """
    System tray integration for virt-manager.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(parent)
        self._tray.setToolTip(_("virt-manager"))
        self._setup_menu()
        self._tray.activated.connect(self._on_activated)
    
    def _setup_menu(self):
        menu = QMenu()

        self._show_action = QAction(_("Show"), menu)
        self._show_action.triggered.connect(self._on_show)
        menu.addAction(self._show_action)

        menu.addSeparator()

        quit_action = QAction(_("Quit"), menu)
        quit_action.triggered.connect(self._on_quit)
        menu.addAction(quit_action)
        
        self._tray.setContextMenu(menu)
    
    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_show()
    
    @pyqtSlot()
    def _on_show(self):
        from .mainwindow import MainWindow
        for widget in self._tray.parent().topLevelWidgets():
            if isinstance(widget, MainWindow):
                widget.show()
                widget.raise_()
                widget.activateWindow()
                break
    
    @pyqtSlot()
    def _on_quit(self):
        from .mainwindow import MainWindow
        for widget in self._tray.parent().topLevelWidgets():
            if isinstance(widget, MainWindow):
                widget.close()
                break
    
    def show(self):
        self._tray.show()
    
    def hide(self):
        self._tray.hide()
    
    def setIcon(self, icon):
        self._tray.setIcon(icon)
    
    def showMessage(
        self, title, message,
        icon=QSystemTrayIcon.MessageIcon.Information, msecs=3000
    ):
        self._tray.showMessage(title, message, icon, msecs)
    
    def isVisible(self):
        return self._tray.isVisible()


class NotificationManager:
    """
    Manager for system notifications.
    """
    
    def __init__(self, tray=None):
        self._tray = tray
    
    def notify(self, title, message, icon="dialog-information"):
        if self._tray:
            icon_map = {
                "dialog-information": QSystemTrayIcon.MessageIcon.Information,
                "dialog-warning": QSystemTrayIcon.MessageIcon.Warning,
                "dialog-error": QSystemTrayIcon.MessageIcon.Critical,
            }
            self._tray.showMessage(title, message, icon_map.get(icon, QSystemTrayIcon.MessageIcon.Information))
    
    def vm_started(self, name):
        self.notify(_("VM Started"), f"{name} is now running", "dialog-information")

    def vm_stopped(self, name):
        self.notify(_("VM Stopped"), f"{name} has been stopped", "dialog-information")

    def vm_error(self, name, error):
        self.notify(_("VM Error"), f"{name}: {error}", "dialog-error")

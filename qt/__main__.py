"""
qt - Entry point for Qt/KDE frontend.

Main entry point for the Qt/KDE frontend of virt-manager.
"""

import os
import sys
import logging
import time

os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")


def setup_logging() -> None:
    """Setup basic logging."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(levelname)s: %(message)s"))
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.DEBUG)


def main() -> int:
    """
    Main entry point.
    
    Initializes Qt application, engine, and shows main window.
    """
    setup_logging()
    log = logging.getLogger("virtmanagerqt")
    
    log.info("Starting virt-manager Qt frontend")
    
    try:
        import libvirt
        log.info(f"libvirt version: {libvirt.getVersion()}")
    except Exception as e:
        log.error(f"libvirt check failed: {e}")
    
    sys.stdout.flush()
    sys.stderr.flush()
    
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer
    
    log.info("Creating QApplication...")
    sys.stdout.flush()
    
    app = QApplication(sys.argv)
    app.setApplicationName("virt-manager")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("virt-manager")
    app.setOrganizationDomain("virt-manager.org")
    
    log.info("QApplication created")
    sys.stdout.flush()
    
    window = None
    engine = None
    
    def delayed_ui():
        log.info("Starting delayed UI init...")
        nonlocal window
        
        try:
            from .ui.mainwindow import MainWindow
            log.info("MainWindow imported")
            
            window = MainWindow()
            log.info("MainWindow created")
            
            window.show()
            log.info("MainWindow shown")
            
        except Exception as e:
            log.error(f"UI init failed: {e}", exc_info=True)
            app.quit()
    
    def delayed_engine():
        log.info("Starting delayed engine init...")
        nonlocal engine
        
        try:
            from .core.config import get_config
            config = get_config()
            log.info("Config loaded")
            
            from .core.engine import get_engine
            engine = get_engine()
            log.info("Engine loaded")
            
            engine.start()
            log.info("Engine started")
            
        except Exception as e:
            log.error(f"Engine init failed: {e}", exc_info=True)
    
    log.info("Scheduling delayed init...")
    sys.stdout.flush()
    
    QTimer.singleShot(500, delayed_ui)
    QTimer.singleShot(1500, delayed_engine)
    
    log.info("Entering event loop")
    ret = app.exec()
    log.info(f"Event loop exited with code {ret}")
    
    if engine:
        engine.stop()
    
    return ret


if __name__ == "__main__":
    sys.exit(main())

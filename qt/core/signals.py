from PyQt6.QtCore import QObject, pyqtSignal


class Signals(QObject):
    """
    Global application-wide signals.
    """
    
    vm_added = pyqtSignal(str, str)  # (uri, uuid)
    vm_removed = pyqtSignal(str, str)  # (uri, uuid)
    vm_state_changed = pyqtSignal(str, str)  # (uri, uuid)
    vm_stats_updated = pyqtSignal(str, str)  # (uri, uuid)
    
    connection_added = pyqtSignal(str)  # uri
    connection_removed = pyqtSignal(str)  # uri
    connection_state_changed = pyqtSignal(str, str)  # (uri, state)
    
    _instance = None
    
    def __init__(self):
        super().__init__()
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def get_signals() -> Signals:
    """Get the global signals instance."""
    return Signals.get_instance()

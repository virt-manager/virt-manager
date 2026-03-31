from PyQt6.QtCore import pyqtSignal


def QtSignal(*args, **kwargs):
    return pyqtSignal(*args, **kwargs)


class Signals:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


_signals = None


def get_signals() -> Signals:
    global _signals
    if _signals is None:
        _signals = Signals()
    return _signals

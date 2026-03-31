"""
Main engine for Qt/KDE frontend.
"""

import logging
from typing import Optional

logger = logging.getLogger("virtmanagerqt.engine")


class Engine:
    """
    Main application engine.
    """
    
    _instance: Optional["Engine"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._config = None
        self._connections: dict = {}
        self._running = False
        self._stats_timer = None
        
        self._load_config()
    
    def _load_config(self):
        """Load config lazily."""
        if self._config is None:
            from .config import get_config
            self._config = get_config()
    
    def add_connection(self, uri: str):
        """Add and connect to a hypervisor."""
        if uri in self._connections:
            return self._connections[uri]
        
        try:
            from ..bridge.connwrapper import ConnectionWrapper
            conn = ConnectionWrapper(uri)
            self._connections[uri] = conn
            
            if self._config and self._config.is_autoconnect(uri):
                conn.connect_async()
            
            return conn
        except Exception as e:
            logger.error(f"Failed to add connection {uri}: {e}")
            return None
    
    def remove_connection(self, uri: str) -> None:
        """Remove a connection."""
        if uri not in self._connections:
            return
        
        conn = self._connections.pop(uri)
        conn.close()
        
        if self._config:
            self._config.remove_connection(uri)
    
    def get_connection(self, uri: str):
        """Get a connection by URI."""
        return self._connections.get(uri)
    
    def get_connections(self) -> dict:
        """Get all connections."""
        return self._connections.copy()
    
    def start(self) -> None:
        """Start the engine."""
        if self._running:
            return
        
        self._running = True
        logger.info("Engine started")
    
    def stop(self) -> None:
        """Stop the engine."""
        if not self._running:
            return
        
        self._running = False
        
        for conn in list(self._connections.values()):
            conn.close()
        
        if self._config:
            self._config.sync()
        logger.info("Engine stopped")


_engine = None


def get_engine() -> "Engine":
    """Get the Engine singleton instance."""
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine

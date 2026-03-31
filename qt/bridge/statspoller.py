"""
Stats poller for VM statistics.
"""

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QTimer

from ..core.config import get_config

if TYPE_CHECKING:
    from .connwrapper import ConnectionWrapper

logger = logging.getLogger("virtmanagerqt.bridge.stats")


class StatsPoller(QObject):
    """
    Efficient stats poller for VM statistics.
    """
    
    def __init__(self, conn: "ConnectionWrapper"):
        super().__init__()
        self._conn = conn
        self._config = get_config()
        self._timer = QTimer(self)
        self._running = False
        
        interval_ms = self._config.get_stats_interval() * 1000
        self._timer.timeout.connect(self._poll)
        self._timer.setInterval(interval_ms)
    
    def start(self) -> None:
        """Start polling."""
        if self._running:
            return
        self._running = True
        self._timer.start()
        logger.debug(f"Stats poller started for {self._conn.uri}")
    
    def stop(self) -> None:
        """Stop polling."""
        if not self._running:
            return
        self._running = False
        self._timer.stop()
        logger.debug(f"Stats poller stopped for {self._conn.uri}")
    
    def _poll(self) -> None:
        """Poll all VMs for statistics."""
        if not self._conn.is_active:
            return
        
        try:
            for vm in self._conn.list_vms():
                vm.update_stats()
            
            self._conn.stats_updated.emit()
            
        except Exception as e:
            logger.error(f"Stats polling failed: {e}")
    
    def set_interval(self, seconds: int) -> None:
        """Change polling interval."""
        self._timer.setInterval(seconds * 1000)
    
    @property
    def is_running(self) -> bool:
        """Check if poller is running."""
        return self._running

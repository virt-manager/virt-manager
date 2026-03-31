"""
VM wrapper for libvirt domains.

Provides Qt signals for VM state changes and stats updates.
"""

import logging
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal

try:
    import libvirt
    LIBVIRT_AVAILABLE = True
except ImportError:
    LIBVIRT_AVAILABLE = False

if TYPE_CHECKING:
    from .connwrapper import ConnectionWrapper

logger = logging.getLogger("virtmanagerqt.bridge.vm")


class VmWrapper(QObject):
    """
    Qt wrapper for a libvirt domain.
    
    Provides signals for state changes and manages domain operations.
    """
    
    STATE_NOSTATE = 0
    STATE_RUNNING = 1
    STATE_BLOCKED = 2
    STATE_PAUSED = 3
    STATE_SHUTDOWN = 4
    STATE_SHUTOFF = 5
    STATE_CRASHED = 6
    STATE_PMSUSPENDED = 7
    
    state_changed = pyqtSignal()
    stats_updated = pyqtSignal()
    
    def __init__(self, conn: "ConnectionWrapper", domain):
        super().__init__()
        self._conn = conn
        self._domain = domain
        self._uuid = domain.UUIDString() if LIBVIRT_AVAILABLE and domain else ""
        self._stats_cache = {
            "cpu_time": 0,
            "cpu_percent": 0.0,
            "memory": 0,
            "disk_rd_rate": 0.0,
            "disk_wr_rate": 0.0,
            "net_rx_rate": 0.0,
            "net_tx_rate": 0.0,
        }
        self._prev_stats = None
    
    @property
    def uuid(self) -> str:
        """Get VM UUID."""
        return self._uuid
    
    @property
    def name(self) -> str:
        """Get VM name."""
        try:
            return self._domain.name()
        except Exception:
            return ""
    
    @property
    def conn(self) -> "ConnectionWrapper":
        """Get parent connection."""
        return self._conn
    
    @property
    def domain(self):
        """Get the libvirt domain."""
        return self._domain
    
    @property
    def state(self) -> int:
        """Get VM state code."""
        try:
            return self._domain.state()[0]
        except Exception:
            return self.STATE_SHUTOFF
    
    @property
    def state_str(self) -> str:
        """Get human-readable state."""
        states = {
            self.STATE_NOSTATE: "No State",
            self.STATE_RUNNING: "Running",
            self.STATE_BLOCKED: "Blocked",
            self.STATE_PAUSED: "Paused",
            self.STATE_SHUTDOWN: "Shutting Down",
            self.STATE_SHUTOFF: "Shut Off",
            self.STATE_CRASHED: "Crashed",
            self.STATE_PMSUSPENDED: "Suspended",
        }
        return states.get(self.state, "Unknown")
    
    @property
    def is_running(self) -> bool:
        """Check if VM is running."""
        return self.state == self.STATE_RUNNING
    
    @property
    def is_paused(self) -> bool:
        """Check if VM is paused."""
        return self.state == self.STATE_PAUSED
    
    @property
    def is_shutoff(self) -> bool:
        """Check if VM is shut off."""
        return self.state == self.STATE_SHUTOFF
    
    @property
    def is_crashed(self) -> bool:
        """Check if VM is crashed."""
        return self.state == self.STATE_CRASHED
    
    @property
    def vcpus(self) -> int:
        """Get number of virtual CPUs."""
        try:
            info = self._domain.vcpus()
            return len(info) if info else 1
        except Exception:
            return 1
    
    @property
    def memory(self) -> int:
        """Get memory in KB."""
        try:
            stats = self._domain.memoryStats()
            return stats.get("rss", 0)
        except Exception:
            return 0
    
    @property
    def memory_mb(self) -> int:
        """Get memory in MB."""
        return self.memory // 1024
    
    @property
    def max_memory(self) -> int:
        """Get max memory in KB."""
        try:
            return self._domain.maxMemory()
        except Exception:
            return 0
    
    def update_stats(self) -> None:
        """Update cached statistics."""
        if not self.is_running:
            return
        
        try:
            stats = self._domain.memoryStats()
            
            if self._prev_stats and "_timestamp" in self._prev_stats:
                time_diff = (
                    stats.get("_timestamp", 0) - self._prev_stats.get("_timestamp", 0)
                )
                if time_diff > 0:
                    cpu_diff = stats.get("cpu_time", 0) - self._prev_stats.get("cpu_time", 0)
                    self._stats_cache["cpu_percent"] = min(100, (cpu_diff / time_diff / 1e9) * 100)
            
            self._stats_cache.update(stats)
            self._prev_stats = stats.copy()
            self.stats_updated.emit()
            
        except Exception as e:
            logger.debug(f"Failed to update stats for {self.name}: {e}")
    
    def get_cpu_percent(self) -> float:
        """Get CPU usage percentage."""
        return self._stats_cache.get("cpu_percent", 0.0)
    
    def get_disk_rate(self) -> float:
        """Get disk I/O rate."""
        return self._stats_cache.get("disk_rd_rate", 0.0) + self._stats_cache.get("disk_wr_rate", 0.0)
    
    def get_network_rate(self) -> float:
        """Get network I/O rate."""
        return self._stats_cache.get("net_rx_rate", 0.0) + self._stats_cache.get("net_tx_rate", 0.0)
    
    def get_stats(self) -> dict:
        """Get all cached stats."""
        return self._stats_cache.copy()
    
    def start(self) -> bool:
        """Start the VM."""
        try:
            if self.is_shutoff or self.is_crashed:
                self._domain.create()
            elif self.is_paused:
                self._domain.resume()
            self.state_changed.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to start {self.name}: {e}")
            return False
    
    def shutdown(self) -> bool:
        """Gracefully shutdown the VM."""
        try:
            self._domain.shutdown()
            self.state_changed.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to shutdown {self.name}: {e}")
            return False
    
    def destroy(self) -> bool:
        """Force stop the VM."""
        try:
            self._domain.destroy()
            self.state_changed.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to destroy {self.name}: {e}")
            return False
    
    def pause(self) -> bool:
        """Pause the VM."""
        try:
            self._domain.suspend()
            self.state_changed.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to pause {self.name}: {e}")
            return False
    
    def resume(self) -> bool:
        """Resume the VM."""
        try:
            self._domain.resume()
            self.state_changed.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to resume {self.name}: {e}")
            return False
    
    def reboot(self) -> bool:
        """Reboot the VM."""
        try:
            self._domain.reboot(0)
            return True
        except Exception as e:
            logger.error(f"Failed to reboot {self.name}: {e}")
            return False
    
    def delete(self, delete_storage: bool = False) -> bool:
        """Delete the VM."""
        try:
            flags = libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE
            if delete_storage:
                flags |= libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
                flags |= libvirt.VIR_DOMAIN_UNDEFINE_NVRAM
            self._domain.undefineFlags(flags)
            self._domain = None
            return True
        except Exception:
            try:
                self._domain.undefine()
                self._domain = None
                return True
            except Exception as e:
                logger.error(f"Failed to delete {self.name}: {e}")
                return False
    
    def get_xml(self, inactive: bool = False) -> str:
        """Get domain XML."""
        try:
            flags = libvirt.VIR_DOMAIN_XML_INACTIVE if inactive else libvirt.VIR_DOMAIN_XML_SECURE
            return self._domain.XMLDesc(flags)
        except Exception:
            return ""
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.state_changed.disconnect()
        self.stats_updated.disconnect()

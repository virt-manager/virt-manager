"""
Storage wrapper for libvirt storage pools and volumes.

Provides Qt signals for storage events.
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

logger = logging.getLogger("virtmanagerqt.bridge.storage")


class StoragePoolWrapper(QObject):
    """
    Qt wrapper for a libvirt storage pool.
    """
    
    STATE_INACTIVE = 0
    STATE_INITIALIZING = 1
    STATE_RUNNING = 2
    STATE_DEGRADED = 3
    STATE_FAILED = 4
    
    state_changed = pyqtSignal()
    
    def __init__(self, conn: "ConnectionWrapper", pool):
        super().__init__()
        self._conn = conn
        self._pool = pool
        self._name = pool.name() if pool else ""
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def state(self) -> int:
        try:
            return self._pool.info()[0]
        except Exception:
            return self.STATE_INACTIVE
    
    @property
    def state_str(self) -> str:
        states = {
            self.STATE_INACTIVE: "Inactive",
            self.STATE_INITIALIZING: "Initializing",
            self.STATE_RUNNING: "Running",
            self.STATE_DEGRADED: "Degraded",
            self.STATE_FAILED: "Failed",
        }
        return states.get(self.state, "Unknown")
    
    @property
    def capacity(self) -> int:
        try:
            return self._pool.info()[1]
        except Exception:
            return 0
    
    @property
    def allocation(self) -> int:
        try:
            return self._pool.info()[2]
        except Exception:
            return 0
    
    @property
    def available(self) -> int:
        try:
            return self._pool.info()[3]
        except Exception:
            return 0
    
    def refresh(self) -> bool:
        try:
            self._pool.refresh(0)
            return True
        except Exception as e:
            logger.error(f"Failed to refresh pool {self._name}: {e}")
            return False
    
    def start(self) -> bool:
        try:
            self._pool.create(0)
            self.state_changed.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to start pool {self._name}: {e}")
            return False
    
    def stop(self) -> bool:
        try:
            self._pool.destroy()
            self.state_changed.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to stop pool {self._name}: {e}")
            return False
    
    def delete(self, delete_volumes: bool = False) -> bool:
        try:
            flags = libvirt.VIR_STORAGE_POOL_DELETE_NORMAL
            if delete_volumes:
                flags = libvirt.VIR_STORAGE_POOL_DELETE_WITH_SNAPSHOTS_RECURSIVE
            self._pool.delete(flags)
            return True
        except Exception as e:
            logger.error(f"Failed to delete pool {self._name}: {e}")
            return False
    
    def get_volumes(self) -> list:
        try:
            return self._pool.listAllVolumes()
        except Exception:
            return []
    
    def get_xml(self) -> str:
        try:
            return self._pool.XMLDesc(0)
        except Exception:
            return ""


class StorageVolumeWrapper:
    """
    Wrapper for a libvirt storage volume.
    """
    
    TYPE_FILE = "file"
    TYPE_BLOCK = "block"
    TYPE_DIR = "dir"
    TYPE_NETWORK = "network"
    TYPE_PLOOP = "ploop"
    
    def __init__(self, pool, volume):
        self._pool = pool
        self._volume = volume
    
    @property
    def name(self) -> str:
        try:
            return self._volume.name()
        except Exception:
            return ""
    
    @property
    def path(self) -> str:
        try:
            return self._volume.path()
        except Exception:
            return ""
    
    @property
    def capacity(self) -> int:
        try:
            return self._volume.info()[1]
        except Exception:
            return 0
    
    @property
    def allocation(self) -> int:
        try:
            return self._volume.info()[2]
        except Exception:
            return 0
    
    def delete(self) -> bool:
        try:
            self._volume.delete(0)
            return True
        except Exception as e:
            logger.error(f"Failed to delete volume {self.name}: {e}")
            return False
    
    def get_xml(self) -> str:
        try:
            return self._volume.XMLDesc(0)
        except Exception:
            return ""


class NetworkWrapper(QObject):
    """
    Qt wrapper for a libvirt network.
    """
    
    STATE_INACTIVE = 0
    STATE_ACTIVE = 1
    
    state_changed = pyqtSignal()
    
    def __init__(self, conn: "ConnectionWrapper", network):
        super().__init__()
        self._conn = conn
        self._network = network
        self._name = network.name() if network else ""
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def uuid(self) -> str:
        try:
            return self._network.UUIDString()
        except Exception:
            return ""
    
    @property
    def bridge_name(self) -> str:
        try:
            xml = self._network.XMLDesc(0)
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            bridge = root.find("bridge")
            if bridge is not None:
                return bridge.get("name", "")
        except Exception:
            pass
        return ""
    
    @property
    def is_active(self) -> bool:
        try:
            return self._network.isActive()
        except Exception:
            return False
    
    @property
    def state_str(self) -> str:
        return "Active" if self.is_active else "Inactive"
    
    def start(self) -> bool:
        try:
            self._network.create()
            self.state_changed.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to start network {self._name}: {e}")
            return False
    
    def stop(self) -> bool:
        try:
            self._network.destroy()
            self.state_changed.emit()
            return True
        except Exception as e:
            logger.error(f"Failed to stop network {self._name}: {e}")
            return False
    
    def delete(self) -> bool:
        try:
            self._network.undefine()
            return True
        except Exception as e:
            logger.error(f"Failed to delete network {self._name}: {e}")
            return False
    
    def get_xml(self) -> str:
        try:
            return self._network.XMLDesc(0)
        except Exception:
            return ""


class SnapshotWrapper(QObject):
    """
    Qt wrapper for a libvirt domain snapshot.
    """
    
    state_changed = pyqtSignal()
    
    def __init__(self, vm, snapshot):
        super().__init__()
        self._vm = vm
        self._snapshot = snapshot
    
    @property
    def name(self) -> str:
        try:
            return self._snapshot.getName()
        except Exception:
            return ""
    
    @property
    def creation_time(self) -> str:
        try:
            xml = self._snapshot.getXMLDesc(0)
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            return root.findtext("creationTime", "")
        except Exception:
            return ""
    
    def delete(self) -> bool:
        try:
            self._snapshot.delete(0)
            return True
        except Exception as e:
            logger.error(f"Failed to delete snapshot {self.name}: {e}")
            return False
    
    def revert(self) -> bool:
        try:
            self._vm.revertToSnapshot(self._snapshot)
            return True
        except Exception as e:
            logger.error(f"Failed to revert to snapshot {self.name}: {e}")
            return False
    
    def get_xml(self) -> str:
        try:
            return self._snapshot.getXMLDesc(0)
        except Exception:
            return ""

"""
Connection wrapper for libvirt connections.

Thin wrapper around libvirt with Qt signals.
Thread-safe operations with signal updates on the main thread.
"""

import logging
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

try:
    import libvirt
    LIBVIRT_AVAILABLE = True
except ImportError:
    LIBVIRT_AVAILABLE = False

from .vmwrapper import VmWrapper
from .statspoller import StatsPoller

logger = logging.getLogger("virtmanagerqt.bridge.conn")


class ConnectionWrapper(QObject):
    """
    Qt wrapper for libvirt connection.
    
    Provides Qt signals for connection events and manages
    VM wrappers for all domains on this connection.
    """
    
    STATE_DISCONNECTED = "disconnected"
    STATE_CONNECTING = "connecting"
    STATE_ACTIVE = "active"
    
    state_changed = pyqtSignal(str)
    error = pyqtSignal(str, str)
    vm_added = pyqtSignal(str)
    vm_removed = pyqtSignal(str)
    vm_state_changed = pyqtSignal(str)
    vm_stats_updated = pyqtSignal(str)
    stats_updated = pyqtSignal()
    
    def __init__(self, uri: str):
        super().__init__()
        self._uri = uri
        self._state = self.STATE_DISCONNECTED
        self._conn = None
        self._vms: dict[str, VmWrapper] = {}
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._closing = False
        self._stats_poller: Optional[StatsPoller] = None
    
    @property
    def uri(self) -> str:
        """Get the connection URI."""
        return self._uri
    
    @property
    def state(self) -> str:
        """Get current connection state."""
        return self._state
    
    @property
    def is_active(self) -> bool:
        """Check if connection is active."""
        return self._state == self.STATE_ACTIVE
    
    @property
    def is_connecting(self) -> bool:
        """Check if connection is in progress."""
        return self._state == self.STATE_CONNECTING
    
    @property
    def is_disconnected(self) -> bool:
        """Check if connection is disconnected."""
        return self._state == self.STATE_DISCONNECTED
    
    @property
    def backend(self):
        """Get the libvirt connection."""
        return self._conn
    
    def connect_sync(self) -> bool:
        """Synchronous connect (blocking)."""
        if self._state != self.STATE_DISCONNECTED:
            return True
        
        self._set_state(self.STATE_CONNECTING)
        
        try:
            if not LIBVIRT_AVAILABLE:
                raise RuntimeError("libvirt not available")
            
            self._conn = libvirt.open(self._uri)
            self._populate_initial_state()
            self._set_state(self.STATE_ACTIVE)
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._set_state(self.STATE_DISCONNECTED)
            self.error.emit(str(e), "")
            return False
    
    def connect_async(self) -> None:
        """Asynchronous connect (non-blocking)."""
        if self._state != self.STATE_DISCONNECTED:
            return
        
        self._set_state(self.STATE_CONNECTING)
        self._thread = threading.Thread(
            target=self._connect_thread,
            name=f"Connect {self._uri}",
            daemon=True
        )
        self._thread.start()
    
    def _connect_thread(self) -> None:
        """Thread target for async connection."""
        try:
            if not LIBVIRT_AVAILABLE:
                raise RuntimeError("libvirt not available")
            
            self._conn = libvirt.open(self._uri)
            self._populate_initial_state()
            self._set_state(self.STATE_ACTIVE)
            
        except Exception as e:
            logger.error(f"Async connection failed: {e}")
            self._set_state(self.STATE_DISCONNECTED)
            self.error.emit(str(e), "")
    
    def _populate_initial_state(self) -> None:
        """Populate initial VM state after connection."""
        if not self._conn:
            return
        
        try:
            self._stats_poller = StatsPoller(self)
            self._stats_poller.start()
            
            for domain in self._conn.listAllDomains():
                self._add_vm(domain)
                
        except Exception as e:
            logger.error(f"Failed to populate initial state: {e}")
    
    def close(self) -> None:
        """Close the connection."""
        if self._state == self.STATE_DISCONNECTED:
            return
        
        self._closing = True
        
        if self._stats_poller:
            self._stats_poller.stop()
            self._stats_poller = None
        
        for vm in list(self._vms.values()):
            vm.cleanup()
        self._vms.clear()
        
        if self._conn:
            try:
                self._conn.close()
            except Exception as e:
                logger.debug(f"Error closing connection: {e}")
        
        self._set_state(self.STATE_DISCONNECTED)
        self._closing = False
    
    def _set_state(self, new_state: str) -> None:
        """Set connection state and emit signal."""
        if self._state != new_state:
            self._state = new_state
            logger.debug(f"Connection {self._uri} state: {new_state}")
            self.state_changed.emit(new_state)
    
    def _add_vm(self, domain) -> Optional[VmWrapper]:
        """Add a VM from a libvirt domain."""
        try:
            uuid = domain.UUIDString()
            
            with self._lock:
                if uuid in self._vms:
                    return self._vms[uuid]
                
                vm = VmWrapper(self, domain)
                vm.state_changed.connect(lambda: self.vm_state_changed.emit(uuid))
                vm.stats_updated.connect(lambda: self.vm_stats_updated.emit(uuid))
                self._vms[uuid] = vm
            
            self.vm_added.emit(uuid)
            return vm
            
        except Exception as e:
            logger.error(f"Failed to add VM: {e}")
            return None
    
    def remove_vm(self, uuid: str) -> None:
        """Remove a VM."""
        with self._lock:
            if uuid not in self._vms:
                return
            
            vm = self._vms.pop(uuid)
            vm.cleanup()
        
        self.vm_removed.emit(uuid)
    
    def get_vm(self, uuid: str) -> Optional[VmWrapper]:
        """Get a VM by UUID."""
        return self._vms.get(uuid)
    
    def get_vms(self) -> dict[str, VmWrapper]:
        """Get all VMs."""
        return self._vms.copy()
    
    def list_vms(self) -> list[VmWrapper]:
        """List all VMs."""
        return list(self._vms.values())
    
    def get_vm_by_name(self, name: str) -> Optional[VmWrapper]:
        """Get a VM by name."""
        for vm in self._vms.values():
            if vm.name == name:
                return vm
        return None
    
    def start_vm(self, uuid: str) -> bool:
        """Start a VM."""
        vm = self._vms.get(uuid)
        if vm:
            return vm.start()
        return False
    
    def shutdown_vm(self, uuid: str) -> bool:
        """Gracefully shutdown a VM."""
        vm = self._vms.get(uuid)
        if vm:
            return vm.shutdown()
        return False
    
    def destroy_vm(self, uuid: str) -> bool:
        """Force stop a VM."""
        vm = self._vms.get(uuid)
        if vm:
            return vm.destroy()
        return False
    
    def pause_vm(self, uuid: str) -> bool:
        """Pause a VM."""
        vm = self._vms.get(uuid)
        if vm:
            return vm.pause()
        return False
    
    def resume_vm(self, uuid: str) -> bool:
        """Resume a VM."""
        vm = self._vms.get(uuid)
        if vm:
            return vm.resume()
        return False
    
    def delete_vm(self, uuid: str, delete_storage: bool = False) -> bool:
        """Delete a VM."""
        vm = self._vms.get(uuid)
        if vm:
            return vm.delete(delete_storage)
        return False
    
    def get_cpu_percent(self) -> float:
        """Get aggregated CPU usage percentage."""
        total = 0.0
        for vm in self._vms.values():
            total += vm.get_cpu_percent()
        return total
    
    def get_memory_used(self) -> int:
        """Get total memory used by active VMs."""
        total = 0
        for vm in self._vms.values():
            if vm.is_running:
                total += vm.memory
        return total
    
    def get_memory_total(self) -> int:
        """Get total host memory."""
        if not self._conn:
            return 0
        try:
            info = self._conn.getInfo()
            return info[1] * 1024 * 1024
        except Exception:
            return 0
    
    def get_disk_rate(self) -> float:
        """Get aggregated disk I/O rate."""
        total = 0.0
        for vm in self._vms.values():
            if vm.is_running:
                total += vm.get_disk_rate()
        return total
    
    def get_network_rate(self) -> float:
        """Get aggregated network I/O rate."""
        total = 0.0
        for vm in self._vms.values():
            if vm.is_running:
                total += vm.get_network_rate()
        return total
    
    def refresh(self) -> None:
        """Refresh VM list from libvirt."""
        if not self._conn:
            return
        
        try:
            current_uuids = {d.UUIDString() for d in self._conn.listAllDomains()}
            existing_uuids = set(self._vms.keys())
            
            removed_uuids = existing_uuids - current_uuids
            for uuid in removed_uuids:
                self.remove_vm(uuid)
            
            for domain in self._conn.listAllDomains():
                uuid = domain.UUIDString()
                if uuid in current_uuids - existing_uuids:
                    self._add_vm(domain)
                    
        except Exception as e:
            logger.error(f"Failed to refresh: {e}")
    
    def get_info(self) -> dict:
        """Get host info."""
        if not self._conn:
            return {}
        
        try:
            info = self._conn.getInfo()
            return {
                "memory": info[1] * 1024,
                "cpus": info[2],
                "nodes": info[4],
                "sockets": info[5],
                "cores": info[6],
                "threads": info[7],
            }
        except Exception:
            return {}
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.close()

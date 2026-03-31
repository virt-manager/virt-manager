"""
Configuration management for Qt frontend.
"""

import json
import os
import logging
from typing import Any, Optional

logger = logging.getLogger("virtmanagerqt.config")


class Config:
    """
    Application configuration singleton.
    """
    
    _instance: Optional["Config"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._config_dir = os.path.expanduser("~/.config/virt-manager-qt")
        self._config_file = os.path.join(self._config_dir, "config.json")
        
        os.makedirs(self._config_dir, exist_ok=True)
        
        self._defaults_cache = {}
        self._data = {}
        self._defaults()
        self._load()
    
    def _defaults(self):
        """Set default values for all settings."""
        self._defaults_cache = {
            "connections/uris": [],
            "connections/autoconnect": [],
            "stats/enable-cpu": True,
            "stats/enable-memory": True,
            "stats/enable-disk": True,
            "stats/enable-network": True,
            "stats/update-interval": 2,
            "stats/history-length": 60,
            "console/scaling": 0,
            "console/auto-redirect": False,
            "console/autoconnect": True,
            "console/grab-keys": "65507,65513",
            "ui/show-toolbar": True,
            "ui/system-tray": False,
            "ui/window-width": 1050,
            "ui/window-height": 700,
            "confirm/forcepoweroff": True,
            "confirm/poweroff": True,
            "confirm/pause": False,
            "confirm/removedev": True,
            "confirm/unapplied": True,
            "confirm/delstorage": True,
            "newvm/graphics-type": "system",
            "newvm/storage-format": "qcow2",
            "newvm/cpu-default": "host-passthrough",
            "newvm/firmware": "default",
        }
    
    def _load(self):
        """Load configuration from file."""
        if os.path.exists(self._config_file):
            try:
                with open(self._config_file, 'r') as f:
                    self._data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")
                self._data = {}
    
    def _save(self):
        """Save configuration to file."""
        try:
            with open(self._config_file, 'w') as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save config: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        if key in self._data:
            return self._data[key]
        if key in self._defaults_cache:
            return self._defaults_cache[key]
        return default
    
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value."""
        self._data[key] = value
        self._save()
    
    def contains(self, key: str) -> bool:
        """Check if a key exists."""
        return key in self._data or key in self._defaults_cache
    
    def get_connections(self) -> list:
        """Get list of saved connection URIs."""
        return self.get("connections/uris", [])
    
    def add_connection(self, uri: str) -> None:
        """Add a connection URI."""
        uris = self.get_connections()
        if uri not in uris:
            uris.append(uri)
            self.set("connections/uris", uris)
    
    def remove_connection(self, uri: str) -> None:
        """Remove a connection URI."""
        uris = self.get_connections()
        if uri in uris:
            uris.remove(uri)
            self.set("connections/uris", uris)
            autoconnect = self.get_autoconnect_uris()
            if uri in autoconnect:
                autoconnect.remove(uri)
                self.set("connections/autoconnect", autoconnect)
    
    def get_autoconnect_uris(self) -> list:
        """Get list of URIs for auto-connection."""
        return self.get("connections/autoconnect", [])
    
    def set_autoconnect(self, uri: str, enabled: bool) -> None:
        """Enable/disable auto-connect for a URI."""
        autoconnect = self.get_autoconnect_uris()
        if enabled and uri not in autoconnect:
            autoconnect.append(uri)
        elif not enabled and uri in autoconnect:
            autoconnect.remove(uri)
        self.set("connections/autoconnect", autoconnect)
    
    def is_autoconnect(self, uri: str) -> bool:
        """Check if URI has auto-connect enabled."""
        return uri in self.get_autoconnect_uris()
    
    def is_stats_enabled(self, stat_type: str) -> bool:
        """Check if a stats type is enabled."""
        return self.get(f"stats/enable-{stat_type}", True)
    
    def set_stats_enabled(self, stat_type: str, enabled: bool) -> None:
        """Enable/disable a stats type."""
        self.set(f"stats/enable-{stat_type}", enabled)
    
    def get_stats_interval(self) -> int:
        """Get polling interval in seconds."""
        return max(1, int(self.get("stats/update-interval", 2)))
    
    def set_stats_interval(self, seconds: int) -> None:
        """Set polling interval in seconds."""
        self.set("stats/update-interval", max(1, seconds))
    
    def get_stats_history_length(self) -> int:
        """Get number of stats samples to keep."""
        return int(self.get("stats/history-length", 60))
    
    def get_console_scaling(self) -> int:
        """Get console scaling mode."""
        return int(self.get("console/scaling", 0))
    
    def set_console_scaling(self, mode: int) -> None:
        """Set console scaling mode."""
        self.set("console/scaling", mode)
    
    def get_grab_keys(self) -> list:
        """Get console grab key combination."""
        keys_str = self.get("console/grab-keys", "65507,65513")
        try:
            return [int(k) for k in keys_str.split(",")]
        except ValueError:
            return [65507, 65513]
    
    def set_grab_keys(self, keys: list) -> None:
        """Set console grab key combination."""
        self.set("console/grab-keys", ",".join(str(k) for k in keys))
    
    def is_auto_usbredir(self) -> bool:
        """Check if USB redirection is automatic."""
        return bool(self.get("console/auto-redirect", False))
    
    def set_auto_usbredir(self, enabled: bool) -> None:
        """Set automatic USB redirection."""
        self.set("console/auto-redirect", enabled)
    
    def is_toolbar_visible(self) -> bool:
        """Check if toolbar is visible."""
        return bool(self.get("ui/show-toolbar", True))
    
    def set_toolbar_visible(self, visible: bool) -> None:
        """Set toolbar visibility."""
        self.set("ui/show-toolbar", visible)
    
    def is_system_tray_enabled(self) -> bool:
        """Check if system tray icon is enabled."""
        return bool(self.get("ui/system-tray", False))
    
    def set_system_tray_enabled(self, enabled: bool) -> None:
        """Set system tray icon enabled."""
        self.set("ui/system-tray", enabled)
    
    def get_window_size(self) -> tuple:
        """Get main window size."""
        w = int(self.get("ui/window-width", 1050))
        h = int(self.get("ui/window-height", 700))
        return w, h
    
    def set_window_size(self, width: int, height: int) -> None:
        """Set main window size."""
        self.set("ui/window-width", width)
        self.set("ui/window-height", height)
    
    def is_confirmation_required(self, action: str) -> bool:
        """Check if confirmation is required for action."""
        return bool(self.get(f"confirm/{action}", True))
    
    def set_confirmation_required(self, action: str, required: bool) -> None:
        """Set confirmation requirement for action."""
        self.set(f"confirm/{action}", required)
    
    def get_default_graphics_type(self) -> str:
        """Get default graphics type."""
        return str(self.get("newvm/graphics-type", "system"))
    
    def set_default_graphics_type(self, gtype: str) -> None:
        """Set default graphics type."""
        self.set("newvm/graphics-type", gtype.lower())
    
    def get_default_storage_format(self) -> str:
        """Get default storage format."""
        return str(self.get("newvm/storage-format", "qcow2"))
    
    def set_default_storage_format(self, fmt: str) -> None:
        """Set default storage format."""
        self.set("newvm/storage-format", fmt.lower())
    
    def sync(self) -> None:
        """Force sync to disk."""
        self._save()
    
    def reset(self) -> None:
        """Reset all settings to defaults."""
        self._data = {}
        self._save()


_config = None


def get_config() -> Config:
    """Get the Config singleton instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config

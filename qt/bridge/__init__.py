"""
Bridge layer components for Qt frontend.

Provides thin wrappers around libvirt to integrate with Qt's signal/slot mechanism.
"""

from .connwrapper import ConnectionWrapper
from .vmwrapper import VmWrapper
from .statspoller import StatsPoller
from .storage import (
    StoragePoolWrapper,
    StorageVolumeWrapper,
    NetworkWrapper,
    SnapshotWrapper,
)

__all__ = [
    "ConnectionWrapper",
    "VmWrapper",
    "StatsPoller",
    "StoragePoolWrapper",
    "StorageVolumeWrapper",
    "NetworkWrapper",
    "SnapshotWrapper",
]

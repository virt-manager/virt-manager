"""
Dialogs for Qt frontend.
"""

from .about import AboutDialog as vmmAbout
from .addhardware import vmmAddHardware
from .clone import CloneDialog as vmmClone, MigrateDialog as vmmMigrate
from .connection import ConnectionDialog as vmmConnectionDialog
from .createconn import vmmCreateConn
from .createvm import CreateVmDialog as vmmCreateVM
from .createnet import vmmCreateNetwork
from .createpool import vmmCreatePool
from .createvol import vmmCreateVolume
from .delete import vmmDeleteDialog, vmmDeleteStorage
from .preferences import PreferencesDialog as vmmPreferences
from .snapshot import SnapshotDialog as vmmSnapshot
from .storagebrowse import vmmStorageBrowser

__all__ = [
    'vmmAbout',
    'vmmAddHardware', 
    'vmmClone',
    'vmmMigrate',
    'vmmConnectionDialog',
    'vmmCreateConn',
    'vmmCreateVM',
    'vmmCreateNetwork',
    'vmmCreatePool',
    'vmmCreateVolume',
    'vmmDeleteDialog',
    'vmmDeleteStorage',
    'vmmPreferences',
    'vmmSnapshot',
    'vmmStorageBrowser',
]

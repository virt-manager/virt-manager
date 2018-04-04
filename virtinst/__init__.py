# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from virtcli import CLIConfig as _CLIConfig


# pylint: disable=wrong-import-position

def _setup_i18n():
    import gettext
    import locale

    try:
        locale.setlocale(locale.LC_ALL, '')
    except Exception:
        # Can happen if user passed a bogus LANG
        pass

    gettext.install("virt-manager", _CLIConfig.gettext_dir)
    gettext.bindtextdomain("virt-manager", _CLIConfig.gettext_dir)

_setup_i18n()
stable_defaults = _CLIConfig.stable_defaults

from virtinst import util
from virtinst import support
from virtinst.uri import URI
from virtinst.osdict import OSDB

from virtinst.domain import *  # pylint: disable=wildcard-import

from virtinst.capabilities import Capabilities
from virtinst.domcapabilities import DomainCapabilities
from virtinst.interface import Interface, InterfaceProtocol
from virtinst.network import Network
from virtinst.nodedev import NodeDevice
from virtinst.storage import StoragePool, StorageVolume

from virtinst.devices import *  # pylint: disable=wildcard-import

from virtinst.installer import (ContainerInstaller, ImportInstaller,
                                PXEInstaller, Installer)

from virtinst.distroinstaller import DistroInstaller

from virtinst.guest import Guest
from virtinst.cloner import Cloner
from virtinst.snapshot import DomainSnapshot

from virtinst.connection import VirtinstConnection

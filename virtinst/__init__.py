# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

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

from virtinst.osxml import OSXML
from virtinst.domainfeatures import DomainFeatures
from virtinst.domainnumatune import DomainNumatune
from virtinst.domainblkiotune import DomainBlkiotune
from virtinst.domainmemorytune import DomainMemorytune
from virtinst.domainmemorybacking import DomainMemorybacking
from virtinst.domainresource import DomainResource
from virtinst.clock import Clock
from virtinst.cpu import CPU, CPUFeature
from virtinst.cputune import CPUTune
from virtinst.seclabel import Seclabel
from virtinst.pm import PM
from virtinst.idmap import IdMap

from virtinst.capabilities import Capabilities
from virtinst.domcapabilities import DomainCapabilities
from virtinst.interface import Interface, InterfaceProtocol
from virtinst.network import Network
from virtinst.nodedev import NodeDevice
from virtinst.storage import StoragePool, StorageVolume

from virtinst.device import Device
from virtinst.deviceinterface import DeviceInterface
from virtinst.devicegraphics import DeviceGraphics
from virtinst.deviceaudio import DeviceSound
from virtinst.deviceinput import DeviceInput
from virtinst.devicedisk import DeviceDisk
from virtinst.devicehostdev import DeviceHostdev
from virtinst.devicechar import (DeviceChannel,
                                 DeviceConsole,
                                 DeviceParallel,
                                 DeviceSerial)
from virtinst.devicevideo import DeviceVideo
from virtinst.devicecontroller import DeviceController
from virtinst.devicewatchdog import DeviceWatchdog
from virtinst.devicefilesystem import DeviceFilesystem
from virtinst.devicesmartcard import DeviceSmartcard
from virtinst.deviceredirdev import DeviceRedirdev
from virtinst.devicememballoon import DeviceMemballoon
from virtinst.devicetpm import DeviceTpm
from virtinst.devicerng import DeviceRng
from virtinst.devicepanic import DevicePanic

from virtinst.installer import (ContainerInstaller, ImportInstaller,
                                PXEInstaller, Installer)

from virtinst.distroinstaller import DistroInstaller

from virtinst.guest import Guest
from virtinst.cloner import Cloner
from virtinst.snapshot import DomainSnapshot

from virtinst.connection import VirtinstConnection

#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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

from virtcli import cliconfig, cliutils
enable_rhel_defaults = not cliconfig.rhel_enable_unsupported_opts
cliutils.setup_i18n()


from virtinst import util
from virtinst import support

from virtinst.osxml import OSXML
from virtinst.domainfeatures import DomainFeatures
from virtinst.domainnumatune import DomainNumatune
from virtinst.clock import Clock
from virtinst.cpu import CPU, CPUFeature
from virtinst.seclabel import Seclabel

import virtinst.storage as Storage
import virtinst.nodedev as NodeDeviceParser
import virtinst.capabilities as CapabilitiesParser
from virtinst.interface import Interface, InterfaceProtocol

from virtinst.device import VirtualDevice
from virtinst.deviceinterface import VirtualNetworkInterface
from virtinst.devicegraphics import VirtualGraphics
from virtinst.deviceaudio import VirtualAudio
from virtinst.deviceinput import VirtualInputDevice
from virtinst.devicedisk import VirtualDisk
from virtinst.devicehostdev import VirtualHostDevice
from virtinst.devicechar import (VirtualChannelDevice,
                                 VirtualConsoleDevice,
                                 VirtualParallelDevice,
                                 VirtualSerialDevice)
from virtinst.devicevideo import VirtualVideoDevice
from virtinst.devicecontroller import VirtualController
from virtinst.devicewatchdog import VirtualWatchdog
from virtinst.devicefilesystem import VirtualFilesystem
from virtinst.devicesmartcard import VirtualSmartCardDevice
from virtinst.deviceredirdev import VirtualRedirDevice
from virtinst.devicememballoon import VirtualMemballoon
from virtinst.devicetpm import VirtualTPMDevice

from virtinst.installer import (ContainerInstaller, ImportInstaller,
                                LiveCDInstaller, PXEInstaller, Installer)

from virtinst.distroinstaller import DistroInstaller

from virtinst.guest import Guest
from virtinst.cloner import Cloner
from virtinst.snapshot import DomainSnapshot

from virtinst.connection import VirtualConnection

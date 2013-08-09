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
from virtinst.DomainFeatures import DomainFeatures
from virtinst.DomainNumatune import DomainNumatune
from virtinst.Clock import Clock
from virtinst.CPU import CPU, CPUFeature
from virtinst.Seclabel import Seclabel

from virtinst.VirtualDevice import VirtualDevice
from virtinst.VirtualNetworkInterface import VirtualNetworkInterface
from virtinst.VirtualGraphics import VirtualGraphics
from virtinst.VirtualAudio import VirtualAudio
from virtinst.VirtualInputDevice import VirtualInputDevice
from virtinst.VirtualDisk import VirtualDisk
from virtinst.VirtualHostDevice import VirtualHostDevice
from virtinst.VirtualCharDevice import (VirtualChannelDevice,
                                        VirtualConsoleDevice,
                                        VirtualParallelDevice,
                                        VirtualSerialDevice)
from virtinst.VirtualVideoDevice import VirtualVideoDevice
from virtinst.VirtualController import VirtualController
from virtinst.VirtualWatchdog import VirtualWatchdog
from virtinst.VirtualFilesystem import VirtualFilesystem
from virtinst.VirtualSmartCardDevice import VirtualSmartCardDevice
from virtinst.VirtualRedirDevice import VirtualRedirDevice
from virtinst.VirtualMemballoon import VirtualMemballoon
from virtinst.VirtualTPMDevice import VirtualTPMDevice

from virtinst.Installer import (ContainerInstaller, ImportInstaller,
                                LiveCDInstaller, PXEInstaller, Installer)

from virtinst.DistroInstaller import DistroInstaller

from virtinst.Guest import Guest
from virtinst.CloneManager import Cloner

from virtinst.connection import VirtualConnection

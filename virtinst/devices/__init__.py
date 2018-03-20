# Copyright (C) 2018 Red Hat, Inc.
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


from .char import DeviceChannel, DeviceConsole, DeviceParallel, DeviceSerial
from .controller import DeviceController
from .device import Device
from .disk import DeviceDisk
from .filesystem import DeviceFilesystem
from .graphics import DeviceGraphics
from .hostdev import DeviceHostdev
from .input import DeviceInput
from .interface import DeviceInterface
from .memballoon import DeviceMemballoon
from .memory import DeviceMemory
from .panic import DevicePanic
from .smartcard import DeviceSmartcard
from .sound import DeviceSound
from .redirdev import DeviceRedirdev
from .rng import DeviceRng
from .tpm import DeviceTpm
from .video import DeviceVideo
from .watchdog import DeviceWatchdog


__all__ = [l for l in locals() if l.startswith("Device")]

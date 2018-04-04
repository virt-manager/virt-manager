# Copyright (C) 2018 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.


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

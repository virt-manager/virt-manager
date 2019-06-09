#
# Copyright 2010, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceWatchdog(Device):
    XML_NAME = "watchdog"

    MODEL_I6300 = "i6300esb"
    MODEL_IB700 = "ib700"
    MODEL_DIAG288 = "diag288"
    MODELS = [MODEL_I6300, MODEL_IB700, MODEL_DIAG288]

    ACTION_SHUTDOWN = "shutdown"
    ACTION_RESET    = "reset"
    ACTION_POWEROFF = "poweroff"
    ACTION_PAUSE    = "pause"
    ACTION_NONE     = "none"
    ACTION_DUMP     = "dump"
    ACTIONS = [ACTION_RESET, ACTION_SHUTDOWN,
               ACTION_POWEROFF, ACTION_PAUSE,
               ACTION_DUMP, ACTION_NONE]

    _XML_PROP_ORDER = ["model", "action"]
    model = XMLProperty("./@model")
    action = XMLProperty("./@action")


    ##################
    # Default config #
    ##################

    def set_defaults(self, _guest):
        if not self.model:
            self.model = self.MODEL_I6300
        if not self.action:
            self.action = self.ACTION_RESET

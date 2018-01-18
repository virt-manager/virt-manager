#
# Copyright 2010, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

from .device import VirtualDevice
from .xmlbuilder import XMLProperty


class VirtualWatchdog(VirtualDevice):

    virtual_device_type = VirtualDevice.VIRTUAL_DEV_WATCHDOG

    MODEL_I6300 = "i6300esb"
    MODEL_IB700 = "ib700"
    MODEL_DIAG288 = "diag288"
    MODEL_DEFAULT = "default"
    MODELS = [MODEL_I6300, MODEL_IB700, MODEL_DIAG288]

    ACTION_SHUTDOWN = "shutdown"
    ACTION_RESET    = "reset"
    ACTION_POWEROFF = "poweroff"
    ACTION_PAUSE    = "pause"
    ACTION_NONE     = "none"
    ACTION_DUMP     = "dump"
    ACTION_DEFAULT  = "default"
    ACTIONS = [ACTION_RESET, ACTION_SHUTDOWN,
               ACTION_POWEROFF, ACTION_PAUSE,
               ACTION_DUMP, ACTION_NONE]

    @staticmethod
    def get_action_desc(action):
        if action == VirtualWatchdog.ACTION_RESET:
            return _("Forcefully reset the guest")
        if action == VirtualWatchdog.ACTION_SHUTDOWN:
            return _("Gracefully shutdown the guest")
        if action == VirtualWatchdog.ACTION_POWEROFF:
            return _("Forcefully power off the guest")
        if action == VirtualWatchdog.ACTION_PAUSE:
            return _("Pause the guest")
        if action == VirtualWatchdog.ACTION_NONE:
            return _("No action")
        if action == VirtualWatchdog.ACTION_DUMP:
            return _("Dump guest memory core")
        return action

    _XML_PROP_ORDER = ["model", "action"]
    model = XMLProperty("./@model",
                        default_name=MODEL_DEFAULT,
                        default_cb=lambda s: s.MODEL_I6300)
    action = XMLProperty("./@action",
                         default_name=ACTION_DEFAULT,
                         default_cb=lambda s: s.ACTION_RESET)


VirtualWatchdog.register_type()

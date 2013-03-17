#
# Copyright 2010  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

import VirtualDevice
from virtinst import _gettext as _
from XMLBuilderDomain import _xml_property

class VirtualWatchdog(VirtualDevice.VirtualDevice):

    _virtual_device_type = VirtualDevice.VirtualDevice.VIRTUAL_DEV_WATCHDOG

    MODEL_DEFAULT = "default"
    MODELS = [ "i6300esb", "ib700", MODEL_DEFAULT ]

    ACTION_DEFAULT  = "default"
    ACTION_SHUTDOWN = "shutdown"
    ACTION_RESET    = "reset"
    ACTION_POWEROFF = "poweroff"
    ACTION_PAUSE    = "pause"
    ACTION_NONE     = "none"
    ACTIONS = [ACTION_RESET, ACTION_SHUTDOWN,
               ACTION_POWEROFF, ACTION_PAUSE,
               ACTION_NONE, ACTION_DEFAULT]

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
        if action == VirtualWatchdog.ACTION_DEFAULT:
            return _("Hypervisor default")
        else:
            return action

    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None):
        VirtualDevice.VirtualDevice.__init__(self, conn, parsexml,
                                             parsexmlnode, caps)

        self._model = None
        self._action = None

        if self._is_parse():
            return

        self.model = self.MODEL_DEFAULT
        self.action = self.ACTION_DEFAULT

    def get_model(self):
        return self._model
    def set_model(self, new_model):
        if type(new_model) != str:
            raise ValueError(_("'model' must be a string, "
                                " was '%s'." % type(new_model)))
        if not self.MODELS.count(new_model):
            raise ValueError(_("Unsupported watchdog model '%s'" % new_model))
        self._model = new_model
    model = _xml_property(get_model, set_model,
                          xpath="./@model")

    def get_action(self):
        return self._action
    def set_action(self, val):
        if val not in self.ACTIONS:
            raise ValueError("Unknown watchdog action '%s'." % val)
        self._action = val
    action = _xml_property(get_action, set_action,
                           xpath="./@action")

    def _get_xml_config(self):
        model = self.model
        if model == self.MODEL_DEFAULT:
            model = "i6300esb"

        action = self.action
        if action == self.ACTION_DEFAULT:
            action = self.ACTION_RESET

        xml = "    <watchdog model='%s'" % model
        if action:
            xml += " action='%s'" % action
        xml += "/>"

        return xml

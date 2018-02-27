#
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
#

import logging
import re

import libvirt

class _LibvirtEnumMap(object):
    """
    Helper for mapping libvirt event int values to their API names
    """
    # Some values we define to distinguish between API objects
    (DOMAIN_EVENT,
     NETWORK_EVENT,
     STORAGE_EVENT,
     NODEDEV_EVENT) = range(1, 5)

    # Regex map for naming all event types depending on the API object
    _EVENT_PREFIX = {
        DOMAIN_EVENT: "VIR_DOMAIN_EVENT_ID_",
        NETWORK_EVENT: "VIR_NETWORK_EVENT_ID_",
        STORAGE_EVENT: "VIR_STORAGE_POOL_EVENT_ID_",
        NODEDEV_EVENT: "VIR_NODE_DEVICE_EVENT_ID_",
    }

    # Regex map for 'state' values returned from lifecycle and other events
    _DETAIL1_PREFIX = {
        "VIR_DOMAIN_EVENT_ID_LIFECYCLE": "VIR_DOMAIN_EVENT_[^_]+$",
        "VIR_NETWORK_EVENT_ID_LIFECYCLE": "VIR_NETWORK_EVENT_[^_]+$",
        "VIR_STORAGE_POOL_EVENT_ID_LIFECYCLE": "VIR_STORAGE_POOL_EVENT_[^_]+$",
        "VIR_NODE_DEVICE_EVENT_ID_LIFECYCLE": "VIR_NODE_DEVICE_EVENT_[^_]+$",
    }

    # Regex map for 'reason' values returned from lifecycle and other events
    _DETAIL2_PREFIX = {
        "VIR_DOMAIN_EVENT_DEFINED": "VIR_DOMAIN_EVENT_DEFINED_",
        "VIR_DOMAIN_EVENT_UNDEFINED": "VIR_DOMAIN_EVENT_UNDEFINED_",
        "VIR_DOMAIN_EVENT_STARTED": "VIR_DOMAIN_EVENT_STARTED_",
        "VIR_DOMAIN_EVENT_SUSPENDED": "VIR_DOMAIN_EVENT_SUSPENDED_",
        "VIR_DOMAIN_EVENT_RESUMED": "VIR_DOMAIN_EVENT_RESUMED_",
        "VIR_DOMAIN_EVENT_STOPPED": "VIR_DOMAIN_EVENT_STOPPED_",
        "VIR_DOMAIN_EVENT_SHUTDOWN": "VIR_DOMAIN_EVENT_SHUTDOWN_",
        "VIR_DOMAIN_EVENT_PMSUSPENDED": "VIR_DOMAIN_EVENT_PMSUSPENDED_",
        "VIR_DOMAIN_EVENT_CRASHED": "VIR_DOMAIN_EVENT_CRASHED_",
    }

    def __init__(self):
        self._mapping = {}

    def _make_map(self, regex):
        # Run the passed regex over dir(libvirt) output
        ret = {}
        for key in [a for a in dir(libvirt) if re.match(regex, a)]:
            val = getattr(libvirt, key)
            if type(val) is not int:
                logging.debug("libvirt regex=%s key=%s val=%s "
                    "isn't an integer", regex, key, val)
                continue
            if val in ret:
                logging.debug("libvirt regex=%s key=%s val=%s is already "
                    "in dict as key=%s", regex, key, val, regex[val])
                continue
            ret[val] = key
        return ret

    def _get_map(self, key, regex):
        if regex is None:
            return {}
        if key not in self._mapping:
            self._mapping[key] = self._make_map(regex)
        return self._mapping[key]

    def _make_strs(self, api, event, detail1, detail2):
        eventstr = str(event)
        detail1str = str(detail1)
        detail2str = str(detail2)
        eventmap = self._get_map(api, self._EVENT_PREFIX[api])

        if event in eventmap:
            eventstr = eventmap[event]
            detail1map = self._get_map(eventstr,
                    self._DETAIL1_PREFIX.get(eventstr))
            if detail1 in detail1map:
                detail1str = detail1map[detail1]
                detail2map = self._get_map(detail1str,
                        self._DETAIL2_PREFIX.get(detail1str))
                if detail2 in detail2map:
                    detail2str = detail2map[detail2]

        return eventstr, detail1str, detail2str

    def _state_str(self, api, detail1, detail2):
        ignore, d1str, d2str = self._make_strs(api, 0,
                detail1, detail2)
        return "state=%s reason=%s" % (d1str, d2str)

    def domain_lifecycle_str(self, detail1, detail2):
        return self._state_str(self.DOMAIN_EVENT, detail1, detail2)
    def network_lifecycle_str(self, detail1, detail2):
        return self._state_str(self.NETWORK_EVENT, detail1, detail2)
    def storage_lifecycle_str(self, detail1, detail2):
        return self._state_str(self.STORAGE_EVENT, detail1, detail2)
    def nodedev_lifecycle_str(self, detail1, detail2):
        return self._state_str(self.NODEDEV_EVENT, detail1, detail2)


LibvirtEnumMap = _LibvirtEnumMap()

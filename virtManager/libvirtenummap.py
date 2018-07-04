# Copyright (C) 2018 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import re

import libvirt

if not hasattr(libvirt, "VIR_DOMAIN_PMSUSPENDED"):
    setattr(libvirt, "VIR_DOMAIN_PMSUSPENDED", 7)


class _LibvirtEnumMap(object):
    """
    Helper for mapping libvirt event int values to their API names
    """
    # Some values we define to distinguish between API objects
    (DOMAIN_EVENT,
     DOMAIN_AGENT_EVENT,
     NETWORK_EVENT,
     STORAGE_EVENT,
     NODEDEV_EVENT) = range(1, 6)

    # Regex map for naming all event types depending on the API object
    _EVENT_PREFIX = {
        DOMAIN_EVENT: "VIR_DOMAIN_EVENT_ID_",
        DOMAIN_AGENT_EVENT: "VIR_DOMAIN_EVENT_ID_AGENT_",
        NETWORK_EVENT: "VIR_NETWORK_EVENT_ID_",
        STORAGE_EVENT: "VIR_STORAGE_POOL_EVENT_ID_",
        NODEDEV_EVENT: "VIR_NODE_DEVICE_EVENT_ID_",
    }

    # Regex map for 'state' values returned from lifecycle and other events
    _DETAIL1_PREFIX = {
        "VIR_DOMAIN_EVENT_ID_LIFECYCLE": "VIR_DOMAIN_EVENT_[^_]+$",
        "VIR_DOMAIN_EVENT_ID_AGENT_LIFECYCLE": _("VIR_CONNECT_DOMAIN_EVENT_AGENT"
                                                 "_LIFECYCLE_STATE_[^_]+$"),
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

    VM_STATUS_ICONS = {
        libvirt.VIR_DOMAIN_BLOCKED: "state_running",
        libvirt.VIR_DOMAIN_CRASHED: "state_shutoff",
        libvirt.VIR_DOMAIN_PAUSED: "state_paused",
        libvirt.VIR_DOMAIN_RUNNING: "state_running",
        libvirt.VIR_DOMAIN_SHUTDOWN: "state_shutoff",
        libvirt.VIR_DOMAIN_SHUTOFF: "state_shutoff",
        libvirt.VIR_DOMAIN_NOSTATE: "state_running",
        libvirt.VIR_DOMAIN_PMSUSPENDED: "state_paused",
    }

    @staticmethod
    def pretty_run_status(status, has_managed_save):
        if status == libvirt.VIR_DOMAIN_RUNNING:
            return _("Running")
        elif status == libvirt.VIR_DOMAIN_PAUSED:
            return _("Paused")
        elif status == libvirt.VIR_DOMAIN_SHUTDOWN:
            return _("Shutting Down")
        elif status == libvirt.VIR_DOMAIN_SHUTOFF:
            if has_managed_save:
                return _("Saved")
            else:
                return _("Shutoff")
        elif status == libvirt.VIR_DOMAIN_CRASHED:
            return _("Crashed")
        elif status == libvirt.VIR_DOMAIN_PMSUSPENDED:
            return _("Suspended")

        logging.debug("Unknown status %s, returning 'Unknown'", status)
        return _("Unknown")

    @staticmethod
    def pretty_status_reason(status, reason):
        def key(x, y):
            return getattr(libvirt, "VIR_DOMAIN_" + x, y)
        reasons = {
            libvirt.VIR_DOMAIN_RUNNING: {
                key("RUNNING_BOOTED", 1):             _("Booted"),
                key("RUNNING_MIGRATED", 2):           _("Migrated"),
                key("RUNNING_RESTORED", 3):           _("Restored"),
                key("RUNNING_FROM_SNAPSHOT", 4):      _("From snapshot"),
                key("RUNNING_UNPAUSED", 5):           _("Unpaused"),
                key("RUNNING_MIGRATION_CANCELED", 6): _("Migration canceled"),
                key("RUNNING_SAVE_CANCELED", 7):      _("Save canceled"),
                key("RUNNING_WAKEUP", 8):             _("Event wakeup"),
                key("RUNNING_CRASHED", 9):            _("Crashed"),
            },
            libvirt.VIR_DOMAIN_PAUSED: {
                key("PAUSED_USER", 1):                _("User"),
                key("PAUSED_MIGRATION", 2):           _("Migrating"),
                key("PAUSED_SAVE", 3):                _("Saving"),
                key("PAUSED_DUMP", 4):                _("Dumping"),
                key("PAUSED_IOERROR", 5):             _("I/O error"),
                key("PAUSED_WATCHDOG", 6):            _("Watchdog"),
                key("PAUSED_FROM_SNAPSHOT", 7):       _("From snapshot"),
                key("PAUSED_SHUTTING_DOWN", 8):       _("Shutting down"),
                key("PAUSED_SNAPSHOT", 9):            _("Creating snapshot"),
                key("PAUSED_CRASHED", 10):            _("Crashed"),
            },
            libvirt.VIR_DOMAIN_SHUTDOWN: {
                key("SHUTDOWN_USER", 1):              _("User"),
            },
            libvirt.VIR_DOMAIN_SHUTOFF: {
                key("SHUTOFF_SHUTDOWN", 1):           _("Shut Down"),
                key("SHUTOFF_DESTROYED", 2):          _("Destroyed"),
                key("SHUTOFF_CRASHED", 3):            _("Crashed"),
                key("SHUTOFF_MIGRATED", 4):           _("Migrated"),
                key("SHUTOFF_SAVED", 5):              _("Saved"),
                key("SHUTOFF_FAILED", 6):             _("Failed"),
                key("SHUTOFF_FROM_SNAPSHOT", 7):      _("From snapshot"),
            },
            libvirt.VIR_DOMAIN_CRASHED: {
                key("CRASHED_PANICKED", 1):           _("Panicked"),
            }
        }
        return reasons.get(status) and reasons[status].get(reason)

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

        if eventmap:
            if event not in eventmap:
                event = next(iter(eventmap))
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
    def domain_agent_lifecycle_str(self, detail1, detail2):
        return self._state_str(self.DOMAIN_AGENT_EVENT, detail1, detail2)


LibvirtEnumMap = _LibvirtEnumMap()

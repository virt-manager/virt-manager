#
# Copyright (C) 2010, 2013 Red Hat, Inc.
# Copyright (C) 2010 Cole Robinson <crobinso@redhat.com>
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

from gi.repository import GObject

import logging

from .baseclass import vmmGObject


class vmmLibvirtObject(vmmGObject):
    __gsignals__ = {
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, []),
        "initialized": (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    _STATUS_ACTIVE = 1
    _STATUS_INACTIVE = 2

    def __init__(self, conn, backend, key, parseclass):
        vmmGObject.__init__(self)
        self._conn = conn
        self._backend = backend
        self._key = key
        self._parseclass = parseclass

        self._initialized = False
        self.__status = self._STATUS_ACTIVE
        self._support_isactive = None

        self._xmlobj = None
        self._xmlobj_to_define = None
        self._is_xml_valid = False

        # These should be set by the child classes if necessary
        self._inactive_xml_flags = 0
        self._active_xml_flags = 0

        # Cache object name. We may need to do this even
        # before init_libvirt_state since it might be needed ahead of time.
        self._name = None
        self.get_name()

    @staticmethod
    def log_redefine_xml_diff(obj, origxml, newxml):
        objname = "<%s name=%s>" % (obj.__class__.__name__, obj.get_name())
        if origxml == newxml:
            logging.debug("Redefine requested for %s, but XML didn't change!",
                          objname)
            return

        import difflib
        diff = "".join(difflib.unified_diff(origxml.splitlines(1),
                                            newxml.splitlines(1),
                                            fromfile="Original XML",
                                            tofile="New XML"))
        logging.debug("Redefining %s with XML diff:\n%s", objname, diff)

    @staticmethod
    def lifecycle_action(fn):
        """
        Decorator for object lifecycle actions like start, stop, delete.
        Will make sure any necessary state is updated accordingly.
        """
        def newfn(self, *args, **kwargs):
            ret = fn(self, *args, **kwargs)

            # If events are supported, this is a no-op, but the event loop
            # will trigger force_status_update, which will refresh_xml as well.
            #
            # If events aren't supported, the priority tick will call
            # self.tick(), which will call force_status_update
            poll_param = self._conn_tick_poll_param()  # pylint: disable=protected-access
            tick_kwargs = {poll_param: True}
            self.conn.schedule_priority_tick(**tick_kwargs)

            return ret
        return newfn

    def _cleanup(self):
        pass

    def _get_conn(self):
        return self._conn
    conn = property(_get_conn)

    def get_backend(self):
        return self._backend
    def get_connkey(self):
        return self._key

    def change_name_backend(self, newbackend):
        # Used for changing the backing object after a rename
        self._backend = newbackend

    def define_name(self, newname):
        oldname = self.get_xmlobj().name
        self._invalidate_xml()
        xmlobj = self._get_xmlobj_to_define()
        if xmlobj.name == newname:
            return

        logging.debug("Changing %s name from %s to %s",
                      self.__class__, oldname, newname)
        origxml = xmlobj.get_xml_config()
        xmlobj.name = newname
        newxml = xmlobj.get_xml_config()

        try:
            self._key = newname
            self.conn.rename_object(self, origxml, newxml, oldname, newname)
        except:
            self._key = oldname
            raise
        finally:
            self._invalidate_xml()

        self.emit("state-changed")


    #############################################################
    # Functions that should probably be overridden in sub class #
    #############################################################

    def _XMLDesc(self, flags):
        raise NotImplementedError()
    def class_name(self):
        raise NotImplementedError()
    def _conn_tick_poll_param(self):
        # The parameter name for conn.tick() object polling. So
        # for vmmDomain == "pollvm"
        raise NotImplementedError()

    def reports_stats(self):
        return False
    def _using_events(self):
        return False
    def _check_supports_isactive(self):
        return False
    def _get_backend_status(self):
        raise NotImplementedError()

    def _define(self, xml):
        ignore = xml
        return

    def delete(self, force=True):
        ignore = force

    def get_name(self):
        if self._name is None:
            self._name = self._backend_get_name()
        return self._name

    def _backend_get_name(self):
        return self._backend.name()

    def tick(self, stats_update=True):
        raise NotImplementedError()

    def _init_libvirt_state(self):
        raise NotImplementedError()

    def init_libvirt_state(self):
        """
        Function called by vmmConnection to populate initial state when
        a new object appears.
        """
        if self._initialized:
            return

        try:
            self._init_libvirt_state()
        finally:
            self._initialized = True
            self.idle_emit("initialized")


    ###################
    # Status handling #
    ###################

    def _get_status(self):
        return self.__status

    def is_active(self):
        # vmmDomain overwrites this since it has more fine grained statuses
        return self._get_status() == self._STATUS_ACTIVE

    def run_status(self):
        if self.is_active():
            return "Active"
        return "Inactive"

    def refresh_status_from_event_loop(self):
        """
        Updates VM status, because we received a status event from libvirt's
        event implementations. That's the only time this should be used.
        """
        return self._refresh_status(skip_if_have_events=False)

    def _refresh_status(self, skip_if_have_events=True, newstatus=None):
        """
        Grab the object status/active state from libvirt, and if the
        status has changed, update the XML cache. Typically called from
        object tick functions for manually updating the object state.

        :param skip_if_have_events: If this object is served by libvirt
            events, we want this to be a no-op for most usages, like
            from tick(), so don't do anything.
        :param newstatus: Used by vmmDomain as a small optimization to
            avoid polling info() twice
        """
        if (self._using_events() and
            skip_if_have_events and
            self._initialized):
            return

        try:
            status = newstatus
            if newstatus is None:
                status = self._get_backend_status()
            if status == self.__status:
                return
            self.__status = status

            # This will send state-change for us
            self.refresh_xml(forcesignal=True)
        except Exception, e:
            # If we hit an exception here, it's often that the object
            # disappeared, so request the poll loop to be updated
            logging.debug("Error polling status for %s: %s", self, e)
            poll_param = self._conn_tick_poll_param()
            if poll_param:
                kwargs = {"force": True, poll_param: True}
                logging.debug("Scheduling priority tick with: %s", kwargs)
                self.conn.schedule_priority_tick(**kwargs)

    def _backend_get_active(self):
        if self._support_isactive is None:
            self._support_isactive = self._check_supports_isactive()

        if not self._support_isactive:
            return self._STATUS_ACTIVE
        return (bool(self._backend.isActive()) and
                self._STATUS_ACTIVE or
                self._STATUS_INACTIVE)


    ##################
    # Public XML API #
    ##################

    def refresh_xml(self, forcesignal=False):
        """
        Force an xml update. Signal 'state-changed' if domain xml has
        changed since last refresh

        :param forcesignal: Send state-changed unconditionally
        """
        origxml = None
        if self._xmlobj:
            origxml = self._xmlobj.get_xml_config()

        self._invalidate_xml()
        active_xml = self._XMLDesc(self._active_xml_flags)
        self._xmlobj = self._parseclass(self.conn.get_backend(),
            parsexml=active_xml)
        self._is_xml_valid = True

        if forcesignal or origxml != active_xml:
            self.idle_emit("state-changed")

    def get_xmlobj(self, inactive=False, refresh_if_nec=True):
        """
        Get object xml, return it wrapped in a virtinst object.
        If cached xml is invalid, update.

        :param inactive: Return persistent XML, not the running config.
            No effect if domain is not running. Use this flag
            if the XML will be used for redefining a guest
        :param refresh_if_nec: Check if XML is out of date, and if so,
            refresh it (default behavior). Skipping a refresh is
            useful to prevent updating xml in the tick loop when
            it's not that important (disk/net stats)
        """
        if inactive:
            # If inactive XML requested, always return a fresh object even if
            # the current object is inactive XML (like when the domain is
            # stopped). Callers that request inactive are basically expecting
            # a new copy.
            inactive_xml = self._XMLDesc(self._inactive_xml_flags)
            return self._parseclass(self.conn.get_backend(),
                parsexml=inactive_xml)

        if (self._xmlobj is None or
            (refresh_if_nec and not self._is_xml_valid)):
            self.refresh_xml()

        return self._xmlobj

    @property
    def xmlobj(self):
        return self.get_xmlobj()

    def redefine_cached(self):
        """
        Redefine the _xmlobj_to_define cache.

        Used by places like details.py and addhardware.py to queue a bunch
        of XML changes via vmmDomain functions, but only call 'define'
        once.
        """
        if not self._xmlobj_to_define:
            logging.debug("No cached XML to define, skipping.")
            return

        try:
            self._redefine_object(self._xmlobj_to_define)
        except:
            # If something fails here, we need to drop the cached object,
            # since some edits like addhardware.py may not be idempotent
            self._invalidate_xml()
            raise


    #########################
    # Internal XML routines #
    #########################

    def _invalidate_xml(self):
        """
        Mark cached XML as invalid. Subclasses may extend this
        to invalidate any specific caches of their own
        """
        self._is_xml_valid = False
        self._xmlobj_to_define = None
        self._name = None

    def _make_xmlobj_to_define(self):
        """
        Build an xmlobj that should be used for defining new XML.

        Most subclasses shouldn't touch this, but vmmDomainVirtinst needs to.
        """
        return self.get_xmlobj(inactive=True)

    def _get_xmlobj_to_define(self):
        """
        Return the XML object that should be used to queue up new XML changes.
        This is what is flushed with redefine_cached.

        Most subclasses shouldn't touch this, but vmmDomainVirtinst needs to.
        """
        if not self._xmlobj_to_define:
            self._xmlobj_to_define = self._make_xmlobj_to_define()
        return self._xmlobj_to_define

    def _redefine_object(self, xmlobj, origxml=None):
        """
        Redefine the passed object. This is called by redefine_cached and
        shouldn't be called directly.

        Most subclasses shouldn't touch this, but vmmDomainVirtinst needs to.

        :param origxml: vmmDomainVirtinst uses that field to make sure
            we detect the actual XML change and log it correctly.
        """
        if not origxml:
            origxml = self._make_xmlobj_to_define().get_xml_config()

        newxml = xmlobj.get_xml_config()
        self.log_redefine_xml_diff(self, origxml, newxml)

        if origxml != newxml:
            self._define(newxml)

        if not self._using_events():
            # Make sure we have latest XML
            self.refresh_xml(forcesignal=True)

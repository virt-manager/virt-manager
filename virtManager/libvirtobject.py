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
        "config-changed": (GObject.SignalFlags.RUN_FIRST, None, []),
        "started": (GObject.SignalFlags.RUN_FIRST, None, []),
        "stopped": (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    def __init__(self, conn, backend, key, parseclass):
        vmmGObject.__init__(self)
        self._conn = conn
        self._backend = backend
        self._key = key
        self._parseclass = parseclass

        self._xml = None
        self._is_xml_valid = False

        self._xmlobj = None
        self._xmlobj_to_define = None

        # These should be set by the child classes if necessary
        self._inactive_xml_flags = 0
        self._active_xml_flags = 0

        # Cache object name
        self._name = None
        self.get_name()

        self.connect("config-changed", self._reparse_xml)

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

        self.emit("config-changed")


    #############################################################
    # Functions that should probably be overridden in sub class #
    #############################################################

    def _XMLDesc(self, flags):
        raise NotImplementedError()
    def _using_events(self):
        return False

    def _define(self, xml):
        ignore = xml
        return

    def delete(self, force=True):
        ignore = force

    def force_update_status(self, from_event=False, log=True):
        ignore = from_event
        ignore = log

    def get_name(self):
        if self._name is None:
            self._name = self._backend_get_name()
        return self._name

    def _backend_get_name(self):
        return self._backend.name()


    ##################
    # Public XML API #
    ##################

    def get_xml(self, *args, **kwargs):
        """
        See _get_raw_xml for parameter docs
        """
        return self.get_xmlobj(*args, **kwargs).get_xml_config()

    def get_xmlobj(self, inactive=False, refresh_if_nec=True):
        xml = self._get_raw_xml(inactive, refresh_if_nec)

        if inactive:
            # If inactive XML requested, always return a fresh object even
            # the current object is inactive XML (like when the domain is
            # stopped). Callers that request inactive are basically expecting
            # a new copy.
            return self._build_xmlobj(xml)

        if not self._xmlobj:
            self._reparse_xml()
        return self._xmlobj

    def refresh_xml(self, forcesignal=False):
        # Force an xml update. Signal 'config-changed' if domain xml has
        # changed since last refresh

        origxml = self._xml
        self._invalidate_xml()
        self._xml = self._XMLDesc(self._active_xml_flags)
        self._is_xml_valid = True

        if origxml != self._xml or forcesignal:
            self.idle_emit("config-changed")


    ######################################
    # Internal XML cache/update routines #
    ######################################

    def _invalidate_xml(self):
        # Mark cached xml as invalid
        self._is_xml_valid = False
        self._xmlobj_to_define = None
        self._name = None


    ##########################
    # Internal API functions #
    ##########################

    def _get_raw_xml(self, inactive=False, refresh_if_nec=True):
        """
        Get object xml. If cached xml is invalid, update.

        @param inactive: Return persistent XML, not the running config.
                    No effect if domain is not running. Use this flag
                    if the XML will be used for redefining a guest
        @param refresh_if_nec: Check if XML is out of date, and if so,
                    refresh it (default behavior). Skipping a refresh is
                    useful to prevent updating xml in the tick loop when
                    it's not that important (disk/net stats)
        """
        if inactive:
            return self._XMLDesc(self._inactive_xml_flags)

        if self._xml is None:
            self.refresh_xml()
        elif refresh_if_nec and not self._is_xml_valid:
            self.refresh_xml()

        return self._xml

    def _xml_to_redefine(self):
        return self.get_xml(inactive=True)

    def redefine_cached(self):
        if not self._xmlobj_to_define:
            logging.debug("No cached XML to define, skipping.")
            return

        obj = self._get_xmlobj_to_define()
        xml = obj.get_xml_config()
        self._redefine_xml(xml)

    def _reparse_xml(self, ignore=None):
        self._xmlobj = self._build_xmlobj(self._get_raw_xml())

    def _build_xmlobj(self, xml):
        return self._parseclass(self.conn.get_backend(), parsexml=xml)

    def _get_xmlobj_to_define(self):
        if not self._xmlobj_to_define:
            self._xmlobj_to_define = self.get_xmlobj(inactive=True)
        return self._xmlobj_to_define

    def _redefine_helper(self, origxml, newxml):
        self.log_redefine_xml_diff(self, origxml, newxml)

        if origxml != newxml:
            self._define(newxml)

        if not self._using_events():
            # Make sure we have latest XML
            self.refresh_xml(forcesignal=True)

    def _redefine_xml(self, newxml):
        origxml = self._xml_to_redefine()
        return self._redefine_helper(origxml, newxml)

    def _redefine(self, cb):
        guest = self._get_xmlobj_to_define()
        return cb(guest)

#
# Copyright (C) 2010 Red Hat, Inc.
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

# pylint: disable=E0611
from gi.repository import GObject
# pylint: enable=E0611

import difflib
import logging

import libxml2

from virtManager.baseclass import vmmGObject


def _sanitize_xml(xml):
    xml = libxml2.parseDoc(xml).serialize()
    # Strip starting <?...> line
    if xml.startswith("<?"):
        ignore, xml = xml.split("\n", 1)
    if not xml.endswith("\n") and xml.count("\n"):
        xml += "\n"
    return xml


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

        self.connect("config-changed", self._reparse_xml)

    def _cleanup(self):
        pass

    def _get_conn(self):
        return self._conn
    conn = property(_get_conn)

    def get_backend(self):
        return self._backend
    def get_key(self):
        return self._key


    #############################################################
    # Functions that should probably be overridden in sub class #
    #############################################################

    def get_name(self):
        raise NotImplementedError()
    def _XMLDesc(self, flags):
        raise NotImplementedError()

    def _define(self, xml):
        ignore = xml
        return


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
        return _sanitize_xml(self.get_xml(inactive=True))

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
        origxml = _sanitize_xml(origxml)
        newxml  = _sanitize_xml(newxml)
        if origxml != newxml:
            diff = "".join(difflib.unified_diff(origxml.splitlines(1),
                                                newxml.splitlines(1),
                                                fromfile="Original XML",
                                                tofile="New XML"))
            logging.debug("Redefining '%s' with XML diff:\n%s",
                          self.get_name(), diff)

            self._define(newxml)
        else:
            logging.debug("Redefine requested, but XML didn't change!")

        # Make sure we have latest XML
        self.refresh_xml(forcesignal=True)
        return

    def _redefine_xml(self, newxml):
        origxml = self._xml_to_redefine()
        return self._redefine_helper(origxml, newxml)

    def _redefine(self, cb):
        guest = self._get_xmlobj_to_define()
        return cb(guest)

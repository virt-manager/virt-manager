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

import gobject

import difflib
import logging

from virtManager import util

class vmmLibvirtObject(gobject.GObject):
    __gsignals__ = {
        "config-changed": (gobject.SIGNAL_RUN_FIRST,
                           gobject.TYPE_NONE,
                           []),
    }

    def __init__(self, config, connection):
        self.__gobject_init__()
        self.config = config
        self.connection = connection

        self._xml = None
        self._is_xml_valid = False

        # These should be set by the child classes if necessary
        self._inactive_xml_flags = 0
        self._active_xml_flags = 0

    def get_connection(self):
        return self.connection

    #############################################################
    # Functions that should probably be overridden in sub class #
    #############################################################

    def _XMLDesc(self, flags):
        ignore = flags
        return

    def _define(self, xml):
        ignore = xml
        return

    def tick(self, now):
        ignore = now

    ##################
    # Public XML API #
    ##################

    def get_xml(self, inactive=False, refresh_if_necc=True):
        """
        Get domain xml. If cached xml is invalid, update.

        @param inactive: Return persistent XML, not the running config.
                    No effect if domain is not running. Use this flag
                    if the XML will be used for redefining a guest
        @param refresh_if_necc: Check if XML is out of date, and if so,
                    refresh it (default behavior). Skipping a refresh is
                    useful to prevent updating xml in the tick loop when
                    it's not that important (disk/net stats)
        """
        if inactive:
            return self._XMLDesc(self._inactive_xml_flags)

        if self._xml is None:
            self.refresh_xml()
        elif refresh_if_necc and not self._is_xml_valid:
            self.refresh_xml()

        return self._xml

    def refresh_xml(self):
        # Force an xml update. Signal 'config-changed' if domain xml has
        # changed since last refresh

        origxml = self._xml
        self._xml = self._XMLDesc(self._active_xml_flags)
        self._is_xml_valid = True

        if origxml != self._xml:
            util.safe_idle_add(util.idle_emit, self, "config-changed")

    ######################################
    # Internal XML cache/update routines #
    ######################################

    def _invalidate_xml(self):
        # Mark cached xml as invalid
        self._is_xml_valid = False

    ##########################
    # Internal API functions #
    ##########################

    def _redefine(self, xml_func, *args):
        """
        Helper function for altering a redefining VM xml

        @param xml_func: Function to alter the running XML. Takes the
                         original XML as its first argument.
        @param args: Extra arguments to pass to xml_func
        """
        origxml = self.get_xml(inactive=True)
        # Sanitize origxml to be similar to what we will get back
        origxml = util.xml_parse_wrapper(origxml, lambda d, c: d.serialize())

        newxml = xml_func(origxml, *args)

        if origxml == newxml:
            logging.debug("Redefinition request XML was no different,"
                          " redefining anyways")
        else:
            diff = "".join(difflib.unified_diff(origxml.splitlines(1),
                                                newxml.splitlines(1),
                                                fromfile="Original XML",
                                                tofile="New XML"))
            logging.debug("Redefining '%s' with XML diff:\n%s",
                          self.get_name(), diff)

        self._define(newxml)

        # Invalidate cached XML
        self._invalidate_xml()

gobject.type_register(vmmLibvirtObject)

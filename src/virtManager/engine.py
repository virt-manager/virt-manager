#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#
import gobject
import gtk
import sys

from virtManager.about import vmmAbout
from virtManager.connect import vmmConnect
from virtManager.connection import vmmConnection
from virtManager.preferences import vmmPreferences
from virtManager.manager import vmmManager
from virtManager.details import vmmDetails
from virtManager.console import vmmConsole

class vmmEngine:
    def __init__(self, config):
        self.windowConnect = None
        self.windowPreferences = None
        self.windowAbout = None

        self.connections = {}

        self.timer = None
        self.last_timeout = 0

        self.config = config
        self.config.on_stats_update_interval_changed(self.reschedule_timer)

        self.schedule_timer()
        self.tick()


    def _do_connection_disconnected(self, connection, hvuri):
        del self.connections[hvuri]

        if len(self.connections.keys()) == 0 and self.windowConnect == None:
            gtk.main_quit()

    def _connect_to_uri(self, connect, uri, readOnly):
        self.windowConnect = None

        try:
            conn = self.get_connection(uri, readOnly)
            self.show_manager(uri)
        except:
            print "Unable to open connection to hypervisor URI '" + str(uri) + "'"
            print str(sys.exc_info()[0]) + " " + str(sys.exc_info()[1])

        if len(self.connections.keys()) == 0:
            gtk.main_quit()

    def _connect_cancelled(self, connect):
        self.windowConnect = None
        if len(self.connections.keys()) == 0:
            gtk.main_quit()


    def _do_vm_removed(self, connection, hvuri, vmuuid):
        if self.connections[hvuri]["windowDetails"].has_key(vmuuid):
            self.connections[hvuri]["windowDetails"][vmuuid].close()
            del self.connections[hvuri]["windowDetails"][vmuuid]
        if self.connections[hvuri]["windowConsole"].has_key(vmuuid):
            self.connections[hvuri]["windowConsole"][vmuuid].close()
            del self.connections[hvuri]["windowConsole"][vmuuid]

    def reschedule_timer(self, ignore1,ignore2,ignore3,ignore4):
        self.schedule_timer()

    def schedule_timer(self):
        interval = self.get_config().get_stats_update_interval() * 1000

        if self.timer != None:
            gobject.source_remove(self.timer)
            self.timer = None

        self.timer = gobject.timeout_add(interval, self.tick)

    def tick(self):
        for uri in self.connections.keys():
            try:
                self.connections[uri]["connection"].tick()
            except KeyboardInterrupt:
                raise KeyboardInterrupt
            except:
                print str(sys.exc_info()[0]) + " " + str(sys.exc_info()[1])
                print "Error refreshing connection " + uri
        return 1

    def change_timer_interval(self,ignore1,ignore2,ignore3,ignore4):
        gobject.source_remove(self.timer)
        self.schedule_timer()

    def get_config(self):
        return self.config

    def _do_show_about(self, src):
        self.show_about()
    def _do_show_preferences(self, src):
        self.show_preferences()
    def _do_show_connect(self, src):
        self.show_connect()
    def _do_show_manager(self, src, uri):
        self.show_manager(uri)
    def _do_show_details(self, src, uri, uuid):
        self.show_details(uri, uuid)
    def _do_show_console(self, src, uri, uuid):
        self.show_console(uri, uuid)

    def show_about(self):
        if self.windowAbout == None:
            self.windowAbout = vmmAbout(self.get_config())
        self.windowAbout.show()

    def show_preferences(self):
        if self.windowPreferences == None:
            self.windowPreferences = vmmPreferences(self.get_config())
        self.windowPreferences.show()

    def show_connect(self):
        if self.windowConnect == None:
            self.windowConnect = vmmConnect(self.get_config(), self)
            self.windowConnect.connect("completed", self._connect_to_uri)
            self.windowConnect.connect("cancelled", self._connect_cancelled)
        self.windowConnect.show()

    def show_console(self, uri, uuid):
        con = self.get_connection(uri)

        if not(self.connections[uri]["windowConsole"].has_key(uuid)):
            console = vmmConsole(self.get_config(),
                                 con.get_vm(uuid))
            console.connect("action-show-details", self._do_show_details)
            self.connections[uri]["windowConsole"][uuid] = console
        self.connections[uri]["windowConsole"][uuid].show()

    def show_details(self, uri, uuid):
        con = self.get_connection(uri)

        if not(self.connections[uri]["windowDetails"].has_key(uuid)):
            details = vmmDetails(self.get_config(),
                                 con.get_vm(uuid))
            details.connect("action-show-console", self._do_show_console)
            self.connections[uri]["windowDetails"][uuid] = details
        self.connections[uri]["windowDetails"][uuid].show()

    def show_manager(self, uri):
        con = self.get_connection(uri)

        if self.connections[uri]["windowManager"] == None:
            manager = vmmManager(self.get_config(),
                                 con)
            manager.connect("action-show-console", self._do_show_console)
            manager.connect("action-show-details", self._do_show_details)
            manager.connect("action-show-preferences", self._do_show_preferences)
            manager.connect("action-show-about", self._do_show_about)
            manager.connect("action-show-connect", self._do_show_connect)
            self.connections[uri]["windowManager"] = manager
        self.connections[uri]["windowManager"].show()

    def get_connection(self, uri, readOnly=True):
        if not(self.connections.has_key(uri)):
            self.connections[uri] = {
                "connection": vmmConnection(self.get_config(), uri, readOnly),
                "windowManager": None,
                "windowDetails": {},
                "windowConsole": {}
                }
            self.connections[uri]["connection"].connect("disconnected", self._do_connection_disconnected)
            self.connections[uri]["connection"].connect("vm-removed", self._do_vm_removed)
            self.connections[uri]["connection"].tick()

        return self.connections[uri]["connection"]

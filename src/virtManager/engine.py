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
        del self.connections[connection.get_uri()]

        if len(self.connections.keys()) == 0 and self.windowConnect == None:
            gtk.main_quit()

    def _connect_to_uri(self, connect, uri, readOnly):
        self.windowOpenConnection = None

        try:
            conn = self.get_connection(uri, readOnly)
            self.show_manager(uri)
        except:
            print "Unable to open connection to hypervisor URI '" + str(uri) + "'"
            print str(sys.exc_info()[0]) + " " + str(sys.exc_info()[1])

        if len(self.connections.keys()) == 0:
            gtk.main_quit()

    def _connect_cancelled(self, connect):
        self.windowOpenConnection = None
        if len(self.connections.keys()) == 0:
            gtk.main_quit()


    def _do_vm_removed(self, connection, hvuri, vmuuid):
        if self.connections[hvuri]["windowDetails"].has_key(vmuuid):
            self.connections[hvuri]["windowDetails"][vmuuid].hide()
            del self.connections[hvuri]["windowDetails"][vmuuid]
        if self.connections[hvuri]["windowConsole"].has_key(vmuuid):
            self.connections[hvuri]["windowConsole"][vmuuid].hide()
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
        key = uri
        if key == None or key == "":
            key = "__default__"

        if not(self.connections.has_key(key)):
            self.connections[key] = {
                "connection": vmmConnection(self.get_config(), uri, readOnly),
                "windowManager": None,
                "windowDetails": {},
                "windowConsole": {}
                }
            self.connections[key]["connection"].connect("disconnected", self._do_connection_disconnected)
            self.connections[key]["connection"].connect("vm-removed", self._do_vm_removed)
            self.connections[key]["connection"].tick()

        return self.connections[key]["connection"]

import gobject

from virtManager.about import vmmAbout
from virtManager.connect import vmmConnect
from virtManager.connection import vmmConnection
from virtManager.preferences import vmmPreferences

class vmmEngine:
    def __init__(self, config):
        self.windowOpenConnection = None
        self.windowPreferences = None
        self.windowAbout = None

        self.connections = {}

        self.timer = None
        self.last_timeout = 0

        self.config = config
        self.config.on_stats_update_interval_changed(self.reschedule_timer)

        self.schedule_timer()
        self.tick()


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
                self.connections[uri].tick()
            except:
                print str(sys.exc_info()[0]) + " " + str(sys.exc_info()[1])
                print "Error refreshing connection " + uri
        return 1

    def change_timer_interval(self,ignore1,ignore2,ignore3,ignore4):
        gobject.source_remove(self.timer)
        self.schedule_timer()

    def get_config(self):
        return self.config

    def show_about(self):
        if self.windowAbout == None:
            self.windowAbout = vmmAbout(self.get_config())
        self.windowAbout.show()

    def show_preferences(self):
        if self.windowPreferences == None:
            self.windowPreferences = vmmPreferences(self.get_config())
        self.windowPreferences.show()

    def show_open_connection(self):
        if self.windowOpenConnection == None:
            self.windowOpenConnection = vmmConnect(self.get_config(), self)
        self.windowOpenConnection.show()

    def show_console(self, uri, uuid):
        con = self.get_connection(uri)
        con.show_console(uuid)

    def show_details(self, uri, uuid):
        con = self.get_connection(uri)
        con.show_details(uuid)

    def show_manager(self, uri):
        con = self.get_connection(uri)
        con.show_manager()

    def get_connection(self, uri, readOnly=True):
        key = uri
        if key == None or key == "":
            key = "__default__"

        if not(self.connections.has_key(key)):
            self.connections[key] = vmmConnection(self, self.get_config(), uri, readOnly)
            self.connections[key].tick()
        return self.connections[key]

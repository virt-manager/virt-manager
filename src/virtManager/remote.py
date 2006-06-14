
import dbus.service

class vmmRemote(dbus.service.Object):
    def __init__(self, engine, bus_name, object_path="/com/redhat/virt/manager"):
        dbus.service.Object.__init__(self, bus_name, object_path)

        self.engine = engine

    @dbus.service.method("com.redhat.virt.manager", in_signature="s")
    def show_domain_creator(self, uri):
        # XXX fixme
        self.engine.show_manager(uri)

    @dbus.service.method("com.redhat.virt.manager", in_signature="ss")
    def show_domain_editor(self, uri, uuid):
        self.engine.show_details(uri, uuid)

    @dbus.service.method("com.redhat.virt.manager", in_signature="ss")
    def show_domain_performance(self, uri, uuid):
        self.engine.show_details(uri, uuid)

    @dbus.service.method("com.redhat.virt.manager", in_signature="ss")
    def show_domain_console(self, uri, uuid):
        self.engine.show_console(uri, uuid)

    @dbus.service.method("com.redhat.virt.manager", in_signature="s")
    def show_host_summary(self, uri):
        print "Openning manage " + uri
        self.engine.show_manager(uri)

    @dbus.service.method("com.redhat.virt.manager")
    def show_open_connection(self):
        self.engine.show_open_connection()

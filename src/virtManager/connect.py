import gobject
import gtk.glade

class vmmConnect(gobject.GObject):
    __gsignals__ = {
        "completed": (gobject.SIGNAL_RUN_FIRST,
                      gobject.TYPE_NONE, (str,bool)),
        "cancelled": (gobject.SIGNAL_RUN_FIRST,
                      gobject.TYPE_NONE, ())
        }
    def __init__(self, config, engine):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-open-connection")
        self.engine = engine
        self.window.get_widget("vmm-open-connection").hide()

        self.window.get_widget("remote-xen-options").set_sensitive(False)
        self.window.get_widget("other-hv-options").set_sensitive(False)

        self.window.signal_autoconnect({
            "on_type_local_xen_toggled": self.change_active_type,
            "on_type_remote_xen_toggled": self.change_active_type,
            "on_type_other_hv_toggled": self.change_active_type,
            "on_cancel_clicked": self.cancel,
            "on_connect_clicked": self.open_connection,
            "on_vmm_open_connection_delete_event": self.cancel,
            })

    def cancel(self,ignore1=None,ignore2=None):
        self.close()
        self.emit("cancelled")
        return 1

    def close(self):
        self.window.get_widget("vmm-open-connection").hide()

    def show(self):
        win = self.window.get_widget("vmm-open-connection")
        win.show_all()
        win.present()

    def change_active_type(self, src):
        if src.get_active():
            if src.get_name() == "type-local-xen":
                self.window.get_widget("remote-xen-options").set_sensitive(False)
                self.window.get_widget("other-hv-options").set_sensitive(False)
            elif src.get_name() == "type-remote-xen":
                self.window.get_widget("remote-xen-options").set_sensitive(True)
                self.window.get_widget("other-hv-options").set_sensitive(False)
            else:
                self.window.get_widget("remote-xen-options").set_sensitive(False)
                self.window.get_widget("other-hv-options").set_sensitive(True)

    def open_connection(self, src):
        uri = None

        if self.window.get_widget("type-local-xen").get_active():
            uri = None
        elif self.window.get_widget("type-remote-xen").get_active():
            protocol = "http"
            if self.window.get_widget("remote-xen-secure").get_active():
                protocol = "https"
                uri = protocol + "://" + self.window.get_widget("remote-xen-host").get_text() + ":" + self.window.get_widget("remote-xen-port").get_text()
        else:
            uri = self.window.get_widget("other-hv-uri").get_text()

        self.close()
        self.emit("completed", uri, self.window.get_widget("option-read-only").get_active())

gobject.type_register(vmmConnect)

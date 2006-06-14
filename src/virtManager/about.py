
import gtk.glade

class vmmAbout:
    def __init__(self, config):
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-about")
        self.window.get_widget("vmm-about").hide()

        self.window.signal_autoconnect({
            "on_vmm_about_delete_event": self.close,
            })

    def show(self):
        dialog = self.window.get_widget("vmm-about")
        dialog.set_version("0.1")
        dialog.show_all()
        dialog.present()

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-about").hide()
        return 1

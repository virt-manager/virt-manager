
import gobject
import gtk.glade
import libvirt

class vmmConsole(gobject.GObject):
    __gsignals__ = {
        "action-show-details": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-launch-terminal": (gobject.SIGNAL_RUN_FIRST,
                                   gobject.TYPE_NONE, (str,str)),
        "action-take-snapshot": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str,str))
        }
    def __init__(self, config, hvuri, stats, vm, vmuuid):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-console")
        self.config = config
        self.hvuri = hvuri
        self.stats = stats
        self.vm = vm
        self.vmuuid = vmuuid
        self.lastStatus = None

        topwin = self.window.get_widget("vmm-console")
        topwin.hide()
        topwin.set_title(vm.name() + " " + topwin.get_title())

        self.window.get_widget("control-run").set_icon_widget(gtk.Image())
        self.window.get_widget("control-run").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_run.png")

        self.window.get_widget("control-pause").set_icon_widget(gtk.Image())
        self.window.get_widget("control-pause").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_pause.png")

        self.window.get_widget("control-shutdown").set_icon_widget(gtk.Image())
        #self.window.get_widget("control-shutdown").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_run.png")

        self.window.get_widget("control-terminal").set_icon_widget(gtk.Image())
        self.window.get_widget("control-terminal").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_launch_term.png")

        self.window.get_widget("control-snapshot").set_icon_widget(gtk.Image())
        self.window.get_widget("control-snapshot").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_snapshot.png")


        self.window.signal_autoconnect({
            "on_vmm_console_delete_event": self.close,

            "on_control_run_clicked": self.control_vm_run,
            "on_control_shutdown_clicked": self.control_vm_shutdown,
            "on_control_pause_toggled": self.control_vm_pause,

            "on_control_terminal_clicked": self.control_vm_terminal,
            "on_control_snapshot_clicked": self.control_vm_snapshot,
            "on_control_details_clicked": self.control_vm_details,
            })

        self.refresh()

    def show(self):
        dialog = self.window.get_widget("vmm-console")
        dialog.show_all()
        dialog.present()

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-console").hide()
        return 1

    def control_vm_run(self, src):
        return 0

    def control_vm_shutdown(self, src):
        info = self.vm.info()
        if not(info[0] in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF ]):
            self.vm.shutdown()
        else:
            print "Shutdown requested, but machine is already shutting down / shutoff"

    def control_vm_pause(self, src):
        info = self.vm.info()
        if info[0] in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
            print "Pause/resume requested, but machine is shutdown / shutoff"
        else:
            if info[0] in [ libvirt.VIR_DOMAIN_PAUSED ]:
                if not src.get_active():
                    self.vm.resume()
                else:
                    print "Pause requested, but machine is already paused"
            else:
                if src.get_active():
                    self.vm.suspend()
                else:
                    print "Resume requested, but machine is already running"


    def control_vm_terminal(self, src):
        self.emit("action-launch-terminal", self.hvuri, self.vmuuid)

    def control_vm_snapshot(self, src):
        self.emit("action-take-snapshot", self.hvuri, self.vmuuid)

    def control_vm_details(self, src):
        self.emit("action-show-details", self.hvuri, self.vmuuid)

    def refresh(self):
        print "In console refresh"
        info = self.vm.info()
        status = info[0]

        if self.lastStatus == status:
            return

        if status == libvirt.VIR_DOMAIN_SHUTOFF:
            self.window.get_widget("control-run").set_sensitive(True)
        else:
            self.window.get_widget("control-run").set_sensitive(False)

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF ]:
            self.window.get_widget("control-pause").set_sensitive(False)
            self.window.get_widget("control-shutdown").set_sensitive(False)
            self.window.get_widget("control-terminal").set_sensitive(False)
            self.window.get_widget("control-snapshot").set_sensitive(False)
        else:
            self.window.get_widget("control-pause").set_sensitive(True)
            self.window.get_widget("control-shutdown").set_sensitive(True)
            self.window.get_widget("control-terminal").set_sensitive(True)
            self.window.get_widget("control-snapshot").set_sensitive(True)
            if status == libvirt.VIR_DOMAIN_PAUSED:
                self.window.get_widget("control-pause").set_active(True)
            else:
                self.window.get_widget("control-pause").set_active(False)

        self.lastStatus = status

gobject.type_register(vmmConsole)

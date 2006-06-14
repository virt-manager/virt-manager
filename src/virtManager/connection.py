
import gobject
import libvirt

from virtManager.stats import vmmStats
from virtManager.manager import vmmManager
from virtManager.details import vmmDetails
from virtManager.console import vmmConsole

class vmmConnection(gobject.GObject):
    __gsignals__ = {
        "vm-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                     (str, str,)),
        "vm-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                       (str,)),
        "vm-updated": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                       (str,)),
        "disconnected": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (str,))
        }

    def __init__(self, engine, config, uri, readOnly):
        self.__gobject_init__()
        self.engine = engine
        self.config = config
        self.uri = uri

        if readOnly:
            self.vmm = libvirt.openReadOnly(uri)
        else:
            self.vmm = libvirt.open(uri)

        self.windowManager = None
        self.windowDetails = {}
        self.windowConsole = {}
        self.vms = {}

        self.stats = vmmStats(config, self)

    def get_uri(self):
        return self.uri

    def get_stats(self):
        return self.stats

    def show_about(self):
        self.engine.show_about()

    def show_preferences(self):
        self.engine.show_preferences()

    def show_manager(self):
        if self.windowManager == None:
            self.windowManager = vmmManager(self.config, self)
        self.windowManager.show()

    def disconnect(self):
        if self.vmm == None:
            return

        #self.vmm.close()
        self.vmm = None
        if self.windowManager != None:
            self.windowManager.close()
            self.windowManager = None
        for uuid in self.windowDetails.keys():
            self.windowDetails[uuid].close()
            del self.windowDetails[uuid]
        for uuid in self.windowConsole.keys():
            self.windowConsole[uuid].close()
            del self.windowConsole[uuid]

        self.emit("disconnected", "dummy")

    def get_host_info(self):
        return self.vmm.getInfo()

    def show_details(self, vmuuid):
        if not(self.windowDetails.has_key(vmuuid)):
            self.windowDetails[vmuuid] = vmmDetails(self.config, self, self.vms[vmuuid], vmuuid)

        self.windowDetails[vmuuid].show()

    def show_console(self, vmuuid):
        if not(self.windowConsole.has_key(vmuuid)):
            self.windowConsole[vmuuid] = vmmConsole(self.config, self, self.vms[vmuuid], vmuuid)

        self.windowConsole[vmuuid].show()

    def show_open_connection(self):
        self.engine.show_open_connection()

    def connect(self, name, callback):
        gobject.GObject.connect(self, name, callback)
        print "Cnnect " + name + " to " + str(callback)
        if name == "vm-added":
            for uuid in self.vms.keys():
                self.emit("vm-added", uuid, self.vms[uuid].name())

    def tick(self):
        if self.vmm == None:
            return

        doms = self.vmm.listDomainsID()
        newVms = {}
        if doms != None:
            for id in doms:
                vm = self.vmm.lookupByID(id)
                newVms[self.uuidstr(vm.UUID())] = vm

        for uuid in self.vms.keys():
            if not(newVms.has_key(uuid)):
                del self.vms[uuid]
                self.emit("vm-removed", uuid)

        for uuid in newVms.keys():
            if not(self.vms.has_key(uuid)):
                self.vms[uuid] = newVms[uuid]
                print "Trying to emit"
                self.emit("vm-added",uuid, newVms[uuid].name())

        for uuid in self.vms.keys():
            self.stats.update(uuid, self.vms[uuid])
            self.emit("vm-updated", uuid)

        return 1

    def uuidstr(self, rawuuid):
        hex = ['0','1','2','3','4','5','6','7','8','9','a','b','c','d','e','f']
        uuid = []
        for i in range(16):
            uuid.append(hex[((ord(rawuuid[i]) >> 4) & 0xf)])
            uuid.append(hex[(ord(rawuuid[i]) & 0xf)])
            if i == 3 or i == 5 or i == 7 or i == 9:
                uuid.append('-')
        return "".join(uuid)

gobject.type_register(vmmConnection)


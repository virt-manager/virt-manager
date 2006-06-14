
import libvirt

from virtManager.stats import vmmStats
from virtManager.manager import vmmManager
from virtManager.details import vmmDetails
from virtManager.console import vmmConsole

class vmmConnection:
    def __init__(self, engine, config, uri, readOnly):
        self.engine = engine
        self.config = config

        if readOnly:
            self.vmm = libvirt.openReadOnly(uri)
        else:
            self.vmm = libvirt.open(uri)

        self.windowManager = None
        self.windowDetails = {}
        self.windowConsole = {}
        self.vms = {}

        self.callbacks = { "vm_added": [], "vm_removed": [], "vm_updated": [] }
        self.stats = vmmStats(config, self)

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

    def connect_to_signal(self, name, callback):
        if not(self.callbacks.has_key(name)):
            raise "unknown signal " + name + "requested"

        self.callbacks[name].append(callback)

        if name == "vm_removed":
            for uuid in self.vms.keys():
                self.notify_vm_added(uuid, self.vms[uuid].name())

    def disconnect_from_signal(self, name, callback):
        for i in len(self.callbacks[name]):
            if self.callbacks[i] == callback:
                del self.callbacks[i:i]


    def notify_vm_added(self, uuid, name):
        for cb in self.callbacks["vm_added"]:
            cb(uuid, name)

    def notify_vm_removed(self, uuid):
        for cb in self.callbacks["vm_removed"]:
            cb(uuid)

    def notify_vm_updated(self, uuid):
        for cb in self.callbacks["vm_updated"]:
            cb(uuid)

    def tick(self):
        doms = self.vmm.listDomainsID()
        newVms = {}
        if doms != None:
            for id in doms:
                vm = self.vmm.lookupByID(id)
                newVms[self.uuidstr(vm.UUID())] = vm

        for uuid in self.vms.keys():
            if not(newVms.has_key(uuid)):
                del self.vms[uuid]
                self.notify_vm_removed(uuid)

        for uuid in newVms.keys():
            if not(self.vms.has_key(uuid)):
                self.vms[uuid] = newVms[uuid]
                self.notify_vm_added(uuid, newVms[uuid].name())

        for uuid in self.vms.keys():
            self.stats.update(uuid, self.vms[uuid])
            self.notify_vm_updated(uuid)

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



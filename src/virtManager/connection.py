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
import libvirt
from time import time

from virtManager.domain import vmmDomain

class vmmConnection(gobject.GObject):
    __gsignals__ = {
        "vm-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                     [str, str]),
        "vm-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                       [str, str]),
        "disconnected": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [str])
        }

    def __init__(self, config, uri, readOnly):
        self.__gobject_init__()
        self.config = config
        self.uri = uri
        self.readOnly = readOnly

        openURI = uri
        if openURI == "Xen":
            openURI = None
        if readOnly:
            self.vmm = libvirt.openReadOnly(openURI)
        else:
            self.vmm = libvirt.open(openURI)

        self.vms = {}
        self.tick()

    def is_read_only(self):
        return self.readOnly

    def get_uri(self):
        return self.uri

    def get_vm(self, uuid):
        return self.vms[uuid]

    def disconnect(self):
        if self.vmm == None:
            return

        #self.vmm.close()
        self.vmm = None
        self.emit("disconnected", self.uri)

    def get_host_info(self):
        return self.hostinfo

    def connect(self, name, callback):
        gobject.GObject.connect(self, name, callback)

        if name == "vm-added":
            for uuid in self.vms.keys():
                self.emit("vm-added", self.uri, uuid)

    def host_memory_size(self):
        return self.hostinfo[1]*1024

    def host_active_processor_count(self):
        return self.hostinfo[2]

    def host_maximum_processor_count(self):
        return self.hostinfo[4] * self.hostinfo[5] * self.hostinfo[6] * self.hostinfo[7]


    def tick(self):
        if self.vmm == None:
            return

        ids = {}
        for uuid in self.vms.keys():
            vm = self.vms[uuid]
            ids[vm.get_id()] = vm

        doms = self.vmm.listDomainsID()
        newVms = {}
        if doms != None:
            for id in doms:
                if ids.has_key(id):
                    # Existing VM, so just keep handle
                    vm = ids[id]
                    del ids[id]
                else:
                    # New VM so create wrapper object
                    vm = self.vmm.lookupByID(id)
                    uuid = self.uuidstr(vm.UUID())
                    newVms[uuid] = vm

        # Any left in ids hash are old removed VMs
        for id in ids:
            vm = ids[id]
            del self.vms[vm.get_uuid()]
            self.emit("vm-removed", self.uri, vm.get_uuid())

        # Any in newVms hash are added
        for uuid in newVms.keys():
            vm = newVms[uuid]
            self.vms[uuid] = vmmDomain(self.config, self, vm, uuid)
            self.emit("vm-added", self.uri, uuid)

        now = time()
        self.hostinfo = self.vmm.getInfo()
        for uuid in self.vms.keys():
            self.vms[uuid].tick(now)

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


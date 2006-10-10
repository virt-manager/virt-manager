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
import os
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

    def is_read_only(self):
        return self.readOnly

    def get_uri(self):
        return self.uri

    def get_vm(self, uuid):
        return self.vms[uuid]

    def close(self):
        if self.vmm == None:
            return

        #self.vmm.close()
        self.vmm = None
        self.emit("disconnected", self.uri)

    def list_vm_uuids(self):
        return self.vms.keys()

    def get_host_info(self):
        return self.hostinfo

    def connect(self, name, callback):
        handle_id = gobject.GObject.connect(self, name, callback)

        if name == "vm-added":
            for uuid in self.vms.keys():
                self.emit("vm-added", self.uri, uuid)

        return handle_id

    def host_memory_size(self):
        return self.hostinfo[1]*1024

    def host_active_processor_count(self):
        return self.hostinfo[2]

    def host_maximum_processor_count(self):
        return self.hostinfo[4] * self.hostinfo[5] * self.hostinfo[6] * self.hostinfo[7]

    def restore(self, frm):
        status = self.vmm.restore(frm)
        if(status == 0):
            os.remove(frm)
        return status

    def tick(self, noStatsUpdate=False):
        if self.vmm == None:
            return

        oldActiveIDs = {}
        oldInactiveNames = {}
        for uuid in self.vms.keys():
            vm = self.vms[uuid]
            if vm.get_id() == -1:
                oldInactiveNames[vm.get_name()] = vm
            else:
                oldActiveIDs[vm.get_id()] = vm

        newActiveIDs = self.vmm.listDomainsID()
        newInactiveNames = self.vmm.listDefinedDomains()

        newUUIDs = {}
        oldUUIDs = {}
        curUUIDs = {}
        maybeNewUUIDs = {}

        # NB in these first 2 loops, we go to great pains to
        # avoid actually instantiating a new VM object so that
        # the common case of 'no new/old VMs' avoids hitting
        # XenD too much & thus slowing stuff down.

        # Filter out active domains which haven't changed
        if newActiveIDs != None:
            for id in newActiveIDs:
                if oldActiveIDs.has_key(id):
                    # No change, copy across existing VM object
                    vm = oldActiveIDs[id]
                    #print "Existing active " + str(vm.get_name()) + " " + vm.get_uuid()
                    curUUIDs[vm.get_uuid()] = vm
                else:
                    # May be a new VM, we have no choice but
                    # to create the wrapper so we can see
                    # if its a previously inactive domain.
                    vm = self.vmm.lookupByID(id)
                    uuid = self.uuidstr(vm.UUID())
                    maybeNewUUIDs[uuid] = vm
                    #print "Maybe new active " + str(maybeNewUUIDs[uuid].get_name()) + " " + uuid

        # Filter out inactive domains which haven't changed
        if newInactiveNames != None:
            for name in newInactiveNames:
                if oldInactiveNames.has_key(name):
                    # No change, copy across existing VM object
                    vm = oldInactiveNames[name]
                    #print "Existing inactive " + str(vm.get_name()) + " " + vm.get_uuid()
                    curUUIDs[vm.get_uuid()] = vm
                else:
                    # May be a new VM, we have no choice but
                    # to create the wrapper so we can see
                    # if its a previously inactive domain.
                    vm = self.vmm.lookupByName(name)
                    uuid = self.uuidstr(vm.UUID())
                    maybeNewUUIDs[uuid] = vm
                    #print "Maybe new inactive " + str(maybeNewUUIDs[uuid].get_name()) + " " + uuid

        # At this point, maybeNewUUIDs has domains which are
        # either completely new, or changed state.

        # Filter out VMs which merely changed state, leaving
        # only new domains
        for uuid in maybeNewUUIDs.keys():
            rawvm = maybeNewUUIDs[uuid]
            if not(self.vms.has_key(uuid)):
                #print "Completely new VM " + str(vm)
                vm = vmmDomain(self.config, self, rawvm, uuid)
                newUUIDs[vm.get_uuid()] = vm
                curUUIDs[uuid] = vm
            else:
                vm = self.vms[uuid]
                vm.set_handle(rawvm)
                curUUIDs[uuid] = vm
                #print "Mere state change " + str(vm)

        # Finalize list of domains which went away altogether
        for uuid in self.vms.keys():
            vm = self.vms[uuid]
            if not(curUUIDs.has_key(uuid)):
                #print "Completly old VM " + str(vm)
                oldUUIDs[uuid] = vm
            else:
                #print "Mere state change " + str(vm)
                pass

        # We have our new master list
        self.vms = curUUIDs

        # Inform everyone what changed
        for uuid in oldUUIDs:
            vm = oldUUIDs[uuid]
            #print "Remove " + vm.get_name() + " " + uuid
            self.emit("vm-removed", self.uri, uuid)

        for uuid in newUUIDs:
            vm = newUUIDs[uuid]
            #print "Add " + vm.get_name() + " " + uuid
            self.emit("vm-added", self.uri, uuid)

        # Finally, we sample each domain
        now = time()
        self.hostinfo = self.vmm.getInfo()

        updateVMs = self.vms
        if noStatsUpdate:
            updateVMs = newVms

        for uuid in updateVMs.keys():
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


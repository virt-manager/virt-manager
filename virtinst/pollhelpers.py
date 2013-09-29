#
# Copyright (C) 2013 Red Hat, Inc.
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.
#

import logging

from virtinst import util


def _new_poll_helper(origmap, typename, listfunc, keyfunc, buildfunc):
    """
    Helper for new style listAll* APIs
    """
    current = {}
    new = {}
    objs = []

    try:
        objs = listfunc()
    except Exception, e:
        logging.debug("Unable to list all %ss: %s", typename, e)

    for obj in objs:
        key = getattr(obj, keyfunc)()

        if key not in origmap:
            # Object is brand new this period
            current[key] = buildfunc(obj, key)
            new[key] = current[key]
        else:
            # Previously known object
            current[key] = origmap[key]
            del origmap[key]

    return (origmap, new, current)


def _old_poll_helper(origmap, typename,
                     active_list, inactive_list,
                     lookup_func, build_func):
    """
    Helper routine for old style split API libvirt polling.
    @origmap: Pre-existing mapping of objects, with key->obj mapping.
        objects must have an is_active and set_active API
    @typename: string describing type of objects we are polling for use
        in debug messages.
    @active_list: Function that returns the list of active objects
    @inactive_list: Function that returns the list of inactive objects
    @lookup_func: Function to get an object handle for the passed name
    @build_func: Function that builds a new object class. It is passed
        args of (raw libvirt object, key (usually UUID))
    """
    current = {}
    new = {}
    newActiveNames = []
    newInactiveNames = []

    try:
        newActiveNames = active_list()
    except Exception, e:
        logging.debug("Unable to list active %ss: %s", typename, e)
    try:
        newInactiveNames = inactive_list()
    except Exception, e:
        logging.debug("Unable to list inactive %ss: %s", typename, e)

    def check_obj(key):
        if key not in origmap:
            try:
                obj = lookup_func(key)
            except Exception, e:
                logging.debug("Could not fetch %s '%s': %s",
                              typename, key, e)
                return

            # Object is brand new this period
            current[key] = build_func(obj, key)
            new[key] = current[key]
        else:
            # Previously known object
            current[key] = origmap[key]
            del origmap[key]

    for name in newActiveNames + newInactiveNames:
        try:
            check_obj(name)
        except:
            logging.exception("Couldn't fetch %s '%s'", typename, name)

    return (origmap, new, current)


def fetch_nets(backend, origmap, build_func):
    name = "network"

    if backend.check_conn_support(
            backend.SUPPORT_CONN_LISTALLNETWORKS):
        return _new_poll_helper(origmap, name,
                                backend.listAllNetworks,
                                "UUIDString", build_func)
    else:
        active_list = backend.listNetworks
        inactive_list = backend.listDefinedNetworks
        lookup_func = backend.networkLookupByName

        return _old_poll_helper(origmap, name,
                                active_list, inactive_list,
                                lookup_func, build_func)


def fetch_pools(backend, origmap, build_func):
    name = "pool"

    if backend.check_conn_support(
            backend.SUPPORT_CONN_LISTALLSTORAGEPOOLS):
        return _new_poll_helper(origmap, name,
                                backend.listAllStoragePools,
                                "UUIDString", build_func)
    else:
        active_list = backend.listStoragePools
        inactive_list = backend.listDefinedStoragePools
        lookup_func = backend.storagePoolLookupByName

        return _old_poll_helper(origmap, name,
                                active_list, inactive_list,
                                lookup_func, build_func)


def fetch_volumes(backend, pool, origmap, build_func):
    name = "volume"

    if backend.check_pool_support(pool,
        backend.SUPPORT_POOL_LISTALLVOLUMES):
        return _new_poll_helper(origmap, name,
                                pool.listAllVolumes,
                                "name", build_func)
    else:
        active_list = pool.listVolumes
        inactive_list = lambda: []
        lookup_func = pool.storageVolLookupByName
        return _old_poll_helper(origmap, name,
                                active_list, inactive_list,
                                lookup_func, build_func)


def fetch_interfaces(backend, origmap, build_func):
    name = "interface"

    if backend.check_conn_support(
            backend.SUPPORT_CONN_LISTALLINTERFACES):
        return _new_poll_helper(origmap, name,
                                backend.listAllInterfaces,
                                "name", build_func)
    else:
        active_list = backend.listInterfaces
        inactive_list = backend.listDefinedInterfaces
        lookup_func = backend.interfaceLookupByName

        return _old_poll_helper(origmap, name,
                                active_list, inactive_list,
                                lookup_func, build_func)


def fetch_nodedevs(backend, origmap, build_func):
    name = "nodedev"
    if backend.check_conn_support(
            backend.SUPPORT_CONN_LISTALLDEVICES):
        return _new_poll_helper(origmap, name,
                                backend.listAllDevices,
                                "name", build_func)
    else:
        active_list = lambda: backend.listDevices(None, 0)
        inactive_list = lambda: []
        lookup_func = backend.nodeDeviceLookupByName
        return _old_poll_helper(origmap, name,
                                active_list, inactive_list,
                                lookup_func, build_func)


def _old_fetch_vms(backend, origmap, build_func):
    # We can't easily use _old_poll_helper here because the domain API
    # doesn't always return names like other objects, it returns
    # IDs for active VMs

    newActiveIDs = []
    newInactiveNames = []
    oldActiveIDs = {}
    oldInactiveNames = {}
    current = {}
    new = {}

    # Build list of previous vms with proper id/name mappings
    for uuid in origmap:
        vm = origmap[uuid]
        if vm.is_active():
            oldActiveIDs[vm.get_id()] = vm
        else:
            oldInactiveNames[vm.get_name()] = vm

    try:
        newActiveIDs = backend.listDomainsID()
    except Exception, e:
        logging.debug("Unable to list active domains: %s", e)

    try:
        newInactiveNames = backend.listDefinedDomains()
    except Exception, e:
        logging.exception("Unable to list inactive domains: %s", e)

    def add_vm(vm):
        uuid = vm.get_uuid()

        current[uuid] = vm
        del(origmap[uuid])

    def check_new(rawvm, uuid):
        if uuid in origmap:
            vm = origmap[uuid]
            del(origmap[uuid])
        else:
            vm = build_func(rawvm, uuid)
            new[uuid] = vm

        current[uuid] = vm

    for _id in newActiveIDs:
        if _id in oldActiveIDs:
            # No change, copy across existing VM object
            vm = oldActiveIDs[_id]
            add_vm(vm)
        else:
            # Check if domain is brand new, or old one that changed state
            try:
                vm = backend.lookupByID(_id)
                uuid = util.uuidstr(vm.UUID())

                check_new(vm, uuid)
            except:
                logging.exception("Couldn't fetch domain id '%s'", _id)


    for name in newInactiveNames:
        if name in oldInactiveNames:
            # No change, copy across existing VM object
            vm = oldInactiveNames[name]
            add_vm(vm)
        else:
            # Check if domain is brand new, or old one that changed state
            try:
                vm = backend.lookupByName(name)
                uuid = util.uuidstr(vm.UUID())

                check_new(vm, uuid)
            except:
                logging.exception("Couldn't fetch domain '%s'", name)

    return (origmap, new, current)


def fetch_vms(backend, origmap, build_func):
    name = "domain"
    if backend.check_conn_support(
            backend.SUPPORT_CONN_LISTALLDOMAINS):
        return _new_poll_helper(origmap, name,
                                backend.listAllDomains,
                                "UUIDString", build_func)
    else:
        return _old_fetch_vms(backend, origmap, build_func)

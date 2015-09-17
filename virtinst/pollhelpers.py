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


# Debugging helper to force old style polling
# Can be enabled with virt-manager --test-old-poll
FORCE_OLD_POLL = False


def _new_poll_helper(origmap, typename, listfunc, buildfunc):
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
        connkey = obj.name()

        if connkey not in origmap:
            # Object is brand new this period
            current[connkey] = buildfunc(obj, connkey)
            new[connkey] = current[connkey]
        else:
            # Previously known object
            current[connkey] = origmap[connkey]
            del(origmap[connkey])

    return (origmap.values(), new.values(), current.values())


def _old_poll_helper(origmap, typename,
                     active_list, inactive_list,
                     lookup_func, build_func):
    """
    Helper routine for old style split API libvirt polling.
    @origmap: Pre-existing mapping of objects, with connkey->obj mapping.
        objects must have an is_active and set_active API
    @typename: string describing type of objects we are polling for use
        in debug messages.
    @active_list: Function that returns the list of active objects
    @inactive_list: Function that returns the list of inactive objects
    @lookup_func: Function to get an object handle for the passed name
    @build_func: Function that builds a new object class. It is passed
        args of (raw libvirt object, connkey)
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

    def check_obj(name):
        obj = None
        connkey = name

        if connkey not in origmap:
            try:
                obj = lookup_func(name)
            except Exception, e:
                logging.debug("Could not fetch %s '%s': %s",
                              typename, connkey, e)
                return

            # Object is brand new this period
            current[connkey] = build_func(obj, connkey)
            new[connkey] = current[connkey]
        else:
            # Previously known object
            current[connkey] = origmap[connkey]
            del(origmap[connkey])

    for name in newActiveNames + newInactiveNames:
        try:
            check_obj(name)
        except:
            logging.exception("Couldn't fetch %s '%s'", typename, name)

    return (origmap.values(), new.values(), current.values())


def fetch_nets(backend, origmap, build_func):
    name = "network"

    if backend.check_support(
        backend.SUPPORT_CONN_LISTALLNETWORKS) and not FORCE_OLD_POLL:
        return _new_poll_helper(origmap, name,
                                backend.listAllNetworks, build_func)
    else:
        active_list = backend.listNetworks
        inactive_list = backend.listDefinedNetworks
        lookup_func = backend.networkLookupByName

        return _old_poll_helper(origmap, name,
                                active_list, inactive_list,
                                lookup_func, build_func)


def fetch_pools(backend, origmap, build_func):
    name = "pool"

    if backend.check_support(
        backend.SUPPORT_CONN_LISTALLSTORAGEPOOLS) and not FORCE_OLD_POLL:
        return _new_poll_helper(origmap, name,
                                backend.listAllStoragePools, build_func)
    else:
        active_list = backend.listStoragePools
        inactive_list = backend.listDefinedStoragePools
        lookup_func = backend.storagePoolLookupByName

        return _old_poll_helper(origmap, name,
                                active_list, inactive_list,
                                lookup_func, build_func)


def fetch_volumes(backend, pool, origmap, build_func):
    name = "volume"

    if backend.check_support(
        backend.SUPPORT_POOL_LISTALLVOLUMES, pool) and not FORCE_OLD_POLL:
        return _new_poll_helper(origmap, name,
                                pool.listAllVolumes, build_func)
    else:
        active_list = pool.listVolumes
        def inactive_list():
            return []
        lookup_func = pool.storageVolLookupByName
        return _old_poll_helper(origmap, name,
                                active_list, inactive_list,
                                lookup_func, build_func)


def fetch_interfaces(backend, origmap, build_func):
    name = "interface"

    if backend.check_support(
        backend.SUPPORT_CONN_LISTALLINTERFACES) and not FORCE_OLD_POLL:
        return _new_poll_helper(origmap, name,
                                backend.listAllInterfaces, build_func)
    else:
        active_list = backend.listInterfaces
        inactive_list = backend.listDefinedInterfaces
        lookup_func = backend.interfaceLookupByName

        return _old_poll_helper(origmap, name,
                                active_list, inactive_list,
                                lookup_func, build_func)


def fetch_nodedevs(backend, origmap, build_func):
    name = "nodedev"
    if backend.check_support(
        backend.SUPPORT_CONN_LISTALLDEVICES) and not FORCE_OLD_POLL:
        return _new_poll_helper(origmap, name,
                                backend.listAllDevices, build_func)
    else:
        def active_list():
            return backend.listDevices(None, 0)
        def inactive_list():
            return []
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
    for vm in origmap.values():
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
        connkey = vm.get_name()

        current[connkey] = vm
        del(origmap[connkey])

    def check_new(rawvm, connkey):
        if connkey in origmap:
            vm = origmap[connkey]
            del(origmap[connkey])
        else:
            vm = build_func(rawvm, connkey)
            new[connkey] = vm

        current[connkey] = vm

    for _id in newActiveIDs:
        if _id in oldActiveIDs:
            # No change, copy across existing VM object
            vm = oldActiveIDs[_id]
            add_vm(vm)
        else:
            # Check if domain is brand new, or old one that changed state
            try:
                vm = backend.lookupByID(_id)
                connkey = vm.name()

                check_new(vm, connkey)
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
                connkey = name

                check_new(vm, connkey)
            except:
                logging.exception("Couldn't fetch domain '%s'", name)

    return (origmap.values(), new.values(), current.values())


def fetch_vms(backend, origmap, build_func):
    name = "domain"
    if backend.check_support(
        backend.SUPPORT_CONN_LISTALLDOMAINS):
        return _new_poll_helper(origmap, name,
                                backend.listAllDomains, build_func)
    else:
        return _old_fetch_vms(backend, origmap, build_func)

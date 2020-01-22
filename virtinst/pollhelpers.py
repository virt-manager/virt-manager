#
# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
#

from .logger import log


def _new_poll_helper(origmap, typename, listfunc, buildfunc):
    """
    Helper for new style listAll* APIs
    """
    current = {}
    new = {}
    objs = []

    try:
        objs = listfunc()
    except Exception as e:
        log.debug("Unable to list all %ss: %s", typename, e)

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

    return (list(origmap.values()), list(new.values()), list(current.values()))


def fetch_nets(backend, origmap, build_func):
    name = "network"
    return _new_poll_helper(origmap, name,
                            backend.listAllNetworks, build_func)


def fetch_pools(backend, origmap, build_func):
    name = "pool"
    return _new_poll_helper(origmap, name,
                            backend.listAllStoragePools, build_func)


def fetch_volumes(backend, pool, origmap, build_func):
    name = "volume"
    return _new_poll_helper(origmap, name,
                            pool.listAllVolumes, build_func)


def fetch_interfaces(backend, origmap, build_func):
    name = "interface"
    return _new_poll_helper(origmap, name,
                            backend.listAllInterfaces, build_func)


def fetch_nodedevs(backend, origmap, build_func):
    name = "nodedev"
    return _new_poll_helper(origmap, name,
                            backend.listAllDevices, build_func)


def fetch_vms(backend, origmap, build_func):
    name = "domain"
    return _new_poll_helper(origmap, name,
                            backend.listAllDomains, build_func)

#
# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
#

from .logger import log


def _new_poll_helper(origmap, typename, list_cb, build_cb, support_cb):
    """
    Helper for new style listAll* APIs
    """
    current = {}
    new = {}
    objs = []

    try:
        if support_cb():
            objs = list_cb()
    except Exception as e:  # pragma: no cover
        log.debug("Unable to list all %ss: %s", typename, e)

    for obj in objs:
        name = obj.name()

        if name not in origmap:
            # Object is brand new this period
            current[name] = build_cb(obj, name)
            new[name] = current[name]
        else:
            # Previously known object
            current[name] = origmap[name]
            del(origmap[name])

    return (list(origmap.values()), list(new.values()), list(current.values()))


def fetch_nets(backend, origmap, build_cb):
    typename = "network"
    list_cb = backend.listAllNetworks
    support_cb = backend.support.conn_network
    return _new_poll_helper(origmap, typename, list_cb, build_cb, support_cb)


def fetch_pools(backend, origmap, build_cb):
    typename = "pool"
    list_cb = backend.listAllStoragePools
    support_cb = backend.support.conn_storage
    return _new_poll_helper(origmap, typename, list_cb, build_cb, support_cb)


def fetch_volumes(backend, pool, origmap, build_cb):
    typename = "volume"
    list_cb = pool.listAllVolumes
    support_cb = backend.support.conn_storage
    return _new_poll_helper(origmap, typename, list_cb, build_cb, support_cb)


def fetch_nodedevs(backend, origmap, build_cb):
    typename = "nodedev"
    list_cb = backend.listAllDevices
    support_cb = backend.support.conn_nodedev
    return _new_poll_helper(origmap, typename, list_cb, build_cb, support_cb)


def fetch_vms(backend, origmap, build_cb):
    typename = "domain"
    list_cb = backend.listAllDomains
    support_cb = backend.support.conn_domain
    return _new_poll_helper(origmap, typename, list_cb, build_cb, support_cb)

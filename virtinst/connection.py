#
# Copyright 2013, 2014, 2015 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import weakref

import libvirt

from . import Capabilities
from . import pollhelpers
from . import support
from . import xmlutil
from .guest import Guest
from .logger import log
from .nodedev import NodeDevice
from .storage import StoragePool, StorageVolume
from .uri import URI, MagicURI


def _real_local_libvirt_version():
    """
    Lookup the local libvirt library version, but cache the value since
    it never changes.
    """
    key = "__virtinst_cached_getVersion"
    if not hasattr(libvirt, key):
        setattr(libvirt, key, libvirt.getVersion())
    return getattr(libvirt, key)


class VirtinstConnection(object):
    """
    Wrapper for libvirt connection that provides various bits like
    - caching static data
    - lookup for API feature support
    - simplified API wrappers that handle new and old ways of doing things
    """
    @staticmethod
    def get_app_cache_dir():
        ret = os.environ.get("XDG_CACHE_HOME")
        if not ret:
            ret = os.path.expanduser("~/.cache")
        return os.path.join(ret, "virt-manager")

    @staticmethod
    def in_testsuite():
        return xmlutil.in_testsuite()

    def __init__(self, uri):
        _initial_uri = uri or ""

        if MagicURI.uri_is_magic(_initial_uri):
            self._magic_uri = MagicURI(_initial_uri)
            self._open_uri = self._magic_uri.open_uri
            self._uri = self._magic_uri.fakeuri or self._open_uri

            self._fake_conn_predictable = self._magic_uri.predictable
            self._fake_conn_version = self._magic_uri.conn_version
            self._fake_libvirt_version = self._magic_uri.libvirt_version
        else:
            self._magic_uri = None
            self._open_uri = _initial_uri
            self._uri = _initial_uri

            self._fake_conn_predictable = False
            self._fake_libvirt_version = None
            self._fake_conn_version = None

        self._daemon_version = None
        self._conn_version = None

        self._libvirtconn = None
        self._uriobj = URI(self._uri)
        self._caps = None

        self._fetch_cache = {}

        # These let virt-manager register a callback which provides its
        # own cached object lists, rather than doing fresh calls
        self.cb_fetch_all_domains = None
        self.cb_fetch_all_pools = None
        self.cb_fetch_all_vols = None
        self.cb_fetch_all_nodedevs = None
        self.cb_cache_new_pool = None

        self.support = support.SupportCache(weakref.proxy(self))


    ##############
    # Properties #
    ##############

    def __getattr__(self, attr):
        # Proxy virConnect API calls
        libvirtconn = self.__dict__.get("_libvirtconn")
        return getattr(libvirtconn, attr)

    def _get_uri(self):
        return self._uri or self._open_uri
    uri = property(_get_uri)

    def _get_caps(self):
        if not self._caps:
            self._caps = Capabilities(self,
                self._libvirtconn.getCapabilities())
        return self._caps
    caps = property(_get_caps)

    def get_conn_for_api_arg(self):
        return self._libvirtconn


    ##############
    # Public API #
    ##############

    def close(self):
        ret = 0
        if self._libvirtconn:
            ret = self._libvirtconn.close()
        self._libvirtconn = None
        self._uri = None
        self._fetch_cache = {}
        return ret

    def fake_conn_predictable(self):
        return self._fake_conn_predictable

    def invalidate_caps(self):
        self._caps = None

    def is_open(self):
        return bool(self._libvirtconn)

    def open(self, authcb, cbdata):
        if self._magic_uri:
            self._magic_uri.validate()

        # Mirror the set of libvirt.c virConnectCredTypeDefault
        valid_auth_options = [
            libvirt.VIR_CRED_AUTHNAME,
            libvirt.VIR_CRED_ECHOPROMPT,
            libvirt.VIR_CRED_REALM,
            libvirt.VIR_CRED_PASSPHRASE,
            libvirt.VIR_CRED_NOECHOPROMPT,
            libvirt.VIR_CRED_EXTERNAL,
        ]
        open_flags = 0

        conn = libvirt.openAuth(self._open_uri,
                [valid_auth_options, authcb, cbdata],
                open_flags)

        if self._magic_uri:
            self._magic_uri.overwrite_conn_functions(conn)

        self._libvirtconn = conn
        if not self._open_uri:
            self._uri = self._libvirtconn.getURI()
            self._uriobj = URI(self._uri)


    ####################
    # Polling routines #
    ####################

    _FETCH_KEY_DOMAINS = "vms"
    _FETCH_KEY_POOLS = "pools"
    _FETCH_KEY_VOLS = "vols"
    _FETCH_KEY_NODEDEVS = "nodedevs"

    def _fetch_helper(self, key, raw_cb, override_cb):
        if override_cb:
            return override_cb()  # pragma: no cover
        if key not in self._fetch_cache:
            self._fetch_cache[key] = raw_cb()
        return self._fetch_cache[key][:]

    def _fetch_all_domains_raw(self):
        dummy1, dummy2, ret = pollhelpers.fetch_vms(
            self, {}, lambda obj, ignore: obj)
        domains = []
        for obj in ret:
            # TOCTOU race: a domain may go away in between enumeration and inspection
            try:
                xml = obj.XMLDesc(0)
            except libvirt.libvirtError as e:  # pragma: no cover
                log.debug("Fetching domain XML failed: %s", e)
                continue
            domains.append(Guest(weakref.proxy(self), parsexml=xml))
        return domains

    def _build_pool_raw(self, poolobj):
        return StoragePool(weakref.proxy(self),
                           parsexml=poolobj.XMLDesc(0))

    def _fetch_all_pools_raw(self):
        dummy1, dummy2, ret = pollhelpers.fetch_pools(
            self, {}, lambda obj, ignore: obj)
        pools = []
        for poolobj in ret:
            # TOCTOU race: a pool may go away in between enumeration and inspection
            try:
                pool = self._build_pool_raw(poolobj)
            except libvirt.libvirtError as e:  # pragma: no cover
                log.debug("Fetching pool XML failed: %s", e)
                continue
            pools.append(pool)
        return pools

    def _fetch_all_nodedevs_raw(self):
        dummy1, dummy2, ret = pollhelpers.fetch_nodedevs(
            self, {}, lambda obj, ignore: obj)
        return [NodeDevice(weakref.proxy(self), obj.XMLDesc(0))
                for obj in ret]

    def _fetch_vols_raw(self, poolxmlobj):
        ret = []
        # TOCTOU race: a volume may go away in between enumeration and inspection
        try:
            pool = self._libvirtconn.storagePoolLookupByName(poolxmlobj.name)
        except libvirt.libvirtError as e:  # pragma: no cover
            return ret

        if pool.info()[0] != libvirt.VIR_STORAGE_POOL_RUNNING:
            return ret

        dummy1, dummy2, vols = pollhelpers.fetch_volumes(
            self, pool, {}, lambda obj, ignore: obj)

        for vol in vols:
            try:
                xml = vol.XMLDesc(0)
                ret.append(StorageVolume(weakref.proxy(self), parsexml=xml))
            except libvirt.libvirtError as e:  # pragma: no cover
                log.debug("Fetching volume XML failed: %s", e)
        return ret

    def _fetch_all_vols_raw(self):
        ret = []
        for poolxmlobj in self.fetch_all_pools():
            ret.extend(self._fetch_vols_raw(poolxmlobj))
        return ret

    def _cache_new_pool_raw(self, poolobj):
        # Make sure cache is primed
        if self._FETCH_KEY_POOLS not in self._fetch_cache:
            # Nothing cached yet, so next poll will pull in latest bits,
            # so there's nothing to do
            return

        poollist = self._fetch_cache[self._FETCH_KEY_POOLS]
        poolxmlobj = self._build_pool_raw(poolobj)
        poollist.append(poolxmlobj)

        if self._FETCH_KEY_VOLS not in self._fetch_cache:
            return
        vollist = self._fetch_cache[self._FETCH_KEY_VOLS]
        vollist.extend(self._fetch_vols_raw(poolxmlobj))

    def cache_new_pool(self, poolobj):
        """
        Insert the passed poolobj into our cache
        """
        if self.cb_cache_new_pool:
            # pylint: disable=not-callable
            return self.cb_cache_new_pool(poolobj)
        return self._cache_new_pool_raw(poolobj)

    def fetch_all_domains(self):
        """
        Returns a list of Guest() objects
        """
        return self._fetch_helper(
                self._FETCH_KEY_DOMAINS,
                self._fetch_all_domains_raw,
                self.cb_fetch_all_domains)

    def fetch_all_pools(self):
        """
        Returns a list of StoragePool objects
        """
        return self._fetch_helper(
                self._FETCH_KEY_POOLS,
                self._fetch_all_pools_raw,
                self.cb_fetch_all_pools)

    def fetch_all_vols(self):
        """
        Returns a list of StorageVolume objects
        """
        return self._fetch_helper(
                self._FETCH_KEY_VOLS,
                self._fetch_all_vols_raw,
                self.cb_fetch_all_vols)

    def fetch_all_nodedevs(self):
        """
        Returns a list of NodeDevice() objects
        """
        return self._fetch_helper(
                self._FETCH_KEY_NODEDEVS,
                self._fetch_all_nodedevs_raw,
                self.cb_fetch_all_nodedevs)


    #########################
    # Libvirt API overrides #
    #########################

    def getURI(self):
        return self._uri


    #########################
    # Public version checks #
    #########################

    def local_libvirt_version(self):
        if self._fake_libvirt_version is not None:
            return self._fake_libvirt_version
        # This handles caching for us
        return _real_local_libvirt_version()

    def daemon_version(self):
        if self._fake_libvirt_version is not None:
            return self._fake_libvirt_version
        if not self.is_remote():
            return _real_local_libvirt_version()

        if self._daemon_version is None:
            self._daemon_version = 0
            try:
                self._daemon_version = self._libvirtconn.getLibVersion()
            except Exception:  # pragma: no cover
                log.debug("Error calling getLibVersion", exc_info=True)
        return self._daemon_version

    def conn_version(self):
        if self._fake_conn_version is not None:
            return self._fake_conn_version

        if self._conn_version is None:
            self._conn_version = 0
            try:
                self._conn_version = self._libvirtconn.getVersion()
            except Exception:  # pragma: no cover
                log.debug("Error calling getVersion", exc_info=True)
        return self._conn_version


    ###################
    # Public URI bits #
    ###################

    def is_remote(self):
        return bool(self._uriobj.hostname)
    def is_privileged(self):
        if self.get_uri_path() == "/session":
            return False
        if self.get_uri_path() == "/embed":
            return os.getuid() == 0
        return True
    def is_unprivileged(self):
        return not self.is_privileged()

    def get_uri_hostname(self):
        return self._uriobj.hostname
    def get_uri_port(self):
        return self._uriobj.port
    def get_uri_username(self):
        return self._uriobj.username
    def get_uri_transport(self):
        if self.get_uri_hostname() and not self._uriobj.transport:
            # Libvirt defaults to transport=tls if hostname specified but
            # no transport is specified
            return "tls"
        return self._uriobj.transport
    def get_uri_path(self):
        return self._uriobj.path

    def get_uri_driver(self):
        return self._uriobj.scheme

    def is_qemu(self):
        return self._uriobj.scheme.startswith("qemu")
    def is_qemu_privileged(self):
        return (self.is_qemu() and self.is_privileged())
    def is_qemu_unprivileged(self):
        return (self.is_qemu() and self.is_unprivileged())

    def is_really_test(self):
        return URI(self._open_uri).scheme.startswith("test")
    def is_test(self):
        return self._uriobj.scheme.startswith("test")
    def is_xen(self):
        return (self._uriobj.scheme.startswith("xen") or
                self._uriobj.scheme.startswith("libxl"))
    def is_lxc(self):
        return self._uriobj.scheme.startswith("lxc")
    def is_openvz(self):
        return self._uriobj.scheme.startswith("openvz")
    def is_container_only(self):
        return self.is_lxc() or self.is_openvz()
    def is_vz(self):
        return (self._uriobj.scheme.startswith("vz") or
                self._uriobj.scheme.startswith("parallels"))


    #########################
    # Support check helpers #
    #########################

    def support_remote_url_install(self):
        ret = self.support.conn_stream()
        if self._magic_uri or self.is_test():
            ret = False
        return self.in_testsuite() or ret

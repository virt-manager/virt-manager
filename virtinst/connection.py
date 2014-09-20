#
# Copyright 2013, 2014 Red Hat, Inc.
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

import logging
import re
import weakref

import libvirt

from . import pollhelpers
from . import support
from . import util
from . import capabilities as CapabilitiesParser
from .cli import VirtOptionString
from .guest import Guest
from .nodedev import NodeDevice
from .storage import StoragePool, StorageVolume

_virtinst_uri_magic = "__virtinst_test__"


def _sanitize_xml(xml):
    import difflib

    orig = xml
    xml = re.sub("arch=\".*\"", "arch=\"i686\"", xml)
    xml = re.sub("domain type=\".*\"", "domain type=\"test\"", xml)
    xml = re.sub("machine type=\".*\"", "", xml)
    xml = re.sub(">exe<", ">hvm<", xml)

    diff = "\n".join(difflib.unified_diff(orig.split("\n"),
                                          xml.split("\n")))
    if diff:
        logging.debug("virtinst test sanitizing diff\n:%s", diff)
    return xml


class VirtualConnection(object):
    """
    Wrapper for libvirt connection that provides various bits like
    - caching static data
    - lookup for API feature support
    - simplified API wrappers that handle new and old ways of doing things
    """
    def __init__(self, uri):
        self._initial_uri = uri or ""

        self._fake_pretty_name = None
        self._fake_libvirt_version = None
        self._fake_conn_version = None
        self._daemon_version = None
        self._conn_version = None

        if self._initial_uri.startswith(_virtinst_uri_magic):
            # virtinst unit test URI handling
            uri = self._initial_uri.replace(_virtinst_uri_magic, "")
            ret = uri.split(",", 1)
            self._open_uri = ret[0]
            self._test_opts = VirtOptionString(
                len(ret) > 1 and ret[1] or "", [], None).opts
            self._early_virtinst_test_uri()
            self._uri = self._virtinst_uri_make_fake()
        else:
            self._open_uri = self._initial_uri
            self._uri = self._initial_uri
            self._test_opts = {}

        self._libvirtconn = None
        self._urisplits = util.uri_split(self._uri)
        self._caps = None

        self._support_cache = {}
        self._fetch_cache = {}

        # Setting this means we only do fetch_all* once and just carry
        # the result. For the virt-* CLI tools this ensures any revalidation
        # isn't hammering the connection over and over
        self.cache_object_fetch = False

        # These let virt-manager register a callback which provides its
        # own cached object lists, rather than doing fresh calls
        self.cb_fetch_all_guests = None
        self.cb_fetch_all_pools = None
        self.cb_fetch_all_vols = None
        self.cb_fetch_all_nodedevs = None
        self.cb_clear_cache = None


    ##############
    # Properties #
    ##############

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]

        # Proxy virConnect API calls
        libvirtconn = self.__dict__.get("_libvirtconn")
        return getattr(libvirtconn, attr)

    def _get_uri(self):
        return self._uri or self._open_uri
    uri = property(_get_uri)

    def _get_caps(self):
        if not self._caps:
            self._caps = CapabilitiesParser.Capabilities(
                                        self._libvirtconn.getCapabilities())
        return self._caps
    caps = property(_get_caps)

    def get_conn_for_api_arg(self):
        return self._libvirtconn


    ##############
    # Public API #
    ##############

    def is_closed(self):
        return not bool(self._libvirtconn)

    def close(self):
        self._libvirtconn = None
        self._uri = None
        self._fetch_cache = {}

    def invalidate_caps(self):
        self._caps = None

    def is_open(self):
        return bool(self._libvirtconn)

    def open(self, passwordcb):
        open_flags = 0
        valid_auth_options = [libvirt.VIR_CRED_AUTHNAME,
                              libvirt.VIR_CRED_PASSPHRASE]
        authcb = self._auth_cb
        authcb_data = passwordcb

        conn = libvirt.openAuth(self._open_uri,
                    [valid_auth_options, authcb,
                    (authcb_data, valid_auth_options)],
                    open_flags)

        self._fixup_virtinst_test_uri(conn)
        self._libvirtconn = conn
        if not self._open_uri:
            self._uri = self._libvirtconn.getURI()
            self._urisplits = util.uri_split(self._uri)

    def set_keep_alive(self, interval, count):
        if hasattr(self._libvirtconn, "setKeepAlive"):
            self._libvirtconn.setKeepAlive(interval, count)


    ####################
    # Polling routines #
    ####################

    _FETCH_KEY_GUESTS = "vms"
    _FETCH_KEY_POOLS = "pools"
    _FETCH_KEY_VOLS = "vols"
    _FETCH_KEY_NODEDEVS = "nodedevs"

    def clear_cache(self, pools=False):
        if self.cb_clear_cache:
            self.cb_clear_cache(pools=pools)  # pylint: disable=not-callable
            return

        if pools:
            self._fetch_cache.pop(self._FETCH_KEY_POOLS, None)

    def _fetch_all_guests_cached(self):
        key = self._FETCH_KEY_GUESTS
        if key in self._fetch_cache:
            return self._fetch_cache[key]

        ignore, ignore, ret = pollhelpers.fetch_vms(self, {},
                                                    lambda obj, ignore: obj)
        ret = [Guest(weakref.ref(self), parsexml=obj.XMLDesc(0))
               for obj in ret.values()]
        if self.cache_object_fetch:
            self._fetch_cache[key] = ret
        return ret

    def fetch_all_guests(self):
        """
        Returns a list of Guest() objects
        """
        if self.cb_fetch_all_guests:
            return self.cb_fetch_all_guests()  # pylint: disable=not-callable
        return self._fetch_all_guests_cached()

    def _fetch_all_pools_cached(self):
        key = self._FETCH_KEY_POOLS
        if key in self._fetch_cache:
            return self._fetch_cache[key]

        ignore, ignore, ret = pollhelpers.fetch_pools(self, {},
                                                    lambda obj, ignore: obj)
        ret = [StoragePool(weakref.ref(self), parsexml=obj.XMLDesc(0))
               for obj in ret.values()]
        if self.cache_object_fetch:
            self._fetch_cache[key] = ret
        return ret

    def fetch_all_pools(self):
        """
        Returns a list of StoragePool objects
        """
        if self.cb_fetch_all_pools:
            return self.cb_fetch_all_pools()  # pylint: disable=not-callable
        return self._fetch_all_pools_cached()

    def _fetch_all_vols_cached(self):
        key = self._FETCH_KEY_VOLS
        if key in self._fetch_cache:
            return self._fetch_cache[key]

        ret = []
        for xmlobj in self.fetch_all_pools():
            pool = self._libvirtconn.storagePoolLookupByName(xmlobj.name)
            ignore, ignore, vols = pollhelpers.fetch_volumes(
                self, pool, {}, lambda obj, ignore: obj)

            for vol in vols.values():
                try:
                    xml = vol.XMLDesc(0)
                    ret.append(StorageVolume(weakref.ref(self), parsexml=xml))
                except Exception, e:
                    logging.debug("Fetching volume XML failed: %s", e)

        if self.cache_object_fetch:
            self._fetch_cache[key] = ret
        return ret

    def fetch_all_vols(self):
        """
        Returns a list of StorageVolume objects
        """
        if self.cb_fetch_all_vols:
            return self.cb_fetch_all_vols()  # pylint: disable=not-callable
        return self._fetch_all_vols_cached()

    def _fetch_all_nodedevs_cached(self):
        key = self._FETCH_KEY_NODEDEVS
        if key in self._fetch_cache:
            return self._fetch_cache[key]

        ignore, ignore, ret = pollhelpers.fetch_nodedevs(
            self, {}, lambda obj, ignore: obj)
        ret = [NodeDevice.parse(weakref.ref(self), obj.XMLDesc(0))
               for obj in ret.values()]
        if self.cache_object_fetch:
            self._fetch_cache[key] = ret
        return ret

    def fetch_all_nodedevs(self):
        """
        Returns a list of NodeDevice() objects
        """
        if self.cb_fetch_all_nodedevs:
            return self.cb_fetch_all_nodedevs()  # pylint: disable=not-callable
        return self._fetch_all_nodedevs_cached()


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
        return util.local_libvirt_version()

    def daemon_version(self):
        if self._fake_libvirt_version is not None:
            return self._fake_libvirt_version
        if not self.is_remote():
            return self.local_libvirt_version()

        if not self._daemon_version:
            if not self.check_support(support.SUPPORT_CONN_LIBVERSION):
                self._daemon_version = 0
            else:
                self._daemon_version = self._libvirtconn.getLibVersion()
        return self._daemon_version

    def conn_version(self):
        if self._fake_conn_version is not None:
            return self._fake_conn_version

        if not self._conn_version:
            if not self.check_support(support.SUPPORT_CONN_GETVERSION):
                self._conn_version = 0
            else:
                self._conn_version = self._libvirtconn.getVersion()
        return self._conn_version


    ###################
    # Public URI bits #
    ###################

    def fake_name(self):
        return self._fake_pretty_name

    def is_remote(self):
        return (hasattr(self, "_virtinst__fake_conn_remote") or
            self._urisplits[2])

    def get_uri_hostname(self):
        return self._urisplits[2] or "localhost"

    def get_uri_host_port(self):
        hostname = self.get_uri_hostname()
        port = None

        if hostname.startswith("[") and "]" in hostname:
            if "]:" in hostname:
                hostname, port = hostname.rsplit(":", 1)
            hostname = "".join(hostname[1:].split("]", 1))
        elif ":" in hostname:
            hostname, port = hostname.split(":", 1)
        return hostname, port

    def get_uri_transport(self):
        scheme = self._urisplits[0]
        username = self._urisplits[1]
        offset = scheme.find("+")
        if offset != -1:
            return [scheme[offset + 1:], username]
        return [None, None]

    def get_uri_driver(self):
        scheme = self._urisplits[0]
        offset = scheme.find("+")
        if offset > 0:
            return scheme[:offset]
        return scheme

    def is_session_uri(self):
        return self._urisplits[3] == "/session"
    def is_qemu(self):
        return self._urisplits[0].startswith("qemu")
    def is_qemu_system(self):
        return (self.is_qemu() and self._urisplits[3] == "/system")
    def is_qemu_session(self):
        return (self.is_qemu() and self.is_session_uri())

    def is_test(self):
        return self._urisplits[0].startswith("test")
    def is_xen(self):
        return (self._urisplits[0].startswith("xen") or
                self._urisplits[0].startswith("libxl"))
    def is_lxc(self):
        return self._urisplits[0].startswith("lxc")
    def is_openvz(self):
        return self._urisplits[0].startswith("openvz")
    def is_container(self):
        return self.is_lxc() or self.is_openvz()


    #########################
    # Support check helpers #
    #########################

    for _supportname in [_supportname for _supportname in dir(support) if
                         _supportname.startswith("SUPPORT_")]:
        locals()[_supportname] = getattr(support, _supportname)

    def check_support(self, feature, data=None):
        key = feature
        data = data or self
        if key not in self._support_cache:
            self._support_cache[key] = support.check_support(
                self, feature, data)
        return self._support_cache[key]

    def support_remote_url_install(self):
        if hasattr(self, "_virtinst__fake_conn"):
            return False
        return (self.check_support(self.SUPPORT_CONN_STREAM) and
                self.check_support(self.SUPPORT_STREAM_UPLOAD))


    ###################
    # Private helpers #
    ###################

    def _auth_cb(self, creds, (passwordcb, passwordcreds)):
        for cred in creds:
            if cred[0] not in passwordcreds:
                raise RuntimeError("Unknown cred type '%s', expected only "
                                   "%s" % (cred[0], passwordcreds))
        return passwordcb(creds)

    def _virtinst_uri_make_fake(self):
        if "qemu" in self._test_opts:
            return "qemu+abc:///system"
        elif "xen" in self._test_opts:
            return "xen+abc:///"
        elif "lxc" in self._test_opts:
            return "lxc+abc:///"
        return self._open_uri

    def _early_virtinst_test_uri(self):
        # Need tmpfile names to be deterministic
        if not self._test_opts:
            return
        opts = self._test_opts

        if "predictable" in opts:
            opts.pop("predictable")
            setattr(self, "_virtinst__fake_conn_predictable", True)

        # Fake remote status
        if "remote" in opts:
            opts.pop("remote")
            setattr(self, "_virtinst__fake_conn_remote", True)

        if "prettyname" in opts:
            self._fake_pretty_name = opts.pop("prettyname")


    def _fixup_virtinst_test_uri(self, conn):
        """
        This hack allows us to fake various drivers via passing a magic
        URI string to virt-*. Helps with testing
        """
        if not self._test_opts:
            return
        opts = self._test_opts.copy()

        # Fake capabilities
        if "caps" in opts:
            capsxml = file(opts.pop("caps")).read()
            conn.getCapabilities = lambda: capsxml

        if ("qemu" in opts) or ("xen" in opts) or ("lxc" in opts):
            opts.pop("qemu", None)
            opts.pop("xen", None)
            opts.pop("lxc", None)

            self._fake_conn_version = 10000000000

            origcreate = conn.createLinux
            origdefine = conn.defineXML
            def newcreate(xml, flags):
                xml = _sanitize_xml(xml)
                return origcreate(xml, flags)
            def newdefine(xml):
                xml = _sanitize_xml(xml)
                return origdefine(xml)
            conn.createLinux = newcreate
            conn.defineXML = newdefine

        # These need to come after the HV setter, since that sets a default
        # conn version
        if "connver" in opts:
            self._fake_conn_version = int(opts.pop("connver"))
        if "libver" in opts:
            self._fake_libvirt_version = int(opts.pop("libver"))

        if opts:
            raise RuntimeError("Unhandled virtinst test uri options %s" % opts)

        setattr(self, "_virtinst__fake_conn", True)

#
# Copyright 2013  Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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
import os
import re

import libvirt

from virtinst import pollhelpers
from virtinst import support
from virtinst import util
from virtinst import CapabilitiesParser
from virtinst.cli import parse_optstr

_virtinst_uri_magic = "__virtinst_test__"


class VirtualConnection(object):
    """
    Wrapper for libvirt connection that provides various bits like
    - caching static data
    - lookup for API feature support
    - simplified API wrappers that handle new and old ways of doing things
    """
    def __init__(self, uri):
        self._initial_uri = uri or ""

        # virtinst unit test URI handling
        if self._initial_uri.startswith(_virtinst_uri_magic):
            uri = self._initial_uri.replace(_virtinst_uri_magic, "")
            ret = uri.split(",", 1)
            self._open_uri = ret[0]
            self._test_opts = parse_optstr(len(ret) > 1 and ret[1] or "")
            self._uri = self._virtinst_uri_make_fake()
        else:
            self._open_uri = self._initial_uri
            self._uri = self._initial_uri
            self._test_opts = {}

        self._libvirtconn = None
        self._urisplits = util.uri_split(self._uri)
        self._caps = None

        self._fake_libvirt_version = None
        self._fake_conn_version = None
        self._daemon_version = None
        self._conn_version = None

        self._support_cache = {}


    ##############
    # Properties #
    ##############

    # Proxy virConnect API calls
    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        libvirtconn = self.__dict__.get("_libvirtconn")
        return getattr(libvirtconn, attr)

    def _get_uri(self):
        return self._uri or self._open_uri
    uri = property(_get_uri)

    libvirtconn = property(lambda self: getattr(self, "_libvirtconn"))

    def _get_caps(self):
        if not self._caps:
            self._caps = CapabilitiesParser.Capabilities(
                                        self.libvirtconn.getCapabilities())
        return self._caps
    caps = property(_get_caps)


    ##############
    # Public API #
    ##############

    def close(self):
        self._libvirtconn = None
        self._uri = None

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

    def fetch_all_guests(self):
        ignore, ignore, ret = pollhelpers.fetch_vms(self, {},
                                                    lambda obj, ignore: obj)
        return ret.values()

    def fetch_all_pools(self):
        ignore, ignore, ret = pollhelpers.fetch_pools(self, {},
                                                    lambda obj, ignore: obj)
        return ret.values()


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
            if not self.check_conn_support(support.SUPPORT_CONN_LIBVERSION):
                self._daemon_version = 0
            else:
                self._daemon_version = self.libvirtconn.getLibVersion()
        return self._daemon_version

    def conn_version(self):
        if self._fake_conn_version is not None:
            return self._fake_conn_version

        if not self._conn_version:
            if not self.check_conn_support(support.SUPPORT_CONN_GETVERSION):
                self._conn_version = 0
            else:
                self._conn_version = self.libvirtconn.getVersion()
        return self._conn_version


    ###################
    # Public URI bits #
    ###################

    def is_remote(self):
        if (hasattr(self, "_virtinst__fake_conn_remote") or
            self._urisplits[2]):
            return True

    def get_uri_hostname(self):
        return self._urisplits[2] or "localhost"

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

    def check_conn_support(self, feature):
        key = feature
        if key not in self._support_cache:
            self._support_cache[key] = support.check_support(self,
                                                             feature, self)
        return self._support_cache[key]
    def check_conn_hv_support(self, feature, hv):
        key = (feature, hv)
        if key not in self._support_cache:
            self._support_cache[key] = support.check_support(self, feature, hv)
        return self._support_cache[key]
    def check_domain_support(self, dom, feature):
        return support.check_support(self, feature, dom)
    def check_pool_support(self, pool, feature):
        return support.check_support(self, feature, pool)
    def check_nodedev_support(self, nodedev, feature):
        return support.check_support(self, feature, nodedev)
    def check_interface_support(self, iface, feature):
        return support.check_support(self, feature, iface)
    def check_stream_support(self, feature):
        return (self.check_conn_support(self.SUPPORT_CONN_STREAM) and
                support.check_support(self, feature, self))
    def check_net_support(self, net, feature):
        return support.check_support(self, feature, net)


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

    def _fixup_virtinst_test_uri(self, conn):
        """
        This hack allows us to fake various drivers via passing a magic
        URI string to virt-*. Helps with testing
        """
        if not self._test_opts:
            return
        opts = self._test_opts.copy()

        def sanitize_xml(xml):
            import difflib

            orig = xml
            xml = re.sub("arch='.*'", "arch='i686'", xml)
            xml = re.sub("domain type='.*'", "domain type='test'", xml)
            xml = re.sub("machine type='.*'", "", xml)
            xml = re.sub(">exe<", ">hvm<", xml)

            logging.debug("virtinst test sanitizing diff\n:%s",
                          "\n".join(difflib.unified_diff(orig.split("\n"),
                                                         xml.split("\n"))))
            return xml

        # Need tmpfile names to be deterministic
        if "predictable" in opts:
            opts.pop("predictable")
            import tempfile
            setattr(self, "_virtinst__fake_conn_predictable", True)

            def fakemkstemp(prefix, *args, **kwargs):
                ignore = args
                ignore = kwargs
                filename = os.path.join(".", prefix)
                return os.open(filename, os.O_RDWR | os.O_CREAT), filename
            tempfile.mkstemp = fakemkstemp

        # Fake remote status
        if "remote" in opts:
            opts.pop("remote")
            setattr(self, "_virtinst__fake_conn_remote", True)

        # Fake capabilities
        if "caps" in opts:
            capsxml = file(opts.pop("caps")).read()
            conn.getCapabilities = lambda: capsxml

        if ("qemu" in opts) or ("xen" in opts) or ("lxc" in opts):
            opts.pop("qemu", None)
            opts.pop("xen", None)
            opts.pop("lxc", None)

            self._fake_conn_version = 10000000000
            conn.getURI = self._virtinst_uri_make_fake

            origcreate = conn.createLinux
            origdefine = conn.defineXML
            def newcreate(xml, flags):
                xml = sanitize_xml(xml)
                return origcreate(xml, flags)
            def newdefine(xml):
                xml = sanitize_xml(xml)
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

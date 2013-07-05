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
        self._uri = uri
        self._libvirtconn = None

        self.is_virtinst_test_uri = uri and uri.startswith(_virtinst_uri_magic)


    # Just proxy virConnect access for now
    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        libvirtconn = self.__dict__.get("_libvirtconn")
        return getattr(libvirtconn, attr)


    ##############
    # Properties #
    ##############

    uri = property(lambda self: getattr(self, "_uri"))
    libvirtconn = property(lambda self: getattr(self, "_libvirtconn"))


    ##############
    # Public API #
    ##############

    def close(self):
        self._libvirtconn = None

    def is_open(self):
        return bool(self._libvirtconn)

    def open(self, passwordcb):
        open_flags = 0
        valid_auth_options = [libvirt.VIR_CRED_AUTHNAME,
                              libvirt.VIR_CRED_PASSPHRASE]
        authcb = self._auth_cb
        authcb_data = passwordcb

        testopts = []
        uri = self.uri
        if self.is_virtinst_test_uri:
            uri = uri.replace(_virtinst_uri_magic, "")
            ret = uri.split(",", 1)
            uri = ret[0]
            testopts = parse_optstr(len(ret) > 1 and ret[1] or "")

        conn = libvirt.openAuth(uri,
                    [valid_auth_options, authcb,
                    (authcb_data, valid_auth_options)],
                    open_flags)

        if testopts:
            self._fixup_virtinst_test_uri(conn, testopts)
        self._libvirtconn = conn




    ###################
    # Private helpers #
    ###################

    def _auth_cb(self, creds, (passwordcb, passwordcreds)):
        for cred in creds:
            if cred[0] not in passwordcreds:
                raise RuntimeError("Unknown cred type '%s', expected only "
                                   "%s" % (cred[0], passwordcreds))
        return passwordcb(creds)

    def _fixup_virtinst_test_uri(self, conn, opts):
        """
        This hack allows us to fake various drivers via passing a magic
        URI string to virt-*. Helps with testing
        """
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
            conn.getVersion = lambda: 10000000000

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

            if "qemu" in opts:
                opts.pop("qemu")
                conn.getURI = lambda: "qemu+abc:///system"
            if "xen" in opts:
                opts.pop("xen")
                conn.getURI = lambda: "xen+abc:///"
            if "lxc" in opts:
                opts.pop("lxc")
                conn.getURI = lambda: "lxc+abc:///"

        # These need to come after the HV setter, since that sets a default
        # conn version
        if "connver" in opts:
            ver = int(opts.pop("connver"))
            def newconnversion():
                return ver
            conn.getVersion = newconnversion

        if "libver" in opts:
            ver = int(opts.pop("libver"))
            def newlibversion(drv=None):
                if drv:
                    return (ver, ver)
                return ver
            libvirt.getVersion = newlibversion

        if opts:
            raise RuntimeError("Unhandled virtinst test uri options %s" % opts)

        setattr(self, "_virtinst__fake_conn", True)

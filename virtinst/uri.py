#
# Copyright 2014 Red Hat, Inc.
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
import re

from .cli import parse_optstr_tuples


def sanitize_xml_for_test_define(xml):
    import difflib

    orig = xml
    xml = re.sub("arch=\".*\"", "arch=\"i686\"", xml)
    xml = re.sub("domain type=\".*\"", "domain type=\"test\"", xml)
    xml = re.sub("machine type=\".*\"", "", xml)
    xml = re.sub(">exe<", ">hvm<", xml)
    xml = re.sub(">linux<", ">xen<", xml)

    diff = "\n".join(difflib.unified_diff(orig.split("\n"),
                                          xml.split("\n")))
    if diff:
        logging.debug("virtinst test sanitizing diff\n:%s", diff)
    return xml


class URI(object):
    """
    Parse an arbitrary URI into its individual parts
    """
    def __init__(self, uri):
        self.uri = uri

        (self.scheme, self.username, self.hostname,
         self.path, self.query, self.fragment) = self._split(self.uri)

        self.transport = ''
        if "+" in self.scheme:
            self.scheme, self.transport = self.scheme.rsplit("+", 1)

        self.port = ''
        self.is_ipv6 = False
        if self.hostname.startswith("[") and "]" in self.hostname:
            if "]:" in self.hostname:
                self.hostname, self.port = self.hostname.rsplit(":", 1)
            self.hostname = "".join(self.hostname[1:].split("]", 1))
            self.is_ipv6 = True
        elif ":" in self.hostname:
            self.hostname, self.port = self.hostname.split(":", 1)

        self.host_is_ipv4_string = bool(re.match("^[0-9.]+$", self.hostname))


    ###################
    # Private helpers #
    ###################

    def _split(self, uri):
        def splitnetloc(url, start=0):
            for c in '/?#':  # the order is important!
                delim = url.find(c, start)
                if delim >= 0:
                    break
            else:
                delim = len(url)
            return url[start:delim], url[delim:]

        scheme = username = netloc = query = fragment = ''
        i = uri.find(":")
        if i > 0:
            scheme, uri = uri[:i].lower(), uri[i + 1:]
            if uri[:2] == '//':
                netloc, uri = splitnetloc(uri, 2)
                offset = netloc.find("@")
                if offset > 0:
                    username = netloc[0:offset]
                    netloc = netloc[offset + 1:]
            if '#' in uri:
                uri, fragment = uri.split('#', 1)
            if '?' in uri:
                uri, query = uri.split('?', 1)
        return scheme, username, netloc, uri, query, fragment


class MagicURI(object):
    """
    Handle magic virtinst URIs we use for the test suite and UI testing.
    This allows a special URI to override various features like capabilities
    XML, reported connection and libvirt versions, that enable testing
    different code paths.

    A magic URI has 3 parts:

        1) Magic prefix __virtinst_test__
        2) Actual openable URI, usually a test:/// URI
        3) Comma separated options

    The available options are:

        * 'predictable': Generate predictable UUIDs, MAC addresses, and
            temporary file names.
        * 'remote': Have the code consider this as a remote URI
        * 'session': Have the code consider this as a session URI
        * 'connver=%d': Override the connection (hv) version
        * 'libver=%d': Override the libvirt version
        * 'caps=%s': Points to a file with capabilities XML, that will
                     be returned in conn.getCapabilities. Ex.
                     files in test/capabilities-xml/
        * 'domcaps=%s': Points to a file with domain capabilities XML, that
                        will be returned in conn.getDomainCapabilities
        * qemu or xen or lxc: Fake the specified hypervisor

    See tests/utils.py for example URLs
    """
    VIRTINST_URI_MAGIC_PREFIX = "__virtinst_test__"

    @staticmethod
    def uri_is_magic(uri):
        return uri.startswith(MagicURI.VIRTINST_URI_MAGIC_PREFIX)

    def __init__(self, uri):
        if not self.uri_is_magic(uri):
            raise RuntimeError("uri=%s is not virtinst magic URI" % uri)

        uri = uri.replace(self.VIRTINST_URI_MAGIC_PREFIX, "")
        ret = uri.split(",", 1)
        self.open_uri = ret[0]
        opts = dict(parse_optstr_tuples(len(ret) > 1 and ret[1] or ""))

        def pop_bool(field):
            ret = field in opts
            opts.pop(field, None)
            return ret

        self.predictable = pop_bool("predictable")
        self.remote = pop_bool("remote")
        self.session = pop_bool("session")
        self.capsfile = opts.pop("caps", None)
        self.domcapsfile = opts.pop("domcaps", None)

        self.hv = None
        if pop_bool("qemu"):
            self.hv = "qemu"
        if pop_bool("lxc"):
            self.hv = "lxc"
        if pop_bool("xen"):
            self.hv = "xen"

        self.conn_version = opts.pop("connver", None)
        if self.conn_version:
            self.conn_version = int(self.conn_version)
        elif self.hv:
            self.conn_version = 10000000000

        self.libvirt_version = opts.pop("libver", None)
        if self.libvirt_version:
            self.libvirt_version = int(self.libvirt_version)

        if opts:
            raise RuntimeError("Unhandled virtinst test uri options %s" % opts)


    ##############
    # Public API #
    ##############

    def make_fake_uri(self):
        """
        If self.hv is set, we need to make a fake URI so that Connection
        URI handling bits have something to work with.
        """
        if self.hv:
            return self.hv + "+abc:///system"
        return self.open_uri

    def overwrite_conn_functions(self, conn):
        """
        After the connection is open, we need to stub out various functions
        depending on what magic bits the user specified in the URI
        """
        # Fake capabilities
        if self.capsfile:
            capsxml = file(self.capsfile).read()
            conn.getCapabilities = lambda: capsxml

        # Fake domcapabilities. This is insufficient since output should
        # vary per type/arch/emulator combo, but it can be expanded later
        # if needed
        if self.domcapsfile:
            domcapsxml = file(self.domcapsfile).read()
            def fake_domcaps(emulator, arch, machine, virttype, flags=0):
                ignore = emulator
                ignore = flags
                ignore = machine
                ignore = virttype

                ret = domcapsxml
                if arch:
                    ret = re.sub("arch>.+</arch", "arch>%s</arch" % arch, ret)
                return ret

            conn.getDomainCapabilities = fake_domcaps

        if self.hv:
            origcreate = conn.createXML
            origdefine = conn.defineXML
            def newcreate(xml, flags):
                xml = sanitize_xml_for_test_define(xml)
                return origcreate(xml, flags)
            def newdefine(xml):
                xml = sanitize_xml_for_test_define(xml)
                return origdefine(xml)
            conn.createXML = newcreate
            conn.defineXML = newdefine

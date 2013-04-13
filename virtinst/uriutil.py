#
# Copyright 2006-2013  Red Hat, Inc.
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
#

import logging


def uri_split(uri):
    """
    Parse a libvirt hypervisor uri into it's individual parts
    @returns: tuple of the form (scheme (ex. 'qemu', 'xen+ssh'), username,
                                 hostname, path (ex. '/system'), query,
                                 fragment)
    """
    def splitnetloc(url, start=0):
        for c in '/?#':  # the order is important!
            delim = url.find(c, start)
            if delim >= 0:
                break
        else:
            delim = len(url)
        return url[start:delim], url[delim:]

    username = netloc = query = fragment = ''
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
    else:
        scheme = uri.lower()
    return scheme, username, netloc, uri, query, fragment


def is_uri_remote(uri, conn=None):
    if conn and hasattr(conn, "_virtinst__fake_conn_remote"):
        # Testing hack
        return True

    try:
        split_uri = uri_split(uri)
        netloc = split_uri[2]

        if netloc == "":
            return False
        return True
    except Exception, e:
        logging.exception("Error parsing URI in is_remote: %s", e)
        return True


def get_uri_hostname(uri):
    try:
        split_uri = uri_split(uri)
        netloc = split_uri[2]

        if netloc != "":
            return netloc
    except Exception, e:
        logging.warning("Cannot parse URI %s: %s", uri, str(e))
    return "localhost"


def get_uri_transport(uri):
    try:
        split_uri = uri_split(uri)
        scheme = split_uri[0]
        username = split_uri[1]

        if scheme:
            offset = scheme.index("+")
            if offset > 0:
                return [scheme[offset + 1:], username]
    except:
        pass
    return [None, None]


def get_uri_driver(uri):
    try:
        split_uri = uri_split(uri)
        scheme = split_uri[0]

        if scheme:
            offset = scheme.find("+")
            if offset > 0:
                return scheme[:offset]
            return scheme
    except Exception:
        pass
    return "xen"


def _get_uri_to_split(conn, uri):
    if not conn and not uri:
        return None

    if type(conn) is str:
        uri = conn
    elif uri is None:
        uri = conn.getURI()
    return uri


def is_qemu_system(conn, uri=None):
    uri = _get_uri_to_split(conn, uri)
    if not uri:
        return False

    (scheme, ignore, ignore,
     path, ignore, ignore) = uri_split(uri)
    if path == "/system" and scheme.startswith("qemu"):
        return True
    return False


def is_session_uri(conn, uri=None):
    uri = _get_uri_to_split(conn, uri)
    if not uri:
        return False

    (ignore, ignore, ignore,
     path, ignore, ignore) = uri_split(uri)
    return bool(path and path == "/session")


def is_qemu(conn, uri=None):
    uri = _get_uri_to_split(conn, uri)
    if not uri:
        return False

    scheme = uri_split(uri)[0]
    return scheme.startswith("qemu")


def is_xen(conn, uri=None):
    uri = _get_uri_to_split(conn, uri)
    if not uri:
        return False

    scheme = uri_split(uri)[0]
    return scheme.startswith("xen")

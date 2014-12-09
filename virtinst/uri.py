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

import re


class URISplit(object):
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

        self.host_is_ipv4_string = bool(re.match(self.hostname, "[0-9.]+"))


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


    ##############
    # Public API #
    ##############

    def rebuild_uri(self):
        ret = self.scheme
        if self.transport:
            ret += "+" % self.transport
        ret += "://"
        if self.username:
            ret += self.username + "@"
        if self.hostname:
            host = self.hostname
            if self.is_ipv6:
                host = "[%s]" % self.hostname
            ret += host
            if self.port:
                ret += ":" + self.port
        if self.query:
            ret += "?" + self.query
        if self.fragment:
            ret += "#" + self.fragment
        return ret

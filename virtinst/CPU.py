#
# Copyright 2010  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

import XMLBuilderDomain
from XMLBuilderDomain import _xml_property

import libxml2

def _int_or_none(val):
    return val and int(val) or val

class CPUFeature(XMLBuilderDomain.XMLBuilderDomain):
    """
    Class for generating <cpu> child <feature> XML
    """

    POLICIES = ["force", "require", "optional", "disable", "forbid"]

    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None):
        XMLBuilderDomain.XMLBuilderDomain.__init__(self, conn, parsexml,
                                                   parsexmlnode, caps)

        self._name = None
        self._policy = None

        if self._is_parse():
            return

    def _get_name(self):
        return self._name
    def _set_name(self, val):
        self._name = val
    name = _xml_property(_get_name, _set_name,
                         xpath="./@name")

    def _get_policy(self):
        return self._policy
    def _set_policy(self, val):
        self._policy = val
    policy = _xml_property(_get_policy, _set_policy,
                           xpath="./@policy")

    def _get_xml_config(self):
        if not self.name:
            return ""

        xml = "    <feature"
        if self.policy:
            xml += " policy='%s'" % self.policy
        xml += " name='%s'/>" % self.name

        return xml


class CPU(XMLBuilderDomain.XMLBuilderDomain):
    """
    Class for generating <cpu> XML
    """

    _dumpxml_xpath = "/domain/cpu"

    MATCHS = ["minimum", "exact", "strict"]

    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None):
        self._model = None
        self._match = None
        self._vendor = None
        self._features = []

        self._sockets = None
        self._cores = None
        self._threads = None

        XMLBuilderDomain.XMLBuilderDomain.__init__(self, conn, parsexml,
                                                   parsexmlnode, caps)
        if self._is_parse():
            return

    def _parsexml(self, xml, node):
        XMLBuilderDomain.XMLBuilderDomain._parsexml(self, xml, node)

        for node in self._xml_node.children:
            if node.name != "feature":
                continue
            feature = CPUFeature(self.conn, parsexmlnode=node)
            self._features.append(feature)

    def _get_features(self):
        return self._features[:]
    features = _xml_property(_get_features)

    def add_feature(self, name, policy="require"):
        feature = CPUFeature(self.conn)
        feature.name = name
        feature.policy = policy

        if self._is_parse():
            xml = feature.get_xml_config()
            node = libxml2.parseDoc(xml).children
            feature.set_xml_node(node)
            self._add_child_node("./cpu", node)

        self._features.append(feature)

    def remove_feature(self, feature):
        if self._is_parse() and feature in self._features:
            xpath = feature.get_xml_node_path()
            if xpath:
                self._remove_child_xpath(xpath)

        self._features.remove(feature)


    def _get_model(self):
        return self._model
    def _set_model(self, val):
        if val and not self.match:
            self.match = "exact"
        self._model = val
    model = _xml_property(_get_model, _set_model,
                          xpath="./cpu/model")

    def _get_match(self):
        return self._match
    def _set_match(self, val):
        self._match = val
    match = _xml_property(_get_match, _set_match,
                          xpath="./cpu/@match")

    def _get_vendor(self):
        return self._vendor
    def _set_vendor(self, val):
        self._vendor = val
    vendor = _xml_property(_get_vendor, _set_vendor,
                           xpath="./cpu/vendor")

    # Topology properties
    def _get_sockets(self):
        return self._sockets
    def _set_sockets(self, val):
        self._sockets = _int_or_none(val)
    sockets = _xml_property(_get_sockets, _set_sockets,
                            get_converter=lambda s, x: _int_or_none(x),
                            xpath="./cpu/topology/@sockets")

    def _get_cores(self):
        return self._cores
    def _set_cores(self, val):
        self._cores = _int_or_none(val)
    cores = _xml_property(_get_cores, _set_cores,
                          get_converter=lambda s, x: _int_or_none(x),
                          xpath="./cpu/topology/@cores")

    def _get_threads(self):
        return self._threads
    def _set_threads(self, val):
        self._threads = _int_or_none(val)
    threads = _xml_property(_get_threads, _set_threads,
                            get_converter=lambda s, x: _int_or_none(x),
                            xpath="./cpu/topology/@threads")

    def copy_host_cpu(self):
        """
        Enact the equivalent of qemu -cpu host, pulling all info
        from capabilities about the host CPU
        """
        cpu = self._get_caps().host.cpu
        if not cpu.model:
            raise ValueError(_("No host CPU reported in capabilities"))

        self.match = "exact"
        self.model = cpu.model
        self.vendor = cpu.vendor

        for feature in self.features:
            self.remove_feature(feature)
        for name in cpu.features.names():
            self.add_feature(name)

    def vcpus_from_topology(self):
        """
        Determine the CPU count represented by topology, or 1 if
        no topology is set
        """
        self.set_topology_defaults()
        if self.sockets:
            return self.sockets * self.cores * self.threads
        return 1

    def set_topology_defaults(self, vcpus=None):
        """
        Fill in unset topology values, using the passed vcpus count if
        required
        """
        if (self.sockets is None and
            self.cores is None and
            self.threads is None):
            return

        if vcpus is None:
            if self.sockets is None:
                self.sockets = 1
            if self.threads is None:
                self.threads = 1
            if self.cores is None:
                self.cores = 1

        vcpus = int(vcpus or 0)
        if not self.sockets:
            if not self.cores:
                self.sockets = vcpus / self.threads
            else:
                self.sockets = vcpus / self.cores

        if not self.cores:
            if not self.threads:
                self.cores = vcpus / self.sockets
            else:
                self.cores = vcpus / (self.sockets * self.threads)

        if not self.threads:
            self.threads = vcpus / (self.sockets * self.cores)

        return

    def _get_topology_xml(self):
        xml = ""
        if self.sockets:
            xml += " sockets='%s'" % self.sockets
        if self.cores:
            xml += " cores='%s'" % self.cores
        if self.threads:
            xml += " threads='%s'" % self.threads

        if not xml:
            return ""
        return "    <topology%s/>\n" % xml

    def _get_feature_xml(self):
        xml = ""
        for feature in self._features:
            xml += feature.get_xml_config() + "\n"
        return xml

    def _get_xml_config(self):
        top_xml = self._get_topology_xml()
        feature_xml = self._get_feature_xml()
        match_xml = ""
        if self.match:
            match_xml = " match='%s'" % self.match
        xml = ""

        if not (self.model or top_xml or feature_xml):
            return ""

        # Simple topology XML mode
        xml += "  <cpu%s>\n" % match_xml
        if self.model:
            xml += "    <model>%s</model>\n" % self.model
        if self.vendor:
            xml += "    <vendor>%s</vendor>\n" % self.vendor
        if top_xml:
            xml += top_xml
        if feature_xml:
            xml += feature_xml

        xml += "  </cpu>"
        return xml

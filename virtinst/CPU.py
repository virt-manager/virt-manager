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

from virtinst.xmlbuilder import XMLBuilder, XMLProperty


class CPUFeature(XMLBuilder):
    """
    Class for generating <cpu> child <feature> XML
    """

    POLICIES = ["force", "require", "optional", "disable", "forbid"]

    _XML_ROOT_XPATH = "/domain/cpu/feature"
    _XML_PROP_ORDER = ["_xmlname", "policy"]

    def __init__(self, conn, name, parsexml=None, parsexmlnode=None):
        XMLBuilder.__init__(self, conn, parsexml, parsexmlnode)

        self._name = name
        self._xmlname = name

    def _get_name(self):
        return self._xmlname
    name = property(_get_name)

    def _name_xpath(self):
        return "./cpu/feature[@name='%s']/@name" % self._name
    _xmlname = XMLProperty(name="feature name",
                      make_getter_xpath_cb=_name_xpath,
                      make_setter_xpath_cb=_name_xpath)
    def _policy_xpath(self):
        return "./cpu/feature[@name='%s']/@policy" % self._name
    policy = XMLProperty(name="feature policy",
                         make_getter_xpath_cb=_policy_xpath,
                         make_setter_xpath_cb=_policy_xpath)


class CPU(XMLBuilder):
    """
    Class for generating <cpu> XML
    """

    MATCHS = ["minimum", "exact", "strict"]

    _XML_ROOT_XPATH = "/domain/cpu"
    _XML_PROP_ORDER = ["mode", "match", "model", "vendor",
                       "sockets", "cores", "threads", "_features"]

    def __init__(self, conn, parsexml=None, parsexmlnode=None):
        self._features = []
        XMLBuilder.__init__(self, conn, parsexml, parsexmlnode)

    def _parsexml(self, xml, node):
        XMLBuilder._parsexml(self, xml, node)

        for node in self._xml_node.children or []:
            if node.name != "feature":
                continue
            if not node.prop("name"):
                continue
            feature = CPUFeature(self.conn, node.prop("name"),
                                 parsexmlnode=self._xml_node)
            self._features.append(feature)

    def add_feature(self, name, policy="require"):
        feature = CPUFeature(self.conn, name, parsexmlnode=self._xml_node)
        feature.policy = policy
        self._features.append(feature)

    def remove_feature(self, feature):
        self._features.remove(feature)
        feature.clear()

    def _get_features(self):
        return self._features[:]
    features = property(_get_features)

    def copy_host_cpu(self):
        """
        Enact the equivalent of qemu -cpu host, pulling all info
        from capabilities about the host CPU
        """
        cpu = self.conn.caps.host.cpu
        if not cpu.model:
            raise ValueError(_("No host CPU reported in capabilities"))

        self.mode = "custom"
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


    ##################
    # XML properties #
    ##################

    def _set_model(self, val):
        if val:
            self.mode = "custom"
            if not self.match:
                self.match = "exact"
        return val
    model = XMLProperty(xpath="./cpu/model", set_converter=_set_model)

    match = XMLProperty(xpath="./cpu/@match")
    vendor = XMLProperty(xpath="./cpu/vendor")
    mode = XMLProperty(xpath="./cpu/@mode")

    sockets = XMLProperty(xpath="./cpu/topology/@sockets", is_int=True)
    cores = XMLProperty(xpath="./cpu/topology/@cores", is_int=True)
    threads = XMLProperty(xpath="./cpu/topology/@threads", is_int=True)

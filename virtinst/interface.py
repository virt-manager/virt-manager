#
# Copyright 2009, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
"""
Classes for building and installing libvirt interface xml
"""

from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _BondConfig(XMLBuilder):
    XML_NAME = "bond"


class _BridgeConfig(XMLBuilder):
    XML_NAME = "bridge"


class _VLANConfig(XMLBuilder):
    XML_NAME = "vlan"


class Interface(XMLBuilder):
    """
    Base class for parsing any libvirt virInterface object XML
    """

    XML_NAME = "interface"
    _XML_PROP_ORDER = ["type", "name", "_bond", "_bridge", "_vlan"]

    ######################
    # Interface handling #
    ######################

    # The recursive nature of nested interfaces complicates things here,
    # which is why this is strange. See bottom of the file for more
    # weirdness

    _bond = XMLChildProperty(_BondConfig, is_single=True)
    _bridge = XMLChildProperty(_BridgeConfig, is_single=True)
    _vlan = XMLChildProperty(_VLANConfig, is_single=True)

    @property
    def interfaces(self):
        if self.type != "ethernet":
            return getattr(self, "_" + self.type).interfaces
        return []


    ##################
    # General params #
    ##################

    type = XMLProperty("./@type")
    name = XMLProperty("./@name")


# Interface can recursively have child interfaces which we can't define
# inline in the class config, hence this hackery
_BondConfig.interfaces = XMLChildProperty(Interface)
_BridgeConfig.interfaces = XMLChildProperty(Interface)
_VLANConfig.interfaces = XMLChildProperty(Interface)

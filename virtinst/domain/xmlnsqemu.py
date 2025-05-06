# Copyright 2017 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


XMLBuilder.register_namespace("qemu", "http://libvirt.org/schemas/domain/qemu/1.0")


class _XMLNSQemuArg(XMLBuilder):
    XML_NAME = "qemu:arg"

    value = XMLProperty("./@value")


class _XMLNSQemuEnv(XMLBuilder):
    XML_NAME = "qemu:env"

    name = XMLProperty("./@name")
    value = XMLProperty("./@value")


class DomainXMLNSQemu(XMLBuilder):
    """
    Class for generating <qemu:commandline> XML
    """

    XML_NAME = "qemu:commandline"
    _XML_PROP_ORDER = ["args", "envs"]

    args = XMLChildProperty(_XMLNSQemuArg)
    envs = XMLChildProperty(_XMLNSQemuEnv)

class QEMUProperty(XMLBuilder):
    XML_NAME = "qemu:property"
    name = XMLProperty("./@name")
    type = XMLProperty("./@type")
    value = XMLProperty("./@value")

class QEMUFrontend(XMLBuilder):
    XML_NAME = "qemu:frontend"
    property = XMLChildProperty(QEMUProperty)

class QEMUDeviceOverride(XMLBuilder):
    XML_NAME = "qemu:device"
    alias = XMLProperty("./@alias")
    frontend = XMLChildProperty(QEMUFrontend, is_single=True)

class QEMUOverride(XMLBuilder):
    XML_NAME = "qemu:override"
    device = XMLChildProperty(QEMUDeviceOverride)

class DeviceDisk(XMLBuilder):
    XML_NAME = "disk"
    # ... other properties ...
    rotational_rate = ... # How you store this property

    qemu_override = XMLChildProperty(QEMUOverride, is_single=True)

    def _add_parse_bits(self, xmlapi):
        super()._add_parse_bits(xmlapi)
        if self.rotational_rate is not None:
            override = self.qemu_override.new()
            device = override.device.new()
            device.alias = self.get_device_alias() # Need a way to get the alias
            frontend = device.frontend.new()
            prop = frontend.property.new()
            prop.name = "rotation_rate"
            prop.type = "unsigned"
            prop.value = str(self.rotational_rate)
            frontend.property.append(prop)
            device.frontend.set(frontend)
            override.device.append(device)
            self.qemu_override.set(override)
            self.add_child(override) # Add the qemu:override block
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

from virtinst.VirtualDevice import VirtualDevice
from virtinst.XMLBuilderDomain import XMLBuilderDomain, _xml_property
import logging


class VirtualController(VirtualDevice):

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_CONTROLLER

    CONTROLLER_TYPE_IDE             = "ide"
    CONTROLLER_TYPE_FDC             = "fdc"
    CONTROLLER_TYPE_SCSI            = "scsi"
    CONTROLLER_TYPE_SATA            = "sata"
    CONTROLLER_TYPE_VIRTIOSERIAL    = "virtio-serial"
    CONTROLLER_TYPE_USB             = "usb"
    CONTROLLER_TYPE_PCI             = "pci"
    CONTROLLER_TYPE_CCID            = "ccid"
    CONTROLLER_TYPES = [CONTROLLER_TYPE_IDE, CONTROLLER_TYPE_FDC,
                        CONTROLLER_TYPE_SCSI, CONTROLLER_TYPE_SATA,
                        CONTROLLER_TYPE_VIRTIOSERIAL, CONTROLLER_TYPE_USB,
                        CONTROLLER_TYPE_PCI, CONTROLLER_TYPE_CCID]

    @staticmethod
    def pretty_type(ctype):
        pretty_mappings = {
            VirtualController.CONTROLLER_TYPE_IDE           : "IDE",
            VirtualController.CONTROLLER_TYPE_FDC           : "Floppy",
            VirtualController.CONTROLLER_TYPE_SCSI          : "SCSI",
            VirtualController.CONTROLLER_TYPE_SATA          : "SATA",
            VirtualController.CONTROLLER_TYPE_VIRTIOSERIAL  : "Virtio Serial",
            VirtualController.CONTROLLER_TYPE_USB           : "USB",
            VirtualController.CONTROLLER_TYPE_PCI           : "PCI",
            VirtualController.CONTROLLER_TYPE_CCID          : "CCID",
       }

        if ctype not in pretty_mappings:
            return ctype
        return pretty_mappings[ctype]

    @staticmethod
    def get_class_for_type(ctype):
        if ctype not in VirtualController.CONTROLLER_TYPES:
            raise ValueError("Unknown controller type '%s'" % ctype)

        if ctype == VirtualController.CONTROLLER_TYPE_IDE:
            return VirtualControllerIDE
        elif ctype == VirtualController.CONTROLLER_TYPE_FDC:
            return VirtualControllerFDC
        elif ctype == VirtualController.CONTROLLER_TYPE_SCSI:
            return VirtualControllerSCSI
        elif ctype == VirtualController.CONTROLLER_TYPE_SATA:
            return VirtualControllerSATA
        elif ctype == VirtualController.CONTROLLER_TYPE_VIRTIOSERIAL:
            return VirtualControllerVirtioSerial
        elif ctype == VirtualController.CONTROLLER_TYPE_USB:
            return VirtualControllerUSB

    _controller_type = None

    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None,
                 model=None):
        VirtualDevice.__init__(self, conn,
                                             parsexml, parsexmlnode, caps)

        self._index = 0
        self._ports = None
        self._vectors = None
        self._model = None
        self._master = VirtualDeviceMaster(conn,
                                           parsexml=parsexml,
                                           parsexmlnode=parsexmlnode,
                                           caps=caps)

        if self._is_parse():
            return

        self.model = model

    def get_type(self):
        return self._controller_type
    type = _xml_property(get_type,
                         xpath="./@type")

    def get_model(self):
        return self._model
    def set_model(self, model):
        self._model = model
    model = _xml_property(get_model, set_model,
                         xpath="./@model")

    def get_index(self):
        return self._index
    def set_index(self, val):
        self._index = int(val)
    index = _xml_property(get_index, set_index,
                          xpath="./@index")

    def get_vectors(self):
        return self._vectors
    def set_vectors(self, val):
        self._vectors = val
    vectors = _xml_property(get_vectors, set_vectors,
                            xpath="./@vectors")

    def get_ports(self):
        return self._ports
    def set_ports(self, val):
        self._ports = val
    ports = _xml_property(get_ports, set_ports,
                          xpath="./@ports")

    def set_master(self, masterstr):
        self._master.parse_friendly_master(masterstr)
    def get_master(self):
        return self._master

    def _extra_config(self):
        return ""

    def _get_xml_config(self):
        extra = self._extra_config()

        xml = "    <controller type='%s' index='%s'" % (self.type, self.index)
        if self.model:
            xml += " model='%s'" % self.model
        xml += extra
        childxml = self.indent(self._master.get_xml_config(), 6)
        childxml += self.indent(self.address.get_xml_config(), 6)
        if len(childxml) == 0:
            return xml + "/>"
        xml += ">\n"
        xml += childxml
        xml += "    </controller>"
        return xml


class VirtualControllerIDE(VirtualController):
    _controller_type = VirtualController.CONTROLLER_TYPE_IDE


class VirtualControllerFDC(VirtualController):
    _controller_type = VirtualController.CONTROLLER_TYPE_FDC


class VirtualControllerSCSI(VirtualController):
    _controller_type = VirtualController.CONTROLLER_TYPE_SCSI


class VirtualControllerSATA(VirtualController):
    _controller_type = VirtualController.CONTROLLER_TYPE_SATA


class VirtualControllerVirtioSerial(VirtualController):
    _controller_type = VirtualController.CONTROLLER_TYPE_VIRTIOSERIAL

    def _extra_config(self):
        xml = ""
        if self.ports is not None:
            xml += " ports='%s'" % self.ports
        if self.vectors is not None:
            xml += " vectors='%s'" % self.vectors

        return xml


class VirtualControllerUSB(VirtualController):
    _controller_type = VirtualController.CONTROLLER_TYPE_USB


class VirtualDeviceMaster(XMLBuilderDomain):
    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None):
        XMLBuilderDomain.__init__(self, conn, parsexml, parsexmlnode,
                                  caps=caps)

        self._startport = None

    def parse_friendly_master(self, masterstr):
        try:
            int(masterstr)
            self._startport = masterstr
        except:
            logging.exception("Error parsing device master.")
            return None

    def _get_startport(self):
        return self._startport
    def _set_startport(self, val):
        self._startport = val
    startport = _xml_property(_get_startport, _set_startport, xpath="./master/@startport")

    def _get_xml_config(self):
        if self.startport is None:
            return

        return "<master startport='%s'/>" % self.startport

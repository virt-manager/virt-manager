# Copyright (C) 2011, 2013 Red Hat, Inc.
# Copyright (C) 2011 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from virtinst import NodeDevice

from .libvirtobject import vmmLibvirtObject


def _usb_pretty_name(xmlobj):
    # product/vendor name fields can be messy, this tries to cope
    product = str(xmlobj.product_name or "").strip()
    vendor = str(xmlobj.vendor_name or "").strip()
    product = product or str(xmlobj.product_id or "")
    vendor = vendor or str(xmlobj.vendor_id or "")
    busstr = "%.3d:%.3d" % (int(xmlobj.bus), int(xmlobj.device))
    desc = "%s %s %s" % (busstr, vendor, product)
    return desc


def _pretty_name(xmlobj):
    if xmlobj.device_type == "net":
        return _("Interface %s") % xmlobj.interface or xmlobj.name

    if xmlobj.device_type == "pci":
        devstr = "%.4X:%.2X:%.2X:%X" % (int(xmlobj.domain),
                                        int(xmlobj.bus),
                                        int(xmlobj.slot),
                                        int(xmlobj.function))
        return "%s %s %s" % (devstr,
                xmlobj.vendor_name, xmlobj.product_name)
    if xmlobj.device_type == "usb_device":
        return _usb_pretty_name(xmlobj)

    if xmlobj.device_type == "drm":
        parent = NodeDevice.lookupNodedevFromString(
                xmlobj.conn, xmlobj.parent)
        return "%s (%s)" % (_pretty_name(parent), xmlobj.drm_type)

    return xmlobj.name  # pragma: no cover


class vmmNodeDevice(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, NodeDevice)

    def _conn_tick_poll_param(self):
        return "pollnodedev"  # pragma: no cover
    def class_name(self):
        return "nodedev"

    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def _get_backend_status(self):
        return self._STATUS_ACTIVE
    def _using_events(self):
        return self.conn.using_node_device_events

    def pretty_name(self):
        return _pretty_name(self.xmlobj)

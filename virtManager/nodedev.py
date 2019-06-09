# Copyright (C) 2011, 2013 Red Hat, Inc.
# Copyright (C) 2011 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from virtinst import NodeDevice

from .libvirtobject import vmmLibvirtObject


def _usb_pretty_name(xmlobj):
    # Hypervisor may return a rather sparse structure, missing
    # some ol all stringular descriptions of the device altogether.
    # Do our best to help user identify the device.

    # Certain devices pad their vendor with trailing spaces,
    # such as "LENOVO       ". It does not look well.
    product = str(xmlobj.product_name).strip()
    vendor = str(xmlobj.vendor_name).strip()

    if product == "":
        product = str(xmlobj.product_id)
        if vendor == "":
            # No stringular descriptions altogether
            vendor = str(xmlobj.vendor_id)
            devstr = "%s:%s" % (vendor, product)
        else:
            # Only the vendor is known
            devstr = "%s %s" % (vendor, product)
    else:
        if vendor == "":
            # Sometimes vendor is left out empty, but product is
            # already descriptive enough or contains the vendor string:
            # "Lenovo USB Laser Mouse"
            devstr = product
        else:
            # We know everything. Perfect.
            devstr = "%s %s" % (vendor, product)

    busstr = "%.3d:%.3d" % (int(xmlobj.bus), int(xmlobj.device))
    desc = "%s %s" % (busstr, devstr)
    return desc


def _pretty_name(xmlobj):
    if xmlobj.device_type == "net":
        if xmlobj.interface:
            return _("Interface %s") % xmlobj.interface
        return xmlobj.name

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

    return xmlobj.name


class vmmNodeDevice(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, NodeDevice)

    def _conn_tick_poll_param(self):
        return "pollnodedev"
    def class_name(self):
        return "nodedev"

    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def _get_backend_status(self):
        return self._STATUS_ACTIVE
    def _backend_get_name(self):
        return self.get_connkey()
    def is_active(self):
        return True
    def _using_events(self):
        return self.conn.using_node_device_events

    def tick(self, stats_update=True):
        # Deliberately empty
        ignore = stats_update
    def _init_libvirt_state(self):
        self.ensure_latest_xml()

    def pretty_name(self):
        return _pretty_name(self.xmlobj)

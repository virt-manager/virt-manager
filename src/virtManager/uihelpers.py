#
# Copyright (C) 2009 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
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
import traceback

import gtk

from virtinst import VirtualNetworkInterface

from virtManager.error import vmmErrorDialog

# Initialize an error object to use for validation functions
err_dial = vmmErrorDialog(None,
                          0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                          _("Unexpected Error"),
                          _("An unexpected error occurred"))

def set_error_parent(parent):
    global err_dial
    err_dial.set_parent(parent)
    err_dial = err_dial

# Widgets for listing network device options (in create, addhardware)
def init_network_list(net_list):
    # [ network type, source name, label, sensitive? ]
    net_model = gtk.ListStore(str, str, str, bool)
    net_list.set_model(net_model)

    if isinstance(net_list, gtk.ComboBox):
        net_col = net_list
    else:
        net_col = gtk.TreeViewColumn()
        net_list.append_column(net_col)

    text = gtk.CellRendererText()
    net_col.pack_start(text, True)
    net_col.add_attribute(text, 'text', 2)
    net_col.add_attribute(text, 'sensitive', 3)

def populate_network_list(net_list, conn):
    model = net_list.get_model()
    model.clear()

    def set_active(idx):
        if isinstance(net_list, gtk.ComboBox):
            net_list.set_active(idx)

    # For qemu:///session
    if conn.is_qemu_session():
        model.append([VirtualNetworkInterface.TYPE_USER, None,
                     _("Usermode Networking"), True])
        set_active(0)
        return

    hasNet = False
    netIdx = 0
    # Virtual Networks
    for uuid in conn.list_net_uuids():
        net = conn.get_net(uuid)

        # FIXME: Should we use 'default' even if it's inactive?
        label = _("Virtual network") + " '%s'" % net.get_name()
        if not net.is_active():
            label +=  " (%s)" % _("Inactive")

        desc = net.pretty_forward_mode()
        label += ": %s" % desc

        hasNet = True
        # FIXME: This preference should be configurable
        if net.get_name() == "default":
            netIdx = len(model) - 1

        model.append([VirtualNetworkInterface.TYPE_VIRTUAL,
                      net.get_name(), label, True])
    if not hasNet:
        model.append([None, None, _("No virtual networks available"), False])

    # Physical devices
    hasShared = False
    brIndex = -1
    if not conn.is_remote():
        for name in conn.list_net_device_paths():
            br = conn.get_net_device(name)

            if br.is_shared():
                hasShared = True
                if brIndex < 0:
                    brIndex = len(model)

                brlabel =  "(%s %s)" % (_("Bridge"), br.get_bridge())
                sensitive = True
            else:
                brlabel = "(%s)" %  _("Not bridged")
                sensitive = False

            model.append([VirtualNetworkInterface.TYPE_BRIDGE,
                          br.get_bridge(),
                          _("Host device %s %s") % (br.get_name(), brlabel),
                          sensitive])

    # If there is a bridge device, default to that
    # If not, use 'default' network
    # If not present, use first list entry
    # If list empty, use no network devices
    if hasShared:
        default = brIndex
    elif hasNet:
        default = netIdx
    else:
        model.insert(0, [None, None, _("No networking."), True])
        default = 0

    set_active(default)

def validate_network(parent, conn, nettype, devname, macaddr, model=None):
    set_error_parent(parent)

    net = None

    if nettype is None:
        return None

    # Make sure VirtualNetwork is running
    if (nettype == VirtualNetworkInterface.TYPE_VIRTUAL and
        devname not in conn.vmm.listNetworks()):

        res = err_dial.yes_no(_("Virtual Network is not active."),
                              _("Virtual Network '%s' is not active. "
                                "Would you like to start the network "
                                "now?") % devname)
        if not res:
            return False

        # Try to start the network
        try:
            virnet = conn.vmm.networkLookupByName(devname)
            virnet.create()
            logging.info("Started network '%s'." % devname)
        except Exception, e:
            return err_dial.show_err(_("Could not start virtual network "
                                       "'%s': %s") % (devname, str(e)),
                                       "".join(traceback.format_exc()))

    # Create network device
    try:
        bridge = None
        netname = None
        if nettype == VirtualNetworkInterface.TYPE_VIRTUAL:
            netname = devname
        elif nettype == VirtualNetworkInterface.TYPE_BRIDGE:
            bridge = devname
        elif nettype == VirtualNetworkInterface.TYPE_USER:
            pass

        net = VirtualNetworkInterface(type = nettype,
                                      bridge = bridge,
                                      network = netname,
                                      macaddr = macaddr,
                                      model = model)
    except Exception, e:
        return err_dial.val_err(_("Error with network parameters."), str(e))

    # Make sure there is no mac address collision
    isfatal, errmsg = net.is_conflict_net(conn.vmm)
    if isfatal:
        return err_dial.val_err(_("Mac address collision."), errmsg)
    elif errmsg is not None:
        retv = err_dial.yes_no(_("Mac address collision."),
                               _("%s Are you sure you want to use this "
                                 "address?") % errmsg)
        if not retv:
            return False

    return net

def generate_macaddr(conn):
    newmac = ""
    try:
        net = VirtualNetworkInterface(conn=conn.vmm)
        net.setup(conn.vmm)
        newmac = net.macaddr
    except:
        pass

    return newmac

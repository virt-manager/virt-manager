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

OPTICAL_DEV_PATH = 0
OPTICAL_LABEL = 1
OPTICAL_IS_MEDIA_PRESENT = 2
OPTICAL_DEV_KEY = 3
OPTICAL_MEDIA_KEY = 4

##############################################################
# Initialize an error object to use for validation functions #
##############################################################

err_dial = vmmErrorDialog(None,
                          0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                          _("Unexpected Error"),
                          _("An unexpected error occurred"))

def set_error_parent(parent):
    global err_dial
    err_dial.set_parent(parent)
    err_dial = err_dial


#######################################################################
# Widgets for listing network device options (in create, addhardware) #
#######################################################################

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

    vnet_dict = {}
    bridge_dict = {}
    iface_dict = {}

    def set_active(idx):
        if isinstance(net_list, gtk.ComboBox):
            net_list.set_active(idx)

    def add_dict(indict, model):
        keylist = indict.keys()
        keylist.sort()
        rowlist = map(lambda key: indict[key], keylist)
        for row in rowlist:
            model.append(row)

    # For qemu:///session
    if conn.is_qemu_session():
        model.append([VirtualNetworkInterface.TYPE_USER, None,
                     _("Usermode Networking"), True])
        set_active(0)
        return

    hasNet = False
    netIdxLabel = None
    # Virtual Networks
    for uuid in conn.list_net_uuids():
        net = conn.get_net(uuid)

        label = _("Virtual network") + " '%s'" % net.get_name()
        if not net.is_active():
            label +=  " (%s)" % _("Inactive")

        desc = net.pretty_forward_mode()
        label += ": %s" % desc

        hasNet = True
        # FIXME: Should we use 'default' even if it's inactive?
        # FIXME: This preference should be configurable
        if net.get_name() == "default":
            netIdxLabel = label

        vnet_dict[label] = [VirtualNetworkInterface.TYPE_VIRTUAL,
                           net.get_name(), label, True]
    if not hasNet:
        label = _("No virtual networks available")
        vnet_dict[label] = [None, None, label, False]

    # Physical devices
    hasShared = False
    brIdxLabel = None
    for name in conn.list_net_device_paths():
        br = conn.get_net_device(name)
        bridge_name = br.get_bridge()

        if br.is_shared():
            hasShared = True
            sensitive = True
            if br.get_bridge():
                brlabel =  "(%s %s)" % (_("Bridge"), br.get_bridge())
            else:
                bridge_name = name
                brlabel = _("(Empty bridge)")
        else:
            sensitive = False
            brlabel = "(%s)" %  _("Not bridged")

        label = _("Host device %s %s") % (br.get_name(), brlabel)
        if hasShared and not brIdxLabel:
            brIdxLabel = label

        row = [VirtualNetworkInterface.TYPE_BRIDGE,
               bridge_name, label, sensitive]

        if sensitive:
            bridge_dict[label] = row
        else:
            iface_dict[label] = row

    add_dict(bridge_dict, model)
    add_dict(vnet_dict, model)
    add_dict(iface_dict, model)

    # If there is a bridge device, default to that
    # If not, use 'default' network
    # If not present, use first list entry
    # If list empty, use no network devices
    label = brIdxLabel or netIdxLabel
    if label:
        for idx in range(len(model)):
            row = model[idx]
            if row[2] == label:
                default = idx
                break

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


##############################################
# Populate optical widget (choosecd, create) #
##############################################

def init_optical_combo(widget, empty_sensitive=False):
    # [Device path, pretty label, has_media?, device key, media key,
    #  vmmMediaDevice]
    model = gtk.ListStore(str, str, bool, str, str)
    widget.set_model(model)
    model.clear()

    text = gtk.CellRendererText()
    widget.pack_start(text, True)
    widget.add_attribute(text, 'text', 1)
    if not empty_sensitive:
        widget.add_attribute(text, 'sensitive', 2)

def populate_optical_combo(conn, widget):
    sigs = []

    widget.get_model().clear()

    sigs.append(conn.connect("optical-added", optical_added, widget))
    sigs.append(conn.connect("optical-removed", optical_removed, widget))

    widget.set_active(-1)
    optical_set_default_selection(widget)

    return sigs

def set_row_from_object(row, obj):
    row[OPTICAL_DEV_PATH] = obj.get_path()
    row[OPTICAL_LABEL] = obj.pretty_label()
    row[OPTICAL_IS_MEDIA_PRESENT] = obj.has_media()
    row[OPTICAL_DEV_KEY] = obj.get_key()
    row[OPTICAL_MEDIA_KEY] = obj.get_media_key()

def optical_removed(ignore_helper, key, widget):
    model = widget.get_model()
    active = widget.get_active()
    idx = 0

    for row in model:
        if row[OPTICAL_DEV_KEY] == key:
            # Whole device removed
            del(model[idx])

            if idx > active and active != -1:
                widget.set_active(active-1)
            elif idx == active:
                widget.set_active(-1)

        idx += 1

    optical_set_default_selection(widget)

def optical_added(ignore_helper, newobj, widget):
    model = widget.get_model()

    newobj.connect("media-added", optical_media_changed, widget)
    newobj.connect("media-removed", optical_media_changed, widget)

    # Brand new device
    row = [None, None, None, None, None]
    set_row_from_object(row, newobj)
    model.append(row)

    optical_set_default_selection(widget)

def optical_media_changed(newobj, widget):
    model = widget.get_model()
    active = widget.get_active()
    idx = 0

    # Search for the row with matching device node and
    # fill in info about inserted media. If model has no current
    # selection, select the new media.
    for row in model:
        if row[OPTICAL_DEV_PATH] == newobj.get_path():
            set_row_from_object(row, newobj)
            has_media = row[OPTICAL_IS_MEDIA_PRESENT]

            if has_media and active == -1:
                widget.set_active(idx)
            elif not has_media and active == idx:
                widget.set_active(-1)

        idx = idx + 1

    optical_set_default_selection(widget)

def optical_set_default_selection(widget):
    # Set the first active cdrom device as selected, otherwise none
    model = widget.get_model()
    idx = 0
    active = widget.get_active()

    if active != -1:
        # already a selection, don't change it
        return

    for row in model:
        if row[OPTICAL_IS_MEDIA_PRESENT] == True:
            widget.set_active(idx)
            return
        idx += 1

    widget.set_active(-1)


####################################################################
# Build toolbar shutdown button menu (manager and details toolbar) #
####################################################################

def build_shutdown_button_menu(config, widget, shutdown_cb, reboot_cb,
                               destroy_cb):
    icon_name = config.get_shutdown_icon_name()
    widget.set_icon_name(icon_name)
    menu = gtk.Menu()
    widget.set_menu(menu)

    rebootimg = gtk.image_new_from_icon_name(icon_name, gtk.ICON_SIZE_MENU)
    shutdownimg = gtk.image_new_from_icon_name(icon_name, gtk.ICON_SIZE_MENU)
    destroyimg = gtk.image_new_from_icon_name(icon_name, gtk.ICON_SIZE_MENU)

    reboot = gtk.ImageMenuItem(_("_Reboot"))
    reboot.set_image(rebootimg)
    reboot.show()
    reboot.connect("activate", reboot_cb)
    menu.add(reboot)

    shutdown = gtk.ImageMenuItem(_("_Shut Down"))
    shutdown.set_image(shutdownimg)
    shutdown.show()
    shutdown.connect("activate", shutdown_cb)
    menu.add(shutdown)

    destroy = gtk.ImageMenuItem(_("_Force Off"))
    destroy.set_image(destroyimg)
    destroy.show()
    destroy.connect("activate", destroy_cb)
    menu.add(destroy)

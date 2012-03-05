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
import os
import statvfs

import gtk

import virtinst
from virtinst import VirtualNetworkInterface
from virtinst import VirtualDisk

from virtManager import util
from virtManager.error import vmmErrorDialog

OPTICAL_DEV_PATH = 0
OPTICAL_LABEL = 1
OPTICAL_IS_MEDIA_PRESENT = 2
OPTICAL_DEV_KEY = 3
OPTICAL_MEDIA_KEY = 4
OPTICAL_IS_VALID = 5

##############################################################
# Initialize an error object to use for validation functions #
##############################################################

err_dial = vmmErrorDialog()

def set_error_parent(parent):
    global err_dial
    err_dial.set_parent(parent)
    err_dial = err_dial

def cleanup():
    global err_dial
    err_dial = None

def spin_get_helper(widget):
    adj = widget.get_adjustment()
    txt = widget.get_text()

    try:
        ret = int(txt)
    except:
        ret = adj.value
    return ret

############################################################
# Helpers for shared storage UI between create/addhardware #
############################################################

def set_sparse_tooltip(widget):
    sparse_str = _("Fully allocating storage may take longer now, "
                   "but the OS install phase will be quicker. \n\n"
                   "Skipping allocation can also cause space issues on "
                   "the host machine, if the maximum image size exceeds "
                   "available storage space.")
    util.tooltip_wrapper(widget, sparse_str)

def host_disk_space(conn):
    pool = util.get_default_pool(conn)
    path = util.get_default_dir(conn)

    avail = 0
    if pool and pool.is_active():
        # FIXME: make sure not inactive?
        # FIXME: use a conn specific function after we send pool-added
        pool.refresh()
        avail = int(util.xpath(pool.get_xml(), "/pool/available"))

    elif not conn.is_remote() and os.path.exists(path):
        vfs = os.statvfs(os.path.dirname(path))
        avail = vfs[statvfs.F_FRSIZE] * vfs[statvfs.F_BAVAIL]

    return float(avail / 1024.0 / 1024.0 / 1024.0)

def host_space_tick(conn, widget):
    try:
        max_storage = host_disk_space(conn)
    except:
        logging.exception("Error determining host disk space")
        return 0

    def pretty_storage(size):
        return "%.1f Gb" % float(size)

    hd_label = ("%s available in the default location" %
                pretty_storage(max_storage))
    hd_label = ("<span color='#484848'>%s</span>" % hd_label)
    widget.set_markup(hd_label)

    return 1

def check_default_pool_active(topwin, conn):
    default_pool = util.get_default_pool(conn)
    if default_pool and not default_pool.is_active():
        res = err_dial.yes_no(_("Default pool is not active."),
                              _("Storage pool '%s' is not active. "
                                "Would you like to start the pool "
                                "now?") % default_pool.get_name())
        if not res:
            return False

        # Try to start the pool
        try:
            default_pool.start()
            logging.info("Started pool '%s'", default_pool.get_name())
        except Exception, e:
            return topwin.err.show_err(_("Could not start storage_pool "
                                         "'%s': %s") %
                                         (default_pool.get_name(), str(e)))
    return True

#####################################################
# Hardware model list building (for details, addhw) #
#####################################################
def build_video_combo(vm, video_dev, no_default=None):
    video_dev_model = gtk.ListStore(str)
    video_dev.set_model(video_dev_model)
    text = gtk.CellRendererText()
    video_dev.pack_start(text, True)
    video_dev.add_attribute(text, 'text', 0)
    video_dev_model.set_sort_column_id(0, gtk.SORT_ASCENDING)

    populate_video_combo(vm, video_dev, no_default)

def populate_video_combo(vm, video_dev, no_default=None):
    video_dev_model = video_dev.get_model()
    has_spice = any(map(lambda g: g.type == g.TYPE_SPICE,
                        vm.get_graphics_devices()))
    has_qxl = any(map(lambda v: v.model_type == "qxl",
                      vm.get_video_devices()))

    video_dev_model.clear()
    tmpdev = virtinst.VirtualVideoDevice(vm.conn.vmm)
    for m in tmpdev.model_types:
        if not vm.rhel6_defaults():
            if m == "qxl" and not has_spice and not has_qxl:
                # Only list QXL video option when VM has SPICE video
                continue

        if m == tmpdev.MODEL_DEFAULT and no_default:
            continue
        video_dev_model.append([m])

    if len(video_dev_model) > 0:
        video_dev.set_active(0)

def build_sound_combo(vm, combo, no_default=False):
    dev_model = gtk.ListStore(str)
    combo.set_model(dev_model)
    text = gtk.CellRendererText()
    combo.pack_start(text, True)
    combo.add_attribute(text, 'text', 0)
    dev_model.set_sort_column_id(0, gtk.SORT_ASCENDING)

    disable_rhel = not vm.rhel6_defaults()
    rhel6_soundmodels = ["ich6", "ac97", "es1370"]

    for m in virtinst.VirtualAudio.MODELS:
        if m == virtinst.VirtualAudio.MODEL_DEFAULT and no_default:
            continue

        if (disable_rhel and m not in rhel6_soundmodels):
            continue

        dev_model.append([m])
    if len(dev_model) > 0:
        combo.set_active(0)

def build_watchdogmodel_combo(vm, combo, no_default=False):
    ignore = vm
    dev_model = gtk.ListStore(str)
    combo.set_model(dev_model)
    text = gtk.CellRendererText()
    combo.pack_start(text, True)
    combo.add_attribute(text, 'text', 0)
    dev_model.set_sort_column_id(0, gtk.SORT_ASCENDING)

    for m in virtinst.VirtualWatchdog.MODELS:
        if m == virtinst.VirtualAudio.MODEL_DEFAULT and no_default:
            continue
        dev_model.append([m])
    if len(dev_model) > 0:
        combo.set_active(0)

def build_watchdogaction_combo(vm, combo, no_default=False):
    ignore = vm
    dev_model = gtk.ListStore(str, str)
    combo.set_model(dev_model)
    text = gtk.CellRendererText()
    combo.pack_start(text, True)
    combo.add_attribute(text, 'text', 1)
    dev_model.set_sort_column_id(0, gtk.SORT_ASCENDING)

    for m in virtinst.VirtualWatchdog.ACTIONS:
        if m == virtinst.VirtualWatchdog.ACTION_DEFAULT and no_default:
            continue
        dev_model.append([m, virtinst.VirtualWatchdog.get_action_desc(m)])
    if len(dev_model) > 0:
        combo.set_active(0)

def build_source_mode_combo(vm, combo):
    source_mode = gtk.ListStore(str, str)
    combo.set_model(source_mode)
    text = gtk.CellRendererText()
    combo.pack_start(text, True)
    combo.add_attribute(text, 'text', 1)

    populate_source_mode_combo(vm, combo)
    combo.set_active(0)

def populate_source_mode_combo(vm, combo):
    ignore = vm
    model = combo.get_model()
    model.clear()

    # [xml value, label]
    model.append([None, "Default"])
    model.append(["vepa", "VEPA"])
    model.append(["bridge", "Bridge"])
    model.append(["private", "Private"])
    model.append(["passthrough", "Passthrough"])

def build_smartcard_mode_combo(vm, combo):
    dev_model = gtk.ListStore(str, str)
    combo.set_model(dev_model)
    text = gtk.CellRendererText()
    combo.pack_start(text, True)
    combo.add_attribute(text, 'text', 1)
    dev_model.set_sort_column_id(0, gtk.SORT_ASCENDING)

    populate_smartcard_mode_combo(vm, combo)

    idx = -1
    for rowid in range(len(combo.get_model())):
        idx = 0
        row = combo.get_model()[rowid]
        if row[0] == virtinst.VirtualSmartCardDevice.MODE_DEFAULT:
            idx = rowid
            break
    combo.set_active(idx)

def populate_smartcard_mode_combo(vm, combo):
    ignore = vm
    model = combo.get_model()
    model.clear()

    # [xml value, label]
    model.append(["passthrough", "Passthrough"])
    model.append(["host", "Host"])
# TODO
#    model.append(["host-certificates", "Host Certificates"])

def build_redir_type_combo(vm, combo):
    source_mode = gtk.ListStore(str, str, bool)
    combo.set_model(source_mode)
    text = gtk.CellRendererText()
    combo.pack_start(text, True)
    combo.add_attribute(text, 'text', 1)

    populate_redir_type_combo(vm, combo)
    combo.set_active(0)

def populate_redir_type_combo(vm, combo):
    ignore = vm
    model = combo.get_model()
    model.clear()

    # [xml value, label, conn details]
    model.append(["spicevmc", "Spice channel", False])
    model.append(["tcp", "TCP", True])

def build_netmodel_combo(vm, combo):
    dev_model = gtk.ListStore(str, str)
    combo.set_model(dev_model)
    text = gtk.CellRendererText()
    combo.pack_start(text, True)
    combo.add_attribute(text, 'text', 1)
    dev_model.set_sort_column_id(0, gtk.SORT_ASCENDING)

    populate_netmodel_combo(vm, combo)
    combo.set_active(0)

def populate_netmodel_combo(vm, combo):
    model = combo.get_model()
    model.clear()

    # [xml value, label]
    model.append([None, _("Hypervisor default")])
    if vm.is_hvm():
        mod_list = ["rtl8139", "ne2k_pci", "pcnet", "e1000"]
        if vm.get_hv_type() in ["kvm", "qemu", "test"]:
            mod_list.append("virtio")
        if (vm.get_hv_type() == "kvm" and
              vm.get_machtype() == "pseries"):
            mod_list.append("spapr-vlan")
        if vm.get_hv_type() in ["xen", "test"]:
            mod_list.append("netfront")
        mod_list.sort()

        for m in mod_list:
            model.append([m, m])

def build_cache_combo(vm, combo, no_default=False):
    ignore = vm
    dev_model = gtk.ListStore(str, str)
    combo.set_model(dev_model)
    text = gtk.CellRendererText()
    combo.pack_start(text, True)
    combo.add_attribute(text, 'text', 1)
    dev_model.set_sort_column_id(0, gtk.SORT_ASCENDING)

    combo.set_active(-1)
    for m in virtinst.VirtualDisk.cache_types:
        dev_model.append([m, m])

    if not no_default:
        dev_model.append([None, "default"])
    combo.set_active(0)

def build_io_combo(vm, combo, no_default=False):
    ignore = vm
    dev_model = gtk.ListStore(str, str)
    combo.set_model(dev_model)
    text = gtk.CellRendererText()
    combo.pack_start(text, True)
    combo.add_attribute(text, 'text', 1)
    dev_model.set_sort_column_id(0, gtk.SORT_ASCENDING)

    combo.set_active(-1)
    for m in virtinst.VirtualDisk.io_modes:
        dev_model.append([m, m])

    if not no_default:
        dev_model.append([None, "default"])
    combo.set_active(0)

def build_disk_bus_combo(vm, combo, no_default=False):
    ignore = vm
    dev_model = gtk.ListStore(str, str)
    combo.set_model(dev_model)
    text = gtk.CellRendererText()
    combo.pack_start(text, True)
    combo.add_attribute(text, 'text', 1)
    dev_model.set_sort_column_id(0, gtk.SORT_ASCENDING)

    if not no_default:
        dev_model.append([None, "default"])
    combo.set_active(-1)

def build_vnc_keymap_combo(vm, combo, no_default=False):
    ignore = vm

    model = gtk.ListStore(str, str)
    combo.set_model(model)
    text = gtk.CellRendererText()
    combo.pack_start(text, True)
    combo.add_attribute(text, 'text', 1)

    if not no_default:
        model.append([None, "default"])
    else:
        model.append([None, "Auto"])

    model.append([virtinst.VirtualGraphics.KEYMAP_LOCAL,
                  "Copy local keymap"])
    for k in virtinst.VirtualGraphics.valid_keymaps():
        model.append([k, k])

    combo.set_active(-1)

#####################################
# Storage format list/combo helpers #
#####################################

def build_storage_format_combo(vm, combo):
    dev_model = gtk.ListStore(str)
    combo.set_model(dev_model)
    combo.set_text_column(0)

    formats = ["raw", "qcow2", "qed"]
    if vm.rhel6_defaults():
        formats.append("vmdk")
        formats.append("vdi")

    for m in formats:
        dev_model.append([m])

    combo.set_active(0)

#######################################################################
# Widgets for listing network device options (in create, addhardware) #
#######################################################################

def pretty_network_desc(nettype, source=None, netobj=None):
    if nettype == VirtualNetworkInterface.TYPE_USER:
        return _("Usermode networking")

    extra = None
    if nettype == VirtualNetworkInterface.TYPE_BRIDGE:
        ret = _("Bridge")
    elif nettype == VirtualNetworkInterface.TYPE_VIRTUAL:
        ret = _("Virtual network")
        if netobj:
            extra = ": %s" % netobj.pretty_forward_mode()
    else:
        ret = nettype.capitalize()

    if source:
        ret += " '%s'" % source
    if extra:
        ret += " %s" % extra

    return ret

def init_network_list(net_list, bridge_box,
                      source_mode_box=None, source_mode_label=None,
                      vport_expander=None):
    # [ network type, source name, label, sensitive?, net is active,
    #   manual bridge, net instance]
    net_model = gtk.ListStore(str, str, str, bool, bool, bool, object)
    net_list.set_model(net_model)

    net_list.connect("changed", net_list_changed, bridge_box, source_mode_box,
                     source_mode_label, vport_expander)

    text = gtk.CellRendererText()
    net_list.pack_start(text, True)
    net_list.add_attribute(text, 'text', 2)
    net_list.add_attribute(text, 'sensitive', 3)

def net_list_changed(net_list, bridge_box,
                     source_mode_box, source_mode_label, vport_expander):
    active = net_list.get_active()
    if active < 0:
        return

    if not bridge_box:
        return

    row = net_list.get_model()[active]

    if source_mode_box != None:
        show_source_mode = (row[0] == VirtualNetworkInterface.TYPE_DIRECT)
        source_mode_box.set_property("visible", show_source_mode)
        source_mode_label.set_property("visible", show_source_mode)
        vport_expander.set_property("visible", show_source_mode)

    show_bridge = row[5]

    bridge_box.set_property("visible", show_bridge)

def get_network_selection(net_list, bridge_entry):
    idx = net_list.get_active()
    if idx == -1:
        return None, None

    row = net_list.get_model()[net_list.get_active()]
    net_type = row[0]
    net_src = row[1]
    net_check_bridge = row[5]

    if net_check_bridge and bridge_entry:
        net_type = VirtualNetworkInterface.TYPE_BRIDGE
        net_src = bridge_entry.get_text()

    return net_type, net_src

def populate_network_list(net_list, conn, show_direct_interfaces=True):
    model = net_list.get_model()
    model.clear()

    vnet_bridges = []
    vnet_dict = {}
    bridge_dict = {}
    iface_dict = {}

    def build_row(nettype, name, label, is_sensitive, is_running,
                  manual_bridge=False, key=None):
        return [nettype, name, label,
                is_sensitive, is_running, manual_bridge,
                key]

    def set_active(idx):
        net_list.set_active(idx)

    def add_dict(indict, model):
        keylist = indict.keys()
        keylist.sort()
        rowlist = map(lambda key: indict[key], keylist)
        for row in rowlist:
            model.append(row)

    # For qemu:///session
    if conn.is_qemu_session():
        nettype = VirtualNetworkInterface.TYPE_USER
        r = build_row(nettype, None, pretty_network_desc(nettype), True, True)
        model.append(r)
        set_active(0)
        return

    hasNet = False
    netIdxLabel = None
    # Virtual Networks
    for uuid in conn.list_net_uuids():
        net = conn.get_net(uuid)
        nettype = VirtualNetworkInterface.TYPE_VIRTUAL

        label = pretty_network_desc(nettype, net.get_name(), net)
        if not net.is_active():
            label += " (%s)" % _("Inactive")

        hasNet = True
        # FIXME: Should we use 'default' even if it's inactive?
        # FIXME: This preference should be configurable
        if net.get_name() == "default":
            netIdxLabel = label

        vnet_dict[label] = build_row(nettype, net.get_name(), label, True,
                                     net.is_active(), key=net.get_uuid())

        # Build a list of vnet bridges, so we know not to list them
        # in the physical interface list
        vnet_bridge = net.get_bridge_device()
        if vnet_bridge:
            vnet_bridges.append(vnet_bridge)

    if not hasNet:
        label = _("No virtual networks available")
        vnet_dict[label] = build_row(None, None, label, False, False)

    # Physical devices
    hasShared = False
    brIdxLabel = None
    for name in conn.list_net_device_paths():
        br = conn.get_net_device(name)
        bridge_name = br.get_bridge()
        nettype = VirtualNetworkInterface.TYPE_BRIDGE

        if (bridge_name in vnet_bridges) or (br.get_name() in vnet_bridges):
            # Don't list this, as it is basically duplicating virtual net info
            continue

        if br.is_shared():
            sensitive = True
            if br.get_bridge():
                hasShared = True
                brlabel = "(%s)" % pretty_network_desc(nettype, bridge_name)
            else:
                bridge_name = name
                brlabel = _("(Empty bridge)")
        else:
            if (show_direct_interfaces and virtinst.support.check_conn_support(conn.vmm,
                         virtinst.support.SUPPORT_CONN_HV_DIRECT_INTERFACE)):
                sensitive = True
                nettype = VirtualNetworkInterface.TYPE_DIRECT
                bridge_name = name
                brlabel = ": %s" % _("macvtap")
            else:
                sensitive = False
                brlabel = "(%s)" % _("Not bridged")

        label = _("Host device %s %s") % (br.get_name(), brlabel)
        if hasShared and not brIdxLabel:
            brIdxLabel = label

        row = build_row(nettype, bridge_name, label, sensitive, True,
                        key=br.get_name())

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
    return_warn = False
    label = brIdxLabel or netIdxLabel

    for idx in range(len(model)):
        row = model[idx]
        is_inactive = not row[4]
        if label:
            if row[2] == label:
                default = idx
                return_warn = is_inactive
                break
        else:
            if row[3] == True:
                default = idx
                return_warn = is_inactive
                break
    else:
        return_warn = True
        row = build_row(None, None, _("No networking"), True, False)
        model.insert(0, row)
        default = 0

    # After all is said and done, add a manual bridge option
    manual_row = build_row(None, None, _("Specify shared device name"),
                           True, False, manual_bridge=True)
    model.append(manual_row)

    set_active(default)
    return return_warn

def validate_network(parent, conn, nettype, devname, macaddr, model=None):
    set_error_parent(parent)

    net = None
    addr = None

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
            logging.info("Started network '%s'", devname)
        except Exception, e:
            return err_dial.show_err(_("Could not start virtual network "
                                       "'%s': %s") % (devname, str(e)))

    # Create network device
    try:
        bridge = None
        netname = None
        if nettype == VirtualNetworkInterface.TYPE_VIRTUAL:
            netname = devname
        elif nettype == VirtualNetworkInterface.TYPE_BRIDGE:
            bridge = devname
        elif nettype == VirtualNetworkInterface.TYPE_DIRECT:
            bridge = devname
        elif nettype == VirtualNetworkInterface.TYPE_USER:
            pass

        net = VirtualNetworkInterface(conn=conn.vmm,
                                      type=nettype,
                                      bridge=bridge,
                                      network=netname,
                                      macaddr=macaddr,
                                      model=model)
        if net.model == "spapr-vlan":
            addr = "spapr-vio"

        net.set_address(addr)

    except Exception, e:
        return err_dial.val_err(_("Error with network parameters."), e)

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


############################################
# Populate media widget (choosecd, create) #
############################################

def init_mediadev_combo(widget):
    # [Device path, pretty label, has_media?, device key, media key,
    #  vmmMediaDevice, is valid device]
    model = gtk.ListStore(str, str, bool, str, str, bool)
    widget.set_model(model)
    model.clear()

    text = gtk.CellRendererText()
    widget.pack_start(text, True)
    widget.add_attribute(text, 'text', OPTICAL_LABEL)
    widget.add_attribute(text, 'sensitive', OPTICAL_IS_VALID)

def populate_mediadev_combo(conn, widget, devtype):
    sigs = []

    model = widget.get_model()
    model.clear()
    set_mediadev_default(model)

    sigs.append(conn.connect("mediadev-added", mediadev_added, widget, devtype))
    sigs.append(conn.connect("mediadev-removed", mediadev_removed, widget))

    widget.set_active(-1)
    mediadev_set_default_selection(widget)

    return sigs

def set_mediadev_default(model):
    if len(model) == 0:
        model.append([None, _("No device present"), False, None, None, False])

def set_row_from_object(row, obj):
    row[OPTICAL_DEV_PATH] = obj.get_path()
    row[OPTICAL_LABEL] = obj.pretty_label()
    row[OPTICAL_IS_MEDIA_PRESENT] = obj.has_media()
    row[OPTICAL_DEV_KEY] = obj.get_key()
    row[OPTICAL_MEDIA_KEY] = obj.get_media_key()
    row[OPTICAL_IS_VALID] = True

def mediadev_removed(ignore_helper, key, widget):
    model = widget.get_model()
    active = widget.get_active()
    idx = 0

    for row in model:
        if row[OPTICAL_DEV_KEY] == key:
            # Whole device removed
            del(model[idx])

            if idx > active and active != -1:
                widget.set_active(active - 1)
            elif idx == active:
                widget.set_active(-1)

        idx += 1

    set_mediadev_default(model)
    mediadev_set_default_selection(widget)

def mediadev_added(ignore_helper, newobj, widget, devtype):
    model = widget.get_model()

    if newobj.get_media_type() != devtype:
        return

    if len(model) == 1 and model[0][OPTICAL_IS_VALID] == False:
        # Only entry is the 'No device' entry
        model.clear()

    newobj.connect("media-added", mediadev_media_changed, widget)
    newobj.connect("media-removed", mediadev_media_changed, widget)

    # Brand new device
    row = [None, None, None, None, None, None]
    set_row_from_object(row, newobj)
    model.append(row)

    mediadev_set_default_selection(widget)

def mediadev_media_changed(newobj, widget):
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

    mediadev_set_default_selection(widget)

def mediadev_set_default_selection(widget):
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

def build_shutdown_button_menu(widget, shutdown_cb, reboot_cb,
                               destroy_cb, save_cb):
    icon_name = util.running_config.get_shutdown_icon_name()
    widget.set_icon_name(icon_name)
    menu = gtk.Menu()
    widget.set_menu(menu)

    rebootimg = gtk.image_new_from_icon_name(icon_name, gtk.ICON_SIZE_MENU)
    shutdownimg = gtk.image_new_from_icon_name(icon_name, gtk.ICON_SIZE_MENU)
    destroyimg = gtk.image_new_from_icon_name(icon_name, gtk.ICON_SIZE_MENU)
    saveimg = gtk.image_new_from_icon_name(gtk.STOCK_SAVE, gtk.ICON_SIZE_MENU)

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

    sep = gtk.SeparatorMenuItem()
    sep.show()
    menu.add(sep)

    save = gtk.ImageMenuItem(_("Sa_ve"))
    save.set_image(saveimg)
    save.show()
    save.connect("activate", save_cb)
    menu.add(save)

#####################################
# Path permissions checker for qemu #
#####################################
def check_path_search_for_qemu(parent, conn, path):
    set_error_parent(parent)

    if conn.is_remote() or not conn.is_qemu_system():
        return

    user = util.running_config.default_qemu_user

    skip_paths = util.running_config.get_perms_fix_ignore()
    broken_paths = VirtualDisk.check_path_search_for_user(conn.vmm, path, user)
    for p in broken_paths:
        if p in skip_paths:
            broken_paths.remove(p)

    if not broken_paths:
        return

    logging.debug("No search access for dirs: %s", broken_paths)
    resp, chkres = err_dial.warn_chkbox(
                    _("The emulator may not have search permissions "
                      "for the path '%s'.") % path,
                    _("Do you want to correct this now?"),
                    _("Don't ask about these directories again."),
                    buttons=gtk.BUTTONS_YES_NO)

    if chkres:
        util.running_config.add_perms_fix_ignore(broken_paths)
    if not resp:
        return

    logging.debug("Attempting to correct permission issues.")
    errors = VirtualDisk.fix_path_search_for_user(conn.vmm, path, user)
    if not errors:
        return

    errmsg = _("Errors were encountered changing permissions for the "
               "following directories:")
    details = ""
    for path, error in errors.items():
        if path not in broken_paths:
            continue
        details += "%s : %s\n" % (path, error)

    logging.debug("Permission errors:\n%s", details)

    ignore, chkres = err_dial.err_chkbox(errmsg, details,
                         _("Don't ask about these directories again."))

    if chkres:
        util.running_config.add_perms_fix_ignore(errors.keys())

######################################
# Interface startmode widget builder #
######################################

def build_startmode_combo(start_list):
    start_model = gtk.ListStore(str)
    start_list.set_model(start_model)
    text = gtk.CellRendererText()
    start_list.pack_start(text, True)
    start_list.add_attribute(text, 'text', 0)
    start_model.append(["none"])
    start_model.append(["onboot"])
    start_model.append(["hotplug"])


#########################
# Console keycombo menu #
#########################

def build_keycombo_menu(cb):
    menu = gtk.Menu()

    def make_item(name, combo):
        item = gtk.MenuItem(name, use_underline=True)
        item.connect("activate", cb, combo)

        menu.add(item)

    make_item("Ctrl+Alt+_Backspace", ["Control_L", "Alt_L", "BackSpace"])
    make_item("Ctrl+Alt+_Delete", ["Control_L", "Alt_L", "Delete"])
    menu.add(gtk.SeparatorMenuItem())

    for i in range(1, 13):
        make_item("Ctrl+Alt+F_%d" % i, ["Control_L", "Alt_L", "F%d" % i])
    menu.add(gtk.SeparatorMenuItem())

    make_item("_Printscreen", ["Print"])

    menu.show_all()
    return menu

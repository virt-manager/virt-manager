#
# Copyright (C) 2009, 2013 Red Hat, Inc.
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

# pylint: disable=E0611
from gi.repository import GObject
from gi.repository import Gtk
# pylint: enable=E0611

import libvirt

import virtinst
from virtManager import config

OPTICAL_DEV_PATH = 0
OPTICAL_LABEL = 1
OPTICAL_IS_MEDIA_PRESENT = 2
OPTICAL_DEV_KEY = 3
OPTICAL_MEDIA_KEY = 4
OPTICAL_IS_VALID = 5

try:
    import gi
    gi.check_version("3.7.4")
    can_set_row_none = True
except (ValueError, AttributeError):
    can_set_row_none = False

vm_status_icons = {
    libvirt.VIR_DOMAIN_BLOCKED: "state_running",
    libvirt.VIR_DOMAIN_CRASHED: "state_shutoff",
    libvirt.VIR_DOMAIN_PAUSED: "state_paused",
    libvirt.VIR_DOMAIN_RUNNING: "state_running",
    libvirt.VIR_DOMAIN_SHUTDOWN: "state_shutoff",
    libvirt.VIR_DOMAIN_SHUTOFF: "state_shutoff",
    libvirt.VIR_DOMAIN_NOSTATE: "state_running",
    # VIR_DOMAIN_PMSUSPENDED
    7: "state_paused",
}


############################################################
# Helpers for shared storage UI between create/addhardware #
############################################################

def set_sparse_tooltip(widget):
    sparse_str = _("Fully allocating storage may take longer now, "
                   "but the OS install phase will be quicker. \n\n"
                   "Skipping allocation can also cause space issues on "
                   "the host machine, if the maximum image size exceeds "
                   "available storage space. \n\n"
                   "Tip: Storage format qcow2 and qed "
                   "do not support full allocation.")
    widget.set_tooltip_text(sparse_str)


def host_disk_space(conn):
    pool = get_default_pool(conn)
    path = get_default_dir(conn)

    avail = 0
    if pool and pool.is_active():
        # FIXME: make sure not inactive?
        # FIXME: use a conn specific function after we send pool-added
        pool.refresh()
        avail = int(pool.get_available())

    elif not conn.is_remote() and os.path.exists(path):
        vfs = os.statvfs(os.path.dirname(path))
        avail = vfs[statvfs.F_FRSIZE] * vfs[statvfs.F_BAVAIL]

    return float(avail / 1024.0 / 1024.0 / 1024.0)


def update_host_space(conn, widget):
    try:
        max_storage = host_disk_space(conn)
    except:
        logging.exception("Error determining host disk space")
        return

    def pretty_storage(size):
        return "%.1f GB" % float(size)

    hd_label = ("%s available in the default location" %
                pretty_storage(max_storage))
    hd_label = ("<span color='#484848'>%s</span>" % hd_label)
    widget.set_markup(hd_label)


def check_default_pool_active(err, conn):
    default_pool = get_default_pool(conn)
    if default_pool and not default_pool.is_active():
        res = err.yes_no(_("Default pool is not active."),
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
            return err.show_err(_("Could not start storage_pool "
                                  "'%s': %s") %
                                (default_pool.get_name(), str(e)))
    return True


#####################################################
# Hardware model list building (for details, addhw) #
#####################################################

def set_combo_text_column(combo, col):
    if combo.get_has_entry():
        combo.set_entry_text_column(col)
    else:
        text = Gtk.CellRendererText()
        combo.pack_start(text, True)
        combo.add_attribute(text, 'text', col)


def build_video_combo(vm, combo, no_default=None):
    model = Gtk.ListStore(str, str)
    combo.set_model(model)
    set_combo_text_column(combo, 1)
    combo.get_model().set_sort_column_id(1, Gtk.SortType.ASCENDING)

    populate_video_combo(vm, combo, no_default)


def populate_video_combo(vm, combo, no_default=None):
    model = combo.get_model()
    has_spice = bool([g for g in vm.get_graphics_devices()
                      if g.type == g.TYPE_SPICE])
    has_qxl = bool([v for v in vm.get_video_devices()
                    if v.model == "qxl"])

    model.clear()
    tmpdev = virtinst.VirtualVideoDevice(vm.conn.get_backend())
    for m in tmpdev.MODELS:
        if not vm.rhel6_defaults():
            if m == "qxl" and not has_spice and not has_qxl:
                # Only list QXL video option when VM has SPICE video
                continue

        if m == tmpdev.MODEL_DEFAULT and no_default:
            continue
        model.append([m, tmpdev.pretty_model(m)])

    if len(model) > 0:
        combo.set_active(0)


def build_sound_combo(vm, combo, no_default=False):
    model = Gtk.ListStore(str)
    combo.set_model(model)
    set_combo_text_column(combo, 0)
    model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

    disable_rhel = not vm.rhel6_defaults()
    rhel_soundmodels = ["ich6", "ac97"]

    for m in virtinst.VirtualAudio.MODELS:
        if m == virtinst.VirtualAudio.MODEL_DEFAULT and no_default:
            continue

        if (disable_rhel and m not in rhel_soundmodels):
            continue

        model.append([m])
    if len(model) > 0:
        combo.set_active(0)


def build_watchdogmodel_combo(vm, combo, no_default=False):
    ignore = vm
    model = Gtk.ListStore(str)
    combo.set_model(model)
    set_combo_text_column(combo, 0)
    model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

    for m in virtinst.VirtualWatchdog.MODELS:
        if m == virtinst.VirtualAudio.MODEL_DEFAULT and no_default:
            continue
        model.append([m])
    if len(model) > 0:
        combo.set_active(0)


def build_watchdogaction_combo(vm, combo, no_default=False):
    ignore = vm
    model = Gtk.ListStore(str, str)
    combo.set_model(model)
    set_combo_text_column(combo, 1)
    model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

    for m in virtinst.VirtualWatchdog.ACTIONS:
        if m == virtinst.VirtualWatchdog.ACTION_DEFAULT and no_default:
            continue
        model.append([m, virtinst.VirtualWatchdog.get_action_desc(m)])
    if len(model) > 0:
        combo.set_active(0)


def build_source_mode_combo(vm, combo):
    model = Gtk.ListStore(str, str)
    combo.set_model(model)
    set_combo_text_column(combo, 1)

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
    model = Gtk.ListStore(str, str)
    combo.set_model(model)
    set_combo_text_column(combo, 1)
    model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

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


def build_redir_type_combo(vm, combo):
    model = Gtk.ListStore(str, str, bool)
    combo.set_model(model)
    set_combo_text_column(combo, 1)

    populate_redir_type_combo(vm, combo)
    combo.set_active(0)


def populate_redir_type_combo(vm, combo):
    ignore = vm
    model = combo.get_model()
    model.clear()

    # [xml value, label, conn details]
    model.append(["spicevmc", "Spice channel", False])
    model.append(["tcp", "TCP", True])


def build_tpm_type_combo(vm, combo):
    model = Gtk.ListStore(str, str)
    combo.set_model(model)
    set_combo_text_column(combo, 1)
    model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

    populate_tpm_type_combo(vm, combo)

    idx = -1
    for rowid in range(len(combo.get_model())):
        idx = 0
        row = combo.get_model()[rowid]
        if row[0] == virtinst.VirtualTPMDevice.TYPE_DEFAULT:
            idx = rowid
            break
    combo.set_active(idx)


def populate_tpm_type_combo(vm, combo):
    ignore = vm
    types = combo.get_model()
    types.clear()

    # [xml value, label]
    for t in virtinst.VirtualTPMDevice.TYPES:
        types.append([t, virtinst.VirtualTPMDevice.get_pretty_type(t)])


def build_netmodel_combo(vm, combo):
    model = Gtk.ListStore(str, str)
    combo.set_model(model)
    set_combo_text_column(combo, 1)
    model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

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


def build_cache_combo(vm, combo):
    ignore = vm
    model = Gtk.ListStore(str, str)
    combo.set_model(model)
    set_combo_text_column(combo, 1)

    combo.set_active(-1)
    for m in virtinst.VirtualDisk.cache_types:
        model.append([m, m])

    _iter = model.insert(0, [None, "default"])
    combo.set_active_iter(_iter)


def build_io_combo(vm, combo, no_default=False):
    ignore = vm
    model = Gtk.ListStore(str, str)
    combo.set_model(model)
    set_combo_text_column(combo, 1)
    model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

    combo.set_active(-1)
    for m in virtinst.VirtualDisk.io_modes:
        model.append([m, m])

    if not no_default:
        model.append([None, "default"])
    combo.set_active(0)


def build_disk_bus_combo(vm, combo, no_default=False):
    ignore = vm
    model = Gtk.ListStore(str, str)
    combo.set_model(model)
    set_combo_text_column(combo, 1)
    model.set_sort_column_id(1, Gtk.SortType.ASCENDING)

    if not no_default:
        model.append([None, "default"])
    combo.set_active(-1)


def build_vnc_keymap_combo(vm, combo, no_default=False):
    ignore = vm
    model = Gtk.ListStore(str, str)
    combo.set_model(model)
    set_combo_text_column(combo, 1)

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

def update_storage_format_combo(vm, combo, create):
    model = Gtk.ListStore(str)
    combo.set_model(model)
    set_combo_text_column(combo, 0)

    formats = ["raw", "qcow2", "qed"]
    no_create_formats = []
    if vm.rhel6_defaults():
        formats.append("vmdk")
        no_create_formats.append("vdi")

    for m in formats:
        model.append([m])
    if not create:
        for m in no_create_formats:
            model.append([m])

    if create:
        combo.set_active(0)


#######################################################################
# Widgets for listing network device options (in create, addhardware) #
#######################################################################

def pretty_network_desc(nettype, source=None, netobj=None):
    if nettype == virtinst.VirtualNetworkInterface.TYPE_USER:
        return _("Usermode networking")

    extra = None
    if nettype == virtinst.VirtualNetworkInterface.TYPE_BRIDGE:
        ret = _("Bridge")
    elif nettype == virtinst.VirtualNetworkInterface.TYPE_VIRTUAL:
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


def init_network_list(net_list, bridge_box, source_mode_combo=None,
                      vport_expander=None):
    # [ network type, source name, label, sensitive?, net is active,
    #   manual bridge, net instance]
    net_model = Gtk.ListStore(str, str, str, bool, bool, bool, object)
    net_list.set_model(net_model)

    net_list.connect("changed", net_list_changed, bridge_box,
                     source_mode_combo, vport_expander)

    text = Gtk.CellRendererText()
    net_list.pack_start(text, True)
    net_list.add_attribute(text, 'text', 2)
    net_list.add_attribute(text, 'sensitive', 3)


def net_list_changed(net_list, bridge_box,
                     source_mode_combo, vport_expander):
    active = net_list.get_active()
    if active < 0:
        return

    if not bridge_box:
        return

    row = net_list.get_model()[active]

    if source_mode_combo is not None:
        doshow = (row[0] == virtinst.VirtualNetworkInterface.TYPE_DIRECT)
        set_grid_row_visible(source_mode_combo, doshow)
        vport_expander.set_visible(doshow)

    show_bridge = row[5]
    set_grid_row_visible(bridge_box, show_bridge)


def get_network_selection(net_list, bridge_entry):
    idx = net_list.get_active()
    if idx == -1:
        return None, None

    row = net_list.get_model()[net_list.get_active()]
    net_type = row[0]
    net_src = row[1]
    net_check_bridge = row[5]

    if net_check_bridge and bridge_entry:
        net_type = virtinst.VirtualNetworkInterface.TYPE_BRIDGE
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
        rowlist = [indict[k] for k in keylist]
        for row in rowlist:
            model.append(row)

    # For qemu:///session
    if conn.is_qemu_session():
        nettype = virtinst.VirtualNetworkInterface.TYPE_USER
        r = build_row(nettype, None, pretty_network_desc(nettype), True, True)
        model.append(r)
        set_active(0)
        return

    hasNet = False
    netIdxLabel = None
    # Virtual Networks
    for uuid in conn.list_net_uuids():
        net = conn.get_net(uuid)
        nettype = virtinst.VirtualNetworkInterface.TYPE_VIRTUAL

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

    vnet_taps = []
    for vm in conn.vms.values():
        for nic in vm.get_network_devices(refresh_if_nec=False):
            if nic.target_dev and nic.target_dev not in vnet_taps:
                vnet_taps.append(nic.target_dev)

    skip_ifaces = ["lo"]

    # Physical devices
    hasShared = False
    brIdxLabel = None
    for name in conn.list_net_device_paths():
        br = conn.get_net_device(name)
        bridge_name = br.get_bridge()
        nettype = virtinst.VirtualNetworkInterface.TYPE_BRIDGE

        if ((bridge_name in vnet_bridges) or
            (br.get_name() in vnet_bridges) or
            (br.get_name() in vnet_taps) or
            (br.get_name() in [v + "-nic" for v in vnet_bridges]) or
            (br.get_name() in skip_ifaces)):
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
            if (show_direct_interfaces and
                conn.check_conn_support(
                    conn.SUPPORT_CONN_HV_DIRECT_INTERFACE)):
                sensitive = True
                nettype = virtinst.VirtualNetworkInterface.TYPE_DIRECT
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
            if row[3] is True:
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


def validate_network(err, conn, nettype, devname, macaddr, model=None):
    net = None

    if nettype is None:
        return None

    # Make sure VirtualNetwork is running
    netobj = None
    if nettype == virtinst.VirtualNetworkInterface.TYPE_VIRTUAL:
        for net in conn.nets.values():
            if net.get_name() == devname:
                netobj = net
                break

    if netobj and not netobj.is_active():
        res = err.yes_no(_("Virtual Network is not active."),
                         _("Virtual Network '%s' is not active. "
                           "Would you like to start the network "
                           "now?") % devname)
        if not res:
            return False

        # Try to start the network
        try:
            netobj.start()
            netobj.tick()
            logging.info("Started network '%s'", devname)
        except Exception, e:
            return err.show_err(_("Could not start virtual network "
                                  "'%s': %s") % (devname, str(e)))

    # Create network device
    try:
        net = virtinst.VirtualNetworkInterface(conn.get_backend())
        net.type = nettype
        net.source = devname
        net.macaddr = macaddr
        net.model = model
        if net.model == "spapr-vlan":
            net.address.set_addrstr("spapr-vio")


    except Exception, e:
        return err.val_err(_("Error with network parameters."), e)

    # Make sure there is no mac address collision
    isfatal, errmsg = net.is_conflict_net(conn.get_backend(), net.macaddr)
    if isfatal:
        return err.val_err(_("Mac address collision."), errmsg)
    elif errmsg is not None:
        retv = err.yes_no(_("Mac address collision."),
                          _("%s Are you sure you want to use this "
                            "address?") % errmsg)
        if not retv:
            return False

    return net


############################################
# Populate media widget (choosecd, create) #
############################################

def init_mediadev_combo(widget):
    # [Device path, pretty label, has_media?, device key, media key,
    #  vmmMediaDevice, is valid device]
    model = Gtk.ListStore(str, str, bool, str, str, bool)
    widget.set_model(model)
    model.clear()

    text = Gtk.CellRendererText()
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
    if model is None:
        return

    if len(model) == 1 and model[0][OPTICAL_IS_VALID] is False:
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
        if row[OPTICAL_IS_MEDIA_PRESENT] is True:
            widget.set_active(idx)
            return
        idx += 1

    widget.set_active(-1)


####################################################################
# Build toolbar shutdown button menu (manager and details toolbar) #
####################################################################

class _VMMenu(Gtk.Menu):
    # pylint: disable=E1101
    # pylint can't detect functions we inheirit from Gtk, ex self.add

    def __init__(self, src, current_vm_cb, show_open=True):
        Gtk.Menu.__init__(self)
        self._parent = src
        self._current_vm_cb = current_vm_cb
        self._show_open = show_open

        self._init_state()

    def _add_action(self, label, signal,
                    iconname="system-shutdown", addcb=True):
        if label.startswith("gtk-"):
            item = Gtk.ImageMenuItem.new_from_stock(label, None)
        else:
            item = Gtk.ImageMenuItem.new_with_mnemonic(label)

        if iconname:
            if iconname.startswith("gtk-"):
                icon = Gtk.Image.new_from_stock(iconname, Gtk.IconSize.MENU)
            else:
                icon = Gtk.Image.new_from_icon_name(iconname,
                                                    Gtk.IconSize.MENU)
            item.set_image(icon)

        item.vmm_widget_name = signal
        if addcb:
            item.connect("activate", self._action_cb)
        self.add(item)
        return item

    def _action_cb(self, src):
        vm = self._current_vm_cb()
        if not vm:
            return
        self._parent.emit("action-%s-domain" % src.vmm_widget_name,
                          vm.conn.get_uri(), vm.get_uuid())

    def _init_state(self):
        raise NotImplementedError()
    def update_widget_states(self, vm):
        raise NotImplementedError()


class VMShutdownMenu(_VMMenu):
    # pylint: disable=E1101
    # pylint can't detect functions we inheirit from Gtk, ex self.add

    def _init_state(self):
        self._add_action(_("_Reboot"), "reboot")
        self._add_action(_("_Shut Down"), "shutdown")
        self._add_action(_("F_orce Reset"), "reset")
        self._add_action(_("_Force Off"), "destroy")
        self.add(Gtk.SeparatorMenuItem())
        self._add_action(_("Sa_ve"), "save", iconname=Gtk.STOCK_SAVE)

        self.show_all()

    def update_widget_states(self, vm):
        statemap = {
            "reboot": bool(vm and vm.is_stoppable()),
            "shutdown": bool(vm and vm.is_stoppable()),
            "reset": bool(vm and vm.is_stoppable()),
            "save": bool(vm and vm.is_destroyable()),
            "destroy": bool(vm and vm.is_destroyable()),
        }

        for child in self.get_children():
            name = getattr(child, "vmm_widget_name", None)
            if name in statemap:
                child.set_sensitive(statemap[name])


class VMActionMenu(_VMMenu):
    # pylint: disable=E1101
    # pylint can't detect functions we inheirit from Gtk, ex self.add

    def _init_state(self):
        self._add_action(_("_Run"), "run", Gtk.STOCK_MEDIA_PLAY)
        self._add_action(_("_Pause"), "suspend", Gtk.STOCK_MEDIA_PAUSE)
        self._add_action(_("R_esume"), "resume", Gtk.STOCK_MEDIA_PAUSE)
        s = self._add_action(_("_Shut Down"), "shutdown", addcb=False)
        s.set_submenu(VMShutdownMenu(self._parent, self._current_vm_cb))

        self.add(Gtk.SeparatorMenuItem())
        self._add_action(_("Clone..."), "clone", None)
        self._add_action(_("Migrate..."), "migrate", None)
        self._add_action(_("_Delete"), "delete", Gtk.STOCK_DELETE)

        if self._show_open:
            self.add(Gtk.SeparatorMenuItem())
            self._add_action(Gtk.STOCK_OPEN, "show", None)

        self.show_all()

    def update_widget_states(self, vm):
        statemap = {
            "run": bool(vm and vm.is_runable()),
            "shutdown": bool(vm and vm.is_stoppable()),
            "suspend": bool(vm and vm.is_stoppable()),
            "resume": bool(vm and vm.is_paused()),
            "migrate": bool(vm and vm.is_stoppable()),
            "clone": bool(vm and not vm.is_read_only()),
        }
        vismap = {
            "suspend": bool(vm and not vm.is_paused()),
            "resume": bool(vm and vm.is_paused()),
        }

        for child in self.get_children():
            name = getattr(child, "vmm_widget_name", None)
            if hasattr(child, "update_widget_states"):
                child.update_widget_states(vm)
            if name in statemap:
                child.set_sensitive(statemap[name])
            if name in vismap:
                child.set_visible(vismap[name])

    def change_run_text(self, text):
        for child in self.get_children():
            if getattr(child, "vmm_widget_name", None) == "run":
                child.get_child().set_label(text)


#####################################
# Path permissions checker for qemu #
#####################################

def check_path_search_for_qemu(err, conn, path):
    if conn.is_remote() or not conn.is_qemu_system():
        return

    user = config.running_config.default_qemu_user

    skip_paths = config.running_config.get_perms_fix_ignore()
    broken_paths = virtinst.VirtualDisk.check_path_search_for_user(
                                                          conn.get_backend(),
                                                          path, user)
    for p in broken_paths:
        if p in skip_paths:
            broken_paths.remove(p)

    if not broken_paths:
        return

    logging.debug("No search access for dirs: %s", broken_paths)
    resp, chkres = err.warn_chkbox(
                    _("The emulator may not have search permissions "
                      "for the path '%s'.") % path,
                    _("Do you want to correct this now?"),
                    _("Don't ask about these directories again."),
                    buttons=Gtk.ButtonsType.YES_NO)

    if chkres:
        config.running_config.add_perms_fix_ignore(broken_paths)
    if not resp:
        return

    logging.debug("Attempting to correct permission issues.")
    errors = virtinst.VirtualDisk.fix_path_search_for_user(conn.get_backend(),
                                                           path, user)
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

    ignore, chkres = err.err_chkbox(errmsg, details,
                         _("Don't ask about these directories again."))

    if chkres:
        config.running_config.add_perms_fix_ignore(errors.keys())


######################################
# Interface startmode widget builder #
######################################

def build_startmode_combo(combo):
    model = Gtk.ListStore(str)
    combo.set_model(model)
    set_combo_text_column(combo, 0)

    model.append(["none"])
    model.append(["onboot"])
    model.append(["hotplug"])


#########################
# Console keycombo menu #
#########################

def build_keycombo_menu(cb):
    menu = Gtk.Menu()

    def make_item(name, combo):
        item = Gtk.MenuItem.new_with_mnemonic(name)
        item.connect("activate", cb, combo)

        menu.add(item)

    make_item("Ctrl+Alt+_Backspace", ["Control_L", "Alt_L", "BackSpace"])
    make_item("Ctrl+Alt+_Delete", ["Control_L", "Alt_L", "Delete"])
    menu.add(Gtk.SeparatorMenuItem())

    for i in range(1, 13):
        make_item("Ctrl+Alt+F_%d" % i, ["Control_L", "Alt_L", "F%d" % i])
    menu.add(Gtk.SeparatorMenuItem())

    make_item("_Printscreen", ["Print"])

    menu.show_all()
    return menu


#############
# Misc bits #
#############

def spin_get_helper(widget):
    adj = widget.get_adjustment()
    txt = widget.get_text()

    try:
        ret = int(txt)
    except:
        ret = adj.get_value()
    return ret


def get_ideal_path_info(conn, name):
    path = get_default_dir(conn)
    suffix = ".img"
    return (path, name, suffix)


def get_ideal_path(conn, name):
    target, name, suffix = get_ideal_path_info(conn, name)
    return os.path.join(target, name) + suffix


def get_default_pool(conn):
    pool = None
    for uuid in conn.list_pool_uuids():
        p = conn.get_pool(uuid)
        if p.get_name() == "default":
            pool = p

    return pool


def get_default_dir(conn):
    pool = get_default_pool(conn)

    if pool:
        return pool.get_target_path()
    else:
        return config.running_config.get_default_image_dir(conn)


def get_default_path(conn, name, collidelist=None):
    collidelist = collidelist or []
    pool = get_default_pool(conn)

    default_dir = get_default_dir(conn)

    def path_exists(p):
        return os.path.exists(p) or p in collidelist

    if not pool:
        # Use old generating method
        origf = os.path.join(default_dir, name + ".img")
        f = origf

        n = 1
        while path_exists(f) and n < 100:
            f = os.path.join(default_dir, name +
                             "-" + str(n) + ".img")
            n += 1

        if path_exists(f):
            f = origf

        path = f
    else:
        target, ignore, suffix = get_ideal_path_info(conn, name)

        # Sanitize collidelist to work with the collision checker
        newcollidelist = []
        for c in collidelist:
            if c and os.path.dirname(c) == pool.get_target_path():
                newcollidelist.append(os.path.basename(c))

        path = virtinst.StorageVolume.find_free_name(
            pool.get_backend(), name,
            suffix=suffix, collidelist=newcollidelist)

        path = os.path.join(target, path)

    return path


def browse_local(parent, dialog_name, conn, start_folder=None,
                 _type=None, dialog_type=None,
                 confirm_func=None, browse_reason=None,
                 choose_button=None, default_name=None):
    """
    Helper function for launching a filechooser

    @param parent: Parent window for the filechooser
    @param dialog_name: String to use in the title bar of the filechooser.
    @param conn: vmmConnection used by calling class
    @param start_folder: Folder the filechooser is viewing at startup
    @param _type: File extension to filter by (e.g. "iso", "png")
    @param dialog_type: Maps to FileChooserDialog 'action'
    @param confirm_func: Optional callback function if file is chosen.
    @param browse_reason: The vmmConfig.CONFIG_DIR* reason we are browsing.
        If set, this will override the 'folder' parameter with the gconf
        value, and store the user chosen path.

    """
    # Initial setup
    overwrite_confirm = False

    if dialog_type is None:
        dialog_type = Gtk.FileChooserAction.OPEN
    if dialog_type == Gtk.FileChooserAction.SAVE:
        if choose_button is None:
            choose_button = Gtk.STOCK_SAVE
            overwrite_confirm = True

    if choose_button is None:
        choose_button = Gtk.STOCK_OPEN

    fcdialog = Gtk.FileChooserDialog(title=dialog_name,
                                parent=parent,
                                action=dialog_type,
                                buttons=(Gtk.STOCK_CANCEL,
                                         Gtk.ResponseType.CANCEL,
                                         choose_button,
                                         Gtk.ResponseType.ACCEPT))
    fcdialog.set_default_response(Gtk.ResponseType.ACCEPT)

    if default_name:
        fcdialog.set_current_name(default_name)

    # If confirm is set, warn about a file overwrite
    if confirm_func:
        overwrite_confirm = True
        fcdialog.connect("confirm-overwrite", confirm_func)
    fcdialog.set_do_overwrite_confirmation(overwrite_confirm)

    # Set file match pattern (ex. *.png)
    if _type is not None:
        pattern = _type
        name = None
        if type(_type) is tuple:
            pattern = _type[0]
            name = _type[1]

        f = Gtk.FileFilter()
        f.add_pattern("*." + pattern)
        if name:
            f.set_name(name)
        fcdialog.set_filter(f)

    # Set initial dialog folder
    if browse_reason:
        start_folder = config.running_config.get_default_directory(conn,
                                                            browse_reason)

    if start_folder is not None:
        if os.access(start_folder, os.R_OK):
            fcdialog.set_current_folder(start_folder)

    # Run the dialog and parse the response
    ret = None
    if fcdialog.run() == Gtk.ResponseType.ACCEPT:
        ret = fcdialog.get_filename()
    fcdialog.destroy()

    # Store the chosen directory in gconf if necessary
    if ret and browse_reason and not ret.startswith("/dev"):
        config.running_config.set_default_directory(os.path.dirname(ret),
                                             browse_reason)
    return ret


def pretty_hv(gtype, domtype):
    """
    Convert XML <domain type='foo'> and <os><type>bar</type>
    into a more human relevant string.
    """

    gtype = gtype.lower()
    domtype = domtype.lower()

    label = domtype
    if domtype == "kvm":
        if gtype == "xen":
            label = "xenner"
    elif domtype == "xen":
        if gtype == "xen":
            label = "xen (paravirt)"
        elif gtype == "hvm":
            label = "xen (fullvirt)"
    elif domtype == "test":
        if gtype == "xen":
            label = "test (xen)"
        elif gtype == "hvm":
            label = "test (hvm)"

    return label


def iface_in_use_by(conn, name):
    use_str = ""
    for i in conn.list_interface_names():
        iface = conn.get_interface(i)
        if name in iface.get_slave_names():
            if use_str:
                use_str += ", "
            use_str += iface.get_name()

    return use_str


def chkbox_helper(src, getcb, setcb, text1, text2=None,
                  alwaysrecord=False,
                  default=True,
                  chktext=_("Don't ask me again")):
    """
    Helper to prompt user about proceeding with an operation
    Returns True if the 'yes' or 'ok' button was selected, False otherwise

    @alwaysrecord: Don't require user to select 'yes' to record chkbox value
    @default: What value to return if getcb tells us not to prompt
    """
    do_prompt = getcb()
    if not do_prompt:
        return default

    res = src.err.warn_chkbox(text1=text1, text2=text2,
                              chktext=chktext,
                              buttons=Gtk.ButtonsType.YES_NO)
    response, skip_prompt = res
    if alwaysrecord or response:
        setcb(not skip_prompt)

    return response


def get_list_selection(widget):
    selection = widget.get_selection()
    active = selection.get_selected()

    treestore, treeiter = active
    if treeiter is not None:
        return treestore[treeiter]
    return None


def set_list_selection(widget, rownum):
    path = str(rownum)
    selection = widget.get_selection()

    selection.unselect_all()
    widget.set_cursor(path)
    selection.select_path(path)


def set_row_selection(listwidget, prevkey):
    model = listwidget.get_model()
    _iter = None
    if prevkey:
        for row in model:
            if row[0] == prevkey:
                _iter = row.iter
                break
    if not _iter:
        _iter = model.get_iter_first()
    if _iter:
        listwidget.get_selection().select_iter(_iter)
    listwidget.get_selection().emit("changed")


def child_get_property(parent, child, propname):
    # Wrapper for child_get_property, which pygobject doesn't properly
    # introspect
    value = GObject.Value()
    value.init(GObject.TYPE_INT)
    parent.child_get_property(child, propname, value)
    return value.get_int()


def set_grid_row_visible(child, visible):
    # For the passed widget, find its parent GtkGrid, and hide/show all
    # elements that are in the same row as it. Simplifies having to name
    # every element in a row when we want to dynamically hide things
    # based on UI interraction

    parent = child.get_parent()
    if not type(parent) is Gtk.Grid:
        raise RuntimeError("Programming error, parent must be grid, "
                           "not %s" % type(parent))

    row = child_get_property(parent, child, "top-attach")
    for child in parent.get_children():
        if child_get_property(parent, child, "top-attach") == row:
            child.set_visible(visible)


def default_uri(always_system=False):
    if os.path.exists('/var/lib/xend'):
        if (os.path.exists('/dev/xen/evtchn') or
            os.path.exists("/proc/xen")):
            return 'xen:///'

    if (os.path.exists("/usr/bin/qemu") or
        os.path.exists("/usr/bin/qemu-kvm") or
        os.path.exists("/usr/bin/kvm") or
        os.path.exists("/usr/libexec/qemu-kvm")):
        if always_system or os.geteuid() == 0:
            return "qemu:///system"
        else:
            return "qemu:///session"
    return None


def exception_is_libvirt_error(e, error):
    return (hasattr(libvirt, error) and
            e.get_error_code() == getattr(libvirt, error))


def log_redefine_xml_diff(origxml, newxml):
    if origxml == newxml:
        logging.debug("Redefine requested, but XML didn't change!")
        return

    import difflib
    diff = "".join(difflib.unified_diff(origxml.splitlines(1),
                                        newxml.splitlines(1),
                                        fromfile="Original XML",
                                        tofile="New XML"))
    logging.debug("Redefining with XML diff:\n%s", diff)

#
# Copyright (C) 2009, 2013, 2014 Red Hat, Inc.
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
import pwd

# pylint: disable=E0611
from gi.repository import Gtk
# pylint: enable=E0611

import virtinst
from virtManager import config
from virtManager import uiutil


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


def _get_default_dir(conn):
    pool = conn.get_default_pool()
    if pool:
        return pool.get_target_path()
    return config.running_config.get_default_image_dir(conn)


def host_disk_space(conn):
    pool = conn.get_default_pool()
    path = _get_default_dir(conn)

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
    default_pool = conn.get_default_pool()
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


def _get_ideal_path_info(conn, name):
    path = _get_default_dir(conn)
    suffix = ".img"
    return (path, name, suffix)


def get_ideal_path(conn, name):
    target, name, suffix = _get_ideal_path_info(conn, name)
    return os.path.join(target, name) + suffix


def get_default_path(conn, name, collidelist=None):
    collidelist = collidelist or []
    pool = conn.get_default_pool()

    default_dir = _get_default_dir(conn)

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
        target, ignore, suffix = _get_ideal_path_info(conn, name)

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


def check_path_search_for_qemu(err, conn, path):
    if conn.is_remote() or not conn.is_qemu_system():
        return

    user = config.running_config.default_qemu_user

    for i in conn.caps.host.secmodels:
        if i.model == "dac":
            label = i.baselabels.get("kvm") or i.baselabels.get("qemu")
            if not label:
                continue
            pwuid = pwd.getpwuid(int(label.split(":")[0].replace("+", "")))
            if pwuid:
                user = pwuid[0]

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


#########################################
# VM <interface> device listing helpers #
#########################################

def _net_list_changed(net_list, bridge_box,
                     source_mode_combo, vport_expander):
    active = net_list.get_active()
    if active < 0:
        return

    if not bridge_box:
        return

    row = net_list.get_model()[active]

    if source_mode_combo is not None:
        doshow = (row[0] == virtinst.VirtualNetworkInterface.TYPE_DIRECT)
        uiutil.set_grid_row_visible(source_mode_combo, doshow)
        vport_expander.set_visible(doshow)

    show_bridge = row[5]
    uiutil.set_grid_row_visible(bridge_box, show_bridge)


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


def build_network_list(net_list, bridge_box, source_mode_combo=None,
                      vport_expander=None):
    # [ network type, source name, label, sensitive?, net is active,
    #   manual bridge, net instance]
    net_model = Gtk.ListStore(str, str, str, bool, bool, bool, object)
    net_list.set_model(net_model)

    net_list.connect("changed", _net_list_changed, bridge_box,
                     source_mode_combo, vport_expander)

    text = Gtk.CellRendererText()
    net_list.pack_start(text, True)
    net_list.add_attribute(text, 'text', 2)
    net_list.add_attribute(text, 'sensitive', 3)


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
                conn.check_support(
                    conn.SUPPORT_CONN_DIRECT_INTERFACE)):
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

OPTICAL_DEV_PATH = 0
OPTICAL_LABEL = 1
OPTICAL_IS_MEDIA_PRESENT = 2
OPTICAL_DEV_KEY = 3
OPTICAL_MEDIA_KEY = 4
OPTICAL_IS_VALID = 5


def _set_mediadev_default(model):
    if len(model) == 0:
        model.append([None, _("No device present"), False, None, None, False])


def _set_mediadev_row_from_object(row, obj):
    row[OPTICAL_DEV_PATH] = obj.get_path()
    row[OPTICAL_LABEL] = obj.pretty_label()
    row[OPTICAL_IS_MEDIA_PRESENT] = obj.has_media()
    row[OPTICAL_DEV_KEY] = obj.get_key()
    row[OPTICAL_MEDIA_KEY] = obj.get_media_key()
    row[OPTICAL_IS_VALID] = True


def _mediadev_set_default_selection(widget):
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


def _mediadev_media_changed(newobj, widget):
    model = widget.get_model()
    active = widget.get_active()
    idx = 0

    # Search for the row with matching device node and
    # fill in info about inserted media. If model has no current
    # selection, select the new media.
    for row in model:
        if row[OPTICAL_DEV_PATH] == newobj.get_path():
            _set_mediadev_row_from_object(row, newobj)
            has_media = row[OPTICAL_IS_MEDIA_PRESENT]

            if has_media and active == -1:
                widget.set_active(idx)
            elif not has_media and active == idx:
                widget.set_active(-1)

        idx = idx + 1

    _mediadev_set_default_selection(widget)


def _mediadev_added(ignore_helper, newobj, widget, devtype):
    model = widget.get_model()

    if newobj.get_media_type() != devtype:
        return
    if model is None:
        return

    if len(model) == 1 and model[0][OPTICAL_IS_VALID] is False:
        # Only entry is the 'No device' entry
        model.clear()

    newobj.connect("media-added", _mediadev_media_changed, widget)
    newobj.connect("media-removed", _mediadev_media_changed, widget)

    # Brand new device
    row = [None, None, None, None, None, None]
    _set_mediadev_row_from_object(row, newobj)
    model.append(row)

    _mediadev_set_default_selection(widget)


def _mediadev_removed(ignore_helper, key, widget):
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

    _set_mediadev_default(model)
    _mediadev_set_default_selection(widget)


def build_mediadev_combo(widget):
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
    _set_mediadev_default(model)

    sigs.append(conn.connect("mediadev-added",
        _mediadev_added, widget, devtype))
    sigs.append(conn.connect("mediadev-removed", _mediadev_removed, widget))

    widget.set_active(-1)
    _mediadev_set_default_selection(widget)

    return sigs


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

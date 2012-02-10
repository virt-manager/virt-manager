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

import gtk

from virtManager.baseclass import vmmGObjectUI
from virtManager.asyncjob import vmmAsyncJob
from virtManager.storagebrowse import vmmStorageBrowser
from virtManager import util

import virtinst
from virtinst import CloneManager
from virtinst.CloneManager import CloneDesign
from virtinst import VirtualNetworkInterface

STORAGE_COMBO_CLONE = 0
STORAGE_COMBO_SHARE = 1
STORAGE_COMBO_SEP = 2
STORAGE_COMBO_DETAILS = 3

STORAGE_INFO_ORIG_PATH = 0
STORAGE_INFO_NEW_PATH = 1
STORAGE_INFO_TARGET = 2
STORAGE_INFO_SIZE = 3
STORAGE_INFO_DEVTYPE = 4
STORAGE_INFO_DO_CLONE = 5
STORAGE_INFO_CAN_CLONE = 6
STORAGE_INFO_CAN_SHARE = 7
STORAGE_INFO_DO_DEFAULT = 8
STORAGE_INFO_DEFINFO = 9
STORAGE_INFO_FAILINFO = 10
STORAGE_INFO_COMBO = 11
STORAGE_INFO_MANUAL_PATH = 12

NETWORK_INFO_LABEL = 0
NETWORK_INFO_ORIG_MAC = 1
NETWORK_INFO_NEW_MAC = 2

# XXX: Some method to check all storage size
# XXX: What to do for cleanup if clone fails?
# XXX: Disable mouse scroll for combo boxes

def can_we_clone(conn, vol, path):
    """Is the passed path even clone-able"""
    ret = True
    msg = None

    if not path:
        msg = _("No storage to clone.")

    elif vol:
        # Managed storage
        if not virtinst.Storage.is_create_vol_from_supported(conn.vmm):
            if conn.is_remote() or not os.access(path, os.R_OK):
                msg = _("Connection does not support managed storage cloning.")
    else:
        is_dev = path.startswith("/dev")
        if conn.is_remote():
            msg = _("Cannot clone unmanaged remote storage.")
        elif not os.access(path, os.R_OK):
            if is_dev:
                msg = _("Block devices to clone must be libvirt\n"
                        "managed storage volumes.")
            else:
                msg = _("No write access to parent directory.")
        elif not os.path.exists(path):
            msg = _("Path does not exist.")

    if msg:
        ret = False

    return (ret, msg)

def do_we_default(conn, vol, path, ro, shared, devtype):
    """ Returns (do we clone by default?, info string if not)"""
    ignore = conn
    info = ""

    def append_str(str1, str2, delim=", "):
        if not str2:
            return str1
        if str1:
            str1 += delim
        str1 += str2
        return str1

    if (devtype == virtinst.VirtualDisk.DEVICE_CDROM or
        devtype == virtinst.VirtualDisk.DEVICE_FLOPPY):
        info = append_str(info, _("Removable"))

    if ro:
        info = append_str(info, _("Read Only"))
    elif not vol and path and not os.access(path, os.W_OK):
        info = append_str(info, _("No write access"))

    if shared:
        info = append_str(info, _("Shareable"))

    return (not info, info)

class vmmCloneVM(vmmGObjectUI):
    def __init__(self, orig_vm):
        vmmGObjectUI.__init__(self, "vmm-clone.ui", "vmm-clone")
        self.orig_vm = orig_vm

        self.conn = self.orig_vm.conn
        self.clone_design = None

        self.storage_list = {}
        self.target_list = []

        self.net_list = {}
        self.mac_list = []

        self.storage_browser = None

        self.change_mac = self.widget("vmm-change-mac")
        self.change_mac.set_transient_for(self.topwin)

        self.change_storage = self.widget("vmm-change-storage")
        self.change_storage.set_transient_for(self.topwin)

        self.window.connect_signals({
            "on_clone_delete_event" : self.close,
            "on_clone_cancel_clicked" : self.close,
            "on_clone_ok_clicked" : self.finish,
            "on_clone_help_clicked" : self.show_help,

            # Change mac dialog
            "on_vmm_change_mac_delete_event": self.change_mac_close,
            "on_change_mac_cancel_clicked" : self.change_mac_close,
            "on_change_mac_ok_clicked" : self.change_mac_finish,

            # Change storage dialog
            "on_vmm_change_storage_delete_event": self.change_storage_close,
            "on_change_storage_cancel_clicked" : self.change_storage_close,
            "on_change_storage_ok_clicked" : self.change_storage_finish,
            "on_change_storage_doclone_toggled" : self.change_storage_doclone_toggled,

            "on_change_storage_browse_clicked" : self.change_storage_browse,
        })
        self.bind_escape_key_close()

        # XXX: Help docs useless/out of date
        self.widget("clone-help").hide()
        finish_img = gtk.image_new_from_stock(gtk.STOCK_NEW,
                                              gtk.ICON_SIZE_BUTTON)
        self.widget("clone-ok").set_image(finish_img)

        self.set_initial_state()

    def show(self, parent):
        logging.debug("Showing clone wizard")
        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.resize(1, 1)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing clone wizard")
        self.change_mac_close()
        self.change_storage_close()
        self.topwin.hide()

        self.orig_vm = None
        self.clone_design = None
        self.storage_list = {}
        self.target_list = []
        self.net_list = {}
        self.mac_list = []

        return 1

    def _cleanup(self):
        self.close()

        self.conn = None

        self.change_mac.destroy()
        self.change_mac = None

        self.change_storage.destroy()
        self.change_storage = None

        if self.storage_browser:
            self.storage_browser.cleanup()
            self.storage_browser = None

    def change_mac_close(self, ignore1=None, ignore2=None):
        self.change_mac.hide()
        return 1

    def change_storage_close(self, ignore1=None, ignore2=None):
        self.change_storage.hide()
        return 1


    # First time setup

    def set_initial_state(self):
        blue = gtk.gdk.color_parse("#0072A8")
        self.widget("clone-header").modify_bg(gtk.STATE_NORMAL, blue)

        box = self.widget("clone-vm-icon-box")
        image = gtk.image_new_from_icon_name("vm_clone_wizard",
                                             gtk.ICON_SIZE_DIALOG)
        image.show()
        box.pack_end(image, False)

    # Populate state
    def reset_state(self):
        self.widget("clone-cancel").grab_focus()

        # Populate default clone values
        self.setup_clone_info()

        cd = self.clone_design
        self.widget("clone-orig-name").set_text(cd.original_guest)
        self.widget("clone-new-name").set_text(cd.clone_name)

        # We need to determine which disks fail (and why).
        self.storage_list, self.target_list = self.check_all_storage()

        self.populate_storage_lists()
        self.populate_network_list()

        return

    def setup_clone_info(self):
        self.clone_design = self.build_new_clone_design()

    def build_new_clone_design(self, new_name=None):
        cd = CloneDesign(self.conn.vmm)
        cd.original_guest = self.orig_vm.get_name()
        if not new_name:
            new_name = virtinst.CloneManager.generate_clone_name(cd)
        cd.clone_name = new_name

        # Erase any clone_policy from the original design, so that we
        # get the entire device list.
        cd.clone_policy = []

        return cd

    def populate_network_list(self):
        net_box = self.widget("clone-network-box")
        for c in net_box.get_children():
            net_box.remove(c)
            c.destroy()

        self.net_list = {}
        self.mac_list = []

        def build_net_row(labelstr, origmac, newmac):

            label = gtk.Label(labelstr + " (%s)" % origmac)
            label.set_alignment(0, .5)
            button = gtk.Button(_("Details..."))
            button.connect("clicked", self.net_change_mac, origmac)

            hbox = gtk.HBox()
            hbox.set_spacing(12)
            hbox.pack_start(label)
            hbox.pack_end(button, False, False)
            hbox.show_all()
            net_box.pack_start(hbox, False, False)

            net_row = []
            net_row.insert(NETWORK_INFO_LABEL, labelstr)
            net_row.insert(NETWORK_INFO_ORIG_MAC, origmac)
            net_row.insert(NETWORK_INFO_NEW_MAC, newmac)
            self.net_list[origmac] = net_row
            self.mac_list.append(origmac)

        for net in self.orig_vm.get_network_devices():
            mac = net.macaddr
            net_dev = net.get_source()
            net_type = net.type

            # Generate a new MAC
            obj = VirtualNetworkInterface(conn=self.conn.vmm,
                                          type=VirtualNetworkInterface.TYPE_USER)
            obj.setup(self.conn.vmm)
            newmac = obj.macaddr


            # [ interface type, device name, origmac, newmac, label ]
            if net_type == VirtualNetworkInterface.TYPE_USER:
                label = _("Usermode")

            elif net_type == VirtualNetworkInterface.TYPE_VIRTUAL:
                net = self.orig_vm.conn.get_net_by_name(net_dev)

                if net:
                    label = ""

                    desc = net.pretty_forward_mode()
                    label += "%s" % desc

                else:
                    label = (_("Virtual Network") +
                             (net_dev and " %s" % net_dev or ""))

            else:
                # 'bridge' or anything else
                label = (net_type.capitalize() +
                         (net_dev and (" %s" % net_dev) or ""))

            build_net_row(label, mac, newmac)

        no_net = bool(len(self.net_list.keys()) == 0)
        self.widget("clone-network-box").set_property("visible", not no_net)
        self.widget("clone-no-net").set_property("visible", no_net)

    def check_all_storage(self):
        """
        Determine which storage is cloneable, and which isn't
        """
        diskinfos = self.orig_vm.get_disk_devices()
        cd = self.clone_design

        storage_list = {}

        # We need to determine which disks fail (and why).
        all_targets = map(lambda d: d.target, diskinfos)

        for disk in diskinfos:
            force_target = disk.target
            path = disk.path
            ro = disk.read_only
            shared = disk.shareable
            devtype = disk.device

            size = None
            clone_path = None
            failinfo = ""
            definfo = ""

            storage_row = []
            storage_row.insert(STORAGE_INFO_ORIG_PATH, path or "-")
            storage_row.insert(STORAGE_INFO_NEW_PATH, clone_path)
            storage_row.insert(STORAGE_INFO_TARGET, force_target)
            storage_row.insert(STORAGE_INFO_SIZE, size)
            storage_row.insert(STORAGE_INFO_DEVTYPE, devtype)
            storage_row.insert(STORAGE_INFO_DO_CLONE, False)
            storage_row.insert(STORAGE_INFO_CAN_CLONE, False)
            storage_row.insert(STORAGE_INFO_CAN_SHARE, False)
            storage_row.insert(STORAGE_INFO_DO_DEFAULT, False)
            storage_row.insert(STORAGE_INFO_DEFINFO, definfo)
            storage_row.insert(STORAGE_INFO_FAILINFO, failinfo)
            storage_row.insert(STORAGE_INFO_COMBO, None)
            storage_row.insert(STORAGE_INFO_MANUAL_PATH, False)

            skip_targets = all_targets[:]
            skip_targets.remove(force_target)

            vol = self.conn.get_vol_by_path(path)
            default, definfo = do_we_default(self.conn, vol, path, ro, shared,
                                             devtype)

            def storage_add(failinfo=None):
                storage_row[STORAGE_INFO_DEFINFO] = definfo
                storage_row[STORAGE_INFO_DO_DEFAULT] = default
                storage_row[STORAGE_INFO_CAN_SHARE] = bool(definfo)
                if failinfo:
                    storage_row[STORAGE_INFO_FAILINFO] = failinfo
                    storage_row[STORAGE_INFO_DO_CLONE] = False

                storage_list[force_target] = storage_row

            # If origdisk is empty, deliberately make it fail
            if not path:
                storage_add(_("Nothing to clone."))
                continue

            try:
                cd.skip_target = skip_targets
                cd.setup_original()
            except Exception, e:
                logging.exception("Disk target '%s' caused clone error",
                                  force_target)
                storage_add(str(e))
                continue

            can_clone, cloneinfo = can_we_clone(self.conn, vol, path)
            if not can_clone:
                storage_add(cloneinfo)
                continue

            try:
                # Generate disk path, make sure that works
                clone_path = self.generate_clone_path_name(path)

                logging.debug("Original path: %s\nGenerated clone path: %s",
                              path, clone_path)

                cd.clone_devices = clone_path
                size = cd.original_virtual_disks[0].size
            except Exception, e:
                logging.exception("Error setting generated path '%s'",
                                  clone_path)
                storage_add(str(e))

            storage_row[STORAGE_INFO_CAN_CLONE] = True
            storage_row[STORAGE_INFO_NEW_PATH] = clone_path
            storage_row[STORAGE_INFO_SIZE] = self.pretty_storage(size)
            storage_add()

        return storage_list, all_targets

    def generate_clone_path_name(self, origpath, newname=None):
        cd = self.clone_design
        if not newname:
            newname = cd.clone_name
        clone_path = CloneManager.generate_clone_disk_path(origpath, cd,
                                                           newname=newname)
        return clone_path

    def set_paths_from_clone_name(self):
        cd = self.clone_design
        newname = self.widget("clone-new-name").get_text()

        if not newname:
            return
        if cd.clone_name == newname:
            return

        for row in self.storage_list.values():
            origpath = row[STORAGE_INFO_ORIG_PATH]
            if row[STORAGE_INFO_MANUAL_PATH]:
                continue
            if not row[STORAGE_INFO_DO_CLONE]:
                return
            try:
                newpath = self.generate_clone_path_name(origpath, newname)
                row[STORAGE_INFO_NEW_PATH] = newpath
            except Exception, e:
                logging.debug("Generating new path from clone name failed: "
                              + str(e))

    def build_storage_entry(self, disk, storage_box):
        origpath = disk[STORAGE_INFO_ORIG_PATH]
        devtype = disk[STORAGE_INFO_DEVTYPE]
        size = disk[STORAGE_INFO_SIZE]
        can_clone = disk[STORAGE_INFO_CAN_CLONE]
        do_clone = disk[STORAGE_INFO_DO_CLONE]
        can_share = disk[STORAGE_INFO_CAN_SHARE]
        is_default = disk[STORAGE_INFO_DO_DEFAULT]
        definfo = disk[STORAGE_INFO_DEFINFO]
        failinfo = disk[STORAGE_INFO_FAILINFO]
        target = disk[STORAGE_INFO_TARGET]

        orig_name = self.orig_vm.get_name()

        disk_label = os.path.basename(origpath)
        info_label = None
        if not can_clone:
            info_label = gtk.Label()
            info_label.set_alignment(0, .5)
            info_label.set_markup("<span size='small'>%s</span>" % failinfo)
        if not is_default:
            disk_label += (definfo and " (%s)" % definfo or "")

        # Build icon
        icon = gtk.Image()
        if devtype == virtinst.VirtualDisk.DEVICE_FLOPPY:
            iconname = "media-floppy"
        elif devtype == virtinst.VirtualDisk.DEVICE_CDROM:
            iconname = "media-optical"
        else:
            iconname = "drive-harddisk"
        icon.set_from_icon_name(iconname, gtk.ICON_SIZE_MENU)
        disk_name_label = gtk.Label(disk_label)
        disk_name_label.set_alignment(0, .5)
        disk_name_box = gtk.HBox(spacing=9)
        disk_name_box.pack_start(icon, False)
        disk_name_box.pack_start(disk_name_label, True)

        def sep_func(model, it, combo):
            ignore = combo
            return model[it][2]

        # [String, sensitive, is sep]
        model = gtk.ListStore(str, bool, bool)
        option_combo = gtk.ComboBox(model)
        text = gtk.CellRendererText()
        option_combo.pack_start(text)
        option_combo.add_attribute(text, "text", 0)
        option_combo.add_attribute(text, "sensitive", 1)
        option_combo.set_row_separator_func(sep_func, option_combo)
        option_combo.connect("changed", self.storage_combo_changed, target)

        vbox = gtk.VBox(spacing=1)
        if can_clone or can_share:
            model.insert(STORAGE_COMBO_CLONE,
                         [(_("Clone this disk") +
                           (size and " (%s)" % size or "")),
                          can_clone, False])
            model.insert(STORAGE_COMBO_SHARE,
                         [_("Share disk with %s") % orig_name, can_share,
                          False])
            model.insert(STORAGE_COMBO_SEP, ["", False, True])
            model.insert(STORAGE_COMBO_DETAILS,
                         [_("Details..."), True, False])

            if (can_clone and is_default) or do_clone:
                option_combo.set_active(STORAGE_COMBO_CLONE)
            else:
                option_combo.set_active(STORAGE_COMBO_SHARE)
        else:
            model.insert(STORAGE_COMBO_CLONE,
                         [_("Storage cannot be shared or cloned."),
                         False, False])
            option_combo.set_active(STORAGE_COMBO_CLONE)

        vbox.pack_start(disk_name_box, False, False)
        vbox.pack_start(option_combo, False, False)
        if info_label:
            vbox.pack_start(info_label, False, False)
        storage_box.pack_start(vbox, False, False)

        disk[STORAGE_INFO_COMBO] = option_combo

    def populate_storage_lists(self):
        storage_box = self.widget("clone-storage-box")
        for c in storage_box.get_children():
            storage_box.remove(c)
            c.destroy()

        for target in self.target_list:
            disk = self.storage_list[target]
            self.build_storage_entry(disk, storage_box)

        num_c = min(len(self.target_list), 3)
        if num_c:
            scroll = self.widget("clone-storage-scroll")
            scroll.set_size_request(-1, 80 * num_c)
        storage_box.show_all()

        no_storage = not bool(len(self.target_list))
        self.widget("clone-storage-box").set_property("visible",
                                                      not no_storage)
        self.widget("clone-no-storage-pass").set_property("visible",
                                                          no_storage)

        skip_targets = []
        new_disks = []
        for target in self.target_list:
            do_clone = self.storage_list[target][STORAGE_INFO_DO_CLONE]
            new_path = self.storage_list[target][STORAGE_INFO_NEW_PATH]

            if do_clone:
                new_disks.append(new_path)
            else:
                skip_targets.append(target)

        self.clone_design.skip_target = skip_targets
        self.clone_design.clone_devices = new_disks

        # If any storage cannot be cloned or shared, don't allow cloning
        clone = True
        tooltip = ""
        for row in self.storage_list.values():
            can_clone = row[STORAGE_INFO_CAN_CLONE]
            can_share = row[STORAGE_INFO_CAN_SHARE]
            if not (can_clone or can_share):
                clone = False
                tooltip = _("One or more disks cannot be cloned or shared.")
                break

        ok_button = self.widget("clone-ok")
        ok_button.set_sensitive(clone)
        util.tooltip_wrapper(ok_button, tooltip)

    def net_change_mac(self, ignore, origmac):
        row      = self.net_list[origmac]
        orig_mac = row[NETWORK_INFO_ORIG_MAC]
        new_mac  = row[NETWORK_INFO_NEW_MAC]
        typ = row[NETWORK_INFO_LABEL]

        self.widget("change-mac-orig").set_text(orig_mac)
        self.widget("change-mac-type").set_text(typ)
        self.widget("change-mac-new").set_text(new_mac)

        self.change_mac.show_all()

    def storage_combo_changed(self, src, target):
        idx = src.get_active()
        row = self.storage_list[target]

        if idx == STORAGE_COMBO_CLONE:
            row[STORAGE_INFO_DO_CLONE] = True
            return
        elif idx == STORAGE_COMBO_SHARE:
            row[STORAGE_INFO_DO_CLONE] = False
            return
        elif idx != STORAGE_COMBO_DETAILS:
            return

        do_clone = row[STORAGE_INFO_DO_CLONE]
        if do_clone:
            src.set_active(STORAGE_COMBO_CLONE)
        else:
            src.set_active(STORAGE_COMBO_SHARE)

        # Show storage
        row = self.storage_change_path(row)

    def change_storage_doclone_toggled(self, src):
        do_clone = src.get_active()

        self.widget("change-storage-new").set_sensitive(do_clone)
        self.widget("change-storage-browse").set_sensitive(do_clone)

    def storage_change_path(self, row):
        # If storage paths are dependent on manually entered clone name,
        # make sure they are up to date
        self.set_paths_from_clone_name()

        orig = row[STORAGE_INFO_ORIG_PATH]
        new  = row[STORAGE_INFO_NEW_PATH]
        tgt  = row[STORAGE_INFO_TARGET]
        size = row[STORAGE_INFO_SIZE]
        can_clone = row[STORAGE_INFO_CAN_CLONE]
        can_share = row[STORAGE_INFO_CAN_SHARE]
        do_clone = row[STORAGE_INFO_DO_CLONE]

        self.widget("change-storage-doclone").set_active(True)
        self.widget("change-storage-doclone").toggled()
        self.widget("change-storage-orig").set_text(orig)
        self.widget("change-storage-target").set_text(tgt)
        self.widget("change-storage-size").set_text(size or "-")
        self.widget("change-storage-doclone").set_active(do_clone)

        if can_clone:
            self.widget("change-storage-new").set_text(new or "")
        else:
            self.widget("change-storage-new").set_text("")
        self.widget("change-storage-doclone").set_sensitive(can_clone and
                                                            can_share)

        self.widget("vmm-change-storage").show_all()

    def set_orig_vm(self, new_orig):
        self.orig_vm = new_orig
        self.conn = self.orig_vm.conn

    def change_mac_finish(self, ignore):
        orig = self.widget("change-mac-orig").get_text()
        new = self.widget("change-mac-new").get_text()
        row = self.net_list[orig]

        try:
            VirtualNetworkInterface(conn=self.conn.vmm,
                                    type=VirtualNetworkInterface.TYPE_USER,
                                    macaddr=new)
            row[NETWORK_INFO_NEW_MAC] = new
        except Exception, e:
            self.err.show_err(_("Error changing MAC address: %s") % str(e))
            return

        self.change_mac_close()

    def change_storage_finish(self, ignore):
        target = self.widget("change-storage-target").get_text()
        row = self.storage_list[target]

        # Sync 'do clone' checkbox, and main dialog combo
        combo = row[STORAGE_INFO_COMBO]
        do_clone = self.widget("change-storage-doclone").get_active()
        if do_clone:
            combo.set_active(STORAGE_COMBO_CLONE)
        else:
            combo.set_active(STORAGE_COMBO_SHARE)

        row[STORAGE_INFO_DO_CLONE] = do_clone
        if not do_clone:
            self.change_storage_close()
            return

        new_path = self.widget("change-storage-new").get_text()

        if virtinst.VirtualDisk.path_exists(self.clone_design.original_conn,
                                            new_path):
            res = self.err.yes_no(_("Cloning will overwrite the existing "
                                    "file"),
                                    _("Using an existing image will overwrite "
                                      "the path during the clone process. Are "
                                      "you sure you want to use this path?"))
            if not res:
                return

        try:
            self.clone_design.clone_devices = new_path
            self.populate_storage_lists()
            row[STORAGE_INFO_NEW_PATH] = new_path
            row[STORAGE_INFO_MANUAL_PATH] = True
        except Exception, e:
            self.err.show_err(_("Error changing storage path: %s") % str(e))
            return

        self.change_storage_close()

    def pretty_storage(self, size):
        if not size:
            return ""
        return "%.1f GB" % float(size)

    # Listeners
    def validate(self):
        self.set_paths_from_clone_name()
        name = self.widget("clone-new-name").get_text()

        # Make another clone_design
        cd = self.build_new_clone_design(name)

        # Set MAC addresses
        for mac in self.mac_list:
            row = self.net_list[mac]
            new_mac = row[NETWORK_INFO_NEW_MAC]
            cd.clone_mac = new_mac

        skip_targets = []
        new_paths = []
        warn_str = ""
        for target in self.target_list:
            path = self.storage_list[target][STORAGE_INFO_ORIG_PATH]
            new_path = self.storage_list[target][STORAGE_INFO_NEW_PATH]
            do_clone = self.storage_list[target][STORAGE_INFO_DO_CLONE]
            do_default = self.storage_list[target][STORAGE_INFO_DO_DEFAULT]

            if do_clone:
                new_paths.append(new_path)
            else:
                skip_targets.append(target)
                if not path or path == '-':
                    continue

                if not do_default:
                    continue

                warn_str += "%s: %s\n" % (target, path)

        cd.skip_target = skip_targets
        cd.setup_original()
        cd.clone_devices = new_paths

        if warn_str:
            res = self.err.ok_cancel(
                _("Skipping disks may cause data to be overwritten."),
                _("The following disk devices will not be cloned:\n\n%s\n"
                  "Running the new guest could overwrite data in these "
                  "disk images.")
                  % warn_str)

            if not res:
                return False

        cd.setup_clone()

        self.clone_design = cd
        return True

    def finish(self, src_ignore):
        try:
            if not self.validate():
                return
        except Exception, e:
            self.err.show_err(_("Uncaught error validating input: %s") % str(e))
            return

        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        title = (_("Creating virtual machine clone '%s'") %
                 self.clone_design.clone_name)
        text = title
        if self.clone_design.clone_devices:
            text = title + _(" and selected storage (this may take a while)")

        progWin = vmmAsyncJob(self._async_clone, [], title, text, self.topwin)
        error, details = progWin.run()

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))

        if error is not None:
            error = (_("Error creating virtual machine clone '%s': %s") %
                      (self.clone_design.clone_name, error))
            self.err.show_err(error, details=details)
        else:
            self.close()
            self.conn.tick(noStatsUpdate=True)

    def _async_clone(self, asyncjob):
        newconn = None

        try:
            self.orig_vm.set_cloning(True)

            # Open a seperate connection to install on since this is async
            logging.debug("Threading off connection to clone VM.")
            newconn = util.dup_conn(self.conn).vmm
            meter = asyncjob.get_meter()

            self.clone_design.orig_connection = newconn
            for d in self.clone_design.clone_virtual_disks:
                d.conn = newconn

            self.clone_design.setup()
            CloneManager.start_duplicate(self.clone_design, meter)
        finally:
            self.orig_vm.set_cloning(False)

    def change_storage_browse(self, ignore):
        def callback(src_ignore, txt):
            self.widget("change-storage-new").set_text(txt)

        if self.storage_browser == None:
            self.storage_browser = vmmStorageBrowser(self.conn)
            self.storage_browser.connect("storage-browse-finish", callback)

        self.storage_browser.show(self.topwin, self.conn)

    def show_help(self, ignore1=None):
        # Nothing yet
        return

vmmGObjectUI.type_register(vmmCloneVM)
vmmCloneVM.signal_new(vmmCloneVM, "action-show-help", [str])

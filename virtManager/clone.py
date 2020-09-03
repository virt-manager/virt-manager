# Copyright (C) 2009, 2013 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from gi.repository import Gtk

import virtinst
from virtinst import Cloner
from virtinst import DeviceInterface
from virtinst import log

from .lib import uiutil
from .baseclass import vmmGObjectUI
from .asyncjob import vmmAsyncJob
from .storagebrowse import vmmStorageBrowser
from .object.storagepool import vmmStoragePool

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


def can_we_clone(conn, vol, path):
    """Is the passed path even clone-able"""
    ret = True
    msg = None

    if not path:
        msg = _("No storage to clone.")

    elif not vol:
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

    else:
        pool = vol.get_parent_pool()
        if not vmmStoragePool.supports_volume_creation(
                pool.get_type(), clone=True):
            msg = _("Cannot clone %s storage pool.") % pool.get_type()

    if msg:
        ret = False

    return (ret, msg)


def do_we_default(conn, vol, path, ro, shared, devtype):
    """ Returns (do we clone by default?, info string if not)"""
    ignore = conn
    info = ""
    can_default = True

    def append_str(str1, str2, delim=", "):
        if not str2:
            return str1
        if str1:
            str1 += delim
        str1 += str2
        return str1

    if (devtype == virtinst.DeviceDisk.DEVICE_CDROM or
        devtype == virtinst.DeviceDisk.DEVICE_FLOPPY):
        info = append_str(info, _("Removable"))

    if ro:
        info = append_str(info, _("Read Only"))
    elif not vol and path and not os.access(path, os.W_OK):
        info = append_str(info, _("No write access"))

    if vol:
        pool_type = vol.get_parent_pool().get_type()
        if pool_type == virtinst.StoragePool.TYPE_DISK:
            info = append_str(info, _("Disk device"))
            can_default = False

    if shared:
        info = append_str(info, _("Shareable"))

    return (not info, info, can_default)


class vmmCloneVM(vmmGObjectUI):
    @classmethod
    def show_instance(cls, parentobj, vm):
        try:
            # Maintain one dialog per connection
            uri = vm.conn.get_uri()
            if cls._instances is None:
                cls._instances = {}
            if uri not in cls._instances:
                cls._instances[uri] = vmmCloneVM()
            cls._instances[uri].show(parentobj.topwin, vm)
        except Exception as e:  # pragma: no cover
            parentobj.err.show_err(
                    _("Error launching clone dialog: %s") % str(e))

    def __init__(self):
        vmmGObjectUI.__init__(self, "clone.ui", "vmm-clone")
        self.vm = None
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

        self.builder.connect_signals({
            "on_clone_delete_event": self.close,
            "on_clone_cancel_clicked": self.close,
            "on_clone_ok_clicked": self.finish,

            # Change mac dialog
            "on_vmm_change_mac_delete_event": self.change_mac_close,
            "on_change_mac_cancel_clicked": self.change_mac_close,
            "on_change_mac_ok_clicked": self.change_mac_finish,

            # Change storage dialog
            "on_vmm_change_storage_delete_event": self.change_storage_close,
            "on_change_storage_cancel_clicked": self.change_storage_close,
            "on_change_storage_ok_clicked": self.change_storage_finish,
            "on_change_storage_doclone_toggled": self.change_storage_doclone_toggled,

            "on_change_storage_browse_clicked": self.change_storage_browse,
        })
        self.bind_escape_key_close()
        self._cleanup_on_app_close()

        self._init_ui()

    @property
    def conn(self):
        if self.vm:
            return self.vm.conn
        return None

    def show(self, parent, vm):
        log.debug("Showing clone wizard")
        self._set_vm(vm)
        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.resize(1, 1)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        log.debug("Closing clone wizard")
        self.change_mac_close()
        self.change_storage_close()
        self.topwin.hide()

        self._set_vm(None)
        self.clone_design = None
        self.storage_list = {}
        self.target_list = []
        self.net_list = {}
        self.mac_list = []

        return 1

    def _vm_removed_cb(self, _conn, vm):
        if self.vm == vm:
            self.close()

    def _set_vm(self, newvm):
        oldvm = self.vm
        if oldvm:
            oldvm.conn.disconnect_by_obj(self)
        if newvm:
            newvm.conn.connect("vm-removed", self._vm_removed_cb)
        self.vm = newvm

    def _cleanup(self):
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

    def _init_ui(self):
        context = self.topwin.get_style_context()
        defcolor = context.get_background_color(Gtk.StateType.NORMAL)
        self.widget("storage-viewport").override_background_color(
                                                  Gtk.StateType.NORMAL,
                                                  defcolor)

    # Populate state
    def reset_state(self):
        self.widget("clone-cancel").grab_focus()

        # Populate default clone values
        self.setup_clone_info()

        cd = self.clone_design
        self.widget("clone-orig-name").set_text(cd.original_guest)
        self.widget("clone-new-name").set_text(cd.clone_name)

        uiutil.set_grid_row_visible(
            self.widget("clone-dest-host"), self.conn.is_remote())
        self.widget("clone-dest-host").set_text(self.conn.get_pretty_desc())

        # We need to determine which disks fail (and why).
        self.storage_list, self.target_list = self.check_all_storage()

        self.populate_storage_lists()
        self.populate_network_list()

        return

    def setup_clone_info(self):
        self.clone_design = self.build_new_clone_design()

    def build_new_clone_design(self, new_name=None):
        design = Cloner(self.conn.get_backend())
        design.original_guest = self.vm.get_name()
        if not new_name:
            new_name = design.generate_clone_name()
        design.clone_name = new_name

        # Erase any clone_policy from the original design, so that we
        # get the entire device list.
        design.clone_policy = []
        return design

    def populate_network_list(self):
        net_box = self.widget("clone-network-box")
        for c in net_box.get_children():
            net_box.remove(c)
            c.destroy()

        self.net_list = {}
        self.mac_list = []

        def build_net_row(labelstr, origmac, newmac):

            label = Gtk.Label(label=labelstr)
            label.set_alignment(0, .5)
            button = Gtk.Button(_("Details..."))
            button.connect("clicked", self.net_change_mac, origmac)

            hbox = Gtk.HBox()
            hbox.set_spacing(12)
            hbox.pack_start(label, True, True, 0)
            hbox.pack_end(button, False, False, False)
            hbox.show_all()
            net_box.pack_start(hbox, False, False, False)

            net_row = []
            net_row.insert(NETWORK_INFO_LABEL, labelstr)
            net_row.insert(NETWORK_INFO_ORIG_MAC, origmac)
            net_row.insert(NETWORK_INFO_NEW_MAC, newmac)
            self.net_list[origmac] = net_row
            self.mac_list.append(origmac)

        for net in self.vm.xmlobj.devices.interface:
            mac = net.macaddr
            net_dev = net.source
            net_type = net.type

            # Generate a new MAC
            newmac = DeviceInterface.generate_mac(
                    self.conn.get_backend())

            # [ interface type, device name, origmac, newmac, label ]
            if net_type == DeviceInterface.TYPE_USER:
                label = _("Usermode (%(mac)s)") % {"mac": mac}

            elif net_type == DeviceInterface.TYPE_VIRTUAL:
                net = None
                for netobj in self.vm.conn.list_nets():
                    if netobj.get_name() == net_dev:
                        net = netobj
                        break

                if net:
                    label = _("%(netmode)s (%(mac)s)") % {
                        "netmode": net.pretty_forward_mode(),
                        "mac": mac,
                    }
                elif net_dev:
                    label = _("Virtual Network %(netdevice)s (%(mac)s)") % {
                        "netdevice": net_dev,
                        "mac": mac,
                    }
                else:
                    label = _("Virtual Network (%(mac)s)") % {"mac": mac}

            else:
                # 'bridge' or anything else
                pretty_net_type = net_type.capitalize()
                if net_dev:
                    label = _("%(nettype)s %(netdevice)s (%(mac)s)") % {
                        "nettype": pretty_net_type,
                        "netdevice": net_dev,
                        "mac": mac,
                    }
                else:
                    label = _("%(nettype)s (%(mac)s)") % {
                        "nettype": pretty_net_type,
                        "mac": mac,
                    }

            build_net_row(label, mac, newmac)

        no_net = (not list(self.net_list.keys()))
        self.widget("clone-network-box").set_visible(not no_net)
        self.widget("clone-no-net").set_visible(no_net)

    def check_all_storage(self):
        """
        Determine which storage is clonable, and which isn't
        """
        diskinfos = self.vm.xmlobj.devices.disk
        cd = self.clone_design

        storage_list = {}

        # We need to determine which disks fail (and why).
        all_targets = [d.target for d in diskinfos]

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
            default, definfo, can_default = do_we_default(self.conn, vol, path,
                                                          ro, shared, devtype)

            def storage_add(failinfo=None):
                # pylint: disable=cell-var-from-loop
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
            except Exception as e:
                log.exception("Disk target '%s' caused clone error",
                                  force_target)
                storage_add(str(e))
                continue

            can_clone, cloneinfo = can_we_clone(self.conn, vol, path)
            if not can_clone:
                storage_add(cloneinfo)
                continue

            storage_row[STORAGE_INFO_CAN_CLONE] = True

            # If we cannot create default clone_path don't even try to do that
            if not can_default:
                storage_add()
                continue

            try:
                # Generate disk path, make sure that works
                clone_path = self.generate_clone_path_name(path)

                log.debug("Original path: %s\nGenerated clone path: %s",
                              path, clone_path)

                cd.clone_paths = clone_path
                size = cd.original_disks[0].get_size()
            except Exception as e:
                log.exception("Error setting generated path '%s'",
                                  clone_path)
                storage_add(str(e))

            storage_row[STORAGE_INFO_NEW_PATH] = clone_path
            storage_row[STORAGE_INFO_SIZE] = self.pretty_storage(size)
            storage_add()

        return storage_list, all_targets

    def generate_clone_path_name(self, origpath, newname=None):
        cd = self.clone_design
        if not newname:
            newname = cd.clone_name
        clone_path = cd.generate_clone_disk_path(origpath,
                                                 newname=newname)
        return clone_path

    def set_paths_from_clone_name(self):
        cd = self.clone_design
        newname = self.widget("clone-new-name").get_text()

        if not newname:
            return
        if cd.clone_name == newname:
            return

        for row in list(self.storage_list.values()):
            origpath = row[STORAGE_INFO_ORIG_PATH]
            if row[STORAGE_INFO_MANUAL_PATH]:
                continue
            if not row[STORAGE_INFO_DO_CLONE]:
                return
            try:
                newpath = self.generate_clone_path_name(origpath, newname)
                row[STORAGE_INFO_NEW_PATH] = newpath
            except Exception as e:
                log.debug("Generating new path from clone name failed: %s",
                              str(e))

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

        orig_name = self.vm.get_name()

        disk_label = os.path.basename(origpath)
        info_label = None
        if not can_clone:
            info_label = Gtk.Label()
            info_label.set_alignment(0, .5)
            info_label.set_markup("<span size='small'>%s</span>" % failinfo)
            info_label.set_line_wrap(True)
        if not is_default:
            disk_label += (definfo and " (%s)" % definfo or "")

        # Build icon
        icon = Gtk.Image()
        if devtype == virtinst.DeviceDisk.DEVICE_FLOPPY:
            iconname = "media-floppy"
        elif devtype == virtinst.DeviceDisk.DEVICE_CDROM:
            iconname = "media-optical"
        else:
            iconname = "drive-harddisk"
        icon.set_from_icon_name(iconname, Gtk.IconSize.MENU)
        disk_name_label = Gtk.Label(label=disk_label)
        disk_name_label.set_alignment(0, .5)
        disk_name_box = Gtk.HBox(spacing=9)
        disk_name_box.pack_start(icon, False, False, 0)
        disk_name_box.pack_start(disk_name_label, True, True, 0)

        def sep_func(model, it, combo):
            ignore = combo
            return model[it][2]

        # [String, sensitive, is sep]
        model = Gtk.ListStore(str, bool, bool)
        option_combo = Gtk.ComboBox()
        option_combo.set_model(model)
        text = Gtk.CellRendererText()
        option_combo.pack_start(text, True)
        option_combo.add_attribute(text, "text", 0)
        option_combo.add_attribute(text, "sensitive", 1)
        option_combo.set_row_separator_func(sep_func, option_combo)
        option_combo.connect("changed", self.storage_combo_changed, target)

        vbox = Gtk.VBox(spacing=1)
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

        vbox.pack_start(disk_name_box, False, False, 0)
        vbox.pack_start(option_combo, False, False, 0)
        if info_label:
            vbox.pack_start(info_label, False, False, 0)
        storage_box.pack_start(vbox, False, False, 0)

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
        self.widget("clone-storage-box").set_visible(not no_storage)
        self.widget("clone-no-storage-pass").set_visible(no_storage)

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
        try:
            self.clone_design.clone_paths = new_disks
        except Exception as e:
            # Just log the error and go on. The UI will fail later if needed
            log.debug("Error setting clone_paths: %s", str(e))

        # If any storage cannot be cloned or shared, don't allow cloning
        clone = True
        tooltip = ""
        for row in list(self.storage_list.values()):
            can_clone = row[STORAGE_INFO_CAN_CLONE]
            can_share = row[STORAGE_INFO_CAN_SHARE]
            if not (can_clone or can_share):
                clone = False
                tooltip = _("One or more disks cannot be cloned or shared.")
                break

        ok_button = self.widget("clone-ok")
        ok_button.set_sensitive(clone)
        ok_button.set_tooltip_text(tooltip)

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
        self.storage_change_path(row)

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

    def change_mac_finish(self, ignore):
        orig = self.widget("change-mac-orig").get_text()
        new = self.widget("change-mac-new").get_text()
        row = self.net_list[orig]

        try:
            DeviceInterface.check_mac_in_use(self.conn.get_backend(), new)
            row[NETWORK_INFO_NEW_MAC] = new
        except Exception as e:
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

        if virtinst.DeviceDisk.path_definitely_exists(self.clone_design.conn,
                                                       new_path):
            res = self.err.yes_no(_("Cloning will overwrite the existing "
                                    "file"),
                                    _("Using an existing image will overwrite "
                                      "the path during the clone process. Are "
                                      "you sure you want to use this path?"))
            if not res:
                return

        try:
            self.clone_design.clone_paths = new_path
            row[STORAGE_INFO_NEW_PATH] = new_path
            row[STORAGE_INFO_MANUAL_PATH] = True
            self.populate_storage_lists()
        except Exception as e:
            self.err.show_err(_("Error changing storage path: %s") % str(e))
            return

        self.change_storage_close()

    def pretty_storage(self, size):
        if not size:
            return ""
        return "%.1f GiB" % float(size)

    # Listeners
    def validate(self):
        self.set_paths_from_clone_name()
        name = self.widget("clone-new-name").get_text()

        # Make another clone_design
        cd = self.build_new_clone_design(name)

        # Set MAC addresses
        clonemacs = []
        for mac in self.mac_list:
            row = self.net_list[mac]
            clonemacs.append(row[NETWORK_INFO_NEW_MAC])
        cd.clone_macs = clonemacs

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
        cd.clone_paths = new_paths

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

    def _finish_cb(self, error, details, conn):
        self.reset_finish_cursor()

        if error is not None:
            error = (_("Error creating virtual machine clone '%(vm)s': "
                       "%(error)s") % {
                     "vm": self.clone_design.clone_name,
                     "error": error,
                     })
            self.err.show_err(error, details=details)
            return

        conn.schedule_priority_tick(pollvm=True)
        self.close()

    def finish(self, src_ignore):
        try:
            if not self.validate():
                return
        except Exception as e:
            self.err.show_err(_("Uncaught error validating input: %s") % str(e))
            return

        self.set_finish_cursor()

        title = (_("Creating virtual machine clone '%s'") %
                 self.clone_design.clone_name)
        text = title
        if self.clone_design.clone_disks:
            text = (_("Creating virtual machine clone '%s' and selected "
                      "storage (this may take a while)") %
                    self.clone_design.clone_name)

        progWin = vmmAsyncJob(self._async_clone, [],
                              self._finish_cb, [self.conn],
                              title, text, self.topwin)
        progWin.run()

    def _async_clone(self, asyncjob):
        meter = asyncjob.get_meter()

        refresh_pools = []
        for disk in self.clone_design.clone_disks:
            if not disk.wants_storage_creation():
                continue

            pool = disk.get_parent_pool()
            if not pool:
                continue

            poolname = pool.name()
            if poolname not in refresh_pools:
                refresh_pools.append(poolname)

        self.clone_design.start_duplicate(meter)

        for poolname in refresh_pools:
            try:
                pool = self.conn.get_pool_by_name(poolname)
                self.idle_add(pool.refresh)
            except Exception:
                log.debug("Error looking up pool=%s for refresh after "
                        "VM clone.", poolname, exc_info=True)

    def change_storage_browse(self, ignore):
        def callback(src_ignore, txt):
            self.widget("change-storage-new").set_text(txt)

        if self.storage_browser and self.storage_browser.conn != self.conn:
            self.storage_browser.cleanup()
            self.storage_browser = None
        if self.storage_browser is None:
            self.storage_browser = vmmStorageBrowser(self.conn)
            self.storage_browser.set_finish_cb(callback)

        self.storage_browser.show(self.topwin)

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

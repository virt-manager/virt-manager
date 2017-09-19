#
# Copyright (C) 2006, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
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

from gi.repository import GObject

from virtinst import VirtualDisk

from .baseclass import vmmGObjectUI
from .mediacombo import vmmMediaCombo
from .storagebrowse import vmmStorageBrowser
from .addstorage import vmmAddStorage


class vmmChooseCD(vmmGObjectUI):
    __gsignals__ = {
        "cdrom-chosen": (GObject.SignalFlags.RUN_FIRST, None, [object, str])
    }

    def __init__(self, vm, disk):
        vmmGObjectUI.__init__(self, "choosecd.ui", "vmm-choose-cd")

        self.vm = vm
        self.conn = self.vm.conn
        self.storage_browser = None

        # This is also overwritten from details.py when targetting a new disk
        self.disk = disk
        self.media_type = disk.device

        self.mediacombo = vmmMediaCombo(self.conn, self.builder, self.topwin,
                                        self.media_type)
        self.widget("media-combo-align").add(self.mediacombo.top_box)

        self.builder.connect_signals({
            "on_vmm_choose_cd_delete_event": self.close,

            "on_media_toggled": self.media_toggled,
            "on_fv_iso_location_browse_clicked": self.browse_fv_iso_location,

            "on_ok_clicked": self.ok,
            "on_cancel_clicked": self.close,
        })

        self.reset_state()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing media chooser")
        self.topwin.hide()
        if self.storage_browser:
            self.storage_browser.close()

        return 1

    def show(self, parent):
        logging.debug("Showing media chooser")
        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()
        self.conn.schedule_priority_tick(pollnodedev=True)

    def _cleanup(self):
        self.vm = None
        self.conn = None
        self.disk = None

        if self.storage_browser:
            self.storage_browser.cleanup()
            self.storage_browser = None
        if self.mediacombo:
            self.mediacombo.cleanup()
            self.mediacombo = None

    def _init_ui(self):
        if self.media_type == vmmMediaCombo.MEDIA_FLOPPY:
            self.widget("physical-media").set_label(_("Floppy D_rive"))
            self.widget("iso-image").set_label(_("Floppy _Image"))

    def reset_state(self):
        self.mediacombo.reset_state()

        enable_phys = not self.vm.stable_defaults()
        self.widget("physical-media").set_sensitive(enable_phys)
        self.widget("physical-media").set_tooltip_text("" if enable_phys else
            _("Physical CDROM passthrough not supported with this hypervisor"))

        use_cdrom = (self.mediacombo.has_media()) and enable_phys

        self.widget("physical-media").set_active(use_cdrom)
        self.widget("iso-image").set_active(not use_cdrom)

    def ok(self, ignore1=None, ignore2=None):
        if self.widget("iso-image").get_active():
            path = self.widget("iso-path").get_text()
        else:
            path = self.mediacombo.get_path()
        if path == "" or path is None:
            return self.err.val_err(_("Invalid Media Path"),
                                    _("A media path must be specified."))

        names = VirtualDisk.path_in_use_by(self.disk.conn, path)
        if names:
            res = self.err.yes_no(
                    _('Disk "%s" is already in use by other guests %s') %
                     (path, names),
                    _("Do you really want to use the disk?"))
            if not res:
                return False

        vmmAddStorage.check_path_search(self, self.conn, path)

        try:
            self.disk.path = path
        except Exception as e:
            return self.err.val_err(_("Invalid Media Path"), e)

        self.emit("cdrom-chosen", self.disk, path)
        self.close()

    def media_toggled(self, ignore1=None, ignore2=None):
        is_phys = bool(self.widget("physical-media").get_active())
        self.mediacombo.combo.set_sensitive(is_phys)
        self.widget("iso-path").set_sensitive(not is_phys)
        self.widget("iso-file-chooser").set_sensitive(not is_phys)

    def browse_fv_iso_location(self, ignore1=None, ignore2=None):
        self._browse_file()

    def set_storage_path(self, src_ignore, path):
        self.widget("iso-path").set_text(path)

    def _browse_file(self):
        if self.storage_browser is None:
            self.storage_browser = vmmStorageBrowser(self.conn)
            self.storage_browser.set_finish_cb(self.set_storage_path)

        self.storage_browser.set_stable_defaults(self.vm.stable_defaults())

        if self.media_type == vmmMediaCombo.MEDIA_FLOPPY:
            self.storage_browser.set_browse_reason(
                                    self.config.CONFIG_DIR_FLOPPY_MEDIA)
        else:
            self.storage_browser.set_browse_reason(
                                    self.config.CONFIG_DIR_ISO_MEDIA)
        self.storage_browser.show(self.topwin)

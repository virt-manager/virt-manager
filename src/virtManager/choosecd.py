#
# Copyright (C) 2006 Red Hat, Inc.
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

import virtManager.uihelpers as uihelpers
import virtManager.util as util
from virtManager.baseclass import vmmGObjectUI
from virtManager.mediadev import MEDIA_FLOPPY
from virtManager.storagebrowse import vmmStorageBrowser

class vmmChooseCD(vmmGObjectUI):
    def __init__(self, vm, disk):
        vmmGObjectUI.__init__(self, "vmm-choose-cd.ui", "vmm-choose-cd")

        self.vm = vm
        self.conn = self.vm.conn
        self.disk = disk
        self.storage_browser = None
        self.media_type = disk.device

        self.window.connect_signals({
            "on_media_toggled": self.media_toggled,
            "on_fv_iso_location_browse_clicked": self.browse_fv_iso_location,
            "on_cd_path_changed": self.change_cd_path,
            "on_ok_clicked": self.ok,
            "on_vmm_choose_cd_delete_event": self.close,
            "on_cancel_clicked": self.close,
        })

        self.widget("iso-image").set_active(True)

        self.initialize_opt_media()
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

    def _cleanup(self):
        self.vm = None
        self.conn = None
        self.disk = None

        if self.storage_browser:
            self.storage_browser.cleanup()
            self.storage_browser = None

    def reset_state(self):
        cd_path = self.widget("cd-path")
        use_cdrom = (cd_path.get_active() > -1)

        if use_cdrom:
            self.widget("physical-media").set_active(True)
        else:
            self.widget("iso-image").set_active(True)

    def ok(self, ignore1=None, ignore2=None):
        path = None

        if self.widget("iso-image").get_active():
            path = self.widget("iso-path").get_text()
        else:
            cd = self.widget("cd-path")
            idx = cd.get_active()
            model = cd.get_model()
            if idx != -1:
                path = model[idx][uihelpers.OPTICAL_DEV_PATH]

        if path == "" or path == None:
            return self.err.val_err(_("Invalid Media Path"),
                                    _("A media path must be specified."))

        try:
            self.disk.path = path
        except Exception, e:
            return self.err.val_err(_("Invalid Media Path"), e)

        uihelpers.check_path_search_for_qemu(self.topwin, self.conn, path)

        self.emit("cdrom-chosen", self.disk, path)
        self.close()

    def media_toggled(self, ignore1=None, ignore2=None):
        if self.widget("physical-media").get_active():
            self.widget("cd-path").set_sensitive(True)
            self.widget("iso-path").set_sensitive(False)
            self.widget("iso-file-chooser").set_sensitive(False)
        else:
            self.widget("cd-path").set_sensitive(False)
            self.widget("iso-path").set_sensitive(True)
            self.widget("iso-file-chooser").set_sensitive(True)

    def change_cd_path(self, ignore1=None, ignore2=None):
        pass

    def browse_fv_iso_location(self, ignore1=None, ignore2=None):
        self._browse_file()

    def initialize_opt_media(self):
        widget = self.widget("cd-path")
        warn = self.widget("cd-path-warn")

        error = self.conn.mediadev_error
        uihelpers.init_mediadev_combo(widget)
        uihelpers.populate_mediadev_combo(self.conn, widget, self.media_type)

        if error:
            warn.show()
            util.tooltip_wrapper(warn, error)
        else:
            warn.hide()

        self.widget("physical-media").set_sensitive(not bool(error))

        if self.media_type == MEDIA_FLOPPY:
            self.widget("physical-media").set_label(_("Floppy D_rive"))
            self.widget("iso-image").set_label(_("Floppy _Image"))

    def set_storage_path(self, src_ignore, path):
        self.widget("iso-path").set_text(path)

    def _browse_file(self):
        if self.storage_browser == None:
            self.storage_browser = vmmStorageBrowser(self.conn)
            self.storage_browser.connect("storage-browse-finish",
                                         self.set_storage_path)

        rhel6 = self.vm.rhel6_defaults()
        self.storage_browser.rhel6_defaults = rhel6

        if self.media_type == MEDIA_FLOPPY:
            self.storage_browser.set_browse_reason(
                                    self.config.CONFIG_DIR_FLOPPY_MEDIA)
        else:
            self.storage_browser.set_browse_reason(
                                    self.config.CONFIG_DIR_ISO_MEDIA)
        self.storage_browser.show(self.topwin, self.conn)

vmmGObjectUI.type_register(vmmChooseCD)
vmmChooseCD.signal_new(vmmChooseCD, "cdrom-chosen", [object, str])

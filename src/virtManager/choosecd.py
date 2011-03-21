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
import gobject

import virtManager.uihelpers as uihelpers
import virtManager.util as util
from virtManager.baseclass import vmmGObjectUI
from virtManager.mediadev import MEDIA_FLOPPY
from virtManager.storagebrowse import vmmStorageBrowser

class vmmChooseCD(vmmGObjectUI):
    __gsignals__ = {
        "cdrom-chosen": (gobject.SIGNAL_RUN_FIRST,
                         gobject.TYPE_NONE,
                         # dev, new path
                         (gobject.TYPE_PYOBJECT, str)),
    }

    def __init__(self, dev_id_info, connection, media_type):
        vmmGObjectUI.__init__(self, "vmm-choose-cd.glade", "vmm-choose-cd")

        self.dev_id_info = dev_id_info
        self.conn = connection
        self.storage_browser = None
        self.media_type = media_type

        self.window.signal_autoconnect({
            "on_media_toggled": self.media_toggled,
            "on_fv_iso_location_browse_clicked": self.browse_fv_iso_location,
            "on_cd_path_changed": self.change_cd_path,
            "on_ok_clicked": self.ok,
            "on_vmm_choose_cd_delete_event": self.close,
            "on_cancel_clicked": self.close,
            })

        self.window.get_widget("iso-image").set_active(True)

        self.initialize_opt_media()
        self.reset_state()

    def close(self, ignore1=None, ignore2=None):
        self.topwin.hide()
        return 1

    def show(self):
        self.reset_state()
        self.topwin.show()

    def reset_state(self):
        cd_path = self.window.get_widget("cd-path")
        use_cdrom = (cd_path.get_active() > -1)

        if use_cdrom:
            self.window.get_widget("physical-media").set_active(True)
        else:
            self.window.get_widget("iso-image").set_active(True)

    def ok(self, ignore1=None, ignore2=None):
        path = None

        if self.window.get_widget("iso-image").get_active():
            path = self.window.get_widget("iso-path").get_text()
        else:
            cd = self.window.get_widget("cd-path")
            idx = cd.get_active()
            model = cd.get_model()
            if idx != -1:
                path = model[idx][uihelpers.OPTICAL_DEV_PATH]

        if path == "" or path == None:
            return self.err.val_err(_("Invalid Media Path"),
                                    _("A media path must be specified."))

        try:
            self.dev_id_info.path = path
        except Exception, e:
            return self.err.val_err(_("Invalid Media Path"), str(e))

        uihelpers.check_path_search_for_qemu(self.topwin, self.conn, path)

        self.emit("cdrom-chosen", self.dev_id_info, path)
        self.close()

    def media_toggled(self, ignore1=None, ignore2=None):
        if self.window.get_widget("physical-media").get_active():
            self.window.get_widget("cd-path").set_sensitive(True)
            self.window.get_widget("iso-path").set_sensitive(False)
            self.window.get_widget("iso-file-chooser").set_sensitive(False)
        else:
            self.window.get_widget("cd-path").set_sensitive(False)
            self.window.get_widget("iso-path").set_sensitive(True)
            self.window.get_widget("iso-file-chooser").set_sensitive(True)

    def change_cd_path(self, ignore1=None, ignore2=None):
        pass

    def browse_fv_iso_location(self, ignore1=None, ignore2=None):
        self._browse_file()

    def initialize_opt_media(self):
        widget = self.window.get_widget("cd-path")
        warn = self.window.get_widget("cd-path-warn")

        error = self.conn.mediadev_error
        uihelpers.init_mediadev_combo(widget)
        uihelpers.populate_mediadev_combo(self.conn, widget, self.media_type)

        if error:
            warn.show()
            util.tooltip_wrapper(warn, error)
        else:
            warn.hide()

        self.window.get_widget("physical-media").set_sensitive(not bool(error))

        if self.media_type == MEDIA_FLOPPY:
            self.window.get_widget("physical-media").set_label(
                                                            _("Floppy D_rive"))
            self.window.get_widget("iso-image").set_label(_("Floppy _Image"))

    def set_storage_path(self, src_ignore, path):
        self.window.get_widget("iso-path").set_text(path)

    def _browse_file(self):
        if self.storage_browser == None:
            self.storage_browser = vmmStorageBrowser(self.conn)
            self.storage_browser.connect("storage-browse-finish",
                                         self.set_storage_path)

        self.storage_browser.set_browse_reason(self.config.CONFIG_DIR_MEDIA)
        self.storage_browser.show(self.conn)

vmmGObjectUI.type_register(vmmChooseCD)

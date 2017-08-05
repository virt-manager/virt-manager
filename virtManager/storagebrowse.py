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

from . import uiutil
from .baseclass import vmmGObjectUI
from .storagelist import vmmStorageList


class vmmStorageBrowser(vmmGObjectUI):
    def __init__(self, conn):
        vmmGObjectUI.__init__(self, "storagebrowse.ui", "vmm-storage-browse")
        self.conn = conn

        self._first_run = False
        self._finish_cb = None

        # Passed to browse_local
        self._browse_reason = None

        # Whether we should abide stable defaults
        self._stable_defaults = False

        self.storagelist = vmmStorageList(self.conn, self.builder, self.topwin,
            self._vol_sensitive_cb)
        self._init_ui()

        self.builder.connect_signals({
            "on_vmm_storage_browse_delete_event": self.close,
        })
        self.bind_escape_key_close()


    def show(self, parent):
        logging.debug("Showing storage browser")
        if not self._first_run:
            self._first_run = True
            pool = self.conn.get_default_pool()
            uiutil.set_list_selection(self.storagelist.widget("pool-list"),
                pool and pool.get_connkey() or None)

        self.topwin.set_transient_for(parent)
        self.topwin.present()
        self.conn.schedule_priority_tick(pollpool=True)

    def close(self, ignore1=None, ignore2=None):
        if self.topwin.is_visible():
            logging.debug("Closing storage browser")
            self.topwin.hide()
        self.storagelist.close()
        return 1

    def _cleanup(self):
        self.conn = None

        self.storagelist.cleanup()
        self.storagelist = None


    ##############
    # Public API #
    ##############

    def set_finish_cb(self, callback):
        self._finish_cb = callback
    def set_browse_reason(self, reason):
        self._browse_reason = reason
    def set_vm_name(self, name):
        self.storagelist.set_name_hint(name)
    def set_stable_defaults(self, val):
        self._stable_defaults = val

    def _init_ui(self):
        self.storagelist.connect("browse-clicked", self._browse_clicked)
        self.storagelist.connect("volume-chosen", self._volume_chosen)
        self.storagelist.connect("cancel-clicked", self.close)

        self.widget("storage-align").add(self.storagelist.top_box)
        self.err.set_modal_default(True)
        self.storagelist.err.set_modal_default(True)

        tooltip = ""
        is_remote = self.conn.is_remote()
        self.storagelist.widget("browse-local").set_sensitive(not is_remote)
        if is_remote:
            tooltip = _("Cannot use local storage on remote connection.")
        self.storagelist.widget("browse-local").set_tooltip_text(tooltip)

        uiutil.set_grid_row_visible(
            self.storagelist.widget("pool-autostart"), False)
        uiutil.set_grid_row_visible(
            self.storagelist.widget("pool-name-entry"), False)
        uiutil.set_grid_row_visible(
            self.storagelist.widget("pool-state-box"), False)
        self.storagelist.widget("browse-local").set_visible(True)
        self.storagelist.widget("browse-cancel").set_visible(True)
        self.storagelist.widget("choose-volume").set_visible(True)
        self.storagelist.widget("choose-volume").set_sensitive(False)
        self.storagelist.widget("pool-apply").set_visible(False)

        data = self.config.browse_reason_data.get(self._browse_reason)
        allow_create = True
        if data:
            self.topwin.set_title(data["storage_title"])
            allow_create = data["enable_create"]

        self.storagelist.widget("vol-add").set_sensitive(allow_create)


    #############
    # Listeners #
    #############

    def _browse_clicked(self, src):
        ignore = src
        return self._browse_local()

    def _volume_chosen(self, src, volume):
        ignore = src
        logging.debug("Chosen volume XML:\n%s", volume.xmlobj.get_xml_config())
        self._finish(volume.get_target_path())

    def _vol_sensitive_cb(self, fmt):
        if ((self._browse_reason == self.config.CONFIG_DIR_FS) and
            fmt != 'dir'):
            return False
        elif self._stable_defaults:
            if fmt == "vmdk":
                return False
        return True


    ####################
    # Internal helpers #
    ####################

    def _browse_local(self):
        dialog_type = None
        dialog_name = None
        choose_button = None

        data = self.config.browse_reason_data.get(self._browse_reason)
        if data:
            dialog_name = data["local_title"] or None
            dialog_type = data.get("dialog_type")
            choose_button = data.get("choose_button")

        filename = self.err.browse_local(self.conn,
            dialog_type=dialog_type, browse_reason=self._browse_reason,
            dialog_name=dialog_name, choose_button=choose_button)
        if filename:
            logging.debug("Browse local chose path=%s", filename)
            self._finish(filename)

    def _finish(self, path):
        if self._finish_cb:
            self._finish_cb(self, path)
        self.close()

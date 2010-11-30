#
# Copyright (C) 2008 Red Hat, Inc.
# Copyright (C) 2008 Cole Robinson <crobinso@redhat.com>
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
import gtk.glade

import traceback
import logging

from virtManager import util
from virtManager.error import vmmErrorDialog
from virtManager.asyncjob import vmmAsyncJob
from virtManager.createmeter import vmmCreateMeter

from virtinst import Storage

DEFAULT_ALLOC = 0
DEFAULT_CAP   = 1000

class vmmCreateVolume(gobject.GObject):
    __gsignals__ = {
        "vol-created": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [])
    }

    def __init__(self, config, conn, parent_pool):
        self.__gobject_init__()
        self.conn = conn
        self.parent_pool = parent_pool
        self.config = config

        self.window = gtk.glade.XML(config.get_glade_dir() + \
                                    "/vmm-create-vol.glade",
                                    "vmm-create-vol", domain="virt-manager")
        self.topwin = self.window.get_widget("vmm-create-vol")
        self.err = vmmErrorDialog(self.topwin)
        self.topwin.hide()

        self.name_hint = None
        self.vol = None
        self.vol_class = Storage.StoragePool.get_volume_for_pool(parent_pool.get_type())

        self.window.signal_autoconnect({
            "on_vmm_create_vol_delete_event" : self.close,
            "on_vol_cancel_clicked"  : self.close,
            "on_vol_create_clicked"  : self.finish,
            "on_vol_name_changed"    : self.vol_name_changed,
            "on_vol_allocation_value_changed" : self.vol_allocation_changed,
            "on_vol_capacity_value_changed"   : self.vol_capacity_changed,
        })
        util.bind_escape_key_close(self)

        format_list = self.window.get_widget("vol-format")
        format_model = gtk.ListStore(str, str)
        format_list.set_model(format_model)
        text2 = gtk.CellRendererText()
        format_list.pack_start(text2, False)
        format_list.add_attribute(text2, 'text', 1)
        self.window.get_widget("vol-info-view").modify_bg(gtk.STATE_NORMAL,
                                                          gtk.gdk.color_parse("grey"))

        # XXX: Help docs useless/out of date
        self.window.get_widget("pool-help").hide()
        finish_img = gtk.image_new_from_stock(gtk.STOCK_QUIT,
                                              gtk.ICON_SIZE_BUTTON)
        self.window.get_widget("vol-create").set_image(finish_img)

        self.reset_state()


    def show(self):
        self.reset_state()
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        self.topwin.hide()
        self.set_modal(False)
        return 1

    def set_name_hint(self, hint):
        self.name_hint = hint

    def set_modal(self, modal):
        self.topwin.set_modal(bool(modal))

    def set_parent_pool(self, pool):
        self.parent_pool = pool
        self.vol_class = Storage.StoragePool.get_volume_for_pool(self.parent_pool.get_type())


    def default_vol_name(self):
        if not self.name_hint:
            return ""

        suffix = self.default_suffix()
        ret = ""
        try:
            ret = Storage.StorageVolume.find_free_name(self.name_hint,
                                            pool_object=self.parent_pool.pool,
                                            suffix=suffix)
            ret = ret.rstrip(suffix)
        except:
            pass

        return ret

    def default_suffix(self):
        suffix = ""
        if self.vol_class == Storage.FileVolume:
            suffix = ".img"
        return suffix

    def reset_state(self):
        default_name = self.default_vol_name()
        self.window.get_widget("vol-name").set_text("")
        self.window.get_widget("vol-create").set_sensitive(False)
        if default_name:
            self.window.get_widget("vol-name").set_text(default_name)

        self.window.get_widget("vol-name").grab_focus()
        self.populate_vol_format()
        self.populate_vol_suffix()

        if len(self.vol_class.formats):
            self.window.get_widget("vol-format").set_sensitive(True)
            self.window.get_widget("vol-format").set_active(0)
        else:
            self.window.get_widget("vol-format").set_sensitive(False)

        self.window.get_widget("vol-allocation").set_range(0, int(self.parent_pool.get_available() / 1024 / 1024))
        self.window.get_widget("vol-allocation").set_value(DEFAULT_ALLOC)
        self.window.get_widget("vol-capacity").set_range(1, int(self.parent_pool.get_available() / 1024 / 1024))
        self.window.get_widget("vol-capacity").set_value(DEFAULT_CAP)

        self.window.get_widget("vol-parent-name").set_markup("<b>" + self.parent_pool.get_name() + "'s</b>")
        self.window.get_widget("vol-parent-space").set_text(self.parent_pool.get_pretty_available())


    def get_config_format(self):
        format_combo = self.window.get_widget("vol-format")
        model = format_combo.get_model()
        if format_combo.get_active_iter() != None:
            model = format_combo.get_model()
            return model.get_value(format_combo.get_active_iter(), 0)
        return None

    def populate_vol_format(self):
        model = self.window.get_widget("vol-format").get_model()
        model.clear()
        formats = self.vol_class.formats
        for f in formats:
            model.append([f, f])

    def populate_vol_suffix(self):
        suffix = self.default_suffix()
        if self.vol_class == Storage.FileVolume:
            suffix = ".img"
        self.window.get_widget("vol-name-suffix").set_text(suffix)

    def vol_name_changed(self, src):
        text = src.get_text()
        self.window.get_widget("vol-create").set_sensitive(bool(text))

    def vol_allocation_changed(self, src):
        cap_widget = self.window.get_widget("vol-capacity")

        alloc = src.get_value()
        cap   = cap_widget.get_value()

        if alloc > cap:
            cap_widget.set_value(alloc)

    def vol_capacity_changed(self, src):
        alloc_widget = self.window.get_widget("vol-allocation")

        cap   = src.get_value()
        alloc = self.window.get_widget("vol-allocation").get_value()

        if cap < alloc:
            alloc_widget.set_value(cap)

    def finish(self, src):
        # validate input
        try:
            if not self.validate():
                return
        except Exception, e:
            self.show_err(_("Uncaught error validating input: %s") % str(e),
                            "".join(traceback.format_exc()))
            return

        logging.debug("Creating volume with xml:\n%s" %
                      self.vol.get_xml_config())

        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        progWin = vmmAsyncJob(self.config, self._async_vol_create, [],
                              title=_("Creating storage volume..."),
                              text=_("Creating the storage volume may take a "
                                     "while..."))
        progWin.run()
        error, details = progWin.get_error()

        if error is not None:
            self.show_err(error, details)

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))

        if not error:
            self.emit("vol-created")
            self.close()

    def _async_vol_create(self, asyncjob):
        newconn = None
        try:
            newconn = util.dup_conn(self.config, self.conn)

            # Lookup different pool obj
            newpool = newconn.storagePoolLookupByName(self.parent_pool.get_name())
            self.vol.pool = newpool

            meter = vmmCreateMeter(asyncjob)
            logging.debug("Starting backround vol creation.")
            self.vol.install(meter=meter)
        except Exception, e:
            error = _("Error creating vol: %s") % str(e)
            details = "".join(traceback.format_exc())
            asyncjob.set_error(error, details)

    def validate(self):
        name = self.window.get_widget("vol-name").get_text()
        suffix = self.window.get_widget("vol-name-suffix").get_text()
        volname = name + suffix
        fmt = self.get_config_format()
        alloc = self.window.get_widget("vol-allocation").get_value()
        cap = self.window.get_widget("vol-capacity").get_value()

        try:
            self.vol = self.vol_class(name=volname,
                                      allocation=(alloc * 1024 * 1024),
                                      capacity=(cap * 1024 * 1024),
                                      pool=self.parent_pool.pool)
            if fmt:
                self.vol.format = fmt
        except ValueError, e:
            return self.val_err(_("Volume Parameter Error"), str(e))
        return True

    def show_err(self, info, details):
        async = not self.topwin.get_modal()
        self.err.show_err(info, details, async=async)

    def val_err(self, info, details):
        modal = self.topwin.get_modal()
        ret = False
        try:
            self.topwin.set_modal(False)
            ret = self.err.val_err(info, details, async=not modal)
        finally:
            self.topwin.set_modal(modal)

        return ret

gobject.type_register(vmmCreateVolume)

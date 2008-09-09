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
import gtk.glade
import gobject
import logging
import virtinst
from virtManager.opticalhelper import vmmOpticalDriveHelper
from virtManager.error import vmmErrorDialog

class vmmChooseCD(gobject.GObject):
    __gsignals__ = {"cdrom-chosen": (gobject.SIGNAL_RUN_FIRST,
                           gobject.TYPE_NONE,
                           (str, str, str)), # type, source, target
}
    def __init__(self, config, target, connection):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-choose-cd.glade", "vmm-choose-cd", domain="virt-manager")
        self.err = vmmErrorDialog(self.window.get_widget("vmm-choose-cd"),
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))
        self.config = config
        self.window.get_widget("vmm-choose-cd").hide()
        self.target = target
        self.conn = connection

        self.window.signal_autoconnect({
            "on_media_toggled": self.media_toggled,
            "on_fv_iso_location_browse_clicked": self.browse_fv_iso_location,
            "on_cd_path_changed": self.change_cd_path,
            "on_ok_clicked": self.ok,
            "on_vmm_choose_cd_delete_event": self.cancel,
            "on_cancel_clicked": self.cancel,
            })

        self.window.get_widget("iso-image").set_active(True)

        # set up the list for the cd-path widget
        cd_list = self.window.get_widget("cd-path")
        # Fields are raw device path, volume label, flag indicating
        # whether volume is present or not, and HAL path
        cd_model = gtk.ListStore(str, str, bool, str)
        cd_list.set_model(cd_model)
        text = gtk.CellRendererText()
        cd_list.pack_start(text, True)
        cd_list.add_attribute(text, 'text', 1)
        cd_list.add_attribute(text, 'sensitive', 2)
        try:
            self.optical_helper = vmmOpticalDriveHelper(self.window.get_widget("cd-path"))
            self.optical_helper.populate_opt_media()
            self.window.get_widget("physical-media").set_sensitive(True)
        except Exception, e:
            logging.error("Unable to create optical-helper widget: '%s'", e)
            self.window.get_widget("physical-media").set_sensitive(False)

    def set_target(self, target):
        self.target=target

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-choose-cd").hide()
        return 1

    def cancel(self,ignore1=None,ignore2=None):
        self.close()

    def show(self):
        win = self.window.get_widget("vmm-choose-cd")
        win.show()

    def ok(self,ignore1=None, ignore2=None):
        if self.window.get_widget("iso-image").get_active():
            path = self.window.get_widget("iso-path").get_text()
        else:
            cd = self.window.get_widget("cd-path")
            model = cd.get_model()
            path = model.get_value(cd.get_active_iter(), 0)

        if path == "" or path == None: 
            return self.err.val_err(_("Invalid Media Path"), \
                                    _("A media path must be specified."))

        try:
            disk = virtinst.VirtualDisk(path=path,
                                        device=virtinst.VirtualDisk.DEVICE_CDROM, 
                                        readOnly=True,
                                        conn=self.conn.vmm)
        except Exception, e:
           return self.err.val_err(_("Invalid Media Path"), str(e))
        self.emit("cdrom-chosen", disk.type, disk.path, self.target)
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
        file = self._browse_file(_("Locate ISO Image"), type="iso")
        if file != None:
            self.window.get_widget("iso-path").set_text(file)

    def _browse_file(self, dialog_name, folder=None, type=None):
        # user wants to browse for an ISO
        fcdialog = gtk.FileChooserDialog(dialog_name,
                                         self.window.get_widget("vmm-choose-cd"),
                                         gtk.FILE_CHOOSER_ACTION_OPEN,
                                         (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                          gtk.STOCK_OPEN, gtk.RESPONSE_ACCEPT),
                                         None)
        fcdialog.set_default_response(gtk.RESPONSE_ACCEPT)
        if type != None:
            f = gtk.FileFilter()
            f.add_pattern("*." + type)
            fcdialog.set_filter(f)
        if folder != None:
            fcdialog.set_current_folder(folder)
        response = fcdialog.run()
        fcdialog.hide()
        if(response == gtk.RESPONSE_ACCEPT):
            filename = fcdialog.get_filename()
            fcdialog.destroy()
            return filename
        else:
            fcdialog.destroy()
            return None

gobject.type_register(vmmChooseCD)

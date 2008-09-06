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

import libvirt

from virtManager.error import vmmErrorDialog
from virtManager.asyncjob import vmmAsyncJob
from virtManager.createmeter import vmmCreateMeter
from virtManager.connection import vmmConnection

from virtinst import Storage

PAGE_NAME   = 0
PAGE_FORMAT = 1

class vmmCreatePool(gobject.GObject):
    __gsignals__ = {
    }

    def __init__(self, config, conn):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + \
                                    "/vmm-create-pool.glade",
                                    "vmm-create-pool", domain="virt-manager")
        self.conn = conn
        self.config = config

        self.topwin = self.window.get_widget("vmm-create-pool")
        self.err = vmmErrorDialog(self.topwin,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))
        self.topwin.hide()

        self._pool = None
        self.error_msg = None
        self.error_details = None

        self.window.signal_autoconnect({
            "on_pool_forward_clicked" : self.forward,
            "on_pool_back_clicked"    : self.back,
            "on_pool_cancel_clicked"  : self.close,
            "on_vmm_create_pool_delete_event" : self.close,
            "on_pool_finish_clicked"  : self.forward,
            "on_pool_pages_change_page" : self.page_changed,
            "on_pool_source_button_clicked" : self.browse_source_path,
            "on_pool_target_button_clicked" : self.browse_target_path,
        })

        self.set_initial_state()

    def show(self):
        self.topwin.show()
        self.reset_state()
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        self.topwin.hide()
        return 1

    def set_initial_state(self):
        self.window.get_widget("pool-pages").set_show_tabs(False)

        type_list = self.window.get_widget("pool-type")
        type_model = gtk.ListStore(str, str)
        type_list.set_model(type_model)
        text1 = gtk.CellRendererText()
        type_list.pack_start(text1, True)
        type_list.add_attribute(text1, 'text', 1)

        format_list = self.window.get_widget("pool-format")
        format_model = gtk.ListStore(str, str)
        format_list.set_model(format_model)
        text2 = gtk.CellRendererText()
        format_list.pack_start(text2, False)
        format_list.add_attribute(text2, 'text', 1)

        self.populate_pool_type()

        self.window.get_widget("pool-info1").modify_base(gtk.STATE_NORMAL, gtk.gdk.color_parse("grey"))
        self.window.get_widget("pool-info2").modify_base(gtk.STATE_NORMAL, gtk.gdk.color_parse("grey"))

    def reset_state(self):
        self.window.get_widget("pool-pages").set_current_page(0)
        self.window.get_widget("pool-forward").show()
        self.window.get_widget("pool-finish").hide()
        self.window.get_widget("pool-back").set_sensitive(False)

        self.window.get_widget("pool-name").set_text("")
        self.window.get_widget("pool-type").set_active(0)
        self.window.get_widget("pool-target-path").set_text("")
        self.window.get_widget("pool-source-path").set_text("")
        self.window.get_widget("pool-hostname").set_text("")
        self.window.get_widget("pool-format").set_active(-1)
        self.window.get_widget("pool-build").set_sensitive(True)
        self.window.get_widget("pool-build").set_active(False)


    def populate_pool_type(self):
        model = self.window.get_widget("pool-type").get_model()
        model.clear()
        types = Storage.StoragePool.get_pool_types()
        types.sort()
        for type in types:
            model.append([type, "%s: %s" % (type, Storage.StoragePool.get_pool_type_desc(type))])

    def populate_pool_format(self):
        model = self.window.get_widget("pool-format").get_model()
        model.clear()
        formats = self._pool.formats
        for f in formats:
            model.append([f, f])

    def show_options_by_pool(self):
        if hasattr(self._pool, "source_path"):
            if self._pool.type in [Storage.StoragePool.TYPE_NETFS,
                                   Storage.StoragePool.TYPE_ISCSI]:
                # Source path broswing is meaningless for net pools
                self.window.get_widget("pool-source-button").set_sensitive(False)
            else:
                self.window.get_widget("pool-source-button").set_sensitive(True)
            self.window.get_widget("pool-source-path").set_sensitive(True)
        else:
            self.window.get_widget("pool-source-path").set_sensitive(False)
            self.window.get_widget("pool-source-button").set_sensitive(False)

        if hasattr(self._pool, "host"):
            self.window.get_widget("pool-hostname").set_sensitive(True)
        else:
            self.window.get_widget("pool-hostname").set_sensitive(False)

        if hasattr(self._pool, "formats"):
            self.window.get_widget("pool-format").set_sensitive(True)
            self.populate_pool_format()
            self.window.get_widget("pool-format").set_active(0)
        else:
            self.window.get_widget("pool-format").set_sensitive(False)
            self.window.get_widget("pool-format").set_active(-1)

        if self.conn.is_remote():
            # Disable browse buttons for remote connections
            self.window.get_widget("pool-source-button").set_sensitive(False)
            self.window.get_widget("pool-target-button").set_sensitive(False)


    def get_config_type(self):
        type = self.window.get_widget("pool-type")
        if type.get_active_iter() != None:
            return type.get_model().get_value(type.get_active_iter(), 0)
        return None

    def get_config_name(self):
        return self.window.get_widget("pool-name").get_text()

    def get_config_target_path(self):
        return self.window.get_widget("pool-target-path").get_text()

    def get_config_source_path(self):
        src = self.window.get_widget("pool-source-path")
        if src.get_property("sensitive"):
            return src.get_text()
        return None

    def get_config_host(self):
        host = self.window.get_widget("pool-hostname")
        if host.get_property("sensitive"):
            return host.get_text()
        return None

    def get_config_format(self):
        format_combo = self.window.get_widget("pool-format")
        model = format_combo.get_model()
        if format_combo.get_active_iter() != None:
            model = format_combo.get_model()
            return model.get_value(format_combo.get_active_iter(), 0)
        return None

    def get_build_default(self):
        """ Return (default value, whether build option can be changed)"""
        if not self._pool:
            return (False, False)
        if self._pool.type in [Storage.StoragePool.TYPE_DIR,
                               Storage.StoragePool.TYPE_FS,
                               Storage.StoragePool.TYPE_NETFS ]:
            # Building for these simply entails creating a directory
            return (True, False)
        elif self._pool.type in [Storage.StoragePool.TYPE_LOGICAL]:
            # Build not yet implemented in virtinst
            return (False, False)
        elif self._pool.type in [Storage.StoragePool.TYPE_DISK]:
            # This is a dangerous operation, anything (False, True)
            # should be assumed to be one.
            return (False, True)
        else:
            return (False, False)


    def browse_source_path(self, ignore1=None):
        source = self._browse_file(_("Choose source path"),
                                   startfolder="/dev", foldermode=False)
        if source:
            self.window.get_widget("pool-source-path").set_text(source)

    def browse_target_path(self, ignore1=None):
        target = self._browse_file(_("Choose target directory"),
                                   startfolder="/var/lib/libvirt",
                                   foldermode=True)
        if target:
            self.window.get_widget("pool-target-path").set_text(target)


    def forward(self, ignore=None):
        notebook = self.window.get_widget("pool-pages")
        try:
            if(self.validate(notebook.get_current_page()) != True):
                return
            if notebook.get_current_page() == PAGE_FORMAT:
                self.finish()
            else:
                notebook.next_page()
        except Exception, e:
            self.err.show_err(_("Uncaught error validating input: %s") % str(e),
                              "".join(traceback.format_exc()))
            return

    def back(self, ignore=None):
        self.window.get_widget("pool-finish").hide()
        self.window.get_widget("pool-forward").show()
        self.window.get_widget("pool-pages").prev_page()

    def finish(self):
        self.error_msg = None
        self.error_details = None
        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        progWin = vmmAsyncJob(self.config, self._async_pool_create, [],
                              title=_("Creating storage pool..."),
                              text=_("Creating the storage pool may take a "
                                     "while..."))
        progWin.run()

        if self.error_msg is not None:
            self.err.show_err(self.error_msg, self.error_details)
            self.topwin.set_sensitive(True)
            self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))
            return

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))
        self.close()

    def _async_pool_create(self, asyncjob):
        newconn = None
        try:
            # Open a seperate connection to install on since this is async
            logging.debug("Threading off connection to create pool.")
            #newconn = vmmConnection(self.config, self.conn.get_uri(),
            #                        self.conn.is_read_only())
            #newconn.open()
            #newconn.connectThreadEvent.wait()
            newconn = libvirt.open(self._pool.conn.getURI())
            meter = vmmCreateMeter(asyncjob)
            self._pool.conn = newconn

            logging.debug("Starting backround pool creation.")
            build = self.window.get_widget("pool-build").get_active()
            poolobj = self._pool.install(create=True, meter=meter, build=build)
            logging.debug("Pool creating succeeded.")
        except Exception, e:
            self.error_msg = _("Error creating pool: %s") % str(e)
            self.error_details = "".join(traceback.format_exc())
            logging.error(self.error_msg + "\n" + self.error_details)

    def page_changed(self, notebook, page, page_number):
        if page_number == PAGE_NAME:
            self.window.get_widget("pool-back").set_sensitive(False)
            self.window.get_widget("pool-finish").hide()
            self.window.get_widget("pool-forward").show()
        elif page_number == PAGE_FORMAT:
            self.show_options_by_pool()
            self.window.get_widget("pool-target-path").set_text(self._pool.target_path)
            self.window.get_widget("pool-back").set_sensitive(True)
            buildret = self.get_build_default()
            self.window.get_widget("pool-build").set_sensitive(buildret[1])
            self.window.get_widget("pool-build").set_active(buildret[0])
            self.window.get_widget("pool-finish").show()
            self.window.get_widget("pool-forward").hide()

    def validate(self, page):
        if page == PAGE_NAME:
            type = self.get_config_type()
            name = self.get_config_name()
            conn = self.conn.vmm

            try:
                pool_class = Storage.StoragePool.get_pool_class(type)
                self._pool = pool_class(name=name,conn=conn)
            except ValueError, e:
                return self.err.val_err(_("Pool Parameter Error"), str(e))

            return True

        elif page == PAGE_FORMAT:
            target = self.get_config_target_path()
            host   = self.get_config_host()
            source = self.get_config_source_path()
            format = self.get_config_format()

            try:
                self._pool.target_path = target
                if host is not None:
                    self._pool.host = host
                if source is not None:
                    self._pool.source_path = source
                if format is not None:
                    self._pool.format = format
            except ValueError, e:
                return self.err.val_err(_("Pool Parameter Error"), str(e))

            buildval = self.window.get_widget("pool-build").get_active()
            buildsen = self.window.get_widget("pool-build").get_property("sensitive")
            if buildsen and buildval:
                return self.err.yes_no(_("Building a pool of this type will "
                                         "format the source device. Are you "
                                         "sure you want to 'build' this pool?"))
            return True


    def _browse_file(self, dialog_name, startfolder=None, foldermode=False):
        mode = gtk.FILE_CHOOSER_ACTION_OPEN
        if foldermode:
            mode = gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER
        fcdialog = gtk.FileChooserDialog(dialog_name, self.topwin, mode,
                                         (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                          gtk.STOCK_OPEN, gtk.RESPONSE_ACCEPT),
                                         None)
        fcdialog.set_default_response(gtk.RESPONSE_ACCEPT)
        if startfolder != None:
            fcdialog.set_current_folder(startfolder)

        response = fcdialog.run()
        fcdialog.hide()
        ret = None
        if(response == gtk.RESPONSE_ACCEPT):
            ret = fcdialog.get_filename()
        fcdialog.destroy()
        return ret

gobject.type_register(vmmCreatePool)

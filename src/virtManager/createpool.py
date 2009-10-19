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
        self._pool_class = Storage.StoragePool

        self.window.signal_autoconnect({
            "on_pool_forward_clicked" : self.forward,
            "on_pool_back_clicked"    : self.back,
            "on_pool_cancel_clicked"  : self.close,
            "on_vmm_create_pool_delete_event" : self.close,
            "on_pool_finish_clicked"  : self.forward,
            "on_pool_pages_change_page" : self.page_changed,
            "on_pool_source_button_clicked" : self.browse_source_path,
            "on_pool_target_button_clicked" : self.browse_target_path,

            "on_pool_name_focus_in_event": (self.update_doc, "name",
                                            "pool-info1"),
            # I cannot for the life of me get a combobox to abide
            # focus-in, button-pressed, motion-over, etc.
            "on_pool_type_focus": (self.update_doc, "type", "pool-info1"),
            "on_pool_type_changed": (self.update_doc_changed, "type",
                                     "pool-info1"),

            "on_pool_format_focus": (self.update_doc, "format", "pool-info2"),
            "on_pool_format_changed": (self.update_doc_changed, "format",
                                       "pool-info2"),
            "on_pool_target_path_focus_in_event": (self.update_doc,
                                                   "target_path",
                                                   "pool-info2"),
            "on_pool_source_path_focus_in_event": (self.update_doc,
                                                   "source_path",
                                                   "pool-info2"),

            "on_pool_source_path_focus": (self.update_doc, "source_path",
                                          "pool-info2"),
            "on_pool_source_path_changed": (self.update_doc_changed,
                                            "source_path",
                                            "pool-info2"),

            "on_pool_hostname_focus_in_event": (self.update_doc, "host",
                                                "pool-info2"),
            "on_pool_build_focus_in_event": (self.update_build_doc)
        })

        # XXX: Help docs useless/out of date
        self.window.get_widget("pool-help").hide()

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

        # Source path combo box entry
        source_list = self.window.get_widget("pool-source-path")
        source_model = gtk.ListStore(str, str)
        source_list.set_model(source_model)
        source_list.set_text_column(0)
        source_list.child.connect("focus-in-event", self.update_doc,
                                  "source_path", "pool-info2")

        self.populate_pool_type()

        self.window.get_widget("pool-info-box1").modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse("grey"))
        self.window.get_widget("pool-info-box2").modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse("grey"))

    def reset_state(self):
        self.window.get_widget("pool-pages").set_current_page(0)
        self.window.get_widget("pool-forward").show()
        self.window.get_widget("pool-finish").hide()
        self.window.get_widget("pool-back").set_sensitive(False)

        self.window.get_widget("pool-name").set_text("")
        self.window.get_widget("pool-type").set_active(0)
        self.window.get_widget("pool-target-path").set_text("")
        self.window.get_widget("pool-source-path").child.set_text("")
        self.window.get_widget("pool-hostname").set_text("")
        self.window.get_widget("pool-format").set_active(-1)
        self.window.get_widget("pool-build").set_sensitive(True)
        self.window.get_widget("pool-build").set_active(False)


    def populate_pool_type(self):
        model = self.window.get_widget("pool-type").get_model()
        model.clear()
        types = Storage.StoragePool.get_pool_types()
        types.sort()
        for typ in types:
            model.append([typ, "%s: %s" % (typ, Storage.StoragePool.get_pool_type_desc(typ))])

    def populate_pool_format(self):
        model = self.window.get_widget("pool-format").get_model()
        model.clear()
        formats = self._pool.formats
        for f in formats:
            model.append([f, f])

    def populate_source_paths(self):
        widget = self.window.get_widget("pool-source-path")
        model = widget.get_model()
        model.clear()

        entry_list = []
        if self._pool.type == Storage.StoragePool.TYPE_SCSI:
            entry_list = self.list_scsi_adapters()

        for e in entry_list:
            model.append(e)

        if entry_list:
            widget.set_active(0)
            widget.child.set_editable(False)
        else:
            widget.set_active(-1)
            widget.child.set_editable(True)

    def list_scsi_adapters(self):
        scsi_hosts = self.conn.get_devices("scsi_host")
        host_list = map(lambda dev: dev.host, scsi_hosts)

        clean_list = []
        for h in host_list:
            name = "host%s" % h
            entry = [name, name]

            if entry not in clean_list:
                clean_list.append(entry)

        return clean_list

    def show_options_by_pool(self):
        if hasattr(self._pool, "source_path"):
            if self._pool.type in [Storage.StoragePool.TYPE_NETFS,
                                   Storage.StoragePool.TYPE_ISCSI,
                                   Storage.StoragePool.TYPE_SCSI]:
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

        self.populate_source_paths()


    def get_config_type(self):
        typ = self.window.get_widget("pool-type")
        if typ.get_active_iter() != None:
            return typ.get_model().get_value(typ.get_active_iter(), 0)
        return None

    def get_config_name(self):
        return self.window.get_widget("pool-name").get_text()

    def get_config_target_path(self):
        return self.window.get_widget("pool-target-path").get_text()

    def get_config_source_path(self):
        src = self.window.get_widget("pool-source-path")
        if not src.get_property("sensitive"):
            return None

        # If we provide the user with a drop down
        model = src.get_model()
        selection = src.get_active()
        if selection != -1:
            return model[selection][1]

        return src.child.get_text()

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
        elif self._pool.type in [Storage.StoragePool.TYPE_LOGICAL,
                                 Storage.StoragePool.TYPE_DISK]:
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
        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        progWin = vmmAsyncJob(self.config, self._async_pool_create, [],
                              title=_("Creating storage pool..."),
                              text=_("Creating the storage pool may take a "
                                     "while..."))
        progWin.run()
        error, details = progWin.get_error()

        if error is not None:
            self.err.show_err(error, details)

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))

        if not error:
            self.close()

    def _async_pool_create(self, asyncjob):
        newconn = None
        try:
            # Open a seperate connection to install on since this is async
            newconn = util.dup_lib_conn(self.config, self._pool.conn)
            meter = vmmCreateMeter(asyncjob)
            self._pool.conn = newconn

            logging.debug("Starting backround pool creation.")
            build = self.window.get_widget("pool-build").get_active()
            poolobj = self._pool.install(create=True, meter=meter, build=build)
            poolobj.setAutostart(True)
            logging.debug("Pool creating succeeded.")
        except Exception, e:
            error = _("Error creating pool: %s") % str(e)
            details = "".join(traceback.format_exc())
            asyncjob.set_error(error, details)

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
            typ  = self.get_config_type()
            name = self.get_config_name()
            conn = self.conn.vmm

            try:
                self._pool_class = Storage.StoragePool.get_pool_class(typ)
                self._pool = self._pool_class(name=name, conn=conn)
            except ValueError, e:
                return self.err.val_err(_("Pool Parameter Error"), str(e))

            return True

        elif page == PAGE_FORMAT:
            target = self.get_config_target_path()
            host   = self.get_config_host()
            source = self.get_config_source_path()
            fmt    = self.get_config_format()

            try:
                self._pool.target_path = target
                if host:
                    self._pool.host = host
                if source:
                    self._pool.source_path = source
                if fmt:
                    self._pool.format = fmt

                self._pool.get_xml_config()
            except ValueError, e:
                return self.err.val_err(_("Pool Parameter Error"), str(e))

            buildval = self.window.get_widget("pool-build").get_active()
            buildsen = self.window.get_widget("pool-build").get_property("sensitive")
            if buildsen and buildval:
                return self.err.yes_no(_("Building a pool of this type will "
                                         "format the source device. Are you "
                                         "sure you want to 'build' this pool?"))
            return True

    def update_doc(self, ignore1, ignore2, param, infobox):
        doc = self._build_doc_str(param)
        self.window.get_widget(infobox).set_markup(doc)

    def update_build_doc(self, ignore1, ignore2):
        doc = ""
        docstr = ""
        if self._pool.type == Storage.StoragePool.TYPE_DISK:
            docstr = _("Format the source device.")
        elif self._pool.type == Storage.StoragePool.TYPE_LOGICAL:
            docstr = _("Create a logical volume group from the source device.")

        if docstr:
            doc = self._build_doc_str("build", docstr)
        self.window.get_widget("pool-info2").set_markup(doc)

    def update_doc_changed(self, ignore1, param, infobox):
        # Wrapper for update_doc and 'changed' signal
        self.update_doc(None, None, param, infobox)

    def _build_doc_str(self, param, docstr=None):
        doc = ""
        doctmpl = "<i><u>%s</u>: %s</i>"
        prettyname = param.replace("_", " ").capitalize()

        if docstr:
            doc = doctmpl % (prettyname, docstr)
        elif hasattr(self._pool_class, param):
            doc = doctmpl % (prettyname,
                             getattr(self._pool_class, param).__doc__)

        return doc

    def _browse_file(self, dialog_name, startfolder=None, foldermode=False):
        mode = gtk.FILE_CHOOSER_ACTION_OPEN
        if foldermode:
            mode = gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER

        return util.browse_local(self.topwin, dialog_name,
                                 self.config, self.conn,
                                 dialog_type=mode,
                                 start_folder=startfolder)

gobject.type_register(vmmCreatePool)

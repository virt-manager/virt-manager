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

import gtk

import copy
import logging

from virtManager import util
from virtManager.baseclass import vmmGObjectUI
from virtManager.asyncjob import vmmAsyncJob

from virtinst import Storage

PAGE_NAME   = 0
PAGE_FORMAT = 1

_comboentry_xml = """
<interface>
    <object class="GtkComboBoxEntry" id="pool-source-path">
        <property name="visible">True</property>
        <signal name="changed" handler="on_pool_source_path_changed"/>
        <signal name="focus" handler="on_pool_source_path_focus"/>
    </object>
    <object class="GtkComboBoxEntry" id="pool-target-path">
        <property name="visible">True</property>
        <signal name="changed" handler="on_pool_target_path_changed"/>
        <signal name="focus_in_event" handler="on_pool_target_path_focus_in_event"/>
    </object>
</interface>
"""

class vmmCreatePool(vmmGObjectUI):
    def __init__(self, conn):
        vmmGObjectUI.__init__(self,
                              "vmm-create-pool.ui",
                              "vmm-create-pool")
        self.conn = conn

        self._pool = None
        self._pool_class = Storage.StoragePool

        self.window.add_from_string(_comboentry_xml)
        self.widget("pool-source-box").pack_start(
            self.widget("pool-source-path"))
        self.widget("pool-target-box").pack_start(
            self.widget("pool-target-path"))

        self.window.connect_signals({
            "on_pool_forward_clicked" : self.forward,
            "on_pool_back_clicked"    : self.back,
            "on_pool_cancel_clicked"  : self.close,
            "on_vmm_create_pool_delete_event" : self.close,
            "on_pool_finish_clicked"  : self.forward,
            "on_pool_pages_change_page" : self.page_changed,
            "on_pool_source_button_clicked" : self.browse_source_path,
            "on_pool_target_button_clicked" : self.browse_target_path,

            "on_pool_name_activate": self.forward,
            "on_pool_hostname_activate" : self.hostname_changed,
            "on_pool_iqn_chk_toggled": self.iqn_toggled,

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
            "on_pool_target_path_focus": (self.update_doc, "target_path",
                                          "pool-info2"),
            "on_pool_target_path_changed": (self.update_doc_changed,
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
            "on_pool_build_focus_in_event": (self.update_build_doc),

            "on_pool_iqn_focus_in_event": (self.update_doc, "iqn",
                                           "pool-info2"),
        })
        self.bind_escape_key_close()

        # XXX: Help docs useless/out of date
        self.widget("pool-help").hide()
        finish_img = gtk.image_new_from_stock(gtk.STOCK_QUIT,
                                              gtk.ICON_SIZE_BUTTON)
        self.widget("pool-finish").set_image(finish_img)

        self.set_initial_state()

    def show(self, parent):
        logging.debug("Showing new pool wizard")
        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing new pool wizard")
        self.topwin.hide()
        return 1

    def _cleanup(self):
        self.conn = None
        self._pool = None

    def set_initial_state(self):
        self.widget("pool-pages").set_show_tabs(False)

        type_list = self.widget("pool-type")
        type_model = gtk.ListStore(str, str)
        type_list.set_model(type_model)
        text1 = gtk.CellRendererText()
        type_list.pack_start(text1, True)
        type_list.add_attribute(text1, 'text', 1)

        format_list = self.widget("pool-format")
        format_model = gtk.ListStore(str, str)
        format_list.set_model(format_model)
        text2 = gtk.CellRendererText()
        format_list.pack_start(text2, False)
        format_list.add_attribute(text2, 'text', 1)

        # Target path combo box entry
        target_list = self.widget("pool-target-path")
        # target_path, Label, pool class instance
        target_model = gtk.ListStore(str, str, object)
        target_model.set_sort_column_id(0, gtk.SORT_ASCENDING)
        target_list.set_model(target_model)
        target_list.set_text_column(0)
        target_list.child.connect("focus-in-event", self.update_doc,
                                  "target_path", "pool-info2")

        # Source path combo box entry
        source_list = self.widget("pool-source-path")
        # source_path, Label, pool class instance
        source_model = gtk.ListStore(str, str, object)
        source_model.set_sort_column_id(0, gtk.SORT_ASCENDING)
        source_list.set_model(source_model)
        source_list.set_text_column(0)
        source_list.child.connect("focus-in-event", self.update_doc,
                                  "source_path", "pool-info2")

        self.populate_pool_type()

        self.widget("pool-info-box1").modify_bg(gtk.STATE_NORMAL,
                                                gtk.gdk.color_parse("grey"))
        self.widget("pool-info-box2").modify_bg(gtk.STATE_NORMAL,
                                                gtk.gdk.color_parse("grey"))

    def reset_state(self):
        self.widget("pool-pages").set_current_page(0)
        self.widget("pool-forward").show()
        self.widget("pool-finish").hide()
        self.widget("pool-back").set_sensitive(False)

        self.widget("pool-name").set_text("")
        self.widget("pool-name").grab_focus()
        self.widget("pool-type").set_active(0)
        self.widget("pool-target-path").child.set_text("")
        self.widget("pool-source-path").child.set_text("")
        self.widget("pool-hostname").set_text("")
        self.widget("pool-iqn-chk").set_active(False)
        self.widget("pool-iqn-chk").toggled()
        self.widget("pool-iqn").set_text("")
        self.widget("pool-format").set_active(-1)
        self.widget("pool-build").set_sensitive(True)
        self.widget("pool-build").set_active(False)


    def hostname_changed(self, ignore):
        # If a hostname was entered, try to lookup valid pool sources.
        self.populate_pool_sources()

    def iqn_toggled(self, src):
        self.widget("pool-iqn").set_sensitive(src.get_active())

    def populate_pool_type(self):
        model = self.widget("pool-type").get_model()
        model.clear()
        types = Storage.StoragePool.get_pool_types()
        types.sort()
        for typ in types:
            model.append([typ, "%s: %s" %
                         (typ, Storage.StoragePool.get_pool_type_desc(typ))])

    def populate_pool_format(self, formats):
        model = self.widget("pool-format").get_model()
        model.clear()
        for f in formats:
            model.append([f, f])

    def populate_pool_sources(self):
        source_list = self.widget("pool-source-path")
        source_model = source_list.get_model()
        source_model.clear()

        target_list = self.widget("pool-target-path")
        target_model = target_list.get_model()
        target_model.clear()

        use_list = source_list
        use_model = source_model
        entry_list = []
        if self._pool.type == Storage.StoragePool.TYPE_SCSI:
            entry_list = self.list_scsi_adapters()
            use_list = source_list
            use_model = source_model

        elif self._pool.type == Storage.StoragePool.TYPE_LOGICAL:
            pool_list = self.list_pool_sources()
            entry_list = map(lambda p: [p.target_path, p.target_path, p],
                             pool_list)
            use_list = target_list
            use_model = target_model

        elif self._pool.type == Storage.StoragePool.TYPE_DISK:
            entry_list = self.list_disk_devs()
            use_list = source_list
            use_model = source_model

        elif self._pool.type == Storage.StoragePool.TYPE_NETFS:
            host = self.get_config_host()
            if host:
                pool_list = self.list_pool_sources(host=host)
                entry_list = map(lambda p: [p.source_path, p.source_path, p],
                                 pool_list)
                use_list = source_list
                use_model = source_model

        for e in entry_list:
            use_model.append(e)

        if entry_list:
            use_list.set_active(0)

    def list_scsi_adapters(self):
        scsi_hosts = self.conn.get_nodedevs("scsi_host")
        host_list = map(lambda dev: dev.host, scsi_hosts)

        clean_list = []
        for h in host_list:
            tmppool = copy.copy(self._pool)
            name = "host%s" % h

            tmppool.source_path = name
            entry = [name, name, tmppool]

            if name not in map(lambda l: l[0], clean_list):
                clean_list.append(entry)

        return clean_list

    def list_disk_devs(self):
        devs = self.conn.get_nodedevs("storage")
        devlist = []
        for dev in devs:
            if dev.drive_type != "disk" or not dev.block:
                continue
            devlist.append(dev.block)

        devlist.sort()
        clean_list = []
        for dev in devlist:
            tmppool = copy.copy(self._pool)
            tmppool.source_path = dev

            entry = [dev, dev, tmppool]
            if dev not in map(lambda l: l[0], clean_list):
                clean_list.append(entry)

        return clean_list

    def list_pool_sources(self, host=None):
        name = self.get_config_name()
        pool_type = self._pool.type

        plist = []
        try:
            plist = Storage.StoragePool.pool_list_from_sources(self.conn.vmm,
                                                               name, pool_type,
                                                               host=host)
        except Exception:
            logging.exception("Pool enumeration failed")

        return plist

    def show_options_by_pool(self):
        def show_row(base, do_show):
            self.widget(base + "-label").set_property("visible", do_show)
            self.widget(base + "-box").set_property("visible", do_show)

        src     = hasattr(self._pool, "source_path")
        src_b   = src and not self.conn.is_remote()
        tgt     = hasattr(self._pool, "target_path")
        tgt_b   = tgt and not self.conn.is_remote()
        host    = hasattr(self._pool, "host")
        fmt     = hasattr(self._pool, "formats")
        iqn     = hasattr(self._pool, "iqn")
        builddef, buildsens = self.get_build_default()

        # Source path broswing is meaningless for net pools
        if self._pool.type in [Storage.StoragePool.TYPE_NETFS,
                               Storage.StoragePool.TYPE_ISCSI,
                               Storage.StoragePool.TYPE_SCSI]:
            src_b = False

        show_row("pool-target", tgt)
        show_row("pool-source", src)
        show_row("pool-hostname", host)
        show_row("pool-format", fmt)
        show_row("pool-build", buildsens)
        show_row("pool-iqn", iqn)

        self.widget("pool-target-path").child.set_text(self._pool.target_path)
        self.widget("pool-target-button").set_sensitive(tgt_b)
        self.widget("pool-source-button").set_sensitive(src_b)
        self.widget("pool-build").set_active(builddef)

        self.widget("pool-format").set_active(-1)
        if fmt:
            self.populate_pool_format(getattr(self._pool, "formats"))
            self.widget("pool-format").set_active(0)

        self.populate_pool_sources()


    def get_config_type(self):
        typ = self.widget("pool-type")
        if typ.get_active_iter() != None:
            return typ.get_model().get_value(typ.get_active_iter(), 0)
        return None

    def get_config_name(self):
        return self.widget("pool-name").get_text()

    def get_config_target_path(self):
        src = self.widget("pool-target-path")
        if not src.get_property("sensitive"):
            return None

        # If we provide the user with a drop down
        model = src.get_model()
        selection = src.get_active()
        if selection != -1:
            return model[selection][1]

        return src.child.get_text()

    def get_config_source_path(self):
        src = self.widget("pool-source-path")
        if not src.get_property("sensitive"):
            return None

        # If we provide the user with a drop down
        model = src.get_model()
        selection = src.get_active()
        if selection != -1:
            return model[selection][1]

        return src.child.get_text().strip()

    def get_config_host(self):
        host = self.widget("pool-hostname")
        if host.get_property("sensitive"):
            return host.get_text().strip()
        return None

    def get_config_format(self):
        format_combo = self.widget("pool-format")
        model = format_combo.get_model()
        if format_combo.get_active_iter() != None:
            model = format_combo.get_model()
            return model.get_value(format_combo.get_active_iter(), 0)
        return None

    def get_config_iqn(self):
        iqn = self.widget("pool-iqn")
        if iqn.get_property("sensitive") and iqn.get_property("visible"):
            return iqn.get_text().strip()
        return None

    def get_build_default(self):
        """ Return (default value, whether build option can be changed)"""
        if not self._pool:
            return (False, False)
        if self._pool.type in [Storage.StoragePool.TYPE_DIR,
                               Storage.StoragePool.TYPE_FS,
                               Storage.StoragePool.TYPE_NETFS]:
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
            self.widget("pool-source-path").child.set_text(source)

    def browse_target_path(self, ignore1=None):
        target = self._browse_file(_("Choose target directory"),
                                   startfolder="/var/lib/libvirt",
                                   foldermode=True)
        if target:
            self.widget("pool-target-path").child.set_text(target)


    def forward(self, ignore=None):
        notebook = self.widget("pool-pages")
        try:
            if(self.validate(notebook.get_current_page()) != True):
                return
            if notebook.get_current_page() == PAGE_FORMAT:
                self.finish()
            else:
                self.widget("pool-forward").grab_focus()
                notebook.next_page()
        except Exception, e:
            self.err.show_err(_("Uncaught error validating input: %s") % str(e))
            return

    def back(self, ignore=None):
        self.widget("pool-finish").hide()
        self.widget("pool-forward").show()
        self.widget("pool-pages").prev_page()

    def finish(self):
        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        build = self.widget("pool-build").get_active()

        progWin = vmmAsyncJob(self._async_pool_create, [build],
                              _("Creating storage pool..."),
                              _("Creating the storage pool may take a "
                                "while..."),
                              self.topwin)
        error, details = progWin.run()

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))

        if error:
            error = _("Error creating pool: %s") % error
            self.err.show_err(error,
                              details=details)
        else:
            self.close()

    def _async_pool_create(self, asyncjob, build):
        newconn = None

        # Open a seperate connection to install on since this is async
        newconn = util.dup_lib_conn(self._pool.conn)
        meter = asyncjob.get_meter()
        self._pool.conn = newconn

        logging.debug("Starting backround pool creation.")
        poolobj = self._pool.install(create=True, meter=meter, build=build)
        poolobj.setAutostart(True)
        logging.debug("Pool creation succeeded")

    def page_changed(self, notebook_ignore, page_ignore, page_number):
        if page_number == PAGE_NAME:
            self.widget("pool-back").set_sensitive(False)
            self.widget("pool-finish").hide()
            self.widget("pool-forward").show()
            self.widget("pool-forward").grab_focus()
        elif page_number == PAGE_FORMAT:
            self.widget("pool-back").set_sensitive(True)
            self.widget("pool-finish").show()
            self.widget("pool-finish").grab_focus()
            self.widget("pool-forward").hide()
            self.show_options_by_pool()

    def get_pool_to_validate(self):
        """
        Return a pool instance to use for parameter assignment validation.
        For most pools this will be the one we built after step 1, but for
        pools we find via FindPoolSources, this will be different
        """
        source_list = self.widget("pool-source-path")
        target_list = self.widget("pool-target-path")

        pool = copy.copy(self._pool)

        if source_list.get_active() != -1:
            pool = source_list.get_model()[source_list.get_active()][2]
        elif target_list.get_active() != -1:
            pool = target_list.get_model()[target_list.get_active()][2]

        return pool

    def validate(self, page):
        if page == PAGE_NAME:
            typ  = self.get_config_type()
            name = self.get_config_name()
            conn = self.conn.vmm

            try:
                self._pool_class = Storage.StoragePool.get_pool_class(typ)
                self._pool = self._pool_class(name=name, conn=conn)
            except ValueError, e:
                return self.err.val_err(_("Pool Parameter Error"), e)

            return True

        elif page == PAGE_FORMAT:
            target  = self.get_config_target_path()
            host    = self.get_config_host()
            source  = self.get_config_source_path()
            fmt     = self.get_config_format()
            iqn     = self.get_config_iqn()

            tmppool = self.get_pool_to_validate()
            try:
                tmppool.target_path = target
                if host:
                    tmppool.host = host
                if source:
                    tmppool.source_path = source
                if fmt:
                    tmppool.format = fmt
                if iqn:
                    tmppool.iqn = iqn

                tmppool.get_xml_config()
            except ValueError, e:
                return self.err.val_err(_("Pool Parameter Error"), e)

            buildval = self.widget("pool-build").get_active()
            buildsen = (self.widget("pool-build").get_property("sensitive") and
                        self.widget("pool-build-box").get_property("visible"))
            if buildsen and buildval:
                ret = self.err.yes_no(_("Building a pool of this type will "
                                        "format the source device. Are you "
                                        "sure you want to 'build' this pool?"))
                if not ret:
                    return ret

            self._pool = tmppool
            return True

    def update_doc(self, ignore1, ignore2, param, infobox):
        doc = self._build_doc_str(param)
        self.widget(infobox).set_markup(doc)

    def update_build_doc(self, ignore1, ignore2):
        doc = ""
        docstr = ""
        if self._pool.type == Storage.StoragePool.TYPE_DISK:
            docstr = _("Format the source device.")
        elif self._pool.type == Storage.StoragePool.TYPE_LOGICAL:
            docstr = _("Create a logical volume group from the source device.")

        if docstr:
            doc = self._build_doc_str("build", docstr)
        self.widget("pool-info2").set_markup(doc)

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

        return util.browse_local(self.topwin, dialog_name, self.conn,
                                 dialog_type=mode,
                                 start_folder=startfolder)

vmmGObjectUI.type_register(vmmCreatePool)

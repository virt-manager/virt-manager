# Copyright (C) 2008, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2008 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from gi.repository import Gtk

from virtinst import log
from virtinst import StoragePool

from .lib import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI
from .object.storagepool import vmmStoragePool
from .xmleditor import vmmXMLEditor


class vmmCreatePool(vmmGObjectUI):
    def __init__(self, conn):
        vmmGObjectUI.__init__(self, "createpool.ui", "vmm-create-pool")
        self.conn = conn

        self._xmleditor = vmmXMLEditor(self.builder, self.topwin,
                self.widget("pool-details-align"),
                self.widget("pool-details"))
        self._xmleditor.connect("xml-requested",
                self._xmleditor_xml_requested_cb)

        self.builder.connect_signals({
            "on_pool_cancel_clicked": self.close,
            "on_vmm_create_pool_delete_event": self.close,
            "on_pool_finish_clicked": self._finish_clicked_cb,
            "on_pool_type_changed": self._pool_type_changed_cb,

            "on_pool_source_button_clicked": self._browse_source_cb,
            "on_pool_target_button_clicked": self._browse_target_cb,

            "on_pool_iqn_chk_toggled": self._iqn_toggled_cb,
        })
        self.bind_escape_key_close()

        self._init_ui()


    #######################
    # Standard UI methods #
    #######################

    def show(self, parent):
        log.debug("Showing new pool wizard")
        self._reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        log.debug("Closing new pool wizard")
        self.topwin.hide()
        return 1

    def _cleanup(self):
        self.conn = None
        self._xmleditor.cleanup()
        self._xmleditor = None


    ###########
    # UI init #
    ###########

    def _build_pool_type_list(self):
        # [pool type, label]
        model = Gtk.ListStore(str, str)
        type_list = self.widget("pool-type")
        type_list.set_model(model)
        uiutil.init_combo_text_column(type_list, 1)

        for typ in vmmStoragePool.list_types():
            desc = vmmStoragePool.pretty_type(typ)
            model.append([typ, "%s: %s" % (typ, desc)])

    def _init_ui(self):
        format_list = self.widget("pool-format")
        format_model = Gtk.ListStore(str, str)
        format_list.set_model(format_model)
        uiutil.init_combo_text_column(format_list, 1)
        for f in ["auto"]:
            format_model.append([f, f])

        combo = self.widget("pool-source-name")
        # [name, label]
        model = Gtk.ListStore(str, str)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        combo.set_model(model)
        combo.set_entry_text_column(0)

        source_list = self.widget("pool-source-path")
        # [source_path, label]
        source_model = Gtk.ListStore(str, str)
        source_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        source_list.set_model(source_model)
        source_list.set_entry_text_column(0)

        self._build_pool_type_list()

    def _reset_state(self):
        self._xmleditor.reset_state()

        defaultname = StoragePool.find_free_name(
                self.conn.get_backend(), "pool")
        self.widget("pool-name").set_text(defaultname)
        self.widget("pool-name").grab_focus()
        self.widget("pool-target-path").set_text("")
        self.widget("pool-source-path").get_child().set_text("")
        self.widget("pool-hostname").set_text("")
        self.widget("pool-iqn-chk").set_active(False)
        self.widget("pool-iqn-chk").toggled()
        self.widget("pool-iqn").set_text("")
        self.widget("pool-format").set_active(0)

        uiutil.set_list_selection(self.widget("pool-type"), 0)
        self._show_options_by_pool()


    #################
    # UI populating #
    #################

    def _populate_pool_sources(self):
        pooltype = self._get_config_pool_type()
        source_list = self.widget("pool-source-path")
        source_list.get_model().clear()

        name_list = self.widget("pool-source-name")
        name_list.get_model().clear()

        if pooltype == StoragePool.TYPE_SCSI:
            host_list = self._list_scsi_adapters()
            entry_list = [[h, h] for h in host_list]
            use_list = source_list

        elif pooltype == StoragePool.TYPE_LOGICAL:
            vglist = self._list_pool_sources(pooltype)
            entry_list = [[v, v] for v in vglist]
            use_list = name_list

        else:
            return

        for e in entry_list:
            use_list.get_model().append(e)
        if entry_list:
            use_list.set_active(0)

    def _list_scsi_adapters(self):
        scsi_hosts = self.conn.filter_nodedevs("scsi_host")
        host_list = [dev.xmlobj.host for dev in scsi_hosts]
        return ["host%s" % h for h in host_list]

    def _list_pool_sources(self, pool_type):
        plist = []
        try:
            plist = StoragePool.pool_list_from_sources(
                    self.conn.get_backend(), pool_type)
        except Exception:  # pragma: no cover
            log.exception("Pool enumeration failed")

        return plist

    def _get_build_default(self, pooltype):
        if pooltype in [StoragePool.TYPE_DIR,
                        StoragePool.TYPE_FS,
                        StoragePool.TYPE_NETFS]:
            # Building for these simply entails creating a directory
            return True
        return False

    def _show_options_by_pool(self):
        def show_row(base, do_show):
            widget = self.widget(base + "-label")
            uiutil.set_grid_row_visible(widget, do_show)

        pool = self._make_stub_pool()
        src = pool.supports_source_path()
        src_b = src and not self.conn.is_remote()
        tgt = pool.supports_target_path()
        tgt_b = tgt and not self.conn.is_remote()
        host = pool.supports_hosts()
        fmt = pool.supports_format()
        iqn = pool.supports_iqn()

        src_name = pool.supports_source_name()
        is_lvm = pool.type == StoragePool.TYPE_LOGICAL
        is_scsi = pool.type == StoragePool.TYPE_SCSI

        # Source path browsing is meaningless for net pools
        if pool.type in [StoragePool.TYPE_NETFS,
                               StoragePool.TYPE_ISCSI,
                               StoragePool.TYPE_SCSI,
                               StoragePool.TYPE_GLUSTER]:
            src_b = False

        show_row("pool-target", tgt)
        show_row("pool-source", src)
        show_row("pool-hostname", host)
        show_row("pool-format", fmt)
        show_row("pool-iqn", iqn)
        show_row("pool-source-name", src_name)

        self.widget("pool-source-name-label").set_label(
                is_lvm and _("Volg_roup Name:") or _("Sou_rce Name:"))

        src_label = _("_Source Path:")
        if iqn:
            src_label = _("_Source IQN:")
        elif is_scsi:
            src_label = _("_Source Adapter:")
        self.widget("pool-source-label").set_text(src_label)
        self.widget("pool-source-label").set_use_underline(True)

        if tgt:
            self.widget("pool-target-path").set_text(
                pool.default_target_path() or "")

        self.widget("pool-target-button").set_sensitive(tgt_b)
        self.widget("pool-source-button").set_sensitive(src_b)

        if src_name:
            self.widget("pool-source-name").get_child().set_text(
                    pool.default_source_name() or "")

        self._populate_pool_sources()


    ################
    # UI accessors #
    ################

    def _get_visible_text(self, widget_name, column=None):
        widget = self.widget(widget_name)
        if not widget.get_sensitive() or not widget.get_visible():
            return None
        if column is None:
            return widget.get_text().strip()

        return uiutil.get_list_selection(widget, column=column)

    def _get_config_pool_type(self):
        return uiutil.get_list_selection(self.widget("pool-type"))

    def _get_config_target_path(self):
        return self._get_visible_text("pool-target-path")

    def _get_config_source_path(self):
        return self._get_visible_text("pool-source-path", column=1)

    def _get_config_host(self):
        return self._get_visible_text("pool-hostname")

    def _get_config_source_name(self):
        return self._get_visible_text("pool-source-name", column=1)

    def _get_config_format(self):
        return uiutil.get_list_selection(self.widget("pool-format"))

    def _get_config_iqn(self):
        return self._get_visible_text("pool-iqn")


    ###################
    # Object building #
    ###################

    def _build_xmlobj_from_xmleditor(self):
        xml = self._xmleditor.get_xml()
        log.debug("Using XML from xmleditor:\n%s", xml)
        return StoragePool(self.conn.get_backend(), parsexml=xml)

    def _make_stub_pool(self):
        pool = StoragePool(self.conn.get_backend())
        pool.type = self._get_config_pool_type()
        pool.name = self.widget("pool-name").get_text()
        return pool

    def _build_xmlobj_from_ui(self):
        target = self._get_config_target_path()
        host = self._get_config_host()
        source = self._get_config_source_path()
        fmt = self._get_config_format()
        iqn = self._get_config_iqn()
        source_name = self._get_config_source_name()

        pool = self._make_stub_pool()

        pool.target_path = target
        if host:
            hostobj = pool.hosts.add_new()
            hostobj.name = host
        if source:
            pool.source_path = source
        if fmt and pool.supports_format():
            pool.format = fmt
        if iqn:
            pool.iqn = iqn
        if source_name:
            pool.source_name = source_name
        return pool

    def _build_xmlobj(self, check_xmleditor):
        try:
            xmlobj = self._build_xmlobj_from_ui()
            if check_xmleditor and self._xmleditor.is_xml_selected():
                xmlobj = self._build_xmlobj_from_xmleditor()
            return xmlobj
        except Exception as e:
            self.err.show_err(_("Error building XML: %s") % str(e))

    def _validate(self, pool):
        pool.validate()


    ##################
    # Object install #
    ##################

    def _finish_cb(self, error, details, pool):
        self.reset_finish_cursor()

        if error:
            error = _("Error creating pool: %s") % error
            self.err.show_err(error,
                              details=details)
        else:
            self.conn.schedule_priority_tick(pollpool=True)
            self.close()

    def _async_pool_create(self, asyncjob, pool, build):
        meter = asyncjob.get_meter()

        log.debug("Starting background pool creation.")
        poolobj = pool.install(create=True, meter=meter, build=build)
        poolobj.setAutostart(True)
        log.debug("Pool creation succeeded")

    def _finish(self):
        pool = self._build_xmlobj(check_xmleditor=True)
        if not pool:
            return

        try:
            self._validate(pool)
            build = self._get_build_default(pool.type)
        except Exception as e:  # pragma: no cover
            return self.err.show_err(_("Error validating pool: %s") % e)

        self.reset_finish_cursor()

        progWin = vmmAsyncJob(self._async_pool_create, [pool, build],
                              self._finish_cb, [pool],
                              _("Creating storage pool..."),
                              _("Creating the storage pool may take a "
                                "while..."),
                              self.topwin)
        progWin.run()


    ################
    # UI listeners #
    ################

    def _xmleditor_xml_requested_cb(self, src):
        xmlobj = self._build_xmlobj(check_xmleditor=False)
        self._xmleditor.set_xml(xmlobj and xmlobj.get_xml() or "")

    def _finish_clicked_cb(self, src):
        self._finish()

    def _pool_type_changed_cb(self, src):
        self._show_options_by_pool()

    def _browse_source_cb(self, src):
        source = self.err.browse_local(self.conn,
                _("Choose source path"),
                dialog_type=Gtk.FileChooserAction.OPEN,
                start_folder="/dev")
        if source:
            self.widget("pool-source-path").get_child().set_text(source)

    def _browse_target_cb(self, src):
        current = self._get_config_target_path()
        startfolder = None
        if current:
            startfolder = os.path.dirname(current)

        target = self.err.browse_local(self.conn,
                _("Choose target directory"),
                dialog_type=Gtk.FileChooserAction.SELECT_FOLDER,
                start_folder=startfolder)
        if target:
            self.widget("pool-target-path").set_text(target)

    def _iqn_toggled_cb(self, src):
        self.widget("pool-iqn").set_sensitive(src.get_active())

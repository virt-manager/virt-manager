# Copyright (C) 2008, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2008 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging

from gi.repository import Gdk
from gi.repository import Gtk

from virtinst import StoragePool

from .baseclass import vmmGObjectUI
from .asyncjob import vmmAsyncJob
from . import uiutil


class vmmCreatePool(vmmGObjectUI):
    __gsignals__ = {
        "pool-created": (vmmGObjectUI.RUN_FIRST, None, [str]),
    }

    def __init__(self, conn):
        vmmGObjectUI.__init__(self, "createpool.ui", "vmm-create-pool")
        self.conn = conn

        self.builder.connect_signals({
            "on_pool_cancel_clicked": self.close,
            "on_vmm_create_pool_delete_event": self.close,
            "on_pool_finish_clicked": self._finish_clicked_cb,
            "on_pool_type_changed": self._pool_type_changed_cb,

            "on_pool_source_button_clicked": self._browse_source_cb,
            "on_pool_target_button_clicked": self._browse_target_cb,

            "on_pool_hostname_activate": self._hostname_changed_cb,
            "on_pool_iqn_chk_toggled": self._iqn_toggled_cb,
        })
        self.bind_escape_key_close()

        self._init_ui()


    #######################
    # Standard UI methods #
    #######################

    def show(self, parent):
        logging.debug("Showing new pool wizard")
        self._reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing new pool wizard")
        self.topwin.hide()
        return 1

    def _cleanup(self):
        self.conn = None

    ###########
    # UI init #
    ###########

    def _build_pool_type_list(self):
        # [pool type, label]
        model = Gtk.ListStore(str, str)
        type_list = self.widget("pool-type")
        type_list.set_model(model)
        uiutil.init_combo_text_column(type_list, 1)

        for typ in sorted(StoragePool.get_pool_types()):
            desc = StoragePool.get_pool_type_desc(typ)
            model.append([typ, "%s: %s" % (typ, desc)])

    def _init_ui(self):
        blue = Gdk.Color.parse("#0072A8")[1]
        self.widget("header").modify_bg(Gtk.StateType.NORMAL, blue)

        format_list = self.widget("pool-format")
        format_model = Gtk.ListStore(str, str)
        format_list.set_model(format_model)
        uiutil.init_combo_text_column(format_list, 1)
        for f in ["auto"]:
            format_model.append([f, f])

        # Target path combo box entry
        target_list = self.widget("pool-target-path")
        # target_path, Label, pool class instance
        target_model = Gtk.ListStore(str, str, object)
        target_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        target_list.set_model(target_model)
        target_list.set_entry_text_column(0)

        # Source path combo box entry
        source_list = self.widget("pool-source-path")
        # source_path, Label, pool class instance
        source_model = Gtk.ListStore(str, str, object)
        source_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        source_list.set_model(source_model)
        source_list.set_entry_text_column(0)

        self._build_pool_type_list()

    def _reset_state(self):
        defaultname = StoragePool.find_free_name(
                self.conn.get_backend(), "pool")
        self.widget("pool-name").set_text(defaultname)
        self.widget("pool-name").grab_focus()
        self.widget("pool-target-path").get_child().set_text("")
        self.widget("pool-source-path").get_child().set_text("")
        self.widget("pool-hostname").set_text("")
        self.widget("pool-iqn-chk").set_active(False)
        self.widget("pool-iqn-chk").toggled()
        self.widget("pool-iqn").set_text("")
        self.widget("pool-format").set_active(0)
        self.widget("pool-build").set_sensitive(True)
        self.widget("pool-build").set_active(False)

        uiutil.set_list_selection(self.widget("pool-type"), 0)
        self._show_options_by_pool()


    #################
    # UI populating #
    #################

    def _populate_pool_sources(self):
        pooltype = self._get_config_pool_type()
        source_list = self.widget("pool-source-path")
        source_model = source_list.get_model()
        source_model.clear()

        target_list = self.widget("pool-target-path")
        target_model = target_list.get_model()
        target_model.clear()

        use_list = source_list
        use_model = source_model
        entry_list = []
        if pooltype == StoragePool.TYPE_SCSI:
            entry_list = self._list_scsi_adapters()
            use_list = source_list
            use_model = source_model

        elif pooltype == StoragePool.TYPE_LOGICAL:
            pool_list = self._list_pool_sources(pooltype)
            entry_list = [[p.target_path, p.target_path, p]
                          for p in pool_list]
            use_list = target_list
            use_model = target_model

        elif pooltype == StoragePool.TYPE_DISK:
            entry_list = self._list_disk_devs()
            use_list = source_list
            use_model = source_model

        elif pooltype == StoragePool.TYPE_NETFS:
            host = self._get_config_host()
            if host:
                pool_list = self._list_pool_sources(pooltype, host=host)
                entry_list = [[p.source_path, p.source_path, p]
                              for p in pool_list]
                use_list = source_list
                use_model = source_model

        for e in entry_list:
            use_model.append(e)

        if entry_list:
            use_list.set_active(0)

    def _list_scsi_adapters(self):
        scsi_hosts = self.conn.filter_nodedevs("scsi_host")
        host_list = [dev.xmlobj.host for dev in scsi_hosts]

        clean_list = []
        for h in host_list:
            name = "host%s" % h
            tmppool = self._make_stub_pool()
            tmppool.source_path = name

            entry = [name, name, tmppool]
            if name not in [l[0] for l in clean_list]:
                clean_list.append(entry)

        return clean_list

    def _list_disk_devs(self):
        devs = self.conn.filter_nodedevs("storage")
        devlist = []
        for dev in devs:
            if dev.xmlobj.drive_type != "disk" or not dev.xmlobj.block:
                continue
            devlist.append(dev.xmlobj.block)

        devlist.sort()
        clean_list = []
        for dev in devlist:
            tmppool = self._make_stub_pool()
            tmppool.source_path = dev

            entry = [dev, dev, tmppool]
            if dev not in [l[0] for l in clean_list]:
                clean_list.append(entry)

        return clean_list

    def _list_pool_sources(self, pool_type, host=None):
        plist = []
        try:
            plist = StoragePool.pool_list_from_sources(
                                                self.conn.get_backend(),
                                                pool_type,
                                                host=host)
        except Exception:
            logging.exception("Pool enumeration failed")

        return plist

    def _get_build_default(self, pooltype):
        """ Return (default value, whether build option can be changed)"""
        if not pooltype:
            return (False, False)

        if pooltype in [StoragePool.TYPE_DIR,
                        StoragePool.TYPE_FS,
                        StoragePool.TYPE_NETFS]:
            # Building for these simply entails creating a directory
            return (True, False)
        elif pooltype in [StoragePool.TYPE_LOGICAL,
                          StoragePool.TYPE_DISK]:
            # This is a dangerous operation, anything (False, True)
            # should be assumed to be one.
            return (False, True)

        return (False, False)

    def _show_options_by_pool(self):
        def show_row(base, do_show):
            widget = self.widget(base + "-label")
            uiutil.set_grid_row_visible(widget, do_show)

        pool = self._make_stub_pool()
        src = pool.supports_property("source_path")
        src_b = src and not self.conn.is_remote()
        tgt = pool.supports_property("target_path")
        tgt_b = tgt and not self.conn.is_remote()
        host = pool.supports_property("hosts")
        fmt = pool.supports_property("format")
        iqn = pool.supports_property("iqn")
        builddef, buildsens = self._get_build_default(pool.type)

        # We don't show source_name for logical pools, since we use
        # pool-sources to avoid the need for it
        src_name = (pool.supports_property("source_name") and
                    pool.type != pool.TYPE_LOGICAL)

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
        show_row("pool-build", buildsens)
        show_row("pool-iqn", iqn)
        show_row("pool-source-name", src_name)

        if iqn:
            self.widget("pool-source-label").set_label(_("_Source IQN:"))
        else:
            self.widget("pool-source-label").set_label(_("_Source Path:"))

        if tgt:
            self.widget("pool-target-path").get_child().set_text(
                pool.default_target_path() or "")

        self.widget("pool-target-button").set_sensitive(tgt_b)
        self.widget("pool-source-button").set_sensitive(src_b)
        self.widget("pool-build").set_active(builddef)

        if src_name:
            self.widget("pool-source-name").set_text(
                    pool.default_source_name())

        self._populate_pool_sources()


    ################
    # UI accessors #
    ################

    def _get_config_pool_type(self):
        return uiutil.get_list_selection(self.widget("pool-type"))

    def _get_config_target_path(self):
        src = self.widget("pool-target-path")
        if not src.get_sensitive():
            return None

        ret = uiutil.get_list_selection(src, column=1)
        if ret is not None:
            return ret
        return src.get_child().get_text()

    def _get_config_source_path(self):
        src = self.widget("pool-source-path")
        if not src.get_sensitive():
            return None

        ret = uiutil.get_list_selection(src, column=1)
        if ret is not None:
            return ret
        return src.get_child().get_text().strip()

    def _get_config_host(self):
        host = self.widget("pool-hostname")
        if host.get_sensitive():
            return host.get_text().strip()
        return None

    def _get_config_source_name(self):
        name = self.widget("pool-source-name")
        if name.get_sensitive():
            return name.get_text().strip()
        return None

    def _get_config_format(self):
        return uiutil.get_list_selection(self.widget("pool-format"))

    def _get_config_iqn(self):
        iqn = self.widget("pool-iqn")
        if iqn.get_sensitive() and iqn.get_visible():
            return iqn.get_text().strip()
        return None


    ###################
    # Object building #
    ###################

    def _get_pool_from_sourcelist(self):
        """
        If an enumerated pool source was selected, use that as the
        basis for our pool object
        """
        source_list = self.widget("pool-source-path")
        target_list = self.widget("pool-target-path")

        pool = uiutil.get_list_selection(source_list, column=2,
                                         check_entry=False)
        if pool is None:
            pool = uiutil.get_list_selection(target_list, column=2,
                                             check_entry=False)

        return pool

    def _make_stub_pool(self):
        pool = self._get_pool_from_sourcelist()
        if not pool:
            pool = StoragePool(self.conn.get_backend())
        pool.type = self._get_config_pool_type()
        pool.name = self.widget("pool-name").get_text()
        return pool

    def _build_pool(self):
        target = self._get_config_target_path()
        host = self._get_config_host()
        source = self._get_config_source_path()
        fmt = self._get_config_format()
        iqn = self._get_config_iqn()
        source_name = self._get_config_source_name()

        try:
            pool = self._make_stub_pool()

            pool.target_path = target
            if host:
                hostobj = pool.hosts.add_new()
                hostobj.name = host
            if source:
                pool.source_path = source
            if fmt and pool.supports_property("format"):
                pool.format = fmt
            if iqn:
                pool.iqn = iqn
            if source_name:
                pool.source_name = source_name

            pool.validate()
        except ValueError as e:
            return self.err.val_err(_("Pool Parameter Error"), e)

        buildval = self.widget("pool-build").get_active()
        buildsen = (self.widget("pool-build").get_sensitive() and
                    self.widget("pool-build").get_visible())
        if buildsen and buildval:
            ret = self.err.yes_no(_("Building a pool of this type will "
                                    "format the source device. Are you "
                                    "sure you want to 'build' this pool?"))
            if not ret:
                return ret

        return pool


    ##################
    # Object install #
    ##################

    def _pool_added_cb(self, src, connkey, created_name):
        if connkey == created_name:
            self.emit("pool-created", connkey)

    def _finish_cb(self, error, details, pool):
        self.reset_finish_cursor()

        if error:
            error = _("Error creating pool: %s") % error
            self.err.show_err(error,
                              details=details)
        else:
            self.conn.connect_once("pool-added", self._pool_added_cb,
                pool.name)
            self.conn.schedule_priority_tick(pollpool=True)
            self.close()

    def _async_pool_create(self, asyncjob, pool, build):
        meter = asyncjob.get_meter()

        logging.debug("Starting background pool creation.")
        poolobj = pool.install(create=True, meter=meter, build=build)
        poolobj.setAutostart(True)
        logging.debug("Pool creation succeeded")

    def _finish(self):
        try:
            pool = self._build_pool()
            if not pool:
                return
        except Exception as e:
            self.err.show_err(
                    _("Uncaught error validating input: %s") % str(e))
            return

        self.reset_finish_cursor()

        build = self.widget("pool-build").get_active()
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
        startfolder = StoragePool.get_default_dir(self.conn.get_backend())
        target = self.err.browse_local(self.conn,
                _("Choose target directory"),
                dialog_type=Gtk.FileChooserAction.SELECT_FOLDER,
                start_folder=startfolder)
        if target:
            self.widget("pool-target-path").get_child().set_text(target)

    def _hostname_changed_cb(self, src):
        # If a hostname was entered, try to lookup valid pool sources.
        self._populate_pool_sources()

    def _iqn_toggled_cb(self, src):
        self.widget("pool-iqn").set_sensitive(src.get_active())

# Copyright (C) 2008, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2008 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gtk

from virtinst import log
from virtinst import StorageVolume

from .lib import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI
from .xmleditor import vmmXMLEditor


class vmmCreateVolume(vmmGObjectUI):
    __gsignals__ = {
        "vol-created": (vmmGObjectUI.RUN_FIRST, None, [object, object]),
    }

    def __init__(self, conn, parent_pool):
        vmmGObjectUI.__init__(self, "createvol.ui", "vmm-create-vol")
        self.conn = conn

        self._parent_pool = parent_pool
        self._name_hint = None
        self._storage_browser = None

        self._xmleditor = vmmXMLEditor(self.builder, self.topwin,
                self.widget("details-box-align"),
                self.widget("details-box"))
        self._xmleditor.connect("xml-requested",
                self._xmleditor_xml_requested_cb)

        self.builder.connect_signals({
            "on_vmm_create_vol_delete_event": self.close,
            "on_vol_cancel_clicked": self.close,
            "on_vol_create_clicked": self._create_clicked_cb,

            "on_vol_name_changed": self._vol_name_changed_cb,
            "on_vol_format_changed": self._vol_format_changed_cb,
            "on_backing_browse_clicked": self._browse_backing_clicked_cb,
        })
        self.bind_escape_key_close()

        self._init_state()


    #######################
    # Standard UI methods #
    #######################

    def show(self, parent):
        try:
            parent_xml = self._parent_pool.xmlobj.get_xml()
        except Exception:  # pragma: no cover
            log.debug("Error getting parent_pool xml", exc_info=True)
            parent_xml = None

        log.debug("Showing new volume wizard for parent_pool=\n%s",
            parent_xml)
        self._reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        log.debug("Closing new volume wizard")
        self.topwin.hide()
        if self._storage_browser:
            self._storage_browser.close()
        self.set_modal(False)
        return 1

    def _cleanup(self):
        self.conn = None
        self._parent_pool = None
        self._xmleditor.cleanup()
        self._xmleditor = None

        if self._storage_browser:
            self._storage_browser.cleanup()
            self._storage_browser = None


    ##############
    # Public API #
    ##############

    def set_name_hint(self, hint):
        self._name_hint = hint

    def set_modal(self, modal):
        self.topwin.set_modal(bool(modal))

    def set_parent_pool(self, pool):
        self._parent_pool = pool


    ###########
    # UI init #
    ###########

    def _init_state(self):
        format_list = self.widget("vol-format")
        format_model = Gtk.ListStore(str, str)
        format_list.set_model(format_model)
        uiutil.init_combo_text_column(format_list, 1)
        for fmt in ["raw", "qcow2"]:
            format_model.append([fmt, fmt])

    def _reset_state(self):
        self._xmleditor.reset_state()

        vol = self._make_stub_vol()

        hasformat = vol.supports_format()
        uiutil.set_grid_row_visible(self.widget("vol-format"), hasformat)
        uiutil.set_list_selection(self.widget("vol-format"),
            self.conn.get_default_storage_format())

        self.widget("vol-name").set_text(self._default_vol_name() or "")
        self.widget("vol-name").grab_focus()
        self.widget("vol-name").emit("changed")

        self.widget("backing-store").set_text("")
        self.widget("vol-nonsparse").set_active(
                not self._should_default_sparse())
        self._show_sparse()
        self._show_backing()
        self.widget("backing-expander").set_expanded(False)

        pool_avail = int(self._parent_pool.get_available() / 1024 / 1024 / 1024)
        default_cap = 20
        self.widget("vol-capacity").set_range(0.1, 1000000)
        self.widget("vol-capacity").set_value(min(default_cap, pool_avail))

        self.widget("vol-parent-info").set_markup(
                        _("<b>%(volume)s's</b> available space: %(size)s") % {
                            "volume": self._parent_pool.get_name(),
                            "size": self._parent_pool.get_pretty_available(),
                        })


    ###################
    # Helper routines #
    ###################

    def _get_config_format(self):
        if not self.widget("vol-format").get_visible():
            return None
        return uiutil.get_list_selection(self.widget("vol-format"))

    def _default_vol_name(self):
        hint = self._name_hint or "vol"
        suffix = self._default_suffix()
        ret = ""
        try:
            ret = StorageVolume.find_free_name(
                self.conn.get_backend(),
                self._parent_pool.get_backend(),
                hint, suffix=suffix)
            if ret and suffix:
                ret = ret.rsplit(".", 1)[0]
        except Exception:  # pragma: no cover
            log.exception("Error finding a default vol name")

        return ret

    def _default_suffix(self):
        vol = self._make_stub_vol()
        if vol.file_type != vol.TYPE_FILE:
            return ""
        return StorageVolume.get_file_extension_for_format(
            self._get_config_format())

    def _should_default_sparse(self):
        return self._get_config_format() == "qcow2"

    def _can_sparse(self):
        dtype = self._parent_pool.xmlobj.get_disk_type()
        return dtype == StorageVolume.TYPE_FILE

    def _show_sparse(self):
        uiutil.set_grid_row_visible(
            self.widget("vol-nonsparse"), self._can_sparse())

    def _can_backing(self):
        if self._parent_pool.get_type() == "logical":
            return True
        if self._get_config_format() == "qcow2":
            return True
        return False

    def _show_backing(self):
        uiutil.set_grid_row_visible(
            self.widget("backing-expander"), self._can_backing())

    def _browse_file(self):
        if self._storage_browser is None:
            def cb(src, text):
                ignore = src
                self.widget("backing-store").set_text(text)

            from .storagebrowse import vmmStorageBrowser
            self._storage_browser = vmmStorageBrowser(self.conn)
            self._storage_browser.set_finish_cb(cb)
            self._storage_browser.topwin.set_modal(self.topwin.get_modal())
            self._storage_browser.set_browse_reason(
                self.config.CONFIG_DIR_IMAGE)

        self._storage_browser.show(self.topwin)

    def _show_err(self, info, details=None):
        self.err.show_err(info, details, modal=self.topwin.get_modal())


    ###################
    # Object building #
    ###################

    def _make_stub_vol(self, xml=None):
        vol = StorageVolume(self.conn.get_backend(), parsexml=xml)
        vol.pool = self._parent_pool.get_backend()
        return vol

    def _build_xmlobj_from_xmleditor(self):
        xml = self._xmleditor.get_xml()
        log.debug("Using XML from xmleditor:\n%s", xml)
        return self._make_stub_vol(xml=xml)

    def _build_xmlobj_from_ui(self):
        name = self.widget("vol-name").get_text()
        suffix = self.widget("vol-name-suffix").get_text()
        volname = name + suffix
        fmt = self._get_config_format()
        cap = self.widget("vol-capacity").get_value()
        nonsparse = self.widget("vol-nonsparse").get_active()
        backing = self.widget("backing-store").get_text()

        alloc = 0
        if nonsparse:
            alloc = cap

        vol = self._make_stub_vol()
        vol.name = volname
        vol.capacity = (cap * 1024 * 1024 * 1024)
        vol.allocation = (alloc * 1024 * 1024 * 1024)
        if backing:
            vol.backing_store = backing
        if fmt:
            vol.format = fmt
        return vol

    def _build_xmlobj(self, check_xmleditor):
        try:
            xmlobj = self._build_xmlobj_from_ui()
            if check_xmleditor and self._xmleditor.is_xml_selected():
                xmlobj = self._build_xmlobj_from_xmleditor()
            return xmlobj
        except Exception as e:
            self.err.show_err(_("Error building XML: %s") % str(e))


    ##################
    # Object install #
    ##################

    def _pool_refreshed_cb(self, pool, volname):
        vol = pool.get_volume_by_name(volname)
        self.emit("vol-created", pool, vol)

    def _finish_cb(self, error, details, vol):
        self.reset_finish_cursor()

        if error:  # pragma: no cover
            error = _("Error creating vol: %s") % error
            self._show_err(error, details=details)
            return
        self._parent_pool.connect("refreshed",
            self._pool_refreshed_cb, vol.name)
        self.idle_add(self._parent_pool.refresh)
        self.close()

    def _finish(self):
        vol = self._build_xmlobj(check_xmleditor=True)
        if not vol:
            return

        try:
            vol.validate()
        except Exception as e:
            return self._show_err(_("Error validating volume: %s") % str(e))

        self.set_finish_cursor()
        progWin = vmmAsyncJob(self._async_vol_create, [vol],
                              self._finish_cb, [vol],
                              _("Creating storage volume..."),
                              _("Creating the storage volume may take a "
                                "while..."),
                              self.topwin)
        progWin.run()

    def _async_vol_create(self, asyncjob, vol):
        conn = self.conn.get_backend()

        # Lookup different pool obj
        newpool = conn.storagePoolLookupByName(self._parent_pool.get_name())
        vol.pool = newpool

        meter = asyncjob.get_meter()
        log.debug("Starting background vol creation.")
        vol.install(meter=meter)
        log.debug("vol creation complete.")


    ################
    # UI listeners #
    ################

    def _xmleditor_xml_requested_cb(self, src):
        xmlobj = self._build_xmlobj(check_xmleditor=False)
        self._xmleditor.set_xml(xmlobj and xmlobj.get_xml() or "")

    def _vol_format_changed_cb(self, src):
        self._show_sparse()
        self.widget("vol-nonsparse").set_active(
                not self._should_default_sparse())
        self._show_backing()
        self.widget("vol-name").emit("changed")

    def _vol_name_changed_cb(self, src):
        text = src.get_text()

        suffix = self._default_suffix()
        if "." in text:
            suffix = ""
        self.widget("vol-name-suffix").set_text(suffix)

    def _browse_backing_clicked_cb(self, src):
        self._browse_file()

    def _create_clicked_cb(self, src):
        self._finish()

# Copyright (C) 2009, 2013 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import traceback

from gi.repository import Gtk
from gi.repository import Pango

from virtinst import log
from virtinst import xmlutil

from .lib import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI
from .connmanager import vmmConnectionManager
from .object.domain import vmmDomain
from .xmleditor import vmmXMLEditor


NUM_COLS = 3
(COL_LABEL,
 COL_URI,
 COL_CAN_MIGRATE) = range(NUM_COLS)


class vmmMigrateDialog(vmmGObjectUI):
    @classmethod
    def show_instance(cls, parentobj, vm):
        try:
            if not cls._instance:
                cls._instance = vmmMigrateDialog()
            cls._instance.show(parentobj.topwin, vm)
        except Exception as e:  # pragma: no cover
            parentobj.err.show_err(
                    _("Error launching migrate dialog: %s") % str(e))

    def __init__(self):
        vmmGObjectUI.__init__(self, "migrate.ui", "vmm-migrate")
        self.vm = None

        self._xmleditor = vmmXMLEditor(self.builder, self.topwin,
                self.widget("details-box-align"),
                self.widget("details-box"))
        self._xmleditor.connect("xml-requested",
                self._xmleditor_xml_requested_cb)

        self.builder.connect_signals({
            "on_vmm_migrate_delete_event": self._delete_event,
            "on_migrate_cancel_clicked": self._cancel_clicked,
            "on_migrate_finish_clicked": self._finish_clicked,

            "on_migrate_dest_changed": self._destconn_changed,
            "on_migrate_set_address_toggled": self._set_address_toggled,
            "on_migrate_set_port_toggled": self._set_port_toggled,
            "on_migrate_mode_changed": self._mode_changed,
        })
        self.bind_escape_key_close()
        self._cleanup_on_app_close()

        self._init_state()


    def _cleanup(self):
        self.vm = None
        self._xmleditor.cleanup()
        self._xmleditor = None

    @property
    def _connobjs(self):
        return vmmConnectionManager.get_instance().conns

    @property
    def conn(self):
        return self.vm and self.vm.conn or None


    ##############
    # Public API #
    ##############

    def show(self, parent, vm):
        log.debug("Showing migrate wizard")
        self._set_vm(vm)
        self._reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        log.debug("Closing migrate wizard")
        self.topwin.hide()
        self._set_vm(None)
        return 1

    def _vm_removed_cb(self, _conn, vm):
        if self.vm == vm:
            self.close()

    def _set_vm(self, newvm):
        oldvm = self.vm
        if oldvm:
            oldvm.conn.disconnect_by_obj(self)
        if newvm:
            newvm.conn.connect("vm-removed", self._vm_removed_cb)
        self.vm = newvm


    ################
    # Init helpers #
    ################

    def _init_state(self):
        # Connection combo
        cols = [None] * NUM_COLS
        cols[COL_LABEL] = str
        cols[COL_URI] = str
        cols[COL_CAN_MIGRATE] = bool
        model = Gtk.ListStore(*cols)
        combo = self.widget("migrate-dest")
        combo.set_model(model)
        text = uiutil.init_combo_text_column(combo, COL_LABEL)
        text.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        text.set_property("width-chars", 30)
        combo.add_attribute(text, 'sensitive', COL_CAN_MIGRATE)
        model.set_sort_column_id(COL_LABEL, Gtk.SortType.ASCENDING)

        def _sorter(model, iter1, iter2, ignore):
            def _cmp(a, b):
                return ((a > b) - (a < b))

            row1 = model[iter1]
            row2 = model[iter2]
            if row1[COL_URI] is None:
                return -1
            return _cmp(row1[COL_LABEL], row2[COL_LABEL])
        model.set_sort_func(COL_LABEL, _sorter)

        # Mode combo
        combo = self.widget("migrate-mode")
        # label, is_tunnel
        model = Gtk.ListStore(str, bool)
        model.append([_("Direct"), False])
        model.append([_("Tunnelled"), True])
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 0)

        self.widget("migrate-dest").emit("changed")

        self.widget("migrate-mode").set_tooltip_text(
            self.widget("migrate-mode-label").get_tooltip_text())
        self.widget("migrate-unsafe").set_tooltip_text(
            self.widget("migrate-unsafe-label").get_tooltip_text())
        self.widget("migrate-temporary").set_tooltip_text(
            self.widget("migrate-temporary-label").get_tooltip_text())

    def _reset_state(self):
        self._xmleditor.reset_state()

        title_str = _("<span size='large'>Migrate '%(vm)s'</span>") % {
            "vm": xmlutil.xml_escape(self.vm.get_name()),
        }
        self.widget("header-label").set_markup(title_str)

        self.widget("migrate-advanced-expander").set_expanded(False)

        self.widget("migrate-cancel").grab_focus()

        self.widget("config-box").set_visible(True)

        hostname = self.conn.libvirt_gethostname()
        srctext = "%s (%s)" % (hostname, self.conn.get_pretty_desc())
        self.widget("migrate-label-name").set_text(self.vm.get_name_or_title())
        self.widget("migrate-label-src").set_text(srctext)
        self.widget("migrate-label-src").set_tooltip_text(self.conn.get_uri())

        self.widget("migrate-set-address").set_active(True)
        self.widget("migrate-set-address").emit("toggled")
        self.widget("migrate-set-port").set_active(True)

        self.widget("migrate-mode").set_active(0)
        self.widget("migrate-unsafe").set_active(False)
        self.widget("migrate-temporary").set_active(False)

        if self.conn.is_xen():
            # Default xen port is 8002
            self.widget("migrate-port").set_value(8002)
        else:
            # QEMU migrate port range is 49152+64
            self.widget("migrate-port").set_value(49152)

        self._populate_destconn()


    #############
    # Listeners #
    #############

    def _delete_event(self, ignore1, ignore2):
        self.close()
        return 1

    def _cancel_clicked(self, src):
        ignore = src
        self.close()

    def _finish_clicked(self, src):
        ignore = src
        self._finish()

    def _destconn_changed(self, src):
        row = uiutil.get_list_selected_row(src)
        if not row:
            return

        can_migrate = row and row[COL_CAN_MIGRATE] or False
        uri = row[COL_URI]

        tooltip = ""
        if not can_migrate:
            tooltip = _("A valid destination connection must be selected.")

        self.widget("config-box").set_visible(can_migrate)
        self.widget("migrate-finish").set_sensitive(can_migrate)
        self.widget("migrate-finish").set_tooltip_text(tooltip)

        address = ""
        tunnel_warning = ""
        tunnel_uri = ""

        if can_migrate and uri in self._connobjs:
            destconn = self._connobjs[uri]

            tunnel_uri = destconn.get_uri()
            if not destconn.is_remote():
                tunnel_warning = _("A remotely accessible libvirt URI "
                    "is required for tunneled migration, but the "
                    "selected connection is a local URI. Libvirt will "
                    "reject this unless you add a transport.")
                tunnel_warning = ("<span size='small'>%s</span>" %
                    tunnel_warning)

            address = destconn.libvirt_gethostname()

        self.widget("migrate-address").set_text(address)

        self.widget("migrate-tunnel-uri").set_text(tunnel_uri)
        uiutil.set_grid_row_visible(
            self.widget("migrate-tunnel-warning-box"), bool(tunnel_warning))
        self.widget("migrate-tunnel-warning-label").set_markup(tunnel_warning)


    def _set_address_toggled(self, src):
        enable = src.get_active()
        self.widget("migrate-address").set_visible(enable)
        self.widget("migrate-address-label").set_visible(not enable)

        port_enable = self.widget("migrate-set-port").get_active()
        self.widget("migrate-set-port").set_active(enable and port_enable)
        self.widget("migrate-set-port").emit("toggled")

    def _set_port_toggled(self, src):
        enable = src.get_active()
        self.widget("migrate-port").set_visible(enable)
        self.widget("migrate-port-label").set_visible(not enable)

    def _is_tunnel_selected(self):
        return uiutil.get_list_selection(self.widget("migrate-mode"), column=1)

    def _mode_changed(self, src):
        ignore = src
        is_tunnel = self._is_tunnel_selected()
        self.widget("migrate-direct-box").set_visible(not is_tunnel)
        self.widget("migrate-tunnel-box").set_visible(is_tunnel)


    ###########################
    # destconn combo handling #
    ###########################

    def _build_dest_row(self, destconn):
        driver = self.conn.get_driver()
        origuri = self.conn.get_uri()

        can_migrate = False
        pretty_uri = destconn.get_pretty_desc()
        desc = pretty_uri
        desturi = destconn.get_uri()

        if destconn.get_driver() != driver:
            desc = _("%(uri)s (Hypervisors do not match)") % {"uri": pretty_uri}
        elif destconn.is_disconnected():
            desc = _("%(uri)s (Disconnected)") % {"uri": pretty_uri}
        elif destconn.get_uri() == origuri:
            desc = _("%(uri)s (Same connection)") % {"uri": pretty_uri}
        elif destconn.is_active():
            can_migrate = True

        return [desc, desturi, can_migrate]

    def _populate_destconn(self):
        combo = self.widget("migrate-dest")
        model = combo.get_model()
        model.clear()

        rows = []
        for conn in list(self._connobjs.values()):
            rows.append(self._build_dest_row(conn))

        if not any([row[COL_CAN_MIGRATE] for row in rows]):
            rows.insert(0,
                [_("No usable connections available."), None, False])

        for row in rows:
            model.append(row)

        combo.set_active(0)
        for idx, row in enumerate(model):
            if row[COL_CAN_MIGRATE]:
                combo.set_active(idx)
                break


    ####################
    # migrate handling #
    ####################

    def _build_regular_migrate_uri(self):
        address = None
        if self.widget("migrate-address").get_visible():
            address = self.widget("migrate-address").get_text()

        port = None
        if self.widget("migrate-port").get_visible():
            port = int(self.widget("migrate-port").get_value())

        if not address:
            return

        if self.conn.is_xen():
            uri = "%s" % address
        else:
            uri = "tcp:%s" % address
        if port:
            uri += ":%s" % port
        return uri

    def _finish_cb(self, error, details, destconn):
        self.reset_finish_cursor()

        if error:
            error = _("Unable to migrate guest: %s") % error
            self.err.show_err(error, details=details)
        else:
            destconn.schedule_priority_tick(pollvm=True)
            self.conn.schedule_priority_tick(pollvm=True)
            self.close()

    def _finish(self):
        try:
            xml = None
            if self._xmleditor.is_xml_selected():
                xml = self._xmleditor.get_xml()
                log.debug("Using XML from xmleditor:\n%s", xml)

            row = uiutil.get_list_selected_row(self.widget("migrate-dest"))
            destlabel = row[COL_LABEL]
            destconn = self._connobjs.get(row[COL_URI])

            tunnel = self._is_tunnel_selected()
            unsafe = self.widget("migrate-unsafe").get_active()
            temporary = self.widget("migrate-temporary").get_active()

            if tunnel:
                uri = self.widget("migrate-tunnel-uri").get_text()
            else:
                uri = self._build_regular_migrate_uri()
        except Exception as e:  # pragma: no cover
            details = "".join(traceback.format_exc())
            self.err.show_err((_("Uncaught error validating input: %s") %
                               str(e)),
                               details=details)
            return

        self.set_finish_cursor()

        cancel_cb = None
        if self.vm.supports_domain_job_info():
            cancel_cb = (self._cancel_migration, self.vm)

        if uri:
            destlabel += " " + uri

        progWin = vmmAsyncJob(
            self._async_migrate,
            [self.vm, destconn, uri, tunnel, unsafe, temporary, xml],
            self._finish_cb, [destconn],
            _("Migrating VM '%s'") % self.vm.get_name(),
            (_("Migrating VM '%(name)s' to %(host)s. This may take a while.") %
                {"name": self.vm.get_name(), "host": destlabel}),
            self.topwin, cancel_cb=cancel_cb)
        progWin.run()

    def _cancel_migration(self, asyncjob, vm):
        log.debug("Cancelling migrate job")
        try:
            vm.abort_job()
        except Exception as e:
            log.exception("Error cancelling migrate job")
            asyncjob.show_warning(_("Error cancelling migrate job: %s") % e)
            return

        asyncjob.job_canceled = True  # pragma: no cover

    def _async_migrate(self, asyncjob,
            origvm, origdconn, migrate_uri, tunnel, unsafe, temporary, xml):
        meter = asyncjob.get_meter()

        srcconn = origvm.conn
        dstconn = origdconn

        vminst = srcconn.get_backend().lookupByName(origvm.get_name())
        vm = vmmDomain(srcconn, vminst, vminst.UUID())

        log.debug("Migrating vm=%s from %s to %s", vm.get_name(),
                      srcconn.get_uri(), dstconn.get_uri())

        vm.migrate(dstconn, migrate_uri, tunnel, unsafe, temporary, xml,
            meter=meter)

    ################
    # UI listeners #
    ################

    def _xmleditor_xml_requested_cb(self, src):
        self._xmleditor.set_xml(self.vm.xmlobj.get_xml())

#
# Copyright (C) 2009, 2013 Red Hat, Inc.
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
import traceback

from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository import Pango

from virtinst import util

from . import uiutil
from .baseclass import vmmGObjectUI
from .asyncjob import vmmAsyncJob
from .domain import vmmDomain


NUM_COLS = 3
(COL_LABEL,
 COL_URI,
 COL_CAN_MIGRATE) = range(NUM_COLS)


class vmmMigrateDialog(vmmGObjectUI):
    def __init__(self, engine):
        vmmGObjectUI.__init__(self, "migrate.ui", "vmm-migrate")
        self.vm = None
        self.conn = None
        self._conns = {}

        self.builder.connect_signals({
            "on_vmm_migrate_delete_event" : self._delete_event,
            "on_migrate_cancel_clicked" : self._cancel_clicked,
            "on_migrate_finish_clicked" : self._finish_clicked,

            "on_migrate_dest_changed" : self._destconn_changed,
            "on_migrate_set_address_toggled" : self._set_address_toggled,
            "on_migrate_set_port_toggled" : self._set_port_toggled,
            "on_migrate_mode_changed" : self._mode_changed,
        })
        self.bind_escape_key_close()

        self._init_state(engine)


    def _cleanup(self):
        self.vm = None
        self.conn = None
        self._conns = None


    ##############
    # Public API #
    ##############

    def show(self, parent, vm):
        logging.debug("Showing migrate wizard")
        self.vm = vm
        self.conn = vm.conn
        self._reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing migrate wizard")
        self.topwin.hide()
        return 1


    ################
    # Init helpers #
    ################

    def _init_state(self, engine):
        blue = Gdk.color_parse("#0072A8")
        self.widget("header").modify_bg(Gtk.StateType.NORMAL, blue)

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
            row1 = model[iter1]
            row2 = model[iter2]
            if row1[COL_URI] is None:
                return -1
            if row2[COL_URI] is None:
                return 1
            return cmp(row1[COL_LABEL], row2[COL_LABEL])
        model.set_sort_func(COL_LABEL, _sorter)

        # Mode combo
        combo = self.widget("migrate-mode")
        # label, is_tunnel
        model = Gtk.ListStore(str, bool)
        model.append([_("Direct"), False])
        model.append([_("Tunnelled"), True])
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 0)

        # Hook up signals to get connection listing
        engine.connect("conn-added", self._conn_added_cb)
        engine.connect("conn-removed", self._conn_removed_cb)
        self.widget("migrate-dest").emit("changed")

        self.widget("migrate-mode").set_tooltip_text(
            self.widget("migrate-mode-label").get_tooltip_text())
        self.widget("migrate-unsafe").set_tooltip_text(
            self.widget("migrate-unsafe-label").get_tooltip_text())
        self.widget("migrate-temporary").set_tooltip_text(
            self.widget("migrate-temporary-label").get_tooltip_text())

    def _reset_state(self):
        title_str = ("<span size='large' color='white'>%s '%s'</span>" %
                     (_("Migrate"), util.xml_escape(self.vm.get_name())))
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
        address_warning = ""
        tunnel_warning = ""
        tunnel_uri = ""

        if can_migrate and uri in self._conns:
            destconn = self._conns[uri]

            tunnel_uri = destconn.get_uri()
            if not destconn.is_remote():
                tunnel_warning = _("A remotely accessible libvirt URI "
                    "is required for tunneled migration, but the "
                    "selected connection is a local URI. Libvirt will "
                    "reject this unless you add a transport.")
                tunnel_warning = ("<span size='small'>%s</span>" %
                    tunnel_warning)

            address = destconn.libvirt_gethostname()

            if self._is_localhost(address):
                address_warning = _("The destination's hostname is "
                    "'localhost', which will be rejected by libvirt. "
                    "You must configure the destination to have a valid "
                    "publicly accessible hostname.")
                address_warning = ("<span size='small'>%s</span>" %
                    address_warning)

        self.widget("migrate-address").set_text(address)
        uiutil.set_grid_row_visible(
            self.widget("migrate-address-warning-box"), bool(address_warning))
        self.widget("migrate-address-warning-label").set_markup(address_warning)

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

    def _conn_added_cb(self, engine, conn):
        ignore = engine
        self._conns[conn.get_uri()] = conn

    def _conn_removed_cb(self, engine, uri):
        ignore = engine
        del(self._conns[uri])


    ###########################
    # destconn combo handling #
    ###########################

    def _is_localhost(self, addr):
        return not addr or addr.startswith("localhost")

    def _build_dest_row(self, destconn):
        driver = self.conn.get_driver()
        origuri = self.conn.get_uri()

        can_migrate = False
        desc = destconn.get_pretty_desc()
        reason = ""
        desturi = destconn.get_uri()

        if destconn.get_driver() != driver:
            reason = _("Hypervisors do not match")
        elif destconn.is_disconnected():
            reason = _("Disconnected")
        elif destconn.get_uri() == origuri:
            reason = _("Same connection")
        elif destconn.is_active():
            can_migrate = True

        if reason:
            desc = "%s (%s)" % (desc, reason)
        return [desc, desturi, can_migrate]

    def _populate_destconn(self):
        combo = self.widget("migrate-dest")
        model = combo.get_model()
        model.clear()

        rows = []
        for conn in self._conns.values():
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
        self.topwin.set_sensitive(True)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.TOP_LEFT_ARROW))

        if error:
            error = _("Unable to migrate guest: %s") % error
            self.err.show_err(error, details=details)
        else:
            self.conn.schedule_priority_tick(pollvm=True)
            destconn.schedule_priority_tick(pollvm=True)
            self.close()

    def _finish(self):
        try:
            row = uiutil.get_list_selected_row(self.widget("migrate-dest"))
            destlabel = row[COL_LABEL]
            destconn = self._conns.get(row[COL_URI])

            tunnel = self._is_tunnel_selected()
            unsafe = self.widget("migrate-unsafe").get_active()
            temporary = self.widget("migrate-temporary").get_active()

            if tunnel:
                uri = self.widget("migrate-tunnel-uri").get_text()
            else:
                uri = self._build_regular_migrate_uri()
        except Exception, e:
            details = "".join(traceback.format_exc())
            self.err.show_err((_("Uncaught error validating input: %s") %
                               str(e)),
                               details=details)
            return

        self.topwin.set_sensitive(False)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.WATCH))

        cancel_cb = None
        if self.vm.getjobinfo_supported:
            cancel_cb = (self._cancel_migration, self.vm)

        if uri:
            destlabel += " " + uri

        progWin = vmmAsyncJob(
            self._async_migrate,
            [self.vm, destconn, uri, tunnel, unsafe, temporary],
            self._finish_cb, [destconn],
            _("Migrating VM '%s'") % self.vm.get_name(),
            (_("Migrating VM '%s' to %s. This may take a while.") %
             (self.vm.get_name(), destlabel)),
            self.topwin, cancel_cb=cancel_cb)
        progWin.run()

    def _cancel_migration(self, asyncjob, vm):
        logging.debug("Cancelling migrate job")
        if not vm:
            return

        try:
            vm.abort_job()
        except Exception, e:
            logging.exception("Error cancelling migrate job")
            asyncjob.show_warning(_("Error cancelling migrate job: %s") % e)
            return

        asyncjob.job_canceled = True
        return

    def _async_migrate(self, asyncjob,
            origvm, origdconn, migrate_uri, tunnel, unsafe, temporary):
        meter = asyncjob.get_meter()

        srcconn = origvm.conn
        dstconn = origdconn

        vminst = srcconn.get_backend().lookupByName(origvm.get_name())
        vm = vmmDomain(srcconn, vminst, vminst.UUID())

        logging.debug("Migrating vm=%s from %s to %s", vm.get_name(),
                      srcconn.get_uri(), dstconn.get_uri())

        vm.migrate(dstconn, migrate_uri, tunnel, unsafe, temporary,
            meter=meter)

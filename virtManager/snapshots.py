#
# Copyright (C) 2013 Red Hat, Inc.
# Copyright (C) 2013 Cole Robinson <crobinso@redhat.com>
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

import datetime
import logging

# pylint: disable=E0611
from gi.repository import Gdk
from gi.repository import Gtk
# pylint: enable=E0611

import libvirt

import virtinst
from virtinst import util

from virtManager import uihelpers
from virtManager.baseclass import vmmGObjectUI
from virtManager.asyncjob import vmmAsyncJob


def _snapshot_state_icon_name(state):
    statemap = {
        "nostate": libvirt.VIR_DOMAIN_NOSTATE,
        "running": libvirt.VIR_DOMAIN_RUNNING,
        "blocked": libvirt.VIR_DOMAIN_BLOCKED,
        "paused": libvirt.VIR_DOMAIN_PAUSED,
        "shutdown": libvirt.VIR_DOMAIN_SHUTDOWN,
        "shutoff": libvirt.VIR_DOMAIN_SHUTOFF,
        "crashed": libvirt.VIR_DOMAIN_CRASHED,
        "pmsuspended": 7,
    }

    if state == "disk-snapshot" or state not in statemap:
        state = "shutoff"
    return uihelpers.vm_status_icons[statemap[state]]


class vmmSnapshotPage(vmmGObjectUI):
    def __init__(self, vm, builder, topwin):
        vmmGObjectUI.__init__(self, "snapshots.ui",
                              None, builder=builder, topwin=topwin)

        self.vm = vm

        self._initial_populate = False

        self._init_ui()

        self._snapshot_new = self.widget("snapshot-new")
        self._snapshot_new.set_transient_for(self.topwin)

        self.builder.connect_signals({
            "on_snapshot_add_clicked": self._on_add_clicked,
            "on_snapshot_delete_clicked": self._on_delete_clicked,
            "on_snapshot_start_clicked": self._on_start_clicked,
            "on_snapshot_apply_clicked": self._on_apply_clicked,
            "on_snapshot_list_changed": self._snapshot_selected,

            # 'Create' dialog
            "on_snapshot_new_delete_event": self._snapshot_new_close,
            "on_snapshot_new_ok_clicked": self._on_new_ok_clicked,
            "on_snapshot_new_cancel_clicked" : self._snapshot_new_close,
            "on_snapshot_new_name_changed" : self._snapshot_new_name_changed,
        })

        self.top_box = self.widget("snapshot-top-box")
        self.widget("snapshot-top-window").remove(self.top_box)
        self.widget("snapshot-list").get_selection().emit("changed")


    ##############
    # Init stuff #
    ##############

    def _cleanup(self):
        self.vm = None

        self._snapshot_new.destroy()
        self._snapshot_new = None

    def _init_ui(self):
        blue = Gdk.color_parse("#0072A8")
        self.widget("header").modify_bg(Gtk.StateType.NORMAL, blue)

        self.widget("snapshot-notebook").set_show_tabs(False)

        buf = Gtk.TextBuffer()
        buf.connect("changed", self._description_changed)
        self.widget("snapshot-description").set_buffer(buf)

        buf = Gtk.TextBuffer()
        self.widget("snapshot-new-description").set_buffer(buf)

        model = Gtk.ListStore(object, str, str)
        model.set_sort_column_id(1, Gtk.SortType.ASCENDING)

        col = Gtk.TreeViewColumn("")
        col.set_min_width(150)
        col.set_expand(True)
        col.set_spacing(6)
        txt = Gtk.CellRendererText()
        col.pack_start(txt, False)
        col.add_attribute(txt, 'text', 1)

        slist = self.widget("snapshot-list")
        slist.set_model(model)
        slist.set_tooltip_column(2)
        slist.append_column(col)


    ###################
    # Functional bits #
    ###################

    def _get_selected_snapshot(self):
        widget = self.widget("snapshot-list")
        selection = widget.get_selection()
        model, treepath = selection.get_selected()
        if treepath is None:
            return None
        return model[treepath][0]

    def _refresh_snapshots(self):
        self.vm.refresh_snapshots()
        self._populate_snapshot_list()

    def show_page(self):
        if not self._initial_populate:
            self._populate_snapshot_list()

    def _set_error_page(self, msg):
        self._set_snapshot_state(None)
        self.widget("snapshot-notebook").set_current_page(1)
        self.widget("snapshot-error-label").set_text(msg)

    def _populate_snapshot_list(self):
        model = self.widget("snapshot-list").get_model()
        model.clear()

        if not self.vm.snapshots_supported:
            self._set_error_page(_("Libvirt connection does not support "
                                  "snapshots."))
            return

        try:
            snapshots = self.vm.list_snapshots()
        except Exception, e:
            logging.exception(e)
            self._set_error_page(_("Error refreshing snapshot list: %s") %
                                str(e))
            return

        for snap in snapshots:
            desc = snap.get_xmlobj().description
            if not uihelpers.can_set_row_none:
                desc = desc or ""

            model.append([snap, snap.get_name(), desc])

        if len(model):
            self.widget("snapshot-list").get_selection().select_iter(
                model.get_iter_from_string("0"))
        self._initial_populate = True

    def _set_snapshot_state(self, snap=None):
        self.widget("snapshot-notebook").set_current_page(0)

        xmlobj = snap and snap.get_xmlobj() or None
        name = snap and xmlobj.name or ""
        desc = snap and xmlobj.description or ""
        state = snap and xmlobj.state or "shutoff"
        timestamp = ""
        if snap:
            timestamp = str(datetime.datetime.fromtimestamp(
                xmlobj.creationTime))

        title = ""
        if name:
            title = "<b>Snapshot '%s':</b>" % util.xml_escape(name)

        self.widget("snapshot-title").set_markup(title)
        self.widget("snapshot-timestamp").set_text(timestamp)
        self.widget("snapshot-description").get_buffer().set_text(desc)

        self.widget("snapshot-status-text").set_text(state)
        self.widget("snapshot-status-icon").set_from_icon_name(
                            _snapshot_state_icon_name(state),
                            Gtk.IconSize.MENU)

        self.widget("snapshot-add").set_sensitive(True)
        self.widget("snapshot-delete").set_sensitive(bool(snap))
        self.widget("snapshot-start").set_sensitive(bool(snap))
        self.widget("snapshot-apply").set_sensitive(False)


    ##################
    # 'New' handling #
    ##################

    def _reset_new_state(self):
        self.widget("snapshot-new-name").set_text("")
        self.widget("snapshot-new-name").emit("changed")
        self.widget("snapshot-new-description").get_buffer().set_text("")

    def _snapshot_new_name_changed(self, src):
        self.widget("snapshot-new-ok").set_sensitive(bool(src.get_text()))

    def _new_finish_cb(self, error, details):
        self.topwin.set_sensitive(True)
        self.topwin.get_window().set_cursor(
                Gdk.Cursor.new(Gdk.CursorType.TOP_LEFT_ARROW))

        if error is not None:
            error = _("Error creating snapshot: %s") % error
            self.err.show_err(error, details=details)
            return
        self._refresh_snapshots()

    def _validate_new_snapshot(self):
        name = self.widget("snapshot-new-name").get_text()
        desc = self.widget("snapshot-new-description"
            ).get_buffer().get_property("text")

        try:
            newsnap = virtinst.DomainSnapshot(self.vm.conn.get_backend())
            newsnap.name = name
            newsnap.description = desc or None
            newsnap.validate()
            return newsnap.get_xml_config()
        except Exception, e:
            return self.err.val_err(_("Error validating snapshot: %s" % e))

    def _create_new_snapshot(self):
        xml = self._validate_new_snapshot()
        if xml is False:
            return

        self.topwin.set_sensitive(False)
        self.topwin.get_window().set_cursor(
                Gdk.Cursor.new(Gdk.CursorType.WATCH))

        self._snapshot_new_close()
        progWin = vmmAsyncJob(
                    lambda ignore, x: self.vm.create_snapshot(x), [xml],
                    self._new_finish_cb, [],
                    _("Creating snapshot"),
                    _("Creating virtual machine snapshot"),
                    self.topwin)
        progWin.run()


    #############
    # Listeners #
    #############

    def _snapshot_new_close(self, *args, **kwargs):
        ignore = args
        ignore = kwargs
        self._snapshot_new.hide()
        return 1

    def _description_changed(self, ignore):
        self.widget("snapshot-apply").set_sensitive(True)

    def _on_apply_clicked(self, ignore):
        snap = self._get_selected_snapshot()
        if not snap:
            return

        desc_widget = self.widget("snapshot-description")
        desc = desc_widget.get_buffer().get_property("text") or ""

        xmlobj = snap.get_xmlobj()
        origxml = xmlobj.get_xml_config()
        xmlobj.description = desc
        newxml = xmlobj.get_xml_config()

        uihelpers.log_redefine_xml_diff(origxml, newxml)
        if newxml == origxml:
            return
        self.vm.create_snapshot(newxml, redefine=True)
        snap.refresh_xml()
        self._refresh_snapshots()

    def _on_new_ok_clicked(self, ignore):
        return self._create_new_snapshot()

    def _on_add_clicked(self, ignore):
        if self._snapshot_new.is_visible():
            return
        self._reset_new_state()
        self._snapshot_new.show()

    def _on_start_clicked(self, ignore):
        snap = self._get_selected_snapshot()
        result = self.err.yes_no(_("Are you sure you want to revert to "
                                   "snapshot '%s'? All disk changes since "
                                   "the last snapshot will be discarded.") %
                                   snap.get_name())
        if not result:
            return

        logging.debug("Revertin to snapshot '%s'", snap.get_name())
        vmmAsyncJob.simple_async_noshow(self.vm.revert_to_snapshot,
                            [snap], self,
                            _("Error reverting to snapshot '%s'") %
                            snap.get_name(),
                            finish_cb=self._refresh_snapshots)

    def _on_delete_clicked(self, ignore):
        snap = self._get_selected_snapshot()
        if not snap:
            return

        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the snapshot '%s'?") %
                                   snap.get_name())
        if not result:
            return

        logging.debug("Deleting snapshot '%s'", snap.get_name())
        vmmAsyncJob.simple_async_noshow(snap.delete, [], self,
                        _("Error deleting snapshot '%s'") % snap.get_name(),
                        finish_cb=self._refresh_snapshots)


    def _snapshot_selected(self, selection):
        model, treepath = selection.get_selected()
        if treepath is None:
            self._set_error_page(_("No snapshot selected."))
            return

        snap = model[treepath][0]

        try:
            self._set_snapshot_state(snap)
        except Exception, e:
            logging.exception(e)
            self._set_error_page(_("Error selecting snapshot: %s") % str(e))

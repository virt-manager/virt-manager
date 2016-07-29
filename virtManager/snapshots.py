#
# Copyright (C) 2013-2014 Red Hat, Inc.
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
import glob
import logging
import os
import StringIO

from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gtk
from gi.repository import Pango

from virtinst import DomainSnapshot
from virtinst import util

from . import uiutil
from .baseclass import vmmGObjectUI
from .asyncjob import vmmAsyncJob


mimemap = {
    "image/x-portable-pixmap": "ppm",
    "image/png": "png",
}


def _mime_to_ext(val, reverse=False):
    for m, e in mimemap.items():
        if val == m and not reverse:
            return e
        if val == e and reverse:
            return m
    logging.debug("Don't know how to convert %s=%s to %s",
                  reverse and "extension" or "mime", val,
                  reverse and "mime" or "extension")


class vmmSnapshotPage(vmmGObjectUI):
    def __init__(self, vm, builder, topwin):
        vmmGObjectUI.__init__(self, "snapshots.ui",
                              None, builder=builder, topwin=topwin)

        self.vm = vm

        self._initial_populate = False
        self._unapplied_changes = False

        self._snapmenu = None
        self._init_ui()

        self._snapshot_new = self.widget("snapshot-new")
        self._snapshot_new.set_transient_for(self.topwin)
        self.bind_escape_key_close_helper(self._snapshot_new,
                                          self._snapshot_new_close)

        self.builder.connect_signals({
            "on_snapshot_add_clicked": self._on_add_clicked,
            "on_snapshot_delete_clicked": self._on_delete_clicked,
            "on_snapshot_start_clicked": self._on_start_clicked,
            "on_snapshot_apply_clicked": self._on_apply_clicked,
            "on_snapshot_list_changed": self._snapshot_selected,
            "on_snapshot_list_button_press_event": self._popup_snapshot_menu,
            "on_snapshot_refresh_clicked": self._refresh_snapshots,
            "on_snapshot_list_row_activated": self._on_start_clicked,

            # 'Create' dialog
            "on_snapshot_new_delete_event": self._snapshot_new_close,
            "on_snapshot_new_ok_clicked": self._on_new_ok_clicked,
            "on_snapshot_new_cancel_clicked" : self._snapshot_new_close,
            "on_snapshot_new_name_changed" : self._snapshot_new_name_changed,
            "on_snapshot_new_name_activate": self._on_new_ok_clicked,
        })

        self.top_box = self.widget("snapshot-top-box")
        self.widget("snapshot-top-window").remove(self.top_box)
        selection = self.widget("snapshot-list").get_selection()
        selection.emit("changed")
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        selection.set_select_function(self._confirm_changes, None)

    ##############
    # Init stuff #
    ##############

    def _cleanup(self):
        self.vm = None

        self._snapshot_new.destroy()
        self._snapshot_new = None

    def _init_ui(self):
        # pylint: disable=redefined-variable-type
        blue = Gdk.color_parse("#0072A8")
        self.widget("header").modify_bg(Gtk.StateType.NORMAL, blue)

        self.widget("snapshot-notebook").set_show_tabs(False)

        buf = Gtk.TextBuffer()
        buf.connect("changed", self._description_changed)
        self.widget("snapshot-description").set_buffer(buf)

        buf = Gtk.TextBuffer()
        self.widget("snapshot-new-description").set_buffer(buf)

        # [name, row label, tooltip, icon name, sortname, current]
        model = Gtk.ListStore(str, str, str, str, str, bool)
        model.set_sort_column_id(4, Gtk.SortType.ASCENDING)

        col = Gtk.TreeViewColumn("")
        col.set_min_width(150)
        col.set_spacing(6)

        img = Gtk.CellRendererPixbuf()
        img.set_property("stock-size", Gtk.IconSize.LARGE_TOOLBAR)
        col.pack_start(img, False)
        col.add_attribute(img, 'icon-name', 3)

        txt = Gtk.CellRendererText()
        txt.set_property("ellipsize", Pango.EllipsizeMode.END)
        col.pack_start(txt, False)
        col.add_attribute(txt, 'markup', 1)

        img = Gtk.CellRendererPixbuf()
        img.set_property("stock-size", Gtk.IconSize.MENU)
        img.set_property("icon-name", Gtk.STOCK_APPLY)
        img.set_property("xalign", 0.0)
        col.pack_start(img, False)
        col.add_attribute(img, "visible", 5)

        def _sep_cb(_model, _iter, ignore):
            return not bool(_model[_iter][0])

        slist = self.widget("snapshot-list")
        slist.set_model(model)
        slist.set_tooltip_column(2)
        slist.append_column(col)
        slist.set_row_separator_func(_sep_cb, None)

        # Snapshot popup menu
        menu = Gtk.Menu()

        item = Gtk.ImageMenuItem.new_with_label(_("_Start snapshot"))
        item.set_use_underline(True)
        img = Gtk.Image()
        img.set_from_stock(Gtk.STOCK_MEDIA_PLAY, Gtk.IconSize.MENU)
        item.set_image(img)
        item.show()
        item.connect("activate", self._on_start_clicked)
        menu.add(item)

        item = Gtk.ImageMenuItem.new_with_label(_("_Delete snapshot"))
        item.set_use_underline(True)
        img = Gtk.Image()
        img.set_from_stock(Gtk.STOCK_DELETE, Gtk.IconSize.MENU)
        item.set_image(img)
        item.show()
        item.connect("activate", self._on_delete_clicked)
        menu.add(item)

        self._snapmenu = menu


    ###################
    # Functional bits #
    ###################

    def _get_selected_snapshots(self):
        selection = self.widget("snapshot-list").get_selection()
        def add_snap(treemodel, path, it, snaps):
            ignore = path
            try:
                name = treemodel[it][0]
                for snap in self.vm.list_snapshots():
                    if name == snap.get_name():
                        snaps.append(snap)
            except:
                pass

        snaps = []
        selection.selected_foreach(add_snap, snaps)
        return snaps

    def _refresh_snapshots(self, select_name=None):
        self.vm.refresh_snapshots()
        self._populate_snapshot_list(select_name)

    def show_page(self):
        if not self._initial_populate:
            self._populate_snapshot_list()

    def _set_error_page(self, msg):
        self._set_snapshot_state(None)
        self.widget("snapshot-notebook").set_current_page(1)
        self.widget("snapshot-error-label").set_text(msg)

    def _populate_snapshot_list(self, select_name=None):
        cursnaps = []
        for i in self._get_selected_snapshots():
            cursnaps.append(i.get_name())

        model = self.widget("snapshot-list").get_model()
        model.clear()

        try:
            snapshots = self.vm.list_snapshots()
        except Exception, e:
            logging.exception(e)
            self._set_error_page(_("Error refreshing snapshot list: %s") %
                                str(e))
            return

        has_external = False
        has_internal = False
        for snap in snapshots:
            desc = snap.get_xmlobj().description
            name = snap.get_name()
            state = util.xml_escape(snap.run_status())
            if snap.is_external():
                has_external = True
                sortname = "3%s" % name
                external = " (%s)" % _("External")
            else:
                has_internal = True
                external = ""
                sortname = "1%s" % name

            label = "%s\n<span size='small'>%s: %s%s</span>" % (
                (name, _("VM State"), state, external))
            model.append([name, label, desc, snap.run_status_icon_name(),
                          sortname, snap.is_current()])

        if has_internal and has_external:
            model.append([None, None, None, None, "2", False])


        def check_selection(treemodel, path, it, snaps):
            if select_name:
                if treemodel[it][0] == select_name:
                    selection.select_path(path)
            elif treemodel[it][0] in snaps:
                selection.select_path(path)

        selection = self.widget("snapshot-list").get_selection()
        model = self.widget("snapshot-list").get_model()
        selection.unselect_all()
        model.foreach(check_selection, cursnaps)

        self._initial_populate = True

    def _make_screenshot_pixbuf(self, mime, sdata):
        loader = GdkPixbuf.PixbufLoader.new_with_mime_type(mime)
        loader.write(sdata)
        pixbuf = loader.get_pixbuf()
        loader.close()

        maxsize = 450
        def _scale(big, small, maxsize):
            if big <= maxsize:
                return big, small
            factor = float(maxsize) / float(big)
            return maxsize, int(factor * float(small))

        width = pixbuf.get_width()
        height = pixbuf.get_height()
        if width > height:
            width, height = _scale(width, height, maxsize)
        else:
            height, width = _scale(height, width, maxsize)

        return pixbuf.scale_simple(width, height,
                                   GdkPixbuf.InterpType.BILINEAR)

    def _read_screenshot_file(self, name):
        if not name:
            return

        cache_dir = self.vm.get_cache_dir()
        basename = os.path.join(cache_dir, "snap-screenshot-%s" % name)
        files = glob.glob(basename + ".*")
        if not files:
            return

        filename = files[0]
        mime = _mime_to_ext(os.path.splitext(filename)[1][1:], reverse=True)
        if not mime:
            return
        return self._make_screenshot_pixbuf(mime, file(filename, "rb").read())

    def _set_snapshot_state(self, snap=None):
        self.widget("snapshot-notebook").set_current_page(0)

        xmlobj = snap and snap.get_xmlobj() or None
        name = snap and xmlobj.name or ""
        desc = snap and xmlobj.description or ""
        state = snap and snap.run_status() or ""
        icon = snap and snap.run_status_icon_name() or None
        is_external = snap and snap.is_external() or False
        is_current = snap and snap.is_current() or False

        timestamp = ""
        if snap:
            timestamp = str(datetime.datetime.fromtimestamp(
                xmlobj.creationTime))

        title = ""
        if name:
            title = "<b>Snapshot '%s':</b>" % util.xml_escape(name)

        uiutil.set_grid_row_visible(
            self.widget("snapshot-is-current"), is_current)
        self.widget("snapshot-title").set_markup(title)
        self.widget("snapshot-timestamp").set_text(timestamp)
        self.widget("snapshot-description").get_buffer().set_text(desc)

        self.widget("snapshot-status-text").set_text(state)
        if icon:
            self.widget("snapshot-status-icon").set_from_icon_name(
                icon, Gtk.IconSize.BUTTON)

        uiutil.set_grid_row_visible(self.widget("snapshot-mode"),
                                       is_external)
        if is_external:
            is_mem = xmlobj.memory_type == "external"
            is_disk = [d.snapshot == "external" for d in xmlobj.disks]
            if is_mem and is_disk:
                mode = _("External disk and memory")
            elif is_mem:
                mode = _("External memory only")
            else:
                mode = _("External disk only")
            self.widget("snapshot-mode").set_text(mode)

        sn = self._read_screenshot_file(name)
        self.widget("snapshot-screenshot").set_visible(bool(sn))
        self.widget("snapshot-screenshot-label").set_visible(not bool(sn))
        if sn:
            self.widget("snapshot-screenshot").set_from_pixbuf(sn)

        self.widget("snapshot-add").set_sensitive(True)
        self.widget("snapshot-delete").set_sensitive(bool(snap))
        self.widget("snapshot-start").set_sensitive(bool(snap))
        self.widget("snapshot-apply").set_sensitive(False)
        self._unapplied_changes = False

    def _confirm_changes(self, sel, model, path, path_selected, user_data):
        ignore1 = sel
        ignore2 = path
        ignore3 = model
        ignore4 = user_data

        if not self._unapplied_changes or not path_selected:
            return True

        if self.err.chkbox_helper(
                self.config.get_confirm_unapplied,
                self.config.set_confirm_unapplied,
                text1=(_("There are unapplied changes. "
                         "Would you like to apply them now?")),
                chktext=_("Don't warn me again."),
                default=False):
            self._apply()

        return True

    ##################
    # 'New' handling #
    ##################

    def _take_screenshot(self):
        stream = None
        try:
            stream = self.vm.conn.get_backend().newStream(0)
            screen = 0
            flags = 0
            mime = self.vm.get_backend().screenshot(stream, screen, flags)

            ret = StringIO.StringIO()
            def _write_cb(_stream, data, userdata):
                ignore = stream
                ignore = userdata
                ret.write(data)

            stream.recvAll(_write_cb, None)
            return mime, ret.getvalue()
        finally:
            try:
                if stream:
                    stream.finish()
            except:
                pass

    def _get_screenshot(self):
        if not self.vm.is_active():
            logging.debug("Skipping screenshot since VM is not active")
            return
        if not self.vm.get_graphics_devices():
            logging.debug("Skipping screenshot since VM has no graphics")
            return

        try:
            # Perform two screenshots, because qemu + qxl has a bug where
            # screenshot generally only shows the data from the previous
            # screenshot request:
            # https://bugs.launchpad.net/qemu/+bug/1314293
            self._take_screenshot()
            mime, sdata = self._take_screenshot()
        except:
            logging.exception("Error taking screenshot")
            return

        ext = _mime_to_ext(mime)
        if not ext:
            return

        newpix = self._make_screenshot_pixbuf(mime, sdata)
        setattr(newpix, "vmm_mimetype", mime)
        setattr(newpix, "vmm_sndata", sdata)
        return newpix

    def _reset_new_state(self):
        collidelist = [s.get_xmlobj().name for s in self.vm.list_snapshots()]
        default_name = DomainSnapshot.find_free_name(
            self.vm.get_backend(), collidelist)

        self.widget("snapshot-new-name").set_text(default_name)
        self.widget("snapshot-new-name").emit("changed")
        self.widget("snapshot-new-description").get_buffer().set_text("")
        self.widget("snapshot-new-ok").grab_focus()
        self.widget("snapshot-new-status-text").set_text(self.vm.run_status())
        self.widget("snapshot-new-status-icon").set_from_icon_name(
            self.vm.run_status_icon_name(), Gtk.IconSize.BUTTON)

        sn = self._get_screenshot()
        uiutil.set_grid_row_visible(
            self.widget("snapshot-new-screenshot"), bool(sn))
        if sn:
            self.widget("snapshot-new-screenshot").set_from_pixbuf(sn)


    def _snapshot_new_name_changed(self, src):
        self.widget("snapshot-new-ok").set_sensitive(bool(src.get_text()))

    def _new_finish_cb(self, error, details, newname):
        self.topwin.set_sensitive(True)
        self.topwin.get_window().set_cursor(
                Gdk.Cursor.new(Gdk.CursorType.TOP_LEFT_ARROW))

        if error is not None:
            error = _("Error creating snapshot: %s") % error
            self.err.show_err(error, details=details)
            return
        self._refresh_snapshots(newname)

    def _validate_new_snapshot(self):
        name = self.widget("snapshot-new-name").get_text()
        desc = self.widget("snapshot-new-description"
            ).get_buffer().get_property("text")

        try:
            newsnap = DomainSnapshot(self.vm.conn.get_backend())
            newsnap.name = name
            newsnap.description = desc or None
            newsnap.validate()
            newsnap.get_xml_config()
            return newsnap
        except Exception, e:
            return self.err.val_err(_("Error validating snapshot: %s") % e)

    def _get_screenshot_data_for_save(self):
        snwidget = self.widget("snapshot-new-screenshot")
        if not snwidget.is_visible():
            return None, None

        sn = snwidget.get_pixbuf()
        if not sn:
            return None, None

        mime = getattr(sn, "vmm_mimetype", None)
        sndata = getattr(sn, "vmm_sndata", None)
        return mime, sndata

    def _do_create_snapshot(self, asyncjob, xml, name, mime, sndata):
        ignore = asyncjob

        self.vm.create_snapshot(xml)

        try:
            cachedir = self.vm.get_cache_dir()
            basesn = os.path.join(cachedir, "snap-screenshot-%s" % name)

            # Remove any pre-existing screenshots so we don't show stale data
            for ext in mimemap.values():
                p = basesn + "." + ext
                if os.path.exists(basesn + "." + ext):
                    os.unlink(p)

            if not mime or not sndata:
                return

            filename = basesn + "." + _mime_to_ext(mime)
            logging.debug("Writing screenshot to %s", filename)
            file(filename, "wb").write(sndata)
        except:
            logging.exception("Error saving screenshot")

    def _create_new_snapshot(self):
        snap = self._validate_new_snapshot()
        if not snap:
            return

        xml = snap.get_xml_config()
        name = snap.name
        mime, sndata = self._get_screenshot_data_for_save()

        self.topwin.set_sensitive(False)
        self.topwin.get_window().set_cursor(
                Gdk.Cursor.new(Gdk.CursorType.WATCH))

        self._snapshot_new_close()
        progWin = vmmAsyncJob(
                    self._do_create_snapshot, [xml, name, mime, sndata],
                    self._new_finish_cb, [name],
                    _("Creating snapshot"),
                    _("Creating virtual machine snapshot"),
                    self.topwin)
        progWin.run()

    def _apply(self):
        snaps = self._get_selected_snapshots()
        if not snaps or len(snaps) > 1:
            return False

        snap = snaps[0]
        desc_widget = self.widget("snapshot-description")
        desc = desc_widget.get_buffer().get_property("text") or ""

        xmlobj = snap.get_xmlobj()
        origxml = xmlobj.get_xml_config()
        xmlobj.description = desc
        newxml = xmlobj.get_xml_config()

        self.vm.log_redefine_xml_diff(snap, origxml, newxml)
        if newxml == origxml:
            return True

        self.vm.create_snapshot(newxml, redefine=True)
        snap.ensure_latest_xml()
        return True


    #############
    # Listeners #
    #############

    def _popup_snapshot_menu(self, src, event):
        ignore = src
        if event.button != 3:
            return
        self._snapmenu.popup(None, None, None, None, 0, event.time)

    def _snapshot_new_close(self, *args, **kwargs):
        ignore = args
        ignore = kwargs
        self._snapshot_new.hide()
        return 1

    def _description_changed(self, ignore):
        snaps = self._get_selected_snapshots()
        desc_widget = self.widget("snapshot-description")
        desc = desc_widget.get_buffer().get_property("text") or ""

        if len(snaps) == 1 and snaps[0].get_xmlobj().description != desc:
            self._unapplied_changes = True

        self.widget("snapshot-apply").set_sensitive(True)

    def _on_apply_clicked(self, ignore):
        self._apply()
        self._refresh_snapshots()

    def _on_new_ok_clicked(self, ignore):
        return self._create_new_snapshot()

    def _on_add_clicked(self, ignore):
        if self._snapshot_new.is_visible():
            return
        self._reset_new_state()
        self._snapshot_new.show()
        self.widget("snapshot-new-name").grab_focus()

    def _on_start_clicked(self, ignore, ignore2=None, ignore3=None):
        snaps = self._get_selected_snapshots()
        if not snaps or len(snaps) > 1:
            return

        snap = snaps[0]
        msg = _("Are you sure you want to run snapshot '%s'? "
            "All %s changes since the last snapshot was created will be "
            "discarded.")
        if self.vm.is_active():
            msg = msg % (snap.get_name(), _("disk"))
        else:
            msg = msg % (snap.get_name(), _("disk and configuration"))

        result = self.err.yes_no(msg)
        if not result:
            return

        logging.debug("Running snapshot '%s'", snap.get_name())
        vmmAsyncJob.simple_async(self.vm.revert_to_snapshot,
                            [snap], self,
                            _("Running snapshot"),
                            _("Running snapshot '%s'") % snap.get_name(),
                            _("Error running snapshot '%s'") %
                            snap.get_name(),
                            finish_cb=self._refresh_snapshots)

    def _on_delete_clicked(self, ignore):
        snaps = self._get_selected_snapshots()
        if not snaps:
            return

        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the selected snapshots?"))
        if not result:
            return

        for snap in snaps:
            logging.debug("Deleting snapshot '%s'", snap.get_name())
            vmmAsyncJob.simple_async(snap.delete, [], self,
                            _("Deleting snapshot"),
                            _("Deleting snapshot '%s'") % snap.get_name(),
                            _("Error deleting snapshot '%s'") % snap.get_name(),
                            finish_cb=self._refresh_snapshots)


    def _snapshot_selected(self, selection):
        ignore = selection
        snap = self._get_selected_snapshots()
        if not snap:
            self._set_error_page(_("No snapshot selected."))
            return
        if len(snap) > 1:
            self._set_error_page(_("Multiple snapshots selected."))
            self.widget("snapshot-start").set_sensitive(False)
            self.widget("snapshot-apply").set_sensitive(False)
            self.widget("snapshot-delete").set_sensitive(True)
            return

        try:
            self._set_snapshot_state(snap[0])
        except Exception, e:
            logging.exception(e)
            self._set_error_page(_("Error selecting snapshot: %s") % str(e))

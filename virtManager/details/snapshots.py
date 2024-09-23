# Copyright (C) 2013-2014 Red Hat, Inc.
# Copyright (C) 2013 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import datetime
import glob
import io
import os

from gi.repository import GdkPixbuf
from gi.repository import Gtk
from gi.repository import Pango

from virtinst import DomainSnapshot
from virtinst import generatename
from virtinst import log
from virtinst import xmlutil

from ..lib import uiutil
from ..asyncjob import vmmAsyncJob
from ..baseclass import vmmGObjectUI


mimemap = {
    "image/x-portable-pixmap": "ppm",
    "image/png": "png",
}


def _make_screenshot_pixbuf(mime, sdata):
    loader = GdkPixbuf.PixbufLoader.new_with_mime_type(mime)
    loader.write(sdata)
    pixbuf = loader.get_pixbuf()
    loader.close()

    maxsize = 450
    def _scale(big, small, maxsize):
        if big <= maxsize:
            return big, small  # pragma: no cover
        factor = float(maxsize) / float(big)
        return maxsize, int(factor * float(small))

    width = pixbuf.get_width()
    height = pixbuf.get_height()
    if width > height:
        width, height = _scale(width, height, maxsize)
    else:
        height, width = _scale(height, width, maxsize)  # pragma: no cover

    return pixbuf.scale_simple(width, height,
                               GdkPixbuf.InterpType.BILINEAR)


def _mime_to_ext(val, reverse=False):
    for m, e in mimemap.items():
        if val == m and not reverse:
            return e
        if val == e and reverse:
            return m
    log.debug("Don't know how to convert %s=%s to %s",  # pragma: no cover
                  reverse and "extension" or "mime", val,
                  reverse and "mime" or "extension")


class vmmSnapshotNew(vmmGObjectUI):
    __gsignals__ = {
        "snapshot-created": (vmmGObjectUI.RUN_FIRST, None, [str]),
    }

    def __init__(self, vm):
        vmmGObjectUI.__init__(self, "snapshotsnew.ui", "snapshot-new")
        self.vm = vm

        self._init_ui()

        self.builder.connect_signals({
            "on_snapshot_new_delete_event": self.close,
            "on_snapshot_new_cancel_clicked": self.close,
            "on_snapshot_new_name_changed": self._name_changed_cb,
            "on_snapshot_new_name_activate": self._ok_clicked_cb,
            "on_snapshot_new_ok_clicked": self._ok_clicked_cb,
            "on_snapshot_new_mode_toggled": self._mode_toggled_cb,
            "on_snapshot_new_memory_toggled": self._memory_toggled_cb,
        })
        self.bind_escape_key_close()


    #######################
    # Standard UI methods #
    #######################

    def show(self, parent):
        log.debug("Showing new snapshot wizard")
        self._reset_state()
        self.topwin.resize(1, 1)
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        log.debug("Closing new snapshot wizard")
        self.topwin.hide()
        return 1

    def _cleanup(self):
        self.vm = None


    ###########
    # UI init #
    ###########

    def _init_snapshot_mode(self):
        mode_external = self.widget("snapshot-new-mode-external")

        capsinfo = self.vm.xmlobj.lookup_capsinfo()

        if not capsinfo.guest.supports_externalSnapshot():
            mode_external.set_sensitive(False)
            mode_external.set_tooltip_text(
                    _("external snapshots not supported with this libvirt connection"))

    def _init_memory_path(self):
        mempaths = self.widget("snapshot-new-memory-path")

        model = Gtk.ListStore(str)
        mempaths.set_model(model)
        uiutil.init_combo_text_column(mempaths, 0)

    def _init_ui(self):
        buf = Gtk.TextBuffer()
        self.widget("snapshot-new-description").set_buffer(buf)
        self._init_snapshot_mode()
        self._init_memory_path()

    def _reset_snapshot_mode(self):
        mode_external = self.widget("snapshot-new-mode-external")
        mode_internal = self.widget("snapshot-new-mode-internal")

        if mode_external.is_sensitive():
            mode_external.set_active(True)
        else:
            mode_internal.set_active(True)

    def _reset_snapshot_memory_path(self):
        mode_box = self.widget("snapshot-new-mode-external")
        self._set_memory_path_visibility(mode_box)

        self.widget("snapshot-new-memory-auto").set_active(True)

    def _reset_state(self):
        basename = "snapshot"
        def cb(n):
            return generatename.check_libvirt_collision(
                self.vm.get_backend().snapshotLookupByName, n)
        default_name = generatename.generate_name(
                basename, cb, sep="", start_num=1, force_num=True)

        self.widget("snapshot-new-name").set_text(default_name)
        self.widget("snapshot-new-name").emit("changed")
        self.widget("snapshot-new-description").get_buffer().set_text("")
        self.widget("snapshot-new-ok").grab_focus()
        self.widget("snapshot-new-status-text").set_text(self.vm.run_status())
        self.widget("snapshot-new-status-icon").set_from_icon_name(
            self.vm.run_status_icon_name(), Gtk.IconSize.BUTTON)

        self._reset_snapshot_mode()

        self._reset_snapshot_memory_path()

        self.widget("snapshot-new-name").grab_focus()

    ############
    # UI utils #
    ############

    def _set_memory_path_visibility(self, mode_box):
        uiutil.set_grid_row_visible(self.widget("snapshot-new-memory-label"),
                                    mode_box.get_active() and self.vm.is_active())

    def _populate_memory_path(self):
        mempaths = self.widget("snapshot-new-memory-path")

        if mempaths.is_sensitive():
            return

        model = mempaths.get_model()
        paths = []

        model.clear()

        name = self.widget("snapshot-new-name").get_text()
        memname = f"{self.vm.get_name()}-mem.{name}"

        for disk in self.vm.get_xmlobj().devices.disk:
            diskpath = disk.get_source_path()

            if not diskpath:
                continue

            newpath = os.path.join(os.path.dirname(diskpath), memname)

            if newpath not in paths:
                paths.append(newpath)

        for path in paths:
            model.append([path])

        mempaths.set_active(0)

    ###################
    # Create handling #
    ###################

    def _take_screenshot(self):
        stream = None
        try:
            stream = self.vm.conn.get_backend().newStream(0)
            screen = 0
            flags = 0
            mime = self.vm.get_backend().screenshot(stream, screen, flags)

            ret = io.BytesIO()
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
            except Exception:  # pragma: no cover
                pass

    def _get_screenshot(self):
        if not self.vm.is_active():
            log.debug("Skipping screenshot since VM is not active")
            return
        if not self.vm.xmlobj.devices.graphics:
            log.debug("Skipping screenshot since VM has no graphics")
            return

        try:
            # Perform two screenshots, because qemu + qxl has a bug where
            # screenshot generally only shows the data from the previous
            # screenshot request:
            # https://bugs.launchpad.net/qemu/+bug/1314293
            self._take_screenshot()
            mime, sdata = self._take_screenshot()
        except Exception:  # pragma: no cover
            log.exception("Error taking screenshot")
            return

        ext = _mime_to_ext(mime)
        if not ext:
            return  # pragma: no cover

        return mime, sdata

    def _get_mode(self):
        mode_external = self.widget("snapshot-new-mode-external")
        if mode_external.get_active():
            return "external"

        return "internal"

    def _new_finish_cb(self, error, details, newname):
        self.reset_finish_cursor()

        if error is not None:
            error = _("Error creating snapshot: %s") % error
            self.err.show_err(error, details=details)
            return

        self.emit("snapshot-created", newname)
        self.close()

    def _validate_new_snapshot(self):
        name = self.widget("snapshot-new-name").get_text()
        desc = self.widget("snapshot-new-description"
                           ).get_buffer().get_property("text")
        mode = self._get_mode()

        try:
            newsnap = DomainSnapshot(self.vm.conn.get_backend())
            newsnap.name = name
            newsnap.description = desc or None
            if mode == "external" and self.vm.is_active():
                mempath = uiutil.get_list_selection(self.widget("snapshot-new-memory-path"))
                newsnap.memory_type = mode
                newsnap.memory_file = mempath
            newsnap.get_xml()
            newsnap.validate_generic_name(_("Snapshot"), newsnap.name)
            return newsnap
        except Exception as e:
            return self.err.val_err(_("Error validating snapshot: %s") % e)

    def _do_create_snapshot(self, asyncjob, xml, name, mime, sndata, diskOnly):
        ignore = asyncjob

        self.vm.create_snapshot(xml, diskOnly=diskOnly)

        try:
            cachedir = self.vm.get_cache_dir()
            basesn = os.path.join(cachedir, "snap-screenshot-%s" % name)

            # Remove any pre-existing screenshots so we don't show stale data
            for ext in list(mimemap.values()):
                p = basesn + "." + ext
                if os.path.exists(basesn + "." + ext):
                    os.unlink(p)

            if not mime or not sndata:
                return

            filename = basesn + "." + _mime_to_ext(mime)
            log.debug("Writing screenshot to %s", filename)
            open(filename, "wb").write(sndata)
        except Exception:  # pragma: no cover
            log.exception("Error saving screenshot")

    def _create_new_snapshot(self):
        snap = self._validate_new_snapshot()
        if not snap:
            return

        xml = snap.get_xml()
        name = snap.name
        mime, sndata = (self._get_screenshot() or (None, None))
        diskOnly = not self.vm.is_active() and self._get_mode() == "external"

        self.set_finish_cursor()
        progWin = vmmAsyncJob(
                    self._do_create_snapshot, [xml, name, mime, sndata, diskOnly],
                    self._new_finish_cb, [name],
                    _("Creating snapshot"),
                    _("Creating virtual machine snapshot"),
                    self.topwin)
        progWin.run()


    ################
    # UI listeners #
    ################

    def _name_changed_cb(self, src):
        self.widget("snapshot-new-ok").set_sensitive(bool(src.get_text()))
        self._populate_memory_path()

    def _ok_clicked_cb(self, src):
        return self._create_new_snapshot()

    def _mode_toggled_cb(self, src):
        self._set_memory_path_visibility(src)

    def _memory_toggled_cb(self, src):
        mempaths = self.widget("snapshot-new-memory-path")

        if src.get_active():
            mempaths.set_sensitive(False)
        else:
            mempaths.set_sensitive(True)

        self._populate_memory_path()


class vmmSnapshotPage(vmmGObjectUI):
    def __init__(self, vm, builder, topwin):
        vmmGObjectUI.__init__(self, "snapshots.ui",
                              None, builder=builder, topwin=topwin)

        self.vm = vm

        self._initial_populate = False
        self._unapplied_changes = False
        self._snapshot_new = None

        self._snapmenu = None
        self._init_ui()

        self.builder.connect_signals({
            "on_snapshot_add_clicked": self._on_add_clicked,
            "on_snapshot_delete_clicked": self._on_delete_clicked,
            "on_snapshot_start_clicked": self._on_start_clicked,
            "on_snapshot_apply_clicked": self._on_apply_clicked,
            "on_snapshot_list_changed": self._snapshot_selected,
            "on_snapshot_list_button_press_event": self._popup_snapshot_menu,
            "on_snapshot_refresh_clicked": self._on_refresh_clicked,
            "on_snapshot_list_row_activated": self._on_start_clicked,
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
        self._snapmenu = None

        if self._snapshot_new:
            self._snapshot_new.cleanup()
            self._snapshot_new = None

    def _init_ui(self):
        # pylint: disable=redefined-variable-type
        self.widget("snapshot-notebook").set_show_tabs(False)

        buf = Gtk.TextBuffer()
        buf.connect("changed", self._description_changed)
        self.widget("snapshot-description").set_buffer(buf)

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
        img.set_property("icon-name", "emblem-default")
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

        item = Gtk.MenuItem.new_with_mnemonic(_("_Start snapshot"))
        item.show()
        item.connect("activate", self._on_start_clicked)
        menu.add(item)

        item = Gtk.MenuItem.new_with_mnemonic(_("_Delete snapshot"))
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
            except Exception:  # pragma: no cover
                pass

        snaps = []
        selection.selected_foreach(add_snap, snaps)
        return snaps

    def _refresh_snapshots(self, select_name=None):
        self.vm.refresh_snapshots()
        self._populate_snapshot_list(select_name)

    def vmwindow_refresh_vm_state(self):
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
        except Exception as e:  # pragma: no cover
            log.exception(e)
            self._set_error_page(_("Error refreshing snapshot list: %s") %
                                str(e))
            return

        has_external = False
        has_internal = False
        for snap in snapshots:
            desc = snap.get_xmlobj().description
            name = snap.get_name()
            state = snap.run_status()
            if snap.is_external():
                has_external = True
                sortname = "3%s" % name
                label = _("%(vm)s\n<span size='small'>VM State: "
                          "%(state)s (External)</span>")
            else:
                has_internal = True
                sortname = "1%s" % name
                label = _("%(vm)s\n<span size='small'>VM State: "
                          "%(state)s</span>")

            label = label % {
                "vm": xmlutil.xml_escape(name),
                "state": xmlutil.xml_escape(state)
            }
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
            return  # pragma: no cover
        return _make_screenshot_pixbuf(mime, open(filename, "rb").read())

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
            title = (_("<b>Snapshot '%(name)s':</b>") %
                     {"name": xmlutil.xml_escape(name)})

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

        if self.err.confirm_unapplied_changes():
            self._apply()

        return True

    def _apply(self):
        snaps = self._get_selected_snapshots()
        if not snaps or len(snaps) > 1:
            return False  # pragma: no cover

        snap = snaps[0]
        desc_widget = self.widget("snapshot-description")
        desc = desc_widget.get_buffer().get_property("text") or ""

        xmlobj = snap.get_xmlobj()
        origxml = xmlobj.get_xml()
        xmlobj.description = desc
        newxml = xmlobj.get_xml()

        self.vm.log_redefine_xml_diff(snap, origxml, newxml)
        if newxml == origxml:
            return True  # pragma: no cover

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
        self._snapmenu.popup_at_pointer(event)

    def close(self, ignore1=None, ignore2=None):
        if self._snapshot_new:
            self._snapshot_new.close()
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

    def _snapshot_created_cb(self, src, newname):
        self._refresh_snapshots(newname)

    def _on_add_clicked(self, ignore):
        if not self._snapshot_new:
            self._snapshot_new = vmmSnapshotNew(self.vm)
            self._snapshot_new.connect("snapshot-created",
                    self._snapshot_created_cb)
        if self.vm.has_managed_save():
            result = self.err.ok_cancel(
                _("Saved memory state will not be part of the snapshot"),
                _("The domain is currently saved. Due to technical "
                  "limitations that saved memory state will not become part "
                  "of the snapshot. Running it later will be the same as "
                  "having forced the system off mid-flight. It is "
                  "recommended to snapshot either the running or shut down "
                  "system instead."))
            if not result:
                return
        self._snapshot_new.show(self.topwin)

    def _on_refresh_clicked(self, ignore):
        self._refresh_snapshots()

    def _on_start_clicked(self, ignore, ignore2=None, ignore3=None):
        snaps = self._get_selected_snapshots()
        if not snaps or len(snaps) > 1:
            return  # pragma: no cover

        snap = snaps[0]

        if self.vm.is_active():
            msg = _("Are you sure you want to run the snapshot '%(name)s'? "
                    "All the disk changes since the last snapshot was created "
                    "will be discarded.")
        else:
            msg = _("Are you sure you want to run the snapshot '%(name)s'? "
                    "All the disk and configuration changes since the last "
                    "snapshot was created will be discarded.")
        msg = msg % {"name": snap.get_name()}

        result = self.err.yes_no(msg)
        if not result:
            return

        if self.vm.has_managed_save() and not snap.has_run_state():
            result = self.err.ok_cancel(
                _("Saved state will be removed to avoid filesystem corruption"),
                _("Snapshot '%s' contains only disk and no memory state. "
                  "Restoring the snapshot would leave the existing saved state "
                  "in place, effectively switching a disk underneath a running "
                  "system. Running the domain afterwards would likely result in "
                  "extensive filesystem corruption. Therefore the saved state "
                  "will be removed before restoring the snapshot."
                  ) % snap.get_name())
            if not result:
                return
            self.vm.remove_saved_image()

        log.debug("Running snapshot '%s'", snap.get_name())
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
            return  # pragma: no cover

        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the selected snapshots?"))
        if not result:
            return

        for snap in snaps:
            log.debug("Deleting snapshot '%s'", snap.get_name())
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
        except Exception as e:  # pragma: no cover
            log.exception(e)
            self._set_error_page(_("Error selecting snapshot: %s") % str(e))

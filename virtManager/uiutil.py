#
# Copyright (C) 2009, 2013, 2014 Red Hat, Inc.
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

# pylint: disable=E0611
from gi.repository import GObject
from gi.repository import Gtk
# pylint: enable=E0611

try:
    import gi
    gi.check_version("3.7.4")
    can_set_row_none = True
except (ValueError, AttributeError):
    can_set_row_none = False


def set_combo_text_column(combo, col):
    """
    Set the text column of the passed combo to 'col'. Does the
    right thing whether it's a plain combo or a comboboxentry. Saves
    some typing.
    """
    if combo.get_has_entry():
        combo.set_entry_text_column(col)
    else:
        text = Gtk.CellRendererText()
        combo.pack_start(text, True)
        combo.add_attribute(text, 'text', col)


def spin_get_helper(widget):
    adj = widget.get_adjustment()
    txt = widget.get_text()

    try:
        return int(txt)
    except:
        return adj.get_value()


def get_list_selection(widget):
    selection = widget.get_selection()
    active = selection.get_selected()

    treestore, treeiter = active
    if treeiter is not None:
        return treestore[treeiter]
    return None


def set_list_selection(widget, rownum):
    path = str(rownum)
    selection = widget.get_selection()

    selection.unselect_all()
    widget.set_cursor(path)
    selection.select_path(path)


def set_row_selection(listwidget, prevkey):
    model = listwidget.get_model()
    _iter = None
    if prevkey:
        for row in model:
            if row[0] == prevkey:
                _iter = row.iter
                break
    if not _iter:
        _iter = model.get_iter_first()

    if hasattr(listwidget, "get_selection"):
        selection = listwidget.get_selection()
        cb = selection.select_iter
    else:
        selection = listwidget
        cb = selection.set_active_iter
    if _iter:
        cb(_iter)
    selection.emit("changed")


def child_get_property(parent, child, propname):
    # Wrapper for child_get_property, which pygobject doesn't properly
    # introspect
    value = GObject.Value()
    value.init(GObject.TYPE_INT)
    parent.child_get_property(child, propname, value)
    return value.get_int()


def set_grid_row_visible(child, visible):
    # For the passed widget, find its parent GtkGrid, and hide/show all
    # elements that are in the same row as it. Simplifies having to name
    # every element in a row when we want to dynamically hide things
    # based on UI interraction

    parent = child.get_parent()
    if not type(parent) is Gtk.Grid:
        raise RuntimeError("Programming error, parent must be grid, "
                           "not %s" % type(parent))

    row = child_get_property(parent, child, "top-attach")
    for child in parent.get_children():
        if child_get_property(parent, child, "top-attach") == row:
            child.set_visible(visible)

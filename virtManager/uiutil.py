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

from gi.repository import GObject
from gi.repository import Gtk


#####################
# UI getter helpers #
#####################

def spin_get_helper(widget):
    """
    Safely get spin button contents, converting to int if possible
    """
    adj = widget.get_adjustment()
    txt = widget.get_text()

    try:
        return int(txt)
    except Exception:
        return adj.get_value()


def get_list_selected_row(widget, check_visible=False):
    """
    Helper to simplify getting the selected row in a list/tree/combo
    """
    if check_visible and not widget.get_visible():
        return None

    if hasattr(widget, "get_selection"):
        selection = widget.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter is None:
            return None

        row = model[treeiter]
    else:
        idx = widget.get_active()
        if idx == -1:
            return None

        row = widget.get_model()[idx]

    return row


def get_list_selection(widget, column=0,
                       check_visible=False, check_entry=True):
    """
    Helper to simplify getting the selected row and value in a list/tree/combo.
    If nothing is selected, and the widget is a combo box with a text entry,
    return the value of that.

    :param check_entry: If True, attempt to check the widget's text entry
        using the logic described above.
    """
    row = get_list_selected_row(widget, check_visible=check_visible)
    if row is not None:
        return row[column]

    if check_entry and hasattr(widget, "get_has_entry"):
        if widget.get_has_entry():
            return widget.get_child().get_text().strip()

    return None


#####################
# UI setter helpers #
#####################

def set_list_selection_by_number(widget, rownum):
    """
    Helper to set list selection from the passed row number
    """
    path = str(rownum)
    selection = widget.get_selection()

    selection.unselect_all()
    widget.set_cursor(path)
    selection.select_path(path)


def set_list_selection(widget, value, column=0):
    """
    Set a list or tree selection given the passed key, expected to
    be stored at the specified column.

    If the passed value is not found, and the widget is a combo box with
    a text entry, set the text entry to the passed value.
    """
    model = widget.get_model()
    _iter = None
    for row in model:
        if row[column] == value:
            _iter = row.iter
            break

    if not _iter:
        if hasattr(widget, "get_has_entry") and widget.get_has_entry():
            widget.get_child().set_text(value or "")
        else:
            _iter = model.get_iter_first()

    if hasattr(widget, "get_selection"):
        selection = widget.get_selection()
        cb = selection.select_iter
    else:
        selection = widget
        cb = selection.set_active_iter
    if _iter:
        cb(_iter)
    selection.emit("changed")


##################
# Misc functions #
##################

def child_get_property(parent, child, propname):
    """
    Wrapper for child_get_property, which pygobject doesn't properly
    introspect
    """
    value = GObject.Value()
    value.init(GObject.TYPE_INT)
    parent.child_get_property(child, propname, value)
    return value.get_int()


def set_grid_row_visible(child, visible):
    """
    For the passed widget, find its parent GtkGrid, and hide/show all
    elements that are in the same row as it. Simplifies having to name
    every element in a row when we want to dynamically hide things
    based on UI interraction
    """
    parent = child.get_parent()
    if not isinstance(parent, Gtk.Grid):
        raise RuntimeError("Programming error, parent must be grid, "
                           "not %s" % type(parent))

    row = child_get_property(parent, child, "top-attach")
    for c in parent.get_children():
        if child_get_property(parent, c, "top-attach") == row:
            c.set_visible(visible)


def init_combo_text_column(combo, col):
    """
    Set the text column of the passed combo to 'col'. Does the
    right thing whether it's a plain combo or a comboboxentry. Saves
    some typing.

    :returns: If we added a cell renderer, returns it. Otherwise return None
    """
    if combo.get_has_entry():
        combo.set_entry_text_column(col)
    else:
        text = Gtk.CellRendererText()
        combo.pack_start(text, True)
        combo.add_attribute(text, 'text', col)
        return text
    return None

from PyQt6.QtCore import Qt


def spin_get_helper(widget):
    try:
        return int(float(widget.text()))
    except Exception:
        return widget.value()


def get_list_selected_row(widget, check_visible=False):
    if check_visible and not widget.isVisible():
        return None

    if hasattr(widget, "selectedItems"):
        items = widget.selectedItems()
        if items:
            return items[0]
    elif hasattr(widget, "currentIndex"):
        idx = widget.currentIndex()
        if idx.isValid():
            return idx
    return None


def get_list_selection(widget, column=0, check_visible=False, check_entry=True):
    row = get_list_selected_row(widget, check_visible=check_visible)
    if row is not None:
        if hasattr(row, "data"):
            return row.data(column)
        if hasattr(widget, "model"):
            model = widget.model()
            if model and hasattr(model, "index"):
                return model.data(row)
        return str(row.text() if hasattr(row, "text") else row)
    return None


def set_list_selection_by_number(widget, rownum):
    if hasattr(widget, "selectRow"):
        widget.selectRow(rownum)
    elif hasattr(widget, "setCurrentIndex"):
        widget.setCurrentIndex(rownum)


def set_list_selection(widget, value, column=0):
    if hasattr(widget, "findItems"):
        items = widget.findItems(str(value), Qt.MatchFlags.MatchExactly)
        if items:
            widget.setCurrentItem(items[0])
            return True
    elif hasattr(widget, "model"):
        model = widget.model()
        if model:
            for row in range(model.rowCount()):
                idx = model.index(row, column)
                if model.data(idx) == value:
                    widget.setCurrentIndex(row)
                    return True
    return False


def pretty_mem(mem):
    if mem >= (1024 * 1024):
        return f"{mem / (1024 * 1024):.1f} GiB"
    elif mem >= 1024:
        return f"{mem / 1024:.1f} MiB"
    return f"{mem} KiB"


def pretty_bytes(size):
    if size >= (1024 * 1024 * 1024):
        return f"{size / (1024 * 1024 * 1024):.1f} GiB"
    elif size >= (1024 * 1024):
        return f"{size / (1024 * 1024):.1f} MiB"
    elif size >= 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size} B"

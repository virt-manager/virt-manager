# Copyright (C) 2013, 2014 Red Hat, Inc.
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

# pylint: disable=arguments-differ
# Newer pylint can detect, but warns that overridden arguments are wrong


def rect_print(name, rect):
    # For debugging
    print("%s: height=%d, width=%d, x=%d, y=%d" %
          (name, rect.height, rect.width, rect.x, rect.y))


def _line_helper(cairo_ct, x, y, w, h, points, for_fill=False):
    ignore = w
    bottom_baseline = y + h
    last_was_zero = False
    last_point = None

    for index in range(0, len(points)):
        x, y = points[index]

        # If stats value == 0, we don't want to draw a line
        is_zero = bool(y == bottom_baseline)

        # If the line is for filling, alter the coords so that fill covers
        # the same area as the parent sparkline: fill is one pixel short
        # to not overwrite the spark line
        if for_fill:
            if index == 0:
                x -= 1
            elif index == (len(points) - 1):
                x += 1
            elif last_was_zero and is_zero:
                y += 1

        if index == 0:
            cairo_ct.move_to(x, y)
        elif last_was_zero and is_zero and not for_fill:
            cairo_ct.move_to(x, y)
        else:
            cairo_ct.line_to(x, y)
            last_point = (x, y)

        last_was_zero = is_zero

    return last_point


def draw_line(cairo_ct, x, y, w, h, points):
    if not len(points):
        return

    last_point = _line_helper(cairo_ct, x, y, w, h, points)
    if not last_point:
        # Nothing to draw
        return

    # Paint the line
    cairo_ct.stroke()


def draw_fill(cairo_ct, x, y, w, h, points, taper=False):
    if not len(points):
        return

    _line_helper(cairo_ct, x, y, w, h, points, for_fill=True)

    baseline_y = h + y + 1
    if taper:
        start_x = w + x
    else:
        start_x = points[-1][0]

    # Box out the area to fill
    cairo_ct.line_to(start_x + 1, baseline_y)
    cairo_ct.line_to(x - 1, baseline_y)

    # Paint the fill
    cairo_ct.fill()


class CellRendererSparkline(Gtk.CellRenderer):
    __gproperties__ = {
        # 'name': (GObject.TYPE_*,
        #           nickname, long desc, (type related args), mode)
        # Type related args can be min, max for int (etc.), or default value
        # for strings and bool
        'data_array': (GObject.TYPE_PYOBJECT, "Data Array",
                        "Array of data points for the graph",
                        GObject.PARAM_READWRITE),
        'reversed': (GObject.TYPE_BOOLEAN, "Reverse data",
                     "Process data from back to front.",
                     0, GObject.PARAM_READWRITE),
    }

    def __init__(self):
        Gtk.CellRenderer.__init__(self)

        self.data_array = []
        self.num_sets = 0
        self.filled = True
        self.reversed = False
        self.rgb = None

    def do_render(self, cr, widget, background_area, cell_area,
                  flags):
        # cr                : Cairo context
        # widget            : GtkWidget instance
        # background_area   : GdkRectangle: entire cell area
        # cell_area         : GdkRectangle: area normally rendered by cell
        # flags             : flags that affect rendering
        # flags = Gtk.CELL_RENDERER_SELECTED, Gtk.CELL_RENDERER_PRELIT,
        #         Gtk.CELL_RENDERER_INSENSITIVE or Gtk.CELL_RENDERER_SORTED
        ignore = widget
        ignore = background_area
        ignore = flags

        # Indent of the gray border around the graph
        BORDER_PADDING = 2
        # Indent of graph from border
        GRAPH_INDENT = 2
        GRAPH_PAD = (BORDER_PADDING + GRAPH_INDENT)

        # We don't use yalign, since we expand to the entire height
        ignore = self.get_property("yalign")
        xalign = self.get_property("xalign")

        # Set up graphing bounds
        graph_x      = (cell_area.x + GRAPH_PAD)
        graph_y      = (cell_area.y + GRAPH_PAD)
        graph_width  = (cell_area.width - (GRAPH_PAD * 2))
        graph_height = (cell_area.height - (GRAPH_PAD * 2))

        pixels_per_point = (graph_width / max(1, len(self.data_array) - 1))

        # Graph width needs to be some multiple of the amount of data points
        # we have
        graph_width = (pixels_per_point * max(1, len(self.data_array) - 1))

        # Recalculate border width based on the amount we are graphing
        border_width = graph_width + (GRAPH_INDENT * 2)

        # Align the widget
        empty_space = cell_area.width - border_width - (BORDER_PADDING * 2)
        if empty_space:
            xalign_space = int(empty_space * xalign)
            cell_area.x += xalign_space
            graph_x += xalign_space

        cr.set_line_width(3)
        # 1 == LINE_CAP_ROUND
        cr.set_line_cap(1)

        # Draw gray graph border
        cr.set_source_rgb(0.8828125, 0.8671875, 0.8671875)
        cr.rectangle(cell_area.x + BORDER_PADDING,
                     cell_area.y + BORDER_PADDING,
                     border_width,
                     cell_area.height - (BORDER_PADDING * 2))
        cr.stroke()

        # Fill in white box inside graph outline
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(cell_area.x + BORDER_PADDING,
                     cell_area.y + BORDER_PADDING,
                     border_width,
                     cell_area.height - (BORDER_PADDING * 2))
        cr.fill()

        def get_y(index):
            baseline_y = graph_y + graph_height

            if self.reversed:
                n = (len(self.data_array) - index - 1)
            else:
                n = index

            val = self.data_array[n]
            y = baseline_y - (graph_height * val)

            y = max(graph_y, y)
            y = min(graph_y + graph_height, y)
            return y

        points = []
        for index in range(0, len(self.data_array)):
            x = int(((index * pixels_per_point) + graph_x))
            y = int(get_y(index))

            points.append((x, y))


        cell_area.x = graph_x
        cell_area.y = graph_y
        cell_area.width = graph_width
        cell_area.height = graph_height

        # Set color to dark blue for the actual sparkline
        cr.set_line_width(2)
        cr.set_source_rgb(0.421875, 0.640625, 0.73046875)
        draw_line(cr,
                  cell_area.x, cell_area.y,
                  cell_area.width, cell_area.height,
                  points)

        # Set color to light blue for the fill
        cr.set_source_rgba(0.71484375, 0.84765625, 0.89453125, .5)
        draw_fill(cr,
                  cell_area.x, cell_area.y,
                  cell_area.width, cell_area.height,
                  points)
        return

    def do_get_size(self, widget, cell_area=None):
        ignore = widget

        FIXED_WIDTH = len(self.data_array)
        FIXED_HEIGHT = 15
        xpad = self.get_property("xpad")
        ypad = self.get_property("ypad")

        if cell_area:
            # What to do here? haven't encountered this in practice
            xoffset = 0
            yoffset = 0
        else:
            xoffset = 0
            yoffset = 0

        width = ((xpad * 2) + FIXED_WIDTH)
        height = ((ypad * 2) + FIXED_HEIGHT)

        return (xoffset, yoffset, width, height)

    # Properties are passed to use with "-" in the name, but python
    # variables can't be named like that
    def _sanitize_param_spec_name(self, name):
        return name.replace("-", "_")
    def do_get_property(self, param_spec):
        name = self._sanitize_param_spec_name(param_spec.name)
        return getattr(self, name)
    def do_set_property(self, param_spec, value):
        name = self._sanitize_param_spec_name(param_spec.name)
        setattr(self, name, value)

    def set_property(self, *args, **kwargs):
        # Make pylint happy
        return Gtk.CellRenderer.set_property(self, *args, **kwargs)


class Sparkline(Gtk.DrawingArea):
    __gproperties__ = {
        # 'name': (GObject.TYPE_*,
        #           nickname, long desc, (type related args), mode)
        # Type related args can be min, max for int (etc.), or default value
        # for strings and bool
        'data_array': (GObject.TYPE_PYOBJECT, "Data Array",
                        "Array of data points for the graph",
                        GObject.PARAM_READWRITE),
        'filled': (GObject.TYPE_BOOLEAN, 'Filled', 'the foo of the object',
                   1,
                   GObject.PARAM_READWRITE),
        'num_sets': (GObject.TYPE_INT, "Number of sets",
                     "Number of data sets to graph",
                     1, 2, 1, GObject.PARAM_READWRITE),
        'reversed': (GObject.TYPE_BOOLEAN, "Reverse data",
                     "Process data from back to front.",
                     0, GObject.PARAM_READWRITE),
        'rgb': (GObject.TYPE_PYOBJECT, "rgb array", "List of rgb values",
                GObject.PARAM_READWRITE),
    }

    def __init__(self):
        Gtk.DrawingArea.__init__(self)

        self._data_array = []
        self.num_sets = 1
        self.filled = True
        self.reversed = False
        self.rgb = []

        ctxt = self.get_style_context()
        ctxt.add_class(Gtk.STYLE_CLASS_ENTRY)

    def set_data_array(self, val):
        self._data_array = val
        self.queue_draw()
    def get_data_array(self):
        return self._data_array
    data_array = property(get_data_array, set_data_array)


    def do_draw(self, cr):
        cr.save()

        window = self.get_window()
        w = window.get_width()
        h = window.get_height()

        points_per_set = (len(self.data_array) / self.num_sets)
        pixels_per_point = (float(w) /
                            (float((points_per_set - 1) or 1)))

        widget = self
        ctx = widget.get_style_context()

        # This draws the light gray backing rectangle
        Gtk.render_background(ctx, cr, 0, 0, w - 1, h - 1)

        # This draws the marker ticks
        max_ticks = 4
        for index in range(1, max_ticks):
            Gtk.render_line(ctx, cr, 1,
                            (h / max_ticks) * index,
                            w - 2,
                            (h / max_ticks) * index)

        # Foreground-color graphics context
        # This draws the black border
        Gtk.render_frame(ctx, cr, 0, 0, w - 1, h - 1)

        # Draw the actual sparkline
        def get_y(dataset, index):
            baseline_y = h

            n = dataset * points_per_set
            if self.reversed:
                n += (points_per_set - index - 1)
            else:
                n += index

            val = self.data_array[n]
            return baseline_y - ((h - 1) * val)

        cr.set_line_width(2)

        for dataset in range(0, self.num_sets):
            if len(self.rgb) == (self.num_sets * 3):
                cr.set_source_rgb(self.rgb[(dataset * 3)],
                                        self.rgb[(dataset * 3) + 1],
                                        self.rgb[(dataset * 1) + 2])
            points = []
            for index in range(0, points_per_set):
                x = index * pixels_per_point
                y = get_y(dataset, index)

                points.append((int(x), int(y)))


            if self.num_sets == 1:
                pass

            draw_line(cr, 0, 0, w, h, points)
            if self.filled:
                # Fixes a fully filled graph from having an oddly
                # tapered in end (bug 560913). Need to figure out
                # what's really going on.
                points = [(0, h)] + points
                draw_fill(cr, 0, 0, w, h, points, taper=True)

        cr.restore()

        return 0

    def do_size_request(self, requisition):
        width = len(self.data_array) / self.num_sets
        height = 20

        requisition.width = width
        requisition.height = height

    # Properties are passed to use with "-" in the name, but python
    # variables can't be named like that
    def _sanitize_param_spec_name(self, name):
        return name.replace("-", "_")
    def do_get_property(self, param_spec):
        name = self._sanitize_param_spec_name(param_spec.name)
        return getattr(self, name)
    def do_set_property(self, param_spec, value):
        name = self._sanitize_param_spec_name(param_spec.name)
        setattr(self, name, value)

    # These make pylint happy
    def set_property(self, *args, **kwargs):
        return Gtk.DrawingArea.set_property(self, *args, **kwargs)
    def show(self, *args, **kwargs):
        return Gtk.DrawingArea.show(self, *args, **kwargs)
    def destroy(self, *args, **kwargs):
        return Gtk.DrawingArea.destroy(self, *args, **kwargs)

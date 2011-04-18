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

import gobject
import gtk
import cairo

# For debugging
def rect_print(name, rect):
    print ("%s: height=%d, width=%d, x=%d, y=%d" %
           (name, rect.height, rect.width, rect.x, rect.y))

# For gproperties info, see:
# http://www.pygtk.org/docs/pygtk/class-gtkcontainer.html#function-gtk--container-class-install-child-property

def _line_helper(cairo_ct, cell_area, points, for_fill=False):

    bottom_baseline = cell_area.y + cell_area.height
    last_was_zero = False
    last_point = None

    for index in range(0, len(points)):
        x, y = points[index]

        # If stats value == 0, we don't want to draw a line
        is_zero = bool(y == bottom_baseline)

        # If the line is for filling, alter the coords so that fill covers
        # the same area as the parent sparkline: by default, fill is one pixel
        # short
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

def draw_line(cairo_ct, cell_area, points):
    if not len(points):
        return

    last_point = _line_helper(cairo_ct, cell_area, points)
    if not last_point:
        # Nothing to draw
        return

    # Paint the line
    cairo_ct.stroke()

def draw_fill(cairo_ct, cell_area, points, taper=False):
    if not len(points):
        return

    last_point = _line_helper(cairo_ct, cell_area, points, for_fill=True)
    if not last_point:
        # Nothing to draw
        #return
        pass

    baseline_y = cell_area.height + cell_area.y + 1
    if taper:
        x = cell_area.width + cell_area.x
    else:
        x = points[-1][0]

    # Box out the area to fill
    cairo_ct.line_to(x + 1, baseline_y)
    cairo_ct.line_to(cell_area.x - 1, baseline_y)

    # Paint the fill
    cairo_ct.fill()


class CellRendererSparkline(gtk.CellRenderer):
    __gproperties__ = {
        # 'name' : (gobject.TYPE_*,
        #           nickname, long desc, (type related args), mode)
        # Type related args can be min, max for int (etc.), or default value
        # for strings and bool
        'data_array' : (gobject.TYPE_PYOBJECT, "Data Array",
                        "Array of data points for the graph",
                        gobject.PARAM_READWRITE),
        'reversed': (gobject.TYPE_BOOLEAN, "Reverse data",
                     "Process data from back to front.",
                     0, gobject.PARAM_READWRITE),
    }

    def __init__(self):
        gtk.CellRenderer.__init__(self)

        self.data_array = []
        self.num_sets = 0
        self.filled = True
        self.reversed = False
        self.rgb = None

    def do_render(self, window, widget, background_area, cell_area,
                  expose_area, flags):
        # window            : gtk.gdk.Window (not plain window)
        # widget            : Parent widget (manager treeview)
        # background_area   : GdkRectangle: entire cell area
        # cell_area         : GdkRectangle: area normally rendered by cell
        # expose_area       : GdkRectangle: area that needs updating
        # flags             : flags that affect rendering
        # flags = gtk.CELL_RENDERER_SELECTED, gtk.CELL_RENDERER_PRELIT,
        #         gtk.CELL_RENDERER_INSENSITIVE or gtk.CELL_RENDERER_SORTED
        ignore = widget
        ignore = expose_area
        ignore = background_area
        ignore = flags

        # Indent of the gray border around the graph
        BORDER_PADDING = 2
        # Indent of graph from border
        GRAPH_INDENT = 2
        GRAPH_PAD = (BORDER_PADDING + GRAPH_INDENT)

        # We don't use yalign, since we expand to the entire height
        #yalign = self.get_property("yalign")
        xalign = self.get_property("xalign")

        # Set up graphing bounds
        graph_x      = (cell_area.x + GRAPH_PAD)
        graph_y      = (cell_area.y + GRAPH_PAD)
        graph_width  = (cell_area.width - (GRAPH_PAD * 2))
        graph_height = (cell_area.height - (GRAPH_PAD * 2))

        # XXX: This needs to be smarter, we need to either center the graph
        #      or have some way of making it variable sized
        pixels_per_point = (graph_width / ((len(self.data_array) or 1) - 1))

        # Graph width needs to be some multiple of the amount of data points
        # we have
        graph_width = (pixels_per_point * ((len(self.data_array) or 1) - 1))

        # Recalculate border width based on the amount we are graphing
        #border_width = graph_width + GRAPH_PAD
        border_width = graph_width + (GRAPH_INDENT * 2)

        # Align the widget
        empty_space = cell_area.width - border_width - (BORDER_PADDING * 2)
        if empty_space:
            xalign_space = int(empty_space * xalign)
            cell_area.x += xalign_space
            graph_x += xalign_space

        cairo_ct = window.cairo_create()
        cairo_ct.set_line_width(3)
        cairo_ct.set_line_cap(cairo.LINE_CAP_ROUND)

        # Draw gray graph border
        cairo_ct.set_source_rgb(0.8828125, 0.8671875, 0.8671875)
        cairo_ct.rectangle(cell_area.x + BORDER_PADDING,
                           cell_area.y + BORDER_PADDING,
                           border_width,
                           cell_area.height - (BORDER_PADDING * 2))
        cairo_ct.stroke()

        # Fill in white box inside graph outline
        cairo_ct.set_source_rgb(1, 1, 1)
        cairo_ct.rectangle(cell_area.x + BORDER_PADDING,
                           cell_area.y + BORDER_PADDING,
                           border_width,
                           cell_area.height - (BORDER_PADDING * 2))
        cairo_ct.fill()

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
        cairo_ct.set_line_width(2)
        cairo_ct.set_source_rgb(0.421875, 0.640625, 0.73046875)
        draw_line(cairo_ct, cell_area, points)

        # Set color to light blue for the fill
        cairo_ct.set_source_rgba(0.71484375, 0.84765625, 0.89453125, .5)
        draw_fill(cairo_ct, cell_area, points)

        # Stop clipping
        cairo_ct.clip()
        cairo_ct.save()
        cairo_ct.restore()
        del(cairo_ct)
        return

    def do_get_size(self, widget, cell_area=None):
        ignore = widget

        FIXED_WIDTH = len(self.data_array)
        FIXED_HEIGHT = 15
        xpad = self.get_property("xpad")
        ypad = self.get_property("ypad")

        if cell_area:
            # XXX: What to do here?
            xoffset = 0
            yoffset = 0
        else:
            xoffset = 0
            yoffset = 0

        width = ((xpad * 2) + FIXED_WIDTH)
        height = ((ypad * 2) + FIXED_HEIGHT)

        return (xoffset, yoffset, width, height)

    def _sanitize_param_spec_name(self, name):
        # Why this is made necessary, I have no idea
        return name.replace("-", "_")

    def do_get_property(self, param_spec):
        name = self._sanitize_param_spec_name(param_spec.name)
        return getattr(self, name)

    def do_set_property(self, param_spec, value):
        name = self._sanitize_param_spec_name(param_spec.name)
        setattr(self, name, value)

class Sparkline(gtk.DrawingArea):
    __gproperties__ = {
        # 'name' : (gobject.TYPE_*,
        #           nickname, long desc, (type related args), mode)
        # Type related args can be min, max for int (etc.), or default value
        # for strings and bool
        'data_array' : (gobject.TYPE_PYOBJECT, "Data Array",
                        "Array of data points for the graph",
                        gobject.PARAM_READWRITE),
        'filled': (gobject.TYPE_BOOLEAN, 'Filled', 'the foo of the object',
                   1,
                   gobject.PARAM_READWRITE),
        'num_sets': (gobject.TYPE_INT, "Number of sets",
                     "Number of data sets to graph",
                     1, 2, 1, gobject.PARAM_READWRITE),
        'reversed': (gobject.TYPE_BOOLEAN, "Reverse data",
                     "Process data from back to front.",
                     0, gobject.PARAM_READWRITE),
        'rgb': (gobject.TYPE_PYOBJECT, "rgb array", "List of rgb values",
                gobject.PARAM_READWRITE),
    }

    def __init__(self):
        gtk.DrawingArea.__init__(self)

        self._data_array = []
        self.num_sets = 1
        self.filled = True
        self.reversed = False
        self.rgb = []

        self.connect("expose-event", self.do_expose)

    def set_data_array(self, val):
        self._data_array = val
        self.queue_draw()
    def get_data_array(self):
        return self._data_array
    data_array = property(get_data_array, set_data_array)


    def do_expose(self, widget, event):
        # widget    : This widget
        # event     : GdkEvent
        # cell_area : GdkRectangle: area normally rendered by cell
        # window            : gtk.gdk.Window (not plain window)
        ignore = event

        # cell_area : GdkRectangle: area normally rendered by cell
        cell_area = widget.allocation

        # window            : gtk.gdk.Window (not plain window)
        window = widget.window

        points_per_set = (len(self.data_array) / self.num_sets)
        pixels_per_point = (float(cell_area.width) /
                            (float((points_per_set - 1) or 1)))

        # Mid-color graphics context (gtk.GC)
        # This draws the light gray backing rectangle
        mid_gc = widget.style.mid_gc[widget.state]
        window.draw_rectangle(mid_gc, True, 0, 0,
                              cell_area.width - 1,
                              cell_area.height - 1)

        # This draws the marker ticks
        max_ticks = 4
        dark_gc = widget.style.dark_gc[widget.state]
        for index in range(0, max_ticks):
            window.draw_line(dark_gc, 1,
                             (cell_area.height / max_ticks) * index,
                             cell_area.width - 2,
                             (cell_area.height / max_ticks) * index)

        # Foreground-color graphics context
        # This draws the black border
        fg_gc = widget.style.fg_gc[widget.state]
        window.draw_rectangle(fg_gc, False, 0, 0,
                              cell_area.width - 1,
                              cell_area.height - 1)

        # Draw the actual sparkline
        def get_y(dataset, index):
            baseline_y = cell_area.height

            n = dataset * points_per_set
            if self.reversed:
                n += (points_per_set - index - 1)
            else:
                n += index

            val = self.data_array[n]
            return baseline_y - ((cell_area.height - 1) * val)

        cairo_ct = window.cairo_create()
        cairo_ct.save()
        cairo_ct.rectangle(0, 0, cell_area.width, cell_area.height)
        cairo_ct.clip()
        cairo_ct.set_line_width(2)

        for dataset in range(0, self.num_sets):
            if len(self.rgb) == (self.num_sets * 3):
                cairo_ct.set_source_rgb(self.rgb[(dataset * 3)],
                                        self.rgb[(dataset * 3) + 1],
                                        self.rgb[(dataset * 1) + 2])
            points = []
            for index in range(0, points_per_set):
                x = index * pixels_per_point
                y = get_y(dataset, index)

                points.append((int(x), int(y)))


            if self.num_sets == 1:
                pass

            draw_line(cairo_ct, cell_area, points)
            if self.filled:
                # XXX: Fixes a fully filled graph from having an oddly
                #      tapered in end (bug 560913). Need to figure out
                #      what's really going on.
                points = [(0, cell_area.height)] + points
                draw_fill(cairo_ct, cell_area, points, taper=True)

        # Stop clipping
        cairo_ct.restore()
        del(cairo_ct)
        return 0

    def do_size_request(self, requisition):
        # Requisition: a GtkRequisition instance
        width = len(self.data_array) / self.num_sets
        height = 20

        requisition.width = width
        requisition.height = height

    def _sanitize_param_spec_name(self, name):
        # Why this is made necessary, I have no idea
        return name.replace("-", "_")

    def do_get_property(self, param_spec):
        name = self._sanitize_param_spec_name(param_spec.name)
        return getattr(self, name)

    def do_set_property(self, param_spec, value):
        name = self._sanitize_param_spec_name(param_spec.name)
        setattr(self, name, value)

gobject.type_register(Sparkline)
gobject.type_register(CellRendererSparkline)

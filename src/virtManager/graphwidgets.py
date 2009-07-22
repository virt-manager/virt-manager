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
import gtk.glade

# For gproperties info, see:
# http://www.pygtk.org/docs/pygtk/class-gtkcontainer.html#function-gtk--container-class-install-child-property

def _draw_sparkline(cairo_ct, cell_area, points, filled, points_per_set,
                    taper=False):
    for index in range(0, points_per_set):
        x, y = points[index]

        if index == 0:
            cairo_ct.move_to(x, y)
        else:
            cairo_ct.line_to(x, y)

    if points_per_set:
        if filled:
            baseline_y = cell_area.height + cell_area.y
            if taper:
                x = cell_area.width + cell_area.x
            else:
                x = points[-1][0]
            cairo_ct.line_to(x, baseline_y)
            cairo_ct.line_to(0, baseline_y)
            cairo_ct.fill()
        else:
            cairo_ct.stroke()


class CellRendererSparkline(gtk.CellRenderer):
    __gsignals__ = {
    }

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

    def do_render(self, window, widget, backround_area, cell_area, expose_area,
                  flags):
        # window            : gtk.gdk.Window (not plain window)
        # widget            : Parent widget (manager treeview)
        # background_area   : GdkRectangle: entire cell area
        # cell_area         : GdkRectangle: area normally rendered by cell
        # expose_area       : GdkRectangle: area that needs updating
        # flags             : flags that affect rendering
        # flags = gtk.CELL_RENDERER_SELECTED, gtk.CELL_RENDERER_PRELIT,
        #         gtk.CELL_RENDERER_INSENSITIVE or gtk.CELL_RENDERER_SORTED
        def get_y(index):
            baseline_y = cell_area.y + cell_area.height

            if self.reversed:
                n = (len(self.data_array) - index - 1)
            else:
                n = index

            val = self.data_array[n]
            return baseline_y - (cell_area.height * val)

        pixels_per_point = (cell_area.width /
                            ((len(self.data_array) - 1) or 1))

        points = []
        for index in range(0, len(self.data_array)):
            x = index * pixels_per_point
            y = get_y(index)

            points.append((int(x + cell_area.x), int(y)))

        # Cairo stuff
        cairo_ct = window.cairo_create()
        cairo_ct.save()
        cairo_ct.rectangle(cell_area.x, cell_area.y, cell_area.width,
                           cell_area.height)
        cairo_ct.clip()
        cairo_ct.set_line_width(.5)

        _draw_sparkline(cairo_ct, cell_area, points, self.filled, len(points))

        # Stop clipping
        cairo_ct.restore()
        del(cairo_ct)
        return

    def do_get_size(self, widget, cell_area=None):
        xoffset = 0
        yoffset = 0
        width = len(self.data_array)
        height = 20

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
    __gsignals__ = {}

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

        # Foreground-color graphics context
        # This draws the black border
        fg_gc = widget.style.fg_gc[widget.state]
        window.draw_rectangle(fg_gc, False, 0, 0,
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
        cairo_ct.set_line_width(.5)

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
                #print cell_area.width
                #print cell_area.x
                #print "\n%s\n" % points
            _draw_sparkline(cairo_ct, cell_area, points, self.filled,
                            points_per_set, True)

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

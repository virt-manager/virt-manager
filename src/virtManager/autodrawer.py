#
# Copyright (C) 2011 Red Hat, Inc.
# Copyright (C) 2011 Cole Robinson <crobinso@redhat.com>
#
# Python implementation of autodrawer, originally found in vinagre sources:
# http://git.gnome.org/browse/vinagre/tree/vinagre/view
# Copyright (c) 2005 VMware Inc.
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
from gi.repository import Gdk
from gi.repository import cairo

class OverBox(Gtk.Box):
    """
    Implementation of an overlapping box
    """
    def __init__(self):
        Gtk.Box.__init__(self)

        self.underWin = None
        self.underWidget = None
        self.overWin = None
        self.overWidget = None
        self.overWidth = -1
        self.overHeight = -1
        self.min = 0
        self._fraction = 0
        self.verticalOffset = 0

        self.set_has_window(True)

    ####################
    # Internal helpers #
    ####################

    def _get_actual_min(self):
        """
        Retrieve the actual 'min' value, i.e. a value that is guaranteed
        not to exceed the height of the 'over' child.
        """
        ret = min(self.min, self.overHeight)
        return ret

    def _get_under_window_geometry(self):
        geo = cairo.RectangleInt()
        actual_min = self._get_actual_min()

        geo.x = 0
        geo.y = actual_min
        geo.width = self.allocation.width
        geo.height = (self.allocation.height - actual_min)

        return geo

    def _get_over_window_geometry(self):
        geo = cairo.RectangleInt()
        boxwidth = self.allocation.width
        expand = True
        fill = True
        padding = 0
        actual_min = self._get_actual_min()

        if self.overWidget:
            # XXX
            expand = self.child_get_property(self.overWidget, "expand", "")
            fill = self.child_get_property(self.overWidget, "fill", "")
            padding = self.child_get_property(self.overWidget, "padding", "")
            padding = 0

        if not expand:
            width = min(self.overWidth, boxwidth - padding)
            x = padding
        elif not fill:
            width = min(self.overWidth, boxwidth)
            x = ((boxwidth - width) / 2)
        else:
            width = boxwidth
            x = 0

        y = (((self.overHeight - actual_min) * (self.fraction - 1)) +
             self.verticalOffset)
        height = self.overHeight

        geo.x = x
        geo.y = y
        geo.width = width
        geo.height = height
        return geo

    def _set_overwin_size(self, alloc):
        # Trying to set the overwindow size to 0,0 always draws a 1,1 pixel
        # on the screen. Have this wrapper hide the window if trying to
        # resize to 0,0

        self.overWin.move_resize(alloc.x, alloc.y,
                                 alloc.width, alloc.height)

        if alloc.height == 0 and alloc.width == 0:
            self.overWin.hide()
        else:
            self.overWin.show()

    def _set_background(self):
        ctx = self.get_style_context()
        ctx.set_background(self.window)
        ctx.set_background(self.underWin)
        ctx.set_background(self.overWin)

    def _size_request(self):
        under = self.underWidget.size_request()
        over = self.overWidget.size_request()

        self.overWidth = over.width
        self.overHeight = over.height

        # XXXX
        expand = self.child_get_property(self.overWidget, "expand", "")
        fill = self.child_get_property(self.overWidget, "fill", "")
        padding = self.child_get_property(self.overWidget, "padding", "")
        padding = 0

        if expand or fill:
            wpad = 0
        else:
            wpad = padding

        width = max(under.width, over.width + wpad)
        height = max(under.height + self._get_actual_min(), over.height)

        return width, height

    ########################
    # Custom functionality #
    ########################

    def do_set_over(self, widget):
        self.set_over(widget)

    def set_over(self, widget):
        if self.overWidget:
            self.remove(self.overWidget)

        if self.overWin:
            widget.set_parent_window(self.overWin)
        self.add(widget)
        self.overWidget = widget

    def set_under(self, widget):
        if self.underWidget:
            self.remove(self.underWidget)

        if self.underWin:
            widget.set_parent_window(self.underWin)
        self.add(widget)
        self.underWidget = widget
        self.underWidget.show_all()

    def set_min(self, newmin):
        self.min = newmin
        self.queue_resize()

    def set_fraction(self, newfraction):
        self._fraction = newfraction

        if self.get_realized():
            overgeo = self._get_over_window_geometry()
            self.overWin.move(overgeo.x, overgeo.y)
    def get_fraction(self):
        return self._fraction
    fraction = property(get_fraction, set_fraction)

    def set_vertical_offset(self, newoff):
        self.verticalOffset = newoff

        if self.get_realized():
            overgeo = self._get_over_window_geometry()
            self.overWin.move(overgeo.x, overgeo.y)

    ####################
    # Standard methods #
    ####################

    def do_map(self):
        self.get_window().show()
        Gtk.Box.do_map(self)

    def do_unmap(self):
        self.get_window().hide()
        Gtk.Box.do_unmap(self)

    def do_realize(self):
        self.set_realized(True)

        attr = Gdk.WindowAttr()
        attr.window_type = Gdk.WindowType.CHILD
        attr.wclass = Gdk.WindowWindowClass.INPUT_OUTPUT
        attr.event_mask = self.get_events() | Gdk.EventMask.EXPOSURE_MASK
        attr.visual = self.get_visual()
        attr.x = self.allocation.x
        attr.y = self.allocation.y
        attr.width = self.allocation.width
        attr.height = self.allocation.height

        mask = Gdk.WindowAttributesType.VISUAL | \
          Gdk.WindowAttributesType.X | \
          Gdk.WindowAttributesType.Y

        window = Gdk.Window.new(self.get_parent_window(), attr, mask)
        self.window = window
        self.set_window(window)

        geo = self._get_under_window_geometry()
        attr.x = geo.x
        attr.y = geo.y
        attr.width = geo.width
        attr.height = geo.height
        self.underWin = Gdk.Window.new(window, attr, mask)
        if self.underWidget:
            self.underWidget.set_parent_window(self.underWin)
        self.underWin.show()

        geo = self._get_over_window_geometry()
        attr.x = geo.x
        attr.y = geo.y
        attr.width = geo.width
        attr.height = geo.height
        self.overWin = Gdk.Window.new(window, attr, mask)
        if self.overWidget:
            self.overWidget.set_parent_window(self.overWin)
        self._set_overwin_size(geo)

        self._set_background()

    def do_unrealize(self):
        Gtk.Box.do_unrealize(self)

        self.overWin.destroy()
        self.overWin = None

        self.underWin.destroy()
        self.underWin = None
        self.set_realized(False)

    def do_size_request(self, req):
        width, height = self._size_request()

        req.width = width
        req.height = height

    def do_get_preferred_width(self):
        req = Gtk.Requisition()
        self.do_size_request(req)
        return (req.width, req.width)

    def do_get_preferred_heigh(self):
        req = Gtk.Requisition()
        self.do_size_request(req)
        return (req.height, req.height)

    def do_size_allocate(self, newalloc):
        self.allocation = newalloc

        over = self._get_over_window_geometry()
        under = self._get_under_window_geometry()

        if self.get_realized():
            self.get_window().move_resize(newalloc.x, newalloc.y,
                                    newalloc.width, newalloc.height)
            self.underWin.move_resize(under.x, under.y,
                                      under.width, under.height)
            self._set_overwin_size(over)

        under.x = 0
        under.y = 0
        self.underWidget.size_allocate(under)
        over.x = 0
        over.y = 0
        self.overWidget.size_allocate(over)


class Drawer(OverBox):
    """
    Implementation of a drawer, basically a floating toolbar
    """
    def __init__(self):
        OverBox.__init__(self)

        self.period = 10
        self.step = 0.2
        self.goal = 0

        self.timer_pending = False
        self.timer_id = None


    # XXX: C version has a finalize impl

    ####################
    # Internal helpers #
    ####################

    def _on_timer(self):
        fraction = self.fraction

        if self.goal == fraction:
            self.timer_pending = False
            return False

        if self.goal > fraction:
            self.fraction = min(fraction + self.step, self.goal)
        else:
            self.fraction = max(fraction - self.step, self.goal)

        return True

    ##############
    # Public API #
    ##############

    def set_speed(self, period, step):
        self.period = period

        if self.timer_pending:
            GObject.source_remove(self.timer_id)
            self.timer_id = GObject.timeout_add(self.period, self._on_timer)

        self.step = step

    def set_goal(self, goal):
        self.goal = goal

        if not self.timer_pending:
            self.timer_id = GObject.timeout_add(self.period, self._on_timer)
            self.timer_pending = True

    def get_close_time(self):
        return (self.period * (int(1 / self.step) + 1))


class AutoDrawer(Drawer):
    """
    Implemenation of an autodrawer, a drawer that hides and reappears on
    mouse over, slowly sliding into view
    """
    def __init__(self):
        Drawer.__init__(self)

        self.active = True
        self.pinned = False
        self.forceClosing = False
        self.inputUngrabbed = True
        self.opened = False

        self.fill = True
        self.offset = -1

        self.closeConnection = 0
        self.delayConnection = 0
        self.delayValue = 250
        self.overlapPixels = 0
        self.noOverlapPixels = 1
        self.overAllocID = None

        self.over = None
        self.eventBox = Gtk.EventBox()
        self.eventBox.show()
        OverBox.set_over(self, self.eventBox)

        self.eventBox.connect("enter-notify-event", self._on_over_enter_leave)
        self.eventBox.connect("leave-notify-event", self._on_over_enter_leave)
        self.eventBox.connect("grab-notify", self._on_grab_notify)

        self.connect("hierarchy-changed", self._on_hierarchy_changed)

        self._update(True)
        self._refresh_packing()

    # XXX: Has a finalize method

    ####################
    # Internal Helpers #
    ####################

    def set_over(self, newover):
        oldChild = self.eventBox.get_child()

        if oldChild:
            self.eventBox.remove(oldChild)
            oldChild.disconnect(self.overAllocID)
            oldChild.destroy()

        if newover:
            def size_allocate(src, newalloc):
                req = (newalloc.width, newalloc.height)
                if req == src.size_request():
                    # If over widget was just allocated it's requested size,
                    # something caused it to pop up, so make sure state
                    # is updated.
                    #
                    # Without this, switching to fullscreen keeps the toolbar
                    # stuck open until mouse over
                    self._update(False)

            self.eventBox.add(newover)
            self.overAllocID = newover.connect("size-allocate", size_allocate)

        self.over = newover

    def _update(self, do_immediate):
        toplevel = self.get_toplevel()
        if not toplevel or not toplevel.is_toplevel():
            # The autoDrawer cannot function properly without a toplevel.
            return

        self.opened = False

        # Is the drawer pinned open?
        if self.pinned:
            do_immediate = True
            self.opened = True

        # Is the mouse cursor inside the event box? */
        x, y = self.eventBox.get_pointer()
        alloc = self.eventBox.get_allocation()
        if x > -1 and y > -1 and x < alloc.width and y < alloc.height:
            self.opened = True

        # If there is a focused widget, is it inside the event box? */
        focus = toplevel.get_focus()
        if focus and focus.is_ancestor(self.eventBox):
            do_immediate = True
            self.opened = True

        # If input is grabbed, is it on behalf of a widget inside the
        # event box?
        if not self.inputUngrabbed:
            grabbed = None

            if toplevel.get_group():
                # XXX: Not in pyGtk.
                #grabbed = toplevel.get_group().get_current_grab()
                pass
            if not grabbed:
                grabbed = Gtk.grab_get_current()

            if grabbed and isinstance(grabbed, Gtk.Menu):

                while True:
                    menuAttach = grabbed.get_attach_widget()
                    if not menuAttach:
                        break

                    grabbed = menuAttach
                    if not isinstance(grabbed, Gtk.MenuItem):
                        break

                    menuItemParent = grabbed.get_parent()
                    if not isinstance(menuItemParent, Gtk.Menu):
                        break

                    grabbed = menuItemParent

            if grabbed and grabbed.is_ancestor(self.eventBox):
                do_immediate = True
                self.opened = True

        if self.delayConnection:
            GObject.source_remove(self.delayConnection)


        if self.forceClosing:
            self._enforce(True)
        elif do_immediate:
            self._enforce(False)
        else:
            self.delayConnection = GObject.timeout_add(self.delayValue,
                                                       self._on_enforce_delay)


    def _refresh_packing(self):
        expand = bool(self.fill or (self.offset < 0))

        if expand or self.fill:
            padding = 0
        else:
            padding = self.offset

        self.set_child_packing(self.eventBox, expand, self.fill, padding,
                               Gtk.PackType.START)

    def _enforce(self, do_animate):
        if not self.active:
            self.set_min(0)
            self.set_fraction(0)
            return

        self.set_min(self.noOverlapPixels)

        if self.opened and not self.forceClosing:
            fraction = 1
        else:
            alloc = self.over.get_allocation()
            fraction = (float(self.overlapPixels) / alloc.height)

        if not do_animate:
            self.set_fraction(fraction)
        self.set_goal(fraction)


    #############
    # Listeners #
    #############

    def _set_focus(self, ignore1, ignore2):
        self._update(False)

    def _on_over_enter_leave(self, ignore1, ignore2):
        self._update(False)

    def _on_grab_notify(self, eventbox, is_ungrabbed):
        ignore = eventbox
        self.inputUngrabbed = is_ungrabbed
        self._update(False)

    def _on_hierarchy_changed(self, oldTopLevel, ignore):
        newTopLevel = self.get_toplevel()

        if oldTopLevel and oldTopLevel.is_toplevel():
            oldTopLevel.disconnect_by_func(self._set_focus)

        if newTopLevel and newTopLevel.is_toplevel():
            newTopLevel.connect_after("set_focus", self._set_focus)

        self._update(True)

    def _on_enforce_delay(self):
        self.delayConnection = 0
        self._enforce(True)

        return False

    def _on_close_delay(self):
        self.closeConnection = 0
        self.forceClosing = False

        return False


    ##############
    # Public API #
    ##############

    def set_slide_delay(self, delay):
        self.delayValue = delay

    def set_overlap_pixels(self, overlap_pixels):
        self.overlapPixels = overlap_pixels
        self._update(True)

    def set_nooverlap_pixels(self, nooverlap_pixels):
        self.noOverlapPixels = nooverlap_pixels
        self._update(True)

    def set_active(self, active):
        self.active = active
        self._update(True)

    def set_pinned(self, pinned):
        self.pinned = pinned
        self._update(False)

    def set_fill(self, fill):
        self.fill = fill
        self._refresh_packing()

    def set_offset(self, offset):
        self.offset = offset
        self._refresh_packing()

    def drawer_close(self):
        toplevel = self.get_toplevel()
        if not toplevel or not toplevel.is_toplevel():
            # The autoDrawer cannot function properly without a toplevel.
            return

        focus = toplevel.get_focus()
        if focus and focus.is_ancestor(self.eventBox):
            toplevel.set_focus(None)

        self.forceClosing = True
        self.closeConnection = GObject.timeout_add(
                                self.get_close_time() + self.delayValue,
                                self._on_close_delay)

        self._update(True)

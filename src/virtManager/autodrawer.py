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

import gobject
import gtk

parentclass = gtk.VBox

def _set_has_window(widget, val):
    if hasattr(widget, "set_has_window"):
        # Only available on gtk 2.18 or later
        widget.set_has_window(val)
    elif val:
        widget.set_flags(widget.flags() & ~gtk.NO_WINDOW)
    else:
        widget.set_flags(widget.flags() | gtk.NO_WINDOW)

def _is_toplevel(widget):
    if hasattr(widget, "is_toplevel"):
        # Only available on gtk 2.18 or later
        return widget.is_toplevel()
    return bool(widget.flags() & gtk.TOPLEVEL)

class OverBox(parentclass):
    """
    Implementation of an overlapping box
    """
    def __init__(self):
        parentclass.__init__(self)

        self.underWin = None
        self.underWidget = None
        self.overWin = None
        self.overWidget = None
        self.overWidth = -1
        self.overHeight = -1
        self.min = 0
        self._fraction = 0
        self.verticalOffset = 0

        _set_has_window(self, True)

    ####################
    # Internal helpers #
    ####################

    def is_realized(self):
        return bool(self.flags() & gtk.REALIZED)
    def set_realized(self):
        flags = self.flags() | gtk.REALIZED
        self.set_flags(flags)

    def _get_actual_min(self):
        """
        Retrieve the actual 'min' value, i.e. a value that is guaranteed
        not to exceed the height of the 'over' child.
        """
        ret = min(self.min, self.overHeight)
        return ret

    def _get_under_window_geometry(self):
        geo = gtk.gdk.Rectangle()
        actual_min = self._get_actual_min()

        geo.x = 0
        geo.y = actual_min
        geo.width = self.allocation.width
        geo.height = (self.allocation.height - actual_min)

        return geo

    def _get_over_window_geometry(self):
        geo = gtk.gdk.Rectangle()
        boxwidth = self.allocation.width
        expand = True
        fill = True
        padding = 0
        actual_min = self._get_actual_min()

        if self.overWidget:
            expand = self.child_get(self.overWidget, "expand")[0]
            fill = self.child_get(self.overWidget, "fill")[0]
            padding = self.child_get(self.overWidget, "padding")[0]

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
        style = self.get_style()
        style.set_background(self.window, gtk.STATE_NORMAL)
        style.set_background(self.underWin, gtk.STATE_NORMAL)
        style.set_background(self.overWin, gtk.STATE_NORMAL)

    def _size_request(self):
        underw, underh = self.underWidget.size_request()
        overw, overh = self.overWidget.size_request()

        self.overWidth = overw
        self.overHeight = overh

        expand = self.child_get(self.overWidget, "expand")
        fill = self.child_get(self.overWidget, "fill")
        padding = self.child_get(self.overWidget, "padding")

        if expand or fill:
            wpad = 0
        else:
            wpad = padding

        width = max(underw, overw + wpad)
        height = max(underh + self._get_actual_min(), overh)

        return width, height

    ########################
    # Custom functionality #
    ########################

    def do_set_over(self, widget):
        self.set_over(widget)

    def set_over(self, widget):
        if self.overWidget:
            self.remove(self.overWidget)

        widget.set_parent_window(self.overWin)
        self.add(widget)
        self.overWidget = widget

    def set_under(self, widget):
        if self.underWidget:
            self.remove(self.underWidget)

        widget.set_parent_window(self.underWin)
        self.add(widget)
        self.underWidget = widget
        self.underWidget.show_all()

    def set_min(self, newmin):
        self.min = newmin
        self.queue_resize()

    def set_fraction(self, newfraction):
        self._fraction = newfraction

        if self.is_realized():
            overgeo = self._get_over_window_geometry()
            self.overWin.move(overgeo.x, overgeo.y)
    def get_fraction(self):
        return self._fraction
    fraction = property(get_fraction, set_fraction)

    def set_vertical_offset(self, newoff):
        self.verticalOffset = newoff

        if self.is_realized():
            overgeo = self._get_over_window_geometry()
            self.overWin.move(overgeo.x, overgeo.y)

    ####################
    # Standard methods #
    ####################

    def do_map(self):
        self.get_window().show()
        parentclass.do_map(self)

    def do_unmap(self):
        self.get_window().hide()
        parentclass.do_unmap(self)

    def do_realize(self):
        event_mask = self.get_events() | gtk.gdk.EXPOSURE_MASK
        colormap = self.get_colormap()
        visual = self.get_visual()

        self.set_realized()

        def make_window(parent, rect):
            return gtk.gdk.Window(parent,
                                  rect.width,
                                  rect.height,
                                  gtk.gdk.WINDOW_CHILD,
                                  event_mask,
                                  gtk.gdk.INPUT_OUTPUT,
                                  x=rect.x,
                                  y=rect.y,
                                  colormap=colormap,
                                  visual=visual)

        window = make_window(self.get_parent_window(), self.allocation)
        self.window = window
        self.window.set_user_data(self)
        self.style.attach(window)

        self.underWin = make_window(window,
                                    self._get_under_window_geometry())
        self.underWin.set_user_data(self)
        if self.underWidget:
            self.underWidget.set_parent_window(self.underWin)
        self.underWin.show()

        overalloc = self._get_over_window_geometry()
        self.overWin = make_window(window,
                                   self._get_over_window_geometry())
        self.overWin.set_user_data(self)
        if self.overWidget:
            self.overWidget.set_parent_window(self.overWin)
        self._set_overwin_size(overalloc)

        self._set_background()

    def do_unrealize(self):
        parentclass.do_unrealize(self)

        self.overWin.destroy()
        self.overWin = None

        self.underWin.destroy()
        self.underWin = None

    def do_size_request(self, req):
        width, height = self._size_request()

        req.width = width
        req.height = height

    def do_size_allocate(self, newalloc):
        self.allocation = newalloc

        over = self._get_over_window_geometry()
        under = self._get_under_window_geometry()

        if self.is_realized():
            self.window.move_resize(newalloc.x, newalloc.y,
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

    def do_style_set(self, style):
        if self.is_realized():
            self._set_background()

        parentclass.do_style_set(self, style)


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
            gobject.source_remove(self.timer_id)
            self.timer_id = gobject.timeout_add(self.period, self._on_timer)

        self.step = step

    def set_goal(self, goal):
        self.goal = goal

        if not self.timer_pending:
            self.timer_id = gobject.timeout_add(self.period, self._on_timer)
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
        self.eventBox = gtk.EventBox()
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
        if not toplevel or not _is_toplevel(toplevel):
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
                # XXX: Not in pygtk?
                #grabbed = toplevel.get_group().get_current_grab()
                pass
            if not grabbed:
                grabbed = gtk.grab_get_current()

            if grabbed and isinstance(grabbed, gtk.Menu):

                while True:
                    menuAttach = grabbed.get_attach_widget()
                    if not menuAttach:
                        break

                    grabbed = menuAttach
                    if not isinstance(grabbed, gtk.MenuItem):
                        break

                    menuItemParent = grabbed.get_parent()
                    if not isinstance(menuItemParent, gtk.Menu):
                        break

                    grabbed = menuItemParent

            if grabbed and grabbed.is_ancestor(self.eventBox):
                do_immediate = True
                self.opened = True

        if self.delayConnection:
            gobject.source_remove(self.delayConnection)


        if self.forceClosing:
            self._enforce(True)
        elif do_immediate:
            self._enforce(False)
        else:
            self.delayConnection = gobject.timeout_add(self.delayValue,
                                                       self._on_enforce_delay)


    def _refresh_packing(self):
        expand = bool(self.fill or (self.offset < 0))

        if expand or self.fill:
            padding = 0
        else:
            padding = self.offset

        self.set_child_packing(self.eventBox, expand, self.fill, padding,
                               gtk.PACK_START)

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

        if oldTopLevel and _is_toplevel(oldTopLevel):
            oldTopLevel.disconnect_by_func(self._set_focus)

        if newTopLevel and _is_toplevel(newTopLevel):
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
        if not toplevel or not _is_toplevel(toplevel):
            # The autoDrawer cannot function properly without a toplevel.
            return

        focus = toplevel.get_focus()
        if focus and focus.is_ancestor(self.eventBox):
            toplevel.set_focus(None)

        self.forceClosing = True
        self.closeConnection = gobject.timeout_add(
                                self.get_close_time() + self.delayValue,
                                self._on_close_delay)

        self._update(True)

gobject.type_register(OverBox)
gobject.type_register(Drawer)
gobject.type_register(AutoDrawer)

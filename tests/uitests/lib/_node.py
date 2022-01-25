# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import re

from gi.repository import Gdk

import dogtail.tree
import pyatspi

from virtinst import log
from . import utils


class _FuzzyPredicate(dogtail.predicate.Predicate):
    """
    Object dogtail/pyatspi want for node searching.
    """
    def __init__(self, name=None, roleName=None, labeller_text=None,
            focusable=False, onscreen=False):
        """
        :param name: Match node.name or node.labeller.text if
            labeller_text not specified
        :param roleName: Match node.roleName
        :param labeller_text: Match node.labeller.text
        :param focusable: Ensure node is focusable
        """
        self._name = name
        self._roleName = roleName
        self._labeller_text = labeller_text
        self._focusable = focusable
        self._onscreen = onscreen

        self._name_pattern = None
        self._role_pattern = None
        self._labeller_pattern = None
        if self._name:
            self._name_pattern = re.compile(self._name, re.DOTALL)
        if self._roleName:
            self._role_pattern = re.compile(self._roleName, re.DOTALL)
        if self._labeller_text:
            self._labeller_pattern = re.compile(self._labeller_text, re.DOTALL)

    def makeScriptMethodCall(self, isRecursive):
        ignore = isRecursive
        return
    def makeScriptVariableName(self):
        return
    def describeSearchResult(self, node=None):
        if not node:
            return ""
        return node.node_string()

    def satisfiedByNode(self, node):
        """
        The actual search routine
        """
        try:
            if self._roleName and not self._role_pattern.match(node.roleName):
                return

            labeller = ""
            if node.labeller:
                labeller = node.labeller.text

            if (self._name and
                    not self._name_pattern.match(node.name) and
                    not self._name_pattern.match(labeller)):
                return
            if (self._labeller_text and
                    not self._labeller_pattern.match(labeller)):
                return
            if (self._focusable and not
                    (node.focusable and
                     node.onscreen and
                     node.sensitive and
                     node.roleName not in ["page tab list", "radio button"])):
                return False
            return True
        except Exception as e:
            log.debug(
                    "got predicate exception name=%s role=%s labeller=%s: %s",
                    self._name, self._roleName, self._labeller_text, e)


def _debug_decorator(fn):
    def _cb(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception:
            print("node=%s\nstates=%s" % (self, self.print_states()))
            raise
    return _cb


class _VMMDogtailNode(dogtail.tree.Node):
    """
    Our extensions to the dogtail node wrapper class.
    """
    # The class hackery means pylint can't figure this class out
    # pylint: disable=no-member

    @property
    def active(self):
        """
        If the window is the raised and active window or not
        """
        return self.getState().contains(pyatspi.STATE_ACTIVE)

    @property
    def state_selected(self):
        return self.getState().contains(pyatspi.STATE_SELECTED)

    @property
    def onscreen(self):
        # We need to check that full widget is on screen because we use this
        # function to check whether we can click a widget. We may click
        # anywhere within the widget and clicks outside the screen bounds are
        # silently ignored.
        if self.roleName in ["frame"]:
            return True
        screen = Gdk.Screen.get_default()
        return (self.position[0] >= 0 and
                self.position[0] + self.size[0] < screen.get_width() and
                self.position[1] >= 0 and
                self.position[1] + self.size[1] < screen.get_height())

    @_debug_decorator
    def check_onscreen(self):
        """
        Check in a loop that the widget is onscreen
        """
        utils.check(lambda: self.onscreen)

    @_debug_decorator
    def check_not_onscreen(self):
        """
        Check in a loop that the widget is not onscreen
        """
        utils.check(lambda: not self.onscreen)

    @_debug_decorator
    def check_focused(self):
        """
        Check in a loop that the widget is focused
        """
        utils.check(lambda: self.focused)

    @_debug_decorator
    def check_sensitive(self):
        """
        Check whether interactive widgets are sensitive or not
        """
        valid_types = [
            "push button",
            "toggle button",
            "check button",
            "combo box",
            "menu item",
            "text",
            "menu",
        ]
        if self.roleName not in valid_types:
            return True
        utils.check(lambda: self.sensitive)

    def click_secondary_icon(self):
        """
        Helper for clicking the secondary icon of a text entry
        """
        self.check_onscreen()
        self.check_sensitive()
        button = 1
        clickX = self.position[0] + self.size[0] - 10
        clickY = self.position[1] + (self.size[1] / 2)
        dogtail.rawinput.click(clickX, clickY, button)

    def click_combo_entry(self):
        """
        Helper for clicking the arrow of a combo entry, to expose the menu.
        Clicks middle of Y axis, but 1/10th of the height from the right side.
        Using a small, hardcoded offset may not work on some themes (e.g. when
        running virt-manager on KDE)
        """
        self.check_onscreen()
        self.check_sensitive()
        button = 1
        clickX = self.position[0] + self.size[0] - self.size[1] / 4
        clickY = self.position[1] + self.size[1] / 2
        dogtail.rawinput.click(clickX, clickY, button)

    def click_expander(self):
        """
        Helper for clicking expander, hitting the text part to actually
        open it. Basically clicks top left corner with some indent
        """
        self.check_onscreen()
        self.check_sensitive()
        button = 1
        clickX = self.position[0] + 10
        clickY = self.position[1] + 5
        dogtail.rawinput.click(clickX, clickY, button)

    def title_coordinates(self):
        """
        Return clickable coordinates of a window's titlebar
        """
        x = self.position[0] + (self.size[0] / 2)
        y = self.position[1] + 10
        return x, y

    def click_title(self):
        """
        Helper to click a window title bar, hitting the horizontal
        center of the bar
        """
        if self.roleName not in ["frame", "alert"]:
            raise RuntimeError("Can't use click_title() on type=%s" %
                    self.roleName)
        button = 1
        clickX, clickY = self.title_coordinates()
        dogtail.rawinput.click(clickX, clickY, button)

    def click(self, *args, **kwargs):
        """
        click wrapper, give up to a second for widget to appear on
        screen, helps reduce some test flakiness
        """
        # pylint: disable=arguments-differ,signature-differs
        self.check_onscreen()
        self.check_sensitive()
        super().click(*args, **kwargs)

    def point(self, *args, **kwargs):
        # pylint: disable=signature-differs
        super().point(*args, **kwargs)

        if (self.roleName == "menu" and
            self.accessible_parent.roleName == "menu"):
            # Widget is a submenu, make sure the item is in selected
            # state before we return
            utils.check(lambda: self.state_selected)

    def set_text(self, text):
        self.check_onscreen()
        self.check_sensitive()
        assert hasattr(self, "text")
        self.text = text

    def get_text(self):
        self.check_onscreen()
        self.check_sensitive()
        assert hasattr(self, "text")
        return self.text

    def bring_on_screen(self, key_name="Down", max_tries=100):
        """
        Attempts to bring the item to screen by repeatedly clicking the given
        key. Raises exception if max_tries attempts are exceeded.
        """
        cur_try = 0
        while not self.onscreen:
            dogtail.rawinput.pressKey(key_name)
            cur_try += 1
            if cur_try > max_tries:
                raise RuntimeError("Could not bring widget on screen")
        return self

    def window_maximize(self):
        assert self.roleName in ["frame", "dialog"]
        self.grab_focus()
        s1 = self.size
        self.keyCombo("<alt>F10")
        utils.check(lambda: self.size != s1)
        self.grab_focus()

    def window_close(self):
        assert self.roleName in ["frame", "alert", "dialog", "file chooser"]
        self.grab_focus()
        self.keyCombo("<alt>F4")
        utils.check(lambda: not self.showing)

    def window_find_focusable_child(self):
        return self.find(None, focusable=True)

    def grab_focus(self):
        if self.roleName in ["frame", "alert", "dialog", "file chooser"]:
            child = self.window_find_focusable_child()
            child.grab_focus()
            utils.check(lambda: self.active)
            return

        self.check_onscreen()
        assert self.focusable
        self.grabFocus()
        self.check_focused()


    #########################
    # Widget search helpers #
    #########################

    def find(self, name, roleName=None, labeller_text=None,
            check_active=True, recursive=True, focusable=False):
        """
        Search root for any widget that contains the passed name/role regex
        strings.
        """
        pred = _FuzzyPredicate(name, roleName, labeller_text, focusable)

        try:
            ret = self.findChild(pred, recursive=recursive)
        except dogtail.tree.SearchError:
            raise dogtail.tree.SearchError("Didn't find widget with name='%s' "
                "roleName='%s' labeller_text='%s'" %
                (name, roleName, labeller_text)) from None

        # Wait for independent windows to become active in the window manager
        # before we return them. This ensures the window is actually onscreen
        # so it sidesteps a lot of race conditions
        if ret.roleName in ["frame", "dialog", "alert"] and check_active:
            utils.check(lambda: ret.active)
        return ret

    def find_fuzzy(self, name, roleName=None, labeller_text=None):
        """
        Search root for any widget that contains the passed name/role strings.
        """
        name_pattern = None
        role_pattern = None
        labeller_pattern = None
        if name:
            name_pattern = ".*%s.*" % name
        if roleName:
            role_pattern = ".*%s.*" % roleName
        if labeller_text:
            labeller_pattern = ".*%s.*" % labeller_text

        return self.find(name_pattern, role_pattern, labeller_pattern)


    ##########################
    # Higher level behaviors #
    ##########################

    def combo_select(self, combolabel, itemlabel):
        """
        Lookup the combo, click it, select the menu item
        """
        combo = self.find(combolabel, "combo box")
        combo.click_combo_entry()
        combo.find(itemlabel, "menu item").click()

    def combo_check_default(self, combolabel, itemlabel):
        """
        Lookup the combo and verify the menu item is selected
        """
        combo = self.find(combolabel, "combo box")
        combo.click_combo_entry()
        item = combo.find(itemlabel, "menu item")
        utils.check(lambda: item.selected)
        dogtail.rawinput.pressKey("Escape")


    #####################
    # Debugging helpers #
    #####################

    def node_string(self):
        msg = "name='%s' roleName='%s'" % (self.name, self.roleName)
        if self.labeller:
            msg += " labeller.text='%s'" % self.labeller.text
        return msg

    def fmt_nodes(self):
        strs = []
        def _walk(node):
            try:
                strs.append(node.node_string())
            except Exception as e:
                strs.append("got exception: %s" % e)

        self.findChildren(_walk, isLambda=True)
        return "\n".join(strs)

    def print_nodes(self):
        """
        Helper to print the entire node tree for the passed root. Useful
        if to figure out the roleName for the object you are looking for
        """
        print(self.fmt_nodes())

    def print_states(self):
        print([s.value_nick for s in self.getState().get_states()])


# This is the same hack dogtail uses to extend the Accessible class.
_bases = list(pyatspi.Accessibility.Accessible.__bases__)
_bases.insert(_bases.index(dogtail.tree.Node), _VMMDogtailNode)
_bases.remove(dogtail.tree.Node)
pyatspi.Accessibility.Accessible.__bases__ = tuple(_bases)

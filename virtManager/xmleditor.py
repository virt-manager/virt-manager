# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import gi

gi.require_version('GtkSource', '4')
from gi.repository import GtkSource

from .baseclass import vmmGObjectUI

_PAGE_DETAILS = 0
_PAGE_XML = 1


class vmmXMLEditor(vmmGObjectUI):
    __gsignals__ = {
        "changed": (vmmGObjectUI.RUN_FIRST, None, []),
        "xml-requested": (vmmGObjectUI.RUN_FIRST, None, []),
        "xml-reset": (vmmGObjectUI.RUN_FIRST, None, []),
    }

    def __init__(self, builder, topwin, parent_container, details_widget):
        super().__init__("xmleditor.ui", None,
                         builder=builder, topwin=topwin)

        parent_container.remove(details_widget)
        parent_container.add(self.widget("xml-notebook"))
        self.widget("xml-details-box").add(details_widget)

        self._curpage = _PAGE_DETAILS
        self._srcxml = ""
        self._srcview = None
        self._srcbuf = None
        self._init_ui()


    def _cleanup(self):
        pass


    ###########
    # UI init #
    ###########

    def _init_ui(self):
        self._srcview = GtkSource.View()
        self._srcbuff = self._srcview.get_buffer()

        lang = GtkSource.LanguageManager.get_default().get_language("xml")
        self._srcbuff.set_language(lang)

        self._srcview.set_monospace(True)
        self._srcview.set_auto_indent(True)
        self._srcview.get_accessible().set_name("XML editor")

        self._srcbuff.set_highlight_syntax(True)
        self._srcbuff.connect("changed", self._buffer_changed_cb)

        self.widget("xml-notebook").connect("switch-page",
                self._before_page_changed_cb)
        self.widget("xml-notebook").connect("notify::page",
                self._after_page_changed_cb)

        self._srcview.show_all()
        self.widget("xml-scroll").add(self._srcview)


    ####################
    # Internal helpers #
    ####################

    def _reselect_xml_page(self):
        # Setting _curpage first will shortcircuit our page changed callback
        self._curpage = _PAGE_XML
        self.widget("xml-notebook").set_current_page(_PAGE_XML)

    def _reset_xml(self):
        self.set_xml("")
        self.emit("xml-reset")

    def _reset_cursor(self):
        # Put cursor at the start of the second line. Starting on the
        # first means XML open/close tags are highlighted which is weird
        # starting visual
        startiter = self._srcbuff.get_start_iter()
        startiter.forward_line()
        self._srcbuff.place_cursor(startiter)


    ##############
    # Public API #
    ##############

    def reset_state(self):
        """
        Clear XML and select the details page. Used when callers do
        their own reset_state
        """
        self._reset_xml()
        return self.widget("xml-notebook").set_current_page(_PAGE_DETAILS)

    def get_xml(self):
        """
        Return the XML from the editor UI
        """
        return self._srcbuff.get_property("text")

    def set_xml(self, xml):
        """
        Set the editor UI XML to the passed string
        """
        try:
            self._srcbuff.disconnect_by_func(self._buffer_changed_cb)
            self._srcxml = xml or ""
            self._srcbuff.set_text(self._srcxml)
            self._reset_cursor()
        finally:
            self._srcbuff.connect("changed", self._buffer_changed_cb)

    def set_xml_from_libvirtobject(self, libvirtobject):
        """
        Set the editor UI XML to the inactive XML from the passed
        vmmLibvirtObject. If the XML UI isn't visible, we don't set
        anything, which lets callers use this on every page refresh
        """
        if not self.is_xml_selected():
            return
        xml = ""
        if libvirtobject:
            xml = libvirtobject.get_xml_to_define()
        self.set_xml(xml)

    def is_xml_selected(self):
        """
        Return True if the XML page is selected
        """
        return self._curpage == _PAGE_XML


    #############
    # Listeners #
    #############

    def _buffer_changed_cb(self, buf):
        self.emit("changed")

    def _before_page_changed_cb(self, notebook, widget, pagenum):
        if self._curpage == pagenum:
            return
        self._curpage = pagenum

        # If the XML page is clicked, emit xml-requested signal which
        # expects the user to call set_xml/set_libvirtobject. This saves
        # having to fetch inactive XML up front, and gives users like
        # a hook to actually serialize the final XML to return
        if pagenum == _PAGE_XML:
            self.emit("xml-requested")
            return

        # If the details page is selected from the XML page, and the user
        # edited the XML, we need to warn that leaving this screen will
        # invalidate the changes.
        if self._srcxml == self.get_xml():
            return

        ret = self.err.yes_no(
                _("There are unapplied changes."),
                _("Your XML changes will be lost if you leave this tab. "
                  "Really leave this tab?"))
        if ret:
            self._reset_xml()
            return

        # I can't find anyway to make the notebook stay on the current page
        # So set an idle callback to switch back to the XML page. It causes
        # a visual UI blip unfortunately
        self.idle_add(self._reselect_xml_page)

    def _after_page_changed_cb(self, notebook, gparam):
        self._curpage = notebook.get_current_page()

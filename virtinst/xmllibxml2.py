#
# XML API using libxml2
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import libxml2

from . import xmlutil
from .logger import log
from .xmlbase import XMLBase, XPath

# pylint: disable=protected-access


def node_is_text(n):
    return bool(n and n.type == "text")


class Libxml2API(XMLBase):
    def __init__(self, xml):
        XMLBase.__init__(self)

        # Use of gtksourceview in virt-manager changes this libxml
        # global setting which messes up whitespace after parsing.
        # We can probably get away with calling this less but it
        # would take some investigation
        libxml2.keepBlanksDefault(1)

        self._doc = libxml2.parseDoc(xml)
        self._ctx = self._doc.xpathNewContext()
        self._ctx.setContextNode(self._doc.children)
        for key, val in self.NAMESPACES.items():
            self._ctx.xpathRegisterNs(key, val)

    def __del__(self):
        if not hasattr(self, "_doc"):
            # In case we error when parsing the doc
            return
        self._doc.freeDoc()
        self._doc = None
        self._ctx.xpathFreeContext()
        self._ctx = None

    def _sanitize_xml(self, xml):
        if not xml.endswith("\n") and "\n" in xml:
            xml += "\n"
        return xml

    def copy_api(self):
        return Libxml2API(self._doc.children.serialize())

    def _find(self, fullxpath):
        xpath = XPath(fullxpath).xpath
        try:
            node = self._ctx.xpathEval(xpath)
        except Exception as e:
            log.debug("fullxpath=%s xpath=%s eval failed", fullxpath, xpath, exc_info=True)
            raise RuntimeError("%s %s" % (fullxpath, str(e))) from None
        return node and node[0] or None

    def count(self, xpath):
        return len(self._ctx.xpathEval(xpath))

    def _node_tostring(self, node):
        return node.serialize()

    def _node_from_xml(self, xml):
        return libxml2.parseDoc(xml).children

    def _node_get_text(self, node):
        return node.content

    def _node_set_text(self, node, setval):
        if setval is not None:
            setval = xmlutil.xml_escape(setval)
        node.setContent(setval)

    def _node_get_property(self, node, propname):
        prop = node.hasProp(propname)
        if prop:
            return prop.content

    def _node_set_property(self, node, propname, setval):
        if setval is None:
            prop = node.hasProp(propname)
            if prop:
                prop.unlinkNode()
                prop.freeNode()
        else:
            node.setProp(propname, setval)

    def _node_new(self, xpathseg, parentnode):
        newnode = libxml2.newNode(xpathseg.nodename)
        if not xpathseg.nsname:
            return newnode

        def _find_parent_ns():
            parent = parentnode
            while parent:
                for ns in xmlutil.listify(parent.nsDefs()):
                    if ns.name == xpathseg.nsname:
                        return ns
                parent = parent.get_parent()

        ns = _find_parent_ns()
        if not ns:
            ns = newnode.newNs(self.NAMESPACES[xpathseg.nsname], xpathseg.nsname)
        newnode.setNs(ns)
        return newnode

    def node_clear(self, xpath):
        node = self._find(xpath)
        if node:
            propnames = [p.name for p in (node.properties or [])]
            for p in propnames:
                node.unsetProp(p)
            node.setContent(None)

    def _node_has_content(self, node):
        return node.type == "element" and (node.children or node.properties)

    def _node_get_name(self, node):
        return node.name

    def _node_remove_child(self, parentnode, childnode):
        node = childnode

        # Look for preceding whitespace and remove it
        white = node.get_prev()
        if node_is_text(white):
            white.unlinkNode()
            white.freeNode()

        node.unlinkNode()
        node.freeNode()
        if all([node_is_text(n) for n in parentnode.children]):
            parentnode.setContent(None)

    def _node_add_child(self, parentxpath, parentnode, newnode):
        ignore = parentxpath
        if not node_is_text(parentnode.get_last()):
            prevsib = parentnode.get_prev()
            if node_is_text(prevsib):
                newlast = libxml2.newText(prevsib.content)
            else:
                newlast = libxml2.newText("\n")
            parentnode.addChild(newlast)

        endtext = parentnode.get_last().content
        parentnode.addChild(libxml2.newText("  "))
        parentnode.addChild(newnode)
        parentnode.addChild(libxml2.newText(endtext))

    def _node_replace_child(self, xpath, newnode):
        oldnode = self._find(xpath)
        oldnode.replaceNode(newnode)

#
# XML API wrappers
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import libxml2

from . import xmlutil
from .logger import log

# pylint: disable=protected-access


class _XPathSegment(object):
    """
    Class representing a single 'segment' of an xpath string. For example,
    the xpath:

        ./qemu:foo/bar[1]/baz[@somepro='someval']/@finalprop

    will be split into the following segments:

        #1: nodename=., fullsegment=.
        #2: nodename=foo, nsname=qemu, fullsegment=qemu:foo
        #3: nodename=bar, condition_num=1, fullsegment=bar[1]
        #4: nodename=baz, condition_prop=somepro, condition_val=someval,
                fullsegment=baz[@somepro='somval']
        #5: nodename=finalprop, is_prop=True, fullsegment=@finalprop
    """
    def __init__(self, fullsegment):
        self.fullsegment = fullsegment
        self.nodename = fullsegment

        self.condition_prop = None
        self.condition_val = None
        self.condition_num = None
        if "[" in self.nodename:
            self.nodename, cond = self.nodename.strip("]").split("[")
            if "=" in cond:
                (cprop, cval) = cond.split("=")
                self.condition_prop = cprop.strip("@")
                self.condition_val = cval.strip("'")
            elif cond.isdigit():
                self.condition_num = int(cond)

        self.is_prop = self.nodename.startswith("@")
        if self.is_prop:
            self.nodename = self.nodename[1:]

        self.nsname = None
        if ":" in self.nodename:
            self.nsname, self.nodename = self.nodename.split(":")


class _XPath(object):
    """
    Helper class for performing manipulations of XPath strings. Splits
    the xpath into segments.
    """
    def __init__(self, fullxpath):
        self.fullxpath = fullxpath
        self.segments = []
        for s in self.fullxpath.split("/"):
            if s == "..":
                # Resolve and flatten .. in xpaths
                self.segments = self.segments[:-1]
                continue
            self.segments.append(_XPathSegment(s))

        self.is_prop = self.segments[-1].is_prop
        self.propname = (self.is_prop and self.segments[-1].nodename or None)
        if self.is_prop:
            self.segments = self.segments[:-1]
        self.xpath = self.join(self.segments)

    @staticmethod
    def join(segments):
        return "/".join(s.fullsegment for s in segments)

    def parent_xpath(self):
        return self.join(self.segments[:-1])


class _XMLBase(object):
    NAMESPACES = {}
    @classmethod
    def register_namespace(cls, nsname, uri):
        cls.NAMESPACES[nsname] = uri

    def copy_api(self):
        raise NotImplementedError()
    def count(self, xpath):
        raise NotImplementedError()
    def _find(self, fullxpath):
        raise NotImplementedError()
    def _node_tostring(self, node):
        raise NotImplementedError()
    def _node_get_text(self, node):
        raise NotImplementedError()
    def _node_set_text(self, node, setval):
        raise NotImplementedError()
    def _node_get_property(self, node, propname):
        raise NotImplementedError()
    def _node_set_property(self, node, propname, setval):
        raise NotImplementedError()
    def _node_new(self, xpathseg, parentnode):
        raise NotImplementedError()
    def _node_add_child(self, parentxpath, parentnode, newnode):
        raise NotImplementedError()
    def _node_remove_child(self, parentnode, childnode):
        raise NotImplementedError()
    def _node_replace_child(self, xpath, newnode):
        raise NotImplementedError()
    def _node_from_xml(self, xml):
        raise NotImplementedError()
    def _node_has_content(self, node):
        raise NotImplementedError()
    def _node_get_name(self, node):
        raise NotImplementedError()
    def node_clear(self, xpath):
        raise NotImplementedError()
    def _sanitize_xml(self, xml):
        raise NotImplementedError()

    def get_xml(self, xpath):
        node = self._find(xpath)
        if node is None:
            return ""
        return self._sanitize_xml(self._node_tostring(node))

    def get_xpath_content(self, xpath, is_bool):
        node = self._find(xpath)
        if node is None:
            return None
        if is_bool:
            return True
        xpathobj = _XPath(xpath)
        if xpathobj.is_prop:
            return self._node_get_property(node, xpathobj.propname)
        return self._node_get_text(node)

    def set_xpath_content(self, xpath, setval):
        node = self._find(xpath)
        if setval is False:
            # Boolean False, means remove the node entirely
            self.node_force_remove(xpath)
        elif setval is None:
            if node is not None:
                self._node_set_content(xpath, node, None)
            self._node_remove_empty(xpath)
        else:
            if node is None:
                node = self._node_make_stub(xpath)

            if setval is True:
                # Boolean property, creating the node is enough
                return
            self._node_set_content(xpath, node, setval)

    def node_add_xml(self, xml, xpath):
        newnode = self._node_from_xml(xml)
        parentnode = self._node_make_stub(xpath)
        self._node_add_child(xpath, parentnode, newnode)

    def node_replace_xml(self, xpath, xml):
        """
        Replace the node at xpath with the passed in xml
        """
        newnode = self._node_from_xml(xml)
        self._node_replace_child(xpath, newnode)

    def node_force_remove(self, fullxpath):
        """
        Remove the element referenced at the passed xpath, regardless
        of whether it has children or not, and then clean up the XML
        chain
        """
        xpathobj = _XPath(fullxpath)
        parentnode = self._find(xpathobj.parent_xpath())
        childnode = self._find(fullxpath)
        if parentnode is None or childnode is None:
            return
        self._node_remove_child(parentnode, childnode)

    def validate_root_name(self, expected_root_name):
        rootname = self._node_get_name(self._find("."))
        if rootname == expected_root_name:
            return
        raise RuntimeError(
            _("XML did not have expected root element name "
              "'%(expectname)s', found '%(foundname)s'") %
            {"expectname": expected_root_name, "foundname": rootname})

    def _node_set_content(self, xpath, node, setval):
        xpathobj = _XPath(xpath)
        if setval is not None:
            setval = str(setval)
        if xpathobj.is_prop:
            self._node_set_property(node, xpathobj.propname, setval)
        else:
            self._node_set_text(node, setval)

    def _node_make_stub(self, fullxpath):
        """
        Build all nodes for the passed xpath. For example, if XML is <foo/>,
        and xpath=./bar/@baz, after this function the XML will be:

          <foo>
            <bar baz=''/>
          </foo>

        And the node pointing to @baz will be returned, for the caller to
        do with as they please.

        There's also special handling to ensure that setting
        xpath=./bar[@baz='foo']/frob will create

          <bar baz='foo'>
            <frob></frob>
          </bar>

        Even if <bar> didn't exist before. So we fill in the dependent property
        expression values
        """
        xpathobj = _XPath(fullxpath)
        parentxpath = "."
        parentnode = self._find(parentxpath)
        if not parentnode:
            raise xmlutil.DevError(
                    "Did not find XML root node for xpath=%s" % fullxpath)

        for xpathseg in xpathobj.segments[1:]:
            oldxpath = parentxpath
            parentxpath += "/%s" % xpathseg.fullsegment
            tmpnode = self._find(parentxpath)
            if tmpnode is not None:
                # xpath node already exists, nothing to create yet
                parentnode = tmpnode
                continue

            newnode = self._node_new(xpathseg, parentnode)
            self._node_add_child(oldxpath, parentnode, newnode)
            parentnode = newnode

            # For a conditional xpath like ./foo[@bar='baz'],
            # we also want to implicitly set <foo bar='baz'/>
            if xpathseg.condition_prop:
                self._node_set_property(parentnode, xpathseg.condition_prop,
                        xpathseg.condition_val)

        return parentnode

    def _node_remove_empty(self, fullxpath):
        """
        Walk backwards up the xpath chain, and remove each element
        if it doesn't have any children or attributes, so we don't
        leave stale elements in the XML
        """
        xpathobj = _XPath(fullxpath)
        segments = xpathobj.segments[:]
        parent = None
        while segments:
            xpath = _XPath.join(segments)
            segments.pop()
            child = parent
            parent = self._find(xpath)
            if parent is None:
                break
            if child is None:
                continue
            if self._node_has_content(child):
                break

            self._node_remove_child(parent, child)


def node_is_text(n):
    return bool(n and n.type == "text")


class _Libxml2API(_XMLBase):
    def __init__(self, xml):
        _XMLBase.__init__(self)

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
        return _Libxml2API(self._doc.children.serialize())

    def _find(self, fullxpath):
        xpath = _XPath(fullxpath).xpath
        try:
            node = self._ctx.xpathEval(xpath)
        except Exception as e:
            log.debug("fullxpath=%s xpath=%s eval failed",
                    fullxpath, xpath, exc_info=True)
            raise RuntimeError("%s %s" % (fullxpath, str(e))) from None
        return (node and node[0] or None)

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
            node.setProp(propname, xmlutil.xml_escape(setval))

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
            ns = newnode.newNs(
                    self.NAMESPACES[xpathseg.nsname], xpathseg.nsname)
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


XMLAPI = _Libxml2API

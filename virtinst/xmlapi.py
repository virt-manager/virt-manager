#
# XML API wrappers
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from lxml import etree

from . import xmlutil
from .logger import log

# pylint: disable=protected-access


class _XPathSegment:
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


class _XPath:
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
        self.propname = self.is_prop and self.segments[-1].nodename or None
        if self.is_prop:
            self.segments = self.segments[:-1]
        self.xpath = self.join(self.segments)

    @staticmethod
    def join(segments):
        return "/".join(s.fullsegment for s in segments)

    def parent_xpath(self):
        return self.join(self.segments[:-1])


class _XMLBase:
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
            _(
                "XML did not have expected root element name "
                "'%(expectname)s', found '%(foundname)s'"
            )
            % {"expectname": expected_root_name, "foundname": rootname}
        )

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
        if parentnode is None:
            raise xmlutil.DevError("Did not find XML root node for xpath=%s" % fullxpath)

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
                self._node_set_property(parentnode, xpathseg.condition_prop, xpathseg.condition_val)

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


class _LxmlAPI(_XMLBase):
    def __init__(self, xml):
        _XMLBase.__init__(self)
        self._parser = etree.XMLParser(remove_blank_text=True)
        self._doc = etree.fromstring(xml, parser=self._parser)

    def _sanitize_xml(self, xml):
        if not xml.endswith("\n") and "\n" in xml:
            xml += "\n"
        return xml

    def copy_api(self):
        return _LxmlAPI(etree.tostring(self._doc, encoding="unicode", pretty_print=True))

    def _find(self, fullxpath):
        xpath = _XPath(fullxpath).xpath
        try:
            node = self._doc.xpath(xpath, namespaces=self.NAMESPACES)
        except Exception as e:
            log.debug("fullxpath=%s xpath=%s eval failed", fullxpath, xpath, exc_info=True)
            raise RuntimeError("%s %s" % (fullxpath, str(e))) from None
        return node[0] if len(node) else None

    def count(self, xpath):
        return len(self._doc.xpath(xpath, namespaces=self.NAMESPACES))

    def _node_tostring(self, node):
        return etree.tostring(node, encoding="unicode", pretty_print=True)

    def _node_from_xml(self, xml):
        return etree.fromstring(xml, parser=self._parser)

    def _node_get_text(self, node):
        return node.text

    def _node_set_text(self, node, setval):
        node.text = setval

    def _node_get_property(self, node, propname):
        return node.get(propname)

    def _node_set_property(self, node, propname, setval):
        if setval is None:
            node.attrib.pop(propname, None)
        else:
            node.set(propname, setval)

    def _node_new(self, xpathseg, parentnode):
        name = xpathseg.nodename
        nsmap = None
        if xpathseg.nsname:
            name = etree.QName(self.NAMESPACES[xpathseg.nsname], name)
            nsmap = {xpathseg.nsname: self.NAMESPACES[xpathseg.nsname]}

        return etree.Element(name, nsmap=nsmap)

    def node_clear(self, xpath):
        node = self._find(xpath)
        if node:
            node.clear()

    def _node_has_content(self, node):
        return etree.iselement(node) and (node.keys() or node.getchildren() or node.text)

    def _node_get_name(self, node):
        return etree.QName(node).localname

    def _node_remove_child(self, parentnode, childnode):
        parentnode.remove(childnode)
        if len(parentnode.getchildren()) == 0:
            parentnode.text = None

    def _node_add_child(self, parentxpath, parentnode, newnode):
        parentnode.append(newnode)
        if parentnode.text and parentnode.text.isspace():
            parentnode.text = None

    def _node_replace_child(self, xpath, newnode):
        oldnode = self._find(xpath)
        oldnode.getparent().replace(oldnode, newnode)


XMLAPI = _LxmlAPI

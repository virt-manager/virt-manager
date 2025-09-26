#
# XML API using stock python ElementTree
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import io
import re
import xml.etree.ElementTree as ET

from . import xmlutil
from .xmlbase import XMLBase, XPath

# We need to extend ElementTree to parse + rebuild XML with no diff
# from default libvirt output. Otherwise `virt-xml --edit` diffs
# are needlessly noisy.
#
# The main problematic area is xmlns namespace handling.
#
# 1) libvirt xml will preserve arbitrary xml definitions.
#    ElementTree will _rename_ xmlns definition to ns0, ns1, etc
#    unless `register_namespace` was called ahead of time.
#
# 2) ElementTree formats every xmlns attribute into the top
#    element of the document, but libvirt may keep them inline,
#    like for <domain> <metadata>.


class _VirtinstElement(ET.Element):
    """
    Wrap Element to track specifically where an xmlns
    was defined. Default ElementTree throws this away
    """

    def __init__(self, *args, **kwargs):
        self.virtinst_namespaces = {}
        ET.Element.__init__(self, *args, **kwargs)

    def virtinst_add_namespace(self, prefix, uri):
        self.virtinst_namespaces[prefix] = uri


def _fromstring(xml):
    namespaces = {}

    class _VirtinstTreeBuilder(ET.TreeBuilder):
        """
        Custom tree builder to do two things:

        1) track element where xmlns attribute was defined
        2) build a mapping of xmlns prefix:uri for every xmlns we see
        """

        _ns_stack = []
        _last_element = None

        def end(self, tag):
            self._last_element = ET.TreeBuilder.end(self, tag)
            return self._last_element

        def start_ns(self, prefix, uri):
            self._ns_stack.append((prefix, uri))
            return (prefix, uri)

        def end_ns(self, _prefix):
            prefix, uri = self._ns_stack.pop()
            self._last_element.virtinst_add_namespace(prefix, uri)
            namespaces[prefix] = uri
            return prefix

    builder = _VirtinstTreeBuilder(element_factory=_VirtinstElement, insert_comments=True)
    parser = ET.XMLParser(target=builder)
    parser.feed(xml)
    node = parser.close()
    return node, namespaces


def _escape_cdata(xml):
    if xml:
        xml = xml.replace("&", "&amp;")
        xml = xml.replace("<", "&lt;")
        xml = xml.replace(">", "&gt;")
    return xml


def _convert_qname(tag, namespaces):
    """
    Convert ElementTree style namespace names to final
    XML format. For example, given this XML:

    <MYNS:FOO xmlns:MYNS="http://example.com"/>

    ElementTree node.tag will be "{http://example.com}FOO",
    and we turn it back into "MYNS:FOO"
    """
    if tag and tag.startswith("{"):
        uri, tag = tag[1:].rsplit("}", 1)
        for key, val in namespaces.items():
            if uri == val:
                tag = key + ":" + tag
                break
    return tag


def _serialize_node(write, elem, namespaces):
    # derived from ElementTree._serialize_xml
    tag = elem.tag
    text = elem.text
    if tag is ET.Comment:
        write("<!--%s-->" % text)
    else:
        use_ns = elem.virtinst_namespaces.copy()
        use_ns.update(namespaces)

        tag = _convert_qname(tag, use_ns)

        if tag is None:  # pragma: no cover
            # This is for CDATA, which libvirt will throw out anyways.
            pass
        else:
            write("<" + tag)
            for nsprefix, nsuri in elem.virtinst_namespaces.items():
                write(' xmlns:%s="%s"' % (nsprefix, nsuri))
            for k, v in list(elem.items()):
                k = _convert_qname(k, use_ns)
                v = xmlutil.xml_escape(v)
                write(' %s="%s"' % (k, v))

            if text or len(elem):
                write(">")
                if text:
                    write(_escape_cdata(text))
                for e in elem:
                    _serialize_node(write, e, namespaces)
                write("</" + tag + ">")
            else:
                write("/>")

    if elem.tail:
        write(_escape_cdata(elem.tail))


def _tostring(node, namespaces):
    stream = io.StringIO()

    _serialize_node(stream.write, node, namespaces)
    ret = stream.getvalue()
    return ret.rstrip()


class ETreeAPI(XMLBase):
    def __init__(self, parsexml):
        XMLBase.__init__(self)
        node, namespaces = _fromstring(parsexml)
        self._et = ET.ElementTree(node)
        self._namespaces = namespaces

    #######################
    # Private helper APIs #
    #######################

    def _sanitize_xml(self, xml):
        return xml

    def _node_tostring(self, node):
        return _tostring(node, self._namespaces)

    def _node_from_xml(self, xml):
        return _fromstring(xml)[0]

    def _node_get_name(self, node):
        name = _convert_qname(node.tag, self._namespaces)
        if ":" in name:
            name = name.split(":", 1)[1]
        return name

    def _node_get_text(self, node):
        return node.text

    def _node_set_text(self, node, setval):
        node.text = setval

    def _node_get_property(self, node, propname):
        return node.attrib.get(propname)

    def _node_set_property(self, node, propname, setval):
        if setval is None:
            node.attrib.pop(propname, None)
        else:
            node.attrib[propname] = setval

    def _find(self, fullxpath):
        xpath = XPath(fullxpath).xpath

        root = "/" + self._node_get_name(self._et.getroot())
        if xpath.startswith(root):
            # ElementTree explicitly warns that absolute xpaths don't
            # work as expected, and need a prepended .
            xpath = "." + xpath[len(root) :]

        node = self._et.find(xpath, self.NAMESPACES)
        if node is None:
            return None
        return node

    ###############
    # Simple APIs #
    ###############

    def copy_api(self):
        return ETreeAPI(self._node_tostring(self._et.getroot()))

    def count(self, xpath):
        return len(self._et.findall(xpath, self.NAMESPACES) or [])

    ####################
    # Private XML APIs #
    ####################

    def _node_add_child(self, parentxpath, parentnode, newnode):
        """
        Add 'newnode' as a child of 'parentnode', but try to preserve
        whitespace and nicely format the result.
        """
        xpathobj = XPath(parentxpath)

        if bool(len(parentnode)):
            lastelem = list(parentnode)[-1]
            newnode.tail = lastelem.tail
            lastelem.tail = parentnode.text
        elif xpathobj.parent_xpath():
            grandparent = self._find(xpathobj.parent_xpath())
            idx = list(grandparent).index(parentnode)
            if idx == (len(list(grandparent)) - 1):
                parentnode.text = (grandparent.text or "\n") + "  "
                newnode.tail = (parentnode.tail or "\n") + "  "
            else:
                parentnode.text = list(grandparent)[0].tail + "  "
                newnode.tail = list(grandparent)[0].tail
        else:
            parentnode.text = "\n  "
            newnode.tail = "\n"

        parentnode.append(newnode)

    def _node_has_content(self, node):
        return len(node) or node.attrib or re.search(r"\w+", (node.text or ""))

    def _node_remove_child(self, parentnode, childnode):
        idx = list(parentnode).index(childnode)

        if idx != 0 and idx == (len(list(parentnode)) - 1):
            prevsibling = list(parentnode)[idx - 1]
            prevsibling.tail = prevsibling.tail[:-2]
        elif idx == 0 and len(list(parentnode)) == 1:
            parentnode.text = None

        parentnode.remove(childnode)

    def _node_new(self, xpathseg, _parentnode):
        newname = xpathseg.nodename
        nsname = xpathseg.nsname
        nsuri = self.NAMESPACES.get(nsname, None)

        if nsname:
            newname = "{%s}%s" % (nsuri, newname)
        element = _VirtinstElement(newname)
        if nsname and nsname not in self._namespaces:
            self._namespaces[nsname] = nsuri
            element.virtinst_add_namespace(nsname, nsuri)
        return element

    def _node_replace_child(self, xpath, newnode):
        oldnode = self._find(xpath)
        parentnode = self._find(xpath + "...")
        for idx, elem in list(enumerate(parentnode)):
            if elem != oldnode:
                continue
            newnode.tail = oldnode.tail
            parentnode.remove(oldnode)
            parentnode.insert(idx, newnode)
            break

    ####################
    # XML editing APIs #
    ####################

    def node_clear(self, xpath):
        node = self._find(xpath)
        if node is not None:
            for c in list(node):
                node.remove(c)
            node.attrib.clear()
            node.text = None

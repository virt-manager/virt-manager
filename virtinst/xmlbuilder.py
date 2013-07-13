#
# Base class for all VM devices
#
# Copyright 2008  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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

import copy
import os

import libxml2

from virtinst import util


_trackprops = bool("VIRTINST_TEST_TRACKPROPS" in os.environ)
_allprops = []
_seenprops = []


class _DocCleanupWrapper(object):
    def __init__(self, doc):
        self._doc = doc
    def __del__(self):
        self._doc.freeDoc()


def _tuplify_lists(*args):
    """
    Similar to zip(), but use None if lists aren't long enough, and
    don't skip any None list entry
    """
    args = [util.listify(l) for l in args]
    maxlen = max([len(l) for l in args])

    ret = []
    for idx in range(maxlen):
        tup = tuple()
        for l in args:
            tup += (idx >= len(l) and (None,) or (l[idx],))
        ret.append(tup)
    return ret


def _sanitize_libxml_xml(xml):
    # Strip starting <?...> line
    if xml.startswith("<?"):
        ignore, xml = xml.split("\n", 1)
    if not xml.endswith("\n") and xml.count("\n"):
        xml += "\n"
    return xml


def _get_xpath_node(ctx, xpath, is_multi=False):
    node = ctx.xpathEval(xpath)
    if not is_multi:
        return (node and node[0] or None)
    return node


def _build_xpath_node(ctx, xpath, addnode=None):
    """
    Build all nodes required to set an xpath. If we have XML <foo/>, and want
    to set xpath /foo/bar/baz@booyeah, we create node 'bar' and 'baz'
    returning the last node created.
    """
    parentpath = ""
    parentnode = None

    def prevSibling(node):
        parent = node.get_parent()
        if not parent:
            return None

        prev = None
        for child in parent.children:
            if child == node:
                return prev
            prev = child

        return None

    def make_node(parentnode, newnode):
        # Add the needed parent node, try to preserve whitespace by
        # looking for a starting TEXT node, and copying it
        def node_is_text(n):
            return bool(n and n.type == "text" and not n.content.count("<"))

        sib = parentnode.get_last()
        if not node_is_text(sib):
            # This case is when we add a child element to a node for the
            # first time, like:
            #
            # <features/>
            # to
            # <features>
            #   <acpi/>
            # </features>
            prevsib = prevSibling(parentnode)
            if node_is_text(prevsib):
                sib = libxml2.newText(prevsib.content)
            else:
                sib = libxml2.newText("")
            parentnode.addChild(sib)

        # This is case is adding a child element to an already properly
        # spaced element. Example:
        # <features>
        #  <acpi/>
        # </features>
        # to
        # <features>
        #  <acpi/>
        #  <apic/>
        # </features>
        sib = parentnode.get_last()
        content = sib.content
        sib = sib.addNextSibling(libxml2.newText("  "))
        txt = libxml2.newText(content)

        sib.addNextSibling(newnode)
        newnode.addNextSibling(txt)
        return newnode

    nodelist = xpath.split("/")
    for idx in range(len(nodelist)):
        nodename = nodelist[idx]
        if not nodename:
            continue

        # If xpath is a node property, set it and move on
        if nodename.startswith("@"):
            nodename = nodename.strip("@")
            parentnode = parentnode.setProp(nodename, "")
            continue

        if not parentpath:
            parentpath = nodename
        else:
            parentpath += "/%s" % nodename

        # Node found, nothing to create for now
        node = _get_xpath_node(ctx, parentpath)
        if node:
            parentnode = node
            continue

        if not parentnode:
            raise RuntimeError("Could not find XML root node")

        # Remove conditional xpath elements for node creation
        if nodename.count("["):
            nodename = nodename[:nodename.index("[")]

        newnode = libxml2.newNode(nodename)
        parentnode = make_node(parentnode, newnode)

    if addnode:
        parentnode = make_node(parentnode, addnode)

    return parentnode


def _remove_xpath_node(ctx, xpath, dofree=True):
    """
    Remove an XML node tree if it has no content
    """
    curxpath = xpath

    while curxpath:
        is_orig = (curxpath == xpath)
        node = _get_xpath_node(ctx, curxpath)
        if curxpath.count("/"):
            curxpath, ignore = curxpath.rsplit("/", 1)
        else:
            curxpath = None

        if not node:
            continue

        if node.type not in ["attribute", "element"]:
            continue

        if node.type == "element" and (node.children or node.properties):
            # Only do a deep unlink if it was the original requested path
            if not is_orig:
                continue

        # Look for preceding whitespace and remove it
        white = node.get_prev()
        if white and white.type == "text" and not white.content.count("<"):
            white.unlinkNode()
            white.freeNode()

        node.unlinkNode()
        if dofree:
            node.freeNode()


class XMLProperty(property):
    def __init__(self, fget=None, fset=None, doc=None,
                 xpath=None, get_converter=None, set_converter=None,
                 xml_get_xpath=None, xml_set_xpath=None,
                 is_bool=False, is_multi=False,
                 default_converter=None, clear_first=None):
        """
        Set a XMLBuilder class property that represents a value in the
        <domain> XML. For example

        name = XMLProperty(get_name, set_name, xpath="/domain/name")

        When building XML from scratch (virt-install), name is a regular
        class property. When parsing and editting existing guest XML, we
        use the xpath value to map the name property to the underlying XML
        definition.

        @param fget: typical getter function for the property
        @param fset: typical setter function for the property
        @param doc: option doc string for the property
        @param xpath: xpath string which maps to the associated property
                      in a typical XML document
        @param get_converter:
        @param set_converter: optional function for converting the property
            value from the virtinst API to the guest XML. For example,
            the Guest.memory API is in MB, but the libvirt domain memory API
            is in KB. So, if xpath is specified, on a 'get' operation we need
            to convert the XML value with int(val) / 1024.
        @param xml_get_xpath:
        @param xml_set_xpath: Not all props map cleanly to a static xpath.
            This allows passing functions which generate an xpath for getting
            or setting.
        @param is_bool: Whether this is a boolean property in the XML
        @param is_multi: Whether data is coming multiple or a single node
        @param default_converter: If the virtinst value is "default", use
                                  this function to get the actual XML value
        @param clear_first: List of xpaths to unset before any 'set' operation.
            For those weird interdependent XML props like disk source type and
            path attribute.
        """

        self._xpath = xpath

        self._is_bool = is_bool
        self._is_multi = is_multi

        self._xpath_for_getter_cb = xml_get_xpath
        self._xpath_for_setter_cb = xml_set_xpath

        self._convert_value_for_getter_cb = get_converter
        self._convert_value_for_setter_cb = set_converter
        self._default_converter = default_converter
        self._setter_clear_these_first = clear_first or []

        if not fget:
            fget = self._default_orig_fget
            fset = self._default_orig_fset
            if _trackprops:
                _allprops.append(self)
        self._orig_fget = fget
        self._orig_fset = fset

        property.__init__(self, fget=self.new_getter, fset=self.new_setter,
                          doc=doc)


    ##################
    # Public-ish API #
    ##################

    def __repr__(self):
        ret = property.__repr__(self)
        if self._xpath:
            ret = "<XMLProperty %s>" % str(self._xpath)
        return ret


    ####################
    # Internal helpers #
    ####################

    def _findpropname(self, xmlbuilder):
        """
        Map the raw property() instance to the param name it's exposed
        as in the XMLBuilder class. This is just for debug purposes.
        """
        for key, val in xmlbuilder.__class__.__dict__.items():
            if val is self:
                return key
        raise RuntimeError("Didn't find expected property")

    def _default_orig_fset(self, xmlbuilder, val, *args, **kwargs):
        """
        If no fset specified, this stores the value in XMLBuilder._propstore
        dict as propname->value. This saves us from having to explicitly
        track every variable.
        """
        ignore = args
        ignore = kwargs
        propstore = getattr(xmlbuilder, "_propstore")
        proporder = getattr(xmlbuilder, "_proporder")

        if _trackprops and self not in _seenprops:
            _seenprops.append(self)
        propname = self._findpropname(xmlbuilder)
        propstore[propname] = val

        if propname in proporder:
            proporder.remove(propname)
        proporder.append(propname)

    def _default_orig_fget(self, xmlbuilder, *args, **kwargs):
        """
        The flip side to default_orig_fset, fetch the value from
        XMLBuilder._propstore
        """
        ignore = args
        ignore = kwargs
        propstore = getattr(xmlbuilder, "_propstore")
        return propstore.get(self._findpropname(xmlbuilder), None)

    def _xpath_for_getter(self, xmlbuilder):
        if self._xpath_for_getter_cb:
            return self._xpath_for_getter_cb(xmlbuilder)
        return self._xpath
    def _xpath_for_setter(self, xmlbuilder):
        if self._xpath_for_setter_cb:
            return self._xpath_for_setter_cb(xmlbuilder)
        return self._xpath

    def _xpath_list_for_setter(self, xpath, setval, nodelist):
        if not self._is_multi:
            return [xpath]

        ret = []
        list_length = max(len(nodelist), len(setval), 1)

        # This might not generally work, but as of this writing there's
        # only one user of is_multi and it works for that. It's probably
        # generalizable though.
        for i in range(list_length):
            idxstr = "[%d]/" % (i + 1)
            splitpath = xpath.rsplit("/", 1)
            ret.append("%s%s%s" % (splitpath[0], idxstr, splitpath[1]))
        return ret


    def _convert_value_for_setter(self, xmlbuilder):
        # Convert from API value to XML value
        val = self._orig_fget(xmlbuilder)
        if self._convert_value_for_setter_cb:
            val = self._convert_value_for_setter_cb(xmlbuilder, val)
        elif self._default_converter and val == "default":
            val = self._default_converter(xmlbuilder)
        return val

    def _build_node_list(self, xmlbuilder, xpath):
        """
        Build list of nodes that the passed xpaths reference
        """
        root_ctx = getattr(xmlbuilder, "_xml_ctx")
        nodes = _get_xpath_node(root_ctx, xpath, self._is_multi)
        return util.listify(nodes)

    def _build_clear_list(self, xmlbuilder, setternodes):
        """
        Build a list of nodes that we should erase first before performing
        a set operation. But we don't want to unset a node that we are
        just going to 'set' on top of afterwards, so skip those ones.
        """
        root_ctx = getattr(xmlbuilder, "_xml_ctx")
        clear_nodes = []

        for cpath in self._setter_clear_these_first:
            cnode = _get_xpath_node(root_ctx, cpath, False)
            if not cnode:
                continue
            if any([(n and n.nodePath() == cnode.nodePath())
                    for n in setternodes]):
                continue
            clear_nodes.append(cnode)
        return clear_nodes


    def new_getter(self, xmlbuilder, *args, **kwargs):
        fgetval = self._orig_fget(xmlbuilder, *args, **kwargs)

        root_node = getattr(xmlbuilder, "_xml_node")
        if root_node is None:
            return fgetval

        xpath = self._xpath_for_getter(xmlbuilder)
        if xpath is None:
            return fgetval

        if self._default_converter and fgetval == "default":
            return fgetval

        nodelist = self._build_node_list(xmlbuilder, xpath)

        if nodelist:
            ret = []
            for node in nodelist:
                val = node.content
                if self._convert_value_for_getter_cb:
                    val = self._convert_value_for_getter_cb(xmlbuilder, val)
                elif self._is_bool:
                    val = True

                if not self._is_multi:
                    return val
                # If user is querying multiple nodes, return a list of results
                ret.append(val)
            return ret

        elif self._is_bool:
            return False
        elif self._convert_value_for_getter_cb:
            return self._convert_value_for_getter_cb(xmlbuilder, None)
        return fgetval


    def new_setter(self, xmlbuilder, val, *args, **kwargs):
        # Do this regardless, for validation purposes
        self._orig_fset(xmlbuilder, val, *args, **kwargs)

        root_node = getattr(xmlbuilder, "_xml_node")
        if root_node is None:
            return

        xpath = self._xpath_for_setter(xmlbuilder)
        if xpath is None:
            return

        setval = self._convert_value_for_setter(xmlbuilder)
        nodelist = self._build_node_list(xmlbuilder, xpath)
        clearlist = self._build_clear_list(xmlbuilder, nodelist)

        node_map = []
        if clearlist:
            node_map += _tuplify_lists(clearlist, None, "")
        node_map += _tuplify_lists(nodelist, setval,
                        self._xpath_list_for_setter(xpath, setval, nodelist))

        for node, val, use_xpath in node_map:
            if node:
                use_xpath = node.nodePath()

            if val not in [None, False]:
                if not node:
                    node = _build_xpath_node(root_node, use_xpath)

                if val is True:
                    # Boolean property, creating the node is enough
                    pass
                else:
                    node.setContent(util.xml_escape(str(val)))
            else:
                _remove_xpath_node(root_node, use_xpath)


class XMLBuilder(object):
    """
    Base for all classes which build or parse domain XML
    """
    @staticmethod
    def indent(xmlstr, level):
        xml = ""
        if not xmlstr:
            return xml

        for l in iter(xmlstr.splitlines()):
            xml += " " * level + l + "\n"
        return xml

    _dumpxml_xpath = "."
    def __init__(self, conn, parsexml=None, parsexmlnode=None):
        """
        Initialize state

        @param conn: libvirt connection to validate device against
        @type conn: VirtualConnection
        @param parsexml: Optional XML string to parse
        @type parsexml: C{str}
        @param parsexmlnode: Option xpathNode to use
        """
        self._conn = conn

        self._xml_node = None
        self._xml_ctx = None
        self._xml_root_doc = None
        self._propstore = {}
        self._proporder = []

        if parsexml or parsexmlnode:
            self._parsexml(parsexml, parsexmlnode)

    def __del__(self):
        if hasattr(self, "_xml_ctx") and self._xml_ctx:
            self._xml_ctx.xpathFreeContext()

    def _cache(self):
        """
        This is a hook for classes to cache any state that is expensive
        to lookup before we copy the object as part of Guest.get_xml_config.
        Saves us from possibly doing the lookup over and over
        """
        pass


    def copy(self):
        # Otherwise we can double free XML info
        if self._is_parse():
            return self
        self._cache()
        return copy.copy(self)

    def _get_conn(self):
        return self._conn
    conn = property(_get_conn)

    def _is_parse(self):
        return bool(self._xml_node or self._xml_ctx)

    def set_xml_node(self, node):
        self._parsexml(None, node)

    def get_xml_node_path(self):
        if self._xml_node:
            return self._xml_node.nodePath()
        return None

    def _add_child_node(self, parent_xpath, newnode):
        ret = _build_xpath_node(self._xml_ctx, parent_xpath, newnode)
        return ret

    def _remove_child_xpath(self, xpath):
        _remove_xpath_node(self._xml_ctx, xpath, dofree=False)
        self._set_xml_context()

    def _set_xml_context(self):
        doc = self._xml_node.doc
        ctx = doc.xpathNewContext()
        ctx.setContextNode(self._xml_node)
        if self._xml_ctx:
            self._xml_ctx.xpathFreeContext()
        self._xml_ctx = ctx

    def _parsexml(self, xml, node):
        if xml:
            doc = libxml2.parseDoc(xml)
            self._xml_root_doc = _DocCleanupWrapper(doc)
            self._xml_node = doc.children
            self._xml_node.virtinst_root_doc = self._xml_root_doc
        else:
            self._xml_node = node

        self._set_xml_context()

    def _add_parse_bits(self, xml):
        if not self._propstore or self._is_parse():
            return xml

        try:
            self._parsexml(xml, None)
            for key in self._proporder[:]:
                setattr(self, key, self._propstore[key])
            ret = self.get_xml_config()
            for c in xml:
                if c != " ":
                    break
                ret = " " + ret
            return ret.strip("\n")
        finally:
            self._xml_root_doc = None
            self._xml_node = None
            if self._xml_ctx:
                self._xml_ctx.xpathFreeContext()
            self._xml_ctx = None

    def _get_xml_config(self):
        """
        Internal XML building function. Must be overwritten by subclass
        """
        raise NotImplementedError()

    def get_xml_config(self, *args, **kwargs):
        """
        Construct and return object xml

        @return: object xml representation as a string
        @rtype: str
        """
        if self._xml_ctx:
            node = _get_xpath_node(self._xml_ctx, self._dumpxml_xpath)
            if not node:
                return ""
            return _sanitize_libxml_xml(node.serialize())

        return self._get_xml_config(*args, **kwargs)

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

# pylint: disable=W0212
# This whole file is calling around into non-public functions that we
# don't want regular API users to touch

_trackprops = bool("VIRTINST_TEST_TRACKPROPS" in os.environ)
_allprops = []
_seenprops = []


class _DocCleanupWrapper(object):
    def __init__(self, doc):
        self._doc = doc
    def __del__(self):
        self._doc.freeDoc()


class _CtxCleanupWrapper(object):
    def __init__(self, ctx):
        self._ctx = ctx
    def __del__(self):
        self._ctx.xpathFreeContext()
        self._ctx = None
    def __getattr__(self, attrname):
        return getattr(self._ctx, attrname)


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
                sib = libxml2.newText("\n")
            parentnode.addChild(sib)

        # This case is adding a child element to an already properly
        # spaced element. Example:
        # <features>
        #   <acpi/>
        # </features>
        # to
        # <features>
        #   <acpi/>
        #   <apic/>
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


def _remove_xpath_node(ctx, xpath, dofree=True, root_name=None):
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

        # Don't unlink the root node. This is usually a programming error,
        # but the error usually cascades to a different spot and is hard
        # to pin down. With this we usually get invalid XML which is
        # easier to debug.
        if root_name and node.name == root_name:
            break

        node.unlinkNode()
        if dofree:
            node.freeNode()


class XMLProperty(property):
    def __init__(self, fget=None, fset=None, doc=None, xpath=None, name=None,
                 get_converter=None, set_converter=None,
                 xml_get_xpath=None, xml_set_xpath=None,
                 is_bool=False, is_tri=False, is_int=False,
                 is_multi=False, is_yesno=False,
                 clear_first=None, default_cb=None, default_name=None):
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
        @param name: Just a string to print for debugging, only needed
            if xpath isn't specified.
        @param get_converter:
        @param set_converter: optional function for converting the property
            value from the virtinst API to the guest XML. For example,
            the Guest.memory API was once in MB, but the libvirt domain
            memory API is in KB. So, if xpath is specified, on a 'get'
            operation we convert the XML value with int(val) / 1024.
        @param xml_get_xpath:
        @param xml_set_xpath: Not all props map cleanly to a static xpath.
            This allows passing functions which generate an xpath for getting
            or setting.
        @param is_bool: Whether this is a boolean property in the XML
        @param is_tri: Boolean XML property, but return None if there's
            no value set.
        @param is_multi: Whether data is coming multiple or a single node
        @param is_int: Whethere this is an integer property in the XML
        @param is_yesno: Whethere this is a yes/no property in the XML
        @param clear_first: List of xpaths to unset before any 'set' operation.
            For those weird interdependent XML props like disk source type and
            path attribute.
        @param default_cb: If building XML from scratch, and this property
            is never explicitly altered, this function is called for setting
            a default value in the XML, and for any 'get' call before the
            first explicit 'set'.
        @param default_name: If the user does a set and passes in this
            value, instead use the value of default_cb()
        """

        self._xpath = xpath
        self._name = name or xpath
        if not self._name:
            raise RuntimeError("XMLProperty: name or xpath must be passed.")

        self._is_tri = is_tri
        self._is_bool = is_bool or is_tri
        self._is_int = is_int
        self._is_multi = is_multi
        self._is_yesno = is_yesno

        self._xpath_for_getter_cb = xml_get_xpath
        self._xpath_for_setter_cb = xml_set_xpath

        self._convert_value_for_getter_cb = get_converter
        self._convert_value_for_setter_cb = set_converter
        self._setter_clear_these_first = clear_first or []
        self._default_cb = default_cb
        self._default_name = default_name

        if sum([int(bool(i)) for i in
               [self._is_bool, self._is_int, self._is_yesno]]) > 1:
            raise RuntimeError("Conflict property converter options.")

        if self._default_name and not self._default_cb:
            raise RuntimeError("default_name requires default_cb.")

        self._fget = fget
        self._fset = fset

        if self._is_new_style_prop():
            if _trackprops:
                _allprops.append(self)
        else:
            if self._default_cb:
                raise RuntimeError("Can't set default_cb for old style XML "
                                   "prop.")

        property.__init__(self, fget=self.new_getter, fset=self.new_setter)
        self.__doc__ = doc


    ##################
    # Public-ish API #
    ##################

    def __repr__(self):
        return "<XMLProperty %s %s>" % (str(self._name), id(self))

    def has_default_value(self):
        return bool(self._default_cb)


    ####################
    # Internal helpers #
    ####################

    def _is_new_style_prop(self):
        """
        True if this is a prop without an explicitly passed in fget/fset
        pair.
        """
        return not bool(self._fget)

    def _findpropname(self, xmlbuilder):
        """
        Map the raw property() instance to the param name it's exposed
        as in the XMLBuilder class. This is just for debug purposes.
        """
        for key, val in xmlbuilder.all_xml_props().items():
            if val is self:
                return key
        raise RuntimeError("Didn't find expected property")

    def _xpath_for_getter(self, xmlbuilder):
        ret = self._xpath
        if self._xpath_for_getter_cb:
            ret = self._xpath_for_getter_cb(xmlbuilder)
        if ret is None:
            raise RuntimeError("%s: didn't generate any setter xpath." % self)
        return self._xpath_fix_relative(xmlbuilder, ret)
    def _xpath_for_setter(self, xmlbuilder):
        ret = self._xpath
        if self._xpath_for_setter_cb:
            ret = self._xpath_for_setter_cb(xmlbuilder)
        if ret is None:
            raise RuntimeError("%s: didn't generate any setter xpath." % self)
        return self._xpath_fix_relative(xmlbuilder, ret)
    def _xpath_fix_relative(self, xmlbuilder, xpath):
        if not getattr(xmlbuilder, "_xml_fixup_relative_xpath"):
            return xpath
        root = "./%s" % getattr(xmlbuilder, "_XML_ROOT_NAME")
        if not xpath.startswith(root):
            raise RuntimeError("%s: xpath did not start with root=%s" %
                               (str(self), root))
        ret = "." + xpath[len(root):]
        return ret


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
        if self._default_name and val == self._default_name:
            val = self._default_cb(xmlbuilder)
        elif self._is_yesno:
            if val is not None:
                val = bool(val) and "yes" or "no"

        if self._convert_value_for_setter_cb:
            val = self._convert_value_for_setter_cb(xmlbuilder, val)
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


    def _convert_get_value(self, xmlbuilder, val, initial=False):
        if self._fget and initial:
            # If user passed in an fget impl, we expect them to put things
            # in the form they want.
            return val

        if self._is_bool:
            if initial and self._is_tri and val is None:
                ret = None
            else:
                ret = bool(val)
        elif self._is_int and val is not None:
            intkwargs = {}
            if "0x" in str(val):
                intkwargs["base"] = 16
            ret = int(val, **intkwargs)
        elif self._is_yesno and val is not None:
            ret = bool(val == "yes")
        elif self._is_multi and val is None:
            ret = []
        else:
            ret = val

        if self._convert_value_for_getter_cb:
            ret = self._convert_value_for_getter_cb(xmlbuilder, ret)
        return ret

    def _orig_fget(self, xmlbuilder):
        # Returns (is unset, fget value)
        if self._fget:
            # For the passed in fget callback, we have any way to
            # tell if the value is unset or not.
            return self._fget(xmlbuilder)

        # The flip side to default_orig_fset, fetch the value from
        # XMLBuilder._propstore
        propstore = getattr(xmlbuilder, "_propstore")
        propname = self._findpropname(xmlbuilder)
        unset = (propname not in propstore)
        if unset and self._default_cb:
            if self._default_name:
                return self._default_name
            return self._default_cb(xmlbuilder)
        return propstore.get(propname, None)

    def _orig_fset(self, xmlbuilder, val):
        """
        If no fset specified, this stores the value in XMLBuilder._propstore
        dict as propname->value. This saves us from having to explicitly
        track every variable.
        """
        if self._fset:
            return self._fset(xmlbuilder, val)

        propstore = getattr(xmlbuilder, "_propstore")
        proporder = getattr(xmlbuilder, "_proporder")

        if _trackprops and self not in _seenprops:
            _seenprops.append(self)
        propname = self._findpropname(xmlbuilder)
        propstore[propname] = val

        if propname in proporder:
            proporder.remove(propname)
        proporder.append(propname)



    ##################################
    # The actual getter/setter impls #
    ##################################

    def new_getter(self, xmlbuilder):
        fgetval = self._orig_fget(xmlbuilder)

        root_node = getattr(xmlbuilder, "_xml_node")
        if root_node is None:
            return self._convert_get_value(xmlbuilder, fgetval, initial=True)

        xpath = self._xpath_for_getter(xmlbuilder)
        nodelist = self._build_node_list(xmlbuilder, xpath)

        if not nodelist:
            return self._convert_get_value(xmlbuilder, None)

        ret = []
        for node in nodelist:
            content = node.content
            if self._is_bool:
                content = True
            val = self._convert_get_value(xmlbuilder, content)
            if not self._is_multi:
                return val
            # If user is querying multiple nodes, return a list of results
            ret.append(val)
        return ret


    def new_setter(self, xmlbuilder, val, call_fset=True):
        if call_fset:
            self._orig_fset(xmlbuilder, val)

        root_node = getattr(xmlbuilder, "_xml_node")
        if root_node is None:
            return

        xpath = self._xpath_for_setter(xmlbuilder)
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

            if val is None or val is False:
                _remove_xpath_node(root_node, use_xpath,
                                   root_name=root_node.name)
                continue

            if not node:
                node = _build_xpath_node(root_node, use_xpath)

            if val is True:
                # Boolean property, creating the node is enough
                continue
            node.setContent(util.xml_escape(str(val)))

    def _prop_is_unset(self, xmlbuilder):
        propstore = getattr(xmlbuilder, "_propstore")
        propname = self._findpropname(xmlbuilder)
        return (propname not in propstore)

    def refresh_xml(self, xmlbuilder, force_call_fset=False):
        call_fset = True
        if not self._is_new_style_prop():
            call_fset = False
        elif getattr(xmlbuilder, "_is_parse")():
            call_fset = False
        elif self._prop_is_unset(xmlbuilder) and self._default_cb:
            call_fset = False

        if force_call_fset:
            call_fset = True
        self.fset(xmlbuilder, self.fget(xmlbuilder), call_fset=call_fset)

    def set_default(self, xmlbuilder):
        if not self._prop_is_unset(xmlbuilder) or not self._default_cb:
            return
        if self._default_cb(xmlbuilder) is None:
            return
        self.refresh_xml(xmlbuilder, force_call_fset=True)


class XMLBuilder(object):
    """
    Base for all classes which build or parse domain XML
    """
    @staticmethod
    def indent(xmlstr, level):
        xml = ""
        if not xmlstr:
            return xml
        if not level:
            return xmlstr
        return "\n".join((" " * level + l) for l in xmlstr.splitlines())

    # Order that we should apply values to the XML. Keeps XML generation
    # consistent with what the test suite expects.
    _XML_PROP_ORDER = []

    # Root element name of this function, used to populate a default
    # _get_xml_config
    _XML_ROOT_NAME = None

    # Integer indentation level for generated XML.
    _XML_INDENT = None

    # If XML xpaths are relative to a different element, like
    # device addresses.
    _XML_XPATH_RELATIVE = False

    # List of property names that point to a manually tracked
    # XMLBuilder that alters our device xml, like self.address for
    # VirtualDevice
    _XML_SUB_ELEMENTS = []

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
        self._xml_fixup_relative_xpath = False
        self._propstore = {}
        self._proporder = []

        if parsexml or parsexmlnode:
            self._parsexml(parsexml, parsexmlnode)


    ##############
    # Public API #
    ##############

    def copy(self):
        ret = copy.copy(self)
        ret._propstore = ret._propstore.copy()
        ret._proporder = ret._proporder[:]
        return ret

    def _get_conn(self):
        return self._conn
    conn = property(_get_conn)

    def set_xml_node(self, node):
        self._parsexml(None, node)

    def get_xml_node_path(self):
        if self._xml_node:
            return self._xml_node.nodePath()
        return None

    def get_xml_config(self, *args, **kwargs):
        """
        Construct and return object xml

        @return: object xml representation as a string
        @rtype: str
        """
        if self._xml_ctx:
            dumpxml_path = self._dumpxml_xpath
            if self._xml_fixup_relative_xpath:
                dumpxml_path = "."

            node = _get_xpath_node(self._xml_ctx, dumpxml_path)
            if not node:
                ret = ""
            else:
                ret = _sanitize_libxml_xml(node.serialize())
        else:
            xmlstub = self._make_xml_stub(fail=False)
            ret = self._get_xml_config(*args, **kwargs)
            if ret is None:
                return None
            ret = self._add_parse_bits(ret)

            for propname in self._XML_SUB_ELEMENTS:
                for prop in util.listify(getattr(self, propname)):
                    ret = prop._add_parse_bits(ret)

            if ret == xmlstub:
                ret = ""

        return self._cleanup_xml(ret)


    #######################
    # Internal helper API #
    #######################

    def _is_parse(self):
        return bool(self._xml_node or self._xml_ctx)

    def _refresh_xml_prop(self, propname):
        """
        Refresh the XML for the passed class propname. Used to adjust
        the XML when an interdependent property changes.
        """
        self.all_xml_props()[propname].refresh_xml(self)


    ###################
    # Child overrides #
    ###################

    def set_defaults(self):
        pass

    def validate(self):
        pass

    def _get_xml_config(self):
        """
        Internal XML building function. Must be overwritten by subclass
        """
        return self._make_xml_stub(fail=True)

    def _cleanup_xml(self, xml):
        """
        Hook for classes to touch up the XML after generation.
        """
        return xml


    ########################
    # Internal XML parsers #
    ########################

    def _make_xml_stub(self, fail=True):
        if self._XML_ROOT_NAME is None:
            if not fail:
                return None
            raise RuntimeError("Must specify _XML_ROOT_NAME.")
        if self._XML_INDENT is None:
            if not fail:
                return None
            raise RuntimeError("Must specify _XML_INDENT.")
        if self._XML_ROOT_NAME == "":
            return ""

        return self.indent("<%s/>" % (self._XML_ROOT_NAME), self._XML_INDENT)

    def _add_child_node(self, parent_xpath, newnode):
        ret = _build_xpath_node(self._xml_ctx, parent_xpath, newnode)
        return ret

    def _remove_child_xpath(self, xpath):
        _remove_xpath_node(self._xml_ctx, xpath, dofree=False)
        self._set_xml_context()

    def _set_xml_context(self):
        doc = self._xml_node.doc
        ctx = _CtxCleanupWrapper(doc.xpathNewContext())
        ctx.setContextNode(self._xml_node)
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

    def all_xml_props(self):
        ret = {}
        for c in reversed(type.mro(self.__class__)[:-1]):
            for key, val in c.__dict__.items():
                if val.__class__ is XMLProperty:
                    ret[key] = val
        return ret

    def _do_add_parse_bits(self, xml):
        # Find all properties that have default callbacks
        xmlprops = self.all_xml_props()
        defaultprops = [v for v in xmlprops.values() if v.has_default_value()]
        for prop in defaultprops:
            prop.set_default(self)

        # Default props alter our _propstore. But at this point _propstore
        # is empty, there's nothing for us to do, so exit early
        if not self._propstore:
            return xml

        # Unindent XML
        indent = 0
        for c in xml:
            if c != " ":
                break
            indent += 1
        xml = "\n".join([l[indent:] for l in xml.splitlines()])

        # Parse the XML into our internal state. Use the raw
        # _parsexml so we don't hit Guest parsing into its internal state
        XMLBuilder._parsexml(self, xml, None)

        # Set up preferred XML ordering
        do_order = self._proporder[:]
        for key in reversed(self._XML_PROP_ORDER):
            if key in do_order:
                do_order.remove(key)
                do_order.insert(0, key)

        # Alter the XML
        for key in do_order:
            setattr(self, key, self._propstore[key])
        return self.indent(self.get_xml_config().strip("\n"), indent)

    def _add_parse_bits(self, xml):
        """
        Callback that adds the implicitly tracked XML properties to
        the manually generated xml. This should only exist until all
        classes are converted to all parsing all the time
        """
        if self._is_parse():
            return xml

        origproporder = self._proporder[:]
        origpropstore = self._propstore.copy()
        try:
            self._xml_fixup_relative_xpath = self._XML_XPATH_RELATIVE
            return self._do_add_parse_bits(xml)
        finally:
            self._xml_root_doc = None
            self._xml_node = None
            self._xml_ctx = None
            self._proporder = origproporder
            self._propstore = origpropstore
            self._xml_fixup_relative_xpath = False

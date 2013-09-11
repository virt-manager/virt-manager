#
# Base class for all VM devices
#
# Copyright 2008, 2013  Red Hat, Inc.
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
import re

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


def _indent(xmlstr, level):
    xml = ""
    if not xmlstr:
        return xml
    if not level:
        return xmlstr
    return "\n".join((" " * level + l) for l in xmlstr.splitlines())


def _make_xml_context(node):
    doc = node.doc
    ctx = _CtxCleanupWrapper(doc.xpathNewContext())
    ctx.setContextNode(node)
    return ctx


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


def _get_xpath_node(ctx, xpath):
    node = ctx.xpathEval(xpath)
    return (node and node[0] or None)


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


def _remove_xpath_node(ctx, xpath, dofree=True, unlinkroot=True):
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

        if not unlinkroot and node == ctx:
            # Don't unlink the root node. This is usually a programming error,
            # but the error usually cascades to a different spot and is hard
            # to pin down. With this we usually get invalid XML which is
            # easier to debug.
            break

        node.unlinkNode()
        if dofree:
            node.freeNode()


class XMLChildProperty(property):
    """
    Property that points to a class used for parsing a subsection of
    of the parent XML. For example when we deligate parsing
    /domain/cpu/feature of the /domain/cpu class.

    @child_classes: Single class or list of classes to parse state into
    @relative_xpath: Relative location where the class is rooted compared
        to its _XML_ROOT_PATH. So interface xml can have nested
        interfaces rooted at /interface/bridge/interface, so we pass
        ./bridge/interface here for example.
    """
    def __init__(self, child_classes, relative_xpath="."):
        self.child_classes = util.listify(child_classes)
        self.relative_xpath = relative_xpath
        property.__init__(self, self._fget)

    def __repr__(self):
        return "<XMLChildProperty %s %s>" % (str(self.child_classes), id(self))

    def _findpropname(self, xmlbuilder):
        for key, val in xmlbuilder._all_child_props().items():
            if val is self:
                return key
        raise RuntimeError("Didn't find expected property=%s" % self)

    def _get_list(self, xmlbuilder):
        propname = self._findpropname(xmlbuilder)
        if propname not in xmlbuilder._propstore:
            xmlbuilder._propstore[propname] = []
        return xmlbuilder._propstore[propname]

    def _fget(self, xmlbuilder):
        return self._get_list(xmlbuilder)[:]

    def append(self, xmlbuilder, obj):
        self._get_list(xmlbuilder).append(obj)
    def remove(self, xmlbuilder, obj):
        self._get_list(xmlbuilder).remove(obj)

    def get_prop_xpath(self, xmlbuilder, child_class):
        child_root = child_class._XML_ROOT_XPATH
        relative_xpath = self.relative_xpath

        match = re.search("%\((.*)\)", self.relative_xpath)
        if match:
            valuedict = {}
            for paramname in match.groups():
                valuedict[paramname] = getattr(xmlbuilder, paramname)
            relative_xpath = relative_xpath % valuedict
        return child_root.replace(xmlbuilder._xmlstate.get_node_top_xpath(),
                                  relative_xpath)


class XMLProperty(property):
    def __init__(self, xpath=None, name=None, doc=None,
                 set_converter=None, validate_cb=None,
                 make_getter_xpath_cb=None, make_setter_xpath_cb=None,
                 is_bool=False, is_int=False, is_yesno=False, is_onoff=False,
                 clear_first=None, default_cb=None, default_name=None):
        """
        Set a XMLBuilder class property that represents a value in the
        <domain> XML. For example

        name = XMLProperty(get_name, set_name, xpath="/domain/name")

        When building XML from scratch (virt-install), name is a regular
        class property. When parsing and editting existing guest XML, we
        use the xpath value to map the name property to the underlying XML
        definition.

        @param doc: option doc string for the property
        @param xpath: xpath string which maps to the associated property
                      in a typical XML document
        @param name: Just a string to print for debugging, only needed
            if xpath isn't specified.
        @param set_converter: optional function for converting the property
            value from the virtinst API to the guest XML. For example,
            the Guest.memory API was once in MB, but the libvirt domain
            memory API is in KB. So, if xpath is specified, on a 'get'
            operation we convert the XML value with int(val) / 1024.
        @param validate_cb: Called once when value is set, should
            raise a RuntimeError if the value is not proper.
        @param make_getter_xpath_cb:
        @param make_setter_xpath_cb: Not all props map cleanly to a
            static xpath. This allows passing functions which generate
            an xpath for getting or setting.
        @param is_bool: Whether this is a boolean property in the XML
        @param is_int: Whether this is an integer property in the XML
        @param is_yesno: Whether this is a yes/no property in the XML
        @param is_onoff: Whether this is an on/off property in the XML
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

        self._is_bool = is_bool
        self._is_int = is_int
        self._is_yesno = is_yesno
        self._is_onoff = is_onoff

        self._xpath_for_getter_cb = make_getter_xpath_cb
        self._xpath_for_setter_cb = make_setter_xpath_cb

        self._validate_cb = validate_cb
        self._convert_value_for_setter_cb = set_converter
        self._setter_clear_these_first = clear_first or []
        self._default_cb = default_cb
        self._default_name = default_name

        if sum([int(bool(i)) for i in
                [self._is_bool, self._is_int,
                 self._is_yesno, self._is_onoff]]) > 1:
            raise RuntimeError("Conflict property converter options.")

        if self._default_name and not self._default_cb:
            raise RuntimeError("default_name requires default_cb.")

        if _trackprops:
            _allprops.append(self)

        property.__init__(self, fget=self.getter, fset=self.setter)
        self.__doc__ = doc


    def __repr__(self):
        return "<XMLProperty %s %s>" % (str(self._name), id(self))


    ####################
    # Internal helpers #
    ####################

    def _findpropname(self, xmlbuilder):
        """
        Map the raw property() instance to the param name it's exposed
        as in the XMLBuilder class. This is just for debug purposes.
        """
        for key, val in xmlbuilder._all_xml_props().items():
            if val is self:
                return key
        raise RuntimeError("Didn't find expected property=%s" % self)

    def _xpath_for_getter(self, xmlbuilder):
        ret = self._xpath
        if self._xpath_for_getter_cb:
            ret = self._xpath_for_getter_cb(xmlbuilder)
        if ret is None:
            raise RuntimeError("%s: didn't generate any setter xpath." % self)
        return xmlbuilder.fix_relative_xpath(ret)
    def _xpath_for_setter(self, xmlbuilder):
        ret = self._xpath
        if self._xpath_for_setter_cb:
            ret = self._xpath_for_setter_cb(xmlbuilder)
        if ret is None:
            raise RuntimeError("%s: didn't generate any setter xpath." % self)
        return xmlbuilder.fix_relative_xpath(ret)


    def _build_node_list(self, xmlbuilder, xpath):
        """
        Build list of nodes that the passed xpaths reference
        """
        nodes = _get_xpath_node(xmlbuilder._xmlstate.xml_ctx, xpath)
        return util.listify(nodes)

    def _build_clear_list(self, xmlbuilder, setternode):
        """
        Build a list of nodes that we should erase first before performing
        a set operation. But we don't want to unset a node that we are
        just going to 'set' on top of afterwards, so skip those ones.
        """
        clear_nodes = []

        for cpath in self._setter_clear_these_first:
            cpath = xmlbuilder.fix_relative_xpath(cpath)
            cnode = _get_xpath_node(xmlbuilder._xmlstate.xml_ctx, cpath)
            if not cnode:
                continue
            if setternode and setternode.nodePath() == cnode.nodePath():
                continue
            clear_nodes.append(cnode)
        return clear_nodes


    def _convert_get_value(self, val):
        if self._default_name and val == self._default_name:
            ret = val
        elif self._is_bool:
            ret = bool(val)
        elif self._is_int and val is not None:
            intkwargs = {}
            if "0x" in str(val):
                intkwargs["base"] = 16
            ret = int(val, **intkwargs)
        elif self._is_yesno and val is not None:
            ret = bool(val == "yes")
        elif self._is_onoff and val is not None:
            ret = bool(val == "on")
        else:
            ret = val
        return ret

    def _convert_set_value(self, xmlbuilder, val):
        if self._default_name and val == self._default_name:
            val = self._default_cb(xmlbuilder)
        elif self._is_onoff and val is not None:
            val = bool(val) and "on" or "off"
        elif self._is_yesno and val is not None:
            val = bool(val) and "yes" or "no"
        elif self._is_int and val is not None:
            intkwargs = {}
            if "0x" in str(val):
                intkwargs["base"] = 16
            val = int(val, **intkwargs)

        if self._convert_value_for_setter_cb:
            val = self._convert_value_for_setter_cb(xmlbuilder, val)
        return val

    def _prop_is_unset(self, xmlbuilder):
        propname = self._findpropname(xmlbuilder)
        return (propname not in xmlbuilder._propstore)

    def _default_get_value(self, xmlbuilder):
        """
        Return (can use default, default value)
        """
        ret = (False, -1)
        if not xmlbuilder._xmlstate.is_build:
            return ret
        if not self._prop_is_unset(xmlbuilder):
            return ret
        if not self._default_cb:
            return ret

        if self._default_name:
            return (True, self._default_name)
        return (True, self._default_cb(xmlbuilder))


    def _set_default(self, xmlbuilder):
        """
        Encode the property default into the XML and propstore, but
        only if a default is registered, and only if the property was
        not already explicitly set by the API user.

        This is called during the get_xml_config process and shouldn't
        be called from outside this file.
        """
        candefault, val = self._default_get_value(xmlbuilder)
        if not candefault:
            return
        self.setter(xmlbuilder, val, validate=False)

    def _nonxml_fset(self, xmlbuilder, val):
        """
        This stores the value in XMLBuilder._propstore
        dict as propname->value. This saves us from having to explicitly
        track every variable.
        """
        propstore = xmlbuilder._propstore
        proporder = xmlbuilder._proporder

        if _trackprops and self not in _seenprops:
            _seenprops.append(self)
        propname = self._findpropname(xmlbuilder)
        propstore[propname] = val

        if propname in proporder:
            proporder.remove(propname)
        proporder.append(propname)

    def _nonxml_fget(self, xmlbuilder):
        """
        The flip side to nonxml_fset, fetch the value from
        XMLBuilder._propstore
        """
        candefault, val = self._default_get_value(xmlbuilder)
        if candefault:
            return val

        propname = self._findpropname(xmlbuilder)
        return xmlbuilder._propstore.get(propname, None)

    def _clear(self, xmlbuilder):
        self.setter(xmlbuilder, None)
        self._set_xml(xmlbuilder, None)


    ##################################
    # The actual getter/setter impls #
    ##################################

    def getter(self, xmlbuilder):
        """
        Fetch value at user request. If we are parsing existing XML and
        the user hasn't done a 'set' yet, return the value from the XML,
        otherwise return the value from propstore

        If this is a built from scratch object, we never pull from XML
        since it's known to the empty, and we may want to return
        a 'default' value
        """
        if (self._prop_is_unset(xmlbuilder) and
            not xmlbuilder._xmlstate.is_build):
            val = self._get_xml(xmlbuilder)
        else:
            val = self._nonxml_fget(xmlbuilder)
        ret = self._convert_get_value(val)
        return ret

    def _get_xml(self, xmlbuilder):
        """
        Actually fetch the associated value from the backing XML
        """
        xpath = self._xpath_for_getter(xmlbuilder)
        node = _get_xpath_node(xmlbuilder._xmlstate.xml_ctx, xpath)
        if not node:
            return None

        content = node.content
        if self._is_bool:
            content = True
        return content

    def setter(self, xmlbuilder, val, validate=True):
        """
        Set the value at user request. This just stores the value
        in propstore. Setting the actual XML is only done at
        get_xml_config time.
        """
        if validate and self._validate_cb:
            self._validate_cb(xmlbuilder, val)
        self._nonxml_fset(xmlbuilder,
                          self._convert_set_value(xmlbuilder, val))

    def _set_xml(self, xmlbuilder, setval, root_node=None):
        """
        Actually set the passed value in the XML document
        """
        if root_node is None:
            root_node = xmlbuilder._xmlstate.xml_node
        xpath = self._xpath_for_setter(xmlbuilder)
        node = _get_xpath_node(xmlbuilder._xmlstate.xml_ctx, xpath)
        clearlist = self._build_clear_list(xmlbuilder, node)

        node_map = []
        if clearlist:
            node_map += _tuplify_lists(clearlist, None, "")
        node_map += [(node, setval, xpath)]

        for node, val, use_xpath in node_map:
            if node:
                use_xpath = node.nodePath()

            if val is None or val is False:
                _remove_xpath_node(root_node, use_xpath, unlinkroot=False)
                continue

            if not node:
                node = _build_xpath_node(root_node, use_xpath)

            if val is True:
                # Boolean property, creating the node is enough
                continue
            node.setContent(util.xml_escape(str(val)))


class _XMLState(object):
    def __init__(self, xpath, parsexml, parsexmlnode):
        if xpath is None or not xpath.startswith("/"):
            raise RuntimeError("xpath=%s must start with /" % xpath)

        self.orig_root_xpath = xpath
        self.root_name = xpath.split("/")[-1]
        self.indent = (xpath.count("/") - 1) * 2

        self.xml_ctx = None
        self.xml_node = None
        self.xml_root_doc = None

        # xpath of this object relative to its parent. So for a standalone
        # <disk> this is empty, but if the disk is the forth one in a <domain>
        # it will be set to ./devices/disk[4]
        self._relative_object_xpath = ""

        # xpath of the parent. For a disk in a standalone <domain>, this
        # is empty, but if the <domain> is part of a <domainsnapshot>,
        # it will be "./domain"
        self._parent_xpath = ""

        self.is_build = False
        if not parsexml and not parsexmlnode:
            self.is_build = True
        self._parse(parsexml, parsexmlnode)

    def _parse(self, xml, node):
        if node:
            self.xml_root_doc = None
            self.xml_node = node
            self.is_build = (getattr(node, "virtinst_is_build", False) or
                             self.is_build)
        else:
            if not xml:
                xml = self.make_xml_stub()
            doc = libxml2.parseDoc(xml)
            self.xml_root_doc = _DocCleanupWrapper(doc)
            self.xml_node = doc.children
            self.xml_node.virtinst_is_build = self.is_build
            self.xml_node.virtinst_node_top_xpath = self.orig_root_xpath

            # This just stores a reference to our root doc wrapper in
            # the root node, so when the node goes away it triggers
            # auto free'ing of the doc
            self.xml_node.virtinst_root_doc = self.xml_root_doc

        self.xml_ctx = _make_xml_context(self.xml_node)

    def make_xml_stub(self):
        return _indent(("<%s/>" % self.root_name), self.indent)

    def set_relative_object_xpath(self, xpath):
        self._relative_object_xpath = xpath or ""
    def get_relative_object_xpath(self):
        return self._relative_object_xpath

    def set_parent_xpath(self, xpath):
        self._parent_xpath = xpath or ""
    def get_parent_xpath(self):
        return self._parent_xpath

    def get_root_xpath(self):
        fullpath = self._parent_xpath or ""
        if not fullpath:
            return self._relative_object_xpath
        if self._relative_object_xpath:
            fullpath += "/" + self._relative_object_xpath[2:]
        return fullpath

    def fix_relative_xpath(self, xpath):
        fullpath = self.get_root_xpath()
        if not fullpath:
            return xpath
        if xpath.startswith("."):
            return "%s%s" % (fullpath, xpath.strip("."))
        if xpath.count("/") == 1:
            return fullpath
        return fullpath + "/" + xpath.split("/", 2)[2]

    def get_node_top_xpath(self):
        """
        Return the XML path of the root xml_node
        """
        return self.xml_node.virtinst_node_top_xpath

    def _get_dump_xpath(self):
        if self.xml_root_doc or self.get_root_xpath():
            return self.fix_relative_xpath(".")
        return self.orig_root_xpath

    def get_node_xml(self, ctx=None):
        if ctx is None:
            ctx = self.xml_ctx

        node = _get_xpath_node(ctx, self._get_dump_xpath())
        if not node:
            return ""
        return _sanitize_libxml_xml(node.serialize())


class XMLBuilder(object):
    """
    Base for all classes which build or parse domain XML
    """
    # Order that we should apply values to the XML. Keeps XML generation
    # consistent with what the test suite expects.
    _XML_PROP_ORDER = []

    # Absolute xpath this object is rooted at
    _XML_ROOT_XPATH = None

    def __init__(self, conn, parsexml=None, parsexmlnode=None):
        """
        Initialize state

        @param conn: libvirt connection to validate device against
        @type conn: VirtualConnection
        @param parsexml: Optional XML string to parse
        @type parsexml: C{str}
        @param parsexmlnode: Option xpathNode to use
        """
        self.conn = conn

        self._propstore = {}
        self._proporder = []
        self._xmlstate = _XMLState(self._XML_ROOT_XPATH,
                                   parsexml, parsexmlnode)

        # Walk the XML tree and hand of parsing to any registered
        # child classes
        for xmlprop in self._all_child_props().values():
            for child_class in xmlprop.child_classes:
                prop_path = xmlprop.get_prop_xpath(self, child_class)

                nodecount = int(self._xml_node.xpathEval(
                    "count(%s)" % prop_path))
                for ignore in range(nodecount):
                    xmlprop.append(self,
                        child_class(self.conn, parsexmlnode=self._xml_node))
        self._set_child_xpaths()


    ########################
    # Public XML Internals #
    ########################

    def copy(self):
        """
        Do a shallow copy of the device
        """
        ret = copy.copy(self)
        ret._propstore = ret._propstore.copy()
        ret._proporder = ret._proporder[:]

        # XMLChildProperty stores a list in propstore, which dict shallow
        # copy won't fix for us.
        for name, value in ret._propstore.items():
            if type(value) is not list:
                continue
            ret._propstore[name] = [obj.copy() for obj in ret._propstore[name]]

        return ret

    def get_root_xpath(self):
        return self._xmlstate.get_root_xpath()

    def fix_relative_xpath(self, xpath):
        return self._xmlstate.fix_relative_xpath(xpath)


    ############################
    # Public XML managing APIs #
    ############################

    def get_xml_config(self):
        """
        Return XML string of the object
        """
        data = self._prepare_get_xml()
        try:
            return self._do_get_xml_config()
        finally:
            self._finish_get_xml(data)

    def clear(self):
        """
        Wipe out all properties of the object
        """
        for prop in self._all_xml_props().values():
            prop._clear(self)
        for prop in self._all_child_props().values():
            for obj in prop._get_list(self)[:]:
                self._remove_child(obj)

    def validate(self):
        """
        Validate any set values and raise an exception if there's
        a problem
        """
        pass

    def set_defaults(self):
        """
        Encode any default values if needed
        """
        pass


    ###################
    # Child overrides #
    ###################

    def _prepare_get_xml(self):
        """
        Subclasses can override this to do any pre-get_xml_config setup.
        Returns data to pass to finish_get_xml
        """
        return None

    def _finish_get_xml(self, data):
        """
        Called after get_xml_config. Data is whatever was returned by
        _prepare_get_xml
        """
        ignore = data


    ################
    # Internal API #
    ################

    _xml_node = property(lambda s: s._xmlstate.xml_node)

    def _all_xml_props(self):
        """
        Return a list of all XMLProperty instances that this class has.
        """
        ret = {}
        for c in reversed(type.mro(self.__class__)[:-1]):
            for key, val in c.__dict__.items():
                if val.__class__ is XMLProperty:
                    ret[key] = val
        return ret

    def _all_child_props(self):
        """
        Return a list of all XMLChildProperty instances that this class has.
        """
        ret = {}
        for c in reversed(type.mro(self.__class__)[:-1]):
            for key, val in c.__dict__.items():
                if val.__class__ is XMLChildProperty:
                    ret[key] = val
        return ret

    def _set_parent_xpath(self, xpath):
        self._xmlstate.set_parent_xpath(xpath)
        for p in self._all_subelement_props():
            p._set_parent_xpath(self.get_root_xpath())

    def _set_relative_object_xpath(self, xpath):
        self._xmlstate.set_relative_object_xpath(xpath)
        for p in self._all_subelement_props():
            p._set_parent_xpath(self.get_root_xpath())

    def _find_child_prop(self, child_class):
        xmlprops = self._all_child_props()
        for xmlprop in xmlprops.values():
            if child_class in xmlprop.child_classes:
                return xmlprop
        raise RuntimeError("programming error: "
                           "Didn't find child property for child_class=%s" %
                           child_class)

    def _add_child(self, obj):
        """
        Insert the passed XMLBuilder object into our XML document. The
        object needs to have an associated mapping via XMLChildProperty
        """
        xmlprop = self._find_child_prop(obj.__class__)
        xml = obj.get_xml_config()
        xmlprop.append(self, obj)
        self._set_child_xpaths()

        if not obj._xmlstate.is_build:
            use_xpath = obj.get_root_xpath().rsplit("/", 1)[0]
            newnode = libxml2.parseDoc(xml).children
            _build_xpath_node(self._xmlstate.xml_ctx, use_xpath, newnode)
        obj._xmlstate._parse(None, self._xmlstate.xml_node)

    def _remove_child(self, obj):
        """
        Remove the passed XMLBuilder object from our XML document, but
        ensure it's data isn't altered.
        """
        xmlprop = self._find_child_prop(obj.__class__)
        xmlprop.remove(self, obj)

        xpath = obj.get_root_xpath()
        xml = obj.get_xml_config()
        obj._set_parent_xpath(None)
        obj._set_relative_object_xpath(None)
        obj._xmlstate._parse(xml, None)
        _remove_xpath_node(self._xmlstate.xml_ctx, xpath, dofree=False)
        self._set_child_xpaths()

    def _all_subelement_props(self):
        """
        Return a list of all sub element properties this class tracks.
        A sub element is an XMLBuilder that is tracked explicitly in
        a parent class, which alters the parent XML.
        VirtualDevice.address is an example.
        """
        xmlprops = self._all_xml_props()
        childprops = self._all_child_props()
        ret = []
        propmap = {}
        for propname in self._XML_PROP_ORDER:
            if propname not in xmlprops:
                propmap[propname] = getattr(self, propname)
        for propname in childprops:
            propmap[propname] = getattr(self, propname)

        for objs in propmap.values():
            ret.extend(util.listify(objs))
        return ret


    #################################
    # Private XML building routines #
    #################################

    def _set_child_xpaths(self):
        """
        Walk the list of child properties and make sure their
        xpaths point at their particular element
        """
        typecount = {}
        for propname, xmlprop in self._all_child_props().items():
            for obj in getattr(self, propname):
                class_type = obj.__class__
                if class_type not in typecount:
                    typecount[class_type] = 0
                idx = typecount[class_type]

                prop_path = xmlprop.get_prop_xpath(self, obj)
                obj._set_parent_xpath(self.get_root_xpath())
                obj._set_relative_object_xpath(prop_path + ("[%d]" % (idx + 1)))
                typecount[class_type] += 1


    def _do_get_xml_config(self):
        xmlstub = self._xmlstate.make_xml_stub()

        try:
            node = None
            ctx = None
            if self._xmlstate.is_build:
                node = self._xmlstate.xml_node.docCopyNodeList(
                    self._xmlstate.xml_node.doc)
                ctx = _make_xml_context(node)
            ret = self._add_parse_bits(node, ctx)
        finally:
            if node:
                node.freeNode()

        if ret == xmlstub:
            ret = ""

        if (ret and
            self._xmlstate.root_name == "domain" and
            not ret.endswith("\n")):
            ret += "\n"
        return ret

    def _add_parse_bits(self, node, ctx):
        """
        Callback that adds the implicitly tracked XML properties to
        the backing xml.
        """
        origproporder = self._proporder[:]
        origpropstore = self._propstore.copy()
        try:
            return self._do_add_parse_bits(node, ctx)
        finally:
            self._proporder = origproporder
            self._propstore = origpropstore

    def _do_add_parse_bits(self, node, ctx):
        # Set all defaults if the properties have one registered
        xmlprops = self._all_xml_props()

        for prop in xmlprops.values():
            prop._set_default(self)

        # Set up preferred XML ordering
        do_order = self._proporder[:]
        for key in reversed(self._XML_PROP_ORDER):
            if key in do_order:
                do_order.remove(key)
                do_order.insert(0, key)
            elif key not in xmlprops:
                do_order.insert(0, key)

        # Alter the XML
        for key in do_order:
            if key in xmlprops:
                xmlprops[key]._set_xml(self, self._propstore[key], node)
                continue

            for obj in util.listify(getattr(self, key)):
                obj._add_parse_bits(node, ctx)

        return self._xmlstate.get_node_xml(ctx)

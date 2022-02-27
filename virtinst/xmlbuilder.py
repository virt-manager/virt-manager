#
# Base class for all VM devices
#
# Copyright 2008, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import collections
import os
import re
import string
import textwrap

from .logger import log
from .xmlapi import XMLAPI
from . import xmlutil


# pylint: disable=protected-access
# This whole file is calling around into non-public functions that we
# don't want regular API users to touch

_trackprops = bool("VIRTINST_TEST_SUITE" in os.environ)
_allprops = []
_seenprops = []


class XMLManualAction(object):
    """
    Helper class for tracking and performing the user requested manual
    XML action
    """
    ACTION_CREATE = 1
    ACTION_DELETE = 2
    ACTION_SET = 3

    xpath_delete = None
    xpath_create = None
    xpath_value = None
    xpath_set = None

    def _process_args(self):
        def _ret(x, a, v=None):
            return (x, a, v)

        if self.xpath_delete:
            return _ret(self.xpath_delete, XMLManualAction.ACTION_DELETE)
        if self.xpath_create:
            return _ret(self.xpath_create, XMLManualAction.ACTION_CREATE)

        xpath = self.xpath_set
        if self.xpath_value:
            val = self.xpath_value
        else:
            if "=" not in str(xpath):
                raise Exception(
                    "%s: Setting xpath must be in the form of XPATH=VALUE" %
                    xpath)
            xpath, val = xpath.rsplit("=", 1)
        return _ret(xpath, XMLManualAction.ACTION_SET, val)

    def perform(self, xmlstate):
        if (not self.xpath_delete and
            not self.xpath_create and
            not self.xpath_value and
            not self.xpath_set):
            return
        xpath, action, value = self._process_args()

        if xpath.startswith("."):
            xpath = xmlstate.make_abs_xpath(xpath)

        if action == self.ACTION_DELETE:
            setval = False
        elif action == self.ACTION_CREATE:
            setval = True
        else:
            setval = value or None
        xmlstate.xmlapi.set_xpath_content(xpath, setval)


class _XMLPropertyCache(object):
    """
    Cache lookup tables mapping classes to their associated
    XMLProperty and XMLChildProperty classes
    """
    def __init__(self):
        self._name_to_prop = {}
        self._prop_to_name = {}

    def _get_prop_cache(self, cls, checkclass):
        cachename = str(cls) + "-" + checkclass.__name__
        if cachename not in self._name_to_prop:
            ret = {}
            for c in reversed(type.mro(cls)[:-1]):
                for key, val in c.__dict__.items():
                    if isinstance(val, checkclass):
                        ret[key] = val
                        self._prop_to_name[val] = key
            self._name_to_prop[cachename] = ret
        return self._name_to_prop[cachename]

    def get_xml_props(self, inst):
        return self._get_prop_cache(inst.__class__, XMLProperty)

    def get_child_props(self, inst):
        return self._get_prop_cache(inst.__class__, XMLChildProperty)

    def get_prop_name(self, propinst):
        return self._prop_to_name[propinst]


_PropCache = _XMLPropertyCache()


class _XMLChildList(list):
    """
    Little wrapper for a list containing XMLChildProperty output.
    This is just to insert a dynamically created add_new() function
    which instantiates and appends a new child object
    """
    def __init__(self, childclass, copylist, xmlbuilder, is_xml=True):
        list.__init__(self)
        self._childclass = childclass
        self._xmlbuilder = xmlbuilder
        self._is_xml = is_xml
        for i in copylist:
            self.append(i)

    def new(self):
        """
        Instantiate a new child object and return it
        """
        args = ()
        if self._is_xml:
            args = (self._xmlbuilder.conn,)
        return self._childclass(*args)

    def add_new(self):
        """
        Instantiate a new child object, append it, and return it
        """
        obj = self.new()
        if self._is_xml:
            self._xmlbuilder.add_child(obj)
        else:
            self.append(obj)
        return obj


class _XMLPropertyBase(property):
    def __init__(self, fget, fset):
        self._propname = None
        property.__init__(self, fget=fget, fset=fset)

    @property
    def propname(self):
        """
        The variable name associated with this XMLProperty. So with
        a definition like

            foo = XMLProperty("./@bar")

        and this will return "foo".
        """
        if not self._propname:
            self._propname = _PropCache.get_prop_name(self)
        return self._propname


class XMLChildProperty(_XMLPropertyBase):
    """
    Property that points to a class used for parsing a subsection of
    of the parent XML. For example when we deligate parsing
    /domain/cpu/feature of the /domain/cpu class.

    @child_class: XMLBuilder class this property is tracking. So for
        guest.devices.disk this is DeviceDisk
    @relative_xpath: Relative location where the class is rooted compared
        to its xmlbuilder root path. So if xmlbuilder is ./foo and we
        want to track ./foo/bar/baz instances, set relative_xpath=./bar
    @is_single: If True, this represents an XML node that is only expected
        to appear once, like <domain><cpu>
    """
    def __init__(self, child_class, relative_xpath=".", is_single=False):
        self.child_class = child_class
        self.is_single = is_single
        self.relative_xpath = relative_xpath

        _XMLPropertyBase.__init__(self, self._fget, None)

    def __repr__(self):
        return "<XMLChildProperty %s %s>" % (str(self.child_class), id(self))


    def _get(self, xmlbuilder):
        if self.propname not in xmlbuilder._propstore and not self.is_single:
            xmlbuilder._propstore[self.propname] = []
        return xmlbuilder._propstore[self.propname]

    def _fget(self, xmlbuilder):
        if self.is_single:
            return self._get(xmlbuilder)
        return _XMLChildList(self.child_class,
                             self._get(xmlbuilder),
                             xmlbuilder)

    def clear(self, xmlbuilder):
        if self.is_single:
            self._get(xmlbuilder).clear()
        else:
            for obj in self._get(xmlbuilder)[:]:
                xmlbuilder.remove_child(obj)

    def insert(self, xmlbuilder, newobj, idx):
        self._get(xmlbuilder).insert(idx, newobj)
    def append(self, xmlbuilder, newobj):
        self._get(xmlbuilder).append(newobj)
    def remove(self, xmlbuilder, obj):
        self._get(xmlbuilder).remove(obj)
    def set(self, xmlbuilder, obj):
        xmlbuilder._propstore[self.propname] = obj

    def get_prop_xpath(self, _xmlbuilder, obj):
        return self.relative_xpath + "/" + obj.XML_NAME


class XMLProperty(_XMLPropertyBase):
    def __init__(self, xpath,
                 is_bool=False, is_int=False, is_yesno=False, is_onoff=False,
                 do_abspath=False):
        """
        Set a XMLBuilder class property that maps to a value in an XML
        document, indicated by the passed xpath. For example, for a
        <domain><name> the definition may look like:

          name = XMLProperty("./name")

        When building XML from scratch (virt-install), 'name' works
        similar to a regular class property(). When parsing and editing
        existing guest XML, we  use the xpath value to get/set the value
        in the parsed XML document.

        :param xpath: xpath string which maps to the associated property
                      in a typical XML document
        :param name: Just a string to print for debugging, only needed
            if xpath isn't specified.
        :param is_bool: Whether this is a boolean property in the XML
        :param is_int: Whether this is an integer property in the XML
        :param is_yesno: Whether this is a yes/no property in the XML
        :param is_onoff: Whether this is an on/off property in the XML
        :param do_abspath: If True, run os.path.abspath on the passed value
        """
        self._xpath = xpath
        if not self._xpath:
            raise xmlutil.DevError("XMLProperty: xpath must be passed.")

        self._is_bool = is_bool
        self._is_int = is_int
        self._is_yesno = is_yesno
        self._is_onoff = is_onoff
        self._do_abspath = do_abspath

        conflicts = sum([int(bool(i)) for i in
                [self._is_bool, self._is_int,
                 self._is_yesno, self._is_onoff]])
        if conflicts > 1:
            raise xmlutil.DevError("Conflict property converter options.")

        self._is_tracked = False
        if _trackprops:
            _allprops.append(self)

        _XMLPropertyBase.__init__(self, self.getter, self.setter)


    def __repr__(self):
        return "<XMLProperty %s %s>" % (str(self._xpath), id(self))


    ####################
    # Internal helpers #
    ####################

    def _convert_get_value(self, val):
        # pylint: disable=redefined-variable-type
        if self._is_bool:
            return bool(val)
        elif self._is_int and val is not None:
            try:
                intkwargs = {}
                if "0x" in str(val):
                    intkwargs["base"] = 16
                ret = int(val, **intkwargs)
            except ValueError as e:
                log.debug("Error converting XML value to int: %s", e)
                ret = val
        elif self._is_yesno:
            if val == "yes":
                ret = True
            elif val == "no":
                ret = False
            else:
                ret = val
        elif self._is_onoff:
            if val == "on":
                ret = True
            elif val == "off":
                ret = False
            else:
                ret = val
        else:
            ret = val
        return ret

    def _convert_set_value(self, val):
        if self._do_abspath and val is not None:
            val = os.path.abspath(val)
        elif self._is_onoff:
            if val is True:
                val = "on"
            elif val is False:
                val = "off"
        elif self._is_yesno:
            if val is True:
                val = "yes"
            elif val is False:
                val = "no"
        elif self._is_int and val is not None:
            intkwargs = {}
            if "0x" in str(val):
                intkwargs["base"] = 16
            val = int(val, **intkwargs)
        return val

    def _nonxml_fset(self, xmlbuilder, val):
        """
        This stores the value in XMLBuilder._propstore
        dict as propname->value. This saves us from having to explicitly
        track every variable.
        """
        propstore = xmlbuilder._propstore

        if self.propname in propstore:
            del(propstore[self.propname])
        propstore[self.propname] = val

    def _nonxml_fget(self, xmlbuilder):
        """
        The flip side to nonxml_fset, fetch the value from
        XMLBuilder._propstore
        """
        return xmlbuilder._propstore.get(self.propname, None)

    def clear(self, xmlbuilder):
        # We only unset the cached data, since XML will be cleared elsewhere
        propstore = xmlbuilder._propstore
        if self.propname in propstore:
            self.setter(xmlbuilder, None)


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
        if _trackprops and not self._is_tracked:
            _seenprops.append(self)
            self._is_tracked = True

        if self.propname in xmlbuilder._propstore:
            val = self._nonxml_fget(xmlbuilder)
        else:
            val = self._get_xml(xmlbuilder)
        return self._convert_get_value(val)

    def _get_xml(self, xmlbuilder):
        """
        Actually fetch the associated value from the backing XML
        """
        xpath = xmlbuilder._xmlstate.make_abs_xpath(self._xpath)
        return xmlbuilder._xmlstate.xmlapi.get_xpath_content(
                xpath, self._is_bool)

    def setter(self, xmlbuilder, val):
        """
        Set the value at user request. This just stores the value
        in propstore. Setting the actual XML is only done at
        get_xml time.
        """
        if _trackprops and not self._is_tracked:
            _seenprops.append(self)
            self._is_tracked = True

        setval = self._convert_set_value(val)
        self._nonxml_fset(xmlbuilder, setval)

    def _set_xml(self, xmlbuilder, setval):
        """
        Actually set the passed value in the XML document
        """
        xpath = xmlbuilder._xmlstate.make_abs_xpath(self._xpath)
        xmlbuilder._xmlstate.xmlapi.set_xpath_content(xpath, setval)


class _XMLState(object):
    def __init__(self, root_name, parsexml, parentxmlstate,
                 relative_object_xpath):
        self._root_name = root_name
        self._namespace = ""
        if ":" in self._root_name:
            ns = self._root_name.split(":")[0]
            self._namespace = " xmlns:%s='%s'" % (ns, XMLAPI.NAMESPACES[ns])

        # xpath of this object relative to its parent. So for a standalone
        # <disk> this is empty, but if the disk is the forth one in a <domain>
        # it will be set to ./devices/disk[4]
        self._relative_object_xpath = relative_object_xpath or ""

        # xpath of the parent. For a disk in a standalone <domain>, this
        # is empty, but if the <domain> is part of a <domainsnapshot>,
        # it will be "./domain"
        self._parent_xpath = (
            parentxmlstate and parentxmlstate.abs_xpath()) or ""

        self.xmlapi = None
        self.is_build = not parsexml and not parentxmlstate
        self.parse(parsexml, parentxmlstate)

    def parse(self, parsexml, parentxmlstate):
        if parentxmlstate:
            self.is_build = parentxmlstate.is_build or self.is_build
            self.xmlapi = parentxmlstate.xmlapi
            return

        # Make sure passed in XML has required xmlns inserted
        if not parsexml:
            parsexml = "<%s%s/>" % (self._root_name, self._namespace)
        elif self._namespace and "xmlns" not in parsexml:
            parsexml = parsexml.replace("<" + self._root_name,
                    "<" + self._root_name + self._namespace)

        try:
            self.xmlapi = XMLAPI(parsexml)
        except Exception:
            log.debug("Error parsing xml=\n%s", parsexml)
            raise

        if not self.is_build:
            # Ensure parsexml has the correct root node
            self.xmlapi.validate_root_name(self._root_name.split(":")[-1])

    def set_relative_object_xpath(self, xpath):
        self._relative_object_xpath = xpath or ""

    def set_parent_xpath(self, xpath):
        self._parent_xpath = xpath or ""

    def _join_xpath(self, x1, x2):
        if x2.startswith("."):
            x2 = x2[1:]
        return x1 + x2

    def abs_xpath(self):
        return self._join_xpath(self._parent_xpath or ".",
                self._relative_object_xpath or ".")

    def make_abs_xpath(self, xpath):
        """
        Convert a relative xpath to an absolute xpath. So for DeviceDisk
        that's part of a Guest, accessing driver_name will do convert:
            ./driver/@name
        to an absolute xpath like:
            ./devices/disk[3]/driver/@name
        """
        return self._join_xpath(self.abs_xpath() or ".", xpath)


class XMLBuilder(object):
    """
    Base for all classes which build or parse domain XML
    """
    # Order that we should apply values to the XML. Keeps XML generation
    # consistent with what the test suite expects.
    _XML_PROP_ORDER = []

    # Name of the root XML element
    XML_NAME = None

    # In some cases, libvirt can incorrectly generate unparsable XML.
    # These are libvirt bugs, but this allows us to work around it in
    # for specific XML classes.
    #
    # Example: nodedev 'system' XML:
    # https://bugzilla.redhat.com/show_bug.cgi?id=1184131
    _XML_SANITIZE = False

    @staticmethod
    def register_namespace(nsname, uri):
        XMLAPI.register_namespace(nsname, uri)

    @staticmethod
    def validate_generic_name(name_label, val):
        # Rather than try and match libvirt's regex, just forbid things we
        # know don't work
        forbid = [" "]
        if not val:
            # translators: value is a generic object type name
            raise ValueError(_("A name must be specified for the %s") %
                    name_label)
        for c in forbid:
            if c not in val:
                continue
            msg = (_("%(objecttype)s name '%(name)s' can not contain "
                    "'%(char)s' character.") %
                    {"objecttype": name_label, "name": val, "char": c})
            raise ValueError(msg)


    def __init__(self, conn, parsexml=None,
                 parentxmlstate=None, relative_object_xpath=None):
        """
        Initialize state

        :param conn: VirtinstConnection to validate device against
        :param parsexml: Optional XML string to parse

        The rest of the parameters are for internal use only
        """
        self.conn = conn

        if self._XML_SANITIZE:
            parsexml = parsexml.encode("ascii", "ignore").decode("ascii")
            parsexml = "".join([c for c in parsexml if c in string.printable])

        self._propstore = collections.OrderedDict()
        self._xmlstate = _XMLState(self.XML_NAME,
                                   parsexml, parentxmlstate,
                                   relative_object_xpath)

        self._validate_xmlbuilder()
        self._initial_child_parse()
        self.xml_actions = _XMLChildList(
                XMLManualAction, [], self, is_xml=False)

    def _validate_xmlbuilder(self):
        # This is one time validation we run once per XMLBuilder class
        cachekey = self.__class__.__name__ + "_xmlbuilder_validated"
        if getattr(self.__class__, cachekey, False):
            return

        xmlprops = self._all_xml_props()
        childprops = self._all_child_props()
        for key in self._XML_PROP_ORDER:
            if key not in xmlprops and key not in childprops:
                raise xmlutil.DevError(
                        "key '%s' must be xml prop or child prop" % key)

        childclasses = []
        for childprop in childprops.values():
            if childprop.child_class in childclasses:
                raise xmlutil.DevError(
                        "can't register duplicate child_class=%s" %
                        childprop.child_class)
            childclasses.append(childprop.child_class)

        setattr(self.__class__, cachekey, True)

    def _initial_child_parse(self):
        # Walk the XML tree and hand of parsing to any registered
        # child classes
        for xmlprop in list(self._all_child_props().values()):
            child_class = xmlprop.child_class
            prop_path = xmlprop.get_prop_xpath(self, child_class)

            if xmlprop.is_single:
                obj = child_class(self.conn,
                    parentxmlstate=self._xmlstate,
                    relative_object_xpath=prop_path)
                xmlprop.set(self, obj)
                continue

            nodecount = self._xmlstate.xmlapi.count(
                self._xmlstate.make_abs_xpath(prop_path))
            for idx in range(nodecount):
                idxstr = "[%d]" % (idx + 1)
                obj = child_class(self.conn,
                    parentxmlstate=self._xmlstate,
                    relative_object_xpath=(prop_path + idxstr))
                xmlprop.append(self, obj)

    def __repr__(self):
        return "<%s %s %s>" % (self.__class__.__name__.split(".")[-1],
                               self.XML_NAME, id(self))


    ############################
    # Public XML managing APIs #
    ############################

    def get_xml(self):
        """
        Return XML string of the object
        """
        xmlapi = self._xmlstate.xmlapi
        if self._xmlstate.is_build:
            xmlapi = xmlapi.copy_api()

        self._add_parse_bits(xmlapi)
        ret = xmlapi.get_xml(self._xmlstate.make_abs_xpath("."))

        if not ret:
            return ret

        lastline = ret.rstrip().splitlines()[-1]
        if not ret.startswith(" ") and lastline.startswith(" "):
            ret = lastline.split("<")[0] + ret

        if not ret.endswith("\n"):
            ret += "\n"
        return ret

    def clear(self, leave_stub=False):
        """
        Wipe out all properties of the object

        :param leave_stub: if True, don't unlink the top stub node,
            see virtinst/cli usage for an explanation
        """
        props = list(self._all_xml_props().values())
        props += list(self._all_child_props().values())
        for prop in props:
            prop.clear(self)

        is_child = bool(re.match(r"^.*\[\d+\]$", self._xmlstate.abs_xpath()))
        if is_child or leave_stub:
            # User requested to clear an object that is the child of
            # another object (xpath ends in [1] etc). We can't fully remove
            # the node in that case, since then the xmlbuilder object is
            # no longer valid, and all the other child xpaths will be
            # pointing to the wrong node. So just stub out the content
            self._xmlstate.xmlapi.node_clear(self._xmlstate.abs_xpath())
        else:
            self._xmlstate.xmlapi.node_force_remove(self._xmlstate.abs_xpath())

    def validate(self):
        """
        Validate any set values and raise an exception if there's
        a problem
        """

    def set_defaults(self, guest):
        """
        Encode any default values if needed
        """
        ignore = guest

    def get_xml_id(self):
        """
        Return the location of the object in the XML document. This is
        basically the absolute xpath, but the value returned should be
        treated as opaque, it's just for cross XML comparisons. Used
        in virt-manager code
        """
        return self._xmlstate.abs_xpath()

    def get_xml_idx(self):
        """
        This is basically the offset parsed out of the object's xpath,
        minus 1. So if this is the fifth <disk> in a <domain>, ret=4.
        If this is the only <cpu> in a domain, ret=0.
        """
        xpath = self._xmlstate.abs_xpath()
        if "[" not in xpath:
            return 0
        return int(xpath.rsplit("[", 1)[1].strip("]")) - 1


    ################
    # Internal API #
    ################

    def _all_xml_props(self):
        """
        Return a list of all XMLProperty instances that this class has.
        """
        return _PropCache.get_xml_props(self)

    def _all_child_props(self):
        """
        Return a list of all XMLChildProperty instances that this class has.
        """
        return _PropCache.get_child_props(self)

    def _find_child_prop(self, child_class):
        xmlprops = self._all_child_props()
        ret = None
        for xmlprop in list(xmlprops.values()):
            if xmlprop.is_single:
                continue
            if child_class is xmlprop.child_class:
                ret = xmlprop
                break
        if not ret:
            raise xmlutil.DevError(
                "Didn't find child property for child_class=%s" % child_class)
        return ret

    def _set_xpaths(self, parent_xpath, relative_object_xpath=-1):
        """
        Change the object hierarchy's cached xpaths
        """
        self._xmlstate.set_parent_xpath(parent_xpath)
        if relative_object_xpath != -1:
            self._xmlstate.set_relative_object_xpath(relative_object_xpath)
        for propname in self._all_child_props():
            for p in xmlutil.listify(getattr(self, propname, [])):
                p._set_xpaths(self._xmlstate.abs_xpath())

    def _set_child_xpaths(self):
        """
        Walk the list of child properties and make sure their
        xpaths point at their particular element. Needs to be called
        whenever child objects are added or removed
        """
        typecount = {}
        for propname, xmlprop in self._all_child_props().items():
            for obj in xmlutil.listify(getattr(self, propname)):
                idxstr = ""
                if not xmlprop.is_single:
                    class_type = obj.__class__
                    if class_type not in typecount:
                        typecount[class_type] = 0
                    typecount[class_type] += 1
                    idxstr = "[%d]" % typecount[class_type]

                prop_path = xmlprop.get_prop_xpath(self, obj)
                obj._set_xpaths(self._xmlstate.abs_xpath(),
                        prop_path + idxstr)

    def _parse_with_children(self, *args, **kwargs):
        """
        Set new backing XML objects in ourselves and all our child props
        """
        self._xmlstate.parse(*args, **kwargs)
        for propname in self._all_child_props():
            for p in xmlutil.listify(getattr(self, propname, [])):
                p._parse_with_children(None, self._xmlstate)

    def add_child(self, obj, idx=None):
        """
        Insert the passed XMLBuilder object into our XML document. The
        object needs to have an associated mapping via XMLChildProperty
        """
        xmlprop = self._find_child_prop(obj.__class__)
        xml = obj.get_xml()
        if idx is None:
            xmlprop.append(self, obj)
        else:
            xmlprop.insert(self, obj, idx)
        self._set_child_xpaths()

        # Only insert the XML directly into the parent XML for !is_build
        # This is the only way to dictate XML ordering when building
        # from scratch, otherwise elements appear in the order they
        # are set. It's just a style issue but annoying nonetheless
        if not obj._xmlstate.is_build:
            use_xpath = obj._xmlstate.abs_xpath().rsplit("/", 1)[0]
            indent = 2 * obj._xmlstate.abs_xpath().count("/")
            self._xmlstate.xmlapi.node_add_xml(
                    textwrap.indent(xml, indent * " "), use_xpath)
        obj._parse_with_children(None, self._xmlstate)

    def remove_child(self, obj):
        """
        Remove the passed XMLBuilder object from our XML document, but
        ensure its data isn't altered.
        """
        xmlprop = self._find_child_prop(obj.__class__)
        xmlprop.remove(self, obj)

        xpath = obj._xmlstate.abs_xpath()
        xml = obj.get_xml()
        obj._set_xpaths(None, None)
        obj._parse_with_children(xml, None)
        self._xmlstate.xmlapi.node_force_remove(xpath)
        self._set_child_xpaths()

    def replace_child(self, origobj, newobj):
        """
        Replace the origobj child with the newobj. For is_build, this
        replaces the objects, but for !is_build this only replaces the
        XML and keeps the object references in place. This is hacky and
        it's fixable but at time or writing it doesn't matter for
        our usecases.
        """
        if not self._xmlstate.is_build:
            xpath = origobj.get_xml_id()
            indent = 2 * xpath.count("/")
            xml = textwrap.indent(newobj.get_xml(), indent * " ").strip()
            self._xmlstate.xmlapi.node_replace_xml(xpath, xml)
        else:
            origidx = origobj.get_xml_idx()
            self.remove_child(origobj)
            self.add_child(newobj, idx=origidx)

    def _prop_is_unset(self, propname):
        """
        Return True if the property name has never had a value set
        """
        if getattr(self, propname):
            return False
        return propname not in self._propstore


    #################################
    # Private XML building routines #
    #################################

    def _add_parse_bits(self, xmlapi):
        """
        Callback that adds the implicitly tracked XML properties to
        the backing xml.
        """
        origpropstore = self._propstore.copy()
        origapi = self._xmlstate.xmlapi
        try:
            self._xmlstate.xmlapi = xmlapi
            return self._do_add_parse_bits()
        finally:
            self._xmlstate.xmlapi = origapi
            self._propstore = origpropstore

    def _do_add_parse_bits(self):
        # Set all defaults if the properties have one registered
        xmlprops = self._all_xml_props()
        childprops = self._all_child_props()

        # Set up preferred XML ordering
        do_order = [p for p in self._propstore if p not in childprops]
        for key in reversed(self._XML_PROP_ORDER):
            if key in do_order:
                do_order.remove(key)
                do_order.insert(0, key)
            elif key in childprops:
                do_order.insert(0, key)

        for key in sorted(list(childprops.keys())):
            if key not in do_order:
                do_order.append(key)

        # Alter the XML
        for key in do_order:
            if key in xmlprops:
                xmlprops[key]._set_xml(self, self._propstore[key])
            elif key in childprops:
                for obj in xmlutil.listify(getattr(self, key)):
                    obj._add_parse_bits(self._xmlstate.xmlapi)

        for manualaction in self.xml_actions:
            manualaction.perform(self._xmlstate)

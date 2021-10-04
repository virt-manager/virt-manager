# Copyright (C) 2010, 2013 Red Hat, Inc.
# Copyright (C) 2010 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from virtinst import log
from virtinst import xmlutil

from ..baseclass import vmmGObject


class vmmLibvirtObject(vmmGObject):
    __gsignals__ = {
        "state-changed": (vmmGObject.RUN_FIRST, None, []),
        "initialized": (vmmGObject.RUN_FIRST, None, [bool]),
    }

    _STATUS_ACTIVE = 1
    _STATUS_INACTIVE = 2

    def __init__(self, conn, backend, name, parseclass):
        vmmGObject.__init__(self)
        self._conn = conn
        self._backend = backend
        self._parseclass = parseclass
        self._name = name

        self.__initialized = False
        self.__status = None

        self._xmlobj = None
        self._xmlobj_to_define = None
        self._is_xml_valid = False

        # These should be set by the child classes if necessary
        self._inactive_xml_flags = 0
        self._active_xml_flags = 0

    @staticmethod
    def log_redefine_xml_diff(obj, origxml, newxml):
        if origxml == newxml:
            log.debug("Redefine requested for %s, but XML didn't change!",
                          obj)
            return

        diff = xmlutil.diff(origxml, newxml, "Original XML", "New XML")
        log.debug("Redefining %s with XML diff:\n%s", obj, diff)

    @staticmethod
    def lifecycle_action(fn):
        """
        Decorator for object lifecycle actions like start, stop, delete.
        Will make sure any necessary state is updated accordingly.
        """
        def newfn(self, *args, **kwargs):
            ret = fn(self, *args, **kwargs)

            # If events are supported, this is a no-op, but the event loop
            # will trigger force_status_update, which will refresh_xml as well.
            #
            # If events aren't supported, the priority tick will call
            # self.tick(), which will call force_status_update
            poll_param = self._conn_tick_poll_param()  # pylint: disable=protected-access
            tick_kwargs = {poll_param: True}
            self.conn.schedule_priority_tick(**tick_kwargs)

            return ret
        return newfn

    def __repr__(self):
        # pylint: disable=arguments-differ
        try:
            name = self.get_name()
        except Exception:
            name = ""
        return "<%s name=%s id=%s>" % (
                self.__class__.__name__, name, hex(id(self)))

    def _cleanup(self):
        self._backend = None

    def _get_conn(self):
        return self._conn
    conn = property(_get_conn)

    def get_backend(self):
        return self._backend

    def is_domain(self):
        return self.class_name() == "domain"
    def is_network(self):
        return self.class_name() == "network"
    def is_pool(self):
        return self.class_name() == "pool"
    def is_nodedev(self):
        return self.class_name() == "nodedev"

    def get_autostart(self):  # pragma: no cover
        return False
    def set_autostart(self, val):  # pragma: no cover
        ignore = val

    def change_name_backend(self, newbackend):
        # Used for changing the backing object after a rename
        self._backend = newbackend

    def define_name(self, newname):
        oldname = self.get_xmlobj().name
        oldautostart = self.get_autostart()

        self.ensure_latest_xml()
        xmlobj = self._make_xmlobj_to_define()
        if xmlobj.name == newname:
            return  # pragma: no cover

        log.debug("Changing %s name from %s to %s",
                      self, oldname, newname)
        origxml = xmlobj.get_xml()
        xmlobj.name = newname
        newxml = xmlobj.get_xml()

        try:
            self._name = newname
            self.conn.rename_object(self, origxml, newxml)
        except Exception:  # pragma: no cover
            self._name = oldname
            raise
        finally:
            self.__force_refresh_xml()

        self.set_autostart(oldautostart)


    #############################################################
    # Functions that should probably be overridden in sub class #
    #############################################################

    def _XMLDesc(self, flags):
        raise NotImplementedError()
    def class_name(self):
        raise NotImplementedError()
    def _conn_tick_poll_param(self):
        # The parameter name for conn.tick() object polling. So
        # for vmmDomain == "pollvm"
        raise NotImplementedError()

    def reports_stats(self):
        return False
    def _using_events(self):
        return False
    def _get_backend_status(self):
        raise NotImplementedError()

    def _define(self, xml):  # pragma: no cover
        ignore = xml
        return

    def delete(self, force=True):  # pragma: no cover
        ignore = force

    def get_name(self):
        return self._name

    def tick(self, stats_update=True):
        ignore = stats_update
        self._refresh_status()

    def _init_libvirt_state(self):
        self.tick()

    def init_libvirt_state(self):
        """
        Function called by vmmConnection to populate initial state when
        a new object appears.
        """
        if self.__initialized:
            return  # pragma: no cover

        initialize_failed = False
        try:
            if self.config.CLITestOptions.object_denylist == self._name:
                raise RuntimeError("fake initialization error")

            self._init_libvirt_state()
        except Exception:  # pragma: no cover
            log.debug("Error initializing libvirt state for %s", self,
                exc_info=True)
            initialize_failed = True

        self.__initialized = True
        self.idle_emit("initialized", initialize_failed)


    ###################
    # Status handling #
    ###################

    def _get_status(self):
        return self.__status

    def is_active(self):
        # vmmDomain overwrites this since it has more fine grained statuses
        return self._get_status() == self._STATUS_ACTIVE

    def run_status(self):
        if self.is_active():
            return _("Active")
        return _("Inactive")

    def _refresh_status(self, newstatus=None, cansignal=True):
        """
        Grab the object status/active state from libvirt, and if the
        status has changed, update the XML cache. Typically called from
        object tick functions for manually updating the object state.

        :param newstatus: Used by vmmDomain as a small optimization to
            avoid polling info() twice
        :param cansignal: If True, this function will signal state-changed
            if required.
        :returns: True if status changed, false otherwise
        """
        if (self._using_events() and
            self.__status is not None):
            return False

        if newstatus is None:
            newstatus = self._get_backend_status()
        status = newstatus
        if status == self.__status:
            return False
        self.__status = status

        self.ensure_latest_xml(nosignal=True)
        if cansignal:
            self.idle_emit("state-changed")
        return True


    ##################
    # Public XML API #
    ##################

    def recache_from_event_loop(self):
        """
        Updates the VM status and XML, because we received an event from
        libvirt's event implementations. That's the only time this should
        be used.

        We refresh status and XML because they are tied together in subtle
        ways, like runtime XML changing when a VM is started.
        """
        try:
            self.__force_refresh_xml(nosignal=True)
            # status = None forces a signal to be emitted
            self.__status = None
            self._refresh_status()
        except Exception as e:
            # If we hit an exception here, it's often that the object
            # disappeared, so request the poll loop to be updated
            log.debug("Error refreshing %s from events: %s", self, e)
            poll_param = self._conn_tick_poll_param()
            if poll_param:
                kwargs = {"force": True, poll_param: True}
                log.debug("Scheduling priority tick with: %s", kwargs)
                self.conn.schedule_priority_tick(**kwargs)

    def ensure_latest_xml(self, nosignal=False):
        """
        Refresh XML if it isn't up to date, basically if we aren't using
        events.
        """
        if (self._using_events() and
            self._xmlobj and
            self._is_xml_valid):
            return
        self.__force_refresh_xml(nosignal=nosignal)

    def __force_refresh_xml(self, nosignal=False):
        """
        Force an xml update. Signal 'state-changed' if domain xml has
        changed since last refresh

        :param nosignal: If true, don't send state-changed. Used by
            callers that are going to send it anyways.
        """
        origxml = None
        if self._xmlobj:
            origxml = self._xmlobj.get_xml()

        self._invalidate_xml()
        active_xml = self._XMLDesc(self._active_xml_flags)
        self._xmlobj = self._parseclass(self.conn.get_backend(),
            parsexml=active_xml)
        self._is_xml_valid = True

        if not nosignal and origxml != active_xml:
            self.idle_emit("state-changed")

    def get_xmlobj(self, inactive=False, refresh_if_nec=True):
        """
        Get object xml, return it wrapped in a virtinst object.
        If cached xml is invalid, update.

        :param inactive: Return persistent XML, not the running config.
            No effect if domain is not running. Use this flag
            if the XML will be used for redefining a guest
        :param refresh_if_nec: Check if XML is out of date, and if so,
            refresh it (default behavior). Skipping a refresh is
            useful to prevent updating xml in the tick loop when
            it's not that important (disk/net stats)
        """
        if inactive:
            # If inactive XML requested, always return a fresh object even if
            # the current object is inactive XML (like when the domain is
            # stopped). Callers that request inactive are basically expecting
            # a new copy.
            inactive_xml = self._XMLDesc(self._inactive_xml_flags)
            return self._parseclass(self.conn.get_backend(),
                parsexml=inactive_xml)

        if (self._xmlobj is None or
            (refresh_if_nec and not self._is_xml_valid)):
            self.ensure_latest_xml()

        return self._xmlobj

    @property
    def xmlobj(self):
        return self.get_xmlobj()

    def get_xml_to_define(self):
        """
        Return the raw inactive XML we would use to alter/define an
        object. Used by the xmleditor UI
        """
        return self._make_xmlobj_to_define().get_xml()

    def define_xml(self, xml):
        """
        Define the passed in XML, and log a diff against the current XML.
        Generally subclasses should use _redefine_xmlobj with higher
        level wrappers, but this is needed for the XML editor
        """
        origxml = self.get_xml_to_define()
        newxml = xml
        self._redefine_xml_internal(origxml, newxml)


    #########################
    # Internal XML routines #
    #########################

    def _invalidate_xml(self):
        """
        Mark cached XML as invalid. Subclasses may extend this
        to invalidate any specific caches of their own
        """
        # While for events we do want to clear cached XML values like
        # _name, the XML is never invalid.
        self._is_xml_valid = self._using_events()

    def _make_xmlobj_to_define(self):
        """
        Build an xmlobj that should be used for defining new XML.

        Most subclasses shouldn't touch this, but vmmDomainVirtinst needs to.
        """
        return self.get_xmlobj(inactive=True)

    def _redefine_xml_internal(self, origxml, newxml):
        self.log_redefine_xml_diff(self, origxml, newxml)

        self._define(newxml)
        if self._using_events():
            return

        self.ensure_latest_xml(nosignal=True)
        self.idle_emit("state-changed")

    def _redefine_xmlobj(self, xmlobj):
        """
        Redefine the passed xmlobj, which should be generated with
        self._make_xmlobj_to_define() and which has accumulated edits
        from UI fields.

        Most subclasses shouldn't alter this, but vmmDomainVirtinst needs to.
        """
        origxml = self._make_xmlobj_to_define().get_xml()
        newxml = xmlobj.get_xml()
        self._redefine_xml_internal(origxml, newxml)

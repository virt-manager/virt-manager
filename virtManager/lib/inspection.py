# Copyright (C) 2011, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import queue
import threading

from virtinst import log

from ..baseclass import vmmGObject
from ..connmanager import vmmConnectionManager
from ..object.domain import vmmInspectionApplication, vmmInspectionData


def _inspection_error(_errstr):
    data = vmmInspectionData()
    data.errorstr = _errstr
    return data


def _make_fake_data(vm):
    """
    Return fake vmmInspectionData for use with the test driver
    """
    if not vm.xmlobj.devices.disk:
        return _inspection_error("Fake test error no disks")

    data = vmmInspectionData()
    data.os_type = "test_os_type"
    data.distro = "test_distro"
    data.major_version = 123
    data.minor_version = 456
    data.hostname = "test_hostname"
    data.product_name = "test_product_name"
    data.product_variant = "test_product_variant"

    from gi.repository import Gtk
    icontheme = Gtk.IconTheme.get_default()
    icon = icontheme.lookup_icon("vm_new", Gtk.IconSize.LARGE_TOOLBAR, 0)
    data.icon = open(icon.get_filename(), "rb").read()

    data.applications = []
    for prefix in ["test_app1_", "test_app2_"]:
        import time
        app = vmmInspectionApplication()
        if "app1" in prefix:
            app.display_name = prefix + "display_name"
            app.summary = prefix + "summary-" + str(time.time())
        else:
            app.name = prefix + "name"
            app.description = prefix + "description-" + str(time.time()) + "\n"
        app.epoch = 1
        app.version = "2"
        app.release = "3"
        data.applications.append(app)

    return data


def _perform_inspection(conn, vm):  # pragma: no cover
    """
    Perform the actual guestfs interaction and return results in
    a vmmInspectionData object
    """
    import guestfs  # pylint: disable=import-error

    g = guestfs.GuestFS(close_on_exit=False, python_return_dict=True)
    prettyvm = conn.get_uri() + ":" + vm.get_name()
    try:
        g.add_libvirt_dom(vm.get_backend(), readonly=1)
        g.launch()
    except Exception as e:
        log.debug("%s: Error launching libguestfs appliance: %s",
                prettyvm, str(e))
        return _inspection_error(
                _("Error launching libguestfs appliance: %s") % str(e))

    log.debug("%s: inspection appliance connected", prettyvm)

    # Inspect the operating system.
    roots = g.inspect_os()
    if len(roots) == 0:
        log.debug("%s: no operating systems found", prettyvm)
        return _inspection_error(
                _("Inspection found no operating systems."))

    # Arbitrarily pick the first root device.
    root = roots[0]

    # Inspection results.
    os_type = g.inspect_get_type(root)  # eg. "linux"
    distro = g.inspect_get_distro(root)  # eg. "fedora"
    major_version = g.inspect_get_major_version(root)  # eg. 14
    minor_version = g.inspect_get_minor_version(root)  # eg. 0
    hostname = g.inspect_get_hostname(root)  # string
    product_name = g.inspect_get_product_name(root)  # string
    product_variant = g.inspect_get_product_variant(root)  # string
    package_format = g.inspect_get_package_format(root)  # string

    # For inspect_list_applications and inspect_get_icon we
    # require that the guest filesystems are mounted.  However
    # don't fail if this is not possible (I'm looking at you,
    # FreeBSD).
    filesystems_mounted = False
    # Mount up the disks, like guestfish --ro -i.

    # Sort keys by length, shortest first, so that we end up
    # mounting the filesystems in the correct order.
    mps = g.inspect_get_mountpoints(root)

    mps = sorted(mps.items(), key=lambda k: len(k[0]))
    for mp, dev in mps:
        try:
            g.mount_ro(dev, mp)
            filesystems_mounted = True
        except Exception:
            log.exception("%s: exception mounting %s on %s "
                              "(ignored)",
                              prettyvm, dev, mp)

    icon = None
    apps = None
    if filesystems_mounted:
        # string containing PNG data
        icon = g.inspect_get_icon(root, favicon=0, highquality=1)
        if icon is None or len(icon) == 0:
            # no high quality icon, try a low quality one
            icon = g.inspect_get_icon(root, favicon=0, highquality=0)
            if icon is None or len(icon) == 0:
                icon = None

        # Inspection applications.
        try:
            gapps = g.inspect_list_applications2(root)
            # applications listing worked, so make apps a real list
            # (instead of None)
            apps = []
            for gapp in gapps:
                app = vmmInspectionApplication()
                if gapp["app2_name"]:
                    app.name = gapp["app2_name"]
                if gapp["app2_display_name"]:
                    app.display_name = gapp["app2_display_name"]
                app.epoch = gapp["app2_epoch"]
                if gapp["app2_version"]:
                    app.version = gapp["app2_version"]
                if gapp["app2_release"]:
                    app.release = gapp["app2_release"]
                if gapp["app2_summary"]:
                    app.summary = gapp["app2_summary"]
                if gapp["app2_description"]:
                    app.description = gapp["app2_description"]
                apps.append(app)
        except Exception:
            log.exception("%s: exception while listing apps (ignored)",
                              prettyvm)

    # Force the libguestfs handle to close right now.
    del g

    # Log what we found.
    log.debug("%s: detected operating system: %s %s %d.%d (%s) (%s)",
                  prettyvm, os_type, distro, major_version, minor_version,
                  product_name, package_format)
    log.debug("hostname: %s", hostname)
    if icon:
        log.debug("icon: %d bytes", len(icon))
    if apps:
        log.debug("# apps: %d", len(apps))

    data = vmmInspectionData()
    data.os_type = str(os_type)
    data.distro = str(distro)
    data.major_version = int(major_version)
    data.minor_version = int(minor_version)
    data.hostname = str(hostname)
    data.product_name = str(product_name)
    data.product_variant = str(product_variant)
    data.icon = icon
    data.applications = list(apps or [])
    data.package_format = str(package_format)

    return data


class vmmInspection(vmmGObject):
    _libguestfs_installed = None

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            if not cls.libguestfs_installed():
                return None  # pragma: no cover
            cls._instance = vmmInspection()
        return cls._instance

    @classmethod
    def libguestfs_installed(cls):
        if cls._libguestfs_installed is None:
            try:
                import guestfs as ignore  # pylint: disable=import-error
                log.debug("python guestfs is installed")
                cls._libguestfs_installed = True
            except ImportError:  # pragma: no cover
                log.debug("python guestfs is not installed")
                cls._libguestfs_installed = False
            except Exception:  # pragma: no cover
                log.debug("error importing guestfs",
                        exc_info=True)
                cls._libguestfs_installed = False
        return cls._libguestfs_installed

    def __init__(self):
        vmmGObject.__init__(self)
        self._cleanup_on_app_close()

        self._thread = None

        self._q = queue.Queue()
        self._cached_data = {}
        self._uris = []

        val = self.config.get_libguestfs_inspect_vms()
        log.debug("libguestfs gsetting enabled=%s", str(val))
        if not val:
            return

        connmanager = vmmConnectionManager.get_instance()
        connmanager.connect("conn-added", self._conn_added_cb)
        connmanager.connect("conn-removed", self._conn_removed_cb)
        for conn in connmanager.conns.values():
            self._conn_added_cb(connmanager, conn)  # pragma: no cover

        self._start()

    def _cleanup(self):
        self._stop()
        self._q = queue.Queue()
        self._cached_data = {}

    def _conn_added_cb(self, connmanager, conn):
        uri = conn.get_uri()
        if uri in self._uris:
            return  # pragma: no cover

        self._uris.append(uri)
        conn.connect("vm-added", self._vm_added_cb)
        for vm in conn.list_vms():  # pragma: no cover
            self._vm_added_cb(conn, vm.get_name())

    def _conn_removed_cb(self, connmanager, uri):
        self._uris.remove(uri)

    def _vm_added_cb(self, conn, vm):
        # Called by the main thread whenever a VM is added to vmlist.
        name = vm.get_name()
        if name.startswith("guestfs-"):  # pragma: no cover
            log.debug("ignore libvirt/guestfs temporary VM %s", name)
            return

        self._q.put((conn.get_uri(), vm.get_name()))

    def _start(self):
        self._thread = threading.Thread(
                name="inspection thread", target=self._run)
        self._thread.daemon = True
        self._thread.start()

    def _stop(self):
        if self._thread is None:
            return

        self._q.put(None)
        self._thread = None

    def _run(self):
        # Process everything on the queue.  If the queue is empty when
        # called, block.
        while True:
            data = self._q.get()
            if data is None:
                log.debug("libguestfs queue vm=None, exiting thread")
                return
            uri, vmname = data
            self._process_vm(uri, vmname)
            self._q.task_done()

    def _process_vm(self, uri, vmname):
        connmanager = vmmConnectionManager.get_instance()
        conn = connmanager.conns.get(uri)
        if not conn:
            return  # pragma: no cover

        vm = conn.get_vm_by_name(vmname)
        if not vm:
            return  # pragma: no cover

        # Try processing a single VM, keeping into account whether it was
        # visited already, and whether there are cached data for it.
        def _set_vm_inspection_data(_data):
            vm.set_inspection_data(_data)
            self._cached_data[vm.get_uuid()] = _data

        prettyvm = conn.get_uri() + ":" + vm.get_name()
        vmuuid = vm.get_uuid()
        if vmuuid in self._cached_data:
            data = self._cached_data.get(vmuuid)
            if vm.inspection != data:
                log.debug("Found cached data for %s", prettyvm)
                _set_vm_inspection_data(data)
            return

        try:
            data = self._inspect_vm(conn, vm)
        except Exception as e:  # pragma: no cover
            data = _inspection_error(_("Error inspection VM: %s") % str(e))
            log.exception("%s: exception while processing", prettyvm)

        _set_vm_inspection_data(data)

    def _inspect_vm(self, conn, vm):
        if self._thread is None:
            return  # pragma: no cover

        if conn.is_remote():  # pragma: no cover
            return _inspection_error(
                    _("Cannot inspect VM on remote connection"))
        if conn.is_test():
            return _make_fake_data(vm)

        return _perform_inspection(conn, vm)  # pragma: no cover


    ##############
    # Public API #
    ##############

    def vm_refresh(self, vm):
        log.debug("Refresh requested for vm=%s", vm.get_name())

        # When refreshing the inspection data of a VM,
        # all we need is to remove it from the "seen" cache,
        # as the data itself will be replaced once the new
        # results are available.
        self._cached_data.pop(vm.get_uuid(), None)
        self._q.put((vm.conn.get_uri(), vm.get_name()))

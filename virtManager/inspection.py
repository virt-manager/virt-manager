# Copyright (C) 2011, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import functools
import logging
import queue
import threading

from .baseclass import vmmGObject
from .connmanager import vmmConnectionManager
from .domain import vmmInspectionData


def _inspection_error(_errstr):
    data = vmmInspectionData()
    data.errorstr = _errstr
    return data


class vmmInspection(vmmGObject):
    _libguestfs_installed = None

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            if not cls.libguestfs_installed():
                return None
            cls._instance = vmmInspection()
        return cls._instance

    @classmethod
    def libguestfs_installed(cls):
        if cls._libguestfs_installed is None:
            try:
                import guestfs as ignore  # pylint: disable=import-error
                logging.debug("python guestfs is installed")
                cls._libguestfs_installed = True
            except ImportError:
                logging.debug("python guestfs is not installed")
                cls._libguestfs_installed = False
            except Exception:
                logging.debug("error importing guestfs",
                        exc_info=True)
                cls._libguestfs_installed = False
        return cls._libguestfs_installed

    def __init__(self):
        vmmGObject.__init__(self)
        self._cleanup_on_app_close()

        self._thread = None

        self._q = queue.Queue()
        self._conns = {}
        self._cached_data = {}

        val = self.config.get_libguestfs_inspect_vms()
        logging.debug("libguestfs gsetting enabled=%s", str(val))
        if not val:
            return

        connmanager = vmmConnectionManager.get_instance()
        connmanager.connect("conn-added", self._conn_added)
        connmanager.connect("conn-removed", self._conn_removed)
        for conn in connmanager.conns.values():
            self._conn_added(connmanager, conn)

        self._start()

    def _cleanup(self):
        self._stop()
        self._q = queue.Queue()
        self._conns = {}
        self._cached_data = {}

    def _conn_added(self, _src, conn):
        obj = ("conn_added", conn)
        self._q.put(obj)

    def _conn_removed(self, _src, uri):
        obj = ("conn_removed", uri)
        self._q.put(obj)

    # Called by the main thread whenever a VM is added to vmlist.
    def _vm_added(self, conn, connkey):
        if connkey.startswith("guestfs-"):
            logging.debug("ignore libvirt/guestfs temporary VM %s",
                          connkey)
            return

        obj = ("vm_added", conn.get_uri(), connkey)
        self._q.put(obj)

    def vm_refresh(self, vm):
        logging.debug("Refresh requested for vm=%s", vm.get_name())
        obj = ("vm_refresh", vm.conn.get_uri(), vm.get_name(), vm.get_uuid())
        self._q.put(obj)

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
            obj = self._q.get()
            if obj is None:
                logging.debug("libguestfs queue obj=None, exiting thread")
                return
            self._process_queue_item(obj)
            self._q.task_done()

    def _process_queue_item(self, obj):
        cmd = obj[0]
        if cmd == "conn_added":
            conn = obj[1]
            uri = conn.get_uri()
            if uri in self._conns:
                return

            self._conns[uri] = conn
            conn.connect("vm-added", self._vm_added)
            for vm in conn.list_vms():
                self._vm_added(conn, vm.get_connkey())

        elif cmd == "conn_removed":
            uri = obj[1]
            self._conns.pop(uri)

        elif cmd == "vm_added" or cmd == "vm_refresh":
            uri = obj[1]
            if uri not in self._conns:
                # This connection disappeared in the meanwhile.
                return

            conn = self._conns[uri]
            vm = conn.get_vm(obj[2])
            if not vm:
                # The VM was removed in the meanwhile.
                return

            if cmd == "vm_refresh":
                vmuuid = obj[3]
                # When refreshing the inspection data of a VM,
                # all we need is to remove it from the "seen" cache,
                # as the data itself will be replaced once the new
                # results are available.
                self._cached_data.pop(vmuuid, None)

            self._process_vm(conn, vm)

    def _process_vm(self, conn, vm):
        # Try processing a single VM, keeping into account whether it was
        # visited already, and whether there are cached data for it.
        def _set_vm_inspection_data(_data):
            vm.inspection = _data
            vm.inspection_data_updated()
            self._cached_data[vm.get_uuid()] = _data

        prettyvm = conn.get_uri() + ":" + vm.get_name()
        vmuuid = vm.get_uuid()
        if vmuuid in self._cached_data:
            data = self._cached_data.get(vmuuid)
            if vm.inspection != data:
                logging.debug("Found cached data for %s", prettyvm)
                _set_vm_inspection_data(data)
            return

        try:
            data = self._inspect_vm(conn, vm)
        except Exception as e:
            data = _inspection_error(_("Error inspection VM: %s") % str(e))
            logging.exception("%s: exception while processing", prettyvm)

        _set_vm_inspection_data(data)

    def _inspect_vm(self, conn, vm):
        if self._thread is None:
            return

        if conn.is_remote():
            return _inspection_error(
                    _("Cannot inspect VM on remote connection"))
        if conn.is_test():
            return _inspection_error("Cannot inspect VM on test connection")

        import guestfs  # pylint: disable=import-error

        g = guestfs.GuestFS(close_on_exit=False)
        prettyvm = conn.get_uri() + ":" + vm.get_name()
        try:
            g.add_libvirt_dom(vm.get_backend(), readonly=1)
            g.launch()
        except Exception as e:
            logging.debug("%s: Error launching libguestfs appliance: %s",
                    prettyvm, str(e))
            return _inspection_error(
                    _("Error launching libguestfs appliance: %s") % str(e))

        logging.debug("%s: inspection appliance connected", prettyvm)

        # Inspect the operating system.
        roots = g.inspect_os()
        if len(roots) == 0:
            logging.debug("%s: no operating systems found", prettyvm)
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

        # For inspect_list_applications and inspect_get_icon we
        # require that the guest filesystems are mounted.  However
        # don't fail if this is not possible (I'm looking at you,
        # FreeBSD).
        filesystems_mounted = False
        try:
            # Mount up the disks, like guestfish --ro -i.

            # Sort keys by length, shortest first, so that we end up
            # mounting the filesystems in the correct order.
            mps = list(g.inspect_get_mountpoints(root))
            def compare(a, b):
                if len(a[0]) > len(b[0]):
                    return 1
                elif len(a[0]) == len(b[0]):
                    return 0
                else:
                    return -1

            mps.sort(key=functools.cmp_to_key(compare))
            for mp_dev in mps:
                try:
                    g.mount_ro(mp_dev[1], mp_dev[0])
                except Exception:
                    logging.exception("%s: exception mounting %s on %s "
                                      "(ignored)",
                                      prettyvm, mp_dev[1], mp_dev[0])

            filesystems_mounted = True
        except Exception:
            logging.exception("%s: exception while mounting disks (ignored)",
                              prettyvm)

        icon = None
        apps = None
        if filesystems_mounted:
            # string containing PNG data
            icon = g.inspect_get_icon(root, favicon=0, highquality=1)
            if icon == "" or icon is None:
                # no high quality icon, try a low quality one
                icon = g.inspect_get_icon(root, favicon=0, highquality=0)
                if icon == "":
                    icon = None

            # Inspection applications.
            apps = g.inspect_list_applications(root)

        # Force the libguestfs handle to close right now.
        del g

        # Log what we found.
        logging.debug("%s: detected operating system: %s %s %d.%d (%s)",
                      prettyvm, os_type, distro, major_version, minor_version,
                      product_name)
        logging.debug("hostname: %s", hostname)
        if icon:
            logging.debug("icon: %d bytes", len(icon))
        if apps:
            logging.debug("# apps: %d", len(apps))

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

        return data

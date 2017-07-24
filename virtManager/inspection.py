#
# Copyright (C) 2011, 2013 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
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
#

from Queue import Queue
from threading import Thread
import logging

from guestfs import GuestFS  # pylint: disable=import-error

from .baseclass import vmmGObject
from .domain import vmmInspectionData


class vmmInspection(vmmGObject):
    # Can't find a way to make Thread release our reference
    _leak_check = False

    def __init__(self):
        vmmGObject.__init__(self)

        self._thread = Thread(name="inspection thread", target=self._run)
        self._thread.daemon = True
        self._wait = 5 * 1000  # 5 seconds

        self._q = Queue()
        self._conns = {}
        self._vmseen = {}
        self._cached_data = {}

    def _cleanup(self):
        self._thread = None
        self._q = Queue()
        self._conns = {}
        self._vmseen = {}
        self._cached_data = {}

    # Called by the main thread whenever a connection is added or
    # removed.  We tell the inspection thread, so it can track
    # connections.
    def conn_added(self, engine_ignore, conn):
        obj = ("conn_added", conn)
        self._q.put(obj)

    def conn_removed(self, engine_ignore, uri):
        obj = ("conn_removed", uri)
        self._q.put(obj)

    # Called by the main thread whenever a VM is added to vmlist.
    def vm_added(self, conn, connkey):
        if connkey.startswith("guestfs-"):
            logging.debug("ignore libvirt/guestfs temporary VM %s",
                          connkey)
            return

        obj = ("vm_added", conn.get_uri(), connkey)
        self._q.put(obj)

    def vm_refresh(self, vm):
        obj = ("vm_refresh", vm.conn.get_uri(), vm.get_name(), vm.get_uuid())
        self._q.put(obj)

    def start(self):
        # Wait a few seconds before we do anything.  This prevents
        # inspection from being a burden for initial virt-manager
        # interactivity (although it shouldn't affect interactivity at
        # all).
        def cb():
            self._thread.start()
            return 0

        logging.debug("waiting")
        self.timeout_add(self._wait, cb)

    def _run(self):
        # Process everything on the queue.  If the queue is empty when
        # called, block.
        while True:
            obj = self._q.get()
            self._process_queue_item(obj)
            self._q.task_done()

    def _process_queue_item(self, obj):
        if obj[0] == "conn_added":
            conn = obj[1]
            uri = conn.get_uri()
            if conn and not (conn.is_remote()) and not (uri in self._conns):
                self._conns[uri] = conn
                conn.connect("vm-added", self.vm_added)
                # No need to push the VMs of the newly added
                # connection manually into the queue, as the above
                # connect() will emit vm-added signals for all of
                # its VMs.
        elif obj[0] == "conn_removed":
            uri = obj[1]
            del self._conns[uri]
        elif obj[0] == "vm_added" or obj[0] == "vm_refresh":
            uri = obj[1]
            if not (uri in self._conns):
                # This connection disappeared in the meanwhile.
                return
            conn = self._conns[uri]
            if not conn.is_active():
                return
            connkey = obj[2]
            vm = conn.get_vm(connkey)
            if not vm:
                # The VM was removed in the meanwhile.
                return
            if obj[0] == "vm_refresh":
                vmuuid = obj[3]
                # When refreshing the inspection data of a VM,
                # all we need is to remove it from the "seen" cache,
                # as the data itself will be replaced once the new
                # results are available.
                del self._vmseen[vmuuid]
            self._process_vm(conn, vm)

    # Try processing a single VM, keeping into account whether it was
    # visited already, and whether there are cached data for it.
    def _process_vm(self, conn, vm):
        def set_inspection_error(vm):
            data = vmmInspectionData()
            data.error = True
            self._set_vm_inspection_data(vm, data)

        vmuuid = vm.get_uuid()
        prettyvm = vmuuid
        try:
            prettyvm = conn.get_uri() + ":" + vm.get_name()

            if vmuuid in self._vmseen:
                data = self._cached_data.get(vmuuid)
                if not data:
                    return

                if vm.inspection != data:
                    logging.debug("Found cached data for %s", prettyvm)
                    self._set_vm_inspection_data(vm, data)
                return

            # Whether success or failure, we've "seen" this VM now.
            self._vmseen[vmuuid] = True
            try:
                data = self._inspect_vm(conn, vm)
                if data:
                    self._set_vm_inspection_data(vm, data)
                else:
                    set_inspection_error(vm)
            except Exception:
                set_inspection_error(vm)
                raise
        except Exception:
            logging.exception("%s: exception while processing", prettyvm)

    def _inspect_vm(self, conn, vm):
        g = GuestFS(close_on_exit=False)
        prettyvm = conn.get_uri() + ":" + vm.get_name()

        g.add_libvirt_dom(vm.get_backend(), readonly=1)

        g.launch()

        # Inspect the operating system.
        roots = g.inspect_os()
        if len(roots) == 0:
            logging.debug("%s: no operating systems found", prettyvm)
            return None

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
            mps.sort(compare)

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
        data.applications = list(apps)
        data.error = False

        return data

    def _set_vm_inspection_data(self, vm, data):
        vm.inspection = data
        vm.inspection_data_updated()
        self._cached_data[vm.get_uuid()] = data

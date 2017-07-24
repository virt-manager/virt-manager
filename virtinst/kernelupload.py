#
# Copyright 2006-2009, 2013, 2014 Red Hat, Inc.
# Daniel P. Berrange <berrange@redhat.com>
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

import logging
import os

from . import util
from .devicedisk import VirtualDisk
from .storage import StoragePool, StorageVolume


def _build_pool(conn, meter, path):
    """
    Helper function for building a pool on demand. Used for building
    a scratchdir pool for volume upload
    """
    pool = StoragePool.lookup_pool_by_path(conn, path)
    if pool:
        logging.debug("Existing pool '%s' found for %s", pool.name(), path)
        pool.refresh(0)
        return pool

    name = StoragePool.find_free_name(conn, "boot-scratch")
    logging.debug("Building storage pool: path=%s name=%s", path, name)
    poolbuild = StoragePool(conn)
    poolbuild.type = poolbuild.TYPE_DIR
    poolbuild.name = name
    poolbuild.target_path = path

    # Explicitly don't build? since if we are creating this directory
    # we probably don't have correct perms
    ret = poolbuild.install(meter=meter, create=True, build=False,
                            autostart=True)
    return ret


def _upload_file(conn, meter, destpool, src):
    """
    Helper for uploading a file to a pool, via libvirt. Used for
    kernel/initrd upload when we can't access the system scratchdir
    """
    # Build stream object
    stream = conn.newStream(0)
    def safe_send(data):
        while True:
            ret = stream.send(data)
            if ret == 0 or ret == len(data):
                break
            data = data[ret:]

    meter = util.ensure_meter(meter)

    # Build placeholder volume
    size = os.path.getsize(src)
    basename = os.path.basename(src)
    name = StorageVolume.find_free_name(destpool, basename)
    if name != basename:
        logging.debug("Generated non-colliding volume name %s", name)

    vol_install = VirtualDisk.build_vol_install(conn, name, destpool,
                    (float(size) / 1024.0 / 1024.0 / 1024.0), True)

    disk = VirtualDisk(conn)
    disk.set_vol_install(vol_install)
    disk.validate()

    disk.setup(meter=meter)
    vol = disk.get_vol_object()
    if not vol:
        raise RuntimeError(_("Failed to lookup scratch media volume"))

    try:
        # Register upload
        offset = 0
        length = size
        flags = 0
        vol.upload(stream, offset, length, flags)

        # Open source file
        fileobj = open(src, "r")

        # Start transfer
        total = 0
        meter.start(size=size,
                    text=_("Transferring %s") % os.path.basename(src))
        while True:
            # blocksize = (1024 ** 2)
            blocksize = 1024
            data = fileobj.read(blocksize)
            if not data:
                break

            safe_send(data)
            total += len(data)
            meter.update(total)

        # Cleanup
        stream.finish()
        meter.end(size)
    except Exception:
        if vol:
            vol.delete(0)
        raise

    return vol


def upload_kernel_initrd(conn, scratchdir, system_scratchdir,
                         meter, kernel, initrd):
    """
    Upload kernel/initrd media to remote connection if necessary
    """
    tmpvols = []

    if (not conn.is_remote() and
        (conn.is_session_uri() or scratchdir == system_scratchdir)):
        # We have access to system scratchdir, don't jump through hoops
        logging.debug("Have access to preferred scratchdir so"
                      " nothing to upload")
        return kernel, initrd, tmpvols

    if not conn.support_remote_url_install():
        logging.debug("Media upload not supported")
        return kernel, initrd, tmpvols

    # Build pool
    logging.debug("Uploading kernel/initrd media")
    pool = _build_pool(conn, meter, system_scratchdir)

    kvol = _upload_file(conn, meter, pool, kernel)
    newkernel = kvol.path()
    tmpvols.append(kvol)

    ivol = _upload_file(conn, meter, pool, initrd)
    newinitrd = ivol.path()
    tmpvols.append(ivol)

    return newkernel, newinitrd, tmpvols

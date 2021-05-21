#
# Copyright 2006-2009, 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from .. import progress
from ..devices import DeviceDisk
from ..logger import log
from ..storage import StoragePool, StorageVolume


def _build_pool(conn, meter, path):
    """
    Helper function for building a pool on demand. Used for building
    a scratchdir pool for volume upload
    """
    pool = StoragePool.lookup_pool_by_path(conn, path)
    if pool:  # pragma: no cover
        log.debug("Existing pool '%s' found for %s", pool.name(), path)
        StoragePool.ensure_pool_is_running(pool, refresh=True)
        return pool

    name = StoragePool.find_free_name(conn, "boot-scratch")
    log.debug("Building storage pool: path=%s name=%s", path, name)
    poolbuild = StoragePool(conn)
    poolbuild.type = poolbuild.TYPE_DIR
    poolbuild.name = name
    poolbuild.target_path = path

    # Explicitly don't build? since if we are creating this directory
    # we probably don't have correct perms
    ret = poolbuild.install(meter=meter, create=True, build=False,
                            autostart=True)
    return ret


class _MockStream:
    _data_size = None

    def send(self, data):
        if self._data_size is None:
            self._data_size = len(data)

        block_size = 128
        ret = min(self._data_size, block_size)
        self._data_size = max(0, self._data_size - block_size)
        return ret

    def finish(self):
        pass


def _upload_file(conn, meter, destpool, src):
    """
    Helper for uploading a file to a pool, via libvirt. Used for
    kernel/initrd upload when we can't access the system scratchdir
    """
    # Build stream object
    if conn.in_testsuite():
        stream = _MockStream()
    else:
        stream = conn.newStream(0)  # pragma: no cover

    def safe_send(data):
        while True:
            ret = stream.send(data)
            if ret == 0 or ret == len(data):
                break
            data = data[ret:]

    meter = progress.ensure_meter(meter)

    # Build placeholder volume
    size = os.path.getsize(src)
    basename = os.path.basename(src)
    name = StorageVolume.find_free_name(conn, destpool, basename)
    log.debug("Generated volume name %s", name)

    vol_install = DeviceDisk.build_vol_install(conn, name, destpool,
                    (float(size) / 1024.0 / 1024.0 / 1024.0), True)

    disk = DeviceDisk(conn)
    disk.set_vol_install(vol_install)
    disk.validate()

    disk.build_storage(meter)
    vol = disk.get_vol_object()
    if not vol:
        raise RuntimeError(  # pragma: no cover
                "Failed to lookup scratch media volume")

    try:
        # Register upload
        offset = 0
        length = size
        flags = 0
        if not conn.in_testsuite():
            vol.upload(stream, offset, length, flags)  # pragma: no cover

        # Open source file
        fileobj = open(src, "rb")

        # Start transfer
        total = 0
        msg = _("Transferring '%(filename)s'") % {
                "filename": os.path.basename(src)}
        meter.start(msg, size)
        while True:
            blocksize = 1024 * 1024  # 1 MiB
            data = fileobj.read(blocksize)
            if not data:
                break

            safe_send(data)
            total += len(data)
            meter.update(total)

        # Cleanup
        stream.finish()
        meter.end()
    except Exception:  # pragma: no cover
        vol.delete(0)
        raise

    return vol


def upload_paths(conn, system_scratchdir, meter, pathlist):
    """
    Upload passed paths to the connection scratchdir
    """
    # Build pool
    log.debug("Uploading kernel/initrd media")
    pool = _build_pool(conn, meter, system_scratchdir)

    tmpvols = []
    newpaths = []
    try:
        for path in pathlist:
            vol = _upload_file(conn, meter, pool, path)
            newpaths.append(vol.path())
            tmpvols.append(vol)
    except Exception:  # pragma: no cover
        for vol in tmpvols:
            vol.delete(0)
        raise

    return newpaths, tmpvols

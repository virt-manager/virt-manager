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
import shutil
import subprocess
import tempfile

from . import urlfetcher
from . import util
from .devicedisk import VirtualDisk
from .installer import Installer
from .osdict import OSDB
from .storage import StoragePool, StorageVolume


def _is_url(conn, url):
    """
    Check if passed string is a (pseudo) valid http, ftp, or nfs url.
    """
    if not conn.is_remote() and os.path.exists(url):
        if os.path.isdir(url):
            return True
        else:
            return False

    return (url.startswith("http://") or url.startswith("https://") or
            url.startswith("ftp://") or url.startswith("nfs:"))


def _sanitize_url(url):
    """
    Do nothing for http or ftp, but make sure nfs is in the expected format
    """
    if url.startswith("nfs://"):
        # Convert RFC compliant NFS      nfs://server/path/to/distro
        # to what mount/anaconda expect  nfs:server:/path/to/distro
        # and carry the latter form around internally
        url = "nfs:" + url[6:]

        # If we need to add the : after the server
        index = url.find("/", 4)
        if index == -1:
            raise ValueError(_("Invalid NFS format: No path specified."))
        if url[index - 1] != ":":
            url = url[:index] + ":" + url[index:]

    return url


def _build_pool(conn, meter, path):
    pool = StoragePool.lookup_pool_by_path(conn, path)
    if pool:
        logging.debug("Existing pool '%s' found for %s", pool.name(), path)
        pool.refresh(0)
        return pool

    name = util.generate_name("boot-scratch",
                               conn.storagePoolLookupByName)
    logging.debug("Building storage pool: path=%s name=%s", path, name)
    poolbuild = StoragePool(conn)
    poolbuild.type = poolbuild.TYPE_DIR
    poolbuild.name = name
    poolbuild.target_path = path

    # Explicitly don't build? since if we are creating this directory
    # we probably don't have correct perms
    ret = poolbuild.install(meter=meter, create=True, build=False,
                            autostart=True)
    conn.clear_cache(pools=True)
    return ret


def _upload_file(conn, meter, destpool, src):
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
        fileobj = file(src, "r")

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
    except:
        if vol:
            vol.delete(0)
        raise

    return vol


def _rhel4_initrd_inject(initrd, injections):
    try:
        file_proc = subprocess.Popen(["file", "-z", initrd],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        if "ext2 filesystem" not in file_proc.communicate()[0]:
            return False
    except:
        logging.exception("Failed to file command for rhel4 initrd detection")
        return False

    logging.debug("Is RHEL4 initrd")

    # Uncompress the initrd
    newinitrd = file(initrd + ".new", "wb")
    gzip_proc = subprocess.Popen(["gzip", "-d", "-f", "-c", initrd],
                                 stdout=newinitrd,
                                 stderr=subprocess.PIPE)
    gzip_proc.wait()
    newinitrd.close()

    debugfserr = ""
    for filename in injections:
        # We have an ext2 filesystem, use debugfs to inject files
        cmd = ["debugfs", "-w", "-R",
               "write %s %s" % (filename, os.path.basename(filename)),
               newinitrd.name]
        logging.debug("Copying %s to the initrd with cmd=%s", filename, cmd)

        debugfs_proc = subprocess.Popen(cmd,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
        debugfs_proc.wait()
        debugfserr += debugfs_proc.stderr.read() or ""

    gziperr = gzip_proc.stderr.read()
    if gziperr:
        logging.debug("gzip stderr=%s", gziperr)
    if debugfserr:
        logging.debug("debugfs stderr=%s", debugfserr)

    # Recompress the initrd
    gzip_proc = subprocess.Popen(["gzip"],
                                 stdin=file(newinitrd.name, "rb"),
                                 stdout=file(initrd, "wb"),
                                 stderr=subprocess.PIPE)
    gzip_proc.wait()
    gziperr = gzip_proc.stderr.read()
    if gziperr:
        logging.debug("gzip stderr=%s", gziperr)
    os.unlink(newinitrd.name)

    return True


def _perform_initrd_injections(initrd, injections, scratchdir):
    """
    Insert files into the root directory of the initial ram disk
    """
    if not injections:
        return

    if _rhel4_initrd_inject(initrd, injections):
        return

    tempdir = tempfile.mkdtemp(dir=scratchdir)
    os.chmod(tempdir, 0775)

    for filename in injections:
        logging.debug("Copying %s to the initrd.", filename)
        shutil.copy(filename, tempdir)

    logging.debug("Appending to the initrd.")
    find_proc = subprocess.Popen(['find', '.', '-print0'],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 cwd=tempdir)
    cpio_proc = subprocess.Popen(['cpio', '-o', '--null', '-Hnewc', '--quiet'],
                                 stdin=find_proc.stdout,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 cwd=tempdir)
    f = open(initrd, 'ab')
    gzip_proc = subprocess.Popen(['gzip'], stdin=cpio_proc.stdout,
                                 stdout=f, stderr=subprocess.PIPE)
    cpio_proc.wait()
    find_proc.wait()
    gzip_proc.wait()
    f.close()
    shutil.rmtree(tempdir)

    finderr = find_proc.stderr.read()
    cpioerr = cpio_proc.stderr.read()
    gziperr = gzip_proc.stderr.read()
    if finderr:
        logging.debug("find stderr=%s", finderr)
    if cpioerr:
        logging.debug("cpio stderr=%s", cpioerr)
    if gziperr:
        logging.debug("gzip stderr=%s", gziperr)



def _upload_media(conn, scratchdir, system_scratchdir,
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



# Enum of the various install media types we can have
(MEDIA_LOCATION_DIR,
 MEDIA_LOCATION_CDROM,
 MEDIA_LOCATION_URL,
 MEDIA_CDROM_PATH,
 MEDIA_CDROM_URL,
 MEDIA_CDROM_IMPLIED) = range(1, 7)


class DistroInstaller(Installer):
    def __init__(self, *args, **kwargs):
        Installer.__init__(self, *args, **kwargs)

        self.livecd = False
        self._cached_fetcher = None
        self._cached_store = None
        self._cdrom_path = None


    ########################
    # Install preparations #
    ########################

    def _get_media_type(self):
        if self.cdrom and not self.location:
            # CDROM install requested from a disk already attached to VM
            return MEDIA_CDROM_IMPLIED

        if self.location and _is_url(self.conn, self.location):
            return self.cdrom and MEDIA_CDROM_URL or MEDIA_LOCATION_URL
        if self.cdrom:
            return MEDIA_CDROM_PATH
        if self.location and os.path.isdir(self.location):
            return MEDIA_LOCATION_DIR
        return MEDIA_LOCATION_CDROM

    def _get_fetcher(self, guest, meter):
        meter = util.ensure_meter(meter)

        if not self._cached_fetcher:
            scratchdir = util.make_scratchdir(guest.conn, guest.type)

            self._cached_fetcher = urlfetcher.fetcherForURI(
                self.location, scratchdir, meter)

        self._cached_fetcher.meter = meter
        return self._cached_fetcher

    def _get_store(self, guest, fetcher):
        # Caller is responsible for calling fetcher prepare/cleanup if needed
        if not self._cached_store:
            self._cached_store = urlfetcher.getDistroStore(guest, fetcher)
        return self._cached_store

    def _prepare_local(self):
        return self.location

    def _prepare_cdrom_url(self, guest, fetcher):
        store = self._get_store(guest, fetcher)
        media = store.acquireBootDisk(guest)
        self._tmpfiles.append(media)
        return media

    def _prepare_kernel_url(self, guest, fetcher):
        store = self._get_store(guest, fetcher)
        kernel, initrd, args = store.acquireKernel(guest)
        self._tmpfiles.append(kernel)
        if initrd:
            self._tmpfiles.append(initrd)

        _perform_initrd_injections(initrd,
                                   self.initrd_injections,
                                   fetcher.scratchdir)

        kernel, initrd, tmpvols = _upload_media(
                guest.conn, fetcher.scratchdir,
                util.get_system_scratchdir(guest.type),
                fetcher.meter, kernel, initrd)
        self._tmpvols += tmpvols

        self._install_kernel = kernel
        self._install_initrd = initrd
        self.extraargs = args


    ###########################
    # Private installer impls #
    ###########################

    def _get_bootdev(self, isinstall, guest):
        mediatype = self._get_media_type()
        local = mediatype in [MEDIA_CDROM_PATH, MEDIA_CDROM_IMPLIED,
                              MEDIA_LOCATION_DIR, MEDIA_LOCATION_CDROM]
        persistent_cd = (local and
                         self.cdrom and
                         self.livecd)

        if isinstall or persistent_cd:
            bootdev = "cdrom"
        else:
            bootdev = "hd"
        return bootdev

    def _validate_location(self, val):
        """
        Valid values for location:

        1) it can be a local file (ex. boot.iso), directory (ex. distro
        tree) or physical device (ex. cdrom media)

        2) http, ftp, or nfs path for an install tree
        """
        self._cached_store = None
        self._cached_fetcher = None

        if _is_url(self.conn, val):
            logging.debug("DistroInstaller location is a network source.")
            return _sanitize_url(val)

        try:
            dev = VirtualDisk(self.conn)
            dev.device = dev.DEVICE_CDROM
            dev.path = val
            dev.validate()

            val = dev.path
        except Exception, e:
            logging.debug("Error validating install location", exc_info=True)
            raise ValueError(_("Validating install media '%s' failed: %s") %
                (str(val), e))

        return val

    def _prepare(self, guest, meter):
        mediatype = self._get_media_type()

        if mediatype == MEDIA_CDROM_IMPLIED:
            return

        cdrom_path = None
        if mediatype == MEDIA_CDROM_PATH or mediatype == MEDIA_LOCATION_CDROM:
            cdrom_path = self.location

        if mediatype != MEDIA_CDROM_PATH:
            fetcher = self._get_fetcher(guest, meter)
            try:
                try:
                    fetcher.prepareLocation()
                except ValueError, e:
                    logging.debug("Error preparing install location",
                        exc_info=True)
                    raise ValueError(_("Invalid install location: ") + str(e))

                if mediatype == MEDIA_CDROM_URL:
                    cdrom_path = self._prepare_cdrom_url(guest, fetcher)
                else:
                    self._prepare_kernel_url(guest, fetcher)
            finally:
                fetcher.cleanupLocation()

        self._cdrom_path = cdrom_path



    ##########################
    # Public installer impls #
    ##########################

    def has_install_phase(self):
        return not self.livecd

    def needs_cdrom(self):
        mediatype = self._get_media_type()
        return mediatype in [MEDIA_CDROM_PATH, MEDIA_LOCATION_CDROM,
                             MEDIA_CDROM_URL]

    def cdrom_path(self):
        return self._cdrom_path

    def scratchdir_required(self):
        mediatype = self._get_media_type()
        return mediatype in [MEDIA_CDROM_URL, MEDIA_LOCATION_URL,
                             MEDIA_LOCATION_DIR, MEDIA_LOCATION_CDROM]

    def check_location(self, guest):
        mediatype = self._get_media_type()
        if mediatype not in [MEDIA_CDROM_URL, MEDIA_LOCATION_URL]:
            return True

        try:
            fetcher = self._get_fetcher(guest, None)
            fetcher.prepareLocation()

            # This will throw an error for us
            ignore = self._get_store(guest, fetcher)
        finally:
            fetcher.cleanupLocation()
        return True

    def detect_distro(self, guest):
        distro = None
        try:
            if _is_url(self.conn, self.location):
                try:
                    fetcher = self._get_fetcher(guest, None)
                    fetcher.prepareLocation()

                    store = self._get_store(guest, fetcher)
                    distro = store.get_osdict_info()
                finally:
                    fetcher.cleanupLocation()
            elif self.conn.is_remote():
                logging.debug("Can't detect distro for media on "
                    "remote connection.")
            else:
                distro = OSDB.lookup_os_by_media(self.location)
        except:
            logging.debug("Error attempting to detect distro.", exc_info=True)

        logging.debug("installer.detect_distro returned=%s", distro)
        return distro

#
# Copyright 2006-2009  Red Hat, Inc.
# Daniel P. Berrange <berrange@redhat.com>
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

import logging
import os
import shutil
import subprocess
import tempfile

import urlgrabber

from virtinst import support
from virtinst import StoragePool, StorageVolume
from virtinst import util
from virtinst import Installer
from virtinst import VirtualDisk
from virtinst import urlfetcher


def _is_url(url, is_local):
    """
    Check if passed string is a (pseudo) valid http, ftp, or nfs url.
    """
    if is_local and os.path.exists(url):
        if os.path.isdir(url):
            return True
        else:
            return False

    return (url.startswith("http://") or url.startswith("ftp://") or
            url.startswith("nfs:"))


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
    conn.clear_cache()
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

    if meter is None:
        meter = urlgrabber.progress.BaseMeter()

    # Build placeholder volume
    size = os.path.getsize(src)
    basename = os.path.basename(src)
    xmlobj = StoragePool(conn, parsexml=destpool.XMLDesc(0))
    poolpath = xmlobj.target_path

    name = StorageVolume.find_free_name(destpool, basename)
    if name != basename:
        logging.debug("Generated non-colliding volume name %s", name)

    vol_install = VirtualDisk.build_vol_install(conn, name, destpool,
                    (float(size) / 1024.0 / 1024.0 / 1024.0), True)

    disk = VirtualDisk(conn)
    disk.path = os.path.join(poolpath, name)
    disk.set_create_storage(vol_install=vol_install)
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
        stream.upload(vol, offset, length, flags)

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
        if not "ext2 filesystem" in file_proc.communicate()[0]:
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

    if not support.support_remote_url_install(conn):
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



class DistroInstaller(Installer):
    def __init__(self, *args, **kwargs):
        Installer.__init__(self, *args, **kwargs)

        self.livecd = False
        self._location_is_path = True


    #######################
    # Install prepartions #
    #######################

    def _prepare_local(self):
        transient = True
        if self.cdrom:
            transient = not self.livecd
        return self._make_cdrom_dev(self.location, transient=transient)

    def _prepare_cdrom_url(self, guest, fetcher):
        store = urlfetcher.getDistroStore(guest, fetcher)
        media = store.acquireBootDisk(guest)
        self._tmpfiles.append(media)
        return self._make_cdrom_dev(media, transient=True)

    def _prepare_kernel_url(self, guest, fetcher):
        store = urlfetcher.getDistroStore(guest, fetcher)
        kernel, initrd, args = store.acquireKernel(guest)
        os_variant = store.get_osdict_info()

        if guest.os_autodetect:
            if os_variant:
                logging.debug("Auto detected OS variant as: %s", os_variant)
                guest.os_variant = os_variant

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
        self._install_args = args


    ###########################
    # Private installer impls #
    ###########################

    def _get_bootdev(self, isinstall, guest):
        persistent_cd = (self._location_is_path and
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
        is_local = not self.conn.is_remote()
        if _is_url(val, is_local):
            self._location_is_path = False
            logging.debug("DistroInstaller location is a network source.")
            return _sanitize_url(val)

        try:
            d = self._make_cdrom_dev(val)
            val = d.path
        except:
            logging.debug("Error validating install location", exc_info=True)
            raise ValueError(_("Checking installer location failed: "
                               "Could not find media '%s'." % str(val)))

        self._location_is_path = True
        return val

    def _prepare(self, guest, meter, scratchdir):
        logging.debug("Using scratchdir=%s", scratchdir)

        if self.cdrom and not self.location:
            # Booting from a cdrom directly allocated to the guest
            return

        # Test suite manually injected a boot kernel
        if self._install_kernel and not self.scratchdir_required():
            return

        dev = None
        if self._location_is_path and not os.path.isdir(self.location):
            dev = self._prepare_local()
        else:
            fetcher = urlfetcher.fetcherForURI(self.location,
                                               scratchdir, meter)
            try:
                try:
                    fetcher.prepareLocation()
                except ValueError, e:
                    logging.exception("Error preparing install location")
                    raise ValueError(_("Invalid install location: ") + str(e))

                if self.cdrom:
                    dev = self._prepare_cdrom_url(guest, fetcher)
                else:
                    self._prepare_kernel_url(guest, fetcher)
            finally:
                fetcher.cleanupLocation()

        if dev:
            self.install_devices.append(dev)



    ##########################
    # Public installer impls #
    ##########################

    def scratchdir_required(self):
        if not self.location:
            return False

        is_url = not self._location_is_path
        mount_dvd = self._location_is_path and not self.cdrom

        return bool(is_url or mount_dvd)

    def check_location(self, guest):
        if self._location_is_path:
            # We already mostly validated this
            return True

        # This will throw an error for us
        urlfetcher.detectMediaDistro(guest, self.location)
        return True

    def detect_distro(self, guest):
        try:
            return urlfetcher.detectMediaDistro(guest, self.location)
        except:
            logging.exception("Error attempting to detect distro.")
            return None

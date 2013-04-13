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

from virtinst import Storage
from virtinst import support
from virtinst import util
from virtinst import Installer
from virtinst.VirtualDisk import VirtualDisk
from virtinst.User import User
from virtinst import OSDistro


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
    pool = util.lookup_pool_by_path(conn, path)
    if pool:
        logging.debug("Existing pool '%s' found for %s", pool.name(), path)
        pool.refresh(0)
        return pool

    name = util.generate_name("boot-scratch",
                               conn.storagePoolLookupByName)
    logging.debug("Building storage pool: path=%s name=%s", path, name)
    poolbuild = Storage.DirectoryPool(conn=conn, name=name,
                                      target_path=path)

    # Explicitly don't build? since if we are creating this directory
    # we probably don't have correct perms
    return poolbuild.install(meter=meter, create=True, build=False,
                             autostart=True)


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
    poolpath = util.get_xml_path(destpool.XMLDesc(0), "/pool/target/path")
    name = Storage.StorageVolume.find_free_name(basename,
                                                pool_object=destpool)
    if name != basename:
        logging.debug("Generated non-colliding volume name %s", name)

    disk = VirtualDisk(conn=conn,
                       path=os.path.join(poolpath, name),
                       sizebytes=size,
                       sparse=True)

    disk.setup_dev(meter=meter)
    vol = disk.vol_object
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


class DistroInstaller(Installer.Installer):
    def __init__(self, type="xen", location=None,
                 extraargs=None, os_type=None,
                 conn=None, caps=None):
        # pylint: disable=W0622
        # Redefining built-in 'type', but it matches the XML so keep it

        Installer.Installer.__init__(self, type, location, extraargs,
                                     os_type, conn=conn, caps=caps)

        self._livecd = False

        # True == location is a filesystem path
        # False == location is a url
        self._location_is_path = True

    # DistroInstaller specific methods/overwrites

    def _get_livecd(self):
        return self._livecd
    def _set_livecd(self, val):
        self._livecd = bool(val)
    livecd = property(_get_livecd, _set_livecd)

    def get_location(self):
        return self._location
    def set_location(self, val):
        """
        Valid values for location:

        1) it can be a local file (ex. boot.iso), directory (ex. distro
        tree) or physical device (ex. cdrom media)

        2) tuple of the form (poolname, volname) pointing to a file or
        device which will set location as that path

        3) http, ftp, or nfs path for an install tree
        """
        is_tuple = False
        validated = True
        self._location_is_path = True
        is_local = (not self.conn or not self.is_remote())

        # Basic validation
        if type(val) is not str and (type(val) is not tuple and len(val) != 2):
            raise ValueError(_("Invalid 'location' type %s." % type(val)))

        if type(val) is tuple and len(val) == 2:
            logging.debug("DistroInstaller location is a (poolname, volname)"
                          " tuple")
            if not self.conn:
                raise ValueError(_("'conn' must be specified if 'location' is"
                                   " a storage tuple."))
            is_tuple = True

        elif _is_url(val, is_local):
            val = _sanitize_url(val)
            self._location_is_path = False
            logging.debug("DistroInstaller location is a network source.")

        elif os.path.exists(os.path.abspath(val)) and is_local:
            val = os.path.abspath(val)
            logging.debug("DistroInstaller location is a local "
                          "file/path: %s", val)

        else:
            # Didn't determine anything about the location
            validated = False

        if self._location_is_path or (not validated and self.conn and
                                      util.is_storage_capable(self.conn)):
            # If user passed a storage tuple, OR
            # We couldn't determine the location type and a storage capable
            #   connection was passed:
            # Pass the parameters off to VirtualDisk to validate, and pull
            # out the path
            stuple = (is_tuple and val) or None
            path = (not is_tuple and val) or None

            try:
                d = VirtualDisk(path=path,
                                device=VirtualDisk.DEVICE_CDROM,
                                transient=True,
                                readOnly=True,
                                conn=self.conn,
                                volName=stuple)
                val = d.path
            except:
                logging.debug("Error validating install location",
                              exc_info=True)
                raise ValueError(_("Checking installer location failed: "
                                   "Could not find media '%s'." % str(val)))
        elif not validated:
            raise ValueError(_("Install media location must be an NFS, HTTP "
                               "or FTP network install source, or an existing "
                               "file/device"))

        if (not self._location_is_path and val.startswith("nfs:") and not
            User.current().has_priv(User.PRIV_NFS_MOUNT,
                                    (self.conn and self.get_uri()))):
            raise ValueError(_('Privilege is required for NFS installations'))

        self._location = val
    location = property(get_location, set_location)


    # Private helper methods

    def _prepare_cdrom(self, guest, meter):
        transient = not self.livecd
        if not self._location_is_path:
            # Xen needs a boot.iso if its a http://, ftp://, or nfs: url
            (store_ignore, os_type_ignore,
             os_variant_ignore, media) = OSDistro.getBootDisk(guest,
                                                              self.location,
                                                              meter,
                                                              self.scratchdir)
            cdrom = media

            self._tmpfiles.append(cdrom)
            transient = True
        else:
            cdrom = self.location

        disk = VirtualDisk(path=cdrom,
                           conn=guest.conn,
                           device=VirtualDisk.DEVICE_CDROM,
                           readOnly=True,
                           transient=transient)
        self.install_devices.append(disk)

    def _perform_initrd_injections(self, initrd):
        """
        Insert files into the root directory of the initial ram disk
        """
        tempdir = tempfile.mkdtemp(dir=self.scratchdir)
        os.chmod(tempdir, 0775)

        for filename in self._initrd_injections:
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

    def support_remote_url_install(self):
        if not self.conn:
            return False
        if hasattr(self.conn, "_virtinst__fake_conn"):
            return False
        return support.check_stream_support(self.conn,
                                            support.SUPPORT_STREAM_UPLOAD)

    def _upload_media(self, guest, meter, kernel, initrd):
        conn = guest.conn
        system_scratchdir = self._get_system_scratchdir()

        if (not guest.is_remote() and
            (self.is_session_uri() or self.scratchdir == system_scratchdir)):
            # We have access to system scratchdir, don't jump through hoops
            logging.debug("Have access to preferred scratchdir so"
                          " nothing to upload")
            return kernel, initrd

        if not self.support_remote_url_install():
            logging.debug("Media upload not supported")
            return kernel, initrd

        # Build pool
        logging.debug("Uploading kernel/initrd media")
        pool = _build_pool(conn, meter, system_scratchdir)

        kvol = _upload_file(conn, meter, pool, kernel)
        newkernel = kvol.path()
        self._tmpvols.append(kvol)

        ivol = _upload_file(conn, meter, pool, initrd)
        newinitrd = ivol.path()
        self._tmpvols.append(ivol)

        return newkernel, newinitrd

    def _prepare_kernel_and_initrd(self, guest, meter):
        disk = None

        # If installing off a local path, map it through to a virtual CD/disk
        if (self.location is not None and
            self._location_is_path and
            not os.path.isdir(self.location)):

            device = VirtualDisk.DEVICE_CDROM

            # pylint: disable=W0212
            # Access to protected member lookup_osdict_key
            can_cdrom = guest._lookup_osdict_key('pv_cdrom_install')
            # pylint: enable=W0212

            if self.is_xenpv() and can_cdrom:
                device = VirtualDisk.DEVICE_DISK

            disk = VirtualDisk(conn=guest.conn,
                               device=device,
                               path=self.location,
                               readOnly=True,
                               transient=True)

        # Make sure we always fetch kernel here if required
        if self._install_bootconfig.kernel and not self.scratchdir_required():
            return disk

        # Need to fetch the kernel & initrd from a remote site, or
        # out of a loopback mounted disk image/device
        ignore, os_type, os_variant, media = OSDistro.getKernel(guest,
                                                self.location, meter,
                                                self.scratchdir,
                                                self.os_type)
        (kernelfn, initrdfn, args) = media

        if guest.get_os_autodetect():
            if os_type:
                logging.debug("Auto detected OS type as: %s", os_type)
                guest.os_type = os_type

            if (os_variant and guest.os_type == os_type):
                logging.debug("Auto detected OS variant as: %s", os_variant)
                guest.os_variant = os_variant

        self._tmpfiles.append(kernelfn)
        if initrdfn:
            self._tmpfiles.append(initrdfn)

        if self._initrd_injections:
            self._perform_initrd_injections(initrdfn)

        # If required, upload media to an accessible guest location
        kernelfn, initrdfn = self._upload_media(guest, meter,
                                                kernelfn, initrdfn)

        self._install_bootconfig.kernel = kernelfn
        self._install_bootconfig.initrd = initrdfn
        self._install_bootconfig.kernel_args = args

        return disk

    def _persistent_cd(self):
        return (self._location_is_path and self.cdrom and self.livecd)

    def _get_bootdev(self, isinstall, guest):
        if isinstall or self._persistent_cd():
            bootdev = self.bootconfig.BOOT_DEVICE_CDROM
        else:
            bootdev = self.bootconfig.BOOT_DEVICE_HARDDISK
        return bootdev

    # General Installer methods

    def scratchdir_required(self):
        if not self.location:
            return False

        is_url = not self._location_is_path
        mount_dvd = self._location_is_path and not self.cdrom

        return bool(is_url or mount_dvd)

    def prepare(self, guest, meter):
        self.cleanup()

        dev = None
        if self.cdrom:
            if self.location:
                dev = self._prepare_cdrom(guest, meter)
            else:
                # Booting from a cdrom directly allocated to the guest
                pass
        else:
            dev = self._prepare_kernel_and_initrd(guest, meter)

        if dev:
            self.install_devices.append(dev)

    def check_location(self):
        if self._location_is_path:
            # We already mostly validated this
            return True
        else:
            # This will throw an error for us
            OSDistro.detectMediaDistro(location=self.location, arch=self.arch)
        return True

    def detect_distro(self):
        try:
            dist_info = OSDistro.detectMediaDistro(location=self.location,
                                                   arch=self.arch)
        except:
            logging.exception("Error attempting to detect distro.")
            return (None, None)

        # detectMediaDistro should only return valid values
        dtype, dvariant = dist_info
        return (dtype, dvariant)

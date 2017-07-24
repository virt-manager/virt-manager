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

from . import urlfetcher
from . import util
from .devicedisk import VirtualDisk
from .initrdinject import perform_initrd_injections
from .kernelupload import upload_kernel_initrd
from .installer import Installer
from .osdict import OSDB


def _is_url(conn, url):
    """
    Check if passed string is a (pseudo) valid http, ftp, or nfs url.
    """
    if not conn.is_remote() and os.path.exists(url):
        return os.path.isdir(url)

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

        perform_initrd_injections(initrd,
                                  self.initrd_injections,
                                  fetcher.scratchdir)

        kernel, initrd, tmpvols = upload_kernel_initrd(
                guest.conn, fetcher.scratchdir,
                util.get_system_scratchdir(guest.type),
                fetcher.meter, kernel, initrd)
        self._tmpvols += tmpvols

        self._install_kernel = kernel
        self._install_initrd = initrd
        if args:
            self.extraargs.append(args)


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
        except Exception as e:
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
                except ValueError as e:
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
        except Exception:
            logging.debug("Error attempting to detect distro.", exc_info=True)

        logging.debug("installer.detect_distro returned=%s", distro)
        return distro

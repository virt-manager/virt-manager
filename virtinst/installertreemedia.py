#
# Copyright 2006-2009, 2013, 2014 Red Hat, Inc.
# Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import os

from . import urldetect
from . import urlfetcher
from . import util
from .devices import DeviceDisk
from .initrdinject import perform_initrd_injections
from .kernelupload import upload_kernel_initrd
from .osdict import OSDB




# Enum of the various install media types we can have
(MEDIA_DIR,
 MEDIA_ISO,
 MEDIA_URL) = range(1, 4)


def _is_url(url):
    return (url.startswith("http://") or
            url.startswith("https://") or
            url.startswith("ftp://"))


class InstallerTreeMedia(object):
    """
    Class representing --location Tree media. Can be one of

      - A network URL: http://dl.fedoraproject.org/...
      - A local directory
      - A local .iso file, which will be accessed with isoinfo
    """

    @staticmethod
    def validate_path(conn, path):
        try:
            dev = DeviceDisk(conn)
            dev.device = dev.DEVICE_CDROM
            dev.path = path
            dev.validate()
            return dev.path
        except Exception as e:
            logging.debug("Error validating install location", exc_info=True)
            if path.startswith("nfs:"):
                logging.warning("NFS URL installs are no longer supported. "
                    "Access your install media over an alternate transport "
                    "like HTTP, or manually mount the NFS share and install "
                    "from the local directory mount point.")

            raise ValueError(_("Validating install media '%s' failed: %s") %
                (str(path), e))

    @staticmethod
    def detect_iso_distro(guest, path):
        if guest.conn.is_remote():
            logging.debug("Can't detect distro for media on "
                "remote connection.")
            return None
        return OSDB.lookup_os_by_media(path)

    def __init__(self, conn, location):
        self.conn = conn
        self.location = location
        self.initrd_injections = []

        self._cached_fetcher = None
        self._cached_store = None

        self._tmpfiles = []
        self._tmpvols = []

        self._media_type = MEDIA_ISO
        if (not self.conn.is_remote() and
            os.path.exists(self.location) and
            os.path.isdir(self.location)):
            self._media_type = MEDIA_DIR
        elif _is_url(self.location):
            self._media_type = MEDIA_URL

        if self._media_type == MEDIA_ISO:
            InstallerTreeMedia.validate_path(self.conn, self.location)


    ########################
    # Install preparations #
    ########################

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
            self._cached_store = urldetect.getDistroStore(guest, fetcher)
        return self._cached_store

    def _prepare_kernel_url(self, guest, fetcher):
        store = self._get_store(guest, fetcher)
        kernel, initrd, args = store.acquireKernel()
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

        return kernel, initrd, args


    ##############
    # Public API #
    ##############

    def prepare(self, guest, meter):
        fetcher = self._get_fetcher(guest, meter)
        try:
            try:
                fetcher.prepareLocation()
            except ValueError as e:
                logging.debug("Error preparing install location",
                    exc_info=True)
                raise ValueError(_("Invalid install location: ") + str(e))

            return self._prepare_kernel_url(guest, fetcher)
        finally:
            fetcher.cleanupLocation()

    def cleanup(self, guest):
        ignore = guest
        for f in self._tmpfiles:
            logging.debug("Removing %s", str(f))
            os.unlink(f)

        for vol in self._tmpvols:
            logging.debug("Removing volume '%s'", vol.name())
            vol.delete(0)

        self._tmpvols = []
        self._tmpfiles = []

    def cdrom_path(self):
        if self._media_type in [MEDIA_ISO]:
            return self.location

    def check_location(self, guest):
        if self._media_type not in [MEDIA_URL]:
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
        if self._media_type in [MEDIA_ISO]:
            return InstallerTreeMedia.detect_iso_distro(guest, self.location)

        try:
            fetcher = self._get_fetcher(guest, None)
            fetcher.prepareLocation()

            store = self._get_store(guest, fetcher)
            return store.get_osdict_info()
        finally:
            fetcher.cleanupLocation()

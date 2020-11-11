#
# Copyright 2006-2009, 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from . import urldetect
from . import urlfetcher
from .installerinject import perform_initrd_injections
from .. import progress
from ..devices import DeviceDisk
from ..logger import log
from ..osdict import OSDB


# Enum of the various install media types we can have
(MEDIA_DIR,
 MEDIA_ISO,
 MEDIA_URL,
 MEDIA_KERNEL) = range(1, 5)


def _is_url(url):
    return (url.startswith("http://") or
            url.startswith("https://") or
            url.startswith("ftp://"))


class _LocationData(object):
    def __init__(self, os_variant, kernel_pairs, os_media, os_tree):
        self.os_variant = os_variant
        self.kernel_pairs = kernel_pairs
        self.os_media = os_media
        self.os_tree = os_tree

        self.kernel_url_arg = None
        if self.os_variant:
            osobj = OSDB.lookup_os(self.os_variant)
            self.kernel_url_arg = osobj.get_kernel_url_arg()


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
            dev.set_source_path(path)
            dev.validate()
            return dev.get_source_path()
        except Exception as e:
            log.debug("Error validating install location", exc_info=True)
            if path.startswith("nfs:"):
                log.warning("NFS URL installs are no longer supported. "
                    "Access your install media over an alternate transport "
                    "like HTTP, or manually mount the NFS share and install "
                    "from the local directory mount point.")

            msg = (_("Validating install media '%(media)s' failed: %(error)s") %
                    {"media": str(path), "error": str(e)})
            raise ValueError(msg) from None

    @staticmethod
    def get_system_scratchdir(guest):
        """
        Return the tmpdir that's accessible by VMs on system libvirt URIs
        """
        if guest.conn.is_xen():
            return "/var/lib/xen"
        return "/var/lib/libvirt/boot"

    @staticmethod
    def make_scratchdir(guest):
        """
        Determine the scratchdir for this URI, create it if necessary.
        scratchdir is the directory that's accessible by VMs
        """
        user_scratchdir = os.path.join(
                guest.conn.get_app_cache_dir(), "boot")
        system_scratchdir = InstallerTreeMedia.get_system_scratchdir(guest)

        # If we are a session URI, or we don't have access to the system
        # scratchdir, make sure the session scratchdir exists and use that.
        if (guest.conn.is_unprivileged() or
            not os.path.exists(system_scratchdir) or
            not os.access(system_scratchdir, os.W_OK)):
            os.makedirs(user_scratchdir, 0o751, exist_ok=True)
            return user_scratchdir

        return system_scratchdir  # pragma: no cover

    def __init__(self, conn, location, location_kernel, location_initrd,
                install_kernel, install_initrd, install_kernel_args):
        self.conn = conn
        self.location = location
        self._location_kernel = location_kernel
        self._location_initrd = location_initrd
        self._install_kernel = install_kernel
        self._install_initrd = install_initrd
        self._install_kernel_args = install_kernel_args
        self._initrd_injections = []
        self._extra_args = []

        if location_kernel or location_initrd:
            if not location:
                raise ValueError(_("location kernel/initrd may only "
                    "be specified with a location URL/path"))
            if not (location_kernel and location_initrd):
                raise ValueError(_("location kernel/initrd must be "
                    "be specified as a pair"))

        self._cached_fetcher = None
        self._cached_data = None

        self._tmpfiles = []

        if self._install_kernel or self._install_initrd:
            self._media_type = MEDIA_KERNEL
        elif (not self.conn.is_remote() and
              os.path.exists(self.location) and
              os.path.isdir(self.location)):
            self.location = os.path.abspath(self.location)
            self._media_type = MEDIA_DIR
        elif _is_url(self.location):
            self._media_type = MEDIA_URL
        else:
            self._media_type = MEDIA_ISO

        if (self.conn.is_remote() and
                not self._media_type == MEDIA_URL and
            not self._media_type == MEDIA_KERNEL):
            raise ValueError(_("Cannot access install tree on remote "
                "connection: %s") % self.location)

        if self._media_type == MEDIA_ISO:
            InstallerTreeMedia.validate_path(self.conn, self.location)


    ########################
    # Install preparations #
    ########################

    def _get_fetcher(self, guest, meter):
        meter = progress.ensure_meter(meter)

        if not self._cached_fetcher:
            scratchdir = InstallerTreeMedia.make_scratchdir(guest)

            if self._media_type == MEDIA_KERNEL:
                self._cached_fetcher = urlfetcher.DirectFetcher(
                    None, scratchdir, meter)
            else:
                self._cached_fetcher = urlfetcher.fetcherForURI(
                    self.location, scratchdir, meter)

        self._cached_fetcher.meter = meter
        return self._cached_fetcher

    def _get_cached_data(self, guest, fetcher):
        if self._cached_data:
            return self._cached_data

        store = None
        os_variant = None
        os_media = None
        os_tree = None
        kernel_paths = []
        has_location_kernel = bool(
                self._location_kernel and self._location_initrd)

        if self._media_type == MEDIA_KERNEL:
            kernel_paths = [
                    (self._install_kernel, self._install_initrd)]
        else:
            store = urldetect.getDistroStore(guest, fetcher,
                    skip_error=has_location_kernel)

        if store:
            kernel_paths = store.get_kernel_paths()
            os_variant = store.get_osdict_info()
            os_media = store.get_os_media()
            os_tree = store.get_os_tree()
        if has_location_kernel:
            kernel_paths = [
                    (self._location_kernel, self._location_initrd)]

        self._cached_data = _LocationData(os_variant, kernel_paths,
                os_media, os_tree)
        return self._cached_data

    def _prepare_kernel_url(self, guest, cache, fetcher):
        ignore = guest

        def _check_kernel_pairs():
            for kpath, ipath in cache.kernel_pairs:
                if fetcher.hasFile(kpath) and fetcher.hasFile(ipath):
                    return kpath, ipath
            raise RuntimeError(  # pragma: no cover
                    _("Couldn't find kernel for install tree."))

        kernelpath, initrdpath = _check_kernel_pairs()
        kernel = fetcher.acquireFile(kernelpath)
        self._tmpfiles.append(kernel)
        initrd = fetcher.acquireFile(initrdpath)
        self._tmpfiles.append(initrd)

        perform_initrd_injections(initrd,
                                  self._initrd_injections,
                                  fetcher.scratchdir)

        return kernel, initrd


    ##############
    # Public API #
    ##############

    def _prepare_unattended_data(self, scripts):
        if not scripts:
            return

        for script in scripts:
            expected_filename = script.get_expected_filename()
            scriptpath = script.write()
            self._tmpfiles.append(scriptpath)
            self._initrd_injections.append((scriptpath, expected_filename))

    def _prepare_kernel_url_arg(self, guest, cache):
        os_variant = cache.os_variant or guest.osinfo.name
        osobj = OSDB.lookup_os(os_variant)
        return osobj.get_kernel_url_arg()

    def _prepare_kernel_args(self, guest, cache, unattended_scripts):
        install_args = None
        if unattended_scripts:
            args = []
            for unattended_script in unattended_scripts:
                cmdline = unattended_script.generate_cmdline()
                if cmdline:
                    args.append(cmdline)
            install_args = (" ").join(args)
            log.debug("Generated unattended cmdline: %s", install_args)
        elif self.is_network_url():
            kernel_url_arg = self._prepare_kernel_url_arg(guest, cache)
            if kernel_url_arg:
                install_args = "%s=%s" % (kernel_url_arg, self.location)

        if install_args:
            self._extra_args.append(install_args)

        if self._install_kernel_args:
            ret = self._install_kernel_args
        else:
            ret = " ".join(self._extra_args)

        if self._media_type == MEDIA_DIR and not ret:
            log.warning(_("Directory tree installs typically do not work "
                "unless extra kernel args are passed to point the "
                "installer at a network accessible install tree."))
        return ret

    def prepare(self, guest, meter, unattended_scripts):
        fetcher = self._get_fetcher(guest, meter)
        cache = self._get_cached_data(guest, fetcher)

        self._prepare_unattended_data(unattended_scripts)
        kernel_args = self._prepare_kernel_args(guest, cache, unattended_scripts)

        kernel, initrd = self._prepare_kernel_url(guest, cache, fetcher)
        return kernel, initrd, kernel_args

    def cleanup(self, guest):
        ignore = guest
        for f in self._tmpfiles:
            log.debug("Removing %s", str(f))
            os.unlink(f)

        self._tmpfiles = []

    def set_initrd_injections(self, initrd_injections):
        self._initrd_injections = initrd_injections

    def set_extra_args(self, extra_args):
        self._extra_args = extra_args

    def cdrom_path(self):
        if self._media_type in [MEDIA_ISO]:
            return self.location

    def is_network_url(self):
        if self._media_type in [MEDIA_URL]:
            return self.location

    def detect_distro(self, guest):
        fetcher = self._get_fetcher(guest, None)
        cache = self._get_cached_data(guest, fetcher)
        return cache.os_variant

    def get_os_media(self, guest, meter):
        fetcher = self._get_fetcher(guest, meter)
        cache = self._get_cached_data(guest, fetcher)
        return cache.os_media

    def get_os_tree(self, guest, meter):
        fetcher = self._get_fetcher(guest, meter)
        cache = self._get_cached_data(guest, fetcher)
        return cache.os_tree

    def requires_internet(self, guest, meter):
        if self._media_type in [MEDIA_URL, MEDIA_DIR]:
            return True

        os_media = self.get_os_media(guest, meter)
        if os_media:
            return os_media.is_netinst()
        return False

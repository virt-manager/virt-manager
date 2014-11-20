#
# Represents OS distribution specific install data
#
# Copyright 2006-2007, 2013 Red Hat, Inc.
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

import ConfigParser
import ftplib
import logging
import os
import re
import stat
import subprocess
import tempfile
import urllib2
import urlparse

import urlgrabber.grabber as grabber

from . import osdict


#########################################################################
# Backends for the various URL types we support (http, ftp, nfs, local) #
#########################################################################

class _ImageFetcher(object):
    """
    This is a generic base class for fetching/extracting files from
    a media source, such as CD ISO, NFS server, or HTTP/FTP server
    """
    def __init__(self, location, scratchdir, meter):
        self.location = location
        self.scratchdir = scratchdir
        self.meter = meter
        self.srcdir = None

        logging.debug("Using scratchdir=%s", scratchdir)

    def _make_path(self, filename):
        path = self.srcdir or self.location

        if filename:
            if not path.endswith("/"):
                path += "/"
            path += filename

        return path

    def saveTemp(self, fileobj, prefix):
        if not os.path.exists(self.scratchdir):
            os.makedirs(self.scratchdir, 0750)

        prefix = "virtinst-" + prefix
        if "VIRTINST_TEST_SUITE" in os.environ:
            fn = os.path.join("/tmp", prefix)
            fd = os.open(fn, os.O_RDWR | os.O_CREAT, 0640)
        else:
            (fd, fn) = tempfile.mkstemp(prefix=prefix,
                                        dir=self.scratchdir)

        block_size = 16384
        try:
            while 1:
                buff = fileobj.read(block_size)
                if not buff:
                    break
                os.write(fd, buff)
        finally:
            os.close(fd)
        return fn

    def prepareLocation(self):
        pass

    def cleanupLocation(self):
        pass

    def acquireFile(self, filename):
        # URLGrabber works for all network and local cases

        f = None
        try:
            path = self._make_path(filename)
            base = os.path.basename(filename)
            logging.debug("Fetching URI: %s", path)

            try:
                f = grabber.urlopen(path,
                                    progress_obj=self.meter,
                                    text=_("Retrieving file %s...") % base)
            except Exception, e:
                raise ValueError(_("Couldn't acquire file %s: %s") %
                                   (path, str(e)))

            tmpname = self.saveTemp(f, prefix=base + ".")
            logging.debug("Saved file to " + tmpname)
            return tmpname
        finally:
            if f:
                f.close()


    def hasFile(self, src):
        raise NotImplementedError("Must be implemented in subclass")


class _URIImageFetcher(_ImageFetcher):
    """
    Base class for downloading from FTP / HTTP
    """
    def hasFile(self, filename):
        raise NotImplementedError

    def prepareLocation(self):
        if not self.hasFile(""):
            raise ValueError(_("Opening URL %s failed.") %
                              (self.location))


class _HTTPImageFetcher(_URIImageFetcher):
    def hasFile(self, filename):
        try:
            path = self._make_path(filename)
            request = urllib2.Request(path)
            request.get_method = lambda: "HEAD"
            urllib2.urlopen(request)
        except Exception, e:
            logging.debug("HTTP hasFile: didn't find %s: %s", path, str(e))
            return False
        return True


class _FTPImageFetcher(_URIImageFetcher):
    ftp = None

    def prepareLocation(self):
        if self.ftp:
            return

        try:
            url = urlparse.urlparse(self._make_path(""))
            if not url[1]:
                raise ValueError(_("Invalid install location"))
            self.ftp = ftplib.FTP(url[1])
            self.ftp.login()
        except Exception, e:
            raise ValueError(_("Opening URL %s failed: %s.") %
                              (self.location, str(e)))

    def cleanupLocation(self):
        if not self.ftp:
            return

        try:
            self.ftp.quit()
        except:
            logging.debug("Error quitting ftp connection", exc_info=True)


    def hasFile(self, filename):
        path = self._make_path(filename)
        url = urlparse.urlparse(path)

        try:
            try:
                # If it's a file
                self.ftp.size(url[2])
            except ftplib.all_errors:
                # If it's a dir
                self.ftp.cwd(url[2])
        except ftplib.all_errors, e:
            logging.debug("FTP hasFile: couldn't access %s: %s",
                          path, str(e))
            return False

        return True


class _LocalImageFetcher(_ImageFetcher):
    def hasFile(self, filename):
        src = self._make_path(filename)
        if os.path.exists(src):
            return True
        else:
            logging.debug("local hasFile: Couldn't find %s", src)
            return False


class _MountedImageFetcher(_LocalImageFetcher):
    """
    Fetcher capable of extracting files from a NFS server
    or loopback mounted file, or local CDROM device
    """
    _in_test_suite = bool("VIRTINST_TEST_SUITE" in os.environ)
    _mounted = False

    def prepareLocation(self):
        if self._mounted:
            return

        if self._in_test_suite:
            self.srcdir = os.environ["VIRTINST_TEST_URL_DIR"]
        else:
            self.srcdir = tempfile.mkdtemp(prefix="virtinstmnt.",
                                           dir=self.scratchdir)
        mountcmd = "/bin/mount"

        logging.debug("Preparing mount at " + self.srcdir)
        if self.location.startswith("nfs:"):
            cmd = [mountcmd, "-o", "ro", self.location[4:], self.srcdir]
        else:
            if stat.S_ISBLK(os.stat(self.location)[stat.ST_MODE]):
                mountopt = "ro"
            else:
                mountopt = "ro,loop"
            cmd = [mountcmd, "-o", mountopt, self.location, self.srcdir]

        logging.debug("mount cmd: %s", cmd)
        if not self._in_test_suite:
            ret = subprocess.call(cmd)
            if ret != 0:
                self.cleanupLocation()
                raise ValueError(_("Mounting location '%s' failed") %
                                 (self.location))

        self._mounted = True

    def cleanupLocation(self):
        if not self._mounted:
            return

        logging.debug("Cleaning up mount at " + self.srcdir)
        try:
            if not self._in_test_suite:
                cmd = ["/bin/umount", self.srcdir]
                subprocess.call(cmd)
                try:
                    os.rmdir(self.srcdir)
                except:
                    pass
        finally:
            self._mounted = False


class _DirectImageFetcher(_LocalImageFetcher):
    def prepareLocation(self):
        self.srcdir = self.location


def fetcherForURI(uri, *args, **kwargs):
    if uri.startswith("http://") or uri.startswith("https://"):
        fclass = _HTTPImageFetcher
    elif uri.startswith("ftp://"):
        fclass = _FTPImageFetcher
    elif uri.startswith("nfs:"):
        fclass = _MountedImageFetcher
    else:
        if os.path.isdir(uri):
            fclass = _DirectImageFetcher
        else:
            fclass = _MountedImageFetcher
    return fclass(uri, *args, **kwargs)


###############################################
# Helpers for detecting distro from given URL #
###############################################

def _distroFromTreeinfo(fetcher, arch, vmtype=None):
    """
    Parse treeinfo 'family' field, and return the associated Distro class
    None if no treeinfo, GenericDistro if unknown family type.
    """
    if not fetcher.hasFile(".treeinfo"):
        return None

    tmptreeinfo = fetcher.acquireFile(".treeinfo")
    try:
        treeinfo = ConfigParser.SafeConfigParser()
        treeinfo.read(tmptreeinfo)
    finally:
        os.unlink(tmptreeinfo)

    try:
        fam = treeinfo.get("general", "family")
    except ConfigParser.NoSectionError:
        return None

    if re.match(".*Fedora.*", fam):
        dclass = FedoraDistro
    elif re.match(".*CentOS.*", fam):
        dclass = CentOSDistro
    elif re.match(".*Red Hat Enterprise Linux.*", fam):
        dclass = RHELDistro
    elif re.match(".*Scientific Linux.*", fam):
        dclass = SLDistro
    else:
        dclass = GenericDistro

    ob = dclass(fetcher, arch, vmtype)
    ob.treeinfo = treeinfo

    # Explicitly call this, so we populate variant info
    ob.isValidStore()

    return ob


def getDistroStore(guest, fetcher):
    stores = []
    logging.debug("Finding distro store for location=%s", fetcher.location)

    arch = guest.os.arch
    _type = guest.os.os_type

    urldistro = None
    if guest.os_variant:
        urldistro = osdict.lookup_os(guest.os_variant).urldistro

    dist = _distroFromTreeinfo(fetcher, arch, _type)
    if dist:
        return dist

    stores = _allstores[:]

    # If user manually specified an os_distro, bump it's URL class
    # to the top of the list
    if urldistro:
        for store in stores:
            if store.urldistro == urldistro:
                logging.debug("Prioritizing distro store=%s", store)
                stores.remove(store)
                stores.insert(0, store)
                break

    # Always stick GenericDistro at the end, since it's a catchall
    stores.remove(GenericDistro)
    stores.append(GenericDistro)

    for sclass in stores:
        store = sclass(fetcher, arch, _type)
        # We already tried the treeinfo short circuit, so skip it here
        store.uses_treeinfo = False
        if store.isValidStore():
            logging.debug("Detected distro name=%s osvariant=%s",
                          store.name, store.os_variant)
            return store

    raise ValueError(
        _("Could not find an installable distribution at '%s'\n"
          "The location must be the root directory of an install tree.\n"
          "See virt-install man page for various distro examples." %
          fetcher.location))


##################
# Distro classes #
##################

class Distro(object):
    """
    An image store is a base class for retrieving either a bootable
    ISO image, or a kernel+initrd  pair for a particular OS distribution
    """
    name = None
    urldistro = None

    # osdict variant value
    os_variant = None

    _boot_iso_paths = []
    _hvm_kernel_paths = []
    _xen_kernel_paths = []
    uses_treeinfo = False

    def __init__(self, fetcher, arch, vmtype):
        self.fetcher = fetcher
        self.type = vmtype
        self.arch = arch

        self.uri = fetcher.location
        self.treeinfo = None

    def isValidStore(self):
        """Determine if uri points to a tree of the store's distro"""
        raise NotImplementedError

    def acquireKernel(self, guest):
        kernelpath = None
        initrdpath = None
        if self._hasTreeinfo():
            try:
                kernelpath = self._getTreeinfoMedia("kernel")
                initrdpath = self._getTreeinfoMedia("initrd")
            except ConfigParser.NoSectionError:
                pass

        if not kernelpath or not initrdpath:
            # fall back to old code
            if self.type is None or self.type == "hvm":
                paths = self._hvm_kernel_paths
            else:
                paths = self._xen_kernel_paths

            for kpath, ipath in paths:
                if self.fetcher.hasFile(kpath) and self.fetcher.hasFile(ipath):
                    kernelpath = kpath
                    initrdpath = ipath

        if not kernelpath or not initrdpath:
            raise RuntimeError(_("Couldn't find %(type)s kernel for "
                                 "%(distro)s tree.") %
                                 {"distro": self.name, "type" : self.type})

        return self._kernelFetchHelper(guest, kernelpath, initrdpath)

    def acquireBootDisk(self, guest):
        ignore = guest

        if self._hasTreeinfo():
            return self.fetcher.acquireFile(self._getTreeinfoMedia("boot.iso"))
        else:
            for path in self._boot_iso_paths:
                if self.fetcher.hasFile(path):
                    return self.fetcher.acquireFile(path)
            raise RuntimeError(_("Could not find boot.iso in %s tree." %
                               self.name))

    def _check_osvariant_valid(self, os_variant):
        return osdict.lookup_os(os_variant) is not None

    def get_osdict_info(self):
        """
        Return (distro, variant) tuple, checking to make sure they are valid
        osdict entries
        """
        if not self.os_variant:
            return None

        if not self._check_osvariant_valid(self.os_variant):
            logging.debug("%s set os_variant to %s, which is not in osdict.",
                          self, self.os_variant)
            return None

        return self.os_variant

    def _get_method_arg(self):
        return "method"

    def _hasTreeinfo(self):
        # all Red Hat based distros should have .treeinfo, perhaps others
        # will in time
        if not (self.treeinfo is None):
            return True

        if not self.uses_treeinfo or not self.fetcher.hasFile(".treeinfo"):
            return False

        logging.debug("Detected .treeinfo file")

        tmptreeinfo = self.fetcher.acquireFile(".treeinfo")
        try:
            self.treeinfo = ConfigParser.SafeConfigParser()
            self.treeinfo.read(tmptreeinfo)
        finally:
            os.unlink(tmptreeinfo)
        return True

    def _getTreeinfoMedia(self, mediaName):
        if self.type == "xen":
            t = "xen"
        else:
            t = self.treeinfo.get("general", "arch")

        return self.treeinfo.get("images-%s" % t, mediaName)

    def _fetchAndMatchRegex(self, filename, regex):
        # Fetch 'filename' and return True/False if it matches the regex
        local_file = None
        try:
            try:
                local_file = self.fetcher.acquireFile(filename)
            except:
                return False

            f = open(local_file, "r")
            try:
                while 1:
                    buf = f.readline()
                    if not buf:
                        break
                    if re.match(regex, buf):
                        return True
            finally:
                f.close()
        finally:
            if local_file is not None:
                os.unlink(local_file)

        return False

    def _kernelFetchHelper(self, guest, kernelpath, initrdpath):
        # Simple helper for fetching kernel + initrd and performing
        # cleanup if necessary
        kernel = self.fetcher.acquireFile(kernelpath)
        args = ''

        if not self.fetcher.location.startswith("/"):
            args += "%s=%s" % (self._get_method_arg(), self.fetcher.location)

        if guest.installer.extraargs:
            args += " " + guest.installer.extraargs

        try:
            initrd = self.fetcher.acquireFile(initrdpath)
            return kernel, initrd, args
        except:
            os.unlink(kernel)
            raise


class GenericDistro(Distro):
    """
    Generic distro store. Check well known paths for kernel locations
    as a last resort if we can't recognize any actual distro
    """

    name = "Generic"
    os_variant = "linux"
    uses_treeinfo = True

    _xen_paths = [("images/xen/vmlinuz",
                    "images/xen/initrd.img"),           # Fedora
                ]
    _hvm_paths = [("images/pxeboot/vmlinuz",
                    "images/pxeboot/initrd.img"),       # Fedora
                ]
    _iso_paths = ["images/boot.iso",                   # RH/Fedora
                   "boot/boot.iso",                     # Suse
                   "current/images/netboot/mini.iso",   # Debian
                   "install/images/boot.iso",           # Mandriva
                ]

    # Holds values to use when actually pulling down media
    _valid_kernel_path = None
    _valid_iso_path = None

    def isValidStore(self):
        if self._hasTreeinfo():
            # Use treeinfo to pull down media paths
            if self.type == "xen":
                typ = "xen"
            else:
                typ = self.treeinfo.get("general", "arch")
            kernelSection = "images-%s" % typ
            isoSection = "images-%s" % self.treeinfo.get("general", "arch")

            if self.treeinfo.has_section(kernelSection):
                try:
                    self._valid_kernel_path = (
                        self._getTreeinfoMedia("kernel"),
                        self._getTreeinfoMedia("initrd"))
                except (ConfigParser.NoSectionError,
                        ConfigParser.NoOptionError), e:
                    logging.debug(e)

            if self.treeinfo.has_section(isoSection):
                try:
                    self._valid_iso_path = self.treeinfo.get(isoSection,
                                                             "boot.iso")
                except ConfigParser.NoOptionError, e:
                    logging.debug(e)

        if self.type == "xen":
            kern_list = self._xen_paths
        else:
            kern_list = self._hvm_paths

        # If validated media paths weren't found (no treeinfo), check against
        # list of media location paths.
        for kern, init in kern_list:
            if (self._valid_kernel_path is None and
                self.fetcher.hasFile(kern) and
                self.fetcher.hasFile(init)):
                self._valid_kernel_path = (kern, init)
                break

        for iso in self._iso_paths:
            if (self._valid_iso_path is None and
                self.fetcher.hasFile(iso)):
                self._valid_iso_path = iso
                break

        if self._valid_kernel_path or self._valid_iso_path:
            return True
        return False

    def acquireKernel(self, guest):
        if self._valid_kernel_path is None:
            raise ValueError(_("Could not find a kernel path for virt type "
                               "'%s'" % self.type))

        return self._kernelFetchHelper(guest,
                                       self._valid_kernel_path[0],
                                       self._valid_kernel_path[1])

    def acquireBootDisk(self, guest):
        if self._valid_iso_path is None:
            raise ValueError(_("Could not find a boot iso path for this tree."))

        return self.fetcher.acquireFile(self._valid_iso_path)


class RedHatDistro(Distro):
    """
    Base image store for any Red Hat related distros which have
    a common layout
    """
    os_variant = "linux"
    _version_number = None

    uses_treeinfo = True
    _boot_iso_paths   = ["images/boot.iso"]
    _hvm_kernel_paths = [("images/pxeboot/vmlinuz",
                           "images/pxeboot/initrd.img")]
    _xen_kernel_paths = [("images/xen/vmlinuz",
                           "images/xen/initrd.img")]

    def isValidStore(self):
        raise NotImplementedError()

    def _get_method_arg(self):
        if (self._version_number is not None and
            ((self.urldistro is "rhel" and self._version_number >= 7) or
             (self.urldistro is "fedora" and self._version_number >= 19))):
            return "inst.repo"
        return "method"


# Fedora distro check
class FedoraDistro(RedHatDistro):
    name = "Fedora"
    urldistro = "fedora"

    def _latestFedoraVariant(self):
        """
        Search osdict list, find newest fedora version listed
        """
        ret = None
        for osinfo in osdict.list_os(typename="linux"):
            if osinfo.name.startswith("fedora") and "unknown" not in osinfo.name:
                # First fedora* occurrence should be the newest
                ret = osinfo.name
                break

        return ret, int(ret[6:])

    def isValidStore(self):
        if not self._hasTreeinfo():
            return self.fetcher.hasFile("Fedora")

        if not re.match(".*Fedora.*", self.treeinfo.get("general", "family")):
            return False

        lateststr, latestnum = self._latestFedoraVariant()
        ver = self.treeinfo.get("general", "version")
        if not ver:
            return False

        if ver == "development" or ver == "rawhide":
            self._version_number = latestnum
            self.os_variant = lateststr
            return

        if "_" in ver:
            ver = ver.split("_")[0]
        vernum = int(str(ver).split("-")[0])
        if vernum > latestnum:
            self.os_variant = lateststr
        else:
            self.os_variant = "fedora" + str(vernum)

        self._version_number = vernum
        return True


# Red Hat Enterprise Linux distro check
class RHELDistro(RedHatDistro):
    name = "Red Hat Enterprise Linux"
    urldistro = "rhel"

    def isValidStore(self):
        if self._hasTreeinfo():
            m = re.match(".*Red Hat Enterprise Linux.*",
                         self.treeinfo.get("general", "family"))
            ret = (m is not None)

            if ret:
                self._variantFromVersion()
            return ret

        if (self.fetcher.hasFile("Server") or
            self.fetcher.hasFile("Client")):
            self.os_variant = "rhel5"
            return True
        return self.fetcher.hasFile("RedHat")


    ################################
    # osdict autodetection helpers #
    ################################

    def _parseTreeinfoVersion(self, verstr):
        def _safeint(c):
            try:
                val = int(c)
            except:
                val = 0
            return val

        version = _safeint(verstr[0])
        update = 0

        # RHEL has version=5.4, scientific linux=54
        updinfo = verstr.split(".")
        if len(updinfo) > 1:
            update = _safeint(updinfo[1])
        elif len(verstr) > 1:
            update = _safeint(verstr[1])

        return version, update

    def _variantFromVersion(self):
        ver = self.treeinfo.get("general", "version")
        name = None
        if self.treeinfo.has_option("general", "name"):
            name = self.treeinfo.get("general", "name")
        if not ver:
            return

        if name and name.startswith("Red Hat Enterprise Linux Server for ARM"):
            # Kind of a hack, but good enough for the time being
            version = 7
            update = 0
        else:
            version, update = self._parseTreeinfoVersion(ver)

        self._version_number = version
        self._setRHELVariant(version, update)

    def _setRHELVariant(self, version, update):
        base = "rhel" + str(version)
        if update < 0:
            update = 0

        ret = None
        while update >= 0:
            tryvar = base + ".%s" % update
            if not self._check_osvariant_valid(tryvar):
                update -= 1
                continue

            ret = tryvar
            break

        if not ret:
            # Try plain rhel5, rhel6, whatev
            if self._check_osvariant_valid(base):
                ret = base

        if ret:
            self.os_variant = ret


# CentOS distro check
class CentOSDistro(RHELDistro):
    name = "CentOS"
    urldistro = None

    def isValidStore(self):
        if not self._hasTreeinfo():
            return self.fetcher.hasFile("CentOS")

        m = re.match(".*CentOS.*", self.treeinfo.get("general", "family"))
        ret = (m is not None)
        if ret:
            self._variantFromVersion()
        return ret


# Scientific Linux distro check
class SLDistro(RHELDistro):
    name = "Scientific Linux"
    urldistro = None

    _boot_iso_paths = RHELDistro._boot_iso_paths + ["images/SL/boot.iso"]
    _hvm_kernel_paths = RHELDistro._hvm_kernel_paths + [
        ("images/SL/pxeboot/vmlinuz", "images/SL/pxeboot/initrd.img")]

    def isValidStore(self):
        if self._hasTreeinfo():
            m = re.match(".*Scientific Linux.*",
                         self.treeinfo.get("general", "family"))
            ret = (m is not None)

            if ret:
                self._variantFromVersion()
            return ret

        return self.fetcher.hasFile("SL")


class SuseDistro(Distro):
    name = "SUSE"
    urldistro = "suse"
    os_variant = "linux"

    _boot_iso_paths   = ["boot/boot.iso"]

    def __init__(self, *args, **kwargs):
        Distro.__init__(self, *args, **kwargs)
        if re.match(r'i[4-9]86', self.arch):
            self.arch = 'i386'

        # Tested with Opensuse >= 10.2, 11, and sles 10
        self._hvm_kernel_paths = [("boot/%s/loader/linux" % self.arch,
                                    "boot/%s/loader/initrd" % self.arch)]

        # Matches Opensuse > 10.2 and sles 10
        self._xen_kernel_paths = [("boot/%s/vmlinuz-xen" % self.arch,
                                    "boot/%s/initrd-xen" % self.arch)]

    def isValidStore(self):
        if not self.fetcher.hasFile("directory.yast"):
            return False

        self.os_variant = self._detect_osdict_from_url()
        return True

    def _get_method_arg(self):
        return "install"

    ################################
    # osdict autodetection helpers #
    ################################

    def _detect_osdict_from_url(self):
        root = "opensuse"
        oses = [n for n in osdict.list_os() if n.name.startswith(root)]

        for osobj in oses:
            codename = osobj.name[len(root):]
            if re.search("/%s/" % codename, self.uri):
                return osobj.name
        return self.os_variant


class DebianDistro(Distro):
    # ex. http://ftp.egr.msu.edu/debian/dists/sarge/main/installer-i386/
    # daily builds: http://d-i.debian.org/daily-images/amd64/
    name = "Debian"
    urldistro = "debian"
    os_variant = "linux"

    def __init__(self, *args, **kwargs):
        Distro.__init__(self, *args, **kwargs)
        if self.uri.count("i386"):
            self._treeArch = "i386"
        elif self.uri.count("amd64"):
            self._treeArch = "amd64"
        else:
            self._treeArch = "i386"

        if re.match(r'i[4-9]86', self.arch):
            self.arch = 'i386'

        self._installer_name = self.name.lower() + "-" + "installer"
        self._prefix = 'current/images'
        self._set_media_paths()

    def _set_media_paths(self):
        # Use self._prefix to set media paths
        self._boot_iso_paths   = ["%s/netboot/mini.iso" % self._prefix]
        hvmroot = "%s/netboot/%s/%s/" % (self._prefix,
                                         self._installer_name,
                                         self._treeArch)
        xenroot = "%s/netboot/xen/" % self._prefix
        self._hvm_kernel_paths = [(hvmroot + "linux", hvmroot + "initrd.gz")]
        self._xen_kernel_paths = [(xenroot + "vmlinuz",
                                    xenroot + "initrd.gz")]

    def isValidStore(self):
        if self.fetcher.hasFile("%s/MANIFEST" % self._prefix):
            # For regular trees
            pass
        elif self.fetcher.hasFile("daily/MANIFEST"):
            # For daily trees
            self._prefix = "daily"
            self._set_media_paths()
        else:
            return False

        filename = "%s/MANIFEST" % self._prefix
        regex = ".*%s.*" % self._installer_name
        if not self._fetchAndMatchRegex(filename, regex):
            logging.debug("Regex didn't match, not a %s distro", self.name)
            return False

        self.os_variant = self._detect_osdict_from_url()
        return True


    ################################
    # osdict autodetection helpers #
    ################################

    def _detect_osdict_from_url(self):
        root = self.name.lower()
        oses = [n for n in osdict.list_os() if n.name.startswith(root)]

        if self._prefix == "daily":
            return oses[0].name

        for osobj in oses:
            # name looks like 'Debian Sarge'
            if " " not in osobj.label:
                continue

            codename = osobj.label.lower().split()[1]
            if ("/%s/" % codename) in self.uri:
                return osobj.name
        return self.os_variant


class UbuntuDistro(DebianDistro):
    # http://archive.ubuntu.com/ubuntu/dists/natty/main/installer-amd64/
    name = "Ubuntu"
    urldistro = "ubuntu"

    def isValidStore(self):
        if self.fetcher.hasFile("%s/MANIFEST" % self._prefix):
            # For regular trees
            filename = "%s/MANIFEST" % self._prefix
            regex = ".*%s.*" % self._installer_name
        elif self.fetcher.hasFile("install/netboot/version.info"):
            # For trees based on ISO's
            self._prefix = "install"
            self._set_media_paths()
            filename = "%s/netboot/version.info" % self._prefix
            regex = "%s*" % self.name
        else:
            return False

        if not self._fetchAndMatchRegex(filename, regex):
            logging.debug("Regex didn't match, not a %s distro", self.name)
            return False

        self.os_variant = self._detect_osdict_from_url()
        return True


class MandrivaDistro(Distro):
    # ftp://ftp.uwsg.indiana.edu/linux/mandrake/official/2007.1/x86_64/
    name = "Mandriva/Mageia"
    urldistro = "mandriva"
    os_variant = "linux"

    _boot_iso_paths = ["install/images/boot.iso"]
    # Kernels for HVM: valid for releases 2007.1, 2008.*, 2009.0
    _hvm_kernel_paths = [("isolinux/alt0/vmlinuz", "isolinux/alt0/all.rdz")]
    _xen_kernel_paths = []

    def isValidStore(self):
        # Don't support any paravirt installs
        if self.type is not None and self.type != "hvm":
            return False

        # Mandriva websites / media appear to have a VERSION
        # file in top level which we can use as our 'magic'
        # check for validity
        if not self.fetcher.hasFile("VERSION"):
            return False

        for name in ["Mandriva", "Mageia"]:
            if self._fetchAndMatchRegex("VERSION", ".*%s.*" % name):
                return True

        logging.debug("Regex didn't match, not a %s distro", self.name)
        return False


class ALTLinuxDistro(Distro):
    # altlinux doesn't have installable URLs, so this is just for a
    # mounted ISO
    name = "ALT Linux"
    urldistro = "altlinux"
    os_variant = "linux"

    _boot_iso_paths = [("altinst", "live")]
    _hvm_kernel_paths = [("syslinux/alt0/vmlinuz", "syslinux/alt0/full.cz")]
    _xen_kernel_paths = []

    def isValidStore(self):
        # Don't support any paravirt installs
        if self.type is not None and self.type != "hvm":
            return False

        if not self.fetcher.hasFile(".disk/info"):
            return False

        if self._fetchAndMatchRegex(".disk/info", ".*%s.*" % self.name):
            return True

        logging.debug("Regex didn't match, not a %s distro", self.name)
        return False


# Build list of all *Distro classes
def _build_distro_list():
    allstores = []
    for obj in globals().values():
        if type(obj) is type and issubclass(obj, Distro) and obj.name:
            allstores.append(obj)

    seen_urldistro = []
    for obj in allstores:
        if obj.urldistro and obj.urldistro in seen_urldistro:
            raise RuntimeError("programming error: duplicate urldistro=%s" %
                               obj.urldistro)
        seen_urldistro.append(obj.urldistro)

    return allstores

_allstores = _build_distro_list()

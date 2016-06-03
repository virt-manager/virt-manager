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
import StringIO
import subprocess
import tempfile
import urllib2
import urlparse

import requests

from .osdict import OSDB


#########################################################################
# Backends for the various URL types we support (http, ftp, nfs, local) #
#########################################################################

class _URLFetcher(object):
    """
    This is a generic base class for fetching/extracting files from
    a media source, such as CD ISO, NFS server, or HTTP/FTP server
    """
    _block_size = 16384

    def __init__(self, location, scratchdir, meter):
        self.location = location
        self.scratchdir = scratchdir
        self.meter = meter

        self._srcdir = None

        logging.debug("Using scratchdir=%s", scratchdir)


    ####################
    # Internal helpers #
    ####################

    def _make_full_url(self, filename):
        """
        Generate a full fetchable URL from the passed filename, which
        is relative to the self.location
        """
        ret = self._srcdir or self.location
        if not filename:
            return ret

        if not ret.endswith("/"):
            ret += "/"
        return ret + filename

    def _grabURL(self, filename, fileobj):
        """
        Download the filename from self.location, and write contents to
        fileobj
        """
        url = self._make_full_url(filename)

        try:
            urlobj, size = self._grabber(url)
        except Exception, e:
            raise ValueError(_("Couldn't acquire file %s: %s") %
                               (url, str(e)))

        logging.debug("Fetching URI: %s", url)
        self.meter.start(
            text=_("Retrieving file %s...") % os.path.basename(filename),
            size=size)

        total = self._write(urlobj, fileobj)
        self.meter.end(total)

    def _write(self, urlobj, fileobj):
        """
        Write the contents of urlobj to python file like object fileobj
        """
        total = 0
        while 1:
            buff = urlobj.read(self._block_size)
            if not buff:
                break
            fileobj.write(buff)
            total += len(buff)
            self.meter.update(total)
        return total

    def _grabber(self, url):
        """
        Returns the urlobj, size for the passed URL. urlobj is whatever
        data needs to be passed to self._write
        """
        raise NotImplementedError("must be implemented in subclass")


    ##############
    # Public API #
    ##############

    def prepareLocation(self):
        """
        Perform any necessary setup
        """
        pass

    def cleanupLocation(self):
        """
        Perform any necessary cleanup
        """
        pass

    def _hasFile(self, url):
        raise NotImplementedError("Must be implemented in subclass")

    def hasFile(self, filename):
        """
        Return True if self.location has the passed filename
        """
        url = self._make_full_url(filename)
        ret = self._hasFile(url)
        logging.debug("hasFile(%s) returning %s", url, ret)
        return ret

    def acquireFile(self, filename):
        """
        Grab the passed filename from self.location and save it to
        a temporary file, returning the temp filename
        """
        prefix = "virtinst-" + os.path.basename(filename) + "."

        # pylint: disable=redefined-variable-type
        if "VIRTINST_TEST_SUITE" in os.environ:
            fn = os.path.join("/tmp", prefix)
            fileobj = file(fn, "w")
        else:
            fileobj = tempfile.NamedTemporaryFile(
                dir=self.scratchdir, prefix=prefix, delete=False)
            fn = fileobj.name

        self._grabURL(filename, fileobj)
        logging.debug("Saved file to " + fn)
        return fn

    def acquireFileContent(self, filename):
        """
        Grab the passed filename from self.location and return it as a string
        """
        fileobj = StringIO.StringIO()
        self._grabURL(filename, fileobj)
        return fileobj.getvalue()


class _HTTPURLFetcher(_URLFetcher):
    def _hasFile(self, url):
        """
        We just do a HEAD request to see if the file exists
        """
        try:
            response = requests.head(url, allow_redirects=True)
            response.raise_for_status()
        except Exception, e:
            logging.debug("HTTP hasFile request failed: %s", str(e))
            return False
        return True

    def _grabber(self, url):
        """
        Use requests for this
        """
        response = requests.get(url, stream=True)
        response.raise_for_status()
        try:
            size = int(response.headers.get('content-length'))
        except:
            size = None
        return response, size

    def _write(self, urlobj, fileobj):
        """
        The requests object doesn't have a file-like read() option, so
        we need to implemente it ourselves
        """
        total = 0
        for data in urlobj.iter_content(chunk_size=self._block_size):
            fileobj.write(data)
            total += len(data)
            self.meter.update(total)
        return total


class _FTPURLFetcher(_URLFetcher):
    _ftp = None

    def prepareLocation(self):
        if self._ftp:
            return

        try:
            parsed = urlparse.urlparse(self.location)
            self._ftp = ftplib.FTP()
            self._ftp.connect(parsed.hostname, parsed.port)
            self._ftp.login()
        except Exception, e:
            raise ValueError(_("Opening URL %s failed: %s.") %
                              (self.location, str(e)))

    def _grabber(self, url):
        """
        Use urllib2 and ftplib to grab the file
        """
        request = urllib2.Request(url)
        urlobj = urllib2.urlopen(request)
        size = self._ftp.size(urlparse.urlparse(url)[2])
        return urlobj, size


    def cleanupLocation(self):
        if not self._ftp:
            return

        try:
            self._ftp.quit()
        except:
            logging.debug("Error quitting ftp connection", exc_info=True)

        self._ftp = None

    def _hasFile(self, url):
        path = urlparse.urlparse(url)[2]

        try:
            try:
                # If it's a file
                self._ftp.size(path)
            except ftplib.all_errors:
                # If it's a dir
                self._ftp.cwd(path)
        except ftplib.all_errors, e:
            logging.debug("FTP hasFile: couldn't access %s: %s",
                          url, str(e))
            return False

        return True


class _LocalURLFetcher(_URLFetcher):
    """
    For grabbing files from a local directory
    """
    def _hasFile(self, url):
        return os.path.exists(url)

    def _grabber(self, url):
        urlobj = file(url, "r")
        size = os.path.getsize(url)
        return urlobj, size


class _MountedURLFetcher(_LocalURLFetcher):
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
            self._srcdir = os.environ["VIRTINST_TEST_URL_DIR"]
        else:
            self._srcdir = tempfile.mkdtemp(prefix="virtinstmnt.",
                                           dir=self.scratchdir)
        mountcmd = "/bin/mount"

        logging.debug("Preparing mount at " + self._srcdir)
        if self.location.startswith("nfs:"):
            cmd = [mountcmd, "-o", "ro", self.location[4:], self._srcdir]
        else:
            if stat.S_ISBLK(os.stat(self.location)[stat.ST_MODE]):
                mountopt = "ro"
            else:
                mountopt = "ro,loop"
            cmd = [mountcmd, "-o", mountopt, self.location, self._srcdir]

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

        logging.debug("Cleaning up mount at " + self._srcdir)
        try:
            if not self._in_test_suite:
                cmd = ["/bin/umount", self._srcdir]
                subprocess.call(cmd)
                try:
                    os.rmdir(self._srcdir)
                except:
                    pass
        finally:
            self._mounted = False


def fetcherForURI(uri, *args, **kwargs):
    if uri.startswith("http://") or uri.startswith("https://"):
        fclass = _HTTPURLFetcher
    elif uri.startswith("ftp://"):
        fclass = _FTPURLFetcher
    elif uri.startswith("nfs:"):
        fclass = _MountedURLFetcher
    elif os.path.isdir(uri):
        # Pointing to a local tree
        fclass = _LocalURLFetcher
    else:
        # Pointing to a path, like an .iso to mount
        fclass = _MountedURLFetcher
    return fclass(uri, *args, **kwargs)


###############################################
# Helpers for detecting distro from given URL #
###############################################

def _grabTreeinfo(fetcher):
    """
    See if the URL has treeinfo, and if so return it as a ConfigParser
    object.
    """
    try:
        tmptreeinfo = fetcher.acquireFile(".treeinfo")
    except ValueError:
        return None

    try:
        treeinfo = ConfigParser.SafeConfigParser()
        treeinfo.read(tmptreeinfo)
    finally:
        os.unlink(tmptreeinfo)

    try:
        treeinfo.get("general", "family")
    except ConfigParser.NoSectionError:
        logging.debug("Did not find 'family' section in treeinfo")
        return None

    logging.debug("treeinfo family=%s", treeinfo.get("general", "family"))
    return treeinfo


def _distroFromSUSEContent(fetcher, arch, vmtype=None):
    # Parse content file for the 'LABEL' field containing the distribution name
    # None if no content, GenericDistro if unknown label type.
    try:
        cbuf = fetcher.acquireFileContent("content")
    except ValueError:
        return None

    distribution = None
    distro_version = None
    distro_summary = None
    distro_distro = None
    distro_arch = None

    lines = cbuf.splitlines()[1:]
    for line in lines:
        if line.startswith("LABEL "):
            distribution = line.split(' ', 1)
        elif line.startswith("DISTRO "):
            distro_distro = line.rsplit(',', 1)
        elif line.startswith("VERSION "):
            distro_version = line.split(' ', 1)
            if len(distro_version) > 1:
                d_version = distro_version[1].split('-', 1)
                if len(d_version) > 1:
                    distro_version[1] = d_version[0]
        elif line.startswith("SUMMARY "):
            distro_summary = line.split(' ', 1)
        elif line.startswith("BASEARCHS "):
            distro_arch = line.split(' ', 1)
        elif line.startswith("DEFAULTBASE "):
            distro_arch = line.split(' ', 1)
        elif line.startswith("REPOID "):
            distro_arch = line.rsplit('/', 1)
        if distribution and distro_version and distro_arch:
            break

    if not distribution:
        if distro_summary:
            distribution = distro_summary
        elif distro_distro:
            distribution = distro_distro
    if distro_arch:
        arch = distro_arch[1].strip()
        # Fix for 13.2 official oss repo
        if arch.find("i586-x86_64") != -1:
            arch = "x86_64"
    else:
        if cbuf.find("x86_64") != -1:
            arch = "x86_64"
        elif cbuf.find("i586") != -1:
            arch = "i586"
        elif cbuf.find("s390x") != -1:
            arch = "s390x"

    def _parse_sle_distribution(d):
        sle_version = d[1].strip().rsplit(' ')[4]
        if len(d[1].strip().rsplit(' ')) > 5:
            sle_version = sle_version + '.' + d[1].strip().rsplit(' ')[5][2]
        return ['VERSION', sle_version]

    dclass = GenericDistro
    if distribution:
        if re.match(".*SUSE Linux Enterprise Server*", distribution[1]) or \
            re.match(".*SUSE SLES*", distribution[1]):
            dclass = SLESDistro
            if distro_version is None:
                distro_version = _parse_sle_distribution(distribution)
        elif re.match(".*SUSE Linux Enterprise Desktop*", distribution[1]):
            dclass = SLEDDistro
            if distro_version is None:
                distro_version = _parse_sle_distribution(distribution)
        elif re.match(".*openSUSE.*", distribution[1]):
            dclass = OpensuseDistro
            if distro_version is None:
                distro_version = ['VERSION', distribution[0].strip().rsplit(':')[4]]

    if distro_version is None:
        return None

    ob = dclass(fetcher, arch, vmtype)
    if dclass != GenericDistro:
        ob.version_from_content = distro_version

    # Explictly call this, so we populate os_type/variant info
    ob.isValidStore()

    return ob


def getDistroStore(guest, fetcher):
    stores = []
    logging.debug("Finding distro store for location=%s", fetcher.location)

    arch = guest.os.arch
    _type = guest.os.os_type

    urldistro = None
    if guest.os_variant:
        urldistro = OSDB.lookup_os(guest.os_variant).urldistro

    treeinfo = _grabTreeinfo(fetcher)
    if not treeinfo:
        dist = _distroFromSUSEContent(fetcher, arch, _type)
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

    if treeinfo:
        stores.sort(key=lambda x: not x.uses_treeinfo)

    for sclass in stores:
        store = sclass(fetcher, arch, _type)
        store.treeinfo = treeinfo
        if store.isValidStore():
            logging.debug("Detected distro name=%s osvariant=%s",
                          store.name, store.os_variant)
            return store

    # No distro was detected. See if the URL even resolves, and if not
    # give the user a hint that maybe they mistyped. This won't always
    # be true since some webservers don't allow directory listing.
    # http://www.redhat.com/archives/virt-tools-list/2014-December/msg00048.html
    extramsg = ""
    if not fetcher.hasFile(""):
        extramsg = (": " +
            _("The URL could not be accessed, maybe you mistyped?"))

    raise ValueError(
        _("Could not find an installable distribution at '%s'%s\n\n"
          "The location must be the root directory of an install tree.\n"
          "See virt-install man page for various distro examples." %
          (fetcher.location, extramsg)))


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
    uses_treeinfo = False

    # osdict variant value
    os_variant = None

    _boot_iso_paths = []
    _hvm_kernel_paths = []
    _xen_kernel_paths = []
    version_from_content = []

    def __init__(self, fetcher, arch, vmtype):
        self.fetcher = fetcher
        self.type = vmtype
        self.arch = arch

        self.uri = fetcher.location

        # This is set externally
        self.treeinfo = None

    def isValidStore(self):
        """Determine if uri points to a tree of the store's distro"""
        raise NotImplementedError

    def acquireKernel(self, guest):
        kernelpath = None
        initrdpath = None
        if self.treeinfo:
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

        if self.treeinfo:
            return self.fetcher.acquireFile(self._getTreeinfoMedia("boot.iso"))

        for path in self._boot_iso_paths:
            if self.fetcher.hasFile(path):
                return self.fetcher.acquireFile(path)
        raise RuntimeError(_("Could not find boot.iso in %s tree." %
                           self.name))

    def _check_osvariant_valid(self, os_variant):
        return OSDB.lookup_os(os_variant) is not None

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

    def _getTreeinfoMedia(self, mediaName):
        if self.type == "xen":
            t = "xen"
        else:
            t = self.treeinfo.get("general", "arch")

        return self.treeinfo.get("images-%s" % t, mediaName)

    def _fetchAndMatchRegex(self, filename, regex):
        # Fetch 'filename' and return True/False if it matches the regex
        try:
            content = self.fetcher.acquireFileContent(filename)
        except ValueError:
            return False

        for line in content.splitlines():
            if re.match(regex, line):
                return True

        return False

    def _kernelFetchHelper(self, guest, kernelpath, initrdpath):
        # Simple helper for fetching kernel + initrd and performing
        # cleanup if necessary
        ignore = guest
        kernel = self.fetcher.acquireFile(kernelpath)
        args = ''

        if not self.fetcher.location.startswith("/"):
            args += "%s=%s" % (self._get_method_arg(), self.fetcher.location)

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
        if self.treeinfo:
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
    uses_treeinfo = True
    _version_number = None

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

    def isValidStore(self):
        if not self.treeinfo:
            return self.fetcher.hasFile("Fedora")

        if not re.match(".*Fedora.*", self.treeinfo.get("general", "family")):
            return False

        ver = self.treeinfo.get("general", "version")
        if not ver:
            logging.debug("No version found in .treeinfo")
            return False
        logging.debug("Found treeinfo version=%s", ver)

        latest_variant = OSDB.latest_fedora_version()
        if re.match("fedora[0-9]+", latest_variant):
            latest_vernum = int(latest_variant[6:])
        else:
            logging.debug("Failed to parse version number from latest "
                "fedora variant=%s. Using safe default 22", latest_variant)
            latest_vernum = 22

        # rawhide trees changed to use version=Rawhide in Apr 2016
        if ver in ["development", "rawhide", "Rawhide"]:
            self._version_number = latest_vernum
            self.os_variant = latest_variant
            return True

        # Dev versions can be like '23_Alpha'
        if "_" in ver:
            ver = ver.split("_")[0]

        # Typical versions are like 'fedora-23'
        vernum = str(ver).split("-")[0]
        if vernum.isdigit():
            vernum = int(vernum)
        else:
            logging.debug("Failed to parse version number from treeinfo "
                "version=%s, using vernum=latest=%s", ver, latest_vernum)
            vernum = latest_vernum

        if vernum > latest_vernum:
            self.os_variant = latest_variant
        else:
            self.os_variant = "fedora" + str(vernum)

        self._version_number = vernum
        return True


# Red Hat Enterprise Linux distro check
class RHELDistro(RedHatDistro):
    name = "Red Hat Enterprise Linux"
    urldistro = "rhel"

    def isValidStore(self):
        if self.treeinfo:
            # Matches:
            #   Red Hat Enterprise Linux
            #   RHEL Atomic Host
            m = re.match(".*(Red Hat Enterprise Linux|RHEL).*",
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
    urldistro = "centos"

    def isValidStore(self):
        if not self.treeinfo:
            return self.fetcher.hasFile("CentOS")

        m = re.match(".*CentOS.*", self.treeinfo.get("general", "family"))
        ret = (m is not None)
        if ret:
            self._variantFromVersion()
            if self.os_variant:
                new_variant = self.os_variant.replace("rhel", "centos")
                if self._check_osvariant_valid(new_variant):
                    self.os_variant = new_variant
        return ret


# Scientific Linux distro check
class SLDistro(RHELDistro):
    name = "Scientific Linux"
    urldistro = None

    _boot_iso_paths = RHELDistro._boot_iso_paths + ["images/SL/boot.iso"]
    _hvm_kernel_paths = RHELDistro._hvm_kernel_paths + [
        ("images/SL/pxeboot/vmlinuz", "images/SL/pxeboot/initrd.img")]

    def isValidStore(self):
        if self.treeinfo:
            m = re.match(".*Scientific.*",
                         self.treeinfo.get("general", "family"))
            ret = (m is not None)

            if ret:
                self._variantFromVersion()
            return ret

        return self.fetcher.hasFile("SL")


class SuseDistro(Distro):
    name = "SUSE"

    _boot_iso_paths   = ["boot/boot.iso"]

    def __init__(self, *args, **kwargs):
        Distro.__init__(self, *args, **kwargs)
        if re.match(r'i[4-9]86', self.arch):
            self.arch = 'i386'

        oldkern = "linux"
        oldinit = "initrd"
        if self.arch == "x86_64":
            oldkern += "64"
            oldinit += "64"

        if self.arch == "s390x":
            self._hvm_kernel_paths = [("boot/%s/linux" % self.arch,
                                       "boot/%s/initrd" % self.arch)]
            # No Xen on s390x
            self._xen_kernel_paths = []
        else:
            # Tested with Opensuse >= 10.2, 11, and sles 10
            self._hvm_kernel_paths = [("boot/%s/loader/linux" % self.arch,
                                        "boot/%s/loader/initrd" % self.arch)]
            # Tested with Opensuse 10.0
            self._hvm_kernel_paths.append(("boot/loader/%s" % oldkern,
                                           "boot/loader/%s" % oldinit))
            # Tested with SLES 12 for ppc64le
            self._hvm_kernel_paths.append(("boot/%s/linux" % self.arch,
                                           "boot/%s/initrd" % self.arch))

            # Matches Opensuse > 10.2 and sles 10
            self._xen_kernel_paths = [("boot/%s/vmlinuz-xen" % self.arch,
                                        "boot/%s/initrd-xen" % self.arch)]

    def _variantFromVersion(self):
        distro_version = self.version_from_content[1].strip()
        version = distro_version.split('.', 1)[0].strip()
        self.os_variant = self.urldistro
        if int(version) >= 10:
            if self.os_variant.startswith(("sles", "sled")):
                sp_version = None
                if len(distro_version.split('.', 1)) == 2:
                    sp_version = 'sp' + distro_version.split('.', 1)[1].strip()
                self.os_variant += version
                if sp_version:
                    self.os_variant += sp_version
            else:
                # Tumbleweed 8 digit date
                if len(version) == 8:
                    self.os_variant += "tumbleweed"
                else:
                    self.os_variant += distro_version
        else:
            self.os_variant += "9"

    def isValidStore(self):
        # self.version_from_content is the VERSION line from the contents file
        if (not self.version_from_content or
            self.version_from_content[1] is None):
            return False

        self._variantFromVersion()

        self.os_variant = self._detect_osdict_from_url()

        # Reset kernel name for sle11 source on s390x
        if self.arch == "s390x":
            if self.os_variant == "sles11" or self.os_variant == "sled11":
                self._hvm_kernel_paths = [("boot/%s/vmrdr.ikr" % self.arch,
                                           "boot/%s/initrd" % self.arch)]

        return True

    def _get_method_arg(self):
        return "install"

    ################################
    # osdict autodetection helpers #
    ################################

    def _detect_osdict_from_url(self):
        root = "opensuse"
        oses = [n for n in OSDB.list_os() if n.name.startswith(root)]

        for osobj in oses:
            codename = osobj.name[len(root):]
            if re.search("/%s/" % codename, self.uri):
                return osobj.name
        return self.os_variant


class SLESDistro(SuseDistro):
    urldistro = "sles"


class SLEDDistro(SuseDistro):
    urldistro = "sled"


# Suse  image store is harder - we fetch the kernel RPM and a helper
# RPM and then munge bits together to generate a initrd
class OpensuseDistro(SuseDistro):
    urldistro = "opensuse"


class DebianDistro(Distro):
    # ex. http://ftp.egr.msu.edu/debian/dists/sarge/main/installer-i386/
    # daily builds: http://d-i.debian.org/daily-images/amd64/
    name = "Debian"
    urldistro = "debian"

    def __init__(self, *args, **kwargs):
        Distro.__init__(self, *args, **kwargs)

        # Pull the tree's arch out of the URL text
        self._treeArch = "i386"
        for pattern in ["^.*/installer-(\w+)/?$",
                        "^.*/daily-images/(\w+)/?$"]:
            arch = re.findall(pattern, self.uri)
            if arch:
                self._treeArch = arch[0]
                break

        self._url_prefix = 'current/images'
        self._installer_dirname = self.name.lower() + "-installer"
        self._set_media_paths()

    def _set_media_paths(self):
        self._boot_iso_paths   = ["%s/netboot/mini.iso" % self._url_prefix]

        hvmroot = "%s/netboot/%s/%s/" % (self._url_prefix,
                                         self._installer_dirname,
                                         self._treeArch)
        initrd_basename = "initrd.gz"
        kernel_basename = "linux"
        if self._treeArch in ["ppc64el"]:
            kernel_basename = "vmlinux"
        self._hvm_kernel_paths = [
            (hvmroot + kernel_basename, hvmroot + initrd_basename)]

        xenroot = "%s/netboot/xen/" % self._url_prefix
        self._xen_kernel_paths = [(xenroot + "vmlinuz", xenroot + "initrd.gz")]

    def isValidStore(self):
        if self.fetcher.hasFile("%s/MANIFEST" % self._url_prefix):
            # For regular trees
            pass
        elif self.fetcher.hasFile("daily/MANIFEST"):
            # For daily trees
            self._url_prefix = "daily"
            self._set_media_paths()
        else:
            return False

        filename = "%s/MANIFEST" % self._url_prefix
        regex = ".*%s.*" % self._installer_dirname
        if not self._fetchAndMatchRegex(filename, regex):
            logging.debug("Regex didn't match, not a %s distro", self.name)
            return False

        self.os_variant = self._detect_debian_osdict_from_url()
        return True


    ################################
    # osdict autodetection helpers #
    ################################

    def _detect_debian_osdict_from_url(self):
        root = self.name.lower()
        oses = [n for n in OSDB.list_os() if n.name.startswith(root)]

        if self._url_prefix == "daily":
            logging.debug("Appears to be debian 'daily' URL, using latest "
                "debian OS")
            return oses[0].name

        for osobj in oses:
            if osobj.codename:
                # Ubuntu codenames look like 'Warty Warthog'
                codename = osobj.codename.split()[0].lower()
            else:
                if " " not in osobj.label:
                    continue
                # Debian labels look like 'Debian Sarge'
                codename = osobj.label.split()[1].lower()

            if ("/%s/" % codename) in self.uri:
                logging.debug("Found codename=%s in the URL string", codename)
                return osobj.name

        logging.debug("Didn't find any known codename in the URL string")
        return self.os_variant


class UbuntuDistro(DebianDistro):
    # http://archive.ubuntu.com/ubuntu/dists/natty/main/installer-amd64/
    name = "Ubuntu"
    urldistro = "ubuntu"

    def isValidStore(self):
        if self.fetcher.hasFile("%s/MANIFEST" % self._url_prefix):
            # For regular trees
            filename = "%s/MANIFEST" % self._url_prefix
            regex = ".*%s.*" % self._installer_dirname
        elif self.fetcher.hasFile("install/netboot/version.info"):
            # For trees based on ISO's
            self._url_prefix = "install"
            self._set_media_paths()
            filename = "%s/netboot/version.info" % self._url_prefix
            regex = "%s*" % self.name
        elif self.fetcher.hasFile(".disk/info") and self.arch == "s390x":
            self._hvm_kernel_paths += [("boot/kernel.ubuntu", "boot/initrd.ubuntu")]
            self._xen_kernel_paths += [("boot/kernel.ubuntu", "boot/initrd.ubuntu")]
            filename = ".disk/info"
            regex = "%s*" % self.name
        else:
            return False

        if not self._fetchAndMatchRegex(filename, regex):
            logging.debug("Regex didn't match, not a %s distro", self.name)
            return False

        self.os_variant = self._detect_debian_osdict_from_url()
        return True


class MandrivaDistro(Distro):
    # ftp://ftp.uwsg.indiana.edu/linux/mandrake/official/2007.1/x86_64/
    name = "Mandriva/Mageia"
    urldistro = "mandriva"

    _boot_iso_paths = ["install/images/boot.iso"]
    _xen_kernel_paths = []

    def __init__(self, *args, **kwargs):
        Distro.__init__(self, *args, **kwargs)
        self._hvm_kernel_paths = []

        # At least Mageia 5 uses arch in the names
        self._hvm_kernel_paths += [
            ("isolinux/%s/vmlinuz" % self.arch,
             "isolinux/%s/all.rdz" % self.arch)]

        # Kernels for HVM: valid for releases 2007.1, 2008.*, 2009.0
        self._hvm_kernel_paths += [
            ("isolinux/alt0/vmlinuz", "isolinux/alt0/all.rdz")]


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

    # Always stick GenericDistro at the end, since it's a catchall
    allstores.remove(GenericDistro)
    allstores.append(GenericDistro)

    return allstores

_allstores = _build_distro_list()

#
# Represents OS distribution specific install data
#
# Copyright 2006-2007  Red Hat, Inc.
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
import gzip
import re
import tempfile
import socket
import ConfigParser

import virtinst
import osdict
from virtinst import _util
from virtinst import _gettext as _

from ImageFetcher import MountedImageFetcher
from ImageFetcher import FTPImageFetcher
from ImageFetcher import HTTPImageFetcher
from ImageFetcher import DirectImageFetcher

def safeint(c):
    try:
        val = int(c)
    except:
        val = 0
    return val

def _fetcherForURI(uri, scratchdir=None):
    if uri.startswith("http://"):
        fclass = HTTPImageFetcher
    elif uri.startswith("ftp://"):
        fclass = FTPImageFetcher
    elif uri.startswith("nfs://"):
        fclass = MountedImageFetcher
    else:
        if os.path.isdir(uri):
            fclass = DirectImageFetcher
        else:
            fclass = MountedImageFetcher
    return fclass(uri, scratchdir)

def _storeForDistro(fetcher, baseuri, typ, progresscb, arch, distro=None,
                    scratchdir=None):
    stores = []
    skip_treeinfo = False
    logging.debug("Attempting to detect distro:")

    dist = virtinst.OSDistro.distroFromTreeinfo(fetcher, progresscb, baseuri,
                                                arch, typ, scratchdir)
    if dist:
        return dist
    skip_treeinfo = True

    # FIXME: This 'distro ==' doesn't cut it. 'distro' is from our os
    # dictionary, so would look like 'fedora9' or 'rhel5', so this needs
    # to be a bit more intelligent
    if distro == "fedora" or distro is None:
        stores.append(FedoraDistro)
    if distro == "rhel" or distro is None:
        stores.append(RHELDistro)
    if distro == "centos" or distro is None:
        stores.append(CentOSDistro)
    if distro == "sl" or distro is None:
        stores.append(SLDistro)
    if distro == "suse" or distro is None:
        stores.append(SuseDistro)
    if distro == "debian" or distro is None:
        stores.append(DebianDistro)
    if distro == "ubuntu" or distro is None:
        stores.append(UbuntuDistro)
    if distro == "mandriva" or distro is None:
        stores.append(MandrivaDistro)
    if distro == "mageia" or distro is None:
        stores.append(MageiaDistro)
    # XXX: this is really "nevada"
    if distro == "solaris" or distro is None:
        stores.append(SolarisDistro)
    if distro == "solaris" or distro is None:
        stores.append(OpenSolarisDistro)
    if distro == "netware" or distro is None:
        stores.append(NetWareDistro)

    stores.append(GenericDistro)

    for sclass in stores:
        store = sclass(baseuri, arch, typ, scratchdir)
        if skip_treeinfo:
            store.uses_treeinfo = False
        if store.isValidStore(fetcher, progresscb):
            return store

    raise ValueError(
        _("Could not find an installable distribution at '%s'\n"
          "The location must be the root directory of an install tree." %
          baseuri))

def _locationCheckWrapper(guest, baseuri, progresscb,
                          scratchdir, _type, arch, callback):
    fetcher = _fetcherForURI(baseuri, scratchdir)
    if guest:
        arch = guest.arch

    try:
        fetcher.prepareLocation()
    except ValueError, e:
        logging.exception("Error preparing install location")
        raise ValueError(_("Invalid install location: ") + str(e))

    try:
        store = _storeForDistro(fetcher=fetcher, baseuri=baseuri, typ=_type,
                                progresscb=progresscb, scratchdir=scratchdir,
                                arch=arch)

        return callback(store, fetcher)
    finally:
        fetcher.cleanupLocation()

def _acquireMedia(iskernel, guest, baseuri, progresscb,
                  scratchdir="/var/tmp", _type=None):

    def media_cb(store, fetcher):
        os_type, os_variant = store.get_osdict_info()
        media = None

        if iskernel:
            media = store.acquireKernel(guest, fetcher, progresscb)
        else:
            media = store.acquireBootDisk(guest, fetcher, progresscb)

        return [store, os_type, os_variant, media]

    return _locationCheckWrapper(guest, baseuri, progresscb, scratchdir, _type,
                                 None, media_cb)

# Helper method to lookup install media distro and fetch an install kernel
def acquireKernel(guest, baseuri, progresscb, scratchdir, type=None):
    iskernel = True
    return _acquireMedia(iskernel, guest, baseuri, progresscb,
                         scratchdir, type)

# Helper method to lookup install media distro and fetch a boot iso
def acquireBootDisk(guest, baseuri, progresscb, scratchdir, type=None):
    iskernel = False
    return _acquireMedia(iskernel, guest, baseuri, progresscb,
                         scratchdir, type)

def _check_ostype_valid(os_type):
    return bool(os_type in osdict.sort_helper(osdict.OS_TYPES))

def _check_osvariant_valid(os_type, os_variant):
    return bool(_check_ostype_valid(os_type) and
        os_variant in osdict.sort_helper(osdict.OS_TYPES[os_type]["variants"]))

# Attempt to detect the os type + variant for the passed location
def detectMediaDistro(location, arch):
    import urlgrabber
    progresscb = urlgrabber.progress.BaseMeter()
    guest = None
    baseuri = location
    scratchdir = "/var/tmp"
    _type = None
    def media_cb(store, ignore):
        return store

    store = _locationCheckWrapper(guest, baseuri, progresscb, scratchdir,
                                  _type, arch, media_cb)

    return store.get_osdict_info()


def distroFromTreeinfo(fetcher, progresscb, uri, arch, vmtype=None,
                       scratchdir=None):
    # Parse treeinfo 'family' field, and return the associated Distro class
    # None if no treeinfo, GenericDistro if unknown family type.
    if not fetcher.hasFile(".treeinfo"):
        return None

    tmptreeinfo = fetcher.acquireFile(".treeinfo", progresscb)
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

    ob = dclass(uri, arch, vmtype, scratchdir)
    ob.treeinfo = treeinfo

    # Explictly call this, so we populate os_type/variant info
    ob.isValidStore(fetcher, progresscb)

    return ob


# An image store is a base class for retrieving either a bootable
# ISO image, or a kernel+initrd  pair for a particular OS distribution
class Distro:

    name = ""

    # osdict type and variant values
    os_type = None
    os_variant = None

    _boot_iso_paths = []
    _hvm_kernel_paths = []
    _xen_kernel_paths = []
    uses_treeinfo = False
    method_arg = "method"

    def __init__(self, uri, arch, vmtype=None, scratchdir=None):
        self.uri = uri
        self.type = vmtype
        self.scratchdir = scratchdir
        self.arch = arch
        self.treeinfo = None

    def isValidStore(self, fetcher, progresscb):
        """Determine if uri points to a tree of the store's distro"""
        raise NotImplementedError

    def acquireKernel(self, guest, fetcher, progresscb):
        kernelpath = None
        initrdpath = None
        if self._hasTreeinfo(fetcher, progresscb):
            kernelpath = self._getTreeinfoMedia("kernel")
            initrdpath = self._getTreeinfoMedia("initrd")
        else:
            # fall back to old code
            if self.type is None or self.type == "hvm":
                paths = self._hvm_kernel_paths
            else:
                paths = self._xen_kernel_paths

            for kpath, ipath in paths:
                if fetcher.hasFile(kpath) and fetcher.hasFile(ipath):
                    kernelpath = kpath
                    initrdpath = ipath

        if not kernelpath or not initrdpath:
            raise RuntimeError(_("Couldn't find %(type)s kernel for "
                                 "%(distro)s tree.") % \
                                 { "distro": self.name, "type" : self.type })

        return self._kernelFetchHelper(fetcher, guest, progresscb, kernelpath,
                                       initrdpath)

    def acquireBootDisk(self, guest, fetcher, progresscb):
        if self._hasTreeinfo(fetcher, progresscb):
            return fetcher.acquireFile(self._getTreeinfoMedia("boot.iso"),
                                       progresscb)
        else:
            for path in self._boot_iso_paths:
                if fetcher.hasFile(path):
                    return fetcher.acquireFile(path, progresscb)
            raise RuntimeError(_("Could not find boot.iso in %s tree." % \
                               self.name))

    def get_osdict_info(self):
        """
        Return (distro, variant) tuple, checking to make sure they are valid
        osdict entries
        """
        if not self.os_type:
            return (None, None)

        if not _check_ostype_valid(self.os_type):
            logging.debug("%s set os_type to %s, which is not in osdict.",
                          self, self.os_type)
            return (None, None)

        if not self.os_variant:
            return (self.os_type, None)

        if not _check_osvariant_valid(self.os_type, self.os_variant):
            logging.debug("%s set os_variant to %s, which is not in osdict"
                          " for distro %s.",
                          self, self.os_variant, self.os_type)
            return (self.os_type, None)

        return (self.os_type, self.os_variant)

    def _hasTreeinfo(self, fetcher, progresscb):
        # all Red Hat based distros should have .treeinfo, perhaps others
        # will in time
        if not (self.treeinfo is None):
            return True

        if not self.uses_treeinfo or not fetcher.hasFile(".treeinfo"):
            return False

        logging.debug("Detected .treeinfo file")

        tmptreeinfo = fetcher.acquireFile(".treeinfo", progresscb)
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

    def _fetchAndMatchRegex(self, fetcher, progresscb, filename, regex):
        # Fetch 'filename' and return True/False if it matches the regex
        local_file = None
        try:
            try:
                local_file = fetcher.acquireFile(filename, progresscb)
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

    def _kernelFetchHelper(self, fetcher, guest, progresscb, kernelpath,
                           initrdpath):
        # Simple helper for fetching kernel + initrd and performing
        # cleanup if neccessary
        kernel = fetcher.acquireFile(kernelpath, progresscb)
        args = ''

        if not fetcher.location.startswith("/"):
            args += "%s=%s" % (self.method_arg, fetcher.location)

        if guest.extraargs:
            args += " " + guest.extraargs

        try:
            initrd = fetcher.acquireFile(initrdpath, progresscb)
            return kernel, initrd, args
        except:
            os.unlink(kernel)


class GenericDistro(Distro):
    """Generic distro store. Check well known paths for kernel locations
       as a last resort if we can't recognize any actual distro"""

    name = "Generic"
    os_type = "linux"
    uses_treeinfo = True

    _xen_paths = [ ("images/xen/vmlinuz",
                    "images/xen/initrd.img"),           # Fedora
                 ]
    _hvm_paths = [ ("images/pxeboot/vmlinuz",
                    "images/pxeboot/initrd.img"),       # Fedora
                 ]
    _iso_paths = [ "images/boot.iso",                   # RH/Fedora
                   "boot/boot.iso",                     # Suse
                   "current/images/netboot/mini.iso",   # Debian
                   "install/images/boot.iso",           # Mandriva
                 ]

    # Holds values to use when actually pulling down media
    _valid_kernel_path = None
    _valid_iso_path = None

    def isValidStore(self, fetcher, progresscb):
        if self._hasTreeinfo(fetcher, progresscb):
            # Use treeinfo to pull down media paths
            if self.type == "xen":
                typ = "xen"
            else:
                typ = self.treeinfo.get("general", "arch")
            kernelSection = "images-%s" % typ
            isoSection = "images-%s" % self.treeinfo.get("general", "arch")

            if self.treeinfo.has_section(kernelSection):
                self._valid_kernel_path = (self._getTreeinfoMedia("kernel"),
                                           self._getTreeinfoMedia("initrd"))
            if self.treeinfo.has_section(isoSection):
                self._valid_iso_path = self.treeinfo.get(isoSection, "boot.iso")

        if self.type == "xen":
            kern_list = self._xen_paths
        else:
            kern_list = self._hvm_paths

        # If validated media paths weren't found (no treeinfo), check against
        # list of media location paths.
        for kern, init in kern_list:
            if self._valid_kernel_path == None \
               and fetcher.hasFile(kern) and fetcher.hasFile(init):
                self._valid_kernel_path = (kern, init)
                break
        for iso in self._iso_paths:
            if self._valid_iso_path == None \
               and fetcher.hasFile(iso):
                self._valid_iso_path = iso
                break

        if self._valid_kernel_path or self._valid_iso_path:
            return True
        return False

    def acquireKernel(self, guest, fetcher, progresscb):
        if self._valid_kernel_path == None:
            raise ValueError(_("Could not find a kernel path for virt type "
                               "'%s'" % self.type))

        return self._kernelFetchHelper(fetcher, guest, progresscb,
                                       self._valid_kernel_path[0],
                                       self._valid_kernel_path[1])

    def acquireBootDisk(self, guest, fetcher, progresscb):
        if self._valid_iso_path == None:
            raise ValueError(_("Could not find a boot iso path for this tree."))

        return fetcher.acquireFile(self._valid_iso_path, progresscb)


# Base image store for any Red Hat related distros which have
# a common layout
class RedHatDistro(Distro):

    name = "Red Hat"
    os_type = "linux"

    uses_treeinfo = True
    _boot_iso_paths   = [ "images/boot.iso" ]
    _hvm_kernel_paths = [ ("images/pxeboot/vmlinuz",
                           "images/pxeboot/initrd.img") ]
    _xen_kernel_paths = [ ("images/xen/vmlinuz",
                           "images/xen/initrd.img") ]

    def isValidStore(self, fetcher, progresscb):
        raise NotImplementedError


# Fedora distro check
class FedoraDistro(RedHatDistro):

    name = "Fedora"

    def isValidStore(self, fetcher, progresscb):
        if self._hasTreeinfo(fetcher, progresscb):
            m = re.match(".*Fedora.*", self.treeinfo.get("general", "family"))
            ret = (m != None)

            if ret:
                lateststr, latestnum = self._latestFedoraVariant()
                ver = self.treeinfo.get("general", "version")
                if ver == "development":
                    self.os_variant = self._latestFedoraVariant()
                elif ver:
                    vernum = int(str(ver).split("-")[0])
                    if vernum > latestnum:
                        self.os_variant = lateststr
                    else:
                        self.os_variant = "fedora" + str(vernum)


            return ret
        else:
            if fetcher.hasFile("Fedora"):
                logging.debug("Detected a Fedora distro")
                return True
            return False

    def _latestFedoraVariant(self):
        ret = None
        for var in osdict.sort_helper(osdict.OS_TYPES["linux"]["variants"]):
            if var.startswith("fedora"):
                # First fedora* occurence should be the newest
                ret = var
                break

        return ret, int(ret[6:])

# Red Hat Enterprise Linux distro check
class RHELDistro(RedHatDistro):

    name = "Red Hat Enterprise Linux"

    def isValidStore(self, fetcher, progresscb):
        if self._hasTreeinfo(fetcher, progresscb):
            m = re.match(".*Red Hat Enterprise Linux.*",
                         self.treeinfo.get("general", "family"))
            ret = (m != None)

            if ret:
                self._variantFromVersion()
            return ret
        else:
            # fall back to old code
            if fetcher.hasFile("Server"):
                logging.debug("Detected a RHEL 5 Server distro")
                self.os_variant = "rhel5"
                return True
            if fetcher.hasFile("Client"):
                logging.debug("Detected a RHEL 5 Client distro")
                self.os_variant = "rhel5"
                return True
            if fetcher.hasFile("RedHat"):
                if fetcher.hasFile("dosutils"):
                    self.os_variant = "rhel3"
                else:
                    self.os_variant = "rhel4"

                logging.debug("Detected a %s distro", self.os_variant)
                return True
            return False

    def _parseTreeinfoVersion(self, verstr):
        version = safeint(verstr[0])
        update = 0

        updinfo = verstr.split(".")
        if len(updinfo) > 1:
            update = safeint(updinfo[1])

        return version, update

    def _variantFromVersion(self):
        ver = self.treeinfo.get("general", "version")
        if not ver:
            return

        version, update = self._parseTreeinfoVersion(ver)
        self._setRHELVariant(version, update)

    def _setRHELVariant(self, version, update):
        if not _check_ostype_valid(self.os_type):
            return

        base = "rhel" + str(version)
        if update < 0:
            update = 0

        ret = None
        while update >= 0:
            tryvar = base + ".%s" % update
            if not _check_osvariant_valid(self.os_type, tryvar):
                update -= 1
                continue

            ret = tryvar
            break

        if not ret:
            # Try plain rhel5, rhel6, whatev
            if _check_osvariant_valid(self.os_type, base):
                ret = base

        if ret:
            self.os_variant = ret


# CentOS distro check
class CentOSDistro(RHELDistro):

    name = "CentOS"

    def isValidStore(self, fetcher, progresscb):
        if self._hasTreeinfo(fetcher, progresscb):
            m = re.match(".*CentOS.*", self.treeinfo.get("general", "family"))
            ret = (m != None)

            if ret:
                self._variantFromVersion()
            return ret
        else:
            # fall back to old code
            if fetcher.hasFile("CentOS"):
                logging.debug("Detected a CentOS distro")
                return True
            return False

# Scientific Linux distro check
class SLDistro(RHELDistro):

    name = "Scientific Linux"

    _boot_iso_paths = RHELDistro._boot_iso_paths + [ "images/SL/boot.iso" ]
    _hvm_kernel_paths = RHELDistro._hvm_kernel_paths + \
                        [ ("images/SL/pxeboot/vmlinuz",
                           "images/SL/pxeboot/initrd.img") ]

    def isValidStore(self, fetcher, progresscb):
        if self._hasTreeinfo(fetcher, progresscb):
            m = re.match(".*Scientific Linux.*",
                         self.treeinfo.get("general", "family"))
            ret = (m != None)

            if ret:
                self._variantFromVersion()
            return ret
        else:
            if fetcher.hasFile("SL"):
                logging.debug("Detected a Scientific Linux distro")
                return True
            return False

    def _parseTreeinfoVersion(self, verstr):
        """
        Overrides method in RHELDistro
        """
        version = safeint(verstr[0])
        update = 0

        if len(verstr) > 1:
            update = safeint(verstr[1])
        return version, update


# Suse  image store is harder - we fetch the kernel RPM and a helper
# RPM and then munge bits together to generate a initrd
class SuseDistro(Distro):

    name = "SUSE"
    os_type = "linux"
    method_arg = "install"
    _boot_iso_paths   = [ "boot/boot.iso" ]

    def __init__(self, uri, arch, vmtype=None, scratchdir=None):
        Distro.__init__(self, uri, arch, vmtype, scratchdir)
        if re.match(r'i[4-9]86', arch):
            self.arch = 'i386'

        oldkern = "linux"
        oldinit = "initrd"
        if arch == "x86_64":
            oldkern += "64"
            oldinit += "64"

        # Tested with Opensuse >= 10.2, 11, and sles 10
        self._hvm_kernel_paths = [ ("boot/%s/loader/linux" % self.arch,
                                    "boot/%s/loader/initrd" % self.arch) ]
        # Tested with Opensuse 10.0
        self._hvm_kernel_paths.append(("boot/loader/%s" % oldkern,
                                       "boot/loader/%s" % oldinit))

        # Matches Opensuse > 10.2 and sles 10
        self._xen_kernel_paths = [ ("boot/%s/vmlinuz-xen" % self.arch,
                                    "boot/%s/initrd-xen" % self.arch) ]

    def isValidStore(self, fetcher, progresscb):
        # Suse distros always have a 'directory.yast' file in the top
        # level of install tree, which we use as the magic check
        if fetcher.hasFile("directory.yast"):
            logging.debug("Detected a Suse distro.")
            return True
        return False

    def acquireKernel(self, guest, fetcher, progresscb):
        # If installing a fullvirt guest
        if self.type is None or self.type == "hvm" or \
           fetcher.hasFile("boot/%s/vmlinuz-xen" % self.arch):
            return Distro.acquireKernel(self, guest, fetcher, progresscb)

        # For Opensuse <= 10.2, we need to perform some heinous stuff
        logging.debug("Trying Opensuse 10 PV rpm hacking")
        return self._findXenRPMS(fetcher, progresscb)


    def _findXenRPMS(self, fetcher, progresscb):
        kernelrpm = None
        installinitrdrpm = None
        filelist = None
        try:
            # There is no predictable filename for kernel/install-initrd RPMs
            # so we have to grok the filelist and find them
            filelist = fetcher.acquireFile("ls-lR.gz", progresscb)
            (kernelrpmname, initrdrpmname) = self._extractRPMNames(filelist)

            # Now fetch the two RPMs we want
            kernelrpm = fetcher.acquireFile(kernelrpmname, progresscb)
            installinitrdrpm = fetcher.acquireFile(initrdrpmname, progresscb)

            # Process the RPMs to extract the kernel & generate an initrd
            return self._buildKernelInitrd(fetcher, kernelrpm, installinitrdrpm, progresscb)
        finally:
            if filelist is not None:
                os.unlink(filelist)
            if kernelrpm is not None:
                os.unlink(kernelrpm)
            if installinitrdrpm is not None:
                os.unlink(installinitrdrpm)

    # We need to parse the ls-lR.gz file, looking for the kernel &
    # install-initrd RPM entries - capturing the directory they are
    # in and the version'd filename.
    def _extractRPMNames(self, filelist):
        filelistData = gzip.GzipFile(filelist, mode="r")
        try:
            arches = [self.arch]
            # On i686 arch, we also look under i585 and i386 dirs
            # in case the RPM is built for a lesser arch. We also
            # need the PAE variant (for Fedora dom0 at least)
            #
            # XXX shouldn't hard code that dom0 is PAE
            if self.arch == "i386":
                arches.append("i586")
                arches.append("i686")
                kernelname = "kernel-xenpae"
            else:
                kernelname = "kernel-xen"

            installinitrdrpm = None
            kernelrpm = None
            dirname = None
            while 1:
                data = filelistData.readline()
                if not data:
                    break
                if dirname is None:
                    for arch in arches:
                        wantdir = "/suse/" + arch
                        if data == "." + wantdir + ":\n":
                            dirname = wantdir
                            break
                else:
                    if data == "\n":
                        dirname = None
                    else:
                        if data[:5] != "total":
                            filename = re.split("\s+", data)[8]

                            if filename[:14] == "install-initrd":
                                installinitrdrpm = dirname + "/" + filename
                            elif filename[:len(kernelname)] == kernelname:
                                kernelrpm = dirname + "/" + filename

            if kernelrpm is None:
                raise Exception(_("Unable to determine kernel RPM path"))
            if installinitrdrpm is None:
                raise Exception(_("Unable to determine install-initrd RPM path"))
            return (kernelrpm, installinitrdrpm)
        finally:
            filelistData.close()

    # We have a kernel RPM and a install-initrd RPM with a generic initrd in it
    # Now we have to merge the two together to build an initrd capable of
    # booting the installer.
    #
    # Yes, this is crazy ass stuff :-)
    def _buildKernelInitrd(self, fetcher, kernelrpm, installinitrdrpm, progresscb):
        progresscb.start(text=_("Building initrd"), size=11)
        progresscb.update(1)
        cpiodir = tempfile.mkdtemp(prefix="virtinstcpio.", dir=self.scratchdir)
        try:
            # Extract the kernel RPM contents
            os.mkdir(cpiodir + "/kernel")
            cmd = "cd " + cpiodir + "/kernel && (rpm2cpio " + kernelrpm + " | cpio --quiet -idm)"
            logging.debug("Running " + cmd)
            os.system(cmd)
            progresscb.update(2)

            # Determine the raw kernel version
            kernelinfo = None
            for f in os.listdir(cpiodir + "/kernel/boot"):
                if f.startswith("System.map-"):
                    kernelinfo = re.split("-", f)
            kernel_override = kernelinfo[1] + "-override-" + kernelinfo[3]
            kernel_version = kernelinfo[1] + "-" + kernelinfo[2] + "-" + kernelinfo[3]
            logging.debug("Got kernel version " + str(kernelinfo))

            # Build a list of all .ko files
            modpaths = {}
            for root, dummy, files in os.walk(cpiodir + "/kernel/lib/modules", topdown=False):
                for name in files:
                    if name.endswith(".ko"):
                        modpaths[name] = os.path.join(root, name)
            progresscb.update(3)

            # Extract the install-initrd RPM contents
            os.mkdir(cpiodir + "/installinitrd")
            cmd = "cd " + cpiodir + "/installinitrd && (rpm2cpio " + installinitrdrpm + " | cpio --quiet -idm)"
            logging.debug("Running " + cmd)
            os.system(cmd)
            progresscb.update(4)

            # Read in list of mods required for initrd
            modnames = []
            fn = open(cpiodir + "/installinitrd/usr/lib/install-initrd/" + kernelinfo[3] + "/module.list", "r")
            try:
                while 1:
                    line = fn.readline()
                    if not line:
                        break
                    line = line[:len(line) - 1]
                    modnames.append(line)
            finally:
                fn.close()
            progresscb.update(5)

            # Uncompress the basic initrd
            cmd = "gunzip -c " + cpiodir + "/installinitrd/usr/lib/install-initrd/initrd-base.gz > " + cpiodir + "/initrd.img"
            logging.debug("Running " + cmd)
            os.system(cmd)
            progresscb.update(6)

            # Create temp tree to hold stuff we're adding to initrd
            moddir = cpiodir + "/initrd/lib/modules/" + kernel_override + "/initrd/"
            moddepdir = cpiodir + "/initrd/lib/modules/" + kernel_version
            os.makedirs(moddir)
            os.makedirs(moddepdir)
            os.symlink("../" + kernel_override, moddepdir + "/updates")
            os.symlink("lib/modules/" + kernel_override + "/initrd", cpiodir + "/initrd/modules")
            cmd = "cp " + cpiodir + "/installinitrd/usr/lib/install-initrd/" + kernelinfo[3] + "/module.config" + " " + moddir
            logging.debug("Running " + cmd)
            os.system(cmd)
            progresscb.update(7)

            # Copy modules we need into initrd staging dir
            for modname in modnames:
                if modname in modpaths:
                    src = modpaths[modname]
                    dst = moddir + "/" + modname
                    os.system("cp " + src + " " + dst)
            progresscb.update(8)

            # Run depmod across the staging area
            cmd = "depmod -a -b " + cpiodir + "/initrd -F " + cpiodir + "/kernel/boot/System.map-" + kernel_version + " " + kernel_version
            logging.debug("Running " + cmd)
            os.system(cmd)
            progresscb.update(9)

            # Add the extra modules to the basic initrd
            cmd = "cd " + cpiodir + "/initrd && ( find . | cpio --quiet -o -H newc -A -F " + cpiodir + "/initrd.img)"
            logging.debug("Running " + cmd)
            os.system(cmd)
            progresscb.update(10)

            # Compress the final initrd
            cmd = "gzip -f9N " + cpiodir + "/initrd.img"
            logging.debug("Running " + cmd)
            os.system(cmd)
            progresscb.end(11)

            # Save initrd & kernel to temp files for booting...
            initrdname = fetcher.saveTemp(open(cpiodir + "/initrd.img.gz", "r"), "initrd.img")
            logging.debug("Saved " + initrdname)
            try:
                kernelname = fetcher.saveTemp(open(cpiodir + "/kernel/boot/vmlinuz-" + kernel_version, "r"), "vmlinuz")
                logging.debug("Saved " + kernelname)
                return (kernelname, initrdname, "install=" + fetcher.location)
            except:
                os.unlink(initrdname)
        finally:
            #pass
            os.system("rm -rf " + cpiodir)


class DebianDistro(Distro):
    # ex. http://ftp.egr.msu.edu/debian/dists/sarge/main/installer-i386/
    # daily builds: http://d-i.debian.org/daily-images/amd64/

    name = "Debian"
    os_type = "linux"

    def __init__(self, uri, arch, vmtype=None, scratchdir=None):
        Distro.__init__(self, uri, arch, vmtype, scratchdir)
        if uri.count("i386"):
            self._treeArch = "i386"
        elif uri.count("amd64"):
            self._treeArch = "amd64"
        else:
            self._treeArch = "i386"

        if re.match(r'i[4-9]86', arch):
            self.arch = 'i386'

        self._installer_name = self.name.lower() + "-" + "installer"
        self._prefix = 'current/images'
        self._set_media_paths()

    def _set_media_paths(self):
        # Use self._prefix to set media paths
        self._boot_iso_paths   = [ "%s/netboot/mini.iso" % self._prefix ]
        hvmroot = "%s/netboot/%s/%s/" % (self._prefix,
                                         self._installer_name,
                                         self._treeArch)
        xenroot = "%s/netboot/xen/" % self._prefix
        self._hvm_kernel_paths = [ (hvmroot + "linux", hvmroot + "initrd.gz") ]
        self._xen_kernel_paths = [ (xenroot + "vmlinuz",
                                    xenroot + "initrd.gz") ]

    def isValidStore(self, fetcher, progresscb):
        if fetcher.hasFile("%s/MANIFEST" % self._prefix):
            # For regular trees
            pass
        elif fetcher.hasFile("daily/MANIFEST"):
            # For daily trees
            self._prefix = "daily"
            self._set_media_paths()
        else:
            return False

        filename = "%s/MANIFEST" % self._prefix
        regex = ".*%s.*" % self._installer_name
        if self._fetchAndMatchRegex(fetcher, progresscb, filename, regex):
            logging.debug("Detected a %s distro", self.name)
            return True

        logging.debug("MANIFEST didn't match regex, not a %s distro",
                      self.name)
        return False


class UbuntuDistro(DebianDistro):
    name = "Ubuntu"
    # regular tree:
    # http://archive.ubuntu.com/ubuntu/dists/natty/main/installer-amd64/

    def isValidStore(self, fetcher, progresscb):
        if fetcher.hasFile("%s/MANIFEST" % self._prefix):
            # For regular trees
            filename = "%s/MANIFEST" % self._prefix
            regex = ".*%s.*" % self._installer_name
        elif fetcher.hasFile("install/netboot/version.info"):
            # For trees based on ISO's
            self._prefix = "install"
            self._set_media_paths()
            filename = "%s/netboot/version.info" % self._prefix
            regex = "%s*" % self.name
        else:
            logging.debug("Doesn't look like an %s Distro.", self.name)
            return False

        if self._fetchAndMatchRegex(fetcher, progresscb, filename, regex):
            logging.debug("Detected an %s distro", self.name)
            return True

        logging.debug("Regex didn't match, not an %s distro", self.name)
        return False


class MandrivaDistro(Distro):
    # Ex. ftp://ftp.uwsg.indiana.edu/linux/mandrake/official/2007.1/x86_64/

    name = "Mandriva"
    os_type = "linux"
    _boot_iso_paths = [ "install/images/boot.iso" ]
    # Kernels for HVM: valid for releases 2007.1, 2008.*, 2009.0
    _hvm_kernel_paths = [ ("isolinux/alt0/vmlinuz", "isolinux/alt0/all.rdz")]
    _xen_kernel_paths = []

    def isValidStore(self, fetcher, progresscb):
        # Don't support any paravirt installs
        if self.type is not None and self.type != "hvm":
            return False

        # Mandriva websites / media appear to have a VERSION
        # file in top level which we can use as our 'magic'
        # check for validity
        if not fetcher.hasFile("VERSION"):
            return False

        if self._fetchAndMatchRegex(fetcher, progresscb, "VERSION",
                                    ".*%s.*" % self.name):
            logging.debug("Detected a %s distro", self.name)
            return True

        return False

class MageiaDistro(MandrivaDistro):
    name = "Mageia"

# Solaris and OpenSolaris distros
class SunDistro(Distro):

    name = "Solaris"
    os_type = "solaris"

    def isValidStore(self, fetcher, progresscb):
        """Determine if uri points to a tree of the store's distro"""
        raise NotImplementedError

    def acquireBootDisk(self, guest, fetcher, progresscb):
        return fetcher.acquireFile("images/solarisdvd.iso", progresscb)

    def process_extra_args(self, argstr):
        """Collect additional arguments."""
        if not argstr:
            return (None, None, None, None)

        kopts = ''
        kargs = ''
        smfargs = ''
        Bargs = ''

        args = argstr.split()
        i = 0
        while i < len(args):
            exarg = args[i]
            if exarg == '-B':
                i += 1
                if i == len(args):
                    continue

                if not Bargs:
                    Bargs = args[i]
                else:
                    Bargs = ','.join([Bargs, args[i]])

            elif exarg == '-m':
                i += 1
                if i == len(args):
                    continue
                smfargs = args[i]
            elif exarg.startswith('-'):
                if kopts is None:
                    kopts = exarg[1:]
                else:
                    kopts = kopts + exarg[1:]
            else:
                if kargs is None:
                    kargs = exarg
                else:
                    kargs = kargs + ' ' + exarg
            i += 1

        return kopts, kargs, smfargs, Bargs

class SolarisDistro(SunDistro):
    kernelpath = 'boot/platform/i86xpv/kernel/unix'
    initrdpath = 'boot/x86.miniroot'

    def isValidStore(self, fetcher, progresscb):
        if fetcher.hasFile(self.kernelpath):
            logging.debug('Detected Solaris')
            return True
        return False

    def install_args(self, guest):
        """Construct kernel cmdline args for the installer, consisting of:
           the pathname of the kernel (32/64) to load, kernel options
           and args, and '-B' boot properties."""

        # XXX: ignoring smfargs for the time being
        (kopts, kargs, ignore_smfargs, kbargs) = \
            self.process_extra_args(guest.extraargs)

        args = [ '' ]
        if kopts:
            args += [ '-%s' % kopts ]
        if kbargs:
            args += [ '-B', kbargs ]

        netmask = ''
        # Yuck. Non-default netmasks require this option to be passed.
        # It's distinctly not-trivial to work out the netmask to be used
        # automatically.
        if kargs:
            for karg in kargs.split():
                if karg.startswith('subnet-mask'):
                    netmask = karg.split('=')[1]
                else:
                    args += [ kargs ]

        iargs = ''
        if not guest.graphics['enabled']:
            iargs += 'nowin '

        if guest.location.startswith('nfs:'):
            try:
                guestIP = socket.gethostbyaddr(guest.name)[2][0]
            except:
                iargs += ' dhcp'
            else:
                iserver = guest.location.split(':')[1]
                ipath = guest.location.split(':')[2]
                iserverIP = socket.gethostbyaddr(iserver)[2][0]
                iargs += ' -B install_media=' + iserverIP + ':' + ipath
                iargs += ',host-ip=' + guestIP
                if netmask:
                    iargs += ',subnet-mask=%s' % netmask
                droute = _util.default_route(guest.nics[0].bridge)
                if droute:
                    iargs += ',router-ip=' + droute
                if guest.nics[0].macaddr:
                    en = guest.nics[0].macaddr.split(':')
                    for i in range(len(en)):
                        # remove leading '0' from mac address element
                        if len(en[i]) > 1 and en[i][0] == '0':
                            en[i] = en[i][1]
                    boot_mac = ':'.join(en)
                    iargs += ',boot-mac=' + boot_mac
        else:
            iargs += '-B install_media=cdrom'

        args += [ '-', iargs ]
        return ' '.join(args)

    def acquireKernel(self, guest, fetcher, progresscb):

        try:
            kernel = fetcher.acquireFile(self.kernelpath, progresscb)
        except:
            raise RuntimeError("Solaris PV kernel not found at %s" %
                self.kernelpath)

        # strip boot from the kernel path
        kpath = self.kernelpath.split('/')[1:]
        args = "/" + "/".join(kpath) + self.install_args(guest)

        try:
            initrd = fetcher.acquireFile(self.initrdpath, progresscb)
            return (kernel, initrd, args)
        except:
            os.unlink(kernel)
            raise RuntimeError(_("Solaris miniroot not found at %s") %
                self.initrdpath)

class OpenSolarisDistro(SunDistro):

    os_variant = "opensolaris"

    kernelpath = "platform/i86xpv/kernel/unix"
    initrdpaths = [ "platform/i86pc/boot_archive", "boot/x86.microroot" ]

    def isValidStore(self, fetcher, progresscb):
        if fetcher.hasFile(self.kernelpath):
            logging.debug("Detected OpenSolaris")
            return True
        return False

    def install_args(self, guest):
        """Construct kernel cmdline args for the installer, consisting of:
           the pathname of the kernel (32/64) to load, kernel options
           and args, and '-B' boot properties."""

        # XXX: ignoring smfargs and kargs for the time being
        (kopts, ignore_kargs, ignore_smfargs, kbargs) = \
            self.process_extra_args(guest.extraargs)

        args = ''
        if kopts:
            args += ' -' + kopts
        if kbargs:
            args += ' -B ' + kbargs

        return args

    def acquireKernel(self, guest, fetcher, progresscb):

        try:
            kernel = fetcher.acquireFile(self.kernelpath, progresscb)
        except:
            raise RuntimeError(_("OpenSolaris PV kernel not found at %s") %
                self.kernelpath)

        args = "/" + self.kernelpath + self.install_args(guest)

        try:
            initrd = fetcher.acquireFile(self.initrdpaths[0], progresscb)
            return (kernel, initrd, args)
        except Exception, e:
            try:
                initrd = fetcher.acquireFile(self.initrdpaths[1], progresscb)
                return (kernel, initrd, args)
            except:
                os.unlink(kernel)
                raise Exception("No OpenSolaris boot archive found: %s\n" % e)


# NetWare 6 PV
class NetWareDistro(Distro):
    name = "NetWare"
    os_type = "other"
    os_variant = "netware6"

    loaderpath = "STARTUP/XNLOADER.SYS"

    def isValidStore(self, fetcher, progresscb):
        if fetcher.hasFile(self.loaderpath):
            logging.debug("Detected NetWare")
            return True
        return False

    def acquireKernel(self, guest, fetcher, progresscb):
        loader = fetcher.acquireFile(self.loaderpath, progresscb)
        return (loader, "", "")

#
# Copyright 2006-2007, 2013 Red Hat, Inc.
# Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2.
# See the COPYING file in the top-level directory.

import configparser
import logging
import os
import re

from .osdict import OSDB


###############################################
# Helpers for detecting distro from given URL #
###############################################

class _DistroCache(object):
    def __init__(self, fetcher):
        self._fetcher = fetcher
        self._filecache = {}

        self._treeinfo = None
        self.treeinfo_family = None
        self.treeinfo_version = None

        self.suse_content_version = None
        self.suse_tree_arch = None

        self.debian_media_type = None


    def acquire_file_content(self, path):
        if path not in self._filecache:
            try:
                content = self._fetcher.acquireFileContent(path)
            except ValueError:
                content = None
                logging.debug("Failed to acquire file=%s", path)
            self._filecache[path] = content
        return self._filecache[path]

    @property
    def treeinfo(self):
        if self._treeinfo:
            return self._treeinfo

        treeinfostr = self.acquire_file_content(".treeinfo")
        if treeinfostr is None:
            return None

        # If the file doesn't parse or there's no 'family', this will
        # error, but that should be fine because we aren't going to
        # successfully detect the tree anyways
        treeinfo = configparser.SafeConfigParser()
        treeinfo.read_string(treeinfostr)
        self.treeinfo_family = treeinfo.get("general", "family")
        self._treeinfo = treeinfo
        logging.debug("treeinfo family=%s", self.treeinfo_family)

        if self._treeinfo.has_option("general", "version"):
            self.treeinfo_version = self._treeinfo.get("general", "version")
            logging.debug("Found treeinfo version=%s", self.treeinfo_version)

        return self._treeinfo

    def treeinfo_family_regex(self, famregex):
        if not self.treeinfo:
            return False

        ret = bool(re.match(famregex, self.treeinfo_family))
        if not ret:
            logging.debug("Didn't match treeinfo family regex=%s", famregex)
        return ret

    def content_regex(self, filename, regex):
        """
        Fetch 'filename' and return True/False if it matches the regex
        """
        content = self.acquire_file_content(filename)
        if content is None:
            return False

        for line in content.splitlines():
            if re.match(regex, line):
                return True

        logging.debug("found filename=%s but regex=%s didn't match",
                filename, regex)
        return False


def _parseSUSEContent(cbuf):
    distribution = None
    distro_version = None
    distro_summary = None
    distro_distro = None
    distro_arch = None

    # As of 2018 all latest distros match only DISTRO and REPOID below
    for line in cbuf.splitlines()[1:]:
        if line.startswith("LABEL "):
            # opensuse 10.3: LABEL openSUSE 10.3
            # opensuse 11.4: LABEL openSUSE 11.4
            # opensuse 12.3: LABEL openSUSE
            # sles11sp4 DVD: LABEL SUSE Linux Enterprise Server 11 SP4
            distribution = line.split(' ', 1)
        elif line.startswith("DISTRO "):
            # DISTRO cpe:/o:opensuse:opensuse:13.2,openSUSE
            # DISTRO cpe:/o:suse:sled:12:sp3,SUSE Linux Enterprise Desktop 12 SP3
            distro_distro = line.rsplit(',', 1)
        elif line.startswith("VERSION "):
            # opensuse 10.3: VERSION 10.3
            # opensuse 12.3: VERSION 12.3
            distro_version = line.split(' ', 1)
            if len(distro_version) > 1:
                d_version = distro_version[1].split('-', 1)
                if len(d_version) > 1:
                    distro_version[1] = d_version[0]
        elif line.startswith("SUMMARY "):
            distro_summary = line.split(' ', 1)
        elif line.startswith("BASEARCHS "):
            # opensuse 11.4: BASEARCHS i586 x86_64
            # opensuse 12.3: BASEARCHS i586 x86_64
            distro_arch = line.split(' ', 1)
        elif line.startswith("DEFAULTBASE "):
            # opensuse 10.3: DEFAULTBASE i586
            distro_arch = line.split(' ', 1)
        elif line.startswith("REPOID "):
            # REPOID obsproduct://build.suse.de/SUSE:SLE-11-SP4:GA/SUSE_SLES/11.4/DVD/x86_64
            # REPOID obsproduct://build.suse.de/SUSE:SLE-12-SP3:GA/SLES/12.3/DVD/aarch64
            distro_arch = line.rsplit('/', 1)
        if distribution and distro_version and distro_arch:
            break

    if not distribution:
        if distro_summary:
            distribution = distro_summary
        elif distro_distro:
            distribution = distro_distro

    tree_arch = None
    if distro_arch:
        tree_arch = distro_arch[1].strip()
        # Fix for 13.2 official oss repo
        if tree_arch.find("i586-x86_64") != -1:
            tree_arch = "x86_64"
    else:
        if cbuf.find("x86_64") != -1:
            tree_arch = "x86_64"
        elif cbuf.find("i586") != -1:
            tree_arch = "i586"
        elif cbuf.find("s390x") != -1:
            tree_arch = "s390x"

    return distribution, distro_version, tree_arch


def _distroFromSUSEContent(cbuf):
    distribution, distro_version, tree_arch = _parseSUSEContent(cbuf)
    logging.debug("SUSE content file found distribution=%s distro_version=%s "
        "tree_arch=%s", distribution, distro_version, tree_arch)

    def _parse_sle_distribution(d):
        sle_version = d[1].strip().rsplit(' ')[4]
        if len(d[1].strip().rsplit(' ')) > 5:
            sle_version = sle_version + '.' + d[1].strip().rsplit(' ')[5][2]
        return ['VERSION', sle_version]

    dclass = OpensuseDistro
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
        logging.debug("No specified SUSE version detected")
        return None, None, None

    distro_version = distro_version[1].strip()
    return dclass, distro_version, tree_arch


def getDistroStore(guest, fetcher):
    logging.debug("Finding distro store for location=%s", fetcher.location)

    arch = guest.os.arch
    _type = guest.os.os_type
    urldistro = OSDB.lookup_os(guest.os_variant).urldistro
    stores = _allstores[:]
    cache = _DistroCache(fetcher)

    # If user manually specified an os_distro, bump it's URL class
    # to the top of the list
    if urldistro:
        logging.debug("variant=%s has distro=%s, looking for matching "
                      "distro store to prioritize",
                      guest.os_variant, urldistro)
        found_store = None
        for store in stores:
            if store.urldistro == urldistro:
                found_store = store

        if found_store:
            logging.debug("Prioritizing distro store=%s", found_store)
            stores.remove(found_store)
            stores.insert(0, found_store)
        else:
            logging.debug("No matching store found, not prioritizing anything")

    for sclass in stores:
        if not sclass.is_valid(cache):
            continue

        store = sclass(fetcher, arch, _type, cache)
        logging.debug("Detected class=%s osvariant=%s",
                      store.__class__.__name__, store.os_variant)
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
    PRETTY_NAME = None
    urldistro = None
    uses_treeinfo = False

    # osdict variant value
    os_variant = None

    _boot_iso_paths = None
    _kernel_paths = None

    def __init__(self, fetcher, arch, vmtype, cache):
        self.fetcher = fetcher
        self.type = vmtype
        self.arch = arch
        self.uri = fetcher.location
        self.cache = cache

    @classmethod
    def is_valid(cls, cache):
        raise NotImplementedError

    def acquireKernel(self):
        kernelpath = None
        initrdpath = None
        for kpath, ipath in self._kernel_paths:
            if self.fetcher.hasFile(kpath) and self.fetcher.hasFile(ipath):
                kernelpath = kpath
                initrdpath = ipath
                break

        if not kernelpath or not initrdpath:
            raise RuntimeError(_("Couldn't find kernel for "
                                 "%(distro)s tree.") %
                                 {"distro": self.PRETTY_NAME})

        args = ""
        if not self.fetcher.location.startswith("/"):
            args += "%s=%s" % (self._get_method_arg(), self.fetcher.location)

        kernel = self.fetcher.acquireFile(kernelpath)
        try:
            initrd = self.fetcher.acquireFile(initrdpath)
            return kernel, initrd, args
        except Exception:
            os.unlink(kernel)
            raise

    def acquireBootISO(self):
        for path in self._boot_iso_paths:
            if self.fetcher.hasFile(path):
                return self.fetcher.acquireFile(path)
        raise RuntimeError(_("Could not find boot.iso in %s tree." %
                           self.PRETTY_NAME))

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


class GenericTreeinfoDistro(Distro):
    PRETTY_NAME = "Generic Treeinfo"
    uses_treeinfo = True
    urldistro = None

    def __init__(self, *args, **kwargs):
        Distro.__init__(self, *args, **kwargs)

        self._detect_version()

        if not self.cache.treeinfo:
            return

        self._kernel_paths = []
        self._boot_iso_paths = []

        try:
            self._kernel_paths.append(
                (self._getTreeinfoMedia("kernel"),
                 self._getTreeinfoMedia("initrd")))
        except Exception:
            logging.debug("Failed to parse treeinfo kernel/initrd",
                    exc_info=True)

        try:
            self._boot_iso_paths.append(self._getTreeinfoMedia("boot.iso"))
        except Exception:
            logging.debug("Failed to parse treeinfo boot.iso", exc_info=True)

    def _getTreeinfoMedia(self, mediaName):
        image_type = self.cache.treeinfo.get("general", "arch")
        if self.type == "xen":
            image_type = "xen"
        return self.cache.treeinfo.get("images-%s" % image_type, mediaName)

    def _detect_version(self):
        pass

    @classmethod
    def is_valid(cls, cache):
        return bool(cache.treeinfo)



class RedHatDistro(GenericTreeinfoDistro):
    """
    Base image store for any Red Hat related distros which have
    a common layout
    """
    PRETTY_NAME = None
    _version_number = None

    def _detect_version(self):
        pass

    def _get_method_arg(self):
        if (self._version_number is not None and
            ((self.urldistro == "rhel" and self._version_number >= 7) or
             (self.urldistro == "fedora" and self._version_number >= 19))):
            return "inst.repo"
        return "method"


class FedoraDistro(RedHatDistro):
    PRETTY_NAME = "Fedora"
    urldistro = "fedora"

    @classmethod
    def is_valid(cls, cache):
        famregex = ".*Fedora.*"
        return cache.treeinfo_family_regex(famregex)

    def _parse_fedora_version(self):
        latest_variant = OSDB.latest_fedora_version()
        if re.match("fedora[0-9]+", latest_variant):
            latest_vernum = int(latest_variant[6:])
        else:
            latest_vernum = 99
            logging.debug("Failed to parse version number from latest "
                "fedora variant=%s. Setting vernum=%s",
                latest_variant, latest_vernum)

        ver = self.cache.treeinfo_version
        if not ver:
            logging.debug("No treeinfo version? Assume rawhide")
            ver = "rawhide"
        # rawhide trees changed to use version=Rawhide in Apr 2016
        if ver in ["development", "rawhide", "Rawhide"]:
            return latest_vernum, latest_variant

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
            os_variant = latest_variant
        else:
            os_variant = "fedora" + str(vernum)

        return vernum, os_variant

    def _detect_version(self):
        self._version_number, self.os_variant = self._parse_fedora_version()


class RHELDistro(RedHatDistro):
    PRETTY_NAME = "Red Hat Enterprise Linux"
    urldistro = "rhel"
    _variant_prefix = "rhel"

    @classmethod
    def is_valid(cls, cache):
        # Matches:
        #   Red Hat Enterprise Linux
        #   RHEL Atomic Host
        famregex = ".*(Red Hat Enterprise Linux|RHEL).*"
        return cache.treeinfo_family_regex(famregex)

    def _split_rhel_version(self):
        verstr = self.cache.treeinfo_version
        def _safeint(c):
            try:
                return int(c)
            except Exception:
                return 0

        # Parse a string like 6.9 or 7.4 into its two parts
        # centos altarch's have just version=7
        update = 0
        version = _safeint(verstr)
        if verstr.count(".") == 1:
            version = _safeint(verstr.split(".")[0])
            update = _safeint(verstr.split(".")[1])

        logging.debug("converted verstr=%s to version=%s update=%s",
                verstr, version, update)
        return version, update

    def _detect_version(self):
        if not self.cache.treeinfo_version:
            return

        version, update = self._split_rhel_version()
        self._version_number = version

        # start with example base=rhel7, then walk backwards
        # through the OS list to find the latest os name that matches
        # this way we handle rhel7.6 from treeinfo when osdict only
        # knows about rhel7.5
        base = self._variant_prefix + str(version)
        while update >= 0:
            tryvar = base + ".%s" % update
            if self._check_osvariant_valid(tryvar):
                self.os_variant = tryvar
                break
            update -= 1


class CentOSDistro(RHELDistro):
    PRETTY_NAME = "CentOS"
    urldistro = "centos"
    _variant_prefix = "centos"

    @classmethod
    def is_valid(cls, cache):
        famregex = ".*(CentOS|Scientific).*"
        return cache.treeinfo_family_regex(famregex)


class SuseDistro(Distro):
    PRETTY_NAME = "SUSE"

    @classmethod
    def is_valid(cls, cache):
        content = cache.acquire_file_content("content")
        if content is None:
            return False

        dclass, distro_version, tree_arch = _distroFromSUSEContent(content)
        if dclass == cls:
            cache.suse_content_version = distro_version
            cache.suse_tree_arch = tree_arch
            return True
        return False

    def __init__(self, *args, **kwargs):
        Distro.__init__(self, *args, **kwargs)
        if self.cache.suse_tree_arch:
            self.arch = self.cache.suse_tree_arch
        self.suse_content_version = self.cache.suse_content_version

        if re.match(r'i[4-9]86', self.arch):
            self.arch = 'i386'

        self._variantFromVersion()
        self.os_variant = self._detect_osdict_from_url()

        oldkern = "linux"
        oldinit = "initrd"
        if self.arch == "x86_64":
            oldkern += "64"
            oldinit += "64"

        self._boot_iso_paths = ["boot/boot.iso"]
        self._kernel_paths = []
        if self.type == "xen":
            # Matches Opensuse > 10.2 and sles 10
            self._kernel_paths.append(
                ("boot/%s/vmlinuz-xen" % self.arch,
                 "boot/%s/initrd-xen" % self.arch))

        if (self.arch == "s390x" and
            (self.os_variant == "sles11" or self.os_variant == "sled11")):
            self._kernel_paths.append(
                ("boot/s390x/vmrdr.ikr", "boot/s390x/initrd"))

        # Tested with SLES 12 for ppc64le, all s390x
        self._kernel_paths.append(
            ("boot/%s/linux" % self.arch,
             "boot/%s/initrd" % self.arch))
        # Tested with Opensuse 10.0
        self._kernel_paths.append(
            ("boot/loader/%s" % oldkern,
             "boot/loader/%s" % oldinit))
        # Tested with Opensuse >= 10.2, 11, and sles 10
        self._kernel_paths.append(
            ("boot/%s/loader/linux" % self.arch,
             "boot/%s/loader/initrd" % self.arch))

    def _variantFromVersion(self):
        if not self.suse_content_version:
            return
        distro_version = self.suse_content_version
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

    def _detect_osdict_from_url(self):
        root = "opensuse"
        oses = [n for n in OSDB.list_os() if n.name.startswith(root)]

        for osobj in oses:
            codename = osobj.name[len(root):]
            if re.search("/%s/" % codename, self.uri):
                return osobj.name
        return self.os_variant

    def _get_method_arg(self):
        return "install"


class SLESDistro(SuseDistro):
    urldistro = "sles"


class SLEDDistro(SuseDistro):
    urldistro = "sled"


class OpensuseDistro(SuseDistro):
    urldistro = "opensuse"


class DebianDistro(Distro):
    # ex. http://ftp.egr.msu.edu/debian/dists/sarge/main/installer-i386/
    # daily builds: http://d-i.debian.org/daily-images/amd64/
    PRETTY_NAME = "Debian"
    urldistro = "debian"
    _debname = "debian"

    @classmethod
    def is_valid(cls, cache):
        def check_manifest(mfile):
            is_ubuntu = cls._debname == "ubuntu"
            if cache.content_regex(mfile, ".*[Uu]buntu.*"):
                return is_ubuntu
            return cache.content_regex(mfile, ".*[Dd]ebian.*")

        media_type = None
        if check_manifest("current/images/MANIFEST"):
            media_type = "url"
        elif check_manifest("daily/MANIFEST"):
            media_type = "daily"
        elif cache.content_regex(".disk/info",
                "%s.*" % cls._debname.capitalize()):
            media_type = "disk"

        if media_type:
            cache.debian_media_type = media_type
        return bool(media_type)


    def __init__(self, *args, **kwargs):
        Distro.__init__(self, *args, **kwargs)

        self._kernel_paths = []
        self._url_prefix = ""

        media_type = self.cache.debian_media_type
        if media_type == "url" or media_type == "daily":
            url_prefix = "current/images"
            if media_type == "daily":
                url_prefix = "daily"
            self._set_url_paths(url_prefix)
            self.os_variant = self._detect_debian_osdict_from_url(url_prefix)

        elif media_type == "disk":
            self._set_installcd_paths()


    def _find_treearch(self):
        for pattern in ["^.*/installer-(\w+)/?$",
                        "^.*/daily-images/(\w+)/?$"]:
            arch = re.findall(pattern, self.uri)
            if not arch:
                continue
            logging.debug("Found pattern=%s treearch=%s in uri",
                pattern, arch[0])
            return arch[0]

        # Check for standard arch strings which will be
        # in the URI name for --location $ISO mounts
        for arch in ["i386", "amd64", "x86_64", "arm64"]:
            if arch in self.uri:
                logging.debug("Found treearch=%s in uri", arch)
                if arch == "x86_64":
                    arch = "amd64"
                return arch

        # Otherwise default to i386
        arch = "i386"
        logging.debug("No treearch found in uri, defaulting to arch=%s", arch)
        return arch

    def _set_url_paths(self, url_prefix):
        self._boot_iso_paths = ["%s/netboot/mini.iso" % url_prefix]

        tree_arch = self._find_treearch()
        hvmroot = "%s/netboot/%s-installer/%s/" % (url_prefix,
                self._debname, tree_arch)
        initrd_basename = "initrd.gz"
        kernel_basename = "linux"
        if tree_arch in ["ppc64el"]:
            kernel_basename = "vmlinux"

        if tree_arch == "s390x":
            hvmroot = "%s/generic/" % url_prefix
            kernel_basename = "kernel.%s" % self._debname
            initrd_basename = "initrd.%s" % self._debname


        if self.type == "xen":
            xenroot = "%s/netboot/xen/" % url_prefix
            self._kernel_paths.append(
                    (xenroot + "vmlinuz", xenroot + "initrd.gz"))
        self._kernel_paths.append(
                (hvmroot + kernel_basename, hvmroot + initrd_basename))

    def _set_installcd_paths(self):
        if self._debname == "ubuntu":
            if not self.arch == "s390x":
                kpair = ("install/vmlinuz", "install/initrd.gz")
            else:
                kpair = ("boot/kernel.ubuntu", "boot/initrd.ubuntu")
        elif self.arch == "x86_64":
            kpair = ("install.amd/vmlinuz", "install.amd/initrd.gz")
        elif self.arch == "i686":
            kpair = ("install.386/vmlinuz", "install.386/initrd.gz")
        elif self.arch == "aarch64":
            kpair = ("install.a64/vmlinuz", "install.a64/initrd.gz")
        elif self.arch == "ppc64le":
            kpair = ("install/vmlinux", "install/initrd.gz")
        elif self.arch == "s390x":
            kpair = ("boot/linux_vm", "boot/root.bin")
        else:
            kpair = ("install/vmlinuz", "install/initrd.gz")
        self._kernel_paths += [kpair]
        return True

    def _detect_debian_osdict_from_url(self, url_prefix):
        oses = [n for n in OSDB.list_os() if n.name.startswith(self._debname)]

        if url_prefix == "daily":
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
    PRETTY_NAME = "Ubuntu"
    urldistro = "ubuntu"
    _debname = "ubuntu"


class ALTLinuxDistro(Distro):
    PRETTY_NAME = "ALT Linux"
    urldistro = "altlinux"

    _boot_iso_paths = [("altinst", "live")]
    _kernel_paths = [("syslinux/alt0/vmlinuz", "syslinux/alt0/full.cz")]

    @classmethod
    def is_valid(cls, cache):
        # altlinux doesn't have installable URLs, so this is just for ISO
        return cache.content_regex(".disk/info", ".*ALT .*")


class MandrivaDistro(Distro):
    # ftp://ftp.uwsg.indiana.edu/linux/mandrake/official/2007.1/x86_64/
    PRETTY_NAME = "Mandriva/Mageia"
    urldistro = "mandriva"

    _boot_iso_paths = ["install/images/boot.iso"]

    @classmethod
    def is_valid(cls, cache):
        return cache.content_regex("VERSION", ".*(Mandriva|Mageia).*")

    def __init__(self, *args, **kwargs):
        Distro.__init__(self, *args, **kwargs)
        self._kernel_paths = []

        # At least Mageia 5 uses arch in the names
        self._kernel_paths += [
            ("isolinux/%s/vmlinuz" % self.arch,
             "isolinux/%s/all.rdz" % self.arch)]

        # Kernels for HVM: valid for releases 2007.1, 2008.*, 2009.0
        self._kernel_paths += [
            ("isolinux/alt0/vmlinuz", "isolinux/alt0/all.rdz")]


# Build list of all *Distro classes
def _build_distro_list():
    allstores = []
    for obj in list(globals().values()):
        if (isinstance(obj, type) and
            issubclass(obj, Distro) and
            obj.PRETTY_NAME):
            allstores.append(obj)

    seen_urldistro = []
    for obj in allstores:
        if obj.urldistro and obj.urldistro in seen_urldistro:
            raise RuntimeError("programming error: duplicate urldistro=%s" %
                               obj.urldistro)
        seen_urldistro.append(obj.urldistro)

    # Always stick GenericDistro at the end, since it's a catchall
    allstores.remove(GenericTreeinfoDistro)
    allstores.append(GenericTreeinfoDistro)

    return allstores

_allstores = _build_distro_list()

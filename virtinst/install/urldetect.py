#
# Copyright 2006-2007, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import configparser
import os
import re

from ..logger import log
from ..osdict import OSDB


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
        self.treeinfo_name = None
        self.treeinfo_matched = False

        self.suse_content = None
        self.checked_for_suse_content = False
        self.debian_media_type = None
        self.mageia_version = None

        self.libosinfo_os_variant = None
        self.libosinfo_mediaobj = None
        self.libosinfo_treeobj = None

    def acquire_file_content(self, path):
        if path not in self._filecache:
            try:
                content = self._fetcher.acquireFileContent(path)
            except ValueError as e:
                content = None
                log.debug("Failed to acquire file=%s: %s", path, e)
            self._filecache[path] = content
        return self._filecache[path]

    @property
    def treeinfo(self):
        if self._treeinfo:
            return self._treeinfo

        # Vast majority of trees here use .treeinfo. However, trees via
        # Red Hat satellite on akamai CDN will use treeinfo, because akamai
        # doesn't do dotfiles apparently:
        #
        #   https://bugzilla.redhat.com/show_bug.cgi?id=635065
        #
        # Anaconda is the canonical treeinfo consumer and they check for both
        # locations, so we need to do the same
        treeinfostr = (self.acquire_file_content(".treeinfo") or
            self.acquire_file_content("treeinfo"))
        if treeinfostr is None:
            return None

        # If the file doesn't parse or there's no 'family', this will
        # error, but that should be fine because we aren't going to
        # successfully detect the tree anyways
        treeinfo = configparser.ConfigParser()
        treeinfo.read_string(treeinfostr)
        self.treeinfo_family = treeinfo.get("general", "family")
        self._treeinfo = treeinfo
        log.debug("treeinfo family=%s", self.treeinfo_family)

        if self._treeinfo.has_option("general", "version"):
            self.treeinfo_version = self._treeinfo.get("general", "version")
            log.debug("Found treeinfo version=%s", self.treeinfo_version)

        if self._treeinfo.has_option("general", "name"):
            self.treeinfo_name = self._treeinfo.get("general", "name")
            log.debug("Found treeinfo name=%s", self.treeinfo_name)

        return self._treeinfo

    def treeinfo_family_regex(self, famregex):
        if not self.treeinfo:
            return False

        ret = bool(re.match(famregex, self.treeinfo_family))
        self.treeinfo_matched = ret
        if not ret:
            log.debug("Didn't match treeinfo family regex=%s", famregex)
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

        log.debug("found filename=%s but regex=%s didn't match",
                filename, regex)
        return False

    def get_treeinfo_media(self, typ):
        """
        Pull kernel/initrd/boot.iso paths out of the treeinfo for
        the passed data
        """
        def _get_treeinfo_path(media_name):
            image_type = self.treeinfo.get("general", "arch")
            if typ == "xen":
                image_type = "xen"
            return self.treeinfo.get("images-%s" % image_type, media_name)

        try:
            return [(_get_treeinfo_path("kernel"),
                     _get_treeinfo_path("initrd"))]
        except Exception:  # pragma: no cover
            log.debug("Failed to parse treeinfo kernel/initrd",
                    exc_info=True)
            return []

    def split_version(self):
        verstr = self.treeinfo_version
        def _safeint(c):
            try:
                return int(c)
            except Exception:
                return 0

        # Parse a string like 6.9 or 7.4 into its two parts
        # centos altarch's have just version=7
        update = 0
        version = _safeint(verstr)
        if verstr.count(".") >= 1:
            # pylint: disable=no-member
            version = _safeint(verstr.split(".")[0])
            update = _safeint(verstr.split(".")[1])

        log.debug("converted verstr=%s to version=%s update=%s",
                verstr, version, update)
        return version, update

    def fetcher_is_iso(self):
        return self._fetcher.is_iso()

    def guess_os_from_iso(self):
        ret = OSDB.guess_os_by_iso(self._fetcher.location)
        if not ret:
            return False

        self.libosinfo_os_variant, self.libosinfo_mediaobj = ret
        if (not self.libosinfo_mediaobj.get_kernel_path() or
            not self.libosinfo_mediaobj.get_initrd_path()):  # pragma: no cover
            # This can happen if the media is live media, or just
            # with incomplete libosinfo data
            log.debug("libosinfo didn't report any media kernel/initrd "
                          "path for detected os_variant=%s",
                          self.libosinfo_mediaobj)
            return False
        return True

    def guess_os_from_tree(self):
        ret = OSDB.guess_os_by_tree(self._fetcher.location)
        if not ret:
            return False

        self.libosinfo_os_variant, self.libosinfo_treeobj = ret
        self.treeinfo_matched = True
        return True


class _SUSEContent(object):
    """
    Helper class tracking the SUSE 'content' files
    """
    def __init__(self, content_str):
        self.content_str = content_str
        self.content_dict = {}

        for line in self.content_str.splitlines():
            for prefix in ["LABEL", "DISTRO", "VERSION",
                           "BASEARCHS", "DEFAULTBASE", "REPOID"]:
                if line.startswith(prefix + " "):
                    self.content_dict[prefix] = line.split(" ", 1)[1]

        log.debug("SUSE content dict: %s", self.content_dict)
        self.tree_arch = self._get_tree_arch()
        self.product_name = self._get_product_name()
        self.product_version = self._get_product_version()
        log.debug("SUSE content product_name=%s product_version=%s "
            "tree_arch=%s", self.product_name, self.product_version,
            self.tree_arch)

    def _get_tree_arch(self):
        # Examples:
        # opensuse 11.4: BASEARCHS i586 x86_64
        # opensuse 12.3: BASEARCHS i586 x86_64
        # opensuse 10.3: DEFAULTBASE i586
        distro_arch = (self.content_dict.get("BASEARCHS") or
                       self.content_dict.get("DEFAULTBASE"))
        if not distro_arch and "REPOID" in self.content_dict:
            distro_arch = self.content_dict["REPOID"].rsplit('/', 1)[1]
        if not distro_arch:
            return None  # pragma: no cover

        tree_arch = distro_arch.strip()
        # Fix for 13.2 official oss repo
        if tree_arch.find("i586-x86_64") != -1:
            tree_arch = "x86_64"
        return tree_arch

    def _get_product_name(self):
        """
        Parse the SUSE product name. Examples:
        SUSE Linux Enterprise Server 11 SP4
        openSUSE 11.4
        """
        # Some field examples in the wild
        #
        # opensuse 10.3: LABEL openSUSE 10.3
        # opensuse 11.4: LABEL openSUSE 11.4
        # opensuse 12.3: LABEL openSUSE
        # sles11sp4 DVD: LABEL SUSE Linux Enterprise Server 11 SP4
        #
        #
        # DISTRO cpe:/o:opensuse:opensuse:13.2,openSUSE
        # DISTRO cpe:/o:suse:sled:12:sp3,SUSE Linux Enterprise Desktop 12 SP3
        #
        # As of 2018 all latest distros match only DISTRO and REPOID.
        product_name = None
        if "LABEL" in self.content_dict:
            product_name = self.content_dict["LABEL"]
        elif "," in self.content_dict.get("DISTRO", ""):
            product_name = self.content_dict["DISTRO"].rsplit(",", 1)[1]

        log.debug("SUSE content product_name=%s", product_name)
        return product_name

    def _get_product_version(self):
        # Some example fields:
        #
        # opensuse 10.3: VERSION 10.3
        # opensuse 12.3: VERSION 12.3
        # SLES-10-SP4-DVD-x86_64-GM-DVD1.iso: VERSION 10.4-0
        #
        # REPOID obsproduct://build.suse.de/SUSE:SLE-11-SP4:GA/SUSE_SLES/11.4/DVD/x86_64
        # REPOID obsproduct://build.suse.de/SUSE:SLE-12-SP3:GA/SLES/12.3/DVD/aarch64
        #
        # As of 2018 all latest distros match only DISTRO and REPOID.
        if not self.product_name:
            return None  # pragma: no cover

        distro_version = self.content_dict.get("VERSION", "")
        if "-" in distro_version:
            distro_version = distro_version.split('-', 1)[0]

        # Special case, parse version out of a line like this
        # cpe:/o:opensuse:opensuse:13.2,openSUSE
        if (not distro_version and
            re.match("^.*:.*,openSUSE*", self.content_dict["DISTRO"])):
            distro_version = self.content_dict["DISTRO"].rsplit(
                    ",", 1)[0].strip().rsplit(":")[4]
        distro_version = distro_version.strip()

        if "Enterprise" in self.product_name or "SLES" in self.product_name:
            sle_version = self.product_name.strip().rsplit(' ')[4]
            if len(self.product_name.strip().rsplit(' ')) > 5:
                sle_version = (sle_version + '.' +
                        self.product_name.strip().rsplit(' ')[5][2])
            distro_version = sle_version

        return distro_version


def getDistroStore(guest, fetcher, skip_error):
    log.debug("Finding distro store for location=%s", fetcher.location)

    arch = guest.os.arch
    _type = guest.os.os_type
    osobj = guest.osinfo
    stores = _build_distro_list(osobj)
    cache = _DistroCache(fetcher)

    for sclass in stores:
        if not sclass.is_valid(cache):
            continue

        store = sclass(fetcher.location, arch, _type, cache)
        log.debug("Detected class=%s osvariant=%s",
                      store.__class__.__name__, store.get_osdict_info())
        return store

    if skip_error:
        return None

    # No distro was detected. See if the URL even resolves, and if not
    # give the user a hint that maybe they mistyped. This won't always
    # be true since some webservers don't allow directory listing.
    # https://www.redhat.com/archives/virt-tools-list/2014-December/msg00048.html
    extramsg = ""
    if not fetcher.can_access():
        extramsg = (": " +
            _("The URL could not be accessed, maybe you mistyped?"))

    msg = (_("Could not find an installable distribution at URL '%s'") %
            fetcher.location)
    msg += extramsg
    msg += "\n\n"
    msg += _("The location must be the root directory of an install tree.\n"
          "See virt-install man page for various distro examples.")
    raise ValueError(msg)


##################
# Distro classes #
##################

class _DistroTree(object):
    """
    Class for determining the kernel/initrd path for an install
    tree (URL, ISO, or local directory)
    """
    PRETTY_NAME = None
    matching_distros = []

    def __init__(self, location, arch, vmtype, cache):
        self.type = vmtype
        self.arch = arch
        self.uri = location
        self.cache = cache

        if self.cache.libosinfo_os_variant:
            self._os_variant = self.cache.libosinfo_os_variant
        else:
            self._os_variant = self._detect_version()

        if (self._os_variant and
            not OSDB.lookup_os(self._os_variant)):
            log.debug("Detected os_variant as %s, which is not in osdict.",
                    self._os_variant)
            self._os_variant = None

        self._kernel_paths = []
        if self.cache.treeinfo_matched:
            self._kernel_paths = self.cache.get_treeinfo_media(self.type)
        else:
            self._set_manual_kernel_paths()


    def _set_manual_kernel_paths(self):
        """
        If kernel/initrd path could not be determined from a source
        like treeinfo, subclasses can override this to set a list
        of manual paths
        """

    def _detect_version(self):
        """
        Hook for subclasses to detect media os variant.
        """
        log.debug("%s does not implement any osdict detection", self)
        return None


    ##############
    # Public API #
    ##############

    @classmethod
    def is_valid(cls, cache):
        raise NotImplementedError

    def get_kernel_paths(self):
        return self._kernel_paths

    def get_osdict_info(self):
        """
        Return detected osdict value
        """
        return self._os_variant

    def get_os_media(self):
        """
        Return an OsMedia wrapper around the detected libosinfo media object
        """
        return self.cache.libosinfo_mediaobj

    def get_os_tree(self):
        """
        Return an OsTree wrapper around the detected libosinfo media object
        """
        return self.cache.libosinfo_treeobj


class _FedoraDistro(_DistroTree):
    PRETTY_NAME = "Fedora"
    matching_distros = ["fedora"]

    @classmethod
    def is_valid(cls, cache):
        famregex = ".*Fedora.*"
        return cache.treeinfo_family_regex(famregex)

    def _detect_version(self):
        latest_variant = "fedora-unknown"

        verstr = self.cache.treeinfo_version
        if not verstr:  # pragma: no cover
            log.debug("No treeinfo version? Assume latest_variant=%s",
                    latest_variant)
            return latest_variant

        # rawhide trees changed to use version=Rawhide in Apr 2016
        if verstr in ["development", "rawhide", "Rawhide"]:
            log.debug("treeinfo version=%s, using latest_variant=%s",
                    verstr, latest_variant)
            return latest_variant

        # treeinfo version is just an integer
        variant = "fedora" + verstr
        if OSDB.lookup_os(variant):
            return variant

        log.debug(
                "variant=%s from treeinfo version=%s not found, "
                "using latest_variant=%s", variant, verstr, latest_variant)
        return latest_variant


class _RHELDistro(_DistroTree):
    PRETTY_NAME = "Red Hat Enterprise Linux"
    matching_distros = ["rhel"]
    _variant_prefix = "rhel"

    @classmethod
    def is_valid(cls, cache):
        # Matches:
        #   Red Hat Enterprise Linux
        #   RHEL Atomic Host
        famregex = ".*(Red Hat Enterprise Linux|RHEL).*"
        if cache.treeinfo_family_regex(famregex):
            return True

    def _detect_version(self):
        if not self.cache.treeinfo_version:  # pragma: no cover
            log.debug("No treeinfo version? Not setting an os_variant")
            return

        version, update = self.cache.split_version()

        # start with example base=rhel7, then walk backwards
        # through the OS list to find the latest os name that matches
        # this way we handle rhel7.6 from treeinfo when osdict only
        # knows about rhel7.5
        base = self._variant_prefix + str(version)
        while update >= 0:
            tryvar = base + ".%s" % update
            if OSDB.lookup_os(tryvar):
                return tryvar
            update -= 1


class _CentOSDistro(_RHELDistro):
    PRETTY_NAME = "CentOS"
    matching_distros = ["centos"]
    _variant_prefix = "centos"

    @classmethod
    def is_valid(cls, cache):
        if cache.treeinfo_family_regex(".*CentOS.*"):
            return True
        if cache.treeinfo_family_regex(".*Scientific.*"):
            return True



class _SuseDistro(_RHELDistro):
    PRETTY_NAME = None
    _suse_regex = []
    matching_distros = []
    _variant_prefix = NotImplementedError
    famregex = NotImplementedError

    @classmethod
    def is_valid(cls, cache):
        if cache.treeinfo_family_regex(cls.famregex):
            return True

        if not cache.checked_for_suse_content:
            cache.checked_for_suse_content = True
            content_str = cache.acquire_file_content("content")
            if content_str is None:
                return False

            try:
                cache.suse_content = _SUSEContent(content_str)
            except Exception as e:  # pragma: no cover
                log.debug("Error parsing SUSE content file: %s", str(e))
                return False

        if not cache.suse_content:
            return False
        for regex in cls._suse_regex:
            if re.match(regex, cache.suse_content.product_name or ""):
                return True
        return False

    def _set_manual_kernel_paths(self):
        # We only reach here if no treeinfo was matched
        tree_arch = self.cache.suse_content.tree_arch

        if re.match(r'i[4-9]86', tree_arch):
            tree_arch = 'i386'

        oldkern = "linux"
        oldinit = "initrd"
        if tree_arch == "x86_64":
            oldkern += "64"
            oldinit += "64"

        if self.type == "xen":
            # Matches Opensuse > 10.2 and sles 10
            self._kernel_paths.append(
                ("boot/%s/vmlinuz-xen" % tree_arch,
                 "boot/%s/initrd-xen" % tree_arch))

        if str(self._os_variant).startswith(("sles11", "sled11")):
            if tree_arch == "s390x":
                self._kernel_paths.append(
                    ("boot/s390x/vmrdr.ikr", "boot/s390x/initrd"))
            if tree_arch == "ppc64":
                self._kernel_paths.append(
                    ("suseboot/linux64", "suseboot/initrd64"))

        # Tested with SLES 12 for ppc64le, all s390x
        self._kernel_paths.append(
            ("boot/%s/linux" % tree_arch,
             "boot/%s/initrd" % tree_arch))
        # Tested with Opensuse 10.0
        self._kernel_paths.append(
            ("boot/loader/%s" % oldkern,
             "boot/loader/%s" % oldinit))
        # Tested with Opensuse >= 10.2, 11, and sles 10
        self._kernel_paths.append(
            ("boot/%s/loader/linux" % tree_arch,
             "boot/%s/loader/initrd" % tree_arch))

    def _detect_osdict_from_suse_content(self):
        if not self.cache.suse_content:
            return  # pragma: no cover

        distro_version = self.cache.suse_content.product_version
        if not distro_version:
            return  # pragma: no cover

        version = distro_version.split('.', 1)[0].strip()

        if str(self._variant_prefix).startswith(("sles", "sled")):
            sp_version = ""
            if len(distro_version.split('.', 1)) == 2:
                sp_version = 'sp' + distro_version.split('.', 1)[1].strip()

            return self._variant_prefix + version + sp_version

        return self._variant_prefix + distro_version

    def _detect_osdict_from_url(self):
        root = "opensuse"
        oses = [n for n in OSDB.list_os() if n.name.startswith(root)]

        for osobj in oses:
            codename = osobj.name[len(root):]
            if re.search("/%s/" % codename, self.uri):
                return osobj.name

    def _detect_from_treeinfo(self):
        if not self.cache.treeinfo_name:
            return
        if re.search("openSUSE Tumbleweed", self.cache.treeinfo_name):
            return "opensusetumbleweed"

        version, update = self.cache.split_version()
        base = self._variant_prefix + str(version)
        while update >= 0:
            tryvar = base
            # SLE doesn't use '.0' for initial releases in
            # osinfo-db (sles11, sles12, etc)
            if update > 0 or not base.startswith('sle'):
                tryvar += ".%s" % update
            if OSDB.lookup_os(tryvar):
                return tryvar
            update -= 1

    def _detect_version(self):
        var = self._detect_from_treeinfo()
        if not var:
            var = self._detect_osdict_from_url()
        if not var:
            var = self._detect_osdict_from_suse_content()
        return var


class _SLESDistro(_SuseDistro):
    PRETTY_NAME = "SLES"
    matching_distros = ["sles"]
    _variant_prefix = "sles"
    _suse_regex = [".*SUSE Linux Enterprise Server*", ".*SUSE SLES*"]
    famregex = ".*SUSE Linux Enterprise.*"


class _SLEDDistro(_SuseDistro):
    PRETTY_NAME = "SLED"
    matching_distros = ["sled"]
    _variant_prefix = "sled"
    _suse_regex = [".*SUSE Linux Enterprise Desktop*"]
    famregex = ".*SUSE Linux Enterprise.*"


class _OpensuseDistro(_SuseDistro):
    PRETTY_NAME = "openSUSE"
    matching_distros = ["opensuse"]
    _variant_prefix = "opensuse"
    _suse_regex = [".*openSUSE.*"]
    famregex = ".*openSUSE.*"


class _DebianDistro(_DistroTree):
    # ex. http://ftp.egr.msu.edu/debian/dists/sarge/main/installer-i386/
    # daily builds: https://d-i.debian.org/daily-images/amd64/
    PRETTY_NAME = "Debian"
    matching_distros = ["debian"]
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
        elif check_manifest("current/legacy-images/MANIFEST"):
            media_type = "legacy_url"
        elif check_manifest("daily/MANIFEST"):
            media_type = "daily"
        elif cache.content_regex(".disk/info",
                "%s.*" % cls._debname.capitalize()):
            # There's two cases here:
            # 1) Direct access ISO, attached as CDROM afterwards. We
            #    use one set of kernels in that case which seem to
            #    assume the prescence of CDROM media
            # 2) ISO mounted and exported over URL. We use a different
            #    set of kernels that expect to boot from the network
            if cache.fetcher_is_iso():
                media_type = "disk"
            else:
                media_type = "mounted_iso_url"

        if media_type:
            cache.debian_media_type = media_type
        return bool(media_type)


    def _set_manual_kernel_paths(self):
        if self.cache.debian_media_type == "disk":
            self._set_installcd_paths()
        else:
            self._set_url_paths()


    def _find_treearch(self):
        for pattern in [r"^.*/installer-(\w+)/?$",
                        r"^.*/daily-images/(\w+)/?$"]:
            arch = re.findall(pattern, self.uri)
            if not arch:
                continue
            log.debug("Found pattern=%s treearch=%s in uri",
                pattern, arch[0])
            return arch[0]

        # Check for standard arch strings which will be
        # in the URI name for --location $ISO mounts
        for arch in ["i386", "amd64", "x86_64", "arm64"]:
            if arch in self.uri:
                log.debug("Found treearch=%s in uri", arch)
                if arch == "x86_64":
                    arch = "amd64"  # pragma: no cover
                return arch

        # Otherwise default to i386
        arch = "i386"
        log.debug("No treearch found in uri, defaulting to arch=%s", arch)
        return arch

    def _set_url_paths(self):
        url_prefix = "current/images"
        if self.cache.debian_media_type == "daily":
            url_prefix = "daily"
        elif self.cache.debian_media_type == "mounted_iso_url":
            url_prefix = "install"
        elif self.cache.debian_media_type == "legacy_url":
            url_prefix = "current/legacy-images"

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

    def _detect_version(self):
        oses = [n for n in OSDB.list_os() if n.name.startswith(self._debname)]

        if self.cache.debian_media_type == "daily":
            log.debug("Appears to be debian 'daily' URL, using latest "
                "debiantesting")
            return "debiantesting"

        for osobj in oses:
            if osobj.codename:
                # Ubuntu codenames look like 'Warty Warthog'
                codename = osobj.codename.split()[0].lower()
            else:
                if " " not in osobj.label:
                    continue  # pragma: no cover
                # Debian labels look like 'Debian Sarge'
                codename = osobj.label.split()[1].lower()

            if ("/%s/" % codename) in self.uri:
                log.debug("Found codename=%s in the URL string", codename)
                return osobj.name


class _UbuntuDistro(_DebianDistro):
    # https://archive.ubuntu.com/ubuntu/dists/natty/main/installer-amd64/
    PRETTY_NAME = "Ubuntu"
    matching_distros = ["ubuntu"]
    _debname = "ubuntu"


class _MageiaDistro(_DistroTree):
    # https://distro.ibiblio.org/mageia/distrib/cauldron/x86_64/
    PRETTY_NAME = "Mageia"
    matching_distros = ["mageia"]

    @classmethod
    def is_valid(cls, cache):
        if not cache.mageia_version:
            content = cache.acquire_file_content("VERSION")
            if not content:
                return False

            m = re.match(r"^Mageia (\d+) .*", content)
            if not m:
                return False  # pragma: no cover

            cache.mageia_version = m.group(1)

        return bool(cache.mageia_version)

    def _set_manual_kernel_paths(self):
        self._kernel_paths += [
            ("isolinux/%s/vmlinuz" % self.arch,
             "isolinux/%s/all.rdz" % self.arch)]

    def _detect_version(self):
        # version is just an integer
        variant = "mageia" + self.cache.mageia_version
        if OSDB.lookup_os(variant):
            return variant


class _GenericTreeinfoDistro(_DistroTree):
    """
    Generic catchall class for .treeinfo using distros
    """
    PRETTY_NAME = "Generic Treeinfo"
    matching_distros = []

    @classmethod
    def is_valid(cls, cache):
        if cache.treeinfo:
            cache.treeinfo_matched = True
            return True
        return False


class _LibosinfoDistro(_DistroTree):
    """
    For ISO media detection that was fully handled by libosinfo
    """
    PRETTY_NAME = "Libosinfo detected"
    matching_distros = []

    @classmethod
    def is_valid(cls, cache):
        if cache.fetcher_is_iso():
            return cache.guess_os_from_iso()
        return cache.guess_os_from_tree()

    def _set_manual_kernel_paths(self):
        self._kernel_paths += [
                (self.cache.libosinfo_mediaobj.get_kernel_path(),
                 self.cache.libosinfo_mediaobj.get_initrd_path())
        ]


def _build_distro_list(osobj):
    allstores = [
        # Libosinfo takes priority
        _LibosinfoDistro,
        _FedoraDistro,
        _RHELDistro,
        _CentOSDistro,
        _SLESDistro,
        _SLEDDistro,
        _OpensuseDistro,
        _DebianDistro,
        _UbuntuDistro,
        _MageiaDistro,
        # Always stick GenericDistro at the end, since it's a catchall
        _GenericTreeinfoDistro,
    ]

    # If user manually specified an os_distro, bump its URL class
    # to the top of the list
    if osobj.distro:
        log.debug("variant=%s has distro=%s, looking for matching "
                      "distro store to prioritize",
                      osobj.name, osobj.distro)
        found_store = None
        for store in allstores:
            if osobj.distro in store.matching_distros:
                found_store = store

        if found_store:
            log.debug("Prioritizing distro store=%s", found_store)
            allstores.remove(found_store)
            allstores.insert(0, found_store)
        else:
            log.debug("No matching store found, not prioritizing anything")

    force_libosinfo = os.environ.get("VIRTINST_TEST_SUITE_FORCE_LIBOSINFO")
    if force_libosinfo:  # pragma: no cover
        if bool(int(force_libosinfo)):
            allstores = [_LibosinfoDistro]
        else:
            allstores.remove(_LibosinfoDistro)

    return allstores

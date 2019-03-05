#
# List of OS Specific data
#
# Copyright 2006-2008, 2013-2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import datetime
import logging
import re

import gi
gi.require_version('Libosinfo', '1.0')
from gi.repository import Libosinfo as libosinfo
from gi.repository import GLib as glib, Gio as gio


###################
# Sorting helpers #
###################

def _sortby(osobj):
    """
    Combines distro+version to make a more sort friendly string. Examples

    fedora25    -> fedora-0025000000000000
    ubuntu17.04 -> ubuntu-0017000400000000
    win2k8r2    -> win-0006000100000000
    """
    if osobj.is_generic():
        # Sort generic at the end of the list
        return "zzzzzz-000000000000"

    version = osobj.version
    try:
        t = version.split(".")
        t = t[:min(4, len(t))] + [0] * (4 - min(4, len(t)))
        new_version = ""
        for n in t:
            new_version = new_version + ("%.4i" % int(n))
        version = new_version
    except Exception:
        pass

    return "%s-%s" % (osobj.distro, version)


def _sort(tosort):
    sortby_mappings = {}
    distro_mappings = {}
    retlist = []

    for key, osinfo in tosort.items():
        # Libosinfo has some duplicate version numbers here, so append .1
        # if there's a collision
        sortby = _sortby(osinfo)
        while sortby_mappings.get(sortby):
            sortby = sortby + ".1"
        sortby_mappings[sortby] = key

        # Group by distro first, so debian is clumped together, fedora, etc.
        distro = osinfo.distro
        if osinfo.is_generic():
            distro = "zzzzzz"
        if distro not in distro_mappings:
            distro_mappings[distro] = []
        distro_mappings[distro].append(sortby)

    # We want returned lists to be sorted descending by 'distro', so we get
    # debian5, debian4, fedora14, fedora13
    #   rather than
    # debian4, debian5, fedora13, fedora14
    for distro_list in list(distro_mappings.values()):
        distro_list.sort()
        distro_list.reverse()

    sorted_distro_list = list(distro_mappings.keys())
    sorted_distro_list.sort()

    # Build the final list of sorted os objects
    for distro in sorted_distro_list:
        distro_list = distro_mappings[distro]
        for key in distro_list:
            orig_key = sortby_mappings[key]
            retlist.append(tosort[orig_key])

    return retlist


class _OSDB(object):
    """
    Entry point for the public API
    """
    def __init__(self):
        self.__os_loader = None
        self.__all_variants = None

    # This is only for back compatibility with pre-libosinfo support.
    # This should never change.
    _aliases = {
        "altlinux": "altlinux1.0",
        "debianetch": "debian4",
        "debianlenny": "debian5",
        "debiansqueeze": "debian6",
        "debianwheezy": "debian7",
        "freebsd10": "freebsd10.0",
        "freebsd6": "freebsd6.0",
        "freebsd7": "freebsd7.0",
        "freebsd8": "freebsd8.0",
        "freebsd9": "freebsd9.0",
        "mandriva2009": "mandriva2009.0",
        "mandriva2010": "mandriva2010.0",
        "mbs1": "mbs1.0",
        "msdos": "msdos6.22",
        "openbsd4": "openbsd4.2",
        "opensolaris": "opensolaris2009.06",
        "opensuse11": "opensuse11.4",
        "opensuse12": "opensuse12.3",
        "rhel4": "rhel4.0",
        "rhel5": "rhel5.0",
        "rhel6": "rhel6.0",
        "rhel7": "rhel7.0",
        "ubuntuhardy": "ubuntu8.04",
        "ubuntuintrepid": "ubuntu8.10",
        "ubuntujaunty": "ubuntu9.04",
        "ubuntukarmic": "ubuntu9.10",
        "ubuntulucid": "ubuntu10.04",
        "ubuntumaverick": "ubuntu10.10",
        "ubuntunatty": "ubuntu11.04",
        "ubuntuoneiric": "ubuntu11.10",
        "ubuntuprecise": "ubuntu12.04",
        "ubuntuquantal": "ubuntu12.10",
        "ubunturaring": "ubuntu13.04",
        "ubuntusaucy": "ubuntu13.10",
        "virtio26": "fedora10",
        "vista": "winvista",
        "winxp64": "winxp",

        # Old --os-type values
        "linux": "generic",
        "windows": "winxp",
        "solaris": "solaris10",
        "unix": "freebsd9.0",
        "other": "generic",
    }


    #################
    # Internal APIs #
    #################

    def _make_default_variants(self):
        ret = {}

        # Generic variant
        v = _OsVariant(None)
        ret[v.name] = v
        return ret

    @property
    def _os_loader(self):
        if not self.__os_loader:
            loader = libosinfo.Loader()
            loader.process_default_path()

            self.__os_loader = loader
        return self.__os_loader

    @property
    def _all_variants(self):
        if not self.__all_variants:
            loader = self._os_loader
            allvariants = self._make_default_variants()
            db = loader.get_db()
            oslist = db.get_os_list()
            for os in range(oslist.get_length()):
                osi = _OsVariant(oslist.get_nth(os))
                allvariants[osi.name] = osi

            self.__all_variants = allvariants
        return self.__all_variants


    ###############
    # Public APIs #
    ###############

    def lookup_os_by_full_id(self, full_id):
        for osobj in self._all_variants.values():
            if osobj.full_id == full_id:
                return osobj

    def lookup_os(self, key):
        if key in self._aliases:
            alias = self._aliases[key]
            # Added 2018-10-02. Maybe remove aliases in a year
            logging.warning(
                _("OS name '%s' is deprecated, using '%s' instead. "
                  "This alias will be removed in the future."), key, alias)
            key = alias
        return self._all_variants.get(key)

    def guess_os_by_iso(self, location):
        try:
            media = libosinfo.Media.create_from_location(location, None)
        except Exception as e:
            logging.debug("Error creating libosinfo media object: %s", str(e))
            return None

        if not self._os_loader.get_db().identify_media(media):
            return None
        return media.get_os().get_short_id(), media

    def list_os(self):
        """
        List all OSes in the DB
        """
        sortmap = {}

        for name, osobj in self._all_variants.items():
            sortmap[name] = osobj

        return _sort(sortmap)


#####################
# OsVariant classes #
#####################

class _OsVariant(object):
    def __init__(self, o):
        self._os = o
        self._family = self._os and self._os.get_family() or None

        self.full_id = self._os and self._os.get_id() or None
        self.name = self._os and self._os.get_short_id() or "generic"
        self.label = self._os and self._os.get_name() or "Generic default"
        self.codename = self._os and self._os.get_codename() or ""
        self.distro = self._os and self._os.get_distro() or ""
        self.version = self._os and self._os.get_version() or None

        self.eol = self._get_eol()

    def __repr__(self):
        return "<%s name=%s>" % (self.__class__.__name__, self.name)


    ########################
    # Internal helper APIs #
    ########################

    def _is_related_to(self, related_os_list, os=None,
            check_derives=True, check_upgrades=True, check_clones=True):
        os = os or self._os
        if not os:
            return False

        if os.get_short_id() in related_os_list:
            return True

        check_list = []
        def _extend(newl):
            for obj in newl:
                if obj not in check_list:
                    check_list.append(obj)

        if check_derives:
            _extend(os.get_related(
                libosinfo.ProductRelationship.DERIVES_FROM).get_elements())
        if check_clones:
            _extend(os.get_related(
                libosinfo.ProductRelationship.CLONES).get_elements())
        if check_upgrades:
            _extend(os.get_related(
                libosinfo.ProductRelationship.UPGRADES).get_elements())

        for checkobj in check_list:
            if (checkobj.get_short_id() in related_os_list or
                self._is_related_to(related_os_list, os=checkobj,
                    check_upgrades=check_upgrades,
                    check_derives=check_derives,
                    check_clones=check_clones)):
                return True

        return False

    def _get_all_devices(self):
        if not self._os:
            return []
        devlist = self._os.get_all_devices()
        return [devlist.get_nth(i) for i in range(devlist.get_length())]

    def _device_filter(self, devids=None, cls=None):
        ret = []
        devids = devids or []
        for dev in self._get_all_devices():
            if devids and dev.get_id() not in devids:
                continue
            if cls and not re.match(cls, dev.get_class()):
                continue
            ret.append(dev.get_name())
        return ret


    ###############
    # Cached APIs #
    ###############

    def _get_eol(self):
        eol = self._os and self._os.get_eol_date() or None
        rel = self._os and self._os.get_release_date() or None

        # We can use os.get_release_status() & osinfo.ReleaseStatus.ROLLING
        # if we require libosinfo >= 1.4.0.
        release_status = self._os and self._os.get_param_value(
                libosinfo.OS_PROP_RELEASE_STATUS) or None

        def _glib_to_datetime(glibdate):
            date = "%s-%s" % (glibdate.get_year(), glibdate.get_day_of_year())
            return datetime.datetime.strptime(date, "%Y-%j")

        now = datetime.datetime.today()
        if eol is not None:
            return now > _glib_to_datetime(eol)

        # Rolling distributions are never EOL.
        if release_status == "rolling":
            return False

        # If no EOL is present, assume EOL if release was > 5 years ago
        if rel is not None:
            rel5 = _glib_to_datetime(rel) + datetime.timedelta(days=365 * 5)
            return now > rel5
        return False


    ###############
    # Public APIs #
    ###############

    def get_handle(self):
        return self._os

    def is_generic(self):
        return self._os is None

    def is_windows(self):
        return self._family in ['win9x', 'winnt', 'win16']

    def broken_x2apic(self):
        # x2apic breaks networking in solaris10
        # https://bugs.launchpad.net/bugs/1395217
        return self.name in ('solaris10', 'solaris11')

    def broken_uefi_with_hyperv(self):
        # Some windows versions are broken with hyperv enlightenments + UEFI
        # https://bugzilla.redhat.com/show_bug.cgi?id=1185253
        # https://bugs.launchpad.net/qemu/+bug/1593605
        return self.name in ("win2k8r2", "win7")

    def get_clock(self):
        if self.is_windows() or self._family in ['solaris']:
            return "localtime"
        return "utc"

    def supported_netmodels(self):
        return self._device_filter(cls="net")

    def supports_usbtablet(self):
        # If no OS specified, still default to tablet
        if not self._os:
            return True

        devids = ["http://usb.org/usb/80ee/0021"]
        return bool(self._device_filter(devids=devids))

    def supports_virtiodisk(self):
        # virtio-block and virtio1.0-block
        devids = ["http://pcisig.com/pci/1af4/1001",
                  "http://pcisig.com/pci/1af4/1042"]
        return bool(self._device_filter(devids=devids))

    def supports_virtionet(self):
        # virtio-net and virtio1.0-net
        devids = ["http://pcisig.com/pci/1af4/1000",
                  "http://pcisig.com/pci/1af4/1041"]
        return bool(self._device_filter(devids=devids))

    def supports_virtiorng(self):
        # virtio-rng and virtio1.0-rng
        devids = ["http://pcisig.com/pci/1af4/1005",
                  "http://pcisig.com/pci/1af4/1044"]
        return bool(self._device_filter(devids=devids))

    def supports_virtioserial(self):
        devids = ["http://pcisig.com/pci/1af4/1003",
                  "http://pcisig.com/pci/1af4/1043"]
        if self._device_filter(devids=devids):
            return True
        # osinfo data was wrong for RHEL/centos here until Oct 2018
        # Remove this hack after 6 months or so
        return self._is_related_to("rhel6.0")

    def supports_usb3(self):
        # qemu-xhci
        devids = ["http://pcisig.com/pci/1b36/0004"]
        return bool(self._device_filter(devids=devids))

    def supports_virtio1(self):
        # Use virtio1.0-net device as a proxy for virtio1.0 as a whole
        devids = ["http://pcisig.com/pci/1af4/1041"]
        return bool(self._device_filter(devids=devids))

    def supports_chipset_q35(self):
        # For our purposes, check for the union of q35 + virtio1.0 support
        if self.supports_virtionet() and not self.supports_virtio1():
            return False
        devids = ["http://qemu.org/chipset/x86/q35"]
        return bool(self._device_filter(devids=devids))

    def get_recommended_resources(self, guest):
        ret = {}
        if not self._os:
            return ret

        def read_resource(resources, minimum, arch):
            # If we are reading the "minimum" block, allocate more
            # resources.
            ram_scale = minimum and 2 or 1
            n_cpus_scale = minimum and 2 or 1
            storage_scale = minimum and 2 or 1
            for i in range(resources.get_length()):
                r = resources.get_nth(i)
                if r.get_architecture() == arch:
                    ret["ram"] = r.get_ram() * ram_scale
                    ret["cpu"] = r.get_cpu()
                    ret["n-cpus"] = r.get_n_cpus() * n_cpus_scale
                    ret["storage"] = r.get_storage() * storage_scale
                    break

        # libosinfo may miss the recommended resources block for some OS,
        # in this case read first the minimum resources (if present)
        # and use them.
        read_resource(self._os.get_minimum_resources(), True, "all")
        read_resource(self._os.get_minimum_resources(), True, guest.os.arch)
        read_resource(self._os.get_recommended_resources(), False, "all")
        read_resource(self._os.get_recommended_resources(),
            False, guest.os.arch)

        # QEMU TCG doesn't gain anything by having extra VCPUs
        if guest.type == "qemu":
            ret["n-cpus"] = 1

        return ret

    def get_kernel_url_arg(self):
        """
        Kernel argument name the distro's installer uses to reference
        a network source, possibly bypassing some installer prompts
        """
        if not self._os:
            return None

        # SUSE distros
        if self.distro in ["caasp", "sle", "sled", "sles", "opensuse"]:
            return "install"

        if self.distro not in ["centos", "rhel", "fedora"]:
            return None

        # Red Hat distros
        if self.name.endswith("-unknown"):
            return "inst.repo"

        try:
            version = float(self.version)
        except Exception:
            return None

        if self.distro in ["centos", "rhel"]:
            if version < 7:
                return "method"
            return "inst.repo"

        if self.distro in ["fedora"]:
            if version < 19:
                return "method"
            return "inst.repo"

        return None

    def get_location(self, arch):
        if not self._os:
            return None

        treefilter = libosinfo.Filter()
        treefilter.add_constraint(libosinfo.TREE_PROP_ARCHITECTURE, arch)

        treelist = self._os.get_tree_list()
        if treelist.get_length() < 1:
            raise RuntimeError(
                _("%s does not have a URL location") % self.name)

        filtered_treelist = treelist.new_filtered(treefilter)
        if filtered_treelist.get_length() < 1:
            raise RuntimeError(
                _("%s does not have a URL location for the %s architecture") %
                (self.name, arch))

        # Some distros have more than one URL for a specific architecture,
        # which is the case for Fedora and different variants (Server,
        # Workstation). Later on, we'll have to differentiate that and return
        # the right one.
        return filtered_treelist.get_nth(0).get_url()

    def get_install_script(self, profile):
        if not self._os:
            return None

        script_list = self._os.get_install_script_list()
        if script_list.get_length() == 0:
            raise RuntimeError(
                _("%s does not support unattended installation.") % self.name)

        profile_filter = libosinfo.Filter()
        profile_filter.add_constraint(
            libosinfo.INSTALL_SCRIPT_PROP_PROFILE, profile)

        filtered_script_list = script_list.new_filtered(profile_filter)
        if filtered_script_list.get_length() == 0:
            raise RuntimeError(
                _("%s does not support unattended installation for the '%s' "
                  "profile.") % (self.name, profile))

        logging.debug("Install script found for profile '%s'", profile)

        # Some OSes (as Windows) have more than one installer script, depending
        # on the OS version and profile choosen, to be used to perform the
        # unattended installation. Let's just deal with multiple installer
        # scripts when its actually needed, though.
        installscript = filtered_script_list.get_nth(0)
        return installscript


class OSInstallScript:
    """
    Wrapper for Libosinfo.InstallScript interactions
    """
    def __init__(self, script, osobj):
        self._script = script
        self._osobj = osobj

    def get_expected_filename(self):
        return self._script.get_expected_filename()

    def set_preferred_injection_method(self, method):
        def nick_to_value(method):
            injection_methods = [
                    libosinfo.InstallScriptInjectionMethod.CDROM,
                    libosinfo.InstallScriptInjectionMethod.DISK,
                    libosinfo.InstallScriptInjectionMethod.FLOPPY,
                    libosinfo.InstallScriptInjectionMethod.INITRD,
                    libosinfo.InstallScriptInjectionMethod.WEB]

            for m in injection_methods:
                if method == m.value_nicks[0]:
                    return m

            raise RuntimeError(
                _("%s is a non-valid injection method in libosinfo."))

        injection_method = nick_to_value(method)
        supported_injection_methods = self._script.get_injection_methods()
        if (injection_method & supported_injection_methods == 0):
            raise RuntimeError(
                _("OS '%s' unattended install is not supported") %
                self._osobj.name)

        logging.debug("Using '%s' injection method", method)
        self._script.set_preferred_injection_method(injection_method)

    def set_installation_source(self, source):
        def nick_to_value(source):
            installation_sources = [
                    libosinfo.InstallScriptInstallationSource.MEDIA,
                    libosinfo.InstallScriptInstallationSource.NETWORK]

            for s in installation_sources:
                if source == s.value_nick:
                    return s

            raise RuntimeError(
                _("%s is a non-valid installation source in libosinfo.") %
                source)

        installation_source = nick_to_value(source)

        logging.debug("Using '%s' installation source", source)
        self._script.set_installation_source(installation_source)

    def get_config(self, unattended_data, arch, hostname):
        def requires_param(config_param):
            param = self._script.get_config_param(config_param)

            if not param or param.is_optional():
                return False

            return True

        def requires_user_password():
            return requires_param(libosinfo.INSTALL_CONFIG_PROP_USER_PASSWORD)

        def requires_admin_password():
            return requires_param(libosinfo.INSTALL_CONFIG_PROP_ADMIN_PASSWORD)

        def get_timezone():
            TZ_FILE = "/etc/localtime"
            localtime = gio.File.new_for_path(TZ_FILE)
            if not localtime.query_exists():
                return None
            info = localtime.query_info(
                gio.FILE_ATTRIBUTE_STANDARD_SYMLINK_TARGET,
                gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS)
            if not info:
                return None
            target = info.get_symlink_target()
            if not target:
                return None
            tokens = target.split("zoneinfo/")
            if not tokens or len(tokens) < 2:
                return None
            return tokens[1]

        def get_language():
            names = glib.get_language_names()
            if not names or len(names) < 2:
                return None
            return names[1]

        config = libosinfo.InstallConfig()

        # Set user login and name based on the one from the system
        config.set_user_login(glib.get_user_name())
        config.set_user_realname(glib.get_real_name())

        # Set user-password.
        # In case it's required and not passed, just raise a RuntimeError.
        if requires_user_password() and not unattended_data.user_password:
            raise RuntimeError(
                _("%s requires the user-password to be set.") %
                self._osobj.name)
        config.set_user_password(
            unattended_data.user_password if unattended_data.user_password
            else "")

        # Set the admin-password:
        # In case it's required and not passed, just raise a RuntimeError.
        if requires_admin_password() and not unattended_data.admin_password:
            raise RuntimeError(
                _("%s requires the admin-password to be set.") %
                self._osobj.name)
        config.set_admin_password(
            unattended_data.admin_password if unattended_data.admin_password
            else "")

        # Set the target disk.
        # virtiodisk is the preferred way, in case it's supported, otherwise
        # just fallback to scsi.
        #
        # Note: this is linux specific and will require some changes whenever
        # support for Windows will be added.
        tgt = "/dev/vda" if self._osobj.supports_virtiodisk() else "/dev/sda"
        config.set_target_disk(tgt)

        # Set hardware architecture and hostname
        config.set_hardware_arch(arch)
        config.set_hostname(hostname)

        # Try to guess the timezone from '/etc/localtime', in case it's not
        # possible 'America/New_York' will be used.
        timezone = get_timezone()
        if timezone:
            config.set_l10n_timezone(timezone)
        else:
            logging.warning(
                _("'America/New_York' timezone will be used for this "
                  "unattended installation."))

        # Try to guess to language and keyboard layout from the system's
        # language.
        #
        # This method has flows as it's quite common to have language and
        # keyboard layout not matching. Otherwise, there's no easy way to guess
        # the keyboard layout without relying on a set of APIs of an specific
        # Desktop Environment.
        language = get_language()
        if language:
            config.set_l10n_language(language)
            config.set_l10n_keyboard(language)
        else:
            logging.warning(
                _("'en_US' will be used as both language and keyboard layout "
                  "for unattended installation."))

        logging.debug("InstallScriptConfig created with the following params:")
        logging.debug("username: %s", config.get_user_login())
        logging.debug("realname: %s", config.get_user_realname())
        logging.debug("user password: %s", config.get_user_password())
        logging.debug("admin password: %s", config.get_admin_password())
        logging.debug("target disk: %s", config.get_target_disk())
        logging.debug("hardware arch: %s", config.get_hardware_arch())
        logging.debug("hostname: %s", config.get_hostname())
        logging.debug("timezone: %s", config.get_l10n_timezone())
        logging.debug("language: %s", config.get_l10n_language())
        logging.debug("keyboard: %s", config.get_l10n_keyboard())

        return config

    def generate_output(self, config, output_dir):
        self._script.generate_output(
                self._osobj.get_handle(), config, output_dir)

    def generate_cmdline(self, config):
        return self._script.generate_command_line(
                self._osobj.get_handle(), config)


OSDB = _OSDB()

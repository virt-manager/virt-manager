#
# Common code for unattended installations
#
# Copyright 2019 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import getpass
import locale
import os
import pwd
import re
import tempfile

from gi.repository import Libosinfo

from . import urlfetcher
from .. import progress
from ..logger import log


def _is_user_login_safe(login):
    return login != "root"


def _login_from_hostuser():
    hostuser = getpass.getuser()
    realname = pwd.getpwnam(hostuser).pw_gecos
    if not _is_user_login_safe(hostuser):
        return None, None  # pragma: no cover
    return hostuser, realname  # pragma: no cover


def _make_installconfig(script, osobj, unattended_data, arch, hostname, url):
    """
    Build a Libosinfo.InstallConfig instance
    """
    def get_timezone():
        TZ_FILE = "/etc/localtime"
        linkpath = os.path.realpath(TZ_FILE)
        tokens = linkpath.split("zoneinfo/")
        if len(tokens) > 1:
            return tokens[1]

    def get_language():
        return locale.getlocale()[0]

    config = Libosinfo.InstallConfig()

    # Set user login and name
    # In case it's specified via command-line, use the specified one as login
    # and realname. Otherwise, fallback fto the one from the system
    login = unattended_data.user_login
    realname = unattended_data.user_login
    if not login:
        login, realname = _login_from_hostuser()

    if login:
        login = login.lower()
        if not _is_user_login_safe(login):
            raise RuntimeError(
                _("%(osname)s cannot use '%(loginname)s' as user-login.") %
                {"osname": osobj.name, "loginname": login})

        config.set_user_login(login)
        config.set_user_realname(realname)

    # Set user-password.
    # In case it's required and not passed, just raise a RuntimeError.
    if (script.requires_user_password() and
        not unattended_data.get_user_password()):
        raise RuntimeError(
            _("%s requires the user-password to be set.") %
            osobj.name)
    config.set_user_password(unattended_data.get_user_password() or "")

    # Set the admin-password:
    # In case it's required and not passed, just raise a RuntimeError.
    if (script.requires_admin_password() and
        not unattended_data.get_admin_password()):
        raise RuntimeError(
            _("%s requires the admin-password to be set.") %
            osobj.name)
    config.set_admin_password(unattended_data.get_admin_password() or "")

    # Set the target disk.
    # virtiodisk is the preferred way, in case it's supported, otherwise
    # just fallback to scsi.
    #
    # Note: this is linux specific and will require some changes whenever
    # support for Windows will be added.
    tgt = "/dev/vda" if osobj.supports_virtiodisk() else "/dev/sda"
    if osobj.is_windows():
        tgt = "C"
    config.set_target_disk(tgt)

    # Set hardware architecture and hostname
    config.set_hardware_arch(arch)

    # Some installations will bail if the Computer's name contains one of the
    # following characters: "[{|}~[\\]^':; <=>?@!\"#$%`()+/.,*&]".
    # In order to take a safer path, let's ensure that we never set those,
    # replacing them by "-".
    hostname = re.sub("[{|}~[\\]^':; <=>?@!\"#$%`()+/.,*&]", "-", hostname)
    config.set_hostname(hostname)

    # Try to guess the timezone from '/etc/localtime', in case it's not
    # possible 'America/New_York' will be used.
    timezone = get_timezone()
    if timezone:
        config.set_l10n_timezone(timezone)

    # Try to guess to language and keyboard layout from the system's
    # language.
    #
    # This method has flaws as it's quite common to have language and
    # keyboard layout not matching. Otherwise, there's no easy way to guess
    # the keyboard layout without relying on a set of APIs of an specific
    # Desktop Environment.
    language = get_language()
    if language:
        config.set_l10n_language(language)
        config.set_l10n_keyboard(language)

    if url:
        config.set_installation_url(url)  # pylint: disable=no-member

    if unattended_data.reg_login:
        config.set_reg_login(unattended_data.reg_login)

    if unattended_data.product_key:
        config.set_reg_product_key(unattended_data.product_key)

    log.debug("InstallScriptConfig created with the following params:")
    log.debug("username: %s", config.get_user_login())
    log.debug("realname: %s", config.get_user_realname())
    log.debug("target disk: %s", config.get_target_disk())
    log.debug("hardware arch: %s", config.get_hardware_arch())
    log.debug("hostname: %s", config.get_hostname())
    log.debug("timezone: %s", config.get_l10n_timezone())
    log.debug("language: %s", config.get_l10n_language())
    log.debug("keyboard: %s", config.get_l10n_keyboard())
    if hasattr(config, "get_installation_url"):
        log.debug("url: %s",
                config.get_installation_url())  # pylint: disable=no-member
    log.debug("reg-login %s", config.get_reg_login())
    log.debug("product-key: %s", config.get_reg_product_key())

    return config


class OSInstallScript:
    """
    Wrapper for Libosinfo.InstallScript interactions
    """
    @staticmethod
    def have_new_libosinfo():
        from ..osdict import OSDB

        win7 = OSDB.lookup_os("win7")
        for script in win7.get_install_script_list():
            if (Libosinfo.InstallScriptInjectionMethod.CDROM &
                script.get_injection_methods()):
                return True
        return False  # pragma: no cover

    @staticmethod
    def have_libosinfo_installation_url():
        return hasattr(Libosinfo.InstallConfig, "set_installation_url")

    def __init__(self, script, osobj, osinfomediaobj, osinfotreeobj):
        self._script = script
        self._osobj = osobj
        self._osinfomediaobj = osinfomediaobj
        self._osinfotreeobj = osinfotreeobj
        self._config = None

        if not OSInstallScript.have_new_libosinfo():  # pragma: no cover
            raise RuntimeError(_("libosinfo or osinfo-db is too old to "
                "support unattended installs."))

    def get_expected_filename(self):
        return self._script.get_expected_filename()

    def set_preferred_injection_method(self, namestr):
        # If we ever make this user configurable, this will need to be smarter
        names = {
            "cdrom": Libosinfo.InstallScriptInjectionMethod.CDROM,
            "initrd": Libosinfo.InstallScriptInjectionMethod.INITRD,
        }

        log.debug("Using '%s' injection method", namestr)
        injection_method = names[namestr]
        supported_injection_methods = self._script.get_injection_methods()
        if (injection_method & supported_injection_methods == 0):
            raise RuntimeError(
                _("OS '%(osname)s' does not support required "
                  "injection method '%(methodname)s'") %
                {"osname": self._osobj.name, "methodname": namestr})

        self._script.set_preferred_injection_method(injection_method)

    def set_installation_source(self, namestr):
        # If we ever make this user configurable, this will need to be smarter
        names = {
            "media": Libosinfo.InstallScriptInstallationSource.MEDIA,
            "network": Libosinfo.InstallScriptInstallationSource.NETWORK,
        }

        log.debug("Using '%s' installation source", namestr)
        self._script.set_installation_source(names[namestr])

    def _requires_param(self, config_param):
        param = self._script.get_config_param(config_param)
        return bool(param and not param.is_optional())

    def requires_user_password(self):
        return self._requires_param(
                Libosinfo.INSTALL_CONFIG_PROP_USER_PASSWORD)
    def requires_admin_password(self):
        return self._requires_param(
                Libosinfo.INSTALL_CONFIG_PROP_ADMIN_PASSWORD)

    def set_config(self, config):
        self._config = config

    def generate(self):
        if self._osinfomediaobj:
            return self._script.generate_for_media(
                    self._osinfomediaobj, self._config)
        if hasattr(self._script, "generate_for_tree") and self._osinfotreeobj:
            # osinfo_install_script_generate_for_tree() is part of
            # libosinfo 1.6.0
            return self._script.generate_for_tree(
                    self._osinfotreeobj, self._config)

        return self._script.generate(self._osobj.get_handle(), self._config)

    def generate_cmdline(self):
        if self._osinfomediaobj:
            return self._script.generate_command_line_for_media(
                    self._osinfomediaobj, self._config)
        if (hasattr(self._script, "generate_command_line_for_tree") and
                self._osinfotreeobj):
            # osinfo_install_script_generate_command_line_for_tree() is part of
            # libosinfo 1.6.0
            return self._script.generate_command_line_for_tree(
                    self._osinfotreeobj, self._config)
        return self._script.generate_command_line(
                self._osobj.get_handle(), self._config)

    def _generate_debug(self):
        original_user_password = self._config.get_user_password()
        original_admin_password = self._config.get_admin_password()

        self._config.set_user_password("[SCRUBBLED]")
        self._config.set_admin_password("[SCRUBBLED]")

        debug_content = self.generate()

        self._config.set_user_password(original_user_password)
        self._config.set_admin_password(original_admin_password)

        return debug_content

    def write(self):
        fileobj = tempfile.NamedTemporaryFile(
            prefix="virtinst-unattended-script", delete=False)
        scriptpath = fileobj.name

        content = self.generate()
        open(scriptpath, "w").write(content)

        debug_content = self._generate_debug()

        log.debug("Generated unattended script: %s", scriptpath)
        log.debug("Generated script contents:\n%s", debug_content)

        return scriptpath


class UnattendedData():
    profile = None
    admin_password_file = None
    user_login = None
    user_password_file = None
    product_key = None
    reg_login = None

    def _get_password(self, pwdfile):
        with open(pwdfile, "r") as fobj:
            return fobj.readline().rstrip("\n\r")

    def get_user_password(self):
        if self.user_password_file:
            return self._get_password(self.user_password_file)

    def get_admin_password(self):
        if self.admin_password_file:
            return self._get_password(self.admin_password_file)


def _make_scriptmap(script_list):
    """
    Generate a mapping of profile name -> [list, of, rawscripts]
    """
    script_map = {}
    for script in script_list:
        profile = script.get_profile()
        if profile not in script_map:
            script_map[profile] = []
        script_map[profile].append(script)
    return script_map


def _find_default_profile(profile_names):
    profile_prefs = ["desktop"]
    found = None
    for p in profile_prefs:
        if p in profile_names:
            found = p
            break
    return found or profile_names[0]


def _lookup_rawscripts(osinfo, profile, os_media):
    script_list = []

    if os_media:
        if not os_media.supports_installer_script():
            # This is a specific annotation for media like livecds that
            # don't support unattended installs
            raise RuntimeError(
                _("OS '%s' media does not support unattended "
                  "installation") % (osinfo.name))

        # In case we're dealing with a media installation, let's try to get
        # the installer scripts from the media, in case any is set.
        script_list = os_media.get_install_script_list()

    if not script_list:
        script_list = osinfo.get_install_script_list()
    if not script_list:
        raise RuntimeError(
            _("OS '%s' does not support unattended installation.") %
            osinfo.name)

    script_map = _make_scriptmap(script_list)
    profile_names = list(sorted(script_map.keys()))
    if profile:
        rawscripts = script_map.get(profile, [])
        if not rawscripts:
            raise RuntimeError(
                _("OS '%(osname)s' does not support unattended "
                  "installation for the '%(profilename)s' profile. "
                  "Available profiles: %(profiles)s") %
                {"osname": osinfo.name, "profilename": profile,
                 "profiles": ", ".join(profile_names)})
    else:
        profile = _find_default_profile(profile_names)
        log.warning(_("Using unattended profile '%s'"), profile)
        rawscripts = script_map[profile]

    # Some OSes (as Windows) have more than one installer script,
    # depending on the OS version and profile chosen, to be used to
    # perform the unattended installation.
    ids = []
    for rawscript in rawscripts:
        ids.append(rawscript.get_id())

    log.debug("Install scripts found for profile '%s': %s",
            profile, ", ".join(ids))
    return rawscripts


def prepare_install_scripts(guest, unattended_data,
        url, os_media, os_tree, injection_method):
    def _get_installation_source(os_media):
        if not os_media:
            return "network"
        return "media"

    scripts = []
    rawscripts = _lookup_rawscripts(guest.osinfo,
            unattended_data.profile, os_media)

    osinfomediaobj = os_media.get_osinfo_media() if os_media else None
    osinfotreeobj = os_tree.get_osinfo_tree() if os_tree else None

    for rawscript in rawscripts:
        script = OSInstallScript(
                rawscript, guest.osinfo, osinfomediaobj, osinfotreeobj)

        script.set_preferred_injection_method(injection_method)

        installationsource = _get_installation_source(os_media)
        script.set_installation_source(installationsource)

        config = _make_installconfig(script, guest.osinfo, unattended_data,
                guest.os.arch, guest.name, url)
        script.set_config(config)
        scripts.append(script)
    return scripts


def download_drivers(locations, scratchdir, meter):
    meter = progress.ensure_meter(meter)
    fetcher = urlfetcher.DirectFetcher(None, scratchdir, meter)
    fetcher.meter = meter

    drivers = []

    try:
        for location in locations:
            filename = location.rsplit('/', 1)[1]
            driver = fetcher.acquireFile(location)
            drivers.append((driver, filename))
    except Exception:  # pragma: no cover
        for driverpair in drivers:
            os.unlink(driverpair[0])
        raise

    return drivers

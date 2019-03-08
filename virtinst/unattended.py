#
# Common code for unattended installations
#
# Copyright 2019 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import os

import gi
gi.require_version('Libosinfo', '1.0')
from gi.repository import Libosinfo
from gi.repository import Gio
from gi.repository import GLib

from . import util


def _make_installconfig(script, osobj, unattended_data, arch, hostname, url):
    """
    Build a Libosinfo.InstallConfig instance
    """
    def get_timezone():
        TZ_FILE = "/etc/localtime"
        localtime = Gio.File.new_for_path(TZ_FILE)
        if not localtime.query_exists():
            return None
        info = localtime.query_info(
            Gio.FILE_ATTRIBUTE_STANDARD_SYMLINK_TARGET,
            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS)
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
        names = GLib.get_language_names()
        if not names or len(names) < 2:
            return None
        return names[1]

    config = Libosinfo.InstallConfig()

    # Set user login and name based on the one from the system
    config.set_user_login(GLib.get_user_name())
    config.set_user_realname(GLib.get_real_name())

    # Set user-password.
    # In case it's required and not passed, just raise a RuntimeError.
    if script.requires_user_password() and not unattended_data.user_password:
        raise RuntimeError(
            _("%s requires the user-password to be set.") %
            osobj.name)
    config.set_user_password(
        unattended_data.user_password if unattended_data.user_password
        else "")

    # Set the admin-password:
    # In case it's required and not passed, just raise a RuntimeError.
    if script.requires_admin_password() and not unattended_data.admin_password:
        raise RuntimeError(
            _("%s requires the admin-password to be set.") %
            osobj.name)
    config.set_admin_password(
        unattended_data.admin_password if unattended_data.admin_password
        else "")

    # Set the target disk.
    # virtiodisk is the preferred way, in case it's supported, otherwise
    # just fallback to scsi.
    #
    # Note: this is linux specific and will require some changes whenever
    # support for Windows will be added.
    tgt = "/dev/vda" if osobj.supports_virtiodisk() else "/dev/sda"
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

    if url:
        config.set_installation_url(url)  # pylint: disable=no-member

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
    logging.debug("url: %s",
            config.get_installation_url())  # pylint: disable=no-member

    return config


class OSInstallScript:
    """
    Wrapper for Libosinfo.InstallScript interactions
    """
    @staticmethod
    def have_new_libosinfo():
        return hasattr(Libosinfo.InstallConfig, "set_installation_url")

    def __init__(self, script, osobj):
        self._script = script
        self._osobj = osobj
        self._config = None

        if not OSInstallScript.have_new_libosinfo():
            raise RuntimeError(_("libosinfo is too old to support unattended "
                "installs."))

    def get_expected_filename(self):
        return self._script.get_expected_filename()

    def set_preferred_injection_method(self, method):
        def nick_to_value(method):
            injection_methods = [
                    Libosinfo.InstallScriptInjectionMethod.CDROM,
                    Libosinfo.InstallScriptInjectionMethod.DISK,
                    Libosinfo.InstallScriptInjectionMethod.FLOPPY,
                    Libosinfo.InstallScriptInjectionMethod.INITRD,
                    Libosinfo.InstallScriptInjectionMethod.WEB]

            for m in injection_methods:
                # pylint: disable=no-member
                if method == m.value_nicks[0]:
                    return m

            raise RuntimeError(
                _("%s is a non-valid injection method in libosinfo.") % method)

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
            # This requires quite new libosinfo as of Mar 2019, disable
            # pylint errors here.
            # pylint: disable=no-member
            installation_sources = [
                    Libosinfo.InstallScriptInstallationSource.MEDIA,
                    Libosinfo.InstallScriptInstallationSource.NETWORK]

            for s in installation_sources:
                if source == s.value_nick:
                    return s

            raise RuntimeError(
                _("%s is a non-valid installation source in libosinfo.") %
                source)

        installation_source = nick_to_value(source)

        logging.debug("Using '%s' installation source", source)
        self._script.set_installation_source(installation_source)

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

    def generate_output(self, output_dir):
        self._script.generate_output(
                self._osobj.get_handle(), self._config, output_dir)

    def generate_cmdline(self):
        return self._script.generate_command_line(
                self._osobj.get_handle(), self._config)


class UnattendedData():
    profile = None
    admin_password = None
    user_password = None


def prepare_install_script(guest, unattended_data, url=None):
    rawscript = guest.osinfo.get_install_script(unattended_data.profile)
    script = OSInstallScript(rawscript, guest.osinfo)

    # For all tree based installations we're going to perform initrd injection
    # and install the systems via network.
    script.set_preferred_injection_method("initrd")
    script.set_installation_source("network")

    config = _make_installconfig(script, guest.osinfo, unattended_data,
            guest.os.arch, guest.name, url)
    script.set_config(config)
    return script


def generate_install_script(script):
    scratch = os.path.join(util.get_cache_dir(), "unattended")
    if not os.path.exists(scratch):
        os.makedirs(scratch, 0o751)

    script.generate_output(Gio.File.new_for_path(scratch))
    path = os.path.join(scratch, script.get_expected_filename())
    cmdline = script.generate_cmdline()

    return path, cmdline

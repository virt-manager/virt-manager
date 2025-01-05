# Copyright 2019 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import random
import re
import string
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from ..logger import log


class CloudInitData():
    disable = None
    root_password_generate = None
    root_password_file = None
    generated_root_password = None
    root_ssh_key = None
    clouduser_ssh_key = None
    user_data = None
    meta_data = None
    network_config = None

    @staticmethod
    def _fetch_url_content(url, fallback_encoding="utf-8"):
        """
        Fetch content from a URL with proper error handling and encoding detection.

        Args:
            url: The URL to fetch content from
            fallback_encoding: Encoding to use if not specified by the server

        Returns:
            str: The decoded content from the URL

        Raises:
            RuntimeError: If there are any HTTP or URL errors
        """
        try:
            with urlopen(url) as response:
                encoding = response.info().get_content_charset() or fallback_encoding
                return response.read().decode(encoding)
        except HTTPError as e:
            raise RuntimeError(f"cloud-init HTTP Error - {e.code} {e.reason} - ({url})")
        except URLError as e:
            raise RuntimeError(f"cloud-init URL Error - {e.reason} - ({url})")

    def _generate_password(self):
        if not self.generated_root_password:
            self.generated_root_password = ""
            for dummy in range(16):
                self.generated_root_password += random.choice(
                        string.ascii_letters + string.digits)
        return self.generated_root_password

    def _get_password(self, pwdfile):
        with open(pwdfile, "r") as fobj:
            return fobj.readline().rstrip("\n\r")

    def get_password_if_generated(self):
        if self.root_password_generate:
            return self._generate_password()

    def get_root_password(self):
        if self.root_password_file:
            return self._get_password(self.root_password_file)
        return self.get_password_if_generated()

    def get_root_ssh_key(self):
        if self.root_ssh_key:
            return self._get_password(self.root_ssh_key)

    def get_clouduser_ssh_key(self):
        if self.clouduser_ssh_key:
            return self._get_password(self.clouduser_ssh_key)

    @staticmethod
    def _validate_url_scheme(url):
        """
        Validate that the URL uses a supported scheme.

        Args:
            url: The URL to validate

        Raises:
            RuntimeError: If the scheme is not supported
        """
        scheme = urlparse(url).scheme
        if scheme and scheme not in ["http", "https"]:
            raise RuntimeError(
                f"cloud-init Protocol Error - {scheme} is unsupported (use http/https) - ({url})"
            )

def _create_metadata_content(cloudinit_data):
    content = ""
    if cloudinit_data.meta_data:
        log.debug("Using meta-data content from path=%s",
                cloudinit_data.meta_data)
        content = open(cloudinit_data.meta_data).read()
    return content


def _create_userdata_content(cloudinit_data):
    """Create the user-data content either from a file or URL"""
    if cloudinit_data.user_data:
        url_scheme = urlparse(cloudinit_data.user_data).scheme

        if not url_scheme:
            log.debug("Using user-data content from path=%s", cloudinit_data.user_data)
            return open(cloudinit_data.user_data).read()

        cloudinit_data._validate_url_scheme(cloudinit_data.user_data)
        log.debug("Fetching user-data content from URL=%s", cloudinit_data.user_data)
        return cloudinit_data._fetch_url_content(cloudinit_data.user_data)

    content = "#cloud-config\n"

    if cloudinit_data.root_password_generate or cloudinit_data.root_password_file:
        rootpass = cloudinit_data.get_root_password()
        content += "chpasswd:\n"
        content += "  list: |\n"
        content += "    root:%s\n" % rootpass

    if cloudinit_data.root_password_generate:
        content += "  expire: True\n"
    elif cloudinit_data.root_password_file:
        content += "  expire: False\n"

    if cloudinit_data.root_ssh_key:
        rootkey = cloudinit_data.get_root_ssh_key()
        content += "users:\n"
        content += "  - default\n"
        content += "  - name: root\n"
        content += "    ssh_authorized_keys:\n"
        content += "      - %s\n" % rootkey

    if cloudinit_data.clouduser_ssh_key:
        userkey = cloudinit_data.get_clouduser_ssh_key()
        content += "ssh_authorized_keys:\n"
        content += "  - %s\n" % userkey

    if cloudinit_data.disable:
        content += "runcmd:\n"
        content += ('- echo "Disabled by virt-install" > '
                    "/etc/cloud/cloud-init.disabled\n")

    clean_content = re.sub(r"root:(.*)", 'root:[SCRUBBLED]', content)
    if "VIRTINST_TEST_SUITE_PRINT_CLOUDINIT" in os.environ:
        print(clean_content)

    log.debug("Generated cloud-init userdata: \n%s", clean_content)
    return content


def _create_network_config_content(cloudinit_data):
    content = ""
    if cloudinit_data.network_config:
        log.debug("Using network-config content from path=%s",
                  cloudinit_data.network_config)
        content = open(cloudinit_data.network_config).read()
    return content


def create_files(scratchdir, cloudinit_data):
    metadata = _create_metadata_content(cloudinit_data)
    userdata = _create_userdata_content(cloudinit_data)

    data = [(metadata, "meta-data"), (userdata, "user-data")]
    network_config = _create_network_config_content(cloudinit_data)
    if network_config:
        data.append((network_config, 'network-config'))

    filepairs = []
    try:
        for content, destfile in data:
            fileobj = tempfile.NamedTemporaryFile(
                    prefix="virtinst-", suffix=("-%s" % destfile),
                    dir=scratchdir, delete=False)
            filename = fileobj.name
            filepairs.append((filename, destfile))

            with open(filename, "w+") as f:
                f.write(content)
    except Exception:  # pragma: no cover
        for filepair in filepairs:
            os.unlink(filepair[0])

    return filepairs

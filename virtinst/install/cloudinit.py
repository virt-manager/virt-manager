# Copyright 2019 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import random
import re
import string
import tempfile

from ..logger import log
from .. import progress
from . import urlfetcher


class _CloudInitConfig:
    """
    Helper class to create cloud-init configuration file.

    @destfile: Name of the cloud-init configuration file to be included
        in cloud-init ISO file.
    @content: Function to create the content of @destfile. It should return str
        to create the configuration file or None to not create the file.
    @config: Path to configuration file user provided to virt-install, if provided
        @content is ignored.
    @scratchdir: Directory where to place temporary files.
    """

    def __init__(self, destfile, content, config, scratchdir):
        self._destfile = destfile
        self._content = content
        self._config = config
        self._scratchdir = scratchdir

    def _create_file(self):
        content = self._content()

        if not content:
            return None

        fileobj = tempfile.NamedTemporaryFile(
            prefix="virtinst-", suffix=f"-{self._destfile}", dir=self._scratchdir, delete=False
        )
        with open(fileobj.name, "w+") as f:
            f.write(content)
        return fileobj.name

    def _fetch_file(self):
        log.debug("Using '%s' content from path='%s'", self._destfile, self._config)
        meter = progress.make_meter(quiet=True)
        fetcher = urlfetcher.DirectFetcher(None, self._scratchdir, meter)
        return fetcher.acquireFile(self._config)

    def add_filepair(self, filepairs):
        if self._config:
            file = self._fetch_file()
        else:
            file = self._create_file()

        if not file:
            return

        filepairs.append((file, self._destfile))


class CloudInitData:
    def __init__(self):
        self.disable = None
        self.root_password_generate = None
        self.root_password_file = None
        self.generated_root_password = None
        self.root_ssh_key = None
        self.clouduser_ssh_key = None
        self.user_data = None
        self.meta_data = None
        self.network_config = None

    def _generate_password(self):
        if not self.generated_root_password:
            self.generated_root_password = ""
            for dummy in range(16):
                self.generated_root_password += random.choice(string.ascii_letters + string.digits)
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

    def _create_metadata_content(self):
        return ""

    def _create_userdata_content(self):
        content = "#cloud-config\n"

        if self.root_password_generate or self.root_password_file:
            rootpass = self.get_root_password()
            content += "chpasswd:\n"
            content += "  list: |\n"
            content += "    root:%s\n" % rootpass

        if self.root_password_generate:
            content += "  expire: True\n"
        elif self.root_password_file:
            content += "  expire: False\n"

        if self.root_ssh_key:
            rootkey = self.get_root_ssh_key()
            content += "users:\n"
            content += "  - default\n"
            content += "  - name: root\n"
            content += "    ssh_authorized_keys:\n"
            content += "      - %s\n" % rootkey

        if self.clouduser_ssh_key:
            userkey = self.get_clouduser_ssh_key()
            content += "ssh_authorized_keys:\n"
            content += "  - %s\n" % userkey

        if self.disable:
            content += "runcmd:\n"
            content += '- echo "Disabled by virt-install" > /etc/cloud/cloud-init.disabled\n'

        clean_content = re.sub(r"root:(.*)", "root:[SCRUBBLED]", content)
        if "VIRTINST_TEST_SUITE_PRINT_CLOUDINIT" in os.environ:
            print(clean_content)

        log.debug("Generated cloud-init userdata: \n%s", clean_content)
        return content

    def _create_network_config_content(self):
        return None

    def create_files(self, scratchdir):
        meta_data = _CloudInitConfig(
            "meta-data", self._create_metadata_content, self.meta_data, scratchdir
        )
        user_data = _CloudInitConfig(
            "user-data", self._create_userdata_content, self.user_data, scratchdir
        )
        network_config = _CloudInitConfig(
            "network-config", self._create_network_config_content, self.network_config, scratchdir
        )

        filepairs = []
        try:
            meta_data.add_filepair(filepairs)
            user_data.add_filepair(filepairs)
            network_config.add_filepair(filepairs)
        except Exception:  # pragma: no cover
            for filepair in filepairs:
                os.unlink(filepair[0])
            raise

        return filepairs

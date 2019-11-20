import tempfile
import random
import string
import re
from ..logger import log


class CloudInitData():
    disable = None
    root_password_generate = None
    root_password_file = None
    generated_root_password = None
    ssh_key = None

    def generate_password(self):
        self.generated_root_password = ""
        for dummy in range(16):
            self.generated_root_password += random.choice(string.ascii_letters + string.digits)
        return self.generated_root_password

    def _get_password(self, pwdfile):
        with open(pwdfile, "r") as fobj:
            return fobj.readline().rstrip("\n\r")

    def get_root_password(self):
        if self.root_password_generate:
            return self.generate_password()
        elif self.root_password_file:
            return self._get_password(self.root_password_file)

    def get_ssh_key(self):
        if self.ssh_key:
            return self._get_password(self.ssh_key)


def create_metadata(scratchdir):
    fileobj = tempfile.NamedTemporaryFile(
            prefix="virtinst-", suffix="-metadata",
            dir=scratchdir, delete=False)
    filename = fileobj.name

    content = ""
    with open(filename, "w") as f:
        f.write(content)
    log.debug("Generated cloud-init metadata\n%s", content)
    return filename


def _create_userdata_content(cloudinit_data):
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

    if cloudinit_data.ssh_key:
        rootpass = cloudinit_data.get_ssh_key()
        content += "users:\n"
        content += "  - name: root\n"
        content += "    ssh-authorized-keys:\n"
        content += "      - %s\n" % rootpass

    if cloudinit_data.disable:
        content += "runcmd:\n"
        content += "- [ sudo, touch, /etc/cloud/cloud-init.disabled ]\n"

    log.debug("Generated cloud-init userdata: \n%s",
            re.sub(r"root:(.*)", 'root:[SCRUBBLED]', content))
    return content


def create_userdata(scratchdir, cloudinit_data):
    content = _create_userdata_content(cloudinit_data)

    fileobj = tempfile.NamedTemporaryFile(
            prefix="virtinst-", suffix="-userdata",
            dir=scratchdir, delete=False)
    filename = fileobj.name

    with open(filename, "w+") as f:
        f.write(content)
    return filename

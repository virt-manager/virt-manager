import tempfile
import random
import string
from ..logger import log


class CloudInitData():
    disable = None
    root_password = None
    root_password_file = None
    generated_root_password = None

    def generate_password(self):
        self.generated_root_password = ""
        for dummy in range(16):
            self.generated_root_password += random.choice(string.ascii_letters + string.digits)
        return self.generated_root_password

    def _get_password(self, pwdfile):
        with open(pwdfile, "r") as fobj:
            return fobj.readline().rstrip("\n\r")

    def get_root_password(self):
        if self.root_password == "generate":
            return self.generate_password()
        elif self.root_password_file:
            return self._get_password(self.root_password_file)
        else:
            return self.root_password


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


def create_userdata(scratchdir, cloudinit_data):
    content = "#cloud-config\n"

    rootpass = cloudinit_data.get_root_password()
    if rootpass:
        content += "chpasswd:\n"
        content += "  list: |\n"
        content += "    root:%s\n" % rootpass
        content += "  expire: True\n"

    if cloudinit_data.disable:
        content += "runcmd:\n"
        content += "- [ sudo, touch, /etc/cloud/cloud-init.disabled ]\n"
    log.debug("Generated cloud-init userdata:\n%s", content)

    fileobj = tempfile.NamedTemporaryFile(
            prefix="virtinst-", suffix="-userdata",
            dir=scratchdir, delete=False)
    filename = fileobj.name

    with open(filename, "w+") as f:
        f.write(content)
    return filename

import tempfile
import random
import string
from ..logger import log


class CloudInitData():
    disable = None
    root_password = None


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

    rootpass = cloudinit_data.root_password
    if rootpass == "generate":
        rootpass = ""
        for dummy in range(16):
            rootpass += random.choice(string.ascii_letters + string.digits)
        log.warning("Generated password for first boot: %s", rootpass)

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

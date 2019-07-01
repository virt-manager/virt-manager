import tempfile
import random
import string
import time
from ..logger import log


class CloudInitData():
    root_password = None


def create_metadata(scratchdir, hostname=None):
    if hostname:
        instance = hostname
    else:
        hostname = instance = "localhost"
    content = 'instance-id: %s\n' % instance
    content += 'hostname: %s\n' % hostname
    log.debug("Generated cloud-init metadata:\n%s", content)

    fileobj = tempfile.NamedTemporaryFile(
            prefix="virtinst-", suffix="-metadata",
            dir=scratchdir, delete=False)
    filename = fileobj.name

    with open(filename, "w") as f:
        f.write(content)
    return filename


def create_userdata(scratchdir, cloudinit_data, username=None, password=None):
    content = "#cloud-config\n"
    if username:
        content += "name: %s\n" % username
    if password:
        content += "password: %s\n" % password

    rootpass = cloudinit_data.root_password
    if rootpass == "generate":
        rootpass = ""
        for dummy in range(16):
            rootpass += random.choice(string.ascii_letters + string.digits)
        log.warning("Generated password for first boot: %s", rootpass)
        time.sleep(20)

    if rootpass:
        content += "chpasswd:\n"
        content += "  list: |\n"
        content += "    root:%s\n" % rootpass
        content += "  expire: True\n"

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

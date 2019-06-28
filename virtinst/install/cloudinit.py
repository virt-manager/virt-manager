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
    if not password:
        password = ""
        for dummy in range(16):
            password += random.choice(string.ascii_letters + string.digits)
    content = "#cloud-config\n"
    if username:
        content += "name: %s\n" % username
    if cloudinit_data.root_password == "generate":
        pass
    else:
        content += "password: %s\n" % password
        log.debug("Generated password for first boot: \n%s", password)
        time.sleep(20)
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

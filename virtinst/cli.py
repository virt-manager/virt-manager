#
# Utility functions for the command line drivers
#
# Copyright 2006-2007, 2013  Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

import itertools
import locale
import logging
import logging.handlers
import optparse
import os
import shlex
import sys
import traceback

import libvirt

from virtcli import cliconfig

import virtinst
from virtinst import util
from virtinst.util import listify

from virtinst import Guest
from virtinst import VirtualNetworkInterface
from virtinst import VirtualGraphics
from virtinst import VirtualAudio
from virtinst import VirtualDisk


DEFAULT_POOL_PATH = "/var/lib/libvirt/images"
DEFAULT_POOL_NAME = "default"

MIN_RAM = 64
force = False
quiet = False
doprompt = True


####################
# CLI init helpers #
####################

class VirtStreamHandler(logging.StreamHandler):

    def emit(self, record):
        """
        Based on the StreamHandler code from python 2.6: ripping out all
        the unicode handling and just uncoditionally logging seems to fix
        logging backtraces with unicode locales (for me at least).

        No doubt this is atrocious, but it WORKSFORME!
        """
        try:
            msg = self.format(record)
            stream = self.stream
            fs = "%s\n"

            stream.write(fs % msg)

            self.flush()
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


class VirtOptionParser(optparse.OptionParser):
    '''Subclass to get print_help to work properly with non-ascii text'''

    def _get_encoding(self, f):
        encoding = getattr(f, "encoding", None)
        if not encoding:
            encoding = locale.getlocale()[1]
        if not encoding:
            encoding = "UTF-8"
        return encoding

    def print_help(self, file=None):
        # pylint: disable=W0622
        # Redefining built in type 'file'
        if file is None:
            file = sys.stdout

        encoding = self._get_encoding(file)
        helpstr = self.format_help()
        try:
            encodedhelp = helpstr.encode(encoding, "replace")
        except UnicodeError:
            # I don't know why the above fails hard, unicode makes my head
            # spin. Just printing the format_help() output seems to work
            # quite fine, with the occasional character ?.
            encodedhelp = helpstr

        file.write(encodedhelp)


class VirtHelpFormatter(optparse.IndentedHelpFormatter):
    """
    Subclass the default help formatter to allow printing newline characters
    in --help output. The way we do this is a huge hack :(

    Inspiration: http://groups.google.com/group/comp.lang.python/browse_thread/thread/6df6e6b541a15bc2/09f28e26af0699b1
    """
    oldwrap = None

    def format_option(self, option):
        self.oldwrap = optparse.textwrap.wrap
        ret = []
        try:
            optparse.textwrap.wrap = self._textwrap_wrapper
            ret = optparse.IndentedHelpFormatter.format_option(self, option)
        finally:
            optparse.textwrap.wrap = self.oldwrap
        return ret

    def _textwrap_wrapper(self, text, width):
        ret = []
        for line in text.split("\n"):
            ret.extend(self.oldwrap(line, width))
        return ret


def setupParser(usage, description):
    parse_class = VirtOptionParser

    parser = parse_class(usage=usage, description=description,
                         formatter=VirtHelpFormatter(),
                         version=cliconfig.__version__)

    parser.epilog = _("See man page for examples and full option syntax.")

    return parser


def earlyLogging():
    logging.basicConfig(level=logging.DEBUG, format='%(message)s')


def setupLogging(appname, debug_stdout, do_quiet, cli_app=True):
    global quiet
    quiet = do_quiet

    dirname = "~/.virtinst"
    if appname == "virt-manager":
        dirname = "~/.virt-manager"

    vi_dir = os.path.expanduser(dirname)
    if not os.access(vi_dir, os.W_OK):
        if os.path.exists(vi_dir):
            raise RuntimeError("No write access to directory %s" % vi_dir)

        try:
            os.mkdir(vi_dir, 0751)
        except IOError, e:
            raise RuntimeError("Could not create directory %s: %s" %
                               (vi_dir, e))


    dateFormat = "%a, %d %b %Y %H:%M:%S"
    fileFormat = ("[%(asctime)s " + appname + " %(process)d] "
                  "%(levelname)s (%(module)s:%(lineno)d) %(message)s")
    streamErrorFormat = "%(levelname)-8s %(message)s"
    filename = os.path.join(vi_dir, appname + ".log")

    rootLogger = logging.getLogger()

    # Undo early logging
    for handler in rootLogger.handlers:
        rootLogger.removeHandler(handler)

    rootLogger.setLevel(logging.DEBUG)
    fileHandler = logging.handlers.RotatingFileHandler(filename, "ae",
                                                       1024 * 1024, 5)
    fileHandler.setFormatter(logging.Formatter(fileFormat,
                                               dateFormat))
    rootLogger.addHandler(fileHandler)

    streamHandler = VirtStreamHandler(sys.stderr)
    if debug_stdout:
        streamHandler.setLevel(logging.DEBUG)
        streamHandler.setFormatter(logging.Formatter(fileFormat,
                                                     dateFormat))
    elif not cli_app:
        streamHandler = None
    else:
        if quiet:
            level = logging.ERROR
        else:
            level = logging.WARN
        streamHandler.setLevel(level)
        streamHandler.setFormatter(logging.Formatter(streamErrorFormat))

    if streamHandler:
        rootLogger.addHandler(streamHandler)

    # Register libvirt handler
    def libvirt_callback(ignore, err):
        if err[3] != libvirt.VIR_ERR_ERROR:
            # Don't log libvirt errors: global error handler will do that
            logging.warn("Non-error from libvirt: '%s'", err[2])
    libvirt.registerErrorHandler(f=libvirt_callback, ctx=None)

    # Log uncaught exceptions
    def exception_log(typ, val, tb):
        logging.debug("Uncaught exception:\n%s",
                      "".join(traceback.format_exception(typ, val, tb)))
        sys.__excepthook__(typ, val, tb)
    sys.excepthook = exception_log

    # Log the app command string
    logging.debug("Launched with command line: %s", " ".join(sys.argv))


#######################################
# Libvirt connection helpers          #
#######################################

def getConnection(uri):
    logging.debug("Requesting libvirt URI %s", (uri or "default"))
    conn = virtinst.VirtualConnection(uri)
    conn.open(_do_creds_authname)
    conn.cache_object_fetch = True
    logging.debug("Received libvirt URI %s", conn.uri)

    return conn


# SASL username/pass auth
def _do_creds_authname(creds):
    retindex = 4

    for cred in creds:
        credtype, prompt, ignore, ignore, ignore = cred
        prompt += ": "

        res = cred[retindex]
        if credtype == libvirt.VIR_CRED_AUTHNAME:
            res = raw_input(prompt)
        elif credtype == libvirt.VIR_CRED_PASSPHRASE:
            import getpass
            res = getpass.getpass(prompt)
        else:
            raise RuntimeError("Unknown auth type in creds callback: %d" %
                               credtype)

        cred[retindex] = res
    return 0


##############################
# Misc CLI utility functions #
##############################

def fail(msg, do_exit=True):
    """
    Convenience function when failing in cli app
    """
    logging.error(msg)
    if traceback.format_exc().strip() != "None":
        logging.debug("", exc_info=True)
    if do_exit:
        _fail_exit()


def print_stdout(msg, do_force=False):
    if do_force or not quiet:
        print msg


def print_stderr(msg):
    logging.debug(msg)
    print >> sys.stderr, msg


def _fail_exit():
    sys.exit(1)


def nice_exit():
    print_stdout(_("Exiting at user request."))
    sys.exit(0)


def virsh_start_cmd(guest):
    return ("virsh --connect %s start %s" % (guest.conn.uri, guest.name))


def install_fail(guest):
    virshcmd = virsh_start_cmd(guest)

    print_stderr(
        _("Domain installation does not appear to have been successful.\n"
          "If it was, you can restart your domain by running:\n"
          "  %s\n"
          "otherwise, please restart your installation.") % virshcmd)
    sys.exit(1)


def build_default_pool(guest):
    if not guest.conn.check_conn_support(guest.conn.SUPPORT_CONN_STORAGE):
        # VirtualDisk will raise an error for us
        return

    pool = None
    try:
        pool = guest.conn.storagePoolLookupByName(DEFAULT_POOL_NAME)
    except libvirt.libvirtError:
        pass

    if pool:
        return

    try:
        logging.debug("Attempting to build default pool with target '%s'",
                      DEFAULT_POOL_PATH)
        defpool = virtinst.Storage.DirectoryPool(conn=guest.conn,
                                                 name=DEFAULT_POOL_NAME,
                                                 target_path=DEFAULT_POOL_PATH)
        defpool.install(build=True, create=True, autostart=True)
    except Exception, e:
        raise RuntimeError(_("Couldn't create default storage pool '%s': %s") %
                             (DEFAULT_POOL_PATH, str(e)))


def partition(string, sep):
    if not string:
        return (None, None, None)

    if string.count(sep):
        splitres = string.split(sep, 1)
        ret = (splitres[0], sep, splitres[1])
    else:
        ret = (string, None, None)
    return ret


#######################
# CLI Prompting utils #
#######################

def set_force(val=True):
    global force
    force = val


def set_prompt(prompt=True):
    # Set whether we allow prompts, or fail if a prompt pops up
    global doprompt
    doprompt = prompt


def is_prompt():
    return doprompt


def yes_or_no_convert(s):
    if s is None:
        return None

    s = s.lower()
    if s in ("y", "yes", "1", "true", "t"):
        return True
    elif s in ("n", "no", "0", "false", "f"):
        return False
    return None


def yes_or_no(s):
    ret = yes_or_no_convert(s)
    if ret is None:
        raise ValueError(_("A yes or no response is required"))
    return ret


def prompt_for_input(noprompt_err, prompt="", val=None, failed=False):
    if val is not None:
        return val

    if force or not is_prompt():
        if failed:
            # We already failed validation in a previous function, just exit
            _fail_exit()

        fail(noprompt_err)

    print_stdout(prompt + " ", do_force=True)
    sys.stdout.flush()
    return sys.stdin.readline().strip()


def prompt_for_yes_or_no(warning, question):
    """catches yes_or_no errors and ensures a valid bool return"""
    if force:
        logging.debug("Forcing return value of True to prompt '%s'")
        return True

    errmsg = warning + _(" (Use --prompt or --force to override)")

    while 1:
        msg = warning
        if question:
            msg += ("\n" + question)

        inp = prompt_for_input(errmsg, msg, None)
        try:
            res = yes_or_no(inp)
            break
        except ValueError, e:
            logging.error(e)
            continue
    return res


def prompt_loop(prompt_txt, noprompt_err, passed_val, obj, param_name,
                err_txt="%s", func=None):
    """
    Prompt the user with 'prompt_txt' for a value. Set 'obj'.'param_name'
    to the entered value. If it errors, use 'err_txt' to print a error
    message, and then re prompt.
    """

    failed = False
    while True:
        passed_val = prompt_for_input(noprompt_err, prompt_txt, passed_val,
                                      failed)
        try:
            if func:
                return func(passed_val)
            setattr(obj, param_name, passed_val)
            break
        except (ValueError, RuntimeError), e:
            logging.error(err_txt, e)
            passed_val = None
            failed = True



# Specific function for disk prompting. Returns a validated VirtualDisk
# device.
#
def disk_prompt(conn, origpath, origsize, origsparse,
                prompt_txt=None,
                warn_overwrite=False, check_size=True,
                path_to_clone=None, origdev=None):

    askmsg = _("Do you really want to use this disk (yes or no)")
    retry_path = True

    no_path_needed = (origdev and
                      (origdev.get_vol_install() or
                       origdev.get_vol_object() or
                       origdev.can_be_empty()))

    def prompt_path(chkpath, chksize):
        """
        Prompt for disk path if nec
        """
        msg = None
        patherr = _("A disk path must be specified.")
        if path_to_clone:
            patherr = (_("A disk path must be specified to clone '%s'.") %
                       path_to_clone)

        if not prompt_txt:
            msg = _("What would you like to use as the disk (file path)?")
            if not chksize is None:
                msg = _("Please enter the path to the file you would like to "
                        "use for storage. It will have size %sGB.") % chksize

        if not no_path_needed:
            path = prompt_for_input(patherr, prompt_txt or msg, chkpath)
        else:
            path = None

        return path

    def prompt_size(chkpath, chksize, path_exists):
        """
        Prompt for disk size if nec.
        """
        sizeerr = _("A size must be specified for non-existent disks.")
        size_prompt = _("How large would you like the disk (%s) to "
                        "be (in gigabytes)?") % chkpath

        if (not chkpath or
            path_exists or
            chksize is not None or
            not check_size):
            return False, chksize

        try:
            chksize = prompt_loop(size_prompt, sizeerr, chksize, None, None,
                               func=float)
            return False, chksize
        except Exception, e:
            # Path is probably bogus, raise the error
            fail(str(e), do_exit=not is_prompt())
            return True, chksize

    def prompt_path_exists(dev):
        """
        Prompt if disk file already exists and preserve mode is not used
        """
        does_collide = (path_exists and
                        dev.type == dev.TYPE_FILE and
                        dev.device == dev.DEVICE_DISK)
        msg = (_("This will overwrite the existing path '%s'" % dev.path))

        if not does_collide:
            return False

        if warn_overwrite or is_prompt():
            return not prompt_for_yes_or_no(msg, askmsg)
        return False

    def prompt_inuse_conflict(dev):
        """
        Check if disk is inuse by another guest
        """
        names = dev.is_conflict_disk(conn)
        if not names:
            return False

        msg = (_("Disk %s is already in use by other guests %s." %
               (dev.path, names)))
        return not prompt_for_yes_or_no(msg, askmsg)

    def prompt_size_conflict(dev):
        """
        Check if specified size exceeds available storage
        """
        isfatal, errmsg = dev.is_size_conflict()
        if isfatal:
            fail(errmsg, do_exit=not is_prompt())
            return True

        if errmsg:
            return not prompt_for_yes_or_no(errmsg, askmsg)

        return False

    while 1:
        # If we fail within the loop, reprompt for size and path
        if not retry_path:
            origpath = None
            if not path_to_clone:
                origsize = None
        retry_path = False

        # Get disk path
        path = prompt_path(origpath, origsize)
        path_exists = VirtualDisk.path_exists(conn, path)

        # Get storage size
        didfail, size = prompt_size(path, origsize, path_exists)
        if didfail:
            continue

        # Build disk object for validation
        try:
            if origdev:
                dev = origdev
                if path is not None and path != dev.path:
                    dev.path = path
                if size is not None and size != dev.get_size():
                    dev.set_create_storage(size=size, sparse=origsparse)
            else:
                dev = VirtualDisk(conn)
                dev.path = path
                dev.set_create_storage(size=size, sparse=origsparse)
            dev.validate()
        except ValueError, e:
            if is_prompt():
                logging.error(e)
                continue
            else:
                fail(_("Error with storage parameters: %s" % str(e)))

        # Check if path exists
        if prompt_path_exists(dev):
            continue

        # Check disk in use by other guests
        if prompt_inuse_conflict(dev):
            continue

        # Check if disk exceeds available storage
        if prompt_size_conflict(dev):
            continue

        # Passed all validation, return disk instance
        return dev


#######################
# Validation wrappers #
#######################

name_missing    = _("--name is required")
ram_missing     = _("--ram amount in MB is required")


def get_name(name, guest, image_name=None):
    prompt_txt = _("What is the name of your virtual machine?")
    err_txt = name_missing

    if name is None:
        name = image_name
    prompt_loop(prompt_txt, err_txt, name, guest, "name")


def get_memory(memory, guest, image_memory=None):
    prompt_txt = _("How much RAM should be allocated (in megabytes)?")
    err_txt = ram_missing

    def check_memory(mem):
        mem = int(mem)
        if mem < MIN_RAM:
            raise ValueError(_("Installs currently require %d megs "
                               "of RAM.") % MIN_RAM)
        guest.memory = mem * 1024

    if memory is None and image_memory is not None:
        memory = int(image_memory)
    prompt_loop(prompt_txt, err_txt, memory, guest, "memory",
                func=check_memory)


def get_uuid(uuid, guest):
    if uuid:
        try:
            guest.uuid = uuid
        except ValueError, e:
            fail(e)


def get_vcpus(guest, vcpus, check_cpu, image_vcpus=None):
    """
    @param vcpus: value of the option '--vcpus' (str or None)
    @param check_cpu: Whether to check that the number virtual cpus requested
                      does not exceed physical CPUs (bool)
    @param guest: virtinst.Guest instance (object)
    @param image_vcpus: ? (It's not used currently and should be None.)
    """
    if vcpus is None:
        if image_vcpus is not None:
            vcpus = image_vcpus
        else:
            vcpus = ""

    parse_vcpu(guest, vcpus, image_vcpus)

    if check_cpu:
        hostinfo = guest.conn.getInfo()
        pcpus = hostinfo[4] * hostinfo[5] * hostinfo[6] * hostinfo[7]

        if guest.vcpus > pcpus:
            msg = _("You have asked for more virtual CPUs (%d) than there "
                    "are physical CPUs (%d) on the host. This will work, "
                    "but performance will be poor. ") % (guest.vcpus, pcpus)
            askmsg = _("Are you sure? (yes or no)")

            if not prompt_for_yes_or_no(msg, askmsg):
                nice_exit()


def get_cpuset(guest, cpuset, memory):
    conn = guest.conn
    if cpuset and cpuset != "auto":
        guest.cpuset = cpuset

    elif cpuset == "auto":
        tmpset = None
        try:
            tmpset = Guest.generate_cpuset(conn, memory)
        except Exception, e:
            logging.debug("Not setting cpuset: %s", str(e))

        if tmpset:
            logging.debug("Auto cpuset is: %s", tmpset)
            guest.cpuset = tmpset

    return


def _default_network_opts(guest):
    opts = ""
    if (guest.conn.is_qemu_session() or guest.conn.is_test()):
        opts = "user"
    else:
        net = util.default_network(guest.conn)
        opts = "%s=%s" % (net[0], net[1])

    return opts


def digest_networks(guest, options, numnics=1):
    macs     = listify(options.mac)
    networks = listify(options.network)
    bridges  = listify(options.bridge)

    if bridges and networks:
        fail(_("Cannot mix both --bridge and --network arguments"))

    if bridges:
        # Convert old --bridges to --networks
        networks = ["bridge:" + b for b in bridges]

    def padlist(l, padsize):
        l = listify(l)
        l.extend((padsize - len(l)) * [None])
        return l

    # If a plain mac is specified, have it imply a default network
    networks = padlist(networks, max(len(macs), numnics))
    macs = padlist(macs, len(networks))

    for idx in range(len(networks)):
        if networks[idx] is None:
            networks[idx] = _default_network_opts(guest)

    return networks, macs


def get_networks(guest, networks, macs):
    for idx in range(len(networks)):
        mac = macs[idx]
        netstr = networks[idx]

        try:
            dev = parse_network(guest, netstr, mac=mac)
            guest.add_device(dev)
        except Exception, e:
            fail(_("Error in network device parameters: %s") % str(e))


def set_os_variant(guest, distro_type, distro_variant):
    if not distro_type and not distro_variant:
        # Default to distro autodetection
        guest.os_autodetect = True
        return

    if (distro_type and str(distro_type).lower() != "none"):
        guest.set_os_type(distro_type)

    if (distro_variant and str(distro_variant).lower() != "none"):
        guest.set_os_variant(distro_variant)


def digest_graphics(guest, options, default_override=None):
    vnc = options.vnc
    vncport = options.vncport
    vnclisten = options.vnclisten
    nographics = options.nographics
    sdl = options.sdl
    keymap = options.keymap
    graphics = options.graphics

    if graphics and (vnc or sdl or keymap or vncport or vnclisten):
        fail(_("Cannot mix --graphics and old style graphical options"))

    optnum = sum([bool(g) for g in [vnc, nographics, sdl, graphics]])
    if optnum > 1:
        raise ValueError(_("Can't specify more than one of VNC, SDL, "
                           "--graphics or --nographics"))

    if graphics:
        return graphics

    if optnum == 0:
        # If no graphics specified, choose a default
        if default_override is True:
            if cliconfig.default_graphics in ["spice", "vnc", "sdl"]:
                return [cliconfig.default_graphics]
        elif default_override is False:
            nographics = True
        else:
            if guest.os.is_container():
                logging.debug("Container guest, defaulting to nographics")
                nographics = True
            elif "DISPLAY" in os.environ.keys():
                logging.debug("DISPLAY is set: looking for pre-configured graphics")
                if cliconfig.default_graphics in ["spice", "vnc", "sdl"]:
                    logging.debug("Defaulting graphics to pre-configured %s",
                                  cliconfig.default_graphics.upper())
                    return [cliconfig.default_graphics]
                logging.debug("No valid pre-configured graphics "
                              "found, defaulting to VNC")
                return ["vnc"]
            else:
                logging.debug("DISPLAY is not set: defaulting to nographics.")
                nographics = True


    # Build a --graphics command line from old style opts
    optstr = ((vnc and "vnc") or
              (sdl and "sdl") or
              (nographics and ("none")))
    if vnclisten:
        optstr += ",listen=%s" % vnclisten
    if vncport:
        optstr += ",port=%s" % vncport
    if keymap:
        optstr += ",keymap=%s" % keymap

    logging.debug("--graphics compat generated: %s", optstr)
    return [optstr]


def get_graphics(guest, graphics):
    for optstr in graphics:
        try:
            dev = parse_graphics(guest, optstr)
        except Exception, e:
            fail(_("Error in graphics device parameters: %s") % str(e))

        if dev:
            guest.add_device(dev)


def get_video(guest, video_models=None):
    video_models = video_models or []

    if guest.get_devices(VirtualGraphics.VIRTUAL_DEV_GRAPHICS):
        if not video_models:
            video_models.append(None)

    for model in video_models:
        guest.add_device(parse_video(guest, model))


def get_sound(old_sound_bool, sound_opts, guest):
    if not sound_opts:
        if old_sound_bool:
            guest.add_device(VirtualAudio(guest.conn))
        return

    for opts in listify(sound_opts):
        guest.add_device(parse_sound(guest, opts))


def get_hostdevs(hostdevs, guest):
    if not hostdevs:
        return

    for devname in hostdevs:
        guest.add_device(parse_hostdev(guest, devname))


def get_smartcard(guest, sc_opts):
    for sc in listify(sc_opts):
        try:
            dev = parse_smartcard(guest, sc)
        except Exception, e:
            fail(_("Error in smartcard device parameters: %s") % str(e))

        if dev:
            guest.add_device(dev)


def get_tpm(guest, tpm_opts):
    for tpm in listify(tpm_opts):
        try:
            dev = parse_tpm(guest, tpm)
        except Exception, e:
            fail(_("Error in TPM device parameters: %s") % str(e))

        if dev:
            guest.add_device(dev)


def get_controller(guest, sc_opts):
    for sc in listify(sc_opts):
        try:
            dev = parse_controller(guest, sc)
        except Exception, e:
            fail(_("Error in controller device parameters: %s") % str(e))

        if dev:
            guest.add_device(dev)


def get_redirdev(guest, sc_opts):
    for sc in listify(sc_opts):
        try:
            dev = parse_redirdev(guest, sc)
        except Exception, e:
            fail(_("Error in redirdev device parameters: %s") % str(e))

        if dev:
            guest.add_device(dev)


def get_memballoon(guest, sc_opts):
    for sc in listify(sc_opts):
        try:
            dev = parse_memballoon(guest, sc)
        except Exception, e:
            fail(_("Error in memballoon device parameters: %s") % str(e))

        if dev:
            guest.add_device(dev)

#############################
# Common CLI option/group   #
#############################


def add_connect_option(parser):
    parser.add_option("", "--connect", metavar="URI", dest="connect",
                      help=_("Connect to hypervisor with libvirt URI"))


def vcpu_cli_options(grp, backcompat=True):
    grp.add_option("", "--vcpus", dest="vcpus",
        help=_("Number of vcpus to configure for your guest. Ex:\n"
               "--vcpus 5\n"
               "--vcpus 5,maxcpus=10\n"
               "--vcpus sockets=2,cores=4,threads=2"))
    grp.add_option("", "--cpuset", dest="cpuset",
                   help=_("Set which physical CPUs domain can use."))
    grp.add_option("", "--cpu", dest="cpu",
        help=_("CPU model and features. Ex: --cpu coreduo,+x2apic"))

    if backcompat:
        grp.add_option("", "--check-cpu", action="store_true",
                       dest="check_cpu", help=optparse.SUPPRESS_HELP)


def graphics_option_group(parser):
    """
    Register vnc + sdl options for virt-install and virt-image
    """

    vncg = optparse.OptionGroup(parser, _("Graphics Configuration"))
    add_gfx_option(vncg)
    vncg.add_option("", "--vnc", action="store_true", dest="vnc",
                    help=optparse.SUPPRESS_HELP)
    vncg.add_option("", "--vncport", type="int", dest="vncport",
                    help=optparse.SUPPRESS_HELP)
    vncg.add_option("", "--vnclisten", dest="vnclisten",
                    help=optparse.SUPPRESS_HELP)
    vncg.add_option("-k", "--keymap", dest="keymap",
                    help=optparse.SUPPRESS_HELP)
    vncg.add_option("", "--sdl", action="store_true", dest="sdl",
                    help=optparse.SUPPRESS_HELP)
    vncg.add_option("", "--nographics", action="store_true",
                    help=optparse.SUPPRESS_HELP)
    return vncg


def network_option_group(parser):
    """
    Register common network options for virt-install and virt-image
    """
    netg = optparse.OptionGroup(parser, _("Networking Configuration"))

    add_net_option(netg)

    # Deprecated net options
    netg.add_option("-b", "--bridge", dest="bridge", action="append",
                    help=optparse.SUPPRESS_HELP)
    netg.add_option("-m", "--mac", dest="mac", action="append",
                    help=optparse.SUPPRESS_HELP)

    return netg


def add_net_option(devg):
    devg.add_option("-w", "--network", dest="network", action="append",
      help=_("Configure a guest network interface. Ex:\n"
             "--network bridge=mybr0\n"
             "--network network=my_libvirt_virtual_net\n"
             "--network network=mynet,model=virtio,mac=00:11..."))


def add_device_options(devg):
    devg.add_option("", "--controller", dest="controller", action="append",
                    help=_("Configure a guest controller device. Ex:\n"
                           "--controller type=usb,model=ich9-ehci1"))
    devg.add_option("", "--serial", dest="serials", action="append",
                    help=_("Configure a guest serial device"))
    devg.add_option("", "--parallel", dest="parallels", action="append",
                    help=_("Configure a guest parallel device"))
    devg.add_option("", "--channel", dest="channels", action="append",
                    help=_("Configure a guest communication channel"))
    devg.add_option("", "--console", dest="consoles", action="append",
                    help=_("Configure a text console connection between "
                           "the guest and host"))
    devg.add_option("", "--host-device", dest="hostdevs", action="append",
                    help=_("Configure physical host devices attached to the "
                           "guest"))
    devg.add_option("", "--soundhw", dest="soundhw", action="append",
                    help=_("Configure guest sound device emulation"))
    devg.add_option("", "--watchdog", dest="watchdog", action="append",
                    help=_("Configure a guest watchdog device"))
    devg.add_option("", "--video", dest="video", action="append",
                    help=_("Configure guest video hardware."))
    devg.add_option("", "--smartcard", dest="smartcard", action="append",
                    help=_("Configure a guest smartcard device. Ex:\n"
                           "--smartcard mode=passthrough"))
    devg.add_option("", "--redirdev", dest="redirdev", action="append",
                    help=_("Configure a guest redirection device. Ex:\n"
                           "--redirdev usb,type=tcp,server=192.168.1.1:4000"))
    devg.add_option("", "--memballoon", dest="memballoon", action="append",
                    help=_("Configure a guest memballoon device. Ex:\n"
                           "--memballoon model=virtio"))
    devg.add_option("", "--tpm", dest="tpm", action="append",
                    help=_("Configure a guest TPM device. Ex:\n"
                           "--tpm type=passthrough"))


def add_gfx_option(devg):
    devg.add_option("", "--graphics", dest="graphics", action="append",
      help=_("Configure guest display settings. Ex:\n"
             "--graphics vnc\n"
             "--graphics spice,port=5901,tlsport=5902\n"
             "--graphics none\n"
             "--graphics vnc,password=foobar,port=5910,keymap=ja"))


def add_fs_option(devg):
    devg.add_option("", "--filesystem", dest="filesystems", action="append",
        help=_("Pass host directory to the guest. Ex: \n"
               "--filesystem /my/source/dir,/dir/in/guest\n"
               "--filesystem template_name,/,type=template"))

#############################################
# CLI complex parsing helpers               #
# (for options like --disk, --network, etc. #
#############################################


def get_opt_param(opts, dictnames, val=None):
    if type(dictnames) is not list:
        dictnames = [dictnames]

    for key in dictnames:
        if key in opts:
            if val is None:
                val = opts[key]
            del(opts[key])

    return val


def _build_set_param(inst, opts):
    def _set_param(paramname, keyname, val=None):
        val = get_opt_param(opts, keyname, val)
        if val is None:
            return
        setattr(inst, paramname, val)

    return _set_param


def parse_optstr_tuples(optstr, compress_first=False):
    """
    Parse optstr into a list of ordered tuples
    """
    optstr = str(optstr or "")
    optlist = []

    if compress_first and optstr and not optstr.count("="):
        return [(optstr, None)]

    argsplitter = shlex.shlex(optstr, posix=True)
    argsplitter.commenters = ""
    argsplitter.whitespace = ","
    argsplitter.whitespace_split = True

    for opt in list(argsplitter):
        if not opt:
            continue

        opt_type = None
        opt_val = None
        if opt.count("="):
            opt_type, opt_val = opt.split("=", 1)
            optlist.append((opt_type, opt_val))
        else:
            optlist.append((opt, None))

    return optlist


def parse_optstr(optstr, basedict=None, remove_first=None,
                 compress_first=False):
    """
    Helper function for parsing opt strings of the form
    opt1=val1,opt2=val2,...

    @param basedict: starting dictionary, so the caller can easily set
                     default values, etc.
    @param remove_first: List or parameters to peel off the front of
                         option string, and store in the returned dict.
                         remove_first=["char_type"] for --serial pty,foo=bar
                         returns {"char_type", "pty", "foo" : "bar"}
    @param compress_first: If there are no options of the form opt1=opt2,
                           compress the string to a single option
    @returns: a dictionary of {'opt1': 'val1', 'opt2': 'val2'}
    """
    optlist = parse_optstr_tuples(optstr, compress_first=compress_first)
    optdict = basedict or {}

    paramlist = remove_first
    if type(paramlist) is not list:
        paramlist = paramlist and [paramlist] or []

    for idx in range(len(paramlist)):
        if len(optlist) < len(paramlist):
            break

        if optlist[idx][1] is None:
            optlist[idx] = (paramlist[idx], optlist[idx][0])

    for opt, val in optlist:
        if type(optdict.get(opt)) is list:
            optdict[opt].append(val)
        else:
            optdict[opt] = val

    return optdict



#######################
# Guest param parsing #
#######################

######################
# --numatune parsing #
######################

def parse_numatune(guest, optstring):
    """
    Helper to parse --numatune string

    @param  guest: virtinst.Guest instanct (object)
    @param  optstring: value of the option '--numatune' (str)
    """
    opts = parse_optstr(optstring, remove_first="nodeset", compress_first=True)

    set_param = _build_set_param(guest.numatune, opts)

    set_param("memory_nodeset", "nodeset")
    set_param("memory_mode", "mode")

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

##################
# --vcpu parsing #
##################


def parse_vcpu(guest, optstring, default_vcpus=None):
    """
    Helper to parse --vcpu string

    @param  guest: virtinst.Guest instance (object)
    @param  optstring: value of the option '--vcpus' (str)
    @param  default_vcpus: ? (it should be None at present.)
    """
    if not optstring:
        return

    opts = parse_optstr(optstring, remove_first="vcpus")
    vcpus = opts.get("vcpus") or default_vcpus
    if vcpus is not None:
        opts["vcpus"] = vcpus

    set_param = _build_set_param(guest, opts)
    set_cpu_param = _build_set_param(guest.cpu, opts)
    has_max = ("maxvcpus" in opts)
    has_vcpus = ("vcpus" in opts) or has_max

    set_param(has_max and "curvcpus" or "vcpus", "vcpus")
    set_param("vcpus", "maxvcpus")

    set_cpu_param("sockets", "sockets")
    set_cpu_param("cores", "cores")
    set_cpu_param("threads", "threads")

    if not has_vcpus:
        guest.vcpus = guest.cpu.vcpus_from_topology()

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

#################
# --cpu parsing #
#################


def parse_cpu(guest, optstring):
    default_dict = {
        "force": [],
        "require": [],
        "optional": [],
        "disable": [],
        "forbid": [],
   }
    opts = parse_optstr(optstring,
                        basedict=default_dict,
                        remove_first="model")

    # Convert +feature, -feature into expected format
    for key, value in opts.items():
        policy = None
        if value or len(key) == 1:
            continue

        if key.startswith("+"):
            policy = "force"
        elif key.startswith("-"):
            policy = "disable"

        if policy:
            del(opts[key])
            opts[policy].append(key[1:])

    set_param = _build_set_param(guest.cpu, opts)
    def set_features(policy):
        for name in opts.get(policy):
            guest.cpu.add_feature(name, policy)
        del(opts[policy])

    if opts.get("model") == "host":
        guest.cpu.copy_host_cpu()
        del(opts["model"])

    set_param("model", "model")
    set_param("match", "match")
    set_param("vendor", "vendor")

    set_features("force")
    set_features("require")
    set_features("optional")
    set_features("disable")
    set_features("forbid")

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

##################
# --boot parsing #
##################


def parse_boot(guest, optstring):
    """
    Helper to parse --boot string
    """
    opts = parse_optstr(optstring)
    optlist = [x[0] for x in parse_optstr_tuples(optstring)]
    menu = None

    def set_param(paramname, dictname, val=None):
        val = get_opt_param(opts, dictname, val)
        if val is None:
            return

        setattr(guest.os, paramname, val)

    # Convert menu= value
    if "menu" in opts:
        menustr = opts["menu"]
        menu = None

        if menustr.lower() == "on":
            menu = True
        elif menustr.lower() == "off":
            menu = False
        else:
            menu = yes_or_no_convert(menustr)

        if menu is None:
            fail(_("--boot menu must be 'on' or 'off'"))

    set_param("enable_bootmenu", "menu", menu)
    set_param("kernel", "kernel")
    set_param("initrd", "initrd")
    set_param("loader", "loader")
    set_param("kernel_args", ["kernel_args", "extra_args"])

    # Build boot order
    if opts:
        boot_order = []
        for boot_dev in optlist:
            if not boot_dev in guest.os.boot_devices:
                continue

            del(opts[boot_dev])
            if boot_dev not in boot_order:
                boot_order.append(boot_dev)

        guest.os.bootorder = boot_order

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

######################
# --security parsing #
######################


def parse_security(guest, security):
    seclist = listify(security)
    secopts = seclist and seclist[0] or None
    if not secopts:
        return

    # Parse security opts
    opts = parse_optstr(secopts)
    arglist = secopts.split(",")
    secmodel = guest.seclabel

    # Beware, adding boolean options here could upset label comma handling
    mode = get_opt_param(opts, "type")
    label = get_opt_param(opts, "label")
    relabel = yes_or_no_convert(get_opt_param(opts, "relabel"))

    # Try to fix up label if it contained commas
    if label:
        tmparglist = arglist[:]
        for idx in range(len(tmparglist)):
            arg = tmparglist[idx]
            if not arg.split("=")[0] == "label":
                continue

            for arg in tmparglist[idx + 1:]:
                if arg.count("="):
                    break

                if arg:
                    label += "," + arg
                    del(opts[arg])

            break

    if label:
        secmodel.label = label
        if not mode:
            mode = secmodel.TYPE_STATIC
    if mode:
        secmodel.type = mode

    if relabel:
        secmodel.relabel = relabel

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

    # Run for validation purposes
    secmodel.get_xml_config()



##########################
# Guest <device> parsing #
##########################


##################
# --disk parsing #
##################

_disk_counter = itertools.count()


def _parse_disk_source(guest, path, pool, vol, size, fmt, sparse):
    abspath = None
    volinst = None
    volobj = None

    # Strip media type
    if sum([bool(p) for p in [path, pool, vol]]) > 1:
        fail(_("Cannot specify more than 1 storage path"))

    if path:
        abspath = os.path.abspath(path)
        if os.path.dirname(abspath) == DEFAULT_POOL_PATH:
            build_default_pool(guest)

    elif pool:
        if not size:
            raise ValueError(_("Size must be specified with all 'pool='"))
        if pool == DEFAULT_POOL_NAME:
            build_default_pool(guest)
        vc = virtinst.Storage.StorageVolume.get_volume_for_pool(pool_name=pool,
                                                                conn=guest.conn)
        vname = virtinst.Storage.StorageVolume.find_free_name(conn=guest.conn,
                                            pool_name=pool,
                                            name=guest.name,
                                            suffix=".img",
                                            start_num=_disk_counter.next())
        volinst = vc(pool_name=pool, name=vname, conn=guest.conn,
                     allocation=0, capacity=(size and
                                             size * 1024 * 1024 * 1024))
        if fmt:
            if not hasattr(volinst, "format"):
                raise ValueError(_("Format attribute not supported for this "
                                   "volume type"))
            setattr(volinst, "format", fmt)

        if not sparse:
            volinst.allocation = volinst.capacity

    elif vol:
        if not vol.count("/"):
            raise ValueError(_("Storage volume must be specified as "
                               "vol=poolname/volname"))
        vollist = vol.split("/")
        voltuple = (vollist[0], vollist[1])
        logging.debug("Parsed volume: as pool='%s' vol='%s'",
                      voltuple[0], voltuple[1])
        if voltuple[0] == DEFAULT_POOL_NAME:
            build_default_pool(guest)

        volobj = virtinst.VirtualDisk.lookup_vol_object(guest.conn, voltuple)

    return abspath, volinst, volobj


def parse_disk(guest, optstr, dev=None):
    """
    helper to properly parse --disk options
    """
    def parse_perms(val):
        ro = False
        shared = False
        if val is not None:
            if val == "ro":
                ro = True
            elif val == "sh":
                shared = True
            elif val == "rw":
                # It's default. Nothing to do.
                pass
            else:
                fail(_("Unknown '%s' value '%s'" % ("perms", val)))

        return ro, shared

    def parse_size(val):
        newsize = None
        if val is not None:
            try:
                newsize = float(val)
            except Exception, e:
                fail(_("Improper value for 'size': %s" % str(e)))

        return newsize

    def parse_sparse(val):
        sparse = True
        if val is not None:
            val = str(val).lower()
            if val in ["true", "yes"]:
                sparse = True
            elif val in ["false", "no"]:
                sparse = False
            else:
                fail(_("Unknown '%s' value '%s'") % ("sparse", val))

        return sparse

    def opt_get(key):
        val = None
        if key in opts:
            val = opts.get(key)
            del(opts[key])

        return val

    if not dev:
        dev = virtinst.VirtualDisk(guest.conn)

    # Parse out comma separated options
    opts = parse_optstr(optstr, remove_first="path")

    path = opt_get("path")
    pool = opt_get("pool")
    vol = opt_get("vol")
    size = parse_size(opt_get("size"))
    fmt = opt_get("format")
    sparse = parse_sparse(opt_get("sparse"))
    ro, shared = parse_perms(opt_get("perms"))

    abspath, volinst, volobj = _parse_disk_source(guest, path, pool, vol,
                                                  size, fmt, sparse)

    dev.path = volobj and volobj.path() or abspath
    dev.read_only = ro
    dev.shareable = shared
    dev.set_create_storage(size=size, fmt=fmt, sparse=sparse,
                           vol_install=volinst)

    set_param = _build_set_param(dev, opts)

    set_param("device", "device")
    set_param("bus", "bus")
    set_param("driver_cache", "cache")
    set_param("driver_name", "driver_name")
    set_param("driver_type", "driver_type")
    set_param("driver_io", "io")
    set_param("error_policy", "error_policy")
    set_param("serial", "serial")

    if opts:
        fail(_("Unknown options %s") % opts.keys())

    dev.validate()
    return dev, size


#####################
# --network parsing #
#####################

def parse_network(guest, optstring, dev=None, mac=None):
    # Handle old format of bridge:foo instead of bridge=foo
    for prefix in ["network", "bridge"]:
        if optstring.startswith(prefix + ":"):
            optstring = optstring.replace(prefix + ":", prefix + "=")

    opts = parse_optstr(optstring, remove_first="type")

    # Determine device type
    net_type = opts.get("type")
    if "network" in opts:
        net_type = VirtualNetworkInterface.TYPE_VIRTUAL
    elif "bridge" in opts:
        net_type = VirtualNetworkInterface.TYPE_BRIDGE

    if not dev:
        dev = VirtualNetworkInterface(conn=guest.conn)

    if mac and not "mac" in opts:
        opts["mac"] = mac
    if "mac" in opts:
        if opts["mac"] == "RANDOM":
            opts["mac"] = None

    set_param = _build_set_param(dev, opts)

    set_param("type", "type", net_type)
    set_param("network", "network")
    set_param("bridge", "bridge")
    set_param("model", "model")
    set_param("macaddr", "mac")

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

    return dev


######################
# --graphics parsing #
######################

def parse_graphics(guest, optstring, dev=None):
    if optstring is None:
        return None

    def sanitize_keymap(keymap):
        from virtinst import hostkeymap

        if not keymap:
            return None
        if keymap.lower() == "local":
            return VirtualGraphics.KEYMAP_LOCAL
        if keymap.lower() == "none":
            return None

        use_keymap = hostkeymap.sanitize_keymap(keymap)
        if not use_keymap:
            raise ValueError(
                        _("Didn't match keymap '%s' in keytable!") % keymap)
        return use_keymap

    # Peel the model type off the front
    opts = parse_optstr(optstring, remove_first="type")
    if opts.get("type") == "none":
        return None

    if not dev:
        dev = VirtualGraphics(conn=guest.conn)

    def set_param(paramname, dictname, val=None):
        val = get_opt_param(opts, dictname, val)
        if val is None:
            return

        if paramname == "keymap":
            val = sanitize_keymap(val)
        setattr(dev, paramname, val)

    set_param("type", "type")
    set_param("port", "port")
    set_param("tlsPort", "tlsport")
    set_param("listen", "listen")
    set_param("keymap", "keymap")
    set_param("passwd", "password")
    set_param("passwdValidTo", "passwordvalidto")

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

    return dev


########################
# --controller parsing #
########################

def parse_controller(guest, optstring, dev=None):
    if optstring is None:
        return None

    if optstring == "usb2":
        for dev in virtinst.VirtualController.get_usb2_controllers(guest.conn):
            guest.add_device(dev)
        return None

    # Peel the mode off the front
    opts = parse_optstr(optstring, remove_first="type")
    address = get_opt_param(opts, "address")

    if not dev:
        dev = virtinst.VirtualController(guest.conn)

    set_param = _build_set_param(dev, opts)

    set_param("type", "type")
    set_param("model", "model")
    set_param("index", "index")
    set_param("master_startport", "master")
    if address:
        dev.address.set_addrstr(address)

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

    return dev


#######################
# --smartcard parsing #
#######################

def parse_smartcard(guest, optstring, dev=None):
    if optstring is None:
        return None

    # Peel the mode off the front
    opts = parse_optstr(optstring, remove_first="mode")
    if opts.get("mode") == "none":
        return None

    if not dev:
        dev = virtinst.VirtualSmartCardDevice(guest.conn)

    set_param = _build_set_param(dev, opts)

    set_param("mode", "mode")
    set_param("type", "type")

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

    return dev


######################
# --redirdev parsing #
######################

def parse_redirdev(guest, optstring, dev=None):
    if optstring is None:
        return None

    # Peel the mode off the front
    opts = parse_optstr(optstring, remove_first="bus")
    server = get_opt_param(opts, "server")

    if opts.get("bus") == "none":
        return None

    if not dev:
        dev = virtinst.VirtualRedirDevice(guest.conn)

    set_param = _build_set_param(dev, opts)

    set_param("bus", "bus")
    set_param("type", "type")
    if server:
        dev.parse_friendly_server(server)

    if dev.type == "spicevmc" and server:
        raise ValueError(
                _("The server option is invalid with spicevmc redirection"))

    if dev.type == "tcp" and not server:
        raise ValueError(
                _("The server option is missing for TCP redirection"))

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

    return dev


#################
# --tpm parsing #
#################

def parse_tpm(guest, optstring, dev=None):
    if optstring is None:
        return None

    # Peel the type off the front
    opts = parse_optstr(optstring, remove_first="type")
    if opts.get("type") == "none":
        return None

    if not dev:
        dev = virtinst.VirtualTPMDevice(guest.conn)

    set_param = _build_set_param(dev, opts)

    set_param("type", "type")
    set_param("model", "model")
    set_param("path", "path")

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

    return dev


######################
# --watchdog parsing #
######################

def parse_watchdog(guest, optstring, dev=None):
    # Peel the model type off the front
    opts = parse_optstr(optstring, remove_first="model")

    if not dev:
        dev = virtinst.VirtualWatchdog(guest.conn)

    def set_param(paramname, dictname, val=None):
        val = get_opt_param(opts, dictname, val)
        if val is None:
            return

        setattr(dev, paramname, val)

    set_param("model", "model")
    set_param("action", "action")

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

    return dev


########################
# --memballoon parsing #
########################

def parse_memballoon(guest, optstring, dev=None):
    if optstring is None:
        return None

    # Peel the mode off the front
    opts = parse_optstr(optstring, remove_first="model")

    if not dev:
        dev = virtinst.VirtualMemballoon(conn=guest.conn)
    dev.model = get_opt_param(opts, "model")

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

    return dev


######################################################
# --serial, --parallel, --channel, --console parsing #
######################################################

def parse_serial(guest, optstring, dev=None):
    if not dev:
        dev = virtinst.VirtualSerialDevice(guest.conn)
    return _parse_char(optstring, "serial", dev)


def parse_parallel(guest, optstring, dev=None):
    if not dev:
        dev = virtinst.VirtualParallelDevice(guest.conn)
    return _parse_char(optstring, "parallel", dev)


def parse_console(guest, optstring, dev=None):
    if not dev:
        dev = virtinst.VirtualConsoleDevice(guest.conn)
    return _parse_char(optstring, "console", dev)


def parse_channel(guest, optstring, dev=None):
    if not dev:
        dev = virtinst.VirtualChannelDevice(guest.conn)
    return _parse_char(optstring, "channel", dev)


def _parse_char(optstring, dev_type, dev=None):
    """
    Helper to parse --serial/--parallel options
    """
    # Peel the char type off the front
    opts = parse_optstr(optstring, remove_first="char_type")
    ctype = opts.get("char_type")

    def set_param(paramname, dictname, val=None):
        val = get_opt_param(opts, dictname, val)
        if val is None:
            return

        if not dev.supports_property(paramname):
            raise ValueError(_("%(devtype)s type '%(chartype)s' does not "
                                "support '%(optname)s' option.") %
                                {"devtype" : dev_type, "chartype": ctype,
                                 "optname" : dictname})
        setattr(dev, paramname, val)

    def parse_host(key):
        host, ignore, port = partition(opts.get(key), ":")
        if key in opts:
            del(opts[key])

        return host or None, port or None

    host, port = parse_host("host")
    bind_host, bind_port = parse_host("bind_host")
    target_addr, target_port = parse_host("target_address")

    set_param("type", "char_type")
    set_param("source_path", "path")
    set_param("source_mode", "mode")
    set_param("protocol",   "protocol")
    set_param("source_host", "host", host)
    set_param("source_port", "host", port)
    set_param("bind_host", "bind_host", bind_host)
    set_param("bind_port", "bind_host", bind_port)
    set_param("target_type", "target_type")
    set_param("target_name", "name")
    set_param("target_address", "target_address", target_addr)
    set_param("target_port", "target_address", target_port)

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

    # Try to generate dev XML to perform upfront validation
    dev.get_xml_config()

    return dev


########################
# --filesystem parsing #
########################

def parse_filesystem(guest, optstring, dev=None):
    opts = parse_optstr(optstring, remove_first=["source", "target"])

    if not dev:
        dev = virtinst.VirtualFilesystem(guest.conn)

    def set_param(paramname, dictname, val=None):
        val = get_opt_param(opts, dictname, val)
        if val is None:
            return

        setattr(dev, paramname, val)

    set_param("type", "type")
    set_param("mode", "mode")
    set_param("source", "source")
    set_param("target", "target")

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())

    return dev


###################
# --video parsing #
###################

def parse_video(guest, optstr, dev=None):
    opts = {"model" : optstr}

    if not dev:
        dev = virtinst.VirtualVideoDevice(conn=guest.conn)

    set_param = _build_set_param(dev, opts)

    set_param("model", "model")

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())
    return dev


#####################
# --soundhw parsing #
#####################

def parse_sound(guest, optstr, dev=None):
    opts = {"model" : optstr}

    if not dev:
        dev = virtinst.VirtualAudio(guest.conn)

    set_param = _build_set_param(dev, opts)
    set_param("model", "model")

    if opts:
        raise ValueError(_("Unknown options %s") % opts.keys())
    return dev


#####################
# --hostdev parsing #
#####################

def parse_hostdev(guest, optstr, dev=None):
    return virtinst.VirtualHostDevice.device_from_node(guest.conn,
                                                       name=optstr,
                                                       dev=dev)

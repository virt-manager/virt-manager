#
# Utility functions for the command line drivers
#
# Copyright 2006-2007, 2013 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
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

    vi_dir = None
    if not "VIRTINST_TEST_SUITE" in os.environ:
        vi_dir = util.get_cache_dir()

    if vi_dir and not os.access(vi_dir, os.W_OK):
        if os.path.exists(vi_dir):
            raise RuntimeError("No write access to directory %s" % vi_dir)

        try:
            os.makedirs(vi_dir, 0751)
        except IOError, e:
            raise RuntimeError("Could not create directory %s: %s" %
                               (vi_dir, e))


    dateFormat = "%a, %d %b %Y %H:%M:%S"
    fileFormat = ("[%(asctime)s " + appname + " %(process)d] "
                  "%(levelname)s (%(module)s:%(lineno)d) %(message)s")
    streamErrorFormat = "%(levelname)-8s %(message)s"

    rootLogger = logging.getLogger()

    # Undo early logging
    for handler in rootLogger.handlers:
        rootLogger.removeHandler(handler)

    rootLogger.setLevel(logging.DEBUG)
    if vi_dir:
        filename = os.path.join(vi_dir, appname + ".log")
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


#######################
# CLI Prompting utils #
#######################

def set_force(val=True):
    global force
    force = val


def set_prompt(prompt):
    # Set whether we allow prompts, or fail if a prompt pops up
    global doprompt
    doprompt = prompt
    if prompt:
        logging.warning("--prompt mode is barely supported and likely to "
                        "be removed in a future release.\n")


def is_prompt():
    return doprompt


def _yes_no_convert(s):
    tvalues = ["y", "yes", "1", "true", "t", "on"]
    fvalues = ["n", "no", "0", "false", "f", "off"]

    s = (s or "").lower()
    if s in tvalues:
        return True
    elif s in fvalues:
        return False
    return None


def _on_off_convert(key, val):
    val = _yes_no_convert(val)
    if val is not None:
        return val
    raise fail(_("%(key)s must be 'yes' or 'no'") % {"key": key})


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


def prompt_for_yes_no(warning, question):
    """catches yes_no errors and ensures a valid bool return"""
    if force:
        logging.debug("Forcing return value of True to prompt '%s'")
        return True

    errmsg = warning + _(" (Use --force to override)")

    while 1:
        msg = warning
        if question:
            msg += ("\n" + question)

        inp = prompt_for_input(errmsg, msg, None)
        try:
            res = _yes_no_convert(inp)
            if res is None:
                raise ValueError(_("A yes or no response is required"))
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
            return not prompt_for_yes_no(msg, askmsg)
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
        return not prompt_for_yes_no(msg, askmsg)

    def prompt_size_conflict(dev):
        """
        Check if specified size exceeds available storage
        """
        isfatal, errmsg = dev.is_size_conflict()
        if isfatal:
            fail(errmsg, do_exit=not is_prompt())
            return True

        if errmsg:
            return not prompt_for_yes_no(errmsg, askmsg)

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
        path_exists = virtinst.VirtualDisk.path_exists(conn, path)

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
                dev = virtinst.VirtualDisk(conn)
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


def get_name(guest, name):
    prompt_txt = _("What is the name of your virtual machine?")
    err_txt = name_missing
    prompt_loop(prompt_txt, err_txt, name, guest, "name")


def get_memory(guest, memory):
    prompt_txt = _("How much RAM should be allocated (in megabytes)?")
    err_txt = ram_missing

    def check_memory(mem):
        mem = int(mem)
        if mem < MIN_RAM:
            raise ValueError(_("Installs currently require %d megs "
                               "of RAM.") % MIN_RAM)
        guest.memory = mem * 1024

    prompt_loop(prompt_txt, err_txt, memory, guest, "memory",
                func=check_memory)


def get_uuid(guest, uuid):
    if not uuid:
        return
    try:
        guest.uuid = uuid
    except ValueError, e:
        fail(e)


def get_vcpus(guest, vcpus, check_cpu):
    if vcpus is None:
        vcpus = ""

    parse_vcpu(guest, vcpus)
    if not check_cpu:
        return

    hostinfo = guest.conn.getInfo()
    pcpus = hostinfo[4] * hostinfo[5] * hostinfo[6] * hostinfo[7]

    if guest.vcpus > pcpus:
        msg = _("You have asked for more virtual CPUs (%d) than there "
                "are physical CPUs (%d) on the host. This will work, "
                "but performance will be poor. ") % (guest.vcpus, pcpus)
        askmsg = _("Are you sure? (yes or no)")

        if not prompt_for_yes_no(msg, askmsg):
            nice_exit()


def get_cpuset(guest, cpuset):
    memory = guest.memory
    conn = guest.conn
    if cpuset and cpuset != "auto":
        guest.cpuset = cpuset

    elif cpuset == "auto":
        tmpset = None
        try:
            tmpset = virtinst.DomainNumatune.generate_cpuset(conn, memory)
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


def convert_old_networks(guest, options, number_of_default_nics):
    macs     = util.listify(options.mac)
    networks = util.listify(options.network)
    bridges  = util.listify(options.bridge)

    if bridges and networks:
        fail(_("Cannot mix both --bridge and --network arguments"))

    if bridges:
        # Convert old --bridges to --networks
        networks = ["bridge:" + b for b in bridges]

    def padlist(l, padsize):
        l = util.listify(l)
        l.extend((padsize - len(l)) * [None])
        return l

    # If a plain mac is specified, have it imply a default network
    networks = padlist(networks, max(len(macs), number_of_default_nics))
    macs = padlist(macs, len(networks))

    for idx in range(len(networks)):
        if networks[idx] is None:
            networks[idx] = _default_network_opts(guest)
        if macs[idx]:
            networks[idx] += ",mac=%s" % macs[idx]

        # Handle old format of bridge:foo instead of bridge=foo
        for prefix in ["network", "bridge"]:
            if networks[idx].startswith(prefix + ":"):
                networks[idx] = networks[idx].replace(prefix + ":",
                                                      prefix + "=")

    options.network = networks


def _determine_default_graphics(guest, default_override):
    if default_override is True:
        return "default"
    elif default_override is False:
        return "none"

    if guest.os.is_container():
        logging.debug("Container guest, defaulting to nographics")
        return "none"

    if "DISPLAY" not in os.environ.keys():
        logging.debug("DISPLAY is not set: defaulting to nographics.")
        return "none"

    logging.debug("DISPLAY is set: using default graphics")
    return "default"


def convert_old_graphics(guest, options, default_override=None):
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

    if options.graphics:
        return

    if optnum == 0:
        options.graphics = [_determine_default_graphics(guest,
                                                        default_override)]
        return

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
    options.graphics = [optstr]


def convert_old_features(options):
    if getattr(options, "features", None):
        return

    opts = ""
    if options.noacpi:
        opts += "acpi=off"
    if options.noapic:
        if opts:
            opts += ","
        opts += "apic=off"
    options.features = opts or None


def set_os_variant(obj, distro_type, distro_variant):
    # This is used for both Guest and virtconv VM, so be careful
    if (not distro_type and
        not distro_variant and
        hasattr(obj, "os_autodetect")):
        # Default to distro autodetection
        obj.os_autodetect = True
        return

    distro_variant = distro_variant and str(distro_variant).lower() or None
    distro_type = distro_type and str(distro_type).lower() or None
    distkey = distro_variant or distro_type
    if not distkey or distkey == "none":
        return

    obj.os_variant = distkey


#############################
# Common CLI option/group   #
#############################

def add_connect_option(parser):
    parser.add_option("--connect", metavar="URI", dest="connect",
                      help=_("Connect to hypervisor with libvirt URI"))


def add_misc_options(grp, prompt=False, replace=False,
                     printxml=False, printstep=False,
                     noreboot=False, dryrun=False):
    if prompt:
        grp.add_option("--prompt", action="store_true", dest="prompt",
                        default=False, help=optparse.SUPPRESS_HELP)
        grp.add_option("--force", action="store_true", dest="force",
                        default=False, help=optparse.SUPPRESS_HELP)

    if noreboot:
        grp.add_option("--noreboot", action="store_true", dest="noreboot",
                       help=_("Don't boot guest after completing install."))

    if replace:
        grp.add_option("--replace", action="store_true", dest="replace",
            help=_("Don't check name collision, overwrite any guest "
                   "with the same name."))

    if printxml:
        grp.add_option("--print-xml", action="store_true", dest="xmlonly",
            help=_("Print the generated domain XML rather than define "
                   "and clone the guest."))
        if printstep:
            grp.add_option("--print-step", type="str", dest="xmlstep",
                help=_("Print XML of a specific install step "
                       "(1, 2, 3, all) rather than define the guest."))

    if dryrun:
        grp.add_option("--dry-run", action="store_true", dest="dry",
                       help=_("Run through install process, but do not "
                              "create devices or define the guest."))

    grp.add_option("-q", "--quiet", action="store_true", dest="quiet",
                   help=_("Suppress non-error output"))
    grp.add_option("-d", "--debug", action="store_true", dest="debug",
                   help=_("Print debugging information"))


def vcpu_cli_options(grp, backcompat=True):
    grp.add_option("--vcpus", dest="vcpus",
        help=_("Number of vcpus to configure for your guest. Ex:\n"
               "--vcpus 5\n"
               "--vcpus 5,maxcpus=10\n"
               "--vcpus sockets=2,cores=4,threads=2"))
    grp.add_option("--cpuset", dest="cpuset",
                   help=_("Set which physical CPUs domain can use."))
    grp.add_option("--cpu", dest="cpu",
        help=_("CPU model and features. Ex: --cpu coreduo,+x2apic"))

    if backcompat:
        grp.add_option("--check-cpu", action="store_true",
                       dest="check_cpu", help=optparse.SUPPRESS_HELP)


def graphics_option_group(parser):
    """
    Register vnc + sdl options for virt-install and virt-image
    """

    vncg = optparse.OptionGroup(parser, _("Graphics Configuration"))
    add_gfx_option(vncg)
    vncg.add_option("--vnc", action="store_true", dest="vnc",
                    help=optparse.SUPPRESS_HELP)
    vncg.add_option("--vncport", type="int", dest="vncport",
                    help=optparse.SUPPRESS_HELP)
    vncg.add_option("--vnclisten", dest="vnclisten",
                    help=optparse.SUPPRESS_HELP)
    vncg.add_option("-k", "--keymap", dest="keymap",
                    help=optparse.SUPPRESS_HELP)
    vncg.add_option("--sdl", action="store_true", dest="sdl",
                    help=optparse.SUPPRESS_HELP)
    vncg.add_option("--nographics", action="store_true",
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
             "--network network=mynet,model=virtio,mac=00:11...\n"
             "--network network=mynet,filterref=clean-traffic,model=virtio"))


def add_device_options(devg):
    devg.add_option("--controller", dest="controller", action="append",
                    help=_("Configure a guest controller device. Ex:\n"
                           "--controller type=usb,model=ich9-ehci1"))
    devg.add_option("--serial", dest="serials", action="append",
                    help=_("Configure a guest serial device"))
    devg.add_option("--parallel", dest="parallels", action="append",
                    help=_("Configure a guest parallel device"))
    devg.add_option("--channel", dest="channels", action="append",
                    help=_("Configure a guest communication channel"))
    devg.add_option("--console", dest="consoles", action="append",
                    help=_("Configure a text console connection between "
                           "the guest and host"))
    devg.add_option("--host-device", dest="hostdevs", action="append",
                    help=_("Configure physical host devices attached to the "
                           "guest"))
    devg.add_option("--soundhw", dest="sound", action="append",
                    help=_("Configure guest sound device emulation"))
    devg.add_option("--watchdog", dest="watchdog", action="append",
                    help=_("Configure a guest watchdog device"))
    devg.add_option("--video", dest="video", action="append",
                    help=_("Configure guest video hardware."))
    devg.add_option("--smartcard", dest="smartcard", action="append",
                    help=_("Configure a guest smartcard device. Ex:\n"
                           "--smartcard mode=passthrough"))
    devg.add_option("--redirdev", dest="redirdev", action="append",
                    help=_("Configure a guest redirection device. Ex:\n"
                           "--redirdev usb,type=tcp,server=192.168.1.1:4000"))
    devg.add_option("--memballoon", dest="memballoon", action="append",
                    help=_("Configure a guest memballoon device. Ex:\n"
                           "--memballoon model=virtio"))
    devg.add_option("--tpm", dest="tpm", action="append",
                    help=_("Configure a guest TPM device. Ex:\n"
                           "--tpm /dev/tpm"))
    devg.add_option("--rng", dest="rng", action="append",
                    help=_("Configure a guest RNG device. Ex:\n"
                           "--rng /dev/random\n"
     "--rng egd,backend_host=localhost,backend_service=708,backend_type=tcp"))


def add_gfx_option(devg):
    devg.add_option("--graphics", dest="graphics", action="append",
      help=_("Configure guest display settings. Ex:\n"
             "--graphics vnc\n"
             "--graphics spice,port=5901,tlsport=5902\n"
             "--graphics none\n"
             "--graphics vnc,password=foobar,port=5910,keymap=ja"))


def add_fs_option(devg):
    devg.add_option("--filesystem", dest="filesystems", action="append",
        help=_("Pass host directory to the guest. Ex: \n"
               "--filesystem /my/source/dir,/dir/in/guest\n"
               "--filesystem template_name,/,type=template"))


def add_distro_options(g):
    # Way back when, we required specifying both --os-type and --os-variant
    # Nowadays the distinction is pointless, so hide the less useful
    # --os-type option.
    g.add_option("--os-type", dest="distro_type",
                help=optparse.SUPPRESS_HELP)
    g.add_option("--os-variant", dest="distro_variant",
                 help=_("The OS variant being installed guests, "
                        "e.g. 'fedora18', 'rhel6', 'winxp', etc."))


def add_old_feature_options(optg):
    optg.add_option("--noapic", action="store_true", dest="noapic",
                    default=False, help=optparse.SUPPRESS_HELP)
    optg.add_option("--noacpi", action="store_true", dest="noacpi",
                    default=False, help=optparse.SUPPRESS_HELP)


#############################################
# CLI complex parsing helpers               #
# (for options like --disk, --network, etc. #
#############################################

def _handle_dev_opts(devclass, cb, guest, opts):
    for optstr in util.listify(opts):
        devtype = devclass.virtual_device_type
        try:
            dev = devclass(guest.conn)
            devs = cb(guest, optstr, dev)
            for dev in util.listify(devs):
                dev.validate()
                guest.add_device(dev)
        except Exception, e:
            logging.debug("Exception parsing devtype=%s optstr=%s",
                          devtype, optstr, exc_info=True)
            fail(_("Error in %(devtype)s device parameters: %(err)s") %
                 {"devtype": devtype, "err": str(e)})


def _make_handler(devtype, parsefunc):
    return lambda *args, **kwargs: _handle_dev_opts(devtype, parsefunc,
                                                    *args, **kwargs)


def get_opt_param(opts, key):
    if key not in opts:
        return None

    val = opts[key]
    del(opts[key])
    return val


_CLI_UNSET = "__virtinst_cli_unset__"


def _build_set_param(inst, opts, support_cb=None):
    def _set_param(paramname, keyname, convert_cb=None, ignore_default=False):
        val = get_opt_param(opts, keyname)
        if val is None:
            return

        if support_cb:
            support_cb(inst, paramname, keyname)

        if convert_cb:
            val = convert_cb(keyname, val)
        if val == _CLI_UNSET:
            return
        if val == "default" and ignore_default:
            return

        if type(paramname) is not str:
            paramname(val)
        else:
            if not hasattr(inst, paramname):
                raise RuntimeError("programming error: obj=%s does not have "
                                   "member=%s" % (inst, paramname))
            setattr(inst, paramname, val)
    return _set_param


def _check_leftover_opts(opts):
    if not opts:
        return
    raise fail(_("Unknown options %s") % opts.keys())


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



######################
# --numatune parsing #
######################

def parse_numatune(guest, optstr):
    opts = parse_optstr(optstr, remove_first="nodeset", compress_first=True)

    set_param = _build_set_param(guest.numatune, opts)

    set_param("memory_nodeset", "nodeset")
    set_param("memory_mode", "mode")

    _check_leftover_opts(opts)


##################
# --vcpu parsing #
##################

def parse_vcpu(guest, optstr):
    if not optstr:
        return

    opts = parse_optstr(optstr, remove_first="vcpus")
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

    _check_leftover_opts(opts)


#################
# --cpu parsing #
#################

def parse_cpu(guest, optstr):
    default_dict = {
        "force": [],
        "require": [],
        "optional": [],
        "disable": [],
        "forbid": [],
    }
    opts = parse_optstr(optstr,
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

    _check_leftover_opts(opts)


##################
# --boot parsing #
##################

def parse_boot(guest, optstr):
    """
    Helper to parse --boot string
    """
    opts = parse_optstr(optstr)
    set_param = _build_set_param(guest.os, opts)

    set_param("useserial", "useserial", convert_cb=_on_off_convert)
    set_param("enable_bootmenu", "menu", convert_cb=_on_off_convert)
    set_param("kernel", "kernel")
    set_param("initrd", "initrd")
    set_param("dtb", "dtb")
    set_param("loader", "loader")
    set_param("kernel_args", "extra_args")
    set_param("kernel_args", "kernel_args")

    # Build boot order
    if opts:
        optlist = [x[0] for x in parse_optstr_tuples(optstr)]
        boot_order = []
        for boot_dev in optlist:
            if not boot_dev in guest.os.boot_devices:
                continue

            del(opts[boot_dev])
            if boot_dev not in boot_order:
                boot_order.append(boot_dev)

        guest.os.bootorder = boot_order

    _check_leftover_opts(opts)


######################
# --security parsing #
######################

def parse_security(guest, optstr):
    if not optstr:
        return

    opts = parse_optstr(optstr)
    arglist = optstr.split(",")

    # Beware, adding boolean options here could upset label comma handling
    mode = get_opt_param(opts, "type")
    label = get_opt_param(opts, "label")
    relabel = _yes_no_convert(get_opt_param(opts, "relabel"))

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
        guest.seclabel.label = label
        if not mode:
            mode = guest.seclabel.TYPE_STATIC
    if mode:
        guest.seclabel.type = mode
    if relabel:
        guest.seclabel.relabel = relabel

    _check_leftover_opts(opts)

    # Run for validation purposes
    guest.seclabel.get_xml_config()


######################
# --features parsing #
######################

def parse_features(guest, optstr):
    if not optstr:
        return

    opts = parse_optstr(optstr)
    set_param = _build_set_param(guest.features, opts)

    set_param("acpi", "acpi", convert_cb=_on_off_convert)
    set_param("apic", "apic", convert_cb=_on_off_convert)
    set_param("pae", "pae", convert_cb=_on_off_convert)
    set_param("privnet", "privnet", convert_cb=_on_off_convert)
    set_param("hap", "hap", convert_cb=_on_off_convert)
    set_param("viridian", "viridian", convert_cb=_on_off_convert)
    set_param("eoi", "eoi", convert_cb=_on_off_convert)

    set_param("hyperv_vapic", "hyperv_vapic", convert_cb=_on_off_convert)
    set_param("hyperv_relaxed", "hyperv_relaxed", convert_cb=_on_off_convert)
    set_param("hyperv_spinlocks", "hyperv_spinlocks",
              convert_cb=_on_off_convert)
    set_param("hyperv_spinlocks_retries", "hyperv_spinlocks_retries")

    _check_leftover_opts(opts)


###################
# --clock parsing #
###################

def parse_clock(guest, optstr):
    opts = parse_optstr(optstr)

    set_param = _build_set_param(guest.clock, opts)
    set_param("offset", "offset")

    timer_opt_names = ["tickpolicy", "present"]
    timer_opts = {}
    for key in opts.keys():
        for name in timer_opt_names:
            if not key.endswith("_" + name):
                continue
            timer_name = key[:-(len(name) + 1)]
            if timer_name not in timer_opts:
                timer_opts[timer_name] = {}
            timer_opts[timer_name][key] = opts.pop(key)

    _check_leftover_opts(opts)

    for timer_name, subopts in timer_opts.items():
        timer = guest.clock.add_timer()
        timer.name = timer_name

        set_param = _build_set_param(timer, subopts)
        set_param("tickpolicy", "%s_tickpolicy" % timer_name)
        set_param("present", "%s_present" % timer_name,
                  convert_cb=_on_off_convert)
        _check_leftover_opts(subopts)


##########################
# Guest <device> parsing #
##########################

##################
# --disk parsing #
##################

def _parse_disk_source(guest, path, pool, vol, size, fmt, sparse):
    abspath = None
    volinst = None
    volobj = None

    # Strip media type
    if sum([bool(p) for p in [path, pool, vol]]) > 1:
        fail(_("Cannot specify more than 1 storage path"))

    if path:
        abspath = os.path.abspath(path)
        if os.path.dirname(abspath) == "/var/lib/libvirt/images":
            virtinst.StoragePool.build_default_pool(guest.conn)

    elif pool:
        if not size:
            raise ValueError(_("Size must be specified with all 'pool='"))
        if pool == "default":
            virtinst.StoragePool.build_default_pool(guest.conn)

        poolobj = guest.conn.storagePoolLookupByName(pool)
        collidelist = []
        for disk in guest.get_devices("disk"):
            if (disk.get_vol_install() and
                disk.get_vol_install().pool.name() == poolobj.name()):
                collidelist.append(os.path.basename(disk.path))

        vname = virtinst.StorageVolume.find_free_name(
            poolobj, guest.name, suffix=".img", collidelist=collidelist)

        volinst = virtinst.VirtualDisk.build_vol_install(
                guest.conn, vname, poolobj, size, sparse)
        if fmt:
            if not volinst.supports_property("format"):
                raise ValueError(_("Format attribute not supported for this "
                                   "volume type"))
            volinst.format = fmt

    elif vol:
        if not vol.count("/"):
            raise ValueError(_("Storage volume must be specified as "
                               "vol=poolname/volname"))
        vollist = vol.split("/")
        voltuple = (vollist[0], vollist[1])
        logging.debug("Parsed volume: as pool='%s' vol='%s'",
                      voltuple[0], voltuple[1])
        if voltuple[0] == "default":
            virtinst.StoragePool.build_default_pool(guest.conn)

        volobj = virtinst.VirtualDisk.lookup_vol_object(guest.conn, voltuple)

    return abspath, volinst, volobj


def parse_disk(guest, optstr, dev=None, validate=True):
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
    backing_store = opt_get("backing_store")
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
                           vol_install=volinst, backing_store=backing_store)

    set_param = _build_set_param(dev, opts)

    set_param("device", "device")
    set_param("bus", "bus")
    set_param("removable", "removable", convert_cb=_on_off_convert)
    set_param("driver_cache", "cache")
    set_param("driver_name", "driver_name")
    set_param("driver_type", "driver_type")
    set_param("driver_io", "io")
    set_param("error_policy", "error_policy")
    set_param("serial", "serial")
    set_param("target", "target")
    set_param("sourceStartupPolicy", "startup_policy")

    _check_leftover_opts(opts)
    if validate:
        dev.validate()
    return dev, size


#####################
# --network parsing #
#####################

def parse_network(guest, optstr, dev):
    ignore = guest
    opts = parse_optstr(optstr, remove_first="type")
    set_param = _build_set_param(dev, opts)

    if "type" not in opts:
        if "network" in opts:
            opts["type"] = virtinst.VirtualNetworkInterface.TYPE_VIRTUAL
        elif "bridge" in opts:
            opts["type"] = virtinst.VirtualNetworkInterface.TYPE_BRIDGE

    def convert_mac(key, val):
        ignore = key
        if val == "RANDOM":
            return None
        return val

    set_param("type", "type")
    set_param("source", "network")
    set_param("source", "bridge")
    set_param("model", "model")
    set_param("macaddr", "mac", convert_cb=convert_mac)
    set_param("filterref", "filterref")

    _check_leftover_opts(opts)
    return dev

get_networks = _make_handler(virtinst.VirtualNetworkInterface, parse_network)


######################
# --graphics parsing #
######################

def parse_graphics(guest, optstr, dev):
    ignore = guest
    opts = parse_optstr(optstr, remove_first="type")
    if opts.get("type") == "none":
        return None
    set_param = _build_set_param(dev, opts)

    def convert_keymap(key, keymap):
        ignore = key
        from virtinst import hostkeymap

        if not keymap:
            return None
        if keymap.lower() == "local":
            return virtinst.VirtualGraphics.KEYMAP_LOCAL
        if keymap.lower() == "none":
            return None

        use_keymap = hostkeymap.sanitize_keymap(keymap)
        if not use_keymap:
            raise ValueError(
                        _("Didn't match keymap '%s' in keytable!") % keymap)
        return use_keymap

    set_param("type", "type", ignore_default=True)
    set_param("port", "port")
    set_param("tlsPort", "tlsport")
    set_param("listen", "listen")
    set_param("keymap", "keymap", convert_cb=convert_keymap)
    set_param("passwd", "password")
    set_param("passwdValidTo", "passwordvalidto")

    _check_leftover_opts(opts)
    return dev

get_graphics = _make_handler(virtinst.VirtualGraphics, parse_graphics)


########################
# --controller parsing #
########################

def parse_controller(guest, optstr, dev):
    if optstr == "usb2":
        return virtinst.VirtualController.get_usb2_controllers(guest.conn)
    elif optstr == "usb3":
        dev.type = "usb"
        dev.model = "nec-xhci"
        return dev

    opts = parse_optstr(optstr, remove_first="type")
    set_param = _build_set_param(dev, opts)

    set_param("type", "type")
    set_param("model", "model")
    set_param("index", "index")
    set_param("master_startport", "master")
    set_param(dev.address.set_addrstr, "address")

    _check_leftover_opts(opts)
    return dev

get_controllers = _make_handler(virtinst.VirtualController, parse_controller)


#######################
# --smartcard parsing #
#######################

def parse_smartcard(guest, optstr, dev=None):
    ignore = guest
    opts = parse_optstr(optstr, remove_first="mode")
    if opts.get("mode") == "none":
        return None

    set_param = _build_set_param(dev, opts)
    set_param("mode", "mode")
    set_param("type", "type")

    _check_leftover_opts(opts)
    return dev

get_smartcards = _make_handler(virtinst.VirtualSmartCardDevice, parse_smartcard)


######################
# --redirdev parsing #
######################

def parse_redirdev(guest, optstr, dev):
    ignore = guest
    opts = parse_optstr(optstr, remove_first="bus")
    if opts.get("bus") == "none":
        return None

    set_param = _build_set_param(dev, opts)
    set_param("bus", "bus")
    set_param("type", "type")
    set_param(dev.parse_friendly_server, "server")

    _check_leftover_opts(opts)
    return dev

get_redirdevs = _make_handler(virtinst.VirtualRedirDevice, parse_redirdev)


#################
# --tpm parsing #
#################

def parse_tpm(guest, optstr, dev=None):
    ignore = guest
    if optstr == "none":
        return None

    opts = parse_optstr(optstr, remove_first="type")
    set_param = _build_set_param(dev, opts)

    # Allow --tpm /dev/tpm
    if opts.get("type", "").startswith("/"):
        dev.device_path = opts.pop("type")
    else:
        set_param("type", "type")

    set_param("model", "model")
    set_param("device_path", "path")

    _check_leftover_opts(opts)
    return dev

get_tpms = _make_handler(virtinst.VirtualTPMDevice, parse_tpm)


#################
# --rng parsing #
#################

def parse_rng(guest, optstr, dev):
    ignore = guest
    if optstr == "none":
        return None

    opts = parse_optstr(optstr, remove_first="type")
    set_param = _build_set_param(dev, opts)

    # Allow --rng /dev/random
    if opts.get("type", "").startswith("/"):
        dev.device = opts.pop("type")
        dev.type = "random"
    else:
        set_param("type", "type")

    set_param("backend_type", "backend_type")

    backend_mode = opts.get("backend_mode", "connect")
    if backend_mode == "connect":
        set_param("connect_host", "backend_host")
        set_param("connect_service", "backend_service")

    if backend_mode == "bind":
        set_param("bind_host", "backend_host")
        set_param("bind_service", "backend_service")

        if opts.get("backend_type", "udp"):
            set_param("connect_host", "backend_connect_host")
            set_param("connect_service", "backend_connect_service")

    set_param("device", "device")
    set_param("model", "model")
    set_param("rate_bytes", "rate_bytes")
    set_param("rate_period", "rate_period")

    return dev

get_rngs = _make_handler(virtinst.VirtualRNGDevice, parse_rng)


######################
# --watchdog parsing #
######################

def parse_watchdog(guest, optstr, dev):
    ignore = guest
    opts = parse_optstr(optstr, remove_first="model")
    set_param = _build_set_param(dev, opts)

    set_param("model", "model")
    set_param("action", "action")

    _check_leftover_opts(opts)
    return dev

get_watchdogs = _make_handler(virtinst.VirtualWatchdog, parse_watchdog)


########################
# --memballoon parsing #
########################

def parse_memballoon(guest, optstr, dev):
    ignore = guest
    opts = parse_optstr(optstr, remove_first="model")
    set_param = _build_set_param(dev, opts)

    set_param("model", "model")

    _check_leftover_opts(opts)
    return dev

get_memballoons = _make_handler(virtinst.VirtualMemballoon, parse_memballoon)


######################################################
# --serial, --parallel, --channel, --console parsing #
######################################################

def _parse_char(guest, optstr, dev):
    """
    Helper to parse --serial/--parallel options
    """
    ignore = guest
    dev_type = dev.virtual_device_type
    opts = parse_optstr(optstr, remove_first="char_type")
    ctype = opts.get("char_type")

    if ctype == "none" and dev_type == "console":
        guest.skip_default_console = True
        return
    if ctype == "none" and dev_type == "channel":
        guest.skip_default_channel = True
        return

    def support_check(dev, paramname, dictname):
        if type(paramname) is not str:
            return
        if not dev.supports_property(paramname):
            raise ValueError(_("%(devtype)s type '%(chartype)s' does not "
                               "support '%(optname)s' option.") %
                             {"devtype" : dev_type, "chartype": ctype,
                              "optname" : dictname})

    def parse_host(val):
        host, ignore, port = (val or "").partition(":")
        return host or None, port or None

    def set_host(hostparam, portparam, val):
        host, port = parse_host(val)
        if host:
            setattr(dev, hostparam, host)
        if port:
            setattr(dev, portparam, port)

    set_param = _build_set_param(dev, opts, support_cb=support_check)
    set_param("type", "char_type")
    set_param("source_path", "path")
    set_param("source_mode", "mode")
    set_param("protocol",   "protocol")
    set_param("target_type", "target_type")
    set_param("target_name", "name")
    set_param(lambda v: set_host("source_host", "source_port", v), "host")
    set_param(lambda v: set_host("bind_host", "bind_port", v), "bind_host")
    set_param(lambda v: set_host("target_address", "target_port", v),
              "target_address")

    _check_leftover_opts(opts)
    return dev

get_serials = _make_handler(virtinst.VirtualSerialDevice, _parse_char)
get_parallels = _make_handler(virtinst.VirtualParallelDevice, _parse_char)
get_channels = _make_handler(virtinst.VirtualChannelDevice, _parse_char)
get_consoles = _make_handler(virtinst.VirtualConsoleDevice, _parse_char)


########################
# --filesystem parsing #
########################

def parse_filesystem(guest, optstr, dev):
    ignore = guest
    opts = parse_optstr(optstr, remove_first=["source", "target"])
    set_param = _build_set_param(dev, opts)

    set_param("type", "type")
    set_param("mode", "mode")
    set_param("source", "source")
    set_param("target", "target")

    _check_leftover_opts(opts)
    return dev

get_filesystems = _make_handler(virtinst.VirtualFilesystem, parse_filesystem)


###################
# --video parsing #
###################

def parse_video(guest, optstr, dev):
    ignore = guest
    opts = parse_optstr(optstr, remove_first="model")
    set_param = _build_set_param(dev, opts)

    def convert_model(key, val):
        ignore = key
        if val == "default":
            return _CLI_UNSET
        return val

    set_param("model", "model", convert_cb=convert_model)

    _check_leftover_opts(opts)
    return dev

get_videos = _make_handler(virtinst.VirtualVideoDevice, parse_video)


#####################
# --soundhw parsing #
#####################

def parse_sound(guest, optstr, dev):
    ignore = guest
    opts = parse_optstr(optstr, remove_first="model")
    set_param = _build_set_param(dev, opts)

    def convert_model(key, val):
        ignore = key
        if val == "default":
            return _CLI_UNSET
        return val

    set_param("model", "model", convert_cb=convert_model)

    _check_leftover_opts(opts)
    return dev

get_sounds = _make_handler(virtinst.VirtualAudio, parse_sound)


#####################
# --hostdev parsing #
#####################

def parse_hostdev(guest, optstr, dev):
    ignore = guest
    opts = parse_optstr(optstr, remove_first="name")
    set_param = _build_set_param(dev, opts)

    def convert_name(key, val):
        ignore = key
        return virtinst.NodeDevice.lookupNodeName(guest.conn, val)

    set_param(dev.set_from_nodedev, "name", convert_cb=convert_name)

    _check_leftover_opts(opts)
    return dev

get_hostdevs = _make_handler(virtinst.VirtualHostDevice, parse_hostdev)

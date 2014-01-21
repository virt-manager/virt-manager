#
# Utility functions for the command line drivers
#
# Copyright 2006-2007, 2013, 2014 Red Hat, Inc.
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

import argparse
import logging
import logging.handlers
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


class VirtHelpFormatter(argparse.HelpFormatter):
    '''
    Subclass the default help formatter to allow printing newline characters
    in --help output. The way we do this is a huge hack :(

    Inspiration: http://groups.google.com/group/comp.lang.python/browse_thread/thread/6df6e6b541a15bc2/09f28e26af0699b1
    '''
    oldwrap = None

    def _split_lines(self, *args, **kwargs):
        def return_default():
            return argparse.HelpFormatter._split_lines(self, *args, **kwargs)

        if len(kwargs) != 0 and len(args) != 2:
            return return_default()

        try:
            text = args[0]
            if "\n" in text:
                return text.splitlines()
            return return_default()
        except:
            return return_default()


def setupParser(usage, description):
    epilog = _("See man page for examples and full option syntax.")

    parser = argparse.ArgumentParser(
        usage=usage, description=description,
        formatter_class=VirtHelpFormatter,
        epilog=epilog)
    parser.add_argument('--version', action='version',
                        version=cliconfig.__version__)

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
    if val is None:
        return None

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
        names = dev.is_conflict_disk()
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
    parser.add_argument("--connect", metavar="URI",
                      help=_("Connect to hypervisor with libvirt URI"))


def add_misc_options(grp, prompt=False, replace=False,
                     printxml=False, printstep=False,
                     noreboot=False, dryrun=False):
    if prompt:
        grp.add_argument("--prompt", action="store_true",
                        default=False, help=argparse.SUPPRESS)
        grp.add_argument("--force", action="store_true",
                        default=False, help=argparse.SUPPRESS)

    if noreboot:
        grp.add_argument("--noreboot", action="store_true",
                       help=_("Don't boot guest after completing install."))

    if replace:
        grp.add_argument("--replace", action="store_true",
            help=_("Don't check name collision, overwrite any guest "
                   "with the same name."))

    if printxml:
        grp.add_argument("--print-xml", action="store_true", dest="xmlonly",
            help=_("Print the generated domain XML rather than define "
                   "and clone the guest."))
        if printstep:
            grp.add_argument("--print-step", dest="xmlstep",
                help=_("Print XML of a specific install step "
                       "(1, 2, 3, all) rather than define the guest."))

    if dryrun:
        grp.add_argument("--dry-run", action="store_true", dest="dry",
                       help=_("Run through install process, but do not "
                              "create devices or define the guest."))

    grp.add_argument("-q", "--quiet", action="store_true",
                   help=_("Suppress non-error output"))
    grp.add_argument("-d", "--debug", action="store_true",
                   help=_("Print debugging information"))


def vcpu_cli_options(grp, backcompat=True):
    grp.add_argument("--vcpus",
        help=_("Number of vcpus to configure for your guest. Ex:\n"
               "--vcpus 5\n"
               "--vcpus 5,maxcpus=10\n"
               "--vcpus sockets=2,cores=4,threads=2"))
    grp.add_argument("--cpuset",
                   help=_("Set which physical CPUs domain can use."))
    grp.add_argument("--cpu",
        help=_("CPU model and features. Ex: --cpu coreduo,+x2apic"))

    if backcompat:
        grp.add_argument("--check-cpu", action="store_true",
                         help=argparse.SUPPRESS)


def graphics_option_group(parser):
    """
    Register vnc + sdl options for virt-install and virt-image
    """

    vncg = parser.add_argument_group(_("Graphics Configuration"))
    add_gfx_option(vncg)
    vncg.add_argument("--vnc", action="store_true",
                    help=argparse.SUPPRESS)
    vncg.add_argument("--vncport", type=int,
                    help=argparse.SUPPRESS)
    vncg.add_argument("--vnclisten",
                    help=argparse.SUPPRESS)
    vncg.add_argument("-k", "--keymap",
                    help=argparse.SUPPRESS)
    vncg.add_argument("--sdl", action="store_true",
                    help=argparse.SUPPRESS)
    vncg.add_argument("--nographics", action="store_true",
                    help=argparse.SUPPRESS)
    return vncg


def network_option_group(parser):
    """
    Register common network options for virt-install and virt-image
    """
    netg = parser.add_argument_group(_("Networking Configuration"))

    add_net_option(netg)

    # Deprecated net options
    netg.add_argument("-b", "--bridge", action="append",
                    help=argparse.SUPPRESS)
    netg.add_argument("-m", "--mac", action="append",
                    help=argparse.SUPPRESS)

    return netg


def add_net_option(devg):
    devg.add_argument("-w", "--network", action="append",
      help=_("Configure a guest network interface. Ex:\n"
             "--network bridge=mybr0\n"
             "--network network=my_libvirt_virtual_net\n"
             "--network network=mynet,model=virtio,mac=00:11...\n"
             "--network network=mynet,filterref=clean-traffic,model=virtio"))


def add_device_options(devg):
    devg.add_argument("--controller", action="append",
                    help=_("Configure a guest controller device. Ex:\n"
                           "--controller type=usb,model=ich9-ehci1"))
    devg.add_argument("--serial", action="append",
                    help=_("Configure a guest serial device"))
    devg.add_argument("--parallel", action="append",
                    help=_("Configure a guest parallel device"))
    devg.add_argument("--channel", action="append",
                    help=_("Configure a guest communication channel"))
    devg.add_argument("--console", action="append",
                    help=_("Configure a text console connection between "
                           "the guest and host"))
    devg.add_argument("--host-device", action="append",
                    help=_("Configure physical host devices attached to the "
                           "guest"))
    devg.add_argument("--soundhw", action="append",
                    help=_("Configure guest sound device emulation"))
    devg.add_argument("--watchdog", action="append",
                    help=_("Configure a guest watchdog device"))
    devg.add_argument("--video", action="append",
                    help=_("Configure guest video hardware."))
    devg.add_argument("--smartcard", action="append",
                    help=_("Configure a guest smartcard device. Ex:\n"
                           "--smartcard mode=passthrough"))
    devg.add_argument("--redirdev", action="append",
                    help=_("Configure a guest redirection device. Ex:\n"
                           "--redirdev usb,type=tcp,server=192.168.1.1:4000"))
    devg.add_argument("--memballoon", action="append",
                    help=_("Configure a guest memballoon device. Ex:\n"
                           "--memballoon model=virtio"))
    devg.add_argument("--tpm", action="append",
                    help=_("Configure a guest TPM device. Ex:\n"
                           "--tpm /dev/tpm"))
    devg.add_argument("--rng", action="append",
                    help=_("Configure a guest RNG device. Ex:\n"
                           "--rng /dev/random\n"
     "--rng egd,backend_host=localhost,backend_service=708,backend_type=tcp"))
    devg.add_argument("--panic", action="append",
                    help=_("Configure a guest panic device. Ex:\n"
                           "--panic default"))


def add_gfx_option(devg):
    devg.add_argument("--graphics", action="append",
      help=_("Configure guest display settings. Ex:\n"
             "--graphics vnc\n"
             "--graphics spice,port=5901,tlsport=5902\n"
             "--graphics none\n"
             "--graphics vnc,password=foobar,port=5910,keymap=ja"))


def add_fs_option(devg):
    devg.add_argument("--filesystem", action="append",
        help=_("Pass host directory to the guest. Ex: \n"
               "--filesystem /my/source/dir,/dir/in/guest\n"
               "--filesystem template_name,/,type=template"))


def add_distro_options(g):
    # Way back when, we required specifying both --os-type and --os-variant
    # Nowadays the distinction is pointless, so hide the less useful
    # --os-type option.
    g.add_argument("--os-type", dest="distro_type",
                help=argparse.SUPPRESS)
    g.add_argument("--os-variant", dest="distro_variant",
                 help=_("The OS variant being installed guests, "
                        "e.g. 'fedora18', 'rhel6', 'winxp', etc."))


def add_old_feature_options(optg):
    optg.add_argument("--noapic", action="store_true",
                    default=False, help=argparse.SUPPRESS)
    optg.add_argument("--noacpi", action="store_true",
                    default=False, help=argparse.SUPPRESS)



#############################################
# CLI complex parsing helpers               #
# (for options like --disk, --network, etc. #
#############################################

class _VirtCLIArgument(object):
    def __init__(self, attrname, cliname,
                 setter_cb=None, ignore_default=False,
                 can_comma=False, is_list=False, is_onoff=False):
        """
        A single subargument passed to compound command lines like --disk,
        --network, etc.

        @attrname: The virtinst API attribute name the cliargument maps to.
            If this is a virtinst object method, it will be called.
        @cliname: The command line option name, 'path' for path=FOO

        @setter_cb: Rather than set an attribute directly on the virtinst
            object, (opts, inst, cliname, val) to this callback to handle it.
        @ignore_default: If the value passed on the cli is 'default', don't
            do anything.
        @can_comma: If True, this option is expected to have embedded commas.
            After the parser sees this option, it will iterate over the
            option string until it finds another known argument name:
            everything prior to that argument name is considered part of
            the value of this option. Should be used sparingly.
        @is_list: This value should be stored as a list, so multiple instances
            are appended.
        @is_onoff: The value expected on the cli is on/off or yes/no, convert
            it to true/false.
        """
        self.attrname = attrname
        self.cliname = cliname

        self.setter_cb = setter_cb
        self.can_comma = can_comma
        self.is_list = is_list
        self.is_onoff = is_onoff
        self.ignore_default = ignore_default


    def parse(self, opts, inst, support_cb=None):
        val = opts.get_opt_param(self.cliname)
        if val is None:
            return

        if support_cb:
            support_cb(inst, self.attrname, self.cliname)
        if self.is_onoff:
            val = _on_off_convert(self.cliname, val)
        if val == "default" and self.ignore_default:
            return

        attr = None
        try:
            if self.setter_cb:
                attr = None
            elif callable(self.attrname):
                attr = self.attrname
            else:
                attr = eval("inst." + self.attrname)
        except AttributeError:
            raise RuntimeError("programming error: obj=%s does not have "
                               "member=%s" % (inst, self.attrname))

        if self.setter_cb:
            self.setter_cb(opts, inst, self.cliname, val)
        elif callable(attr):
            attr(val)
        else:
            exec("inst." + self.attrname + " = val")  # pylint: disable=W0122



class VirtOptionString(object):
    def __init__(self, optstr, virtargs, remove_first=None):
        """
        Helper class for parsing opt strings of the form
        opt1=val1,opt2=val2,...

        @optstr: The full option string
        @virtargs: A list of VirtCLIArguments
        @remove_first: List or parameters to peel off the front of
            option string, and store in the returned dict.
            remove_first=["char_type"] for --serial pty,foo=bar
            maps to {"char_type", "pty", "foo" : "bar"}
        """
        self.fullopts = optstr

        virtargmap = dict((arg.cliname, arg) for arg in virtargs)

        # @opts: A dictionary of the mapping {cliname: val}
        # @orderedopts: A list of tuples (cliname: val), in the order
        #   they appeared on the CLI.
        self.opts, self.orderedopts = self._parse_optstr(
            virtargmap, remove_first)

    def get_opt_param(self, key):
        return self.opts.pop(key, None)

    def check_leftover_opts(self):
        if not self.opts:
            return
        raise fail(_("Unknown options %s") % self.opts.keys())


    ###########################
    # Actual parsing routines #
    ###########################

    def _parse_optstr_tuples(self, virtargmap, remove_first):
        """
        Parse the command string into an ordered list of tuples (see
        docs for orderedopts
        """
        optstr = str(self.fullopts or "")
        optlist = []

        argsplitter = shlex.shlex(optstr, posix=True)
        argsplitter.commenters = ""
        argsplitter.whitespace = ","
        argsplitter.whitespace_split = True

        remove_first = util.listify(remove_first)[:]
        commaopt = None
        for opt in list(argsplitter):
            if not opt:
                continue

            cliname = opt
            val = None
            if opt.count("="):
                cliname, val = opt.split("=", 1)
                remove_first = []
            elif remove_first:
                val = cliname
                cliname = remove_first.pop(0)

            if commaopt:
                if cliname in virtargmap:
                    optlist.append(tuple(commaopt))
                    commaopt = None
                else:
                    commaopt[1] += "," + (val or cliname)
                    continue

            if (cliname in virtargmap and virtargmap[cliname].can_comma):
                commaopt = [cliname, val]
                continue

            optlist.append((cliname, val))

        if commaopt:
            optlist.append(tuple(commaopt))

        return optlist

    def _parse_optstr(self, virtargmap, remove_first):
        orderedopts = self._parse_optstr_tuples(virtargmap, remove_first)
        optdict = {}

        for cliname, val in orderedopts:
            if (cliname not in optdict and
                cliname in virtargmap and
                virtargmap[cliname].is_list):
                optdict[cliname] = []

            if type(optdict.get(cliname)) is list:
                optdict[cliname].append(val)
            else:
                optdict[cliname] = val

        return optdict, orderedopts


class VirtCLIParser(object):
    """
    Parse a compound arg string like --option foo=bar,baz=12. This is
    the desired interface to VirtCLIArgument and VirtCLIOptionString.

    A command line argument just extends this interface, implements
    _init_params, and calls set_param in the order it wants the options
    parsed on the command line. See existing impls examples of how to
    do all sorts of crazy stuff
    """
    devclass = None

    def __init__(self, cli_arg_name):
        """
        These values should be set by subclasses in _init_params

        @cli_arg_name: The command line argument this maps to, so
            "host-device" for --host-device
        @guest: Will be set parse(), the toplevel virtinst.Guest object
        @remove_first: Passed to VirtOptionString
        @check_none: If the parsed option string is just 'none', return None
        @support_cb: An extra support check function for further validation.
            Called before the virtinst object is altered. Take arguments
            (inst, attrname, cliname)
        """
        self.cli_arg_name = cli_arg_name
        # This is the name of the variable that argparse will set in
        # the result of parse_args()
        self.option_variable_name = cli_arg_name.replace("-", "_")

        self.guest = None
        self.remove_first = None
        self.check_none = False
        self.support_cb = None

        self._params = []
        self._inparse = False

        self._init_params()

    def set_param(self, *args, **kwargs):
        if self._inparse:
            # Otherwise we might break command line introspection
            raise RuntimeError("programming error: Can not call set_param "
                               "from parse handler.")
        self._params.append(_VirtCLIArgument(*args, **kwargs))

    def parse(self, guest, optlist, inst=None, validate=True):
        optlist = util.listify(optlist)
        editting = bool(inst)

        if editting and optlist:
            # If an object is passed in, we are updating it in place, and
            # only use the last command line occurence, eg. from virt-xml
            optlist = [optlist[-1]]

        ret = []
        for optstr in optlist:
            optinst = inst
            if self.devclass and not inst:
                optinst = self.devclass(guest.conn)  # pylint: disable=E1102

            try:
                devs = self._parse_single_optstr(guest, optstr, optinst)
                for dev in util.listify(devs):
                    if not hasattr(dev, "virtual_device_type"):
                        continue

                    if validate:
                        dev.validate()
                    if editting:
                        continue
                    guest.add_device(dev)

                ret += util.listify(devs)
            except Exception, e:
                logging.debug("Exception parsing inst=%s optstr=%s",
                              inst, optstr, exc_info=True)
                fail(_("Error: --%(cli_arg_name)s %(options)s: %(err)s") %
                        {"cli_arg_name": self.cli_arg_name,
                         "options": optstr, "err": str(e)})

        if not ret:
            return None
        if len(ret) == 1:
            return ret[0]
        return ret

    def _parse_single_optstr(self, guest, optstr, inst):
        if not optstr:
            return None
        if self.check_none and optstr == "none":
            return None

        if not inst:
            inst = guest

        try:
            self.guest = guest
            self._inparse = True
            opts = VirtOptionString(optstr, self._params,
                                    remove_first=self.remove_first)
            return self._parse(opts, inst)
        finally:
            self.guest = None
            self._inparse = False

    def _parse(self, opts, inst):
        for param in self._params:
            param.parse(opts, inst, self.support_cb)
        opts.check_leftover_opts()
        return inst

    def _init_params(self):
        raise NotImplementedError()




######################
# --numatune parsing #
######################

class ParserNumatune(VirtCLIParser):
    def _init_params(self):
        self.remove_first = "nodeset"

        self.set_param("numatune.memory_nodeset", "nodeset", can_comma=True)
        self.set_param("numatune.memory_mode", "mode")


##################
# --vcpu parsing #
##################

class ParserVCPU(VirtCLIParser):
    def _init_params(self):
        self.remove_first = "vcpus"

        self.set_param("cpu.sockets", "sockets")
        self.set_param("cpu.cores", "cores")
        self.set_param("cpu.threads", "threads")

        def set_vcpus_cb(opts, inst, cliname, val):
            ignore = cliname
            attrname = ("maxvcpus" in opts.opts) and "curvcpus" or "vcpus"
            setattr(inst, attrname, val)

        self.set_param(None, "vcpus", setter_cb=set_vcpus_cb)
        self.set_param("vcpus", "maxvcpus")


    def _parse(self, opts, inst):
        set_from_top = ("maxvcpus" not in opts.opts and
                        "vcpus" not in opts.opts)

        ret = VirtCLIParser._parse(self, opts, inst)

        if set_from_top:
            inst.vcpus = inst.cpu.vcpus_from_topology()
        return ret


#################
# --cpu parsing #
#################

class ParserCPU(VirtCLIParser):
    def _init_params(self):
        self.remove_first = "model"

        def set_model_cb(opts, inst, cliname, val):
            ignore = opts
            ignore = cliname
            if val == "host":
                inst.cpu.copy_host_cpu()
            else:
                inst.cpu.model = val

        def set_feature_cb(opts, inst, cliname, val):
            ignore = opts
            policy = cliname
            for feature_name in util.listify(val):
                inst.cpu.add_feature(feature_name, policy)

        self.set_param(None, "model", setter_cb=set_model_cb)
        self.set_param("cpu.match", "match")
        self.set_param("cpu.vendor", "vendor")

        self.set_param(None, "force", is_list=True, setter_cb=set_feature_cb)
        self.set_param(None, "require", is_list=True, setter_cb=set_feature_cb)
        self.set_param(None, "optional", is_list=True, setter_cb=set_feature_cb)
        self.set_param(None, "disable", is_list=True, setter_cb=set_feature_cb)
        self.set_param(None, "forbid", is_list=True, setter_cb=set_feature_cb)

    def _parse(self, optsobj, inst):
        opts = optsobj.opts

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
                if opts.get(policy) is None:
                    opts[policy] = []
                opts[policy].append(key[1:])

        return VirtCLIParser._parse(self, optsobj, inst)


##################
# --boot parsing #
##################

class ParserBoot(VirtCLIParser):
    def _init_params(self):
        self.set_param("os.useserial", "useserial", is_onoff=True)
        self.set_param("os.enable_bootmenu", "menu", is_onoff=True)
        self.set_param("os.kernel", "kernel")
        self.set_param("os.initrd", "initrd")
        self.set_param("os.dtb", "dtb")
        self.set_param("os.loader", "loader")
        self.set_param("os.kernel_args", "extra_args")
        self.set_param("os.kernel_args", "kernel_args")

        # Order matters for boot devices, we handle it specially in parse
        def noset_cb(val):
            ignore = val
        for b in virtinst.OSXML.BOOT_DEVICES:
            self.set_param(noset_cb, b)

    def _parse(self, opts, inst):
        # Build boot order
        boot_order = []
        for cliname, ignore in opts.orderedopts:
            if not cliname in inst.os.BOOT_DEVICES:
                continue

            del(opts.opts[cliname])
            if cliname not in boot_order:
                boot_order.append(cliname)

        if boot_order:
            inst.os.bootorder = boot_order

        VirtCLIParser._parse(self, opts, inst)


######################
# --security parsing #
######################

class ParserSecurity(VirtCLIParser):
    def _init_params(self):
        self.set_param("seclabel.type", "type")
        self.set_param("seclabel.label", "label", can_comma=True)
        self.set_param("seclabel.relabel", "relabel",
                       is_onoff=True)


######################
# --features parsing #
######################

class ParserFeatures(VirtCLIParser):
    def _init_params(self):
        self.set_param("features.acpi", "acpi", is_onoff=True)
        self.set_param("features.apic", "apic", is_onoff=True)
        self.set_param("features.pae", "pae", is_onoff=True)
        self.set_param("features.privnet", "privnet",
            is_onoff=True)
        self.set_param("features.hap", "hap",
            is_onoff=True)
        self.set_param("features.viridian", "viridian",
            is_onoff=True)
        self.set_param("features.eoi", "eoi", is_onoff=True)

        self.set_param("features.hyperv_vapic", "hyperv_vapic",
            is_onoff=True)
        self.set_param("features.hyperv_relaxed", "hyperv_relaxed",
            is_onoff=True)
        self.set_param("features.hyperv_spinlocks", "hyperv_spinlocks",
            is_onoff=True)
        self.set_param("features.hyperv_spinlocks_retries",
            "hyperv_spinlocks_retries")


###################
# --clock parsing #
###################

class ParserClock(VirtCLIParser):
    def _init_params(self):
        self.set_param("clock.offset", "offset")

        def set_timer(opts, inst, cliname, val):
            ignore = opts
            tname, attrname = cliname.split("_")

            timerobj = None
            for t in inst.clock.timers:
                if t.name == tname:
                    timerobj = t
                    break

            if not timerobj:
                timerobj = inst.clock.add_timer()
                timerobj.name = tname

            setattr(timerobj, attrname, val)

        for tname in virtinst.Clock.TIMER_NAMES:
            self.set_param(None, tname + "_present",
                is_onoff=True,
                setter_cb=set_timer)
            self.set_param(None, tname + "_tickpolicy", setter_cb=set_timer)


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


class ParserDisk(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualDisk
        self.remove_first = "path"

        def noset_cb(val):
            ignore = val

        # These are all handled specially in _parse
        self.set_param(noset_cb, "path")
        self.set_param(noset_cb, "backing_store")
        self.set_param(noset_cb, "pool")
        self.set_param(noset_cb, "vol")
        self.set_param(noset_cb, "size")
        self.set_param(noset_cb, "format")
        self.set_param(noset_cb, "sparse")
        self.set_param(noset_cb, "perms")

        self.set_param("device", "device")
        self.set_param("bus", "bus")
        self.set_param("removable", "removable", is_onoff=True)
        self.set_param("driver_cache", "cache")
        self.set_param("driver_name", "driver_name")
        self.set_param("driver_type", "driver_type")
        self.set_param("driver_io", "io")
        self.set_param("error_policy", "error_policy")
        self.set_param("serial", "serial")
        self.set_param("target", "target")
        self.set_param("sourceStartupPolicy", "startup_policy")


    def _parse(self, opts, inst):
        def parse_size(val):
            if val is None:
                return None
            try:
                return float(val)
            except Exception, e:
                fail(_("Improper value for 'size': %s" % str(e)))

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

        path = opts.get_opt_param("path")
        backing_store = opts.get_opt_param("backing_store")
        pool = opts.get_opt_param("pool")
        vol = opts.get_opt_param("vol")
        size = parse_size(opts.get_opt_param("size"))
        fmt = opts.get_opt_param("format")
        sparse = _on_off_convert("sparse", opts.get_opt_param("sparse"))
        ro, shared = parse_perms(opts.get_opt_param("perms"))

        abspath, volinst, volobj = _parse_disk_source(
            self.guest, path, pool, vol, size, fmt, sparse)

        inst.path = volobj and volobj.path() or abspath
        inst.read_only = ro
        inst.shareable = shared
        inst.set_create_storage(size=size, fmt=fmt, sparse=sparse,
                               vol_install=volinst, backing_store=backing_store)

        inst = VirtCLIParser._parse(self, opts, inst)
        inst.cli_size = size
        return inst


parse_disk = ParserDisk("disk").parse


#####################
# --network parsing #
#####################

class ParserNetwork(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualNetworkInterface
        self.remove_first = "type"

        def set_mac_cb(opts, inst, cliname, val):
            ignore = opts
            ignore = cliname
            if val == "RANDOM":
                val = None
            inst.macaddr = val
            return val

        self.set_param("type", "type")
        self.set_param("source", "source")
        self.set_param("source_mode", "source_mode")
        self.set_param("target_dev", "target")
        self.set_param("model", "model")
        self.set_param(None, "mac", setter_cb=set_mac_cb)
        self.set_param("filterref", "filterref")

    def _parse(self, optsobj, inst):
        opts = optsobj.opts
        if "type" not in opts:
            if "network" in opts:
                opts["type"] = virtinst.VirtualNetworkInterface.TYPE_VIRTUAL
                opts["source"] = opts.pop("network")
            elif "bridge" in opts:
                opts["type"] = virtinst.VirtualNetworkInterface.TYPE_BRIDGE
                opts["source"] = opts.pop("bridge")

        return VirtCLIParser._parse(self, optsobj, inst)


######################
# --graphics parsing #
######################

class ParserGraphics(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualGraphics
        self.remove_first = "type"
        self.check_none = True

        def set_keymap_cb(opts, inst, cliname, val):
            ignore = opts
            ignore = cliname
            from virtinst import hostkeymap

            if not val:
                val = None
            elif val.lower() == "local":
                val = virtinst.VirtualGraphics.KEYMAP_LOCAL
            elif val.lower() == "none":
                val = None
            else:
                use_keymap = hostkeymap.sanitize_keymap(val)
                if not use_keymap:
                    raise ValueError(
                        _("Didn't match keymap '%s' in keytable!") % val)
                val = use_keymap
            inst.keymap = val

        def set_type_cb(opts, inst, cliname, val):
            ignore = opts
            if val == "default":
                return
            inst.type = val

        self.set_param(None, "type", setter_cb=set_type_cb)
        self.set_param("port", "port")
        self.set_param("tlsPort", "tlsport")
        self.set_param("listen", "listen")
        self.set_param(None, "keymap", setter_cb=set_keymap_cb)
        self.set_param("passwd", "password")
        self.set_param("passwdValidTo", "passwordvalidto")


########################
# --controller parsing #
########################

class ParserController(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualController
        self.remove_first = "type"

        self.set_param("type", "type")
        self.set_param("type", "type")
        self.set_param("model", "model")
        self.set_param("index", "index")
        self.set_param("master_startport", "master")
        self.set_param("address.set_addrstr", "address")

    def _parse(self, opts, inst):
        if opts.fullopts == "usb2":
            return virtinst.VirtualController.get_usb2_controllers(inst.conn)
        elif opts.fullopts == "usb3":
            inst.type = "usb"
            inst.model = "nec-xhci"
            return inst
        return VirtCLIParser._parse(self, opts, inst)


#######################
# --smartcard parsing #
#######################

class ParserSmartcard(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualSmartCardDevice
        self.remove_first = "mode"
        self.check_none = True

        self.set_param("mode", "mode")
        self.set_param("type", "type")


######################
# --redirdev parsing #
######################

class ParserRedir(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualRedirDevice
        self.remove_first = "bus"
        self.check_none = True

        self.set_param("bus", "bus")
        self.set_param("type", "type")
        self.set_param("parse_friendly_server", "server")


#################
# --tpm parsing #
#################

class ParserTPM(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualTPMDevice
        self.remove_first = "type"
        self.check_none = True

        self.set_param("type", "type")
        self.set_param("model", "model")
        self.set_param("device_path", "path")

    def _parse(self, opts, inst):
        if (opts.opts.get("type", "").startswith("/")):
            opts.opts["path"] = opts.opts.pop("type")
        return VirtCLIParser._parse(self, opts, inst)


#################
# --rng parsing #
#################

class ParserRNG(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualRNGDevice
        self.remove_first = "type"
        self.check_none = True

        def set_hosts_cb(opts, inst, cliname, val):
            namemap = {}
            inst.backend_type = self._cli_backend_type

            if self._cli_backend_mode == "connect":
                namemap["backend_host"] = "connect_host"
                namemap["backend_service"] = "connect_service"

            if self._cli_backend_mode == "bind":
                namemap["backend_host"] = "bind_host"
                namemap["backend_service"] = "bind_service"

                if self._cli_backend_type == "udp":
                    namemap["backend_connect_host"] = "connect_host"
                    namemap["backend_connect_service"] = "connect_service"

            if cliname in namemap:
                setattr(inst, namemap[cliname], val)

        def set_backend_cb(opts, inst, cliname, val):
            ignore = opts
            ignore = inst
            if cliname == "backend_mode":
                self._cli_backend_mode = val
            elif cliname == "backend_type":
                self._cli_backend_type = val

        self.set_param("type", "type")

        self.set_param(None, "backend_mode", setter_cb=set_backend_cb)
        self.set_param(None, "backend_type", setter_cb=set_backend_cb)

        self.set_param(None, "backend_host", setter_cb=set_hosts_cb)
        self.set_param(None, "backend_service", setter_cb=set_hosts_cb)
        self.set_param(None, "backend_connect_host", setter_cb=set_hosts_cb)
        self.set_param(None, "backend_connect_service", setter_cb=set_hosts_cb)

        self.set_param("device", "device")
        self.set_param("model", "model")
        self.set_param("rate_bytes", "rate_bytes")
        self.set_param("rate_period", "rate_period")

    def _parse(self, optsobj, inst):
        opts = optsobj.opts

        # pylint: disable=W0201
        # Defined outside init, but its easier this way
        self._cli_backend_mode = "connect"
        self._cli_backend_type = "udp"
        # pylint: enable=W0201

        if opts.get("type", "").startswith("/"):
            # Allow --rng /dev/random
            opts["device"] = opts.pop("type")
            opts["type"] = "random"

        return VirtCLIParser._parse(self, optsobj, inst)


######################
# --watchdog parsing #
######################

class ParserWatchdog(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualWatchdog
        self.remove_first = "model"

        self.set_param("model", "model")
        self.set_param("action", "action")


########################
# --memballoon parsing #
########################

class ParserMemballoon(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualMemballoon
        self.remove_first = "model"

        self.set_param("model", "model")


###################
# --panic parsing #
###################

class ParserPanic(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualPanicDevice
        self.remove_first = "iobase"

        def set_iobase_cb(opts, inst, cliname, val):
            ignore = opts
            ignore = cliname
            if val == "default":
                return
            inst.iobase = val
        self.set_param(None, "iobase", setter_cb=set_iobase_cb)


######################################################
# --serial, --parallel, --channel, --console parsing #
######################################################

class _ParserChar(VirtCLIParser):
    def _init_params(self):
        self.remove_first = "char_type"

        def support_check(inst, attrname, cliname):
            if type(attrname) is not str:
                return
            if not inst.supports_property(attrname):
                raise ValueError(_("%(devtype)s type '%(chartype)s' does not "
                    "support '%(optname)s' option.") %
                    {"devtype" : inst.virtual_device_type,
                     "chartype": inst.type,
                     "optname" : cliname})
        self.support_cb = support_check

        self.set_param("type", "char_type")
        self.set_param("source_path", "path")
        self.set_param("source_mode", "mode")
        self.set_param("protocol",   "protocol")
        self.set_param("target_type", "target_type")
        self.set_param("target_name", "name")
        self.set_param("set_friendly_source", "host")
        self.set_param("set_friendly_bind", "bind_host")
        self.set_param("set_friendly_target", "target_address")

    def _parse(self, opts, inst):
        if opts.fullopts == "none" and inst.virtual_device_type == "console":
            self.guest.skip_default_console = True
            return
        if opts.fullopts == "none" and inst.virtual_device_type == "channel":
            self.guest.skip_default_channel = True
            return

        return VirtCLIParser._parse(self, opts, inst)


class ParserSerial(_ParserChar):
    devclass = virtinst.VirtualSerialDevice


class ParserParallel(_ParserChar):
    devclass = virtinst.VirtualParallelDevice


class ParserChannel(_ParserChar):
    devclass = virtinst.VirtualChannelDevice


class ParserConsole(_ParserChar):
    devclass = virtinst.VirtualConsoleDevice


########################
# --filesystem parsing #
########################

class ParserFilesystem(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualFilesystem
        self.remove_first = ["source", "target"]

        self.set_param("type", "type")
        self.set_param("mode", "mode")
        self.set_param("source", "source")
        self.set_param("target", "target")


###################
# --video parsing #
###################

class ParserVideo(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualVideoDevice
        self.remove_first = "model"

        self.set_param("model", "model", ignore_default=True)


#####################
# --soundhw parsing #
#####################

class ParserSound(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualAudio
        self.remove_first = "model"

        self.set_param("model", "model", ignore_default=True)


#####################
# --hostdev parsing #
#####################

class ParserHostdev(VirtCLIParser):
    def _init_params(self):
        self.devclass = virtinst.VirtualHostDevice
        self.remove_first = "name"

        def set_name_cb(opts, inst, cliname, val):
            ignore = opts
            ignore = cliname
            val = virtinst.NodeDevice.lookupNodeName(inst.conn, val)
            inst.set_from_nodedev(val)

        self.set_param(None, "name", setter_cb=set_name_cb)
        self.set_param("driver_name", "driver_name")


###########################
# Register parser classes #
###########################

def build_parser_map(options, skip=None, only=None):
    """
    Build a dictionary with mapping of cli-name->parserinstance, so
    --vcpus -> ParserVCPU object.
    """
    parsermap = {}
    def register_parser(cli_arg_name, parserclass):
        if cli_arg_name in util.listify(skip):
            return
        if only and cli_arg_name not in util.listify(only):
            return

        parserobj = parserclass(cli_arg_name)
        if not hasattr(options, parserobj.option_variable_name):
            raise RuntimeError("programming error: unknown option=%s "
                               "cliname=%s class=%s" %
                               (parserobj.option_variable_name,
                                parserobj.cli_arg_name, parserclass))
        parsermap[parserobj.option_variable_name] = parserobj

    register_parser("vcpus", ParserVCPU)
    register_parser("cpu", ParserCPU)
    register_parser("numatune", ParserNumatune)
    register_parser("boot", ParserBoot)
    register_parser("security", ParserSecurity)
    register_parser("features", ParserFeatures)
    register_parser("clock", ParserClock)
    register_parser("disk", ParserDisk)
    register_parser("network", ParserNetwork)
    register_parser("graphics", ParserGraphics)
    register_parser("controller", ParserController)
    register_parser("smartcard", ParserSmartcard)
    register_parser("redirdev", ParserRedir)
    register_parser("tpm", ParserTPM)
    register_parser("rng", ParserRNG)
    register_parser("watchdog", ParserWatchdog)
    register_parser("memballoon", ParserMemballoon)
    register_parser("serial", ParserSerial)
    register_parser("parallel", ParserParallel)
    register_parser("channel", ParserChannel)
    register_parser("console", ParserConsole)
    register_parser("filesystem", ParserFilesystem)
    register_parser("video", ParserVideo)
    register_parser("soundhw", ParserSound)
    register_parser("host-device", ParserHostdev)
    register_parser("panic", ParserPanic)

    return parsermap


def parse_option_strings(parsermap, options, guest, inst):
    """
    Iterate over the parsermap, and launch the associated parser
    function for every value that was filled in on 'options', which
    came from argparse/the command line.
    """
    for option_variable_name in dir(options):
        if option_variable_name not in parsermap:
            continue
        parsermap[option_variable_name].parse(
            guest, getattr(options, option_variable_name), inst)

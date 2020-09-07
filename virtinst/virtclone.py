#!/usr/bin/env python3
#
# Copyright(c) FUJITSU Limited 2007.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import argparse
import sys

from . import cli
from .cli import fail, print_stdout, print_stderr
from .cloner import Cloner
from .logger import log


# General input gathering functions
def get_clone_name(new_name, auto_clone, design):
    if not new_name and auto_clone:
        # Generate a name to use
        new_name = design.generate_clone_name()
        log.debug("Auto-generated clone name '%s'", new_name)

    if not new_name:
        fail(_("A name is required for the new virtual machine,"
            " use '--name NEW_VM_NAME' to specify one."))
    design.clone_name = new_name


def get_original_guest(guest_name, origfile, design):
    origxml = None
    if origfile:
        f = open(origfile, "r")
        origxml = f.read()
        f.close()

        try:
            design.original_xml = origxml
            return
        except (ValueError, RuntimeError) as e:  # pragma: no cover
            fail(e)

    if not guest_name:
        fail(_("An original machine name is required,"
            " use '--original ORIGINAL_GUEST' and try again."))
    design.original_guest = guest_name


def get_clone_macaddr(new_mac, design):
    if new_mac is None or new_mac[0] == "RANDOM":
        return
    design.clone_macs = new_mac

    for mac in design.clone_macs:
        cli.validate_mac(design.conn, mac)


def get_clone_diskfile(new_diskfiles, design, preserve, auto_clone):
    if new_diskfiles is None:
        new_diskfiles = [None]

    newidx = 0
    clonepaths = []
    for origpath in [d.path for d in design.original_disks]:
        if len(new_diskfiles) <= newidx:
            # Extend the new/passed paths list with None if it's not
            # long enough
            new_diskfiles.append(None)
        newpath = new_diskfiles[newidx]

        if origpath is None:
            newpath = None
        elif newpath is None and auto_clone:
            newpath = design.generate_clone_disk_path(origpath)

        clonepaths.append(newpath)
        newidx += 1
    design.clone_paths = clonepaths

    for disk in design.clone_disks:
        cli.validate_disk(disk, warn_overwrite=not preserve)


def parse_args():
    desc = _("Duplicate a virtual machine, changing all the unique "
        "host side configuration like MAC address, name, etc. \n\n"
        "The VM contents are NOT altered: virt-clone does not change "
        "anything _inside_ the guest OS, it only duplicates disks and "
        "does host side changes. So things like changing passwords, "
        "changing static IP address, etc are outside the scope of "
        "this tool. For these types of changes, please see virt-sysprep(1).")
    parser = cli.setupParser("%(prog)s --original [NAME] ...", desc)
    cli.add_connect_option(parser)

    geng = parser.add_argument_group(_("General Options"))
    geng.add_argument("-o", "--original", dest="original_guest",
                    help=_("Name of the original guest to clone."))
    geng.add_argument("--original-xml",
                    help=_("XML file to use as the original guest."))
    geng.add_argument("--auto-clone", action="store_true",
                    help=_("Auto generate clone name and storage paths from"
                           " the original guest configuration."))
    geng.add_argument("-n", "--name", dest="new_name",
                    help=_("Name for the new guest"))
    geng.add_argument("-u", "--uuid", dest="new_uuid", help=argparse.SUPPRESS)
    geng.add_argument("--reflink", action="store_true",
            help=_("use btrfs COW lightweight copy"))

    stog = parser.add_argument_group(_("Storage Configuration"))
    stog.add_argument("-f", "--file", dest="new_diskfile", action="append",
                    help=_("New file to use as the disk image for the "
                           "new guest"))
    stog.add_argument("--force-copy", dest="target", action="append",
                    help=_("Force to copy devices (eg, if 'hdc' is a "
                           "readonly cdrom device, --force-copy=hdc)"))
    stog.add_argument("--skip-copy", action="append",
                    help=_("Skip copy of the device target. (eg, if 'vda' is a "
                           "disk you don't want to copy and use the same path "
                           "in the new VM, use --skip-copy=vda)"))
    stog.add_argument("--nonsparse", action="store_false", dest="sparse",
                    default=True,
                    help=_("Do not use a sparse file for the clone's "
                           "disk image"))
    stog.add_argument("--preserve-data", action="store_false",
                    dest="preserve", default=True,
                    help=_("Do not clone storage, new disk images specified "
                           "via --file are preserved unchanged"))
    stog.add_argument("--nvram", dest="new_nvram",
                      help=_("New file to use as storage for nvram VARS"))

    netg = parser.add_argument_group(_("Networking Configuration"))
    netg.add_argument("-m", "--mac", dest="new_mac", action="append",
                    help=_("New fixed MAC address for the clone guest. "
                           "Default is a randomly generated MAC"))

    misc = parser.add_argument_group(_("Miscellaneous Options"))

    # Just used for clone tests
    misc.add_argument("--clone-running", action="store_true",
                      default=False, help=argparse.SUPPRESS)
    misc.add_argument("--__test-nodry", action="store_true",
                      default=False, help=argparse.SUPPRESS)

    cli.add_misc_options(misc, prompt=True, replace=True, printxml=True)

    cli.autocomplete(parser)

    return parser.parse_args()



def main(conn=None):
    cli.earlyLogging()
    options = parse_args()

    options.quiet = options.quiet or options.xmlonly
    cli.setupLogging("virt-clone", options.debug, options.quiet)

    cli.convert_old_force(options)
    cli.parse_check(options.check)
    cli.set_prompt(options.prompt)
    conn = cli.getConnection(options.connect, conn=conn)

    if (options.new_diskfile is None and
        options.auto_clone is False and
        options.xmlonly is False):
        fail(_("Either --auto-clone or --file is required,"
               " use '--auto-clone or --file' and try again."))

    design = Cloner(conn)

    design.clone_running = options.clone_running
    design.replace = bool(options.replace)
    get_original_guest(options.original_guest, options.original_xml,
                       design)
    get_clone_name(options.new_name, options.auto_clone, design)

    get_clone_macaddr(options.new_mac, design)
    if options.new_uuid is not None:
        design.clone_uuid = options.new_uuid
    if options.reflink is True:
        design.reflink = True
    for i in options.target or []:
        design.force_target = i
    for i in options.skip_copy or []:
        design.skip_target = i
    design.clone_sparse = options.sparse
    design.preserve = options.preserve

    design.clone_nvram = options.new_nvram

    # This determines the devices that need to be cloned, so that
    # get_clone_diskfile knows how many new disk paths it needs
    design.setup_original()

    get_clone_diskfile(options.new_diskfile, design,
                       not options.preserve, options.auto_clone)

    # setup design object
    design.setup_clone()

    run = True
    if options.xmlonly:
        run = options.__test_nodry
        print_stdout(design.clone_xml, do_force=True)
    if run:
        design.start_duplicate(cli.get_meter())

    print_stdout("")
    print_stdout(_("Clone '%s' created successfully.") % design.clone_name)
    log.debug("end clone")
    return 0


def runcli():  # pragma: no cover
    try:
        sys.exit(main())
    except SystemExit as sys_e:
        sys.exit(sys_e.code)
    except KeyboardInterrupt:
        print_stderr(_("Installation aborted at user request"))
    except Exception as main_e:
        fail(main_e)

# Copyright 2013-2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import sys

import libvirt

from . import cli
from .cli import fail, fail_conflicting, print_stdout, print_stderr
from .guest import Guest
from .logger import log
from . import xmlutil


###################
# Utility helpers #
###################

def prompt_yes_or_no(msg):
    while 1:
        printmsg = msg + " (y/n): "
        sys.stdout.write(printmsg)
        sys.stdout.flush()
        inp = sys.stdin.readline().lower().strip()

        if inp in ["y", "yes"]:
            return True
        elif inp in ["n", "no"]:
            return False
        else:
            print_stdout(_("Please enter 'yes' or 'no'."))


def get_diff(origxml, newxml):
    diff = xmlutil.diff(origxml, newxml, "Original XML", "Altered XML")

    if diff:
        log.debug("XML diff:\n%s", diff)
    else:
        log.debug("No XML diff, didn't generate any change.")
    return diff


def set_os_variant(guest, os_variant):
    if os_variant is None:
        return

    osdata = cli.parse_os_variant(os_variant)
    if osdata.get_name():
        guest.set_os_name(osdata.get_name())


def defined_xml_is_unchanged(conn, domain, original_xml):
    rawxml = cli.get_xmldesc(domain, inactive=True)
    new_xml = Guest(conn, parsexml=rawxml).get_xml()
    return new_xml == original_xml


##################
# Action parsing #
##################

class Action:
    """
    Helper class tracking one pair of
        XML ACTION (ex. --edit) and
        XML OPTION (ex. --disk)
    """
    def __init__(self, action_name, selector, parserclass, parservalue):
        # one of ["edit", "add-device", "remove-device", "build-xml"]
        self.action_name = action_name
        # ex. for `--edit 1` this is selector="1"
        self.selector = selector
        # ParserDisk, etc
        self.parserclass = parserclass
        # ex for `--disk path=/foo` this is "path=/foo"
        self.parservalue = parservalue

    @property
    def is_edit(self):
        return self.action_name == "edit"

    @property
    def is_add_device(self):
        return self.action_name == "add-device"

    @property
    def is_remove_device(self):
        return self.action_name == "remove-device"

    @property
    def is_build_xml(self):
        return self.action_name == "build-xml"


def validate_action(action, conn, options):
    if options.os_variant is not None:
        if action.is_edit:
            fail(_("--os-variant/--osinfo is not supported with --edit"))
        if action.is_remove_device:
            fail(_("--os-variant/--osinfo is not supported with --remove-device"))
        if action.is_build_xml:
            fail(_("--os-variant/--osinfo is not supported with --build-xml"))

    if not action.parserclass.guest_propname and action.is_build_xml:
        fail(_("--build-xml not supported for {cli_flag}").format(
             cli_flag=action.parserclass.cli_flag_name()))

    stub_guest = Guest(conn)
    if not action.parserclass.prop_is_list(stub_guest):
        if action.is_remove_device:
            fail(_("Cannot use --remove-device with {cli_flag}").format(
                 cli_flag=action.parserclass.cli_flag_name()))
        if action.is_add_device:
            fail(_("Cannot use --add-device with {cli_flag}").format(
                 cli_flag=action.parserclass.cli_flag_name()))

    if options.update and not action.parserclass.guest_propname:
        fail(_("Don't know how to --update for {cli_flag}").format(
             cli_flag=action.parserclass.cli_flag_name()))


def check_action_collision(options):
    collisions = []
    actions = ["edit", "add-device", "remove-device", "build-xml"]
    for cliname in actions:
        optname = cliname.replace("-", "_")
        value = getattr(options, optname)
        if value not in [False, -1]:
            collisions.append((cliname, value))

    if len(collisions) == 0:
        fail(_("One of %s must be specified.") %
             ", ".join(["--" + c for c in actions]))
    if len(collisions) > 1:
        fail(_("Conflicting options %s") %
             ", ".join(["--" + c[0] for c in collisions]))

    action_name, selector = collisions[0]
    return action_name, selector


def check_xmlopt_collision(options):
    collisions = []
    for parserclass in cli.VIRT_PARSERS:
        value = getattr(options, parserclass.cli_arg_name)
        if value:
            collisions.append((parserclass, value))

    if len(collisions) == 0:
        fail(_("No change specified."))
    if len(collisions) != 1:
        fail(_("Only one change operation may be specified "
               "(conflicting options %s)") %
               [c[0].cli_flag_name() for c in collisions])

    parserclass, parservalue = collisions[0]
    return parserclass, parservalue


def parse_action(conn, options):
    # Ensure there wasn't more than one device/xml config option
    # specified. So reject '--disk X --network X'
    parserclass, parservalue = check_xmlopt_collision(options)

    # Ensure only one of these actions was specified
    #   --edit
    #   --remove-device
    #   --add-device
    #   --build-xml
    action_name, selector = check_action_collision(options)

    action = Action(action_name, selector, parserclass, parservalue)
    validate_action(action, conn, options)
    return action


################
# Change logic #
################

def _find_objects_to_edit(guest, action_name, editval, parserclass):
    objlist = xmlutil.listify(parserclass.lookup_prop(guest))
    idx = None

    if editval is None:
        idx = 1
    elif (editval.isdigit() or
          editval.startswith("-") and editval[1:].isdigit()):
        idx = int(editval)

    if idx is not None:
        # Edit device by index
        if idx == 0:
            fail(_("Invalid --edit option '%s'") % editval)

        if not objlist:
            fail(_("No {cli_flag} objects found in the XML").format(
                cli_flag=parserclass.cli_flag_name()))
        if len(objlist) < abs(idx):
            fail(ngettext("'--edit {number}' requested but there's only "
                          "{maxnum} {cli_flag} object in the XML",
                          "'--edit {number}' requested but there are only "
                          "{maxnum} {cli_flag} objects in the XML",
                          len(objlist)).format(
                number=idx, maxnum=len(objlist),
                cli_flag=parserclass.cli_flag_name()))

        if idx > 0:
            idx -= 1
        inst = objlist[idx]

    elif editval == "all":
        # Edit 'all' devices
        inst = objlist[:]

    else:
        # Lookup device by the passed prop string
        parserobj = parserclass(editval, guest=guest)
        inst = parserobj.lookup_child_from_option_string()
        if not inst:
            fail(_("No matching objects found for %s") %
                 ("--%s %s" % (action_name, editval)))

    return inst


def action_edit(action, guest):
    parserclass = action.parserclass
    parservalue = action.parservalue
    selector = action.selector

    if parserclass.guest_propname:
        inst = _find_objects_to_edit(guest, "edit",
                                     selector, parserclass)
    else:
        inst = guest
        if (selector and selector != '1' and selector != 'all'):
            fail(_("'--edit {option}' doesn't make sense with "
                   "{cli_flag}, just use empty '--edit'").format(
                   option=selector,
                   cli_flag=parserclass.cli_flag_name()))

    devs = []
    for editinst in xmlutil.listify(inst):
        devs += cli.run_parser(guest, parserclass, parservalue,
                               editinst=editinst)
    return devs


def action_add_device(action, guest, os_variant, input_devs):
    parserclass = action.parserclass
    parservalue = action.parservalue

    set_os_variant(guest, os_variant)

    if input_devs:
        for dev in input_devs:
            guest.add_device(dev)
        devs = input_devs
    else:
        devs = cli.run_parser(guest, parserclass, parservalue)
        for dev in devs:
            dev.set_defaults(guest)

    return devs


def action_remove_device(action, guest):
    parserclass = action.parserclass
    parservalue = action.parservalue[-1]

    devs = _find_objects_to_edit(guest, "remove-device",
        parservalue, parserclass)
    devs = xmlutil.listify(devs)

    for dev in devs:
        guest.remove_device(dev)
    return devs


def action_build_xml(action, guest):
    parserclass = action.parserclass
    parservalue = action.parservalue

    devs = cli.run_parser(guest, parserclass, parservalue)
    for dev in devs:
        dev.set_defaults(guest)
    return devs


def perform_action(action, guest, options, input_devs):
    if action.is_add_device:
        return action_add_device(action, guest, options.os_variant, input_devs)
    if action.is_remove_device:
        return action_remove_device(action, guest)
    if action.is_edit:
        return action_edit(action, guest)
    raise xmlutil.DevError(
        "perform_action() incorrectly called with action_name=%s" %
        action.action_name)


def setup_device(dev):
    if getattr(dev, "DEVICE_TYPE", None) != "disk":
        return

    log.debug("Doing setup for disk=%s", dev)
    dev.build_storage(cli.get_meter())


def define_changes(conn, inactive_xmlobj, devs, action, confirm):
    if confirm:
        if not prompt_yes_or_no(
                _("Define '%s' with the changed XML?") % inactive_xmlobj.name):
            return False

    if action.is_add_device:
        for dev in devs:
            setup_device(dev)

    dom = conn.defineXML(inactive_xmlobj.get_xml())
    print_stdout(_("Domain '%s' defined successfully.") % inactive_xmlobj.name)
    return dom


def start_domain_transient(conn, xmlobj, devs, action, confirm):
    if confirm:
        if not prompt_yes_or_no(
                _("Start '%s' with the changed XML?") % xmlobj.name):
            return False

    if action.is_add_device:
        for dev in devs:
            setup_device(dev)

    try:
        dom = conn.createXML(xmlobj.get_xml())
    except libvirt.libvirtError as e:
        fail(_("Failed starting domain '%(domain)s': %(error)s") % {
                 "domain": xmlobj.name,
                 "error": e,
             })
    else:
        print_stdout(_("Domain '%s' started successfully.") % xmlobj.name)
        return dom


def update_changes(domain, devs, action, confirm):
    if action.is_add_device:
        msg_confirm = _("%(xml)s\n\nHotplug this device to the guest "
                        "'%(domain)s'?")
        msg_success = _("Device hotplug successful.")
        msg_fail = _("Error attempting device hotplug: %(error)s")
    elif action.is_remove_device:
        msg_confirm = _("%(xml)s\n\nHotunplug this device from the guest "
                        "'%(domain)s'?")
        msg_success = _("Device hotunplug successful.")
        msg_fail = _("Error attempting device hotunplug: %(error)s")
    elif action.is_edit:
        msg_confirm = _("%(xml)s\n\nUpdate this device for the guest "
                        "'%(domain)s'?")
        msg_success = _("Device update successful.")
        msg_fail = _("Error attempting device update: %(error)s")
    else:
        raise xmlutil.DevError(
                "update_changes() incorrectly called with action=%s" %
                action.action_name)

    for dev in devs:
        xml = dev.get_xml()

        if confirm:
            msg = msg_confirm % {
                "xml": xml,
                "domain": domain.name(),
            }
            if not prompt_yes_or_no(msg):
                continue

        if action.is_add_device:
            setup_device(dev)

        try:
            if action.is_add_device:
                domain.attachDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)
            elif action.is_remove_device:
                domain.detachDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)
            elif action.is_edit:
                domain.updateDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)
        except libvirt.libvirtError as e:
            if "VIRTXML_TESTSUITE_UPDATE_IGNORE_FAIL" not in os.environ:
                fail(msg_fail % {"error": e})

        print_stdout(msg_success)
        if confirm:
            print_stdout("")


def prepare_changes(orig_xmlobj, options, action, input_devs=None):
    """
    Perform requested XML edits locally, but don't submit them to libvirt.
    Optionally perform any XML printing per user request

    :returns: (list of device objects, altered xmlobj)
    """
    origxml = orig_xmlobj.get_xml()
    xmlobj = orig_xmlobj.__class__(conn=orig_xmlobj.conn, parsexml=origxml)

    devs = perform_action(action, xmlobj, options, input_devs)
    newxml = xmlobj.get_xml()
    diff = get_diff(origxml, newxml)

    if not diff:
        log.warning(_("No XML diff was generated. The requested "
            "changes will have no effect."))

    if options.print_diff:
        if diff:
            print_stdout(diff)
    elif options.print_xml:
        print_stdout(newxml)

    return devs, xmlobj


#######################
# CLI option handling #
#######################

def parse_args():
    parser = cli.setupParser(
        "%(prog)s [options]",
        _("Edit libvirt XML using command line options."),
        introspection_epilog=True)

    cli.add_connect_option(parser, "virt-xml")

    parser.add_argument("domain", nargs='?',
        help=_("Domain name, id, or uuid"))

    actg = parser.add_argument_group(_("XML actions"))
    actg.add_argument("--edit", nargs='?', default=-1,
        help=_("Edit VM XML. Examples:\n"
        "--edit --disk ...     (edit first disk device)\n"
        "--edit 2 --disk ...   (edit second disk device)\n"
        "--edit all --disk ... (edit all disk devices)\n"
        "--edit target=hda --disk ... (edit disk 'hda')\n"))
    actg.add_argument("--remove-device", action="store_true",
        help=_("Remove specified device. Examples:\n"
        "--remove-device --disk 1 (remove first disk)\n"
        "--remove-device --disk all (remove all disks)\n"
        "--remove-device --disk /some/path"))
    actg.add_argument("--add-device", action="store_true",
        help=_("Add specified device. Example:\n"
        "--add-device --disk ..."))
    actg.add_argument("--build-xml", action="store_true",
        help=_("Output built device XML. Domain is optional but "
               "recommended to ensure optimal defaults."))

    outg = parser.add_argument_group(_("Output options"))
    outg.add_argument("--update", action="store_true",
        help=_("Apply changes to the running VM.\n"
               "With --add-device, this is a hotplug operation.\n"
               "With --remove-device, this is a hotunplug operation.\n"
               "With --edit, this is an update device operation."))
    define_g = outg.add_mutually_exclusive_group()
    define_g.add_argument("--define", action="store_true",
                          help=_("Force defining the domain. Only required if a --print "
                                 "option was specified."))
    define_g.add_argument("--no-define", dest='define', action="store_false",
                          help=_("Force not defining the domain."))
    define_g.set_defaults(define=None)
    outg.add_argument("--start", action="store_true",
                      help=_("Start the domain."))
    outg.add_argument("--print-diff", action="store_true",
        help=_("Only print the requested change, in diff format"))
    outg.add_argument("--print-xml", action="store_true",
        help=_("Only print the requested change, in full XML format"))
    outg.add_argument("--confirm", action="store_true",
        help=_("Require confirmation before saving any results."))

    cli.add_os_variant_option(parser, virtinstall=False)

    conv = parser.add_argument_group(_("Conversion options"))
    cli.ParserConvertToQ35.register()
    conv.add_argument("--convert-to-q35", nargs="?",
        const=cli.VirtCLIParser.OPTSTR_EMPTY,
        help=_("Convert an existing VM from PC/i440FX to Q35."))

    cli.ParserConvertToVNC.register()
    conv.add_argument("--convert-to-vnc", nargs="?",
        const=cli.VirtCLIParser.OPTSTR_EMPTY,
        help=_("Convert an existing VM to use VNC graphics. "
               "This removes any remnants of Spice graphics."))

    g = parser.add_argument_group(_("XML options"))
    cli.add_disk_option(g, editexample=True)
    cli.add_net_option(g)
    cli.add_gfx_option(g)
    cli.add_metadata_option(g)
    cli.add_memory_option(g)
    cli.vcpu_cli_options(g, editexample=True)
    cli.add_xml_option(g)
    cli.add_guest_xml_options(g)
    cli.add_boot_options(g)
    cli.add_device_options(g)

    misc = parser.add_argument_group(_("Miscellaneous Options"))
    cli.add_misc_options(misc, prompt=False, printxml=False, dryrun=False)

    cli.autocomplete(parser)

    return parser.parse_args()


###################
# main() handling #
###################

def main(conn=None):
    cli.earlyLogging()
    options = parse_args()

    if (options.confirm or options.print_xml or
        options.print_diff or options.build_xml):
        options.quiet = False
    cli.setupLogging("virt-xml", options.debug, options.quiet)

    if cli.check_option_introspection(options):
        return 0
    if cli.check_osinfo_list(options):
        return 0

    options.stdinxml = None
    if not options.domain and not options.build_xml:
        if not sys.stdin.closed and not sys.stdin.isatty():
            if options.confirm:
                fail(_("Can't use --confirm with stdin input."))
            if options.update:
                fail(_("Can't use --update with stdin input."))
            options.stdinxml = sys.stdin.read()
        else:
            fail(_("A domain must be specified"))

    # Default to --define, unless:
    #  --no-define explicitly specified
    #  --print-* option is used
    #  XML input came from stdin
    if not options.print_xml and not options.print_diff:
        if options.stdinxml:
            if not options.define:
                options.print_xml = True
        else:
            if options.define is None:
                options.define = True
    if options.confirm and not options.print_xml:
        options.print_diff = True

    conn = cli.getConnection(options.connect, conn)
    action = parse_action(conn, options)

    domain = None
    active_xmlobj = None
    inactive_xmlobj = None
    if options.domain:
        domain, inactive_xmlobj, active_xmlobj = cli.get_domain_and_guest(
            conn, options.domain)
    else:
        inactive_xmlobj = Guest(conn, parsexml=options.stdinxml)
    vm_is_running = bool(active_xmlobj)

    if action.is_build_xml:
        built_devs = action_build_xml(action, inactive_xmlobj)
        for dev in built_devs:
            # pylint: disable=no-member
            print_stdout(xmlutil.unindent_device_xml(dev.get_xml()))
        return 0

    input_devs = None
    performed_update = False
    if options.update:
        if options.update and options.start:
            fail_conflicting("--update", "--start")
        if vm_is_running:
            input_devs, dummy = prepare_changes(
                    active_xmlobj, options, action)
            update_changes(domain, input_devs, action, options.confirm)
            performed_update = True
        else:
            log.warning(
                _("The VM is not running, --update is inapplicable."))
        if not options.define:
            # --update and --no-define passed, so we are done
            return 0

    original_xml = inactive_xmlobj.get_xml()
    devs, xmlobj_to_define = prepare_changes(
            inactive_xmlobj, options, action, input_devs=input_devs)
    if not options.define:
        if options.start:
            start_domain_transient(conn, xmlobj_to_define, devs,
                                   action, options.confirm)
        return 0

    dom = define_changes(conn, xmlobj_to_define,
                         devs, action, options.confirm)
    if not dom:
        # --confirm user said 'no'
        return 0

    if options.start:
        try:
            dom.create()
        except libvirt.libvirtError as e:  # pragma: no cover
            fail(_("Failed starting domain '%(domain)s': %(error)s") % {
                     "domain": inactive_xmlobj.name,
                     "error": e,
                 })
        print_stdout(_("Domain '%s' started successfully.") %
                     inactive_xmlobj.name)

    elif vm_is_running and not performed_update:
        print_stdout(
            _("Changes will take effect after the domain is fully powered off."))
    elif defined_xml_is_unchanged(conn, dom, original_xml):
        log.warning(_("XML did not change after domain define. You may "
            "have changed a value that libvirt is setting by default."))

    return 0


def runcli():  # pragma: no cover
    try:
        sys.exit(main())
    except SystemExit as sys_e:
        sys.exit(sys_e.code)
    except KeyboardInterrupt:
        log.debug("", exc_info=True)
        print_stderr(_("Aborted at user request"))
    except Exception as main_e:
        fail(main_e)

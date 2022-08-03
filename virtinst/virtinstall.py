# Copyright 2005-2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import argparse
import atexit
import os
import sys
import time
import select

import libvirt

import virtinst
from . import cli
from .cli import fail, fail_conflicting, print_stdout, print_stderr
from . import Network
from .guest import Guest
from .logger import log


##############################
# Validation utility helpers #
##############################

INSTALL_METHODS = "--location URL, --cdrom CD/ISO, --pxe, --import, --boot hd|cdrom|..."


def supports_pxe(guest):
    """
    Return False if we are pretty sure the config doesn't support PXE
    """
    for nic in guest.devices.interface:
        if nic.type == nic.TYPE_USER:
            continue
        if nic.type != nic.TYPE_VIRTUAL:
            return True

        try:
            netobj = nic.conn.networkLookupByName(nic.source)
            xmlobj = Network(nic.conn, parsexml=netobj.XMLDesc(0))
            return xmlobj.can_pxe()
        except Exception:  # pragma: no cover
            log.debug("Error checking if PXE supported", exc_info=True)
            return True

    return False


def check_cdrom_option_error(options):
    if options.cdrom_short and options.cdrom:
        fail_conflicting("-c", "--cdrom")

    if options.cdrom_short:
        if "://" in options.cdrom_short:
            fail(_("-c specified with what looks like a libvirt URI. "
                   "Did you mean to use --connect? If not, use --cdrom "
                   "instead"))
        options.cdrom = options.cdrom_short


#################################
# Back compat option conversion #
#################################

def convert_old_printxml(options):
    if options.xmlstep:
        options.xmlonly = options.xmlstep
        del(options.xmlstep)


def convert_old_sound(options):
    if not options.sound:
        return
    for idx, dummy in enumerate(options.sound):
        if options.sound[idx] is None:
            options.sound[idx] = "default"


def convert_old_init(options):
    if not options.init:
        return
    if not options.boot:
        options.boot = [""]
    options.boot[-1] += ",init=%s" % options.init
    log.debug("Converted old --init to --boot %s", options.boot[-1])


def _do_convert_old_disks(options):
    paths = virtinst.xmlutil.listify(options.file_paths)
    sizes = virtinst.xmlutil.listify(options.disksize)

    def padlist(l, padsize):
        l = virtinst.xmlutil.listify(l)
        l.extend((padsize - len(l)) * [None])
        return l

    disklist = padlist(paths, max(0, len(sizes)))
    sizelist = padlist(sizes, len(disklist))

    opts = []
    for idx, path in enumerate(disklist):
        optstr = ""
        if path:
            optstr += "path=%s" % path
        if sizelist[idx]:
            if optstr:
                optstr += ","
            optstr += "size=%s" % sizelist[idx]
        if options.sparse is False:
            if optstr:
                optstr += ","
            optstr += "sparse=no"
        log.debug("Converted to new style: --disk %s", optstr)
        opts.append(optstr)

    options.disk = opts


def convert_old_disks(options):
    if options.nodisks and (options.file_paths or
                            options.disk or
                            options.disksize):
        fail(_("Cannot specify storage and use --nodisks"))

    if ((options.file_paths or options.disksize or not options.sparse) and
        options.disk):
        fail(_("Cannot mix --file, --nonsparse, or --file-size with --disk "
               "options. Use --disk PATH[,size=SIZE][,sparse=yes|no]"))

    if not options.disk:
        if options.nodisks:
            options.disk = ["none"]
        else:
            _do_convert_old_disks(options)

    del(options.file_paths)
    del(options.disksize)
    del(options.sparse)
    del(options.nodisks)
    log.debug("Distilled --disk options: %s", options.disk)


def convert_old_os_options(options):
    if not options.old_os_type:
        return
    log.warning(
        _("--os-type is deprecated and does nothing. Please stop using it."))
    del(options.old_os_type)


def convert_old_memory(options):
    if options.memory:
        return
    if not options.oldmemory:
        return
    options.memory = str(options.oldmemory)


def convert_old_cpuset(options):
    if not options.cpuset:
        return

    newvcpus = options.vcpus or []
    newvcpus.append(",cpuset=%s" % options.cpuset)
    options.vcpus = newvcpus
    log.debug("Generated compat cpuset: --vcpus %s", options.vcpus[-1])


def convert_old_networks(options):
    if options.nonetworks:
        options.network = ["none"]

    macs = virtinst.xmlutil.listify(options.mac)
    networks = virtinst.xmlutil.listify(options.network)
    bridges = virtinst.xmlutil.listify(options.bridge)

    if bridges and networks:
        fail_conflicting("--bridge", "--network")

    if bridges:
        # Convert old --bridges to --networks
        networks = ["bridge:" + b for b in bridges]

    def padlist(l, padsize):
        l = virtinst.xmlutil.listify(l)
        l.extend((padsize - len(l)) * [None])
        return l

    # If a plain mac is specified, have it imply a default network
    networks = padlist(networks, max(len(macs), 1))
    macs = padlist(macs, len(networks))

    for idx, ignore in enumerate(networks):
        if networks[idx] is None:
            networks[idx] = "default"
        if macs[idx]:
            networks[idx] += ",mac=%s" % macs[idx]

        # Handle old format of bridge:foo instead of bridge=foo
        for prefix in ["network", "bridge"]:
            if networks[idx].startswith(prefix + ":"):
                networks[idx] = networks[idx].replace(prefix + ":",
                                                      prefix + "=")

    del(options.mac)
    del(options.bridge)
    del(options.nonetworks)

    options.network = networks
    log.debug("Distilled --network options: %s", options.network)


def convert_old_graphics(options):
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

    log.debug("--graphics compat generated: %s", optstr)
    options.graphics = [optstr]


def convert_old_features(options):
    if options.features:
        return

    opts = []
    if options.noacpi:
        opts.append("acpi=off")
    if options.noapic:
        opts.append("apic=off")
    if opts:
        options.features = [",".join(opts)]


def convert_wait_zero(options):
    # Historical back compat, --wait 0 is identical to --noautoconsole
    if options.wait == 0:
        log.warning("Treating --wait 0 as --noautoconsole")
        options.autoconsole = "none"
        options.wait = None


##################################
# Install media setup/validation #
##################################

def do_test_media_detection(conn, options):
    url = options.test_media_detection
    guest = virtinst.Guest(conn)
    if options.arch:
        guest.os.arch = options.arch
    if options.os_type:
        guest.os.os_type = options.os_type
    guest.set_capabilities_defaults()

    installer = virtinst.Installer(conn, location=url)
    print_stdout(installer.detect_distro(guest), do_force=True)


#############################
# General option validation #
#############################

def storage_specified(options, guest):
    if guest.os.is_container():
        return True
    return options.disk or options.filesystem


def memory_specified(guest):
    return guest.memory or guest.currentMemory or guest.cpu.cells


def validate_required_options(options, guest, installer):
    # Required config. Don't error right away if nothing is specified,
    # aggregate the errors to help first time users get it right
    msg = ""

    if not options.reinstall:
        if not memory_specified(guest):
            msg += "\n" + _("--memory amount in MiB is required")

        if not storage_specified(options, guest):
            msg += "\n" + (
                _("--disk storage must be specified (override with --disk none)"))

    if not guest.os.is_container() and not installer.options_specified():
        msg += "\n" + (
            _("An install method must be specified\n(%(methods)s)") %
            {"methods": INSTALL_METHODS})

    if msg:
        fail(msg)


def show_console_warnings(installer, autoconsole):
    if not installer.cdrom:
        return
    if not autoconsole.is_text():
        return
    log.warning(_("CDROM media does not print to the text console "
        "by default, so you likely will not see text install output. "
        "You might want to use --location.") + " " +
        _("See the man page for examples of "
          "using --location with CDROM media"))


def _show_memory_warnings(guest):
    if not guest.currentMemory:
        return

    res = guest.osinfo.get_recommended_resources()
    rammb = guest.currentMemory // 1024
    minram = (res.get_minimum_ram(guest.os.arch) or 0)
    if minram:
        if (minram // 1024) > guest.currentMemory:
            log.warning(_("Requested memory %(mem1)s MiB is less than the "
                "recommended %(mem2)s MiB for OS %(osname)s"),
                {"mem1": rammb, "mem2": minram // (1024 * 1024),
                 "osname": guest.osinfo.name})
    elif rammb < 17:
        log.warning(_("Requested memory %s MiB is abnormally low. "
            "Were you trying to specify GiB?"), rammb)


def _needs_accurate_osinfo(guest):
    # HVM is really the only case where OS impacts what we set for defaults,
    # so far.
    #
    # Historically we would only warn about missing osinfo on x86, but
    # with the change to make osinfo mandatory we relaxed the arch check,
    # so virt-install behavior is more consistent.
    return guest.os.is_hvm()


def show_guest_warnings(options, guest):
    if options.pxe and not supports_pxe(guest):
        log.warning(
            _("The guest's network configuration may not support PXE"))

    if guest.osinfo.is_generic() and _needs_accurate_osinfo(guest):
        log.warning(
            _("Using --osinfo {osname}, VM performance may suffer. "
              "Specify an accurate OS for optimal results.").format(
            osname=guest.osinfo.name))

    _show_memory_warnings(guest)


##########################
# Guest building helpers #
##########################

def get_location_for_os(guest, osname, profile=None):
    osinfo = virtinst.OSDB.lookup_os(osname, raise_error=True)
    location = osinfo.get_location(guest.os.arch, profile)
    print_stdout(_("Using {osname} --location {url}").format(
        osname=osname, url=location))
    return location


def build_installer(options, guest, installdata):
    cdrom = None
    location = None
    location_kernel = None
    location_initrd = None
    is_reinstall = bool(options.reinstall)
    unattended_data = None
    extra_args = options.extra_args

    install_bootdev = installdata.bootdev
    install_kernel = installdata.kernel
    install_initrd = installdata.initrd
    install_kernel_args = installdata.kernel_args
    install_os = installdata.os
    no_install = installdata.no_install
    if installdata.kernel_args:
        if installdata.kernel_args_overwrite:
            install_kernel_args = installdata.kernel_args
        else:
            extra_args = [installdata.kernel_args]

    if options.unattended:
        unattended_data = cli.parse_unattended(options.unattended)

    if install_os:
        profile = unattended_data.profile if unattended_data else None
        location = get_location_for_os(guest, install_os, profile)
    elif options.location:
        (location,
         location_kernel,
         location_initrd) = cli.parse_location(options.location)
    elif options.cdrom:
        cdrom = options.cdrom
        if options.livecd:
            no_install = True
    elif options.pxe:
        install_bootdev = "network"
    elif installdata.is_set:
        pass
    elif (options.import_install or
          options.xmlonly or
          options.boot or
          options.cloud_init or
          options.unattended):
        no_install = True

    installer = virtinst.Installer(guest.conn,
            cdrom=cdrom,
            location=location,
            location_kernel=location_kernel,
            location_initrd=location_initrd,
            install_bootdev=install_bootdev,
            install_kernel=install_kernel,
            install_initrd=install_initrd,
            install_kernel_args=install_kernel_args,
            no_install=no_install,
            is_reinstall=is_reinstall)

    if unattended_data:
        installer.set_unattended_data(unattended_data)
    if extra_args:
        installer.set_extra_args(extra_args)
    if options.initrd_inject:
        installer.set_initrd_injections(options.initrd_inject)
    if options.autostart:
        installer.autostart = True
    if options.cloud_init:
        cloudinit_data = cli.parse_cloud_init(options.cloud_init)
        installer.set_cloudinit_data(cloudinit_data)

    return installer


def set_cli_default_name(guest):
    if not guest.name:
        default_name = virtinst.Guest.generate_name(guest)
        cli.print_stdout(_("Using default --name {vm_name}").format(
            vm_name=default_name))
        guest.name = default_name


def set_cli_defaults(options, guest):
    if guest.os.is_container():
        if not memory_specified(guest):
            mbram = 1024
            # LXC doesn't even do anything with memory settings, but libvirt
            # XML requires it anyways. Fill in 64 MiB
            cli.print_stdout(
                _("Using container default --memory {megabytes}").format(
                megabytes=mbram))
            guest.currentMemory = mbram * 1024
        return

    if (options.unattended and
        guest.osinfo.is_windows() and
        guest.osinfo.supports_unattended_drivers(guest.os.arch)):
        guest.add_extra_drivers(
                guest.osinfo.get_pre_installable_devices(guest.os.arch))

    res = guest.osinfo.get_recommended_resources()
    storage = res.get_recommended_storage(guest.os.arch)
    ram = res.get_recommended_ram(guest.os.arch)
    ncpus = res.get_recommended_ncpus(guest.os.arch)

    if ram and not memory_specified(guest):
        mbram = str(ram / (1024 * 1024)).rstrip("0").rstrip(".")
        cli.print_stdout(
            _("Using {os_name} default --memory {megabytes}").format(
            os_name=guest.osinfo.name, megabytes=mbram))
        guest.currentMemory = ram // 1024

    if ncpus:
        # We need to do this upfront, so we don't incorrectly set guest.vcpus
        guest.sync_vcpus_topology(ncpus)

    if storage and not storage_specified(options, guest):
        diskstr = 'size=%d' % (storage // (1024 ** 3))
        cli.print_stdout(
            _("Using {os_name} default --disk {disk_options}".format(
            os_name=guest.osinfo.name, disk_options=diskstr)))
        options.disk = [diskstr]
        cli.ParserDisk(diskstr, guest=guest).parse(None)


def set_explicit_guest_options(options, guest):
    if options.name:
        guest.name = options.name
        options.name = None
    if options.uuid:
        guest.uuid = options.uuid
        options.uuid = None
    if options.description:
        guest.description = options.description
        options.description = None
    if options.os_type:
        guest.os.os_type = options.os_type
        options.os_type = None
    if options.virt_type:
        guest.type = options.virt_type
        options.virt_type = None
    if options.arch:
        guest.os.arch = options.arch
        options.arch = None
    if options.machine:
        guest.os.machine = options.machine
        options.machine = None


def installer_detect_distro(guest, installer, osdata):
    os_set = False
    try:
        # OS name has to be set firstly whenever --osinfo is passed,
        # otherwise it won't be respected when the installer creates the
        # Distro Store.
        if osdata.get_name():
            os_set = True
            guest.set_os_name(osdata.get_name())

        # This also validates the install location
        autodistro = installer.detect_distro(guest)
        if osdata.is_detect() and autodistro:
            os_set = True
            guest.set_os_name(autodistro)
    except ValueError as e:
        fail(_("Error validating install location: %s") % str(e))

    msg = _(
        "--os-variant/--osinfo OS name is required, but no value was\n"
        "set or detected.")
    if os_set:
        return
    if osdata.is_require_on():
        fail(msg)
    if not osdata.is_require_default():
        return

    if not _needs_accurate_osinfo(guest):
        return

    fail_msg = msg + "\n\n"
    fail_msg += _(
        "This is now a fatal error. Specifying an OS name is required\n"
        "for modern, performant, and secure virtual machine defaults.\n")

    detect_msg = _(
        "If you expected virt-install to detect an OS name from the\n"
        "install media, you can set a fallback OS name with:\n"
        "\n"
        "  --osinfo detect=on,name=OSNAME\n")
    possibly_detectable = bool(installer.location or installer.cdrom)
    if possibly_detectable:
        fail_msg += "\n" + detect_msg

    fail_msg += "\n" + _(
        "You can see a full list of possible OS name values with:\n"
        "\n"
        "   virt-install --osinfo list\n")

    generic_linux_names = [o.name for o in virtinst.OSDB.list_os() if
                           o.is_linux_generic()]
    generic_linux_msg = _(
        "If your Linux distro is not listed, try one of generic values\n"
        "such as: {oslist}\n").format(oslist=", ".join(generic_linux_names))
    if generic_linux_names:
        fail_msg += "\n" + generic_linux_msg

    envkey = "VIRTINSTALL_OSINFO_DISABLE_REQUIRE"
    fail_msg += "\n" + _(
        "If you just need to get the old behavior back, you can use:\n"
        "\n"
        "  --osinfo detect=on,require=off\n"
        "\n"
        "Or export {env_var}=1\n"
        ).format(env_var=envkey)

    fail_msg = "\n" + fail_msg
    if envkey in os.environ:
        log.warning(fail_msg)
        m = _("{env_var} set. Skipping fatal error.").format(env_var=envkey)
        log.warning(m)
    else:
        fail(fail_msg)


def _build_options_guest(conn, options):
    guest = Guest(conn)
    guest.skip_default_osinfo = True

    # Fill in guest from the command line content
    set_explicit_guest_options(options, guest)

    # We do these two parser bit early, since Installer setup will
    # depend on them, but delay the rest to later, since things like
    # disk naming can depend on Installer operations
    cli.run_parser(options, guest, cli.ParserBoot)
    options.boot = None
    cli.run_parser(options, guest, cli.ParserMetadata)
    options.metadata = None

    # Call set_capabilities_defaults explicitly here rather than depend
    # on set_defaults calling it. Installer setup needs filled in values.
    # However we want to do it after run_all_parsers to ensure
    # we are operating on any arch/os/type values passed in with --boot
    guest.set_capabilities_defaults()

    return guest


def build_guest_instance(conn, options):
    installdata = cli.parse_install(options.install)
    osdata = cli.parse_os_variant(options.os_variant or installdata.os)

    if options.reinstall:
        dummy1, guest, dummy2 = cli.get_domain_and_guest(conn, options.reinstall)
    else:
        guest = _build_options_guest(conn, options)

    installer = build_installer(options, guest, installdata)

    # Set guest osname, from commandline or detected from media
    guest.set_default_os_name()
    installer_detect_distro(guest, installer, osdata)

    if not options.reinstall:
        # We want to fill in --name before we do disk parsing, since
        # default disk paths are generated based on VM name
        set_cli_default_name(guest)
        cli.run_all_parsers(options, guest)
        cli.parse_xmlcli(guest, options)
        set_cli_defaults(options, guest)

    installer.set_install_defaults(guest)
    for path in installer.get_search_paths(guest):
        cli.check_path_search(guest.conn, path)

    if not options.reinstall:
        # cli specific disk validation
        for disk in guest.devices.disk:
            cli.validate_disk(disk)
        for net in guest.devices.interface:
            cli.validate_mac(net.conn, net.macaddr)

    validate_required_options(options, guest, installer)
    show_guest_warnings(options, guest)

    return guest, installer


###########################
# Install process helpers #
###########################

def _sleep(secs):
    if not virtinst.xmlutil.in_testsuite():
        time.sleep(secs)  # pragma: no cover


def _set_default_wait(autoconsole, options):
    if (options.wait is not None or
        autoconsole.has_console_cb() or
        not autoconsole.is_default()):
        return

    # If there isn't any console to actually connect up,
    # default to --wait -1 to get similarish behavior
    log.warning(_("No console to launch for the guest, "
        "defaulting to --wait -1"))
    options.wait = -1


class WaitHandler:
    """
    Helper class for handling the --wait option sleeping and time tracking
    """
    def __init__(self, wait):
        self.wait_is_requested = False
        self._wait_mins = 0
        self._start_time = 0

        if wait is not None:
            self.wait_is_requested = True
            self._wait_mins = wait

    @property
    def wait_for_console_to_exit(self):
        # If --wait specified, we don't want the default behavior of waiting
        # for virt-viewer to exit, we want to launch it, then manually count
        # down time for ourselves
        return not self.wait_is_requested
    @property
    def _wait_forever(self):
        return self._wait_mins < 0
    @property
    def _wait_secs(self):
        return self._wait_mins * 60

    def start(self):
        self._start_time = time.time()

    def get_time_string(self):
        if self._wait_forever:
            return _("Waiting for the installation to complete.")
        return ngettext("Waiting %(minutes)d minute for the installation to complete.",
                        "Waiting %(minutes)d minutes for the installation to complete.",
                        self._wait_mins) % {"minutes": self._wait_mins}

    def wait(self):
        """
        sleep 1 second, then teturn True if wait time has expired
        """
        _sleep(1)
        if self._wait_forever:
            if virtinst.xmlutil.in_testsuite():
                return True
            return False  # pragma: no cover

        time_elapsed = (time.time() - self._start_time)
        return (time_elapsed >= self._wait_secs) or virtinst.xmlutil.in_testsuite()


def _print_cloudinit_passwd(installer):
    passwd = installer.get_generated_password()
    if not passwd:
        return

    print_stdout(_("Password for first root login is: %s") % passwd,
            do_force=True, do_log=False)

    stdins = [sys.stdin]
    timeout = 10
    if sys.stdin.closed or not sys.stdin.isatty():
        if not virtinst.xmlutil.in_testsuite():  # pragma: no cover
            return
        stdins = []
        timeout = .0001

    sys.stdout.write(
        _("Installation will continue in 10 seconds "
          "(press Enter to skip)..."))
    sys.stdout.flush()

    select.select(stdins, [], [], timeout)


def _connect_console(guest, instdomain, autoconsole, wait):
    """
    Launched the passed console callback for the already defined
    domain. If domain isn't running, return an error.
    """
    console_cb = autoconsole.get_console_cb()
    if not console_cb:
        return

    child = console_cb(guest)
    if not wait:
        return

    # If we connected the console, wait for it to finish
    try:
        errcode = os.waitpid(child, 0)[1]
    except OSError as e:  # pragma: no cover
        log.debug("waitpid error: %s", e)

    if errcode:
        log.warning(_("Console command returned failure."))

    instdomain.handle_destroy_on_exit()


class _InstalledDomain:
    """
    Wrapper for the domain object after the initial install creation
    """
    def __init__(self, domain, transient, destroy_on_exit):
        self._domain = domain
        self._transient = transient
        self._destroy_on_exit = destroy_on_exit

        if destroy_on_exit:
            atexit.register(_destroy_on_exit, domain)

    def handle_destroy_on_exit(self):
        if self._destroy_on_exit and self._domain.isActive():
            log.debug("console exited and destroy_on_exit passed, destroying")
            self._domain.destroy()

    def domain_was_destroyed(self):
        try:
            state, reason = self._domain.state()
            return (state == libvirt.VIR_DOMAIN_SHUTOFF and
                    reason in [libvirt.VIR_DOMAIN_SHUTOFF_DESTROYED,
                               libvirt.VIR_DOMAIN_SHUTOFF_SAVED])
        except Exception:  # pragma: no cover
            log.debug("Error checking VM shutdown reason", exc_info=True)

    def check_inactive(self):
        try:
            dominfo = self._domain.info()
            state = dominfo[0]

            if state == libvirt.VIR_DOMAIN_CRASHED:
                fail(_("Domain has crashed."))  # pragma: no cover

            return not self._domain.isActive()
        except libvirt.libvirtError as e:
            if (self._transient and
                e.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN):
                log.debug("transient VM shutdown and disappeared.")
                return True
            raise  # pragma: no cover


def _wait_for_domain(installer, instdomain, autoconsole, waithandler):
    """
    Make sure domain ends up in expected state, and wait if for install
    to complete if requested
    """
    if instdomain.check_inactive():
        return

    if bool(autoconsole.get_console_cb()):
        # We are trying to detect if the VM shutdown, or the user
        # just closed the console and the VM is still running. In the
        # the former case, libvirt may not have caught up yet with the
        # VM having exited, so wait a bit and check again
        _sleep(2)
        if instdomain.check_inactive():
            return  # pragma: no cover

    # If we reach here, the VM still appears to be running.
    msg = "\n"
    msg += _("Domain is still running. Installation may be in progress.")

    if not waithandler.wait_is_requested:
        # User either:
        #   used --noautoconsole
        #   killed console and guest is still running
        if not installer.has_install_phase():
            return

        msg += "\n"
        msg += _("You can reconnect to the console to complete the "
                 "installation process.")
        print_stdout(msg)
        sys.exit(0)

    print_stdout(msg)
    print_stdout(waithandler.get_time_string())

    # Wait loop
    while True:
        if instdomain.check_inactive():  # pragma: no cover
            print_stdout(_("Domain has shutdown. Continuing."))
            break

        done = waithandler.wait()
        if done:
            print_stdout(
                _("Installation has exceeded specified time limit. "
                  "Exiting application."))
            sys.exit(1)


def _testsuite_hack_destroy(domain):
    # Trigger specific behavior checking if user destroyed the domain
    if os.environ.get("VIRTINST_TESTSUITE_HACK_DESTROY"):
        domain.destroy()


def _process_domain(domain, guest, installer, waithandler, autoconsole,
        transient, destroy_on_exit, noreboot):
    """
    Handle the pieces of the install process after the initial VM startup
    """
    instdomain = _InstalledDomain(domain, transient, destroy_on_exit)

    _connect_console(guest, instdomain, autoconsole,
            waithandler.wait_for_console_to_exit)

    _testsuite_hack_destroy(domain)
    _wait_for_domain(installer, instdomain, autoconsole, waithandler)
    print_stdout(_("Domain creation completed."))

    if transient:
        return
    if domain.isActive():
        return

    if noreboot or not installer.has_install_phase():
        print_stdout(  # pragma: no cover
            _("You can restart your domain by running:\n  %s") %
            cli.virsh_start_cmd(guest))
        return

    if instdomain.domain_was_destroyed() and not destroy_on_exit:
        print_stdout(_("User stopped the VM. Not rebooting."))
        return

    print_stdout(_("Restarting guest."))
    domain.create()
    _connect_console(guest, instdomain, autoconsole, True)


def start_install(guest, installer, options):
    """
    Process all the install workflow specific options, and kick off
    the Installer process
    """
    autoconsole = cli.parse_autoconsole(options, guest, installer)
    show_console_warnings(installer, autoconsole)
    _set_default_wait(autoconsole, options)
    waithandler = WaitHandler(options.wait)
    meter = cli.get_meter()

    # we've got everything -- try to start the install
    print_stdout(_("\nStarting install..."))
    _print_cloudinit_passwd(installer)
    waithandler.start()

    try:
        try:
            domain = installer.start_install(
                    guest, meter=meter,
                    doboot=not options.noreboot,
                    transient=options.transient)
        except:  # noqa
            virtinst.Installer.cleanup_created_disks(guest, meter)
            raise

        _process_domain(domain, guest, installer,
                waithandler, autoconsole, options.transient,
                options.destroy_on_exit, options.noreboot)

        if virtinst.xmlutil.in_testsuite() and options.destroy_on_exit:
            # Helps with unit testing
            _destroy_on_exit(domain)
    except KeyboardInterrupt:  # pragma: no cover
        log.debug("", exc_info=True)
        print_stderr(_("Domain install interrupted."))
        raise
    except Exception as e:
        fail(e, do_exit=False)
        cli.install_fail(guest)


########################
# XML printing helpers #
########################

def xml_to_print(guest, installer, xmlonly, dry):
    start_xml, final_xml = installer.start_install(
            guest, dry=dry, return_xml=True)
    if not start_xml:
        start_xml = final_xml
        final_xml = None

    if dry and not xmlonly:
        print_stdout(_("Dry run completed successfully"))
        return

    if xmlonly not in [False, "1", "2", "all"]:
        fail(_("Unknown XML step request '%s', must be 1, 2, or all") %
             xmlonly)

    if xmlonly == "1":
        return start_xml
    if xmlonly == "2":
        if not final_xml:
            fail(_("Requested installation does not have XML step 2"))
        return final_xml

    # "all" case
    xml = start_xml
    if final_xml:
        xml += final_xml
    return xml


#######################
# CLI option handling #
#######################

def parse_args():
    parser = cli.setupParser(
        "%(prog)s --name NAME --memory MB STORAGE INSTALL [options]",
        _("Create a new virtual machine from specified install media."),
        introspection_epilog=True)
    cli.add_connect_option(parser)

    geng = parser.add_argument_group(_("General Options"))
    geng.add_argument("-n", "--name",
                    help=_("Name of the guest instance"))
    cli.add_memory_option(geng, backcompat=True)
    cli.vcpu_cli_options(geng)
    cli.add_metadata_option(geng)
    cli.add_xml_option(geng)
    geng.add_argument("-u", "--uuid", help=argparse.SUPPRESS)
    geng.add_argument("--description", help=argparse.SUPPRESS)

    insg = parser.add_argument_group(_("Installation Method Options"))
    insg.add_argument("-c", dest="cdrom_short", help=argparse.SUPPRESS)
    insg.add_argument("--cdrom", help=_("CD-ROM installation media"))
    insg.add_argument("-l", "--location",
            help=_("Distro install URL, eg. https://host/path. See man "
                   "page for specific distro examples."))
    insg.add_argument("--pxe", action="store_true",
                    help=_("Boot from the network using the PXE protocol"))
    insg.add_argument("--import", action="store_true", dest="import_install",
                    help=_("Build guest around an existing disk image"))
    insg.add_argument("--livecd", action="store_true", help=argparse.SUPPRESS)
    insg.add_argument("-x", "--extra-args", action="append",
                    help=_("Additional arguments to pass to the install kernel "
                           "booted from --location"))
    insg.add_argument("--initrd-inject", action="append",
                    help=_("Add given file to root of initrd from --location"))
    insg.add_argument("--unattended", nargs="?", const=1,
                    help=_("Perform an unattended installation"))
    insg.add_argument("--install",
            help=_("Specify fine grained install options"))
    insg.add_argument("--reinstall", metavar="DOMAIN",
            help=_("Reinstall existing VM. Only install options are applied, "
                   "all other VM configuration options are ignored."))
    insg.add_argument("--cloud-init", nargs="?", const=1,
                    help=_("Perform a cloud image installation, configuring cloud-init"))

    # Takes a URL and just prints to stdout the detected distro name
    insg.add_argument("--test-media-detection", help=argparse.SUPPRESS)
    # Helper for cli testing, fills in standard stub options
    insg.add_argument("--test-stub-command", action="store_true",
            help=argparse.SUPPRESS)

    cli.add_boot_options(insg)
    insg.add_argument("--init", help=argparse.SUPPRESS)

    osg = cli.add_os_variant_option(parser, virtinstall=True)
    osg.add_argument("--os-type", dest="old_os_type", help=argparse.SUPPRESS)

    devg = parser.add_argument_group(_("Device Options"))
    cli.add_disk_option(devg)
    cli.add_net_option(devg)
    cli.add_gfx_option(devg)
    cli.add_device_options(devg, sound_back_compat=True)

    # Deprecated device options
    devg.add_argument("-f", "--file", dest="file_paths", action="append",
                    help=argparse.SUPPRESS)
    devg.add_argument("-s", "--file-size", type=float,
                    action="append", dest="disksize",
                    help=argparse.SUPPRESS)
    devg.add_argument("--nonsparse", action="store_false",
                    default=True, dest="sparse",
                    help=argparse.SUPPRESS)
    devg.add_argument("--nodisks", action="store_true", help=argparse.SUPPRESS)
    devg.add_argument("--nonetworks", action="store_true",
        help=argparse.SUPPRESS)
    devg.add_argument("-b", "--bridge", action="append",
        help=argparse.SUPPRESS)
    devg.add_argument("-m", "--mac", action="append", help=argparse.SUPPRESS)
    devg.add_argument("--vnc", action="store_true", help=argparse.SUPPRESS)
    devg.add_argument("--vncport", type=int, help=argparse.SUPPRESS)
    devg.add_argument("--vnclisten", help=argparse.SUPPRESS)
    devg.add_argument("-k", "--keymap", help=argparse.SUPPRESS)
    devg.add_argument("--sdl", action="store_true", help=argparse.SUPPRESS)
    devg.add_argument("--nographics", action="store_true",
        help=argparse.SUPPRESS)


    gxmlg = parser.add_argument_group(_("Guest Configuration Options"))
    cli.add_guest_xml_options(gxmlg)


    virg = parser.add_argument_group(_("Virtualization Platform Options"))
    ostypeg = virg.add_mutually_exclusive_group()
    ostypeg.add_argument("-v", "--hvm",
        action="store_const", const="hvm", dest="os_type",
        help=_("This guest should be a fully virtualized guest"))
    ostypeg.add_argument("-p", "--paravirt",
        action="store_const", const="xen", dest="os_type",
        help=_("This guest should be a paravirtualized guest"))
    ostypeg.add_argument("--container",
        action="store_const", const="exe", dest="os_type",
        help=_("This guest should be a container guest"))
    virg.add_argument("--virt-type",
        help=_("Hypervisor name to use (kvm, qemu, xen, ...)"))
    virg.add_argument("--arch", help=_("The CPU architecture to simulate"))
    virg.add_argument("--machine", help=_("The machine type to emulate"))
    virg.add_argument("--accelerate", action="store_true",
        help=argparse.SUPPRESS)
    virg.add_argument("--noapic", action="store_true",
        default=False, help=argparse.SUPPRESS)
    virg.add_argument("--noacpi", action="store_true",
        default=False, help=argparse.SUPPRESS)


    misc = parser.add_argument_group(_("Miscellaneous Options"))
    misc.add_argument("--autostart", action="store_true", default=False,
                      help=_("Have domain autostart on host boot up."))
    misc.add_argument("--transient", action="store_true", default=False,
                      help=_("Create a transient domain."))
    misc.add_argument("--destroy-on-exit", action="store_true", default=False,
                      help=_("Force power off the domain when the console "
                             "viewer is closed."))
    misc.add_argument("--wait", type=int, const=-1, nargs="?",
                      help=_("Minutes to wait for install to complete."))

    cli.add_misc_options(misc, prompt=True, printxml=True, printstep=True,
                         noreboot=True, dryrun=True, noautoconsole=True)

    cli.autocomplete(parser)

    return parser.parse_args()


###################
# main() handling #
###################

# Catchall for destroying the VM on ex. ctrl-c
def _destroy_on_exit(domain):
    try:
        isactive = bool(domain and domain.isActive())
        if isactive:
            domain.destroy()  # pragma: no cover
    except libvirt.libvirtError as e:  # pragma: no cover
        if e.get_error_code() != libvirt.VIR_ERR_NO_DOMAIN:
            log.debug("Error invoking atexit destroy_on_exit",
                    exc_info=True)


def set_test_stub_options(options):  # pragma: no cover
    # Set some basic options that will let virt-install succeed. Helps
    # save boiler plate typing when testing new command line additions
    if not options.test_stub_command:
        return

    options.import_install = True
    if not options.connect:
        options.connect = "test:///default"
    if not options.name:
        options.name = "test-stub-command"
    if not options.memory:
        options.memory = "256"
    if not options.disk:
        options.disk = "none"
    if not options.graphics:
        options.graphics = "none"
    if not options.os_variant:
        options.os_variant = "fedora27"


def main(conn=None):
    cli.earlyLogging()
    options = parse_args()

    # Default setup options
    convert_old_printxml(options)
    options.quiet = (options.xmlonly or
        options.test_media_detection or options.quiet)
    cli.setupLogging("virt-install", options.debug, options.quiet)

    if cli.check_option_introspection(options):
        return 0
    if cli.check_osinfo_list(options):
        return 0

    check_cdrom_option_error(options)
    cli.convert_old_force(options)
    cli.parse_check(options.check)
    cli.set_prompt(options.prompt)
    convert_old_memory(options)
    convert_old_sound(options)
    convert_old_networks(options)
    convert_old_graphics(options)
    convert_old_disks(options)
    convert_old_features(options)
    convert_old_cpuset(options)
    convert_old_init(options)
    convert_wait_zero(options)
    set_test_stub_options(options)
    convert_old_os_options(options)

    conn = cli.getConnection(options.connect, conn=conn)

    if options.test_media_detection:
        do_test_media_detection(conn, options)
        return 0

    guest, installer = build_guest_instance(conn, options)
    if options.xmlonly or options.dry:
        xml = xml_to_print(guest, installer, options.xmlonly, options.dry)
        if xml:
            print_stdout(xml, do_force=True)
    else:
        start_install(guest, installer, options)

    return 0


def runcli():  # pragma: no cover
    try:
        sys.exit(main())
    except SystemExit as sys_e:
        sys.exit(sys_e.code)
    except KeyboardInterrupt:
        log.debug("", exc_info=True)
        print_stderr(_("Installation aborted at user request"))
    except Exception as main_e:
        fail(main_e)

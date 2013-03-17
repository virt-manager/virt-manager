#!/usr/bin/env python

import glob
import os

from distutils.core import Command, setup
from distutils.command.install_egg_info import install_egg_info

from DistUtilsExtra.auto import sdist_auto
from DistUtilsExtra.command.build_i18n import build_i18n
from DistUtilsExtra.command.build_extra import build_extra
from DistUtilsExtra.command.build_icons import build_icons

from virtcli import cliconfig


class my_build_i18n(build_i18n):
    """
    Add our desktop files to the list, saves us having to track setup.cfg
    """
    def finalize_options(self):
        build_i18n.finalize_options(self)

        self.desktop_files = ('[("share/applications",' +
                              ' ("data/virt-manager.desktop.in", ))]')


class my_build(build_extra):
    """
    Create simple shell wrappers for /usr/bin/ tools to point to /usr/share
    Compile .pod file
    """

    def run(self):
        cmds = ["virt-manager"]
        if cliconfig.with_tui:
            cmds += ["virt-manager-tui"]

        for app in cmds:
            sharepath = os.path.join(cliconfig.asset_dir, app + ".py")

            wrapper = "#!/bin/sh\n\n"
            wrapper += "exec python \"%s\" \"$@\"" % (sharepath)
            file(app, "w").write(wrapper)

        os.system('pod2man --release="" --center="Virtual Machine Manager" '
                  '< ./man/virt-manager.pod > ./man/virt-manager.1')
        build_extra.run(self)


class my_build_icons(build_icons):
    """
    Fix up build_icon output to put or private icons in share/virt-manager
    """

    def run(self):
        data_files = self.distribution.data_files

        for size in glob.glob(os.path.join(self.icon_dir, "*")):
            for category in glob.glob(os.path.join(size, "*")):
                icons = []
                for icon in glob.glob(os.path.join(category,"*")):
                    if not os.path.islink(icon):
                        icons.append(icon)
                if not icons:
                    continue

                category = os.path.basename(category)
                dest = ("share/icons/hicolor/%s/%s" %
                        (os.path.basename(size), category))
                if category != "apps":
                    dest = dest.replace("share/", "share/virt-manager/")

                data_files.append((dest, icons))


class my_egg_info(install_egg_info):
    """
    Disable egg_info installation, seems pointless for a non-library
    """
    def run(self):
        pass


###################
# Custom commands #
###################

class my_rpm(Command):
    user_options = []
    description = "Build a non-binary rpm."

    def initialize_options(self):
        pass
    def finalize_options(self):
        pass

    def run(self):
        """
        Run sdist, then 'rpmbuild' the tar.gz
        """
        self.run_command('sdist')
        os.system('rpmbuild -ta dist/virt-manager-%s.tar.gz' %
                  cliconfig.__version__)


class configure(Command):
    user_options = [
        ("without-tui", None, "don't install virt-manager-tui"),
        ("qemu-user=", None,
         "user libvirt uses to launch qemu processes (default=root)"),
        ("libvirt-package-names=", None,
         "list of libvirt distro packages virt-manager will check for on "
         "first run. comma separated string (default=none)"),
        ("kvm-package-names=", None,
         "recommended kvm packages virt-manager will check for on first run "
         "(default=none)"),
        ("askpass-package-names=", None,
         "name of your distro's askpass package(s) (default=none)"),
        ("hide-unsupported-rhel-options", None,
         "Hide config bits that are not supported on RHEL (default=no)"),
        ("preferred-distros=", None,
         "Distros to list first in the New VM wizard (default=none)"),
        ("default-graphics=", None,
         "Default graphics type (spice or vnc) (default=vnc)"),

    ]
    description = "Configure the build, similar to ./configure"

    def finalize_options(self):
        pass

    def initialize_options(self):
        self.without_tui = 0
        self.qemu_user = "root"
        self.libvirt_package_names = ""
        self.kvm_package_names = ""
        self.askpass_package_names = ""
        self.hide_unsupported_rhel_options = 0
        self.preferred_distros = ""
        self.default_graphics = "vnc"


    def run(self):
        template = ""
        template += "[config]\n"
        template += "with_tui = %s\n" % int(not self.without_tui)
        template += "default_qemu_user = %s\n" % self.qemu_user
        template += "libvirt_packages = %s\n" % self.libvirt_package_names
        template += "hv_packages = %s\n" % self.kvm_package_names
        template += "askpass_packages = %s\n" % self.askpass_package_names
        template += "preferred_distros = %s\n" % self.preferred_distros
        template += ("hide_unsupported_rhel_options = %s\n" %
                     self.hide_unsupported_rhel_options)
        template += "default_graphics = %s\n" % self.default_graphics

        file(cliconfig.cfgpath, "w").write(template)
        print "Generated %s" % cliconfig.cfgpath


tui_files = [
    ("share/virt-manager/", ["virt-manager-tui.py"]),

    ("share/virt-manager/virtManagerTui",
     glob.glob("virtManagerTui/*.py")),
    ("share/virt-manager/virtManagerTui/importblacklist",
     glob.glob("virtManagerTui/importblacklist/*.py")),
]
if not cliconfig.with_tui:
    tui_files = []


setup(
    name = "virt-manager",
    version = cliconfig.__version__,
    # XXX: proper version, description, long_description, author, author_email
    url = "http://virt-manager.org",
    license = "GPLv2+",

    scripts = (["virt-manager"] +
               (cliconfig.with_tui and ["virt-manager-tui"] or [])),

    data_files = [
        ("share/virt-manager/", ["virt-manager.py"]),
        ("/etc/gconf/schemas", ["data/virt-manager.schemas"]),
        ("share/virt-manager/ui", glob.glob("ui/*.ui")),

        ("share/man/man1", ["man/virt-manager.1"]),

        ("share/virt-manager/virtManager", glob.glob("virtManager/*.py")),
    ] + tui_files,

    cmdclass = {
        'build': my_build,
        'build_i18n': my_build_i18n,
        'build_icons': my_build_icons,
        'sdist': sdist_auto,

        'install_egg_info': my_egg_info,

        'configure': configure,

        'rpm': my_rpm,
    }
)

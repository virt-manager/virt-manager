#!/usr/bin/env python

# pylint: disable=W0201
# Attribute defined outside __init__: custom commands require breaking this

import glob
import fnmatch
import os
import sys
import unittest

from distutils.core import Command, setup
from distutils.command.install import install
from distutils.command.install_egg_info import install_egg_info
from distutils.sysconfig import get_config_var
sysprefix = get_config_var("prefix")

from DistUtilsExtra.auto import sdist_auto
from DistUtilsExtra.command.build_i18n import build_i18n
from DistUtilsExtra.command.build_extra import build_extra
from DistUtilsExtra.command.build_icons import build_icons

from virtcli import cliconfig


def _generate_potfiles_in():
    def find(dirname, ext):
        ret = []
        for root, ignore, filenames in os.walk(dirname):
            for filename in fnmatch.filter(filenames, ext):
                ret.append(os.path.join(root, filename))
        ret.sort(key=lambda s: s.lower())
        return ret

    scripts = ["virt-manager", "virt-manager-tui", "virt-install",
               "virt-clone", "virt-image", "virt-convert"]

    potfiles = "\n".join(scripts) + "\n\n"
    potfiles += "\n".join(find("virtManager", "*.py")) + "\n\n"
    potfiles += "\n".join(find("virtManagerTui", "*.py")) + "\n\n"
    potfiles += "\n".join(find("virtcli", "*.py")) + "\n\n"
    potfiles += "\n".join(find("virtconv", "*.py")) + "\n\n"
    potfiles += "\n".join(find("virtinst", "*.py")) + "\n\n"

    potfiles += "\n".join(["[type: gettext/glade]" + f for
                          f in find("ui", "*.ui")])

    return potfiles


class my_build_i18n(build_i18n):
    """
    Add our desktop files to the list, saves us having to track setup.cfg
    """
    def finalize_options(self):
        build_i18n.finalize_options(self)

        self.desktop_files = ('[("share/applications",' +
                              ' ("data/virt-manager.desktop.in", ))]')

    def run(self):
        potfiles = _generate_potfiles_in()
        potpath = "po/POTFILES.in"

        try:
            print "Writing %s" % potpath
            file(potpath, "w").write(potfiles)
            build_i18n.run(self)
        finally:
            print "Removing %s" % potpath
            os.unlink(potpath)


class my_build(build_extra):
    """
    Create simple shell wrappers for /usr/bin/ tools to point to /usr/share
    Compile .pod file
    """

    def _make_bin_wrappers(self):
        cmds = ["virt-manager", "virt-install", "virt-clone",
                "virt-image", "virt-convert"]
        if cliconfig.with_tui:
            cmds += ["virt-manager-tui"]

        if not os.path.exists("build"):
            os.mkdir("build")

        for app in cmds:
            sharepath = os.path.join(cliconfig.install_asset_dir, app)

            wrapper = "#!/bin/sh\n\n"
            wrapper += "exec \"%s\" \"$@\"" % (sharepath)

            newpath = os.path.abspath(os.path.join("build", app))
            print "Generating %s" % newpath
            file(newpath, "w").write(wrapper)


    def _make_man_pages(self):
        for path in glob.glob("man/*.pod"):
            base = os.path.basename(path)

            mantype = "1"
            newbase = base
            if base == "virt-image-xml.pod":
                mantype = "5"
                newbase = "virt-image.pod"

            newpath = os.path.join(os.path.dirname(path),
                                os.path.splitext(newbase)[0] + "." + mantype)

            print "Generating %s" % newpath
            ret = os.system('pod2man --release="" '
                            '--center "Virtual Machine Manager" '
                            '< %s > %s' % (path, newpath))
            if ret != 0:
                raise RuntimeError("Generating '%s' failed." % newpath)

        if os.system("grep -IRq 'Hey!' man/") == 0:
            raise RuntimeError("man pages have errors in them! "
                               "(grep for 'Hey!')")


    def run(self):
        self._make_bin_wrappers()
        self._make_man_pages()

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
                for icon in glob.glob(os.path.join(category, "*")):
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


class my_install(install):
    """
    Error if we weren't 'configure'd with the correct install prefix
    """
    def finalize_options(self):
        if self.prefix is None:
            if cliconfig.prefix != sysprefix:
                print "Using prefix from 'configure': %s" % cliconfig.prefix
                self.prefix = cliconfig.prefix
        elif self.prefix != cliconfig.prefix:
            print ("Install prefix=%s doesn't match configure prefix=%s\n"
                   "Pass matching --prefix to 'setup.py configure'" %
                   (self.prefix, cliconfig.prefix))
            sys.exit(1)

        install.finalize_options(self)


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
        ("prefix=", None, "installation prefix"),
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
        self.prefix = sysprefix


    def run(self):
        template = ""
        template += "[config]\n"
        template += "prefix = %s\n" % self.prefix
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
    ("share/virt-manager/", ["virt-manager-tui"]),

    ("share/virt-manager/virtManagerTui",
     glob.glob("virtManagerTui/*.py")),
    ("share/virt-manager/virtManagerTui/importblacklist",
     glob.glob("virtManagerTui/importblacklist/*.py")),
]
if not cliconfig.with_tui:
    tui_files = []


class TestBaseCommand(Command):
    user_options = [('debug', 'd', 'Show debug output')]
    boolean_options = ['debug']

    def initialize_options(self):
        self.debug = 0
        self._testfiles = []
        self._dir = os.getcwd()

    def finalize_options(self):
        if self.debug and "DEBUG_TESTS" not in os.environ:
            os.environ["DEBUG_TESTS"] = "1"

    def run(self):
        try:
            # Use system 'coverage' if available
            import coverage
            use_coverage = True
        except:
            use_coverage = False

        tests = unittest.TestLoader().loadTestsFromNames(self._testfiles)
        t = unittest.TextTestRunner(verbosity=1)

        if use_coverage:
            coverage.erase()
            coverage.start()

        if hasattr(unittest, "installHandler"):
            try:
                unittest.installHandler()
            except:
                print "installHandler hack failed"

        try:
            result = t.run(tests)
        except KeyboardInterrupt:
            sys.exit(1)

        if use_coverage:
            coverage.stop()

        sys.exit(int(bool(len(result.failures) > 0 or
                          len(result.errors) > 0)))


class TestCommand(TestBaseCommand):
    description = "Runs a quick unit test suite"
    user_options = TestBaseCommand.user_options + \
                   [("testfile=", None, "Specific test file to run (e.g "
                                        "validation, storage, ...)"),
                    ("skipcli", None, "Skip CLI tests")]

    def initialize_options(self):
        TestBaseCommand.initialize_options(self)
        self.testfile = None
        self.skipcli = None

    def finalize_options(self):
        TestBaseCommand.finalize_options(self)

    def run(self):
        '''
        Finds all the tests modules in tests/, and runs them.
        '''
        testfiles = []
        for t in glob.glob(os.path.join(self._dir, 'tests', '*.py')):
            if (t.endswith("__init__.py") or
                t.endswith("urltest.py")):
                continue

            base = os.path.basename(t)
            if self.testfile:
                check = os.path.basename(self.testfile)
                if base != check and base != (check + ".py"):
                    continue
            if self.skipcli and base.count("clitest"):
                continue

            testfiles.append('.'.join(['tests', os.path.splitext(base)[0]]))

        if not testfiles:
            raise RuntimeError("--testfile didn't catch anything")

        self._testfiles = testfiles
        TestBaseCommand.run(self)


class TestURLFetch(TestBaseCommand):
    description = "Test fetching kernels and isos from various distro trees"

    user_options = TestBaseCommand.user_options + \
                   [("match=", None, "Regular expression of dist names to "
                                     "match [default: '.*']"),
                    ("path=", None, "Paths to local iso or directory or check"
                                    " for installable distro. Comma separated")]

    def initialize_options(self):
        TestBaseCommand.initialize_options(self)
        self.match = None
        self.path = ""

    def finalize_options(self):
        TestBaseCommand.finalize_options(self)
        if self.match is None:
            self.match = ".*"

        origpath = str(self.path)
        if not origpath:
            self.path = []
        else:
            self.path = origpath.split(",")

    def run(self):
        import tests
        self._testfiles = ["tests.urltest"]
        tests.urltest.MATCH_FILTER = self.match
        if self.path:
            for p in self.path:
                tests.urltest.LOCAL_MEDIA.append(p)
        TestBaseCommand.run(self)


class CheckPylint(Command):
    user_options = []
    description = "Check code using pylint and pep8"

    def initialize_options(self):
        pass
    def finalize_options(self):
        pass

    def run(self):
        files = ["setup.py", "virt-install", "virt-clone", "virt-image",
                 "virt-convert", "virt-manager", "virt-manager-tui",
                 "virtcli", "virtinst", "virtconv", "virtManager",
                 "virtManagerTui", "tests"]

        output_format = sys.stdout.isatty() and "colorized" or "text"

        cmd = "pylint "
        cmd += "--output-format=%s " % output_format
        cmd += " ".join(files)
        os.system(cmd + " --rcfile tests/pylint.cfg")

        print "running pep8"
        cmd = "pep8 "
        cmd += "--exclude scriptimports "
        cmd += " ".join(files)
        os.system(cmd + " --config tests/pep8.cfg")


setup(
    name="virt-manager",
    version=cliconfig.__version__,
    author="Cole Robinson",
    author_email="virt-tools-list@redhat.com",
    url="http://virt-manager.org",
    license="GPLv2+",

    # These wrappers are generated in our custom build command
    scripts=([
        "build/virt-manager",
        "build/virt-clone",
        "build/virt-install",
        "build/virt-image",
        "build/virt-convert"] +
        (cliconfig.with_tui and ["build/virt-manager-tui"] or [])),

    data_files=[
        ("share/virt-manager/", [
            "virt-manager",
            "virt-install",
            "virt-clone",
            "virt-image",
            "virt-convert",
        ]),
        ("/etc/gconf/schemas", ["data/virt-manager.schemas"]),
        ("share/virt-manager/ui", glob.glob("ui/*.ui")),

        ("share/man/man1", [
            "man/virt-manager.1",
            "man/virt-install.1",
            "man/virt-clone.1",
            "man/virt-image.1",
            "man/virt-convert.1"
        ]),
        ("share/man/man5", ["man/virt-image.5"]),

        ("share/virt-manager/virtManager", glob.glob("virtManager/*.py")),

        ("share/virt-manager/virtcli",
         glob.glob("virtcli/*.py") + ["virtcli/cli.cfg"]),
        ("share/virt-manager/virtinst", glob.glob("virtinst/*.py")),
        ("share/virt-manager/virtconv", glob.glob("virtconv/*.py")),
        ("share/virt-manager/virtconv/parsers",
         glob.glob("virtconv/parsers/*.py")),
    ] + tui_files,

    cmdclass={
        'build': my_build,
        'build_i18n': my_build_i18n,
        'build_icons': my_build_icons,

        'sdist': sdist_auto,
        'install': my_install,
        'install_egg_info': my_egg_info,

        'configure': configure,

        'pylint': CheckPylint,
        'rpm': my_rpm,
        'test': TestCommand,
        'test_urls' : TestURLFetch,
    }
)

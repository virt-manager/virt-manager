#!/usr/bin/env python
# Copyright (C) 2013, 2014 Red Hat, Inc.

# pylint: disable=W0201
# Attribute defined outside __init__: custom commands require breaking this

import datetime
import glob
import fnmatch
import os
import sys
import unittest

from distutils.core import Command, setup
from distutils.command.build import build
from distutils.command.install import install
from distutils.command.install_egg_info import install_egg_info
from distutils.command.sdist import sdist
from distutils.sysconfig import get_config_var
sysprefix = get_config_var("prefix")

from virtcli import cliconfig


def _generate_potfiles_in():
    def find(dirname, ext):
        ret = []
        for root, ignore, filenames in os.walk(dirname):
            for filename in fnmatch.filter(filenames, ext):
                ret.append(os.path.join(root, filename))
        ret.sort(key=lambda s: s.lower())
        return ret

    scripts = ["virt-manager", "virt-install",
               "virt-clone", "virt-image", "virt-convert", "virt-xml"]

    potfiles = "\n".join(scripts) + "\n\n"
    potfiles += "\n".join(find("virtManager", "*.py")) + "\n\n"
    potfiles += "\n".join(find("virtcli", "*.py")) + "\n\n"
    potfiles += "\n".join(find("virtconv", "*.py")) + "\n\n"
    potfiles += "\n".join(find("virtinst", "*.py")) + "\n\n"

    potfiles += "\n".join(["[type: gettext/glade]" + f for
                          f in find("ui", "*.ui")])

    return potfiles


class my_build_i18n(build):
    """
    Add our desktop files to the list, saves us having to track setup.cfg
    """
    user_options = [
        ('merge-po', 'm', 'merge po files against template'),
    ]

    def initialize_options(self):
        self.merge_po = False
    def finalize_options(self):
        pass

    def run(self):
        potfiles = _generate_potfiles_in()
        potpath = "po/POTFILES.in"

        try:
            print "Writing %s" % potpath
            file(potpath, "w").write(potfiles)
            self._run()
        finally:
            print "Removing %s" % potpath
            os.unlink(potpath)

    def _run(self):
        # Borrowed from python-distutils-extra
        desktop_files = [
            ("share/applications", ["data/virt-manager.desktop.in"]),
            ("share/appdata", ["data/virt-manager.appdata.xml"]),
        ]
        po_dir = "po"


        # Update po(t) files and print a report
        # We have to change the working dir to the po dir for intltool
        cmd = ["intltool-update",
               (self.merge_po and "-r" or "-p"), "-g", "virt-manager"]

        wd = os.getcwd()
        os.chdir("po")
        self.spawn(cmd)
        os.chdir(wd)
        max_po_mtime = 0
        for po_file in glob.glob("%s/*.po" % po_dir):
            lang = os.path.basename(po_file[:-3])
            mo_dir = os.path.join("build", "mo", lang, "LC_MESSAGES")
            mo_file = os.path.join(mo_dir, "virt-manager.mo")
            if not os.path.exists(mo_dir):
                os.makedirs(mo_dir)

            cmd = ["msgfmt", po_file, "-o", mo_file]
            po_mtime = os.path.getmtime(po_file)
            mo_mtime = (os.path.exists(mo_file) and
                        os.path.getmtime(mo_file)) or 0
            if po_mtime > max_po_mtime:
                max_po_mtime = po_mtime
            if po_mtime > mo_mtime:
                self.spawn(cmd)

            targetpath = os.path.join("share/locale", lang, "LC_MESSAGES")
            self.distribution.data_files.append((targetpath, (mo_file,)))

        # merge .in with translation
        for (file_set, switch) in [(desktop_files, "-d")]:
            for (target, files) in file_set:
                build_target = os.path.join("build", target)
                if not os.path.exists(build_target):
                    os.makedirs(build_target)

                files_merged = []
                for f in files:
                    if f.endswith(".in"):
                        file_merged = os.path.basename(f[:-3])
                    else:
                        file_merged = os.path.basename(f)

                    file_merged = os.path.join(build_target, file_merged)
                    cmd = ["intltool-merge", switch, po_dir, f,
                           file_merged]
                    mtime_merged = (os.path.exists(file_merged) and
                                    os.path.getmtime(file_merged)) or 0
                    mtime_file = os.path.getmtime(f)
                    if (mtime_merged < max_po_mtime or
                        mtime_merged < mtime_file):
                        # Only build if output is older than input (.po,.in)
                        self.spawn(cmd)
                    files_merged.append(file_merged)
                self.distribution.data_files.append((target, files_merged))


class my_build(build):
    """
    Create simple shell wrappers for /usr/bin/ tools to point to /usr/share
    Compile .pod file
    """

    def _make_bin_wrappers(self):
        cmds = ["virt-manager", "virt-install", "virt-clone",
                "virt-image", "virt-convert", "virt-xml"]

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

            appname = os.path.splitext(newbase)[0]
            newpath = os.path.join(os.path.dirname(path),
                                   appname + "." + mantype)

            print "Generating %s" % newpath
            ret = os.system('pod2man '
                            '--center "Virtual Machine Manager" '
                            '--release %s --name %s '
                            '< %s > %s' % (cliconfig.__version__,
                                           appname.upper(),
                                           path, newpath))
            if ret != 0:
                raise RuntimeError("Generating '%s' failed." % newpath)

        if os.system("grep -IRq 'Hey!' man/") == 0:
            raise RuntimeError("man pages have errors in them! "
                               "(grep for 'Hey!')")

    def _build_icons(self):
        for size in glob.glob(os.path.join("data/icons", "*")):
            for category in glob.glob(os.path.join(size, "*")):
                icons = []
                for icon in glob.glob(os.path.join(category, "*")):
                    icons.append(icon)
                if not icons:
                    continue

                category = os.path.basename(category)
                dest = ("share/icons/hicolor/%s/%s" %
                        (os.path.basename(size), category))
                if category != "apps":
                    dest = dest.replace("share/", "share/virt-manager/")

                self.distribution.data_files.append((dest, icons))


    def run(self):
        self._make_bin_wrappers()
        self._make_man_pages()
        self._build_icons()

        self.run_command("build_i18n")
        build.run(self)


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


class my_sdist(sdist):
    user_options = sdist.user_options + [
        ("snapshot", "s", "add snapshot id to version"),
    ]

    description = "Update virt-manager.spec; build sdist-tarball."

    def initialize_options(self):
        self.snapshot = None
        sdist.initialize_options(self)

    def finalize_options(self):
        if self.snapshot is not None:
            self.snapshot = 1
            cliconfig.__snapshot__ = 1
        sdist.finalize_options(self)

    def run(self):
        # Note: cliconfig.__snapshot__ by default is 0, it can be set to 1 by
        #       either sdist or rpm and then the snapshot suffix is appended.
        ver = cliconfig.__version__
        if cliconfig.__snapshot__ == 1:
            ver = ver + '.' + datetime.date.today().isoformat().replace('-', '')
        cliconfig.__version__ = ver

        setattr(self.distribution.metadata, 'version', ver)
        f1 = open('virt-manager.spec.in', 'r')
        f2 = open('virt-manager.spec', 'w')
        for line in f1:
            f2.write(line.replace('@VERSION@', ver))
        f1.close()
        f2.close()

        sdist.run(self)


###################
# Custom commands #
###################

class my_rpm(Command):
    user_options = [("snapshot", "s", "add snapshot id to version")]

    description = "Build src and noarch rpms."

    def initialize_options(self):
        self.snapshot = None

    def finalize_options(self):
        if self.snapshot is not None:
            self.snapshot = 1
            cliconfig.__snapshot__ = 1

    def run(self):
        """
        Run sdist, then 'rpmbuild' the tar.gz
        """
        self.run_command('sdist')
        os.system('rpmbuild -ta --clean dist/virt-manager-%s.tar.gz' %
                  cliconfig.__version__)


class configure(Command):
    user_options = [
        ("prefix=", None, "installation prefix"),
        ("pkgversion=", None, "user specified version-id"),
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
        ("preferred-distros=", None,
         "Distros to list first in the New VM wizard (default=none)"),
        ("stable-defaults", None,
         "Hide config bits that are not considered stable (default=no)"),
        ("default-graphics=", None,
         "Default graphics type (spice or vnc) (default=spice)"),

    ]
    description = "Configure the build, similar to ./configure"

    def finalize_options(self):
        pass

    def initialize_options(self):
        self.prefix = sysprefix
        self.pkgversion = None
        self.qemu_user = None
        self.libvirt_package_names = None
        self.kvm_package_names = None
        self.askpass_package_names = None
        self.preferred_distros = None
        self.stable_defaults = None
        self.default_graphics = None


    def run(self):
        template = ""
        template += "[config]\n"
        template += "prefix = %s\n" % self.prefix
        if self.pkgversion is not None:
            template += "pkgversion = %s\n" % self.pkgversion
        if self.qemu_user is not None:
            template += "default_qemu_user = %s\n" % self.qemu_user
        if self.libvirt_package_names is not None:
            template += "libvirt_packages = %s\n" % self.libvirt_package_names
        if self.kvm_package_names is not None:
            template += "hv_packages = %s\n" % self.kvm_package_names
        if self.askpass_package_names is not None:
            template += "askpass_packages = %s\n" % self.askpass_package_names
        if self.preferred_distros is not None:
            template += "preferred_distros = %s\n" % self.preferred_distros
        if self.stable_defaults is not None:
            template += ("stable_defaults = %s\n" %
                         self.stable_defaults)
        if self.default_graphics is not None:
            template += "default_graphics = %s\n" % self.default_graphics

        file(cliconfig.cfgpath, "w").write(template)
        print "Generated %s" % cliconfig.cfgpath


class TestBaseCommand(Command):
    user_options = [
        ('debug', 'd', 'Show debug output'),
        ('coverage', 'c', 'Show coverage report'),
        ("only=", None,
         "Run only testcases whose name contains the passed string"),
    ]

    def initialize_options(self):
        self.debug = 0
        self.coverage = 0
        self.only = None
        self._testfiles = []
        self._dir = os.getcwd()

    def finalize_options(self):
        if self.debug and "DEBUG_TESTS" not in os.environ:
            os.environ["DEBUG_TESTS"] = "1"

    def run(self):
        try:
            import coverage
            use_cov = True
        except:
            use_cov = False
            cov = None

        if use_cov:
            omit = ["/usr/*", "/*/tests/*"]
            cov = coverage.coverage(omit=omit)
            cov.erase()
            cov.start()

        import tests as testsmodule
        testsmodule.cov = cov

        if hasattr(unittest, "installHandler"):
            try:
                unittest.installHandler()
            except:
                print "installHandler hack failed"

        tests = unittest.TestLoader().loadTestsFromNames(self._testfiles)
        if self.only:
            newtests = []
            for suite1 in tests:
                for suite2 in suite1:
                    for testcase in suite2:
                        if self.only in str(testcase):
                            newtests.append(testcase)

            if not newtests:
                print "--only didn't find any tests"
                sys.exit(1)
            tests = unittest.TestSuite(newtests)
            print "Running only:"
            for test in newtests:
                print "%s" % test
            print

        t = unittest.TextTestRunner(verbosity=1)

        try:
            result = t.run(tests)
        except KeyboardInterrupt:
            sys.exit(1)

        if use_cov:
            cov.stop()
            cov.save()

        err = int(bool(len(result.failures) > 0 or
                       len(result.errors) > 0))
        if not err and use_cov and self.coverage:
            cov.report(show_missing=False)
        sys.exit(err)



class TestCommand(TestBaseCommand):
    description = "Runs a quick unit test suite"
    user_options = TestBaseCommand.user_options + [
        ("testfile=", None, "Specific test file to run (e.g "
                            "validation, storage, ...)"),
        ("skipcli", None, "Skip CLI tests"),
    ]

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
                t.endswith("test_urls.py") or
                t.endswith("test_inject.py")):
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

    user_options = TestBaseCommand.user_options + [
        ("path=", None, "Paths to local iso or directory or check"
                        " for installable distro. Comma separated"),
    ]

    def initialize_options(self):
        TestBaseCommand.initialize_options(self)
        self.path = ""

    def finalize_options(self):
        TestBaseCommand.finalize_options(self)
        origpath = str(self.path)
        if not origpath:
            self.path = []
        else:
            self.path = origpath.split(",")

    def run(self):
        self._testfiles = ["tests.test_urls"]
        if self.path:
            import tests
            tests.URLTEST_LOCAL_MEDIA += self.path
        TestBaseCommand.run(self)


class TestInitrdInject(TestBaseCommand):
    description = "Test initrd inject with real kernels, fetched from URLs"

    user_options = TestBaseCommand.user_options + [
        ("distro=", None, "Comma separated list of distros to test, from "
                          "the tests internal URL dictionary.")
    ]

    def initialize_options(self):
        TestBaseCommand.initialize_options(self)
        self.distro = ""

    def finalize_options(self):
        TestBaseCommand.finalize_options(self)
        orig = str(self.distro)
        if not orig:
            self.distro = []
        else:
            self.distro = orig.split(",")

    def run(self):
        self._testfiles = ["tests.test_inject"]
        if self.distro:
            import tests
            tests.INITRD_TEST_DISTROS += self.distro
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
                 "virt-convert", "virt-xml", "virt-manager",
                 "virtcli", "virtinst", "virtconv", "virtManager",
                 "tests"]

        output_format = sys.stdout.isatty() and "colorized" or "text"

        cmd = "pylint "
        cmd += "--output-format=%s " % output_format
        cmd += " ".join(files)
        os.system(cmd + " --rcfile tests/pylint.cfg")

        print "running pep8"
        cmd = "pep8 "
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
        "build/virt-convert",
        "build/virt-xml"]),

    data_files=[
        ("share/virt-manager/", [
            "virt-manager",
            "virt-install",
            "virt-clone",
            "virt-image",
            "virt-convert",
            "virt-xml",
        ]),
        ("share/glib-2.0/schemas",
         ["data/org.virt-manager.virt-manager.gschema.xml"]),
        ("share/virt-manager/ui", glob.glob("ui/*.ui")),

        ("share/man/man1", [
            "man/virt-manager.1",
            "man/virt-install.1",
            "man/virt-clone.1",
            "man/virt-image.1",
            "man/virt-convert.1",
            "man/virt-xml.1"
        ]),
        ("share/man/man5", ["man/virt-image.5"]),

        ("share/virt-manager/virtManager", glob.glob("virtManager/*.py")),

        ("share/virt-manager/virtcli",
         glob.glob("virtcli/*.py") + glob.glob("virtcli/cli.cfg")),
        ("share/virt-manager/virtinst", glob.glob("virtinst/*.py")),
        ("share/virt-manager/virtconv", glob.glob("virtconv/*.py")),
        ("share/virt-manager/virtconv/parsers",
         glob.glob("virtconv/parsers/*.py")),
    ],

    cmdclass={
        'build': my_build,
        'build_i18n': my_build_i18n,

        'sdist': my_sdist,
        'install': my_install,
        'install_egg_info': my_egg_info,

        'configure': configure,

        'pylint': CheckPylint,
        'rpm': my_rpm,
        'test': TestCommand,
        'test_urls' : TestURLFetch,
        'test_initrd_inject' : TestInitrdInject,
    }
)

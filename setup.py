#!/usr/bin/env python3
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.


import sys
if sys.version_info.major < 3:
    print("virt-manager is python3 only. Run this as ./setup.py")
    sys.exit(1)

import glob
import fnmatch
import os
import unittest

import distutils
import distutils.command.build
import distutils.command.install
import distutils.command.install_data
import distutils.command.install_egg_info
import distutils.command.sdist
import distutils.dist
import distutils.log
import distutils.sysconfig


sysprefix = distutils.sysconfig.get_config_var("prefix")


def _import_buildconfig():
    # A bit of crazyness to import the buildconfig file without importing
    # the rest of virtinst, so the build process doesn't require all the
    # runtime deps to be installed
    import warnings

    # 'imp' is deprecated. We use it elsewhere though too. Deal with using
    # the modern replacement when we replace all usage
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        import imp
        buildconfig = imp.load_source('buildconfig', 'virtinst/buildconfig.py')
        if "libvirt" in sys.modules:
            raise RuntimeError("Found libvirt in sys.modules. setup.py should "
                    "not import virtinst.")
        return buildconfig.BuildConfig


BuildConfig = _import_buildconfig()


# pylint: disable=attribute-defined-outside-init

_desktop_files = [
    ("share/applications", ["data/virt-manager.desktop.in"]),
]
_appdata_files = [
    ("share/appdata", ["data/virt-manager.appdata.xml.in"]),
]


def _generate_potfiles_in():
    def find(dirname, ext):
        ret = []
        for root, ignore, filenames in os.walk(dirname):
            for filename in fnmatch.filter(filenames, ext):
                ret.append(os.path.join(root, filename))
        ret.sort(key=lambda s: s.lower())
        return ret

    scripts = ["virt-manager", "virt-install",
               "virt-clone", "virt-convert", "virt-xml"]

    potfiles = "\n".join(scripts) + "\n\n"
    potfiles += "\n".join(find("virtManager", "*.py")) + "\n\n"
    potfiles += "\n".join(find("virtconv", "*.py")) + "\n\n"
    potfiles += "\n".join(find("virtinst", "*.py")) + "\n\n"

    for ignore, filelist in _desktop_files + _appdata_files:
        potfiles += "\n".join(filelist) + "\n"
    potfiles += "\n"

    potfiles += "\n".join(["[type: gettext/glade]" + f for
                          f in find("ui", "*.ui")]) + "\n\n"

    return potfiles


class my_build_i18n(distutils.command.build.build):
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
            print("Writing %s" % potpath)
            open(potpath, "w").write(potfiles)
            self._run()
        finally:
            print("Removing %s" % potpath)
            os.unlink(potpath)

    def _run(self):
        # Borrowed from python-distutils-extra
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
        for (file_set, switch) in [(_desktop_files, "-d"),
                                   (_appdata_files, "-x")]:
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


class my_build(distutils.command.build.build):
    """
    Create simple shell wrappers for /usr/bin/ tools to point to /usr/share
    Compile .pod file
    """

    def _make_bin_wrappers(self):
        cmds = ["virt-manager", "virt-install", "virt-clone",
                "virt-convert", "virt-xml"]
        if not os.path.exists("build"):
            os.mkdir("build")

        for app in cmds:
            sharepath = os.path.join(BuildConfig.prefix,
                "share", "virt-manager", app)

            wrapper = "#!/bin/sh\n\n"
            wrapper += "exec \"%s\" \"$@\"" % (sharepath)

            newpath = os.path.abspath(os.path.join("build", app))
            print("Generating %s" % newpath)
            open(newpath, "w").write(wrapper)


    def _make_man_pages(self):
        for path in glob.glob("man/*.pod"):
            base = os.path.basename(path)
            appname = os.path.splitext(base)[0]
            newpath = os.path.join(os.path.dirname(path),
                                   appname + ".1")

            print("Generating %s" % newpath)
            ret = os.system('pod2man '
                            '--center "Virtual Machine Manager" '
                            '--release %s --name %s '
                            '< %s > %s' % (BuildConfig.version,
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


    def _make_bash_completion_files(self):
        scripts = ["virt-install", "virt-clone", "virt-convert", "virt-xml"]
        srcfile = "data/bash-completion.sh.in"
        builddir = "build/bash-completion/"
        if not os.path.exists(builddir):
            os.makedirs(builddir)

        instpaths = []
        for script in scripts:
            genfile = os.path.join(builddir, script)
            print("Generating %s" % genfile)
            src = open(srcfile, "r")
            dst = open(genfile, "w")
            dst.write(src.read().replace("::SCRIPTNAME::", script))
            dst.close()
            instpaths.append(genfile)

        bashdir = "share/bash-completion/completions/"
        self.distribution.data_files.append((bashdir, instpaths))


    def run(self):
        self._make_bin_wrappers()
        self._make_man_pages()
        self._build_icons()
        self._make_bash_completion_files()

        self.run_command("build_i18n")
        distutils.command.build.build.run(self)


class my_egg_info(distutils.command.install_egg_info.install_egg_info):
    """
    Disable egg_info installation, seems pointless for a non-library
    """
    def run(self):
        pass


class my_install(distutils.command.install.install):
    """
    Error if we weren't 'configure'd with the correct install prefix
    """
    def finalize_options(self):
        if self.prefix is None:
            if BuildConfig.prefix != sysprefix:
                print("Using configured prefix=%s instead of sysprefix=%s" % (
                    BuildConfig.prefix, sysprefix))
                self.prefix = BuildConfig.prefix
            else:
                print("Using sysprefix=%s" % sysprefix)
                self.prefix = sysprefix

        elif self.prefix != BuildConfig.prefix:
            print("Install prefix=%s doesn't match configure prefix=%s\n"
                  "Pass matching --prefix to 'setup.py configure'" %
                  (self.prefix, BuildConfig.prefix))
            sys.exit(1)

        distutils.command.install.install.finalize_options(self)


class my_install_data(distutils.command.install_data.install_data):
    def run(self):
        distutils.command.install_data.install_data.run(self)

        if not self.distribution.no_update_icon_cache:
            distutils.log.info("running gtk-update-icon-cache")
            icon_path = os.path.join(self.install_dir, "share/icons/hicolor")
            self.spawn(["gtk-update-icon-cache", "-q", "-t", icon_path])

        if not self.distribution.no_compile_schemas:
            distutils.log.info("compiling gsettings schemas")
            gschema_install = os.path.join(self.install_dir,
                "share/glib-2.0/schemas")
            self.spawn(["glib-compile-schemas", gschema_install])


class my_sdist(distutils.command.sdist.sdist):
    description = "Update virt-manager.spec; build sdist-tarball."

    def run(self):
        f1 = open('virt-manager.spec.in', 'r')
        f2 = open('virt-manager.spec', 'w')
        for line in f1:
            f2.write(line.replace('@VERSION@', BuildConfig.version))
        f1.close()
        f2.close()

        distutils.command.sdist.sdist.run(self)


###################
# Custom commands #
###################

class my_rpm(distutils.core.Command):
    user_options = []
    description = "Build src and noarch rpms."

    def initialize_options(self):
        pass
    def finalize_options(self):
        pass

    def run(self):
        """
        Run sdist, then 'rpmbuild' the tar.gz
        """
        self.run_command('sdist')
        os.system('rpmbuild -ta --clean dist/virt-manager-%s.tar.gz' %
                  BuildConfig.version)


class configure(distutils.core.Command):
    user_options = [
        ("prefix=", None, "installation prefix"),
        ("default-graphics=", None,
         "Default graphics type (spice or vnc) (default=spice)"),
        ("default-hvs=", None,
         "Comma separated list of hypervisors shown in 'Open Connection' "
         "wizard. (default=all hvs)"),

    ]
    description = "Configure the build, similar to ./configure"

    def finalize_options(self):
        pass

    def initialize_options(self):
        self.prefix = sysprefix
        self.default_graphics = None
        self.default_hvs = None


    def run(self):
        template = ""
        template += "[config]\n"
        template += "prefix = %s\n" % self.prefix
        if self.default_graphics is not None:
            template += "default_graphics = %s\n" % self.default_graphics
        if self.default_hvs is not None:
            template += "default_hvs = %s\n" % self.default_hvs

        open(BuildConfig.cfgpath, "w").write(template)
        print("Generated %s" % BuildConfig.cfgpath)


class TestBaseCommand(distutils.core.Command):
    user_options = [
        ('debug', 'd', 'Show debug output'),
        ('testverbose', None, 'Show verbose output'),
        ('coverage', 'c', 'Show coverage report'),
        ('regenerate-output', None, 'Regenerate test output'),
        ("only=", None,
         "Run only testcases whose name contains the passed string"),
        ("testfile=", None, "Specific test file to run (e.g "
                            "validation, storage, ...)"),
    ]

    def initialize_options(self):
        self.debug = 0
        self.testverbose = 0
        self.regenerate_output = 0
        self.coverage = 0
        self.only = None
        self._testfiles = []
        self._clistate = {}
        self._dir = os.getcwd()
        self.testfile = None
        self._force_verbose = False
        self._external_coverage = False

    def finalize_options(self):
        if self.only:
            # Can do --only many-devices to match on the cli testcase
            # for "virt-install-many-devices", despite the actual test
            # function name not containing any '-'
            self.only = self.only.replace("-", "_")

    def _find_tests_in_dir(self, dirname, excludes):
        testfiles = []
        for t in sorted(glob.glob(os.path.join(self._dir, dirname, '*.py'))):
            base = os.path.basename(t)
            if base in excludes + ["__init__.py"]:
                continue

            if self.testfile:
                check = os.path.basename(self.testfile)
                if base != check and base != (check + ".py"):
                    continue

            testfiles.append('.'.join(
                dirname.split("/") + [os.path.splitext(base)[0]]))

        if not testfiles:
            raise RuntimeError("--testfile didn't catch anything")
        return testfiles

    def run(self):
        cov = None
        if self.coverage:
            import coverage
            omit = ["/usr/*", "/*/tests/*", "*progress.py"]
            cov = coverage.coverage(omit=omit)
            cov.erase()
            if not self._external_coverage:
                cov.start()

        import tests as testsmodule
        testsmodule.utils.clistate.regenerate_output = bool(
                self.regenerate_output)
        testsmodule.utils.clistate.use_coverage = bool(cov)
        testsmodule.utils.clistate.debug = bool(self.debug)
        for key, val in self._clistate.items():
            setattr(testsmodule.utils.clistate, key, val)
        testsmodule.setup_logging()
        testsmodule.setup_cli_imports()

        # This makes the test runner report results before exiting from ctrl-c
        unittest.installHandler()

        tests = unittest.TestLoader().loadTestsFromNames(self._testfiles)
        if self.only:
            newtests = []
            for suite1 in tests:
                for suite2 in suite1:
                    for testcase in suite2:
                        if self.only in str(testcase):
                            newtests.append(testcase)

            if not newtests:
                print("--only didn't find any tests")
                sys.exit(1)
            tests = unittest.TestSuite(newtests)
            print("Running only:")
            for test in newtests:
                print("%s" % test)
            print("")

        verbosity = 1
        if self.debug or self.testverbose or self._force_verbose:
            verbosity = 2
        t = unittest.TextTestRunner(verbosity=verbosity)

        try:
            result = t.run(tests)
        except KeyboardInterrupt:
            sys.exit(1)

        if cov:
            if self._external_coverage:
                cov.load()
            else:
                cov.stop()
                cov.save()

        err = int(bool(len(result.failures) > 0 or
                       len(result.errors) > 0))
        if cov and not err:
            cov.report(show_missing=False, skip_covered=True)
        sys.exit(err)



class TestCommand(TestBaseCommand):
    description = "Runs a quick unit test suite"

    def run(self):
        '''
        Finds all the tests modules in tests/, and runs them.
        '''
        excludes = ["dist.py", "test_urls.py", "test_inject.py"]
        testfiles = self._find_tests_in_dir("tests", excludes)

        # Put clitest at the end, since it takes the longest
        for f in testfiles[:]:
            if "clitest" in f:
                testfiles.remove(f)
                testfiles.append(f)

        # Always want to put checkprops at the end to get accurate results
        for f in testfiles[:]:
            if "checkprops" in f:
                testfiles.remove(f)
                if not self.testfile:
                    testfiles.append(f)

        self._testfiles = testfiles
        TestBaseCommand.run(self)


class TestUI(TestBaseCommand):
    description = "Run UI dogtails tests"

    def run(self):
        self._testfiles = self._find_tests_in_dir("tests/uitests", [])
        self._force_verbose = True
        self._external_coverage = True
        TestBaseCommand.run(self)


class TestURLFetch(TestBaseCommand):
    description = "Test fetching kernels and isos from various distro trees"
    user_options = TestBaseCommand.user_options + [
        ('skip-libosinfo', None,
            "Don't use libosinfo for media/tree detection, "
            "Use our internal detection logic."),
        ('force-libosinfo', None,
            "Only use libosinfo for media/tree detection. This will skip "
            "some cases that are known not to work, like debian/ubuntu "
            "tree detection."),
        ('iso-only', None, "Only run iso tests"),
        ('url-only', None, "Only run url tests"),
    ]

    def initialize_options(self):
        TestBaseCommand.initialize_options(self)
        self.skip_libosinfo = 0
        self.force_libosinfo = 0
        self.iso_only = 0
        self.url_only = 0

    def finalize_options(self):
        TestBaseCommand.finalize_options(self)

    def run(self):
        self._testfiles = ["tests.test_urls"]
        self._clistate = {
            "url_iso_only": bool(self.iso_only),
            "url_only": bool(self.url_only),
            "url_skip_libosinfo": bool(self.skip_libosinfo),
            "url_force_libosinfo": bool(self.force_libosinfo),
        }
        TestBaseCommand.run(self)


class TestInitrdInject(TestBaseCommand):
    description = "Test initrd inject with real kernels, fetched from URLs"

    def run(self):
        self._testfiles = ["tests.test_inject"]
        TestBaseCommand.run(self)


class TestDist(TestBaseCommand):
    description = "Tests to run before cutting a release"

    def run(self):
        self._testfiles = ["tests.dist"]
        TestBaseCommand.run(self)


class CheckPylint(distutils.core.Command):
    user_options = [
        ("jobs=", "j", "use multiple processes to speed up Pylint"),
    ]
    description = "Check code using pylint and pycodestyle"

    def initialize_options(self):
        self.jobs = None

    def finalize_options(self):
        if self.jobs:
            self.jobs = int(self.jobs)

    def run(self):
        import pylint.lint
        import pycodestyle

        files = ["setup.py", "virt-install", "virt-clone",
                 "virt-convert", "virt-xml", "virt-manager",
                 "virtinst", "virtconv", "virtManager",
                 "tests"]

        try:
            import codespell_lib
            # pylint: disable=protected-access
            print("running codespell")
            codespell_lib._codespell.main(
                '-I', 'tests/codespell_dict.txt',
                '--skip', '*.pyc,*.zip,*.vmdk,*.iso,*.xml', *files)
        except ImportError:
            print("codespell is not installed. skipping...")
        except Exception as e:
            print("Error running codespell: %s" % e)

        output_format = sys.stdout.isatty() and "colorized" or "text"

        print("running pycodestyle")
        style_guide = pycodestyle.StyleGuide(
            config_file='setup.cfg',
            format="pylint",
            paths=files
        )
        report = style_guide.check_files()
        if style_guide.options.count:
            sys.stderr.write(str(report.total_errors) + '\n')

        print("running pylint")
        pylint_opts = [
            "--rcfile", "pylintrc",
            "--output-format=%s" % output_format,
        ]
        if self.jobs:
            pylint_opts += ["--jobs=%d" % self.jobs]

        pylint.lint.Run(files + pylint_opts)


class VMMDistribution(distutils.dist.Distribution):
    global_options = distutils.dist.Distribution.global_options + [
        ("no-update-icon-cache", None, "Don't run gtk-update-icon-cache"),
        ("no-compile-schemas", None, "Don't compile gsettings schemas"),
    ]

    def __init__(self, *args, **kwargs):
        self.no_update_icon_cache = False
        self.no_compile_schemas = False
        distutils.dist.Distribution.__init__(self, *args, **kwargs)


distutils.core.setup(
    name="virt-manager",
    version=BuildConfig.version,
    author="Cole Robinson",
    author_email="virt-tools-list@redhat.com",
    url="http://virt-manager.org",
    license="GPLv2+",

    # These wrappers are generated in our custom build command
    scripts=([
        "build/virt-manager",
        "build/virt-clone",
        "build/virt-install",
        "build/virt-convert",
        "build/virt-xml"]),

    data_files=[
        ("share/virt-manager/", [
            "virt-manager",
            "virt-install",
            "virt-clone",
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
            "man/virt-convert.1",
            "man/virt-xml.1"
        ]),

        ("share/virt-manager/virtManager", glob.glob("virtManager/*.py")),
        ("share/virt-manager/virtManager/details",
            glob.glob("virtManager/details/*.py")),
        ("share/virt-manager/virtManager/device",
            glob.glob("virtManager/device/*.py")),
        ("share/virt-manager/virtManager/lib",
            glob.glob("virtManager/lib/*.py")),
        ("share/virt-manager/virtManager/object",
            glob.glob("virtManager/object/*.py")),
        ("share/virt-manager/virtinst",
            glob.glob("virtinst/*.py") + glob.glob("virtinst/build.cfg")),
        ("share/virt-manager/virtinst/devices",
            glob.glob("virtinst/devices/*.py")),
        ("share/virt-manager/virtinst/domain",
            glob.glob("virtinst/domain/*.py")),
        ("share/virt-manager/virtinst/install",
            glob.glob("virtinst/install/*.py")),
        ("share/virt-manager/virtconv",
            glob.glob("virtconv/*.py")),
    ],

    cmdclass={
        'build': my_build,
        'build_i18n': my_build_i18n,

        'sdist': my_sdist,
        'install': my_install,
        'install_data': my_install_data,
        'install_egg_info': my_egg_info,

        'configure': configure,

        'pylint': CheckPylint,
        'rpm': my_rpm,
        'test': TestCommand,
        'test_ui': TestUI,
        'test_urls': TestURLFetch,
        'test_initrd_inject': TestInitrdInject,
        'test_dist': TestDist,
    },

    distclass=VMMDistribution,
)

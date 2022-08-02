#!/usr/bin/env python3
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.


import sys
if sys.version_info.major < 3:
    print("virt-manager is python3 only. Run this as ./setup.py")
    sys.exit(1)

import glob
import importlib.util
import os
from pathlib import Path
import shutil
import sysconfig
import subprocess

import setuptools
import setuptools.command.install
import setuptools.command.install_egg_info


# distutils will be deprecated in python 3.12 in favor of setuptools,
# but as of this writing there's standard no setuptools way to extend the
# 'build' commands which are the only standard commands we trigger.
# https://github.com/pypa/setuptools/issues/2591
#
# Newer setuptools will transparently support 'import distutils' though.
# That can be overridden with SETUPTOOLS_USE_DISTUTILS env variable
import distutils.command.build  # pylint: disable=wrong-import-order


SYSPREFIX = sysconfig.get_config_var("prefix")


def _import_buildconfig():
    # A bit of crazyness to import the buildconfig file without importing
    # the rest of virtinst, so the build process doesn't require all the
    # runtime deps to be installed
    spec = importlib.util.spec_from_file_location(
            'buildconfig', 'virtinst/buildconfig.py')
    buildconfig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(buildconfig)
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
    ("share/metainfo", ["data/virt-manager.appdata.xml.in"]),
]


class my_build_i18n(setuptools.Command):
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
        po_dir = "po"
        if self.merge_po:
            pot_file = os.path.join("po", "virt-manager.pot")
            for po_file in glob.glob("%s/*.po" % po_dir):
                cmd = ["msgmerge", "--previous", "-o", po_file, po_file, pot_file]
                self.spawn(cmd)

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

        # Merge .in with translations using gettext
        for (file_set, switch) in [(_appdata_files, "--xml"),
                                   (_desktop_files, "--desktop")]:
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
                    cmd = ["msgfmt", switch, "--template", f, "-d", po_dir,
                           "-o", file_merged]
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
    def _make_bin_wrappers(self):
        template = """#!/usr/bin/env python3

import os
import sys
sys.path.insert(0, "%(sharepath)s")
from %(pkgname)s import %(filename)s

%(filename)s.runcli()
"""
        if not os.path.exists("build"):
            os.mkdir("build")
        sharepath = os.path.join(BuildConfig.prefix, "share", "virt-manager")

        def make_script(pkgname, filename, toolname):
            assert os.path.exists(pkgname + "/" + filename + ".py")
            content = template % {
                "sharepath": sharepath,
                "pkgname": pkgname,
                "filename": filename}

            newpath = os.path.abspath(os.path.join("build", toolname))
            print("Generating %s" % newpath)
            open(newpath, "w").write(content)

        make_script("virtinst", "virtinstall", "virt-install")
        make_script("virtinst", "virtclone", "virt-clone")
        make_script("virtinst", "virtxml", "virt-xml")
        make_script("virtManager", "virtmanager", "virt-manager")


    def _make_man_pages(self):
        rstbin = shutil.which("rst2man")
        if not rstbin:
            rstbin = shutil.which("rst2man.py")
        if not rstbin:
            sys.exit("Didn't find rst2man or rst2man.py")

        for path in glob.glob("man/*.rst"):
            base = os.path.basename(path)
            appname = os.path.splitext(base)[0]
            newpath = os.path.join(os.path.dirname(path),
                                   appname + ".1")

            print("Generating %s" % newpath)
            out = subprocess.check_output([rstbin, "--strict", path])
            open(newpath, "wb").write(out)

            self.distribution.data_files.append(
                ('share/man/man1', (newpath,)))

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
        scripts = ["virt-install", "virt-clone", "virt-xml"]
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


class my_egg_info(setuptools.command.install_egg_info.install_egg_info):
    """
    Disable egg_info installation, seems pointless for a non-library
    """
    def run(self):
        pass


class my_install(setuptools.command.install.install):
    """
    Error if we weren't 'configure'd with the correct install prefix
    """
    def finalize_options(self):
        if self.prefix is None:
            if BuildConfig.prefix != SYSPREFIX:
                print("Using configured prefix=%s instead of SYSPREFIX=%s" % (
                    BuildConfig.prefix, SYSPREFIX))
                self.prefix = BuildConfig.prefix
            else:
                print("Using SYSPREFIX=%s" % SYSPREFIX)
                self.prefix = SYSPREFIX

        elif self.prefix != BuildConfig.prefix:
            print("Install prefix=%s doesn't match configure prefix=%s\n"
                  "Pass matching --prefix to 'setup.py configure'" %
                  (self.prefix, BuildConfig.prefix))
            sys.exit(1)

        setuptools.command.install.install.finalize_options(self)

    def run(self):
        setuptools.command.install.install.run(self)

        if not self.distribution.no_update_icon_cache:
            print("running gtk-update-icon-cache")
            icon_path = os.path.join(self.install_data, "share/icons/hicolor")
            self.spawn(["gtk-update-icon-cache", "-q", "-t", icon_path])

        if not self.distribution.no_compile_schemas:
            print("compiling gsettings schemas")
            gschema_install = os.path.join(self.install_data,
                "share/glib-2.0/schemas")
            self.spawn(["glib-compile-schemas", gschema_install])


###################
# Custom commands #
###################

class my_rpm(setuptools.Command):
    user_options = []
    description = "Build RPMs and output to the source directory."

    def initialize_options(self):
        pass
    def finalize_options(self):
        pass

    def run(self):
        self.run_command('sdist')
        srcdir = os.path.dirname(__file__)
        cmd = [
            "rpmbuild", "-ta",
            "--define", "_rpmdir %s" % srcdir,
            "--define", "_srcrpmdir %s" % srcdir,
            "--define", "_specdir /tmp",
            "dist/virt-manager-%s.tar.gz" % BuildConfig.version,
        ]
        subprocess.check_call(cmd)


class configure(setuptools.Command):
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
        self.prefix = SYSPREFIX
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


class TestCommand(setuptools.Command):
    user_options = []
    description = "DEPRECATED: Use `pytest`. See CONTRIBUTING.md"
    def finalize_options(self):
        pass
    def initialize_options(self):
        pass
    def run(self):
        sys.exit("ERROR: `test` is deprecated. Call `pytest` instead. "
                 "See CONTRIBUTING.md for more info.")


class CheckPylint(setuptools.Command):
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

        lintfiles = [
            # Put this first so pylint learns what Gtk version we
            # want to lint against
            "virtManager/virtmanager.py",
            "setup.py",
            "tests",
            "virtinst",
            "virtManager"]

        spellfiles = lintfiles[:]
        spellfiles += list(glob.glob("*.md"))
        spellfiles += list(glob.glob("man/*.rst"))
        spellfiles += ["data/virt-manager.appdata.xml.in",
                       "data/virt-manager.desktop.in",
                       "data/org.virt-manager.virt-manager.gschema.xml",
                       "virt-manager.spec"]
        spellfiles.remove("NEWS.md")

        try:
            import codespell_lib
            # pylint: disable=protected-access
            print("running codespell")
            codespell_lib._codespell.main(
                '-I', 'tests/data/codespell_dict.txt',
                '--skip', '*.pyc,*.iso,*.xml', *spellfiles)
        except ImportError:
            print("codespell is not installed. skipping...")
        except Exception as e:
            print("Error running codespell: %s" % e)

        output_format = sys.stdout.isatty() and "colorized" or "text"

        print("running pycodestyle")
        style_guide = pycodestyle.StyleGuide(
            config_file='setup.cfg',
            format="pylint",
            paths=lintfiles,
        )
        report = style_guide.check_files()
        if style_guide.options.count:
            sys.stderr.write(str(report.total_errors) + '\n')

        print("running pylint")
        pylint_opts = [
            "--rcfile", ".pylintrc",
            "--output-format=%s" % output_format,
        ]
        if self.jobs:
            pylint_opts += ["--jobs=%d" % self.jobs]

        pylint.lint.Run(lintfiles + pylint_opts)


class VMMDistribution(setuptools.dist.Distribution):
    global_options = setuptools.dist.Distribution.global_options + [
        ("no-update-icon-cache", None, "Don't run gtk-update-icon-cache"),
        ("no-compile-schemas", None, "Don't compile gsettings schemas"),
    ]

    def __init__(self, *args, **kwargs):
        self.no_update_icon_cache = False
        self.no_compile_schemas = False
        setuptools.dist.Distribution.__init__(self, *args, **kwargs)


class ExtractMessages(setuptools.Command):
    user_options = [
    ]
    description = "Extract the translation messages"

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        bug_address = "https://github.com/virt-manager/virt-manager/issues"
        potfile = "po/virt-manager.pot"
        xgettext_args = [
            "xgettext",
            "--add-comments=translators",
            "--msgid-bugs-address=" + bug_address,
            "--package-name=virt-manager",
            "--output=" + potfile,
            "--sort-by-file",
            "--join-existing",
        ]

        # Truncate .pot file to ensure it exists
        open(potfile, "w").write("")

        # First extract the messages from the AppStream sources,
        # creating the template
        appdata_files = [f for sublist in _appdata_files for f in sublist[1]]
        cmd = xgettext_args + appdata_files
        self.spawn(cmd)

        # Extract the messages from the desktop files
        desktop_files = [f for sublist in _desktop_files for f in sublist[1]]
        cmd = xgettext_args + ["--language=Desktop"] + desktop_files
        self.spawn(cmd)

        # Extract the messages from the Python sources
        py_sources = list(Path("virtManager").rglob("*.py"))
        py_sources += list(Path("virtinst").rglob("*.py"))
        py_sources = [str(src) for src in py_sources]
        cmd = xgettext_args + ["--language=Python"] + py_sources
        self.spawn(cmd)

        # Extract the messages from the Glade UI files
        ui_files = list(Path(".").rglob("*.ui"))
        ui_files = [str(src) for src in ui_files]
        cmd = xgettext_args + ["--language=Glade"] + ui_files
        self.spawn(cmd)


setuptools.setup(
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
        "build/virt-xml"]),

    data_files=[
        ("share/glib-2.0/schemas",
         ["data/org.virt-manager.virt-manager.gschema.xml"]),
        ("share/virt-manager/ui", glob.glob("ui/*.ui")),

        ("share/man/man1", [
            "man/virt-manager.1",
            "man/virt-install.1",
            "man/virt-clone.1",
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
    ],

    # stop setuptools 61+ thinking we want to include everything automatically
    py_modules=[],

    cmdclass={
        'build': my_build,
        'build_i18n': my_build_i18n,

        'install': my_install,
        'install_egg_info': my_egg_info,

        'configure': configure,

        'pylint': CheckPylint,
        'rpm': my_rpm,
        'test': TestCommand,

        'extract_messages': ExtractMessages,
    },

    distclass=VMMDistribution,
    packages=[],
)

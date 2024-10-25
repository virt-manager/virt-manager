#!/usr/bin/env python3
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.


import sys
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
try:
    # Use the setuptools build command with setuptools >= 62.4.0
    import setuptools.command.build
    BUILD_COMMAND_CLASS = setuptools.command.build.build
except ImportError:
    # Use distutils with an older setuptools version
    #
    # Newer setuptools will transparently support 'import distutils' though.
    # That can be overridden with SETUPTOOLS_USE_DISTUTILS env variable
    import distutils.command.build  # pylint: disable=wrong-import-order,deprecated-module,import-error
    BUILD_COMMAND_CLASS = distutils.command.build.build  # pylint: disable=c-extension-no-member


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
        # pylint: disable=access-member-before-definition
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

        super().finalize_options()

    def run(self):
        super().run()

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
        if self.jobs is not None:
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
        if self.jobs is not None:
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
        super().__init__(*args, **kwargs)


setuptools.setup(
    name="virt-manager",
    version=BuildConfig.version,
    url="https://virt-manager.org",
    license="GPLv2+",

    data_files=[
        ("share/virt-manager/virtinst",
            glob.glob("virtinst/build.cfg")),
    ],

    # stop setuptools 61+ thinking we want to include everything automatically
    py_modules=[],

    cmdclass={
        'install': my_install,
        'install_egg_info': my_egg_info,

        'configure': configure,

        'pylint': CheckPylint,
        'rpm': my_rpm,
        'test': TestCommand,
    },

    distclass=VMMDistribution,
    packages=[],
)

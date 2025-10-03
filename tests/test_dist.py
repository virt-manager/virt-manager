# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import glob
import subprocess
import xml.etree.ElementTree as ET


def test_validate_po_files():
    """
    Validate that po translations don't mess up python format strings,
    which has broken the app in the past:
    https://bugzilla.redhat.com/show_bug.cgi?id=1350185
    https://bugzilla.redhat.com/show_bug.cgi?id=1433800
    """
    failures = []
    for pofile in glob.glob("po/*.po"):
        proc = subprocess.Popen(
            ["msgfmt", "--output-file=/dev/null", "--check", pofile],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        ignore, stderr = proc.communicate()
        if proc.wait():
            failures.append("%s: %s" % (pofile, stderr))

    if not failures:
        return

    msg = "The following po files have errors:\n"
    msg += "\n".join(failures)
    raise AssertionError(msg)


def test_validate_pot_strings():
    """
    Validate that xgettext via don't print any warnings.
    """
    potfile = "po/virt-manager.pot"
    origpot = open(potfile).read()
    try:
        subprocess.run(["meson", "setup", "build"], check=True)
        out = subprocess.check_output(
            ["meson", "compile", "-C", "build", "virt-manager-pot"], stderr=subprocess.STDOUT
        )
        warnings = [line for line in out.decode("utf-8").splitlines() if "warning:" in line]
        warnings = [warning for warning in warnings if "a fallback ITS rule file" not in warning]
        if warnings:
            raise AssertionError("xgettext has warnings:\n\n%s" % "\n".join(warnings))
    finally:
        open(potfile, "w").write(origpot)


def test_ui_minimum_version():
    """
    Ensure all glade XML files don't _require_ UI bits later than
    our minimum supported version
    """
    # Minimum dep is 3.22 to fix popups on some wayland window managers.
    # 3.22 is from Sep 2016, so coupled with python3 deps this seems fine
    # to enforce
    minimum_version_major = 3
    minimum_version_minor = 22
    minimum_version_str = "%s.%s" % (minimum_version_major, minimum_version_minor)

    failures = []
    for filename in glob.glob("ui/*.ui"):
        required_version = None
        for line in open(filename).readlines():
            # This is much faster than XML parsing the whole file
            if not line.strip().startswith("<requires "):
                continue

            req = ET.fromstring(line)
            if req.tag != "requires" or req.attrib.get("lib") != "gtk+":
                continue
            required_version = req.attrib["version"]

        if required_version is None:
            raise AssertionError("ui file=%s doesn't have a <requires> tag for gtk+")

        if (
            int(required_version.split(".")[0]) != minimum_version_major
            or int(required_version.split(".")[1]) != minimum_version_minor
        ):
            failures.append((filename, required_version))

    if not failures:
        return

    err = "The following files should require version of gtk-%s:\n" % minimum_version_str
    err += "\n".join([("%s version=%s" % tup) for tup in failures])
    raise AssertionError(err)


def test_ui_translatable_atknames():
    """
    We only use accessible names for uitests, they shouldn't be
    marked as translatable
    """
    failures = []
    atkstr = "AtkObject::accessible-name"
    for filename in glob.glob("ui/*.ui"):
        for line in open(filename).readlines():
            if atkstr not in line:
                continue
            if "translatable=" in line:
                failures.append(filename)
                break

    if not failures:
        return
    err = "Some files incorrectly have translatable ATK names.\n"
    err += "Run this command to fix:\n\n"
    err += """sed -i -e 's/%s" translatable="yes"/%s"/g' """ % (atkstr, atkstr)
    err += " ".join(failures)
    raise AssertionError(err)


def test_appstream_validate():
    subprocess.check_call(
        ["appstream-util", "validate", "data/org.virt_manager.virt-manager.metainfo.xml.in"]
    )

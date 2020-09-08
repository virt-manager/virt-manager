# Copyright (C) 2013, 2015 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import tempfile

from tests import utils

from virtinst import Cloner


CLI_XMLDIR = utils.DATADIR + "/cli/virtclone/"


def test_clone_unmanaged():
    """
    Test that unmanaged storage duplication via the clone wizard
    actually copies data
    """
    xmlpath = CLI_XMLDIR + "clone-disk.xml"
    conn = utils.URIs.open_testdefault_cached()
    xml = open(xmlpath).read()

    tmp1 = tempfile.NamedTemporaryFile()
    tmp2 = tempfile.NamedTemporaryFile()
    inp1 = os.path.abspath(__file__)
    inp2 = xmlpath

    xml = xml.replace("/tmp/__virtinst_cli_exist1.img", inp1)
    xml = xml.replace("/tmp/__virtinst_cli_exist2.img", inp2)
    cloner = Cloner(conn, src_xml=xml)

    diskinfos = cloner.get_nonshare_diskinfos()
    assert len(diskinfos) == 2
    diskinfos[0].set_new_path(tmp1.name, False)
    diskinfos[1].set_new_path(tmp2.name, False)

    cloner.prepare()
    cloner.start_duplicate(None)

    assert open(tmp1.name).read() == open(inp1).read()
    assert open(tmp2.name).read() == open(inp2).read()


def test_generate_name():
    conn = utils.URIs.open_testdriver_cached()
    def _g(n):
        return Cloner.generate_clone_name(conn, n)

    assert _g("test") == "test-clone1"
    assert _g("test-clone-simple") == "test-clone-simple-clone"
    assert _g("test-clone-simple-clone") == "test-clone-simple-clone1"
    assert _g("test-clone-simple-clone5") == "test-clone-simple-clone6"

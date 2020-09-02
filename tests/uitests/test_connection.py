# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from tests.uitests import utils as uiutils


class UITestConnection(uiutils.UITestCase):
    """
    UI tests for various connection.py related bits
    """

    ##############
    # Test cases #
    ##############

    def testConnectionBlacklist(self):
        self.app.open(
            extra_opts=["--test-options=object-blacklist=test-many-devices"])
        manager = self.app.topwin

        def _delete_vm(vmname):
            cell = manager.find(vmname, "table cell")
            cell.click()
            cell.click(button=3)
            menu = self.app.root.find("vm-action-menu")
            menu.find("Delete", "menu item").click()
            delete = self.app.root.find_fuzzy("Delete", "frame")
            delete.find("Delete associated", "check box").click()
            delete.find("Delete", "push button").click()
            uiutils.check(lambda: cell.dead)
            uiutils.check(lambda: manager.active)

        uiutils.check(
                lambda: "test-many-devices" not in self.app.topwin.fmt_nodes())
        _delete_vm("test-arm-kernel")
        _delete_vm("test alternate")
        _delete_vm("test-clone-simple")
        self.sleep(.5)
        uiutils.check(
                lambda: "test-many-devices" not in self.app.topwin.fmt_nodes())

    def testConnectionConnCrash(self):
        self.app.open(
            extra_opts=["--test-options=conn-crash"])
        manager = self.app.topwin

        self.sleep(1)
        manager.find(r"^test testdriver.xml - Not Connected", "table cell")
        uiutils.check(lambda: manager.active)

    def testConnectionFakeEvents(self):
        self.app.open(
            extra_opts=["--test-options=fake-nodedev-event=computer",
                        "--test-options=fake-agent-event=test-many-devices"])
        manager = self.app.topwin
        self.sleep(2.5)
        uiutils.check(lambda: manager.active)
